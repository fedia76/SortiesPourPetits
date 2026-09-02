"""Étage 7 — remonter de la page lue à la page qui fait autorité.

Une recherche remonte surtout des **agrégateurs** : kidiklik, citizenkid,
parismômes, familyinparis. C'est normal, ils sont bons à ça — ils indexent
tout et sortent en tête. Mais un atelier du musée Rodin n'est pas une
information de kidiklik : c'est une information du musée Rodin, que kidiklik
a republiée. Le parent qui clique veut les horaires à jour, la billetterie,
l'annulation du jour — donc la page du musée.

Cet étage ne change rien à ce qui a été lu. Il répond à une seule question,
posée une fois par fiche : **existe-t-il une page de l'organisateur, et
laquelle ?**

## La cascade, du certain au flou

Comme celle de `classify.py`, et pour la même raison : chaque signal gratuit
qui tranche est un appel payant qu'on ne fait pas.

| # | Signal | D'où il vient | Coût |
|---|---|---|---|
| 1 | **JSON-LD** — `Event.url`, `sameAs`, `offers.url` | le HTML déjà téléchargé | nul |
| 2 | **Domaine du lieu** — « Musée Rodin » ↔ `musee-rodin.fr` | les liens sortants | nul |
| 3 | **Texte du lien** — « site officiel », « réserver » | les liens sortants | nul |
| 4 | **Le moteur** — une requête Serper | le réseau | ~0,001 $ |

Les trois premiers lisent le HTML que le `Fetcher` garde déjà : ils ne coûtent
ni un octet de réseau ni un jeton. Le quatrième n'est atteint que lorsque la
page lue ne porte tout simplement pas le lien — et il se coupe par
configuration (`source_search: false`).

## La validation, qui n'est pas optionnelle

Aucun de ces quatre signaux ne prouve quoi que ce soit. Un lien « réserver »
peut mener à la page d'accueil d'une billetterie ; un résultat de moteur peut
être le bon site et la mauvaise saison. Une source fausse est **pire** qu'une
source absente : elle a l'air d'une réponse, le modérateur la croit, et le
parent atterrit sur un spectacle qui n'existe plus.

Donc la page candidate est **ouverte et lue** avant d'être retenue. Elle doit
parler de cette sortie : son titre, ou son lieu et une de ses dates. Ce qui ne
passe pas cette épreuve est journalisé et jeté — `SourceLink.found` n'est vrai
que si `checked` l'est.

Le contrôle est du Python sur du texte, donc gratuit ; le téléchargement passe
par le `Fetcher` du run, donc respecte `robots.txt` et le délai par hôte comme
partout ailleurs.

## La langue de la source

L'organisateur publie souvent en deux langues, et la cascade ramasse volontiers
son `/en/` — un `sameAs` anglais, un résultat de moteur. La page candidate est
donc échangée contre sa jumelle française quand le site en déclare une (voir
[`language.py`](../language.py)), **avant** la vérification : la page contrôlée
doit être celle qui sera publiée, et le contrôle ci-dessous porte justement sur
un titre et des dates écrits en français.

## Ce que cette brique ne fait pas

Elle ne demande **jamais une URL au modèle**. C'est la règle que la publication
applique déjà à la photo — « une URL de sa part est au mieux une devinette » —
et elle vaut ici plus encore : une URL inventée qui répond en 200 est
indétectable. Toute adresse qui sort d'ici a été lue dans un HTML ou rendue par
un moteur, jamais produite de mémoire.
"""

from __future__ import annotations

import re
import unicodedata

from ..harvest import (
    FetchError,
    Link,
    host_of,
    in_domains,
    json_ld_urls,
    outbound_links,
    page_text,
    same_site,
)
from ..language import french_version
from ..models import (
    SIGNAL_JSON_LD,
    SIGNAL_PAGE_LINK,
    SIGNAL_SEARCH,
    SIGNAL_VENUE_DOMAIN,
    Candidate,
    ExtractedEvent,
    SourceLink,
)
from ..providers.base import ProviderError
from ..providers.serper_client import SerperClient
from . import Stage
from .base import Brick, PageContent

