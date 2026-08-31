"""Étage découverte : trouver les pages à lire.

C'est le seul étage qui diffère d'un mode à l'autre, et c'est pour ça qu'il
vit dans son propre module. Les deux stratégies rendent la même chose — une
liste de `Candidate` — et tout ce qui suit dans `pipeline.py` ignore laquelle
a servi :

* `_by_search` — mode « recherche » : le modèle lance des recherches web, on
  télécharge les agendas qu'elles remontent et on en tire les liens. C'est le
  chemin historique, déplacé ici sans changement.
* `_by_seeds` — mode « site » : les URLs sont données par la configuration,
  aucune recherche web n'est lancée. Une URL qui donne des liens vers des
  fiches se dépouille comme un agenda ; une URL qui n'en donne aucun est un
  programme, dont on tirera plusieurs sorties d'un coup.

Le dépouillement d'une page (`_harvest`) est commun aux deux : c'est
mécaniquement le même travail — télécharger, extraire les liens, faire
trancher le modèle. Seul le sort d'une page dont on ne tire rien change, d'où
`fallback_multiple`.
"""

from __future__ import annotations

from .config import Config
from .harvest import FetchError, Fetcher, links_of
from .journal import RunLog
from .models import Candidate, Summary
from .providers.base import Provider, ProviderError
from .stages import Stage


def candidates(
    config: Config,
    provider: Provider,
    fetcher: Fetcher,
    log: RunLog,
    summary: Summary,
) -> list[Candidate]:
    """Les pages à lire, selon le mode de la configuration.

    Peut lever `ProviderError` : une recherche impossible arrête le run, et
    c'est `pipeline.run` qui en rend compte.
    """
    if config.targets_site:
        return _by_seeds(config, provider, fetcher, log, summary)
    return _by_search(config, provider, fetcher, log, summary)


# ------------------------------------------------------------ mode recherche


def _by_search(
    config: Config,
    provider: Provider,
    fetcher: Fetcher,
    log: RunLog,
    summary: Summary,
) -> list[Candidate]:
    """Recherches web, puis dépouillement des agendas remontés."""
    # Étage 1 — le modèle cherche et classe. C'est le seul étage qui diffère
    # d'un mode à l'autre, et le seul qui paie une recherche web.
    with log.stage(Stage.DISCOVERY, mode="recherche", theme=config.theme, area=config.area) as st:
        found = provider.search(config, log)

        # Une recherche ne remonte pas que des agendas : elle tombe régulièrement
        # sur la page d'une sortie précise, qui part telle quelle à l'extraction.
        candidats = [p for p in found if p.is_agenda]
        agendas = candidats[: config.max_agendas]
        recales = candidats[config.max_agendas :]
        directes = [p for p in found if not p.is_agenda]

        for page in directes:
            log.event("direct", url=page.url, title=page.title, why=page.reason)

        # Le sort de chaque agenda désigné est journalisé avant qu'on l'ouvre :
        # sans ça, un agenda recalé par le plafond ou injoignable disparaissait
        # de la console sans laisser de trace, et on cherchait pourquoi un site
        # remonté par la recherche n'apparaissait nulle part.
        for page in agendas:
            log.event("agenda_planned", url=page.url, title=page.title, why=page.reason)
        for page in recales:
            log.warn(
                "discovery",
                f"plafond de {config.max_agendas} agenda(s) atteint : celui-ci ne sera pas ouvert",
                url=page.url,
                title=page.title,
                why=page.reason,
            )

        st.produced(
            f"{len(agendas)} agenda(s) à dépouiller, {len(directes)} sortie(s) directe(s)"
            + (f", {len(recales)} au-delà du plafond" if recales else ""),
            agendas=len(agendas),
            direct=len(directes),
            over_cap=len(recales),
        )

    trouvees = [
        Candidate(url=p.url, title=p.title, source="recherche", context=p.reason)
        for p in directes
    ]
    for agenda in agendas:
        trouvees.extend(_harvest(agenda.url, config, provider, fetcher, log, summary))
    return trouvees


# ----------------------------------------------------------------- mode site


