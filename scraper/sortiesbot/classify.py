"""Ce qu'est une page, constaté sur son HTML : agenda, sortie, ou indécis.

Cette brique-ci ne décide encore rien. Elle **observe** : le pipeline continue
de suivre le classement du modèle, et ce module dit, en parallèle, ce qu'il
aurait répondu. C'est ce qui permet de mesurer avant de remplacer, plutôt que
de troquer un jugement qui marche contre un jugement qu'on espère bon.

Le principe est celui du mode « site » : la forme d'une page n'a pas à être
déclarée, elle se constate. Une page qui présente **une** sortie et une page
qui en **liste** vingt ne se ressemblent pas dans leur HTML, et c'est gratuit
à regarder — là où le faire lire à un modèle coûte à chaque page.

La cascade va du plus certain au plus flou, et s'arrête au premier signal qui
tranche :

1. **L'URL** — `?page=2`, `?search=`, `?filter[]=` : une page paginée ou
   filtrée *est* une liste de résultats. Ce n'est pas une heuristique sur le
   gabarit d'un site, c'est la sémantique d'un paramètre de requête.
2. **JSON-LD** — le site déclare lui-même ce qu'il publie. Un seul spectacle
   nommé, c'est une sortie ; trois titres différents ou un `ItemList`, c'est
   une liste. C'est le signal le plus rentable des trois.
3. **OpenGraph** — `og:type: event`, rare mais sans ambiguïté quand il est là.

Et quand rien ne tranche, la réponse est `INCONNU` — ce n'est pas un échec.
L'orchestrateur sait déjà quoi faire d'une page dont on ignore la nature : il
la traite en agenda, et son filet la relit comme une sortie si le
dépouillement ne donne rien. Se tromper dans ce sens coûte un appel de
sélection ; se tromper dans l'autre coûte tous les liens de l'agenda. D'où le
biais assumé : **dans le doute, agenda.**

Un piège, et il vient d'ici : `harvest.json_ld_dates` rappelle que beaucoup de
sites publient « un `schema.org/Event` par représentation ». Compter les
objets `Event` classerait donc en agenda toute pièce jouée douze fois. On
compte les **titres distincts**, pas les objets.

## Pourquoi il n'y a pas de troisième signal

Une première version tranchait, faute de mieux, sur le **nombre de liens
exploitables** : beaucoup de liens pour une liste, peu pour une fiche. Vingt-sept
pages réelles ont suffi à l'enterrer. Les deux populations se recouvrent de bout
en bout :

    agendas, liens dépouillés        10   33   55  65  78  90
    fiches tirées d'un agenda        10 10 10 10 11  21  38  42  61

Aucun seuil ne les sépare, et deux observations disent pourquoi. Sur
`parismomes.fr`, huit pages du même site — agendas et fiches mêlés — rendent
toutes **exactement dix liens** : c'est le gabarit du site qu'on mesurait, pas
la nature de la page. Sur `sortiraparis.com`, une fiche unique en rend deux
cents, c'est-à-dire le plafond de `links_of` : le compteur est saturé et ne
mesure plus rien.

Le compte reste **relevé** — il part au registre, où il servira le jour où on
cherchera un vrai signal structurel (des blocs répétés portant chacun un lien
*et* une date, par exemple). Il n'a simplement plus voix au chapitre.

## Pourquoi le chemin d'une URL ne dit rien non plus

Le réflexe suivant est de lire le chemin : `/agenda/`, `/sorties/`,
`/que-faire/`. Les mêmes vingt-sept pages l'interdisent — deux domaines sur
sept servent agendas et fiches sous le même segment :

    iledefrance.kidiklik.fr/articles/   → un agenda ET des fiches
    parismomes.fr/ecouter-voir/         → un agenda ET des fiches

Ce serait réapprendre le gabarit de chaque site, et ne rien savoir du site
qu'on n'a jamais vu — c'est-à-dire du cas d'usage. Seuls les **paramètres de
requête** sont retenus : eux ne décrivent pas un site, ils décrivent une
opération.

## Le condensé

`digest()` prépare la carte d'identité d'une page — URL, titre, `h1`, début du
texte, textes des liens et surtout **combien d'entre eux voisinent une date**.
C'est ce qu'on soumet à un modèle quand les signaux certains se taisent, et
c'est ce qu'on archive pour, plus tard, entraîner de quoi s'en passer.

La densité de dates est le candidat sérieux au signal structurel qui manque :
un agenda mène à des choses **datées**. On la relève dès maintenant, sans lui
donner voix au chapitre — c'est la leçon du comptage de liens.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .harvest import Link, _is_event, _ld_blocks, _soup, _walk, links_of

#: Les trois réponses possibles. `INCONNU` est une réponse, pas une panne.
AGENDA = "agenda"
SORTIE = "sortie"
INCONNU = "inconnu"

#: L'en-tête d'une page, où vivent les métadonnées. Au-delà, on est dans le
#: corps, et un `og:` qui s'y trouve est du texte, pas une déclaration.
HEAD_CHARS = 8192

#: Paramètres de requête qui trahissent une liste de résultats. Une page qui
#: se pagine, se cherche ou se filtre n'est pas une fiche — c'est vrai partout,
#: quel que soit le site, et ça ne s'apprend pas d'un gabarit.
_LIST_QUERY = re.compile(
    r"(^|&)(page|paged|pagenum|p|offset|start|search|s|q|query|recherche|"
    r"filter|filtre|filters|tag|tags|categorie|category|cat|tri|sort|"
    r"date_debut|date_fin|periode)(\[\]?\d*\]?)?=",
    re.I,
)

#: Segments de chemin qui paginent, quel que soit le site : /page/2, /p/3.
_LIST_PATH = re.compile(r"/(page|p)/\d+/?$", re.I)

#: Types JSON-LD qui annoncent une liste plutôt qu'un événement.
_LIST_TYPES = re.compile(r"ItemList|CollectionPage|SearchResultsPage", re.I)

#: Au-delà, des titres distincts déclarés en JSON-LD font une liste. Deux ne
#: suffisent pas : une page de spectacle annonce souvent la séance scolaire à
#: côté de la séance tout public, sous deux noms.
LIST_NAMES = 3


@dataclass(frozen=True)
class Verdict:
    """Ce que la page est, et sur quoi on s'est fondé pour le dire."""

    kind: str
    #: Le signal qui a tranché — pour savoir lequel se trompe, le jour venu.
    signal: str
    #: Ce qu'on a constaté, en une ligne lisible dans le journal.
    detail: str
    #: `certain` : le site le déclare. `probable` : on l'infère de sa forme.
    confidence: str

    def agrees_with(self, announced: str) -> bool | None:
        """Vrai, faux, ou `None` s'il n'y a rien à comparer."""
        if not announced or self.kind == INCONNU:
            return None
        return self.kind == announced

    def as_dict(self) -> dict[str, str]:
        return {
            "verdict": self.kind,
            "signal": self.signal,
            "detail": self.detail,
            "confidence": self.confidence,
        }