#: Textes de lien qui annoncent la page de l'organisateur. Volontairement
#: courts et sans accents : ils sont cherchés dans un texte replié.
OFFICIAL_TEXT = re.compile(
    r"\b(site (officiel|internet|web|du lieu)|page officielle|site de l|"
    r"reserver|reservation|billetterie|billets|en savoir plus|plus d.infos?|"
    r"plus d.informations|infos? pratiques|toutes les infos|programme complet|"
    r"acceder au site|voir le site|lien vers)\b"
)

#: Mots qu'on retire d'un nom de lieu avant d'en chercher le domaine : ils sont
#: dans l'adresse de tout le monde ou dans celle de personne.
VENUE_NOISE = {
    "le", "la", "les", "l", "du", "de", "des", "d", "au", "aux", "et",
    "salle", "espace", "centre", "maison", "parc", "jardin", "square",
    "paris", "france", "ile", "saint", "sainte", "site", "www", "fr", "com",
}

#: En dessous, un fragment de nom de lieu est trop court pour reconnaître un
#: domaine sans se tromper : « art » se retrouve dans la moitié du web.
MIN_VENUE_TOKEN = 4

#: Résultats demandés au moteur. On ne cherche pas à ratisser : on cherche
#: l'organisateur, qui est en tête ou nulle part.
SEARCH_RESULTS = 5

#: Pages candidates ouvertes au plus, tous signaux confondus. Chacune est un
#: téléchargement et une seconde de politesse envers son hôte : au-delà, on
#: paie en temps ce qu'on ne trouvera pas.
MAX_CANDIDATES = 4

#: Caractères lus sur la page candidate pour la vérifier. Bien plus que ce que
#: l'extraction transmet au modèle : ici personne ne paie au caractère, et le
#: titre peut être loin dans un programme.
CHECK_CHARS = 20_000

#: Mots du titre à retrouver sur la page candidate, en proportion. Un titre est
#: souvent reformulé — « Atelier modelage » contre « Atelier de modelage en
#: famille » — donc on n'exige pas la phrase, on exige l'essentiel.
TITLE_MATCH_RATIO = 0.6

#: Un mot de titre plus court n'apporte rien à la comparaison.
MIN_TITLE_TOKEN = 4

#: Sans accents : la page candidate est comparée repliée (voir `fold`).
MOIS = (
    "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
    "aout", "septembre", "octobre", "novembre", "decembre",
)


def fold(text: str) -> str:
    """Replie un texte pour le comparer : sans casse, sans accents, sans ponctuation."""
    stripped = unicodedata.normalize("NFKD", (text or "").lower())
    plain = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def tokens(text: str, minimum: int) -> list[str]:
    """Les mots significatifs d'un texte replié, dédoublonnés dans l'ordre."""
    seen: dict[str, None] = {}
    for word in fold(text).split():
        if len(word) >= minimum and word not in VENUE_NOISE:
            seen.setdefault(word, None)
    return list(seen)


