"""Enchaînement d'un run.

    1. recherche       (modèle)  → pages d'agenda à ouvrir
    2. téléchargement  (Python)  → HTML des agendas               gratuit
    3. extraction liens(Python)  → (texte, url, contexte)          gratuit
    4. sélection       (modèle)  → liens menant à une sortie
    5. lecture + fiche (Python + modèle) → sortie structurée
    puis géocodage, validation, photo, soumission — inchangés.

Le partage est toujours le même : Python fait ce qui est mécanique, le modèle
fait ce qui demande du jugement, et aucun appel ne boucle. Le filtre des URLs
déjà vues intervient avant l'étape 5, la seule qui coûte par sortie.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .api import ApiError, SppApi
from .config import Config, describe
from .harvest import FetchError, Fetcher, Link, links_of, page_text
from .journal import RunLog
from .models import Candidate, Summary
from .payload import UNKNOWN_PRICE, Rejected, build_payload
from .photo import PhotoError, download
from .providers.base import Provider, ProviderError
from .store import SeenStore
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


def _is_blocked(url: str, blocked: list[str]) -> bool:
    host = urlsplit(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return any(host == d or host.endswith(f".{d}") for d in blocked)


def run(
    config: Config,
    provider: Provider,
    store: SeenStore,
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

    # 1. Recherche.
    try:
        agendas = provider.search(config, log)
    except ProviderError as err:
        log.error("search", str(err))
        summary.errors += 1
        log.event("run_end", summary=summary.as_dict())
        return result

    # 2 à 4. Chaque agenda est téléchargé, dépouillé, puis trié par le modèle.
    candidates: list[Candidate] = []
    for agenda in agendas[: config.max_agendas]:
        candidates.extend(_harvest(agenda.url, config, provider, fetcher, log, summary))

    summary.candidates = len(candidates)
    result.candidates = [
        {"url": c.url, "title": c.title, "source": c.source, "context": c.context}
        for c in candidates
    ]
    for candidate in candidates:
        log.event("candidate", url=candidate.url, title=candidate.title, why=candidate.context)

    if not candidates:
        log.event("nothing_found", searches=provider.usage.web_searches, pages=summary.pages)

    # 5. Une sortie à la fois.
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
        _process(candidate, config, provider, store, api, fetcher, log, submit, categories, result)

    summary.retained = len(result.events)
    summary.usage.add(provider.usage)
    log.event("run_end", summary=summary.as_dict())
    return result


def _harvest(
    url: str,
    config: Config,
    provider: Provider,
    fetcher: Fetcher,
    log: RunLog,
    summary: Summary,
) -> list[Candidate]:
    """Télécharge un agenda, en extrait les liens, et fait trancher le modèle."""
    log.event("fetching", stage="agenda", url=url)
    try:
        html = fetcher.get_html(url)
    except FetchError as err:
        log.error("agenda", str(err), url=url)
        return []

    links = links_of(html, url)
    summary.pages += 1
    log.event("harvested", url=url, links=len(links))
    if not links:
        return []

    try:
        kept = provider.select(url, links, config, log)
    except ProviderError as err:
        summary.errors += 1
        log.error("select", str(err), url=url)
        return []

    log.event("selected", url=url, kept=len(kept), among=len(links))
    return [
        Candidate(url=link.url, title=link.text, source=url, context=link.context)
        for link in kept
    ]


def _process(
    candidate: Candidate,
    config: Config,
    provider: Provider,
    store: SeenStore,
    api: SppApi,
    fetcher: Fetcher,
    log: RunLog,
    submit: bool,
    categories: dict[str, int],
    result: RunResult,
) -> None:
    summary = result.summary
    url = candidate.url

    if _is_blocked(url, config.blocked_domains):
        summary.skipped_blocked += 1
        log.event("skip", reason="domaine bloqué", url=url)
        return
    if store.seen(url):
        summary.skipped_seen += 1
        log.event("skip", reason="déjà vue lors d'un run précédent", url=url)
        return

    # La page est lue en Python : le modèle ne reçoit que du texte, sans outil,
    # donc sans boucle serveur ni refacturation.
    try:
        content = page_text(fetcher.get_html(url), limit=config.max_page_chars)
    except FetchError as err:
        summary.errors += 1
        log.error("extraction", str(err), url=url)
        return
    if len(content) < MIN_PAGE_CHARS:
        summary.skipped_invalid += 1
        log.event("skip", reason="page vide ou illisible", url=url)
        store.remember(url, "invalid", title=candidate.title)
        return

    try:
        extracted = provider.extract(url, content, config, sorted(categories), log)
    except ProviderError as err:
        summary.errors += 1
        log.error("extraction", str(err), url=url)
        return

    if not extracted.relevant:
        summary.skipped_irrelevant += 1
        log.event("skip", reason=extracted.skip_reason or "hors sujet", url=url)
        store.remember(url, "irrelevant", title=candidate.title)
        return

    log.event(
        "extract",
        url=url,
        title=extracted.title,
        venue=f"{extracted.venue_name} — {extracted.venue_city}".strip(" —"),
    )

    geo = geocoding.geocode(extracted, config.postal_prefixes)
    log.event(
        "geocode", url=url, query=geo.query, located=geo.located,
        lat=geo.location.lat, lng=geo.location.lng, reason=geo.reason,
    )
    if not geo.located:
        summary.ungeocoded += 1

    try:
        category_id = resolve_category(extracted.category, categories, config.default_category)
        payload = build_payload(extracted, geo.location, category_id, url)
    except Rejected as err:
        summary.skipped_invalid += 1
        log.event("skip", reason=str(err), url=url)
        store.remember(url, "invalid", title=extracted.title or candidate.title)
        return

    if payload["price"] == UNKNOWN_PRICE:
        summary.unpriced += 1
        log.event("incomplete", field="tarif", url=url, title=payload["title"])
    if not geo.located:
        log.event("incomplete", field="adresse", url=url, title=payload["title"])

    photo = None
    if submit and extracted.photo_url:
        try:
            photo = download(extracted.photo_url)
            log.event("photo", status="téléchargée", url=extracted.photo_url)
        except PhotoError as err:
            log.event("photo", status=f"ignorée ({err})", url=extracted.photo_url)

    record = {
        "payload": payload,
        "source_url": url,
        "found_on": candidate.source,
        "photo_url": extracted.photo_url,
        "located": geo.located,
    }

    if not submit:
        result.events.append(record)
        log.event("dry_run", title=payload["title"], url=url)
        return

    try:
        event = api.create_event(payload, photo)
    except ApiError as err:
        summary.errors += 1
        log.error("submit", str(err), url=url)
        store.remember(url, "error", title=payload["title"])
        return

    event_id = event.get("id")
    record["event_id"] = event_id
    result.events.append(record)
    summary.submitted += 1
    store.remember(url, "submitted", title=payload["title"], event_id=event_id)
    log.event("submit", event_id=event_id, title=payload["title"], url=url)