def classify(html: str, url: str, *, links: int | None = None) -> Verdict:
    """Dit ce qu'est cette page, sans jamais appeler de modèle.

    `links` évite un second passage sur le HTML quand l'appelant a déjà
    dépouillé la page ; sinon il est calculé ici.
    """
    verdict = _by_url(url)
    if verdict is not None:
        return verdict

    verdict = _by_json_ld(html)
    if verdict is not None:
        return verdict

    verdict = _by_opengraph(html)
    if verdict is not None:
        return verdict

    # Rien de déclaré : on ne devine pas. Le compte de liens accompagne le
    # verdict pour finir au registre, mais il ne le décide pas — voir l'en-tête.
    count = links if links is not None else len(links_of(html, url))
    return Verdict(INCONNU, "aucun", f"rien de déclaré ({count} liens relevés)", "faible")


# --------------------------------------------------------- 1. ce que l'URL dit


def _by_url(url: str) -> Verdict | None:
    """Une page paginée, cherchée ou filtrée est une liste. Sans exception.

    Rarement utile — pas une des vingt-sept premières pages observées ne
    portait le moindre paramètre, un moteur ne remontant pas de `?page=3`.
    Mais quand ça tire, c'est juste, et ça ne coûte rien.
    """
    parts = urlsplit(url)
    if _LIST_QUERY.search(parts.query or ""):
        return Verdict(AGENDA, "url", f"paramètres de liste ({parts.query[:60]})", "certain")
    if _LIST_PATH.search(parts.path or ""):
        return Verdict(AGENDA, "url", f"chemin paginé ({parts.path[-30:]})", "certain")
    return None