class Attribution(Brick):
    stage = Stage.ATTRIBUTE

    def __init__(self, ctx, engine: SerperClient | None = None) -> None:
        super().__init__(ctx)
        #: Le moteur, s'il y a une clé. `None` est un cas normal, pas une
        #: panne : les trois signaux gratuits tournent quand même.
        self.engine = engine

    def run(
        self, extracted: ExtractedEvent, candidate: Candidate, page: PageContent
    ) -> SourceLink:
        """Rend la page de l'organisateur, vérifiée. `SourceLink()` sinon.

        Jamais d'exception : une attribution qui échoue laisse la sortie partir
        avec la page lue, ce qui est exactement l'état d'avant cet étage.
        """
        with self.opened(url=page.url, title=extracted.title) as st:
            source = self._attribute(extracted, candidate, page)
            if source.found:
                st.produced(
                    f"source : {host_of(source.url)} [{source.signal}]",
                    signal=source.signal,
                    source_url=source.url,
                )
            else:
                st.produced(
                    source.detail or "aucune source distincte de la page lue",
                    signal="",
                )
            self.ctx.ledger.record(
                "attribute",
                url=page.url,
                stage=self.stage.value,
                title=extracted.title,
                venue=extracted.venue_name,
                aggregator=self._is_aggregator(page.url),
                source_url=source.url,
                signal=source.signal,
                detail=source.detail,
                checked=source.checked,
            )
            return source

    # ────────────────────────────────────────────────────────── la cascade

    def _attribute(
        self, extracted: ExtractedEvent, candidate: Candidate, page: PageContent
    ) -> SourceLink:
        """La cascade, et l'épreuve de vérité au bout. Voir l'en-tête du module.

        Les chercheurs **proposent**, ils ne décident pas : chacun rend les
        candidates qu'il voit, dans son ordre de confiance, et c'est la
        vérification qui tranche. C'est ce qui évite qu'un premier lien
        plausible mais faux fasse perdre le bon, qui était deux lignes plus bas.
        """
        if not self._is_aggregator(page.url):
            # La page lue est déjà celle de quelqu'un qui organise : il n'y a
            # rien à remonter, et chercher coûterait sans rien apprendre.
            self.log.event("attribution", url=page.url, status="page déjà à la source")
            return SourceLink(detail="la page lue est déjà celle de l'organisateur")

        try:
            html = self.ctx.fetcher.get_html(page.url)
        except FetchError as err:
            # Le HTML est en cache depuis la lecture : n'arrive que si le cache
            # a été vidé. Sans lui, les trois signaux gratuits sont muets.
            self.log.warn("attribution", f"page illisible : {err}", url=page.url)
            html = ""

        links = outbound_links(html, page.url) if html else []
        proposees: list[SourceLink] = []
        for finder in (self._by_json_ld, self._by_venue_domain, self._by_link_text):
            proposees.extend(finder(html, page.url, links, extracted))

        vues: set[str] = set()
        ouvertes = 0
        for proposee in proposees:
            if proposee.url in vues:
                continue
            vues.add(proposee.url)
            if ouvertes >= MAX_CANDIDATES:
                break
            ouvertes += 1
            checked = self._checked(proposee, extracted, page)
            if checked.found:
                return checked

        # Aucun signal gratuit n'a tenu : la page ne porte pas son organisateur.
        # C'est exactement le cas que le moteur sait traiter.
        return self._by_search(extracted, page)

    def _by_json_ld(
        self, html: str, page_url: str, links: list[Link], extracted: ExtractedEvent
    ) -> list[SourceLink]:
        """1. Ce que la page **déclare** — le signal le plus sûr et le plus rare.

        Un agrégateur qui remplit son `schema.org/Event` y met l'adresse
        canonique de la fiche, parce que c'est ce que Google Événements attend.
        Quand elle est là, elle est juste.
        """
        return [
            SourceLink(url=url, signal=SIGNAL_JSON_LD, detail="URL déclarée en JSON-LD")
            for url in json_ld_urls(html, page_url)
            if self._usable(url, page_url)
        ]

    def _by_venue_domain(
        self, html: str, page_url: str, links: list[Link], extracted: ExtractedEvent
    ) -> list[SourceLink]:
        """2. Le nom du lieu qu'on retrouve dans un domaine.

        « Musée Rodin » et `musee-rodin.fr` : la correspondance est gratuite et
        elle est forte, parce qu'elle croise deux sources indépendantes — ce que
        l'extraction a lu dans le texte, et ce que le HTML porte en lien.

        On exige un mot entier d'au moins quatre lettres : sans ce plancher,
        « art » ferait passer n'importe quel `artistes-en-herbe.fr` pour le
        domaine du Musée d'Art Moderne.
        """
        wanted = tokens(extracted.venue_name, MIN_VENUE_TOKEN)
        if not wanted:
            return []
        found: list[SourceLink] = []
        for link in links:
            if not self._usable(link.url, page_url):
                continue
            domain = fold(host_of(link.url).rsplit(".", 1)[0]).replace(" ", "")
            hit = next((w for w in wanted if w in domain), "")
            if hit:
                found.append(
                    SourceLink(
                        url=link.url,
                        signal=SIGNAL_VENUE_DOMAIN,
                        detail=f"« {hit} » du lieu se retrouve dans {host_of(link.url)}",
                    )
                )
        return found

    def _by_link_text(
        self, html: str, page_url: str, links: list[Link], extracted: ExtractedEvent
    ) -> list[SourceLink]:
        """3. Le lien qui s'annonce comme tel — « site officiel », « réserver ».

        Le moins sûr des trois gratuits : un agrégateur met parfois « réserver »
        sur sa propre billetterie affiliée. D'où sa place en dernier, et d'où la
        vérification qui suit.
        """
        return [
            SourceLink(
                url=link.url,
                signal=SIGNAL_PAGE_LINK,
                detail=f"lien « {link.text.strip()[:60]} »",
            )
            for link in links
            if self._usable(link.url, page_url) and OFFICIAL_TEXT.search(fold(link.text))
        ]

    def _by_search(self, extracted: ExtractedEvent, page: PageContent) -> SourceLink:
        """4. Le repli : on demande au moteur, puis on vérifie comme les autres.

        Le seul appel payant de l'étage, et le seul qui puisse être coupé. On
        n'y arrive que si la page lue ne porte pas le lien — ce qui arrive :
        beaucoup d'agrégateurs recopient l'information sans jamais citer leur
        source, et c'est précisément le cas que les signaux gratuits ne
        savent pas traiter.

        La requête est faite du titre et du lieu, pas de « site officiel » : on
        cherche la page de cette sortie, pas la racine d'un site. Les résultats
        passent le même tamis que les liens — pas d'agrégateur, pas de réseau
        social — et la même vérification.
        """
        if not self.config.source_search:
            return SourceLink(detail="recherche de source désactivée")
        if self.engine is None:
            return SourceLink(detail="aucun moteur configuré (SERPER_API_KEY absente)")
        if self.ctx.budget_reached:
            self.log.event("skip", reason="budget atteint, source non cherchée", url=page.url)
            return SourceLink(detail="budget atteint")

        query = self._query(extracted)
        if not query:
            return SourceLink(detail="pas de quoi formuler une requête")

        self.log.event("query", op="source", query=query, url=page.url)
        try:
            reply = self.engine.ask(query, num=SEARCH_RESULTS)
        except ProviderError as err:
            self.log.warn("attribution", f"moteur indisponible : {err}", url=page.url)
            return SourceLink(detail=f"moteur indisponible ({err})")
        reply.bill(self.ctx.provider.usage)

        for item in reply.results:
            url = str(item.get("link", "") or "").strip()
            if not self._usable(url, page.url):
                continue
            found = SourceLink(
                url=url,
                signal=SIGNAL_SEARCH,
                detail=f"1er résultat exploitable pour « {query} »",
            )
            checked = self._checked(found, extracted, page)
            if checked.found:
                return checked

        return SourceLink(detail=f"aucun résultat vérifiable pour « {query} »")

    def _query(self, extracted: ExtractedEvent) -> str:
        """Titre et lieu : ce qui identifie la sortie, sans mot de remplissage.

        Pas de « site officiel » dans la requête. On cherche *cette page*, et
        l'ajouter ferait remonter la racine du site, qui ne parle de rien.
        """
        parts = [extracted.title.strip(), extracted.venue_name.strip()]
        ville = extracted.venue_city.strip()
        if ville and fold(ville) not in fold(" ".join(parts)):
            parts.append(ville)
        query = " ".join(p for p in parts if p)
        return query if len(fold(query)) >= 8 else ""

    # ──────────────────────────────────────────────────────── la validation

    def _checked(
        self, source: SourceLink, extracted: ExtractedEvent, page: PageContent
    ) -> SourceLink:
        """Ouvre la page candidate et exige qu'elle parle de cette sortie.

        C'est le cœur de l'étage, et la raison pour laquelle il vaut mieux que
        deux lignes dans la publication. Deux preuves acceptées, dans cet ordre :

        * le **titre** s'y retrouve, à 60 % de ses mots significatifs — un titre
          est presque toujours reformulé d'un site à l'autre, exiger la phrase
          exacte reviendrait à ne jamais rien valider ;
        * à défaut, le **lieu et une date** : c'est la preuve du festival, dont
          le programme nomme rarement chaque atelier comme l'agrégateur.

        Un échec est journalisé avec l'URL écartée. C'est ce qui permettra de
        savoir, dans quelques semaines, si la cascade se trompe de page ou si
        elle ne trouve simplement rien.
        """
        try:
            html = self.ctx.fetcher.get_html(source.url)
        except FetchError as err:
            self.log.event(
                "attribution",
                url=page.url,
                status="candidate injoignable",
                candidate=source.url,
                signal=source.signal,
                reason=str(err),
            )
            return SourceLink(detail=f"source candidate injoignable ({err})")

        # L'organisateur publie souvent en deux langues, et c'est parfois sa
        # page anglaise que la cascade a ramassée — un `sameAs` vers `/en/`, un
        # résultat de moteur. On bascule AVANT de vérifier : la page contrôlée
        # doit être celle qui sera publiée, et le contrôle porte justement sur
        # un titre et des dates écrits en français.
        #
        # Une traduction déclarée peut vivre ailleurs (`fr.exemple.org`) : les
        # quatre refus valent pour elle comme pour toute autre candidate, sinon
        # la langue rouvrirait une porte que cet étage vient de fermer.
        autre, traduite = french_version(source.url, html, self.ctx.fetcher, self.log)
        url, html = (autre, traduite) if self._usable(autre, page.url) else (source.url, html)

        text = fold(page_text(html, limit=CHECK_CHARS))
        why = self._matches(text, extracted, page)
        if not why:
            self.log.event(
                "attribution",
                url=page.url,
                status="candidate écartée",
                candidate=url,
                signal=source.signal,
                reason="la page ne parle pas de cette sortie",
            )
            return SourceLink(detail="la page candidate ne parle pas de cette sortie")

        self.log.event(
            "attribution",
            url=page.url,
            status="source retenue",
            candidate=url,
            signal=source.signal,
            detail=source.detail,
            checked=why,
        )
        return SourceLink(
            url=url,
            signal=source.signal,
            detail=f"{source.detail} — vérifié : {why}",
            checked=True,
        )

    def _matches(self, text: str, extracted: ExtractedEvent, page: PageContent) -> str:
        """Ce qui prouve que ce texte parle de cette sortie. Vide s'il ne le prouve pas."""
        wanted = tokens(extracted.title, MIN_TITLE_TOKEN)
        if wanted:
            hits = [w for w in wanted if w in text]
            if len(hits) >= max(1, round(len(wanted) * TITLE_MATCH_RATIO)):
                return f"titre ({len(hits)}/{len(wanted)} mots)"

        lieu = tokens(extracted.venue_name, MIN_VENUE_TOKEN)
        if lieu and all(w in text for w in lieu):
            dates = [d for d in (extracted.date_start, extracted.date_end) if d]
            for iso in dates + list(page.json_ld_dates):
                if self._mentions_date(text, iso):
                    return f"lieu et date ({iso[:10]})"
        return ""

    @staticmethod
    def _mentions_date(text: str, iso: str) -> bool:
        """La date est-elle sur la page, en chiffres ou en toutes lettres ?

        Trois écritures couvrent l'essentiel du web français : `2026-04-12`,
        `12/04/2026` et « 12 avril ». On ne cherche pas plus loin — cette preuve
        n'est qu'un recours quand le titre ne suffit pas.
        """
        iso = (iso or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso):
            return False
        annee, mois, jour = iso.split("-")
        j = str(int(jour))
        formes = [
            iso,
            f"{jour}/{mois}/{annee}",
            f"{j}/{int(mois)}/{annee}",
            f"{j} {MOIS[int(mois) - 1]}",
        ]
        return any(f in text for f in formes)

    # ───────────────────────────────────────────────────────────── le tamis

    def _is_aggregator(self, url: str) -> bool:
        return in_domains(url, self.config.aggregator_domains)

    def _usable(self, url: str, page_url: str) -> bool:
        """Une URL peut-elle être *la* source ?

        Quatre refus, tous pour la même raison : ce ne serait pas une source.
        Le site courant (on n'a pas bougé), un autre agrégateur (on a changé de
        republication), un domaine bloqué (on ne le lit pas), et l'URL qui n'en
        est pas une.
        """
        if not url.startswith(("http://", "https://")):
            return False
        if same_site(url, page_url) or self._is_aggregator(url):
            return False
        return not in_domains(url, self.config.blocked_domains)
