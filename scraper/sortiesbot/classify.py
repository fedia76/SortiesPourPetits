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

1. **JSON-LD** — le site déclare lui-même ce qu'il publie. Un seul spectacle
   nommé, c'est une sortie ; trois titres différents ou un `ItemList`, c'est
   une liste. C'est le seul signal qu'on puisse qualifier de certain.
2. **OpenGraph** — `og:type: event`, rare mais sans ambiguïté quand il est là.

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
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .harvest import _is_event, _ld_blocks, _walk, links_of

#: Les trois réponses possibles. `INCONNU` est une réponse, pas une panne.
AGENDA = "agenda"
SORTIE = "sortie"
INCONNU = "inconnu"

#: L'en-tête d'une page, où vivent les métadonnées. Au-delà, on est dans le
#: corps, et un `og:` qui s'y trouve est du texte, pas une déclaration.
HEAD_CHARS = 8192

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


# ------------------------------------------------------- 1. ce que le site déclare


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


# ------------------------------------------------------------ 2. les métadonnées


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