# ------------------------------------------------------- 2. ce que le site déclare


def _by_json_ld(html: str) -> Verdict | None:
    """Le signal le plus sûr : la page dit elle-même ce qu'elle publie."""
    names: set[str] = set()
    events = 0
    listed = False

    for block in _ld_blocks(html):
        for node in _walk(block):
            if _declares_list(node):
                listed = True
            if not _is_event(node):
                continue
            events += 1
            name = node.get("name")
            if isinstance(name, str) and name.strip():
                names.add(_fold(name))

    if listed and (events > 1 or len(names) > 1):
        return Verdict(
            AGENDA, "json-ld", f"liste déclarée, {len(names)} titre(s) distinct(s)", "certain"
        )
    if len(names) >= LIST_NAMES:
        return Verdict(
            AGENDA, "json-ld", f"{len(names)} événements distincts déclarés", "certain"
        )
    if len(names) == 1:
        # Une pièce jouée douze fois publie douze `Event` du même nom : c'est
        # un calendrier, pas un agenda.
        detail = f"un seul événement déclaré ({events} représentation(s))"
        return Verdict(SORTIE, "json-ld", detail, "certain")
    if events == 1:
        return Verdict(SORTIE, "json-ld", "un seul événement déclaré, sans titre", "probable")
    return None


def _declares_list(node: dict) -> bool:
    types = node.get("@type")
    types = types if isinstance(types, list) else [types]
    return any(isinstance(t, str) and _LIST_TYPES.search(t) for t in types)


# ------------------------------------------------------------ 3. les métadonnées


#: `<meta property="og:type" content="…">`, cherché dans l'en-tête seule. Une
#: expression régulière plutôt qu'un arbre : monter tout le document en mémoire
#: pour une balise que presque aucun site ne pose serait payer cher un signal
#: qui, sur nos vingt-sept premières pages, n'a jamais servi une seule fois.
_OG_TYPE = re.compile(
    r"""<meta[^>]+property\s*=\s*['"]og:type['"][^>]+content\s*=\s*['"]([^'"]+)['"]""",
    re.I,
)


def _by_opengraph(html: str) -> Verdict | None:
    """`og:type: event` — rare, mais sans ambiguïté quand il est là."""
    match = _OG_TYPE.search(html[:HEAD_CHARS])
    value = match.group(1).strip().lower() if match else ""
    if value in ("event", "article:event", "activity"):
        return Verdict(SORTIE, "opengraph", f"og:type = {value}", "probable")
    return None


def _fold(text: str) -> str:
    """Compare des titres sans se soucier de la casse ni des accents."""
    stripped = unicodedata.normalize("NFKD", text.strip().lower())
    return " ".join("".join(c for c in stripped if not unicodedata.combining(c)).split())


# ═══════════════════════════════════════════════ le condensé d'une page

