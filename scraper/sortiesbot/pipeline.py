"""Enchaînement d'un run.

    1. découverte      (discovery)         → pages à lire
    2. lecture         (Python)            → texte, JSON-LD, image     gratuit
    3. fiche(s)        (modèle)            → une sortie, ou plusieurs
    puis géocodage, validation, photo, soumission — une fois par sortie.

La découverte est le seul étage qui connaisse le mode de la configuration
(`recherche` ou `site`) ; elle vit dans `discovery.py` et rend dans les deux
cas une liste de `Candidate`. Tout ce qui suit ici est commun : c'est ce qui
évite d'avoir deux scrapers à corriger au lieu d'un.

Une page vaut une sortie, sauf quand la découverte la marque `multiple` — la
page de programme d'un festival, qui en porte vingt. L'extraction rend donc
toujours une liste, à un élément le plus souvent, et la publication boucle
dessus. Le reste — géocodage, dates réelles, photo, mémoire, soumission — ne
sait pas d'où la fiche vient.

Le partage est toujours le même : Python fait ce qui est mécanique, le modèle
fait ce qui demande du jugement, et aucun appel ne boucle. Le filtre des URLs
déjà vues intervient avant l'extraction, la seule étape qui coûte par page.

Thème, période et zone sont une **stratégie de recherche**, pas un filtre de
sortie : ils orientent les requêtes et le tri des liens, là où ils font gagner
du temps et de l'argent. Une fois la page lue, elle est payée — l'écarter
parce qu'elle déborde de la fenêtre reviendrait à payer pour rien, alors que
le site sait filtrer par date et par distance, et qu'un modérateur relit tout.
Seul ce qui est inexploitable est écarté.

Chaque page traitée est rendue à la mémoire (`store.report`) avec ce qu'on en
a fait. Une décision définitive y est mémorisée — la page ne sera plus jamais
relue, par aucune configuration ; une décision provisoire (déjà connue,
doublon, essai sans soumission, erreur réseau) est seulement journalisée.
"""

from __future__ import annotations


from . import discovery
from .api import ApiError, SppApi
from .config import Config, describe
from .harvest import Fetcher
from .journal import RunLog
from .models import Candidate, Summary
from .providers.base import Provider, ProviderError
from .stages import describe as describe_stages
from .stages.base import RunContext, RunResult
from .stages.extraction import Extraction
from .stages.publication import Publication, describe_schedule, resolve_category
from .stages.reading import Reading
from .store import Memory, normalize_url


#: En dessous, la page n'a pas de contenu exploitable (mur de cookies, page
#: vide, redirection JavaScript) : inutile de payer une extraction dessus.
MIN_PAGE_CHARS = 200


def run(
    config: Config,
    provider: Provider,
    store: Memory,
    api: SppApi,
    log: RunLog,
    submit: bool = False,
    fetcher: Fetcher | None = None,
) -> RunResult:
    result = RunResult()
    summary = result.summary
    fetcher = fetcher or Fetcher()
    # Le graphe part avec le premier événement : la console peut dessiner les
    # six briques avant même que la première ait produit quoi que ce soit.
    log.event(
        "run_start",
        config=describe(config),
        mode="soumission" if submit else "dry-run",
        stages=describe_stages(),
    )

    categories: dict[str, int] = {}
    try:
        categories = api.categories()
    except ApiError as err:
        log.error("categories", str(err))
        if submit:
            summary.errors += 1
            log.event("run_end", summary=summary.as_dict())
            return result

    # 1. Découverte — recherche web, ou URLs données. Seul étage qui diffère.
    try:
        trouvees = discovery.candidates(config, provider, fetcher, log, summary)
    except ProviderError as err:
        log.error("search", str(err))
        summary.errors += 1
        log.event("run_end", summary=summary.as_dict())
        return result

    candidates: list[Candidate] = []
    vues: set[str] = set()
    for candidate in trouvees:
        # Deux agendas listent souvent la même sortie — parfois la même page
        # sous deux URLs. Sans ce filtre, elle est lue, extraite et soumise
        # deux fois.
        key = normalize_url(candidate.url)
        if key in vues:
            summary.duplicates += 1
            log.event("skip", reason="déjà repérée ailleurs", url=candidate.url)
            # Provisoire : c'est le premier exemplaire qui décidera du sort
            # de la page, pas ce doublon.
            store.report(
                candidate.url,
                "duplicate",
                title=candidate.title,
                reason="déjà repérée ailleurs dans ce run",
                remember=False,
            )
            continue
        vues.add(key)
        candidates.append(candidate)

    summary.candidates = len(candidates)
    result.candidates = [
        {
            "url": c.url,
            "title": c.title,
            "source": c.source,
            "context": c.context,
            "multiple": c.multiple,
        }
        for c in candidates
    ]
    for candidate in candidates:
        log.event(
            "candidate",
            url=candidate.url,
            title=candidate.title,
            why=candidate.context,
            agenda=candidate.source,
        )

    if not candidates:
        log.event("nothing_found", searches=provider.usage.web_searches, pages=summary.pages)

    # Une seule question à la mémoire pour tout le lot : la suite ne fait plus
    # que consulter le résultat. Une page de programme n'en est pas : ce sont
    # ses sorties qui se mémorisent, une par une, et leurs clés n'existent
    # qu'une fois la page lue.
    store.preload([c.url for c in candidates if not c.multiple])

    ctx = RunContext(
        config=config,
        provider=provider,
        store=store,
        api=api,
        fetcher=fetcher,
        log=log,
        submit=submit,
        categories=categories,
        result=result,
    )

    # 2 et 3. Une page à la fois.
    for candidate in candidates:
        if len(result.events) >= config.max_events:
            break
        if provider.usage.total_usd >= config.max_cost_usd:
            summary.stopped_on_budget = True
            log.event(
                "budget",
                spent=round(provider.usage.total_usd, 4),
                limit=config.max_cost_usd,
                candidates=len(candidates),
            )
            break
        _process(candidate, ctx)

    summary.retained = len(result.events)
    summary.usage.add(provider.usage)
    store.flush()
    log.event("run_end", summary=summary.as_dict())
    return result


def _process(candidate: Candidate, ctx: RunContext) -> None:
    """Lit une page et publie ce qu'elle porte : une sortie, ou vingt.

    Trois briques s'enchaînent ici, et la cardinalité change à chaque flèche :
    on lit **une** page, on en extrait **n** fiches, on en publie **n**. C'est
    précisément ce qu'une interface uniforme aurait caché.
    """
    with ctx.log.trail(page=candidate.url, agenda=candidate.source):
        page = Reading(ctx).run(candidate)
        if page is None:
            return

        for extracted in Extraction(ctx).run(page, candidate):
            if ctx.full:
                ctx.log.event("skip", reason="plafond de sorties atteint", url=candidate.url)
                break
            Publication(ctx).run(extracted, candidate, page)