def _by_seeds(
    config: Config,
    provider: Provider,
    fetcher: Fetcher,
    log: RunLog,
    summary: Summary,
) -> list[Candidate]:
    """Part des URLs données, sans la moindre recherche web.

    La forme du site n'a pas à être déclarée : elle se constate. Une page qui
    mène à des fiches est un agenda, une page qui ne mène nulle part est le
    programme lui-même. Un festival tient souvent sur une seule page, où les
    entrées ne sont reliées que par des ancres — donc sans lien à suivre.
    """
    trouvees: list[Candidate] = []
    # Même plafond que les agendas d'une recherche : c'est le même travail, et
    # la console présente le réglage sous les deux noms.
    seeds = config.seed_urls[: config.max_agendas]
    # L'étage 1 existe aussi ici, il ne coûte simplement rien : les URL sont
    # données. Le graphe de la console garde ainsi ses six briques.
    with log.stage(Stage.DISCOVERY, mode="site", seeds=len(seeds)) as st:
        for url in seeds:
            log.event("seed", url=url)
        st.produced(f"{len(seeds)} point(s) de départ, aucune recherche lancée", agendas=len(seeds))

    for url in seeds:
        trouvees.extend(
            _harvest(
                url,
                config,
                provider,
                fetcher,
                log,
                summary,
                source="site",
                fallback_multiple=True,
            )
        )
    return trouvees


# -------------------------------------------------------------------- commun


def _harvest(
    url: str,
    config: Config,
    provider: Provider,
    fetcher: Fetcher,
    log: RunLog,
    summary: Summary,
    *,
    source: str = "recherche",
    fallback_multiple: bool = False,
) -> list[Candidate]:
    """Télécharge une page, en extrait les liens, et fait trancher le modèle.

    `fallback_multiple` dit ce qu'on fait d'une page dont on ne tire aucun
    lien : la relire comme une sortie unique (mode recherche, où c'est un
    agenda mal classé) ou comme un programme (mode site, où c'est le cas
    normal d'un festival tenant sur une page).

    Tout ce qui se journalise ici descend de cet agenda : c'est ce qui permet
    à la console de répondre à « quels liens venaient de quelle page ? ».
    """
    with log.trail(agenda=url):
        return _harvest_one(url, config, provider, fetcher, log, summary, source, fallback_multiple)


def _harvest_one(
    url: str,
    config: Config,
    provider: Provider,
    fetcher: Fetcher,
    log: RunLog,
    summary: Summary,
    source: str,
    fallback_multiple: bool,
) -> list[Candidate]:
    """Le dépouillement lui-même, une fois la piste ouverte."""
    # Étage 2 — Python télécharge l'agenda et en extrait les liens. Gratuit.
    with log.stage(Stage.HARVEST, url=url) as st:
        log.event("fetching", url=url)
        try:
            html = fetcher.get_html(url)
        except FetchError as err:
            log.error("agenda", str(err), url=url)
            st.produced(f"non dépouillé : {err}", links=0)
            return []

        links = links_of(html, url)
        summary.pages += 1
        log.event("harvested", url=url, links=len(links), chars=len(html))
        st.produced(f"{len(links)} lien(s) extrait(s)", links=len(links))

    if not links:
        # Pas un seul lien exploitable : ce n'est pas un agenda. La page est
        # téléchargée, autant la lire pour ce qu'elle est.
        return [_fallback(url, log, source, fallback_multiple)]

    # Étage 3 — le modèle tranche, sur une liste numérotée. Facturé.
    with log.stage(Stage.SELECT, url=url, among=len(links)) as st:
        try:
            kept = provider.select(url, links, config, log)
        except ProviderError as err:
            summary.errors += 1
            log.error("select", str(err), url=url)
            st.produced("échec de la sélection", kept=0, among=len(links))
            return []

        st.produced(f"{len(kept)} lien(s) retenu(s) sur {len(links)}", kept=len(kept), among=len(links))

    if not kept:
        # Un agenda dont on ne tire aucun lien est peut-être une page de
        # sortie que la recherche a mal classée. Elle est déjà téléchargée :
        # la lire coûte une extraction, l'ignorer coûte la sortie.
        return [_fallback(url, log, source, fallback_multiple)]

    return [
        Candidate(url=link.url, title=link.text, source=url, context=link.context)
        for link in kept
    ]


def _fallback(url: str, log: RunLog, source: str, multiple: bool) -> Candidate:
    log.event("fallback", url=url, multiple=multiple)
    return Candidate(url=url, title="", source=source, context="", multiple=multiple)