#: Ce qui ressemble à une date dans le voisinage d'un lien. On ne cherche pas à
#: la lire — `schedule.py` fait ça — seulement à constater qu'il y en a une.
_DATE = re.compile(
    r"\b(\d{1,2}[/.-]\d{1,2}([/.-]\d{2,4})?"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(lun|mar|mer|jeu|ven|sam|dim)[a-z]*\.?\s+\d{1,2}"
    r"|\d{1,2}\s*(er)?\s*(janv|f[ée]vr|mars|avr|mai|juin|juil|ao[uû]t|sept|"
    r"oct|nov|d[ée]c)[a-z]*\.?)\b",
    re.I,
)

#: De quoi reconnaître le ton d'une page sans la lire en entier.
OPENING_CHARS = 300

#: Bandeaux de consentement, reconnus à leur identifiant ou à leur classe. Ils
#: ne sont ni `nav` ni `footer`, donc `page_text` les laisse passer — et dans
#: trois cents caractères, quarante de « nous utilisons des cookies » sont
#: quarante de perdus. Nettoyage propre au condensé : ce que reçoit
#: l'extraction ne change pas.
_CONSENT = re.compile(
    r"cookie|consent|rgpd|gdpr|tarteaucitron|didomi|axeptio|orejime|cmp", re.I
)
#: Au-delà, les textes de liens coûtent sans rien apprendre de plus.
DIGEST_LINKS = 20


@dataclass(frozen=True)
class Digest:
    """La carte d'identité d'une page : ce qu'on soumet quand on ne sait pas.

    Assez pour trancher, assez peu pour ne rien coûter — quelques centaines de
    jetons là où la page entière en ferait des milliers. Et c'est ce qu'on
    archive : le jour où l'on voudra un classifieur local, le corpus sera là,
    déjà réduit aux traits qui comptent.
    """

    url: str
    title: str
    heading: str
    opening: str
    #: Nombre de liens exploitables, avant troncature.
    links: int
    #: Combien de leurs voisinages portent une date. Un agenda mène à des
    #: choses datées : c'est le trait le plus prometteur du lot.
    dated: int
    texts: list[str] = field(default_factory=list)

    def as_prompt(self) -> str:
        """Le condensé tel qu'il part au modèle."""
        liens = "\n".join(f"  · {t}" for t in self.texts) or "  (aucun)"
        return (
            f"URL : {self.url}\n"
            f"Titre : {self.title or '(sans titre)'}\n"
            f"Titre principal : {self.heading or '(aucun h1)'}\n"
            f"Début du texte : {self.opening or '(vide)'}\n"
            f"Liens exploitables : {self.links}, dont {self.dated} "
            f"voisinent une date.\n"
            f"Textes des {len(self.texts)} premiers :\n{liens}"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "heading": self.heading,
            "opening": self.opening,
            "links": self.links,
            "dated": self.dated,
            "texts": self.texts,
        }


def digest(html: str, url: str, links: list[Link] | None = None) -> Digest:
    """Réduit une page à ce qui permet d'en juger la nature.

    Les liens sont repris de l'appelant quand il les a — le dépouillement les
    a déjà extraits, les recalculer serait payer deux fois la même analyse.
    """
    found = links if links is not None else links_of(html, url)
    soup = _soup(html)

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.find("h1")
    heading = " ".join(h1.get_text(" ", strip=True).split()) if h1 else ""

    # La tête d'abord, sinon le `<title>` ouvre le texte et le répète.
    for tag in soup(["head", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    for tag in soup.find_all(attrs={"id": _CONSENT}) + soup.find_all(attrs={"class": _CONSENT}):
        tag.decompose()
    opening = " ".join(soup.get_text(" ", strip=True).split())[:OPENING_CHARS]

    return Digest(
        url=url,
        title=" ".join(title.split())[:150],
        heading=heading[:150],
        opening=opening,
        links=len(found),
        dated=sum(1 for link in found if _DATE.search(link.context or "")),
        texts=[link.text[:80] for link in found[:DIGEST_LINKS]],
    )
