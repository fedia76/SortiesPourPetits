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

import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from . import discovery
from .api import ApiError, SppApi
from .config import Config, describe
from .harvest import FetchError, Fetcher, json_ld_dates, main_image, page_text
from .journal import RunLog
from .models import Candidate, ExtractedEvent, Summary
from .payload import UNKNOWN_PRICE, OutOfPeriod, Rejected, build_payload
from .photo import PhotoError, download
from .providers.base import Provider, ProviderError
from .schedule import Schedule, resolve as resolve_schedule
from .store import Memory, event_key, normalize_url
from . import geocode as geocoding


#: En dessous, la page n'a pas de contenu exploitable (mur de cookies, page
#: vide, redirection JavaScript) : inutile de payer une extraction dessus.
MIN_PAGE_CHARS = 200


@dataclass
class RunResult:
    summary: Summary = field(default_factory=Summary)
    #: Pages de sortie repérées, conservées même si la suite s'arrête.
    candidates: list[dict[str, Any]] = field(default_factory=list)
    #: Sorties retenues : payload prêt pour l'API, plus de quoi les relire.
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Stage:
    """Ce dont la lecture d'une page a besoin, d'un bout à l'autre.

    Ces dix objets voyageaient en paramètres de fonction en fonction ; les
    réunir garde les signatures lisibles maintenant qu'une page peut donner
    plusieurs sorties, donc une étape de plus.
    """

    config: Config
    provider: Provider
    store: Memory
    api: SppApi
    fetcher: Fetcher
    log: RunLog
    submit: bool
    categories: dict[str, int]
    result: RunResult
    #: Clés des sorties déjà publiées par ce run. Deux programmes d'un même
    #: festival annoncent souvent les mêmes séances.
    keys: set[str] = field(default_factory=set)

    @property
    def summary(self) -> Summary:
        return self.result.summary


def _fold(text: str) -> str:
    """Compare des noms de catégories sans se soucier de la casse ni des accents."""
    stripped = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in stripped if not unicodedata.combining(c))


def resolve_category(name: str, categories: dict[str, int], default: str) -> int:
    """Rattache la catégorie annoncée par le modèle à une catégorie du site."""
    if not categories:
        return 0  # dry-run sans API joignable : identifiant symbolique.
    by_fold = {_fold(k): v for k, v in categories.items()}
    for candidate in (name, default):
        found = by_fold.get(_fold(candidate or ""))
        if found is not None:
            return found
    raise Rejected(f"catégorie « {name or '?'} » inconnue et « {default} » absente du site")


def _out_of_area(postal_code: str, prefixes: list[str]) -> bool:
    """Un code postal connu hors zone écarte la sortie.

    Un géocodage hors zone échoue déjà, mais la sortie partait quand même en
    (0, 0) « adresse à compléter » — un spectacle à Chantilly, dans l'Oise,
    s'est retrouvé dans un run Île-de-France.
    """
    code = postal_code.strip()
    return bool(code and prefixes and not code.startswith(tuple(prefixes)))


def describe_schedule(schedule: Schedule, payload: dict[str, Any]) -> str:
    """Le calendrier en une ligne, pour la colonne « Détail » de la console."""
    plage = " → ".join(d for d in (payload["dateStart"], payload["dateEnd"]) if d)
    if not schedule.precise:
        return f"{plage} — tous les jours" if plage else "sortie permanente"
    jours = ", ".join(schedule.weekdays)
    detail = f"{len(schedule.dates)} date(s) [{schedule.source}]"
    return f"{plage} — {detail}" + (f" : {jours}" if jours else "")


def _is_blocked(url: str, blocked: list[str]) -> bool:
    host = urlsplit(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return any(host == d or host.endswith(f".{d}") for d in blocked)


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
    log.event("run_start", config=describe(config), mode="soumission" if submit else "dry-run")

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
        log.event("candidate", url=candidate.url, title=candidate.title, why=candidate.context)

    if not candidates:
        log.event("nothing_found", searches=provider.usage.web_searches, pages=summary.pages)

    # Une seule question à la mémoire pour tout le lot : la suite ne fait plus
    # que consulter le résultat. Une page de programme n'en est pas : ce sont
    # ses sorties qui se mémorisent, une par une, et leurs clés n'existent
    # qu'une fois la page lue.
    store.preload([c.url for c in candidates if not c.multiple])

    stage = _Stage(
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
        _process(candidate, stage)

    summary.retained = len(result.events)
    summary.usage.add(provider.usage)
    store.flush()
    log.event("run_end", summary=summary.as_dict())
    return result


def _process(candidate: Candidate, stage: _Stage) -> None:
    """Lit une page et publie ce qu'elle porte : une sortie, ou vingt."""
    config, log, store = stage.config, stage.log, stage.store
    summary = stage.summary
    url = candidate.url

    if _is_blocked(url, config.blocked_domains):
        summary.skipped_blocked += 1
        log.event("skip", reason="domaine bloqué", url=url)
        # Provisoire : la liste des domaines bloqués est un réglage, pas un
        # jugement sur la page. La retirer de la liste doit suffire à la lire.
        store.report(url, "blocked", title=candidate.title, remember=False)
        return
    # Une page de programme échappe à ce filtre, et c'est le but : le
    # programme d'un festival s'étoffe, et ce sont ses sorties qui sont
    # mémorisées une à une, pas lui. Le relire est justement ce qu'on veut.
    if not candidate.multiple and store.seen(url):
        summary.skipped_seen += 1
        log.event("skip", reason="déjà vue lors d'un run précédent", url=url)
        store.report(url, "seen", title=candidate.title, remember=False)
        return

    # La page est lue en Python : le modèle ne reçoit que du texte, sans outil,
    # donc sans boucle serveur ni refacturation. Le HTML brut sert une seconde
    # fois, pour le JSON-LD que le nettoyage du texte jetterait.
    try:
        html = stage.fetcher.get_html(url)
        content = page_text(html, limit=config.max_page_chars)
        declared = json_ld_dates(html)
        # L'illustration se lit dans le HTML, pas dans le texte : le modèle ne
        # voit que le second et ne pouvait donc jamais donner d'URL d'image.
        page_image = main_image(html, url)
    except FetchError as err:
        summary.errors += 1
        log.error("extraction", str(err), url=url)
        # Un site injoignable aujourd'hui peut répondre demain : on ne
        # mémorise pas, le prochain run réessaiera.
        store.report(url, "error", title=candidate.title, reason=str(err), remember=False)
        return
    if len(content) < MIN_PAGE_CHARS:
        summary.skipped_invalid += 1
        log.event("skip", reason="page vide ou illisible", url=url)
        store.report(url, "invalid", title=candidate.title, reason="page vide ou illisible")
        return

    try:
        extracted = stage.provider.extract(
            url,
            content,
            config,
            sorted(stage.categories),
            log,
            multiple=candidate.multiple,
        )
    except ProviderError as err:
        summary.errors += 1
        log.error("extraction", str(err), url=url)
        store.report(url, "error", title=candidate.title, reason=str(err), remember=False)
        return

    if candidate.multiple:
        log.event(
            "programme",
            url=url,
            found=len([e for e in extracted if e.relevant]),
            chars=len(content),
        )

    for event in extracted:
        if len(stage.result.events) >= config.max_events:
            log.event("skip", reason="plafond de sorties atteint", url=url)
            break
        _publish(event, candidate, page_image, declared, stage)


def _publish(
    extracted: ExtractedEvent,
    candidate: Candidate,
    page_image: str,
    declared: list[str],
    stage: _Stage,
) -> None:
    """Géocode, date, illustre et propose une sortie déjà lue.

    Appelé une fois par page en mode « recherche », autant de fois qu'il y a
    de sorties sur une page de programme. Rien ici ne sait laquelle des deux.
    """
    config, log, store = stage.config, stage.log, stage.store
    summary = stage.summary
    url = candidate.url

    # Sur une page de programme, l'unité mémorisable n'est pas la page mais
    # chacune de ses sorties : sinon un programme lu une fois ne serait plus
    # jamais relu, et tout ce qu'il annoncera ensuite serait perdu.
    key = event_key(url, extracted.title) if candidate.multiple else None

    if not extracted.relevant:
        summary.skipped_irrelevant += 1
        log.event("skip", reason=extracted.skip_reason or "hors sujet", url=url)
        store.report(
            url,
            "irrelevant",
            key=key,
            title=candidate.title,
            reason=extracted.skip_reason or "hors sujet",
        )
        return

    if key is not None:
        if key in stage.keys or store.seen(url, key):
            summary.duplicates += 1
            log.event("skip", reason="sortie déjà connue", url=url, title=extracted.title)
            store.report(
                url,
                "duplicate",
                key=key,
                title=extracted.title,
                reason="déjà relevée sur ce programme",
                remember=False,
            )
            return
        stage.keys.add(key)

    log.event(
        "extract",
        url=url,
        title=extracted.title,
        venue=f"{extracted.venue_name} — {extracted.venue_city}".strip(" —"),
    )

    if _out_of_area(extracted.venue_postal_code, config.postal_prefixes):
        summary.out_of_area += 1
        if not config.keep_out_of_scope:
            reason = f"code postal {extracted.venue_postal_code} hors zone"
            log.event("skip", reason=reason, url=url)
            store.report(url, "out_of_area", key=key, title=extracted.title, reason=reason)
            return
        log.event("out_of_scope", field="zone", url=url, detail=extracted.venue_postal_code)

    geo = geocoding.geocode(extracted)
    log.event(
        "geocode", url=url, query=geo.query, located=geo.located,
        lat=geo.location.lat, lng=geo.location.lng, reason=geo.reason,
    )
    if not geo.located:
        summary.ungeocoded += 1

    try:
        category_id = resolve_category(extracted.category, stage.categories, config.default_category)
        payload = build_payload(
            extracted,
            geo.location,
            category_id,
            url,
            until=None if config.keep_out_of_scope else config.date_to,
        )
    except OutOfPeriod as err:
        summary.out_of_period += 1
        log.event("skip", reason=str(err), url=url)
        store.report(url, "out_of_period", key=key, title=extracted.title, reason=str(err))
        return
    except Rejected as err:
        summary.skipped_invalid += 1
        log.event("skip", reason=str(err), url=url)
        store.report(
            url,
            "invalid",
            key=key,
            title=extracted.title or candidate.title,
            reason=str(err),
        )
        return

    if payload["dateStart"] and payload["dateStart"] > config.date_to.isoformat():
        summary.out_of_period += 1
        log.event("out_of_scope", field="période", url=url, detail=payload["dateStart"])

    # Dates réelles de la sortie.
    schedule = resolve_schedule(
        payload["dateStart"] or "",
        payload["dateEnd"] or "",
        weekdays=extracted.weekdays,
        announced=extracted.dates,
        json_ld=declared,
    )
    # Le site ne reçoit des jours que s'ils apprennent quelque chose : sinon
    # la liste reste vide, et sa période vaut pour tous ses jours.
    payload["dates"] = list(schedule.dates)
    if schedule.precise:
        summary.scheduled += 1
    # La plage est journalisée avec le calendrier : sans elle, impossible de
    # rejuger après coup si une date isolée était une séance ou un premier jour.
    log.event(
        "schedule",
        url=url,
        title=payload["title"],
        start=payload["dateStart"],
        end=payload["dateEnd"],
        **schedule.as_dict(),
    )

    if payload["price"] == UNKNOWN_PRICE:
        summary.unpriced += 1
        log.event("incomplete", field="tarif", url=url, title=payload["title"])
    if not geo.located:
        log.event("incomplete", field="adresse", url=url, title=payload["title"])

    # Ce que la page déclare passe avant ce que le modèle a pu écrire : lui ne
    # voit que du texte, donc une URL de sa part est au mieux une devinette.
    # Les sorties d'un même programme partagent l'illustration de la page :
    # c'est la seule que le HTML donne, et une vignette juste vaut mieux que
    # vingt fiches nues.
    photo_url = page_image or extracted.photo_url
    if not photo_url:
        log.event("photo", status="aucune image sur la page", url=url)

    photo = None
    if stage.submit and photo_url:
        try:
            # Même session que les pages : sans notre User-Agent, beaucoup de
            # serveurs refusent l'image qu'ils viennent pourtant d'annoncer.
            photo = download(photo_url, stage.fetcher.session)
            log.event("photo", status="téléchargée", url=photo_url)
        except PhotoError as err:
            log.event("photo", status=f"ignorée ({err})", url=photo_url)

    record = {
        "payload": payload,
        "source_url": url,
        "found_on": candidate.source,
        "photo_url": photo_url,
        "located": geo.located,
        "schedule": schedule.as_dict(),
    }

    if not stage.submit:
        stage.result.events.append(record)
        log.event("dry_run", title=payload["title"], url=url)
        # Un essai ne mémorise pas : sinon la sortie qu'il vient de repérer ne
        # serait jamais proposée, le run réel la sautant comme « déjà vue ».
        store.report(
            url,
            "dry_run",
            key=key,
            title=payload["title"],
            reason=describe_schedule(schedule, payload),
            remember=False,
        )
        return

    try:
        event = stage.api.create_event(payload, photo)
    except ApiError as err:
        summary.errors += 1
        log.error("submit", str(err), url=url)
        store.report(
            url, "error", key=key, title=payload["title"], reason=str(err), remember=False
        )
        return

    event_id = event.get("id")
    record["event_id"] = event_id
    stage.result.events.append(record)
    summary.submitted += 1
    store.report(
        url,
        "submitted",
        key=key,
        title=payload["title"],
        reason=describe_schedule(schedule, payload),
        event_id=event_id,
    )
    log.event("submit", event_id=event_id, title=payload["title"], url=url)
