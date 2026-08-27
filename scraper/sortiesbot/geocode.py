"""Géocodage des lieux, via Photon (OpenStreetMap).

Même fournisseur que le formulaire du site (`client/src/lib/geocode.ts`), pour
que les positions issues du scraper et celles saisies à la main viennent de la
même source. Photon connaît aussi les lieux d'intérêt (parcs, musées, fermes
pédagogiques), ce qui compte ici : les pages d'événement donnent souvent un nom
de lieu plutôt qu'une adresse.

Une position hors de la zone attendue est traitée comme un échec : mieux vaut
laisser le modérateur compléter que publier une sortie à l'autre bout du monde.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

import requests

from .models import UNLOCATED, ExtractedEvent, Location

PHOTON_URL = "https://photon.komoot.io/api/"

#: Biais de recherche : centre de Paris, pour que « Le Zèbre » sorte en IDF.
_BIAS = {"lat": 48.8566, "lon": 2.3522}

_TIMEOUT = 10


class GeocodeResult:
    """Position trouvée, ou raison de l'échec — les deux intéressent le journal."""

    def __init__(self, location: Location, query: str, reason: str = ""):
        self.location = location
        self.query = query
        self.reason = reason

    @property
    def located(self) -> bool:
        return self.location.located


def _queries(event: ExtractedEvent) -> Iterable[str]:
    """Tentatives, de la plus précise à la plus large."""
    city = event.venue_city
    seen: set[str] = set()
    for parts in (
        (event.venue_address, event.venue_postal_code, city),
        (event.venue_name, event.venue_postal_code, city),
        (event.venue_address, city),
        (event.venue_name, city),
        (event.venue_name,),
    ):
        query = ", ".join(p for p in parts if p)
        if query and query not in seen:
            seen.add(query)
            yield query


def _photon_search(query: str) -> list[dict[str, Any]]:
    response = requests.get(
        PHOTON_URL,
        params={"q": query, "limit": 5, "lang": "fr", **_BIAS},
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    return body.get("features", []) if isinstance(body, dict) else []


def _to_location(feature: dict[str, Any]) -> Location | None:
    props = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None
    try:
        lng, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        return None
    if lat == 0 and lng == 0:
        return None
    return Location(
        lat=lat,
        lng=lng,
        city=str(props.get("city") or props.get("town") or ""),
        postal_code=str(props.get("postcode") or ""),
    )


def geocode(
    event: ExtractedEvent,
    postal_prefixes: list[str],
    search: Callable[[str], list[dict[str, Any]]] | None = None,
) -> GeocodeResult:
    """Cherche la position d'un lieu ; retourne `UNLOCATED` en cas d'échec.

    `search` est injectable pour les tests ; par défaut c'est Photon.
    """
    search = search or _photon_search
    last_query = event.venue_name or event.venue_city or "(lieu inconnu)"
    out_of_area = False

    for query in _queries(event):
        last_query = query
        try:
            features = search(query)
        except requests.RequestException as err:
            return GeocodeResult(UNLOCATED, query, f"géocodeur injoignable : {err}")

        for feature in features:
            location = _to_location(feature)
            if location is None:
                continue
            if not location.postal_code:
                # Sans code postal, impossible de vérifier qu'on est dans la
                # zone : on préfère la tentative suivante, plus précise.
                continue
            if postal_prefixes and not location.postal_code.startswith(tuple(postal_prefixes)):
                out_of_area = True
                continue
            return GeocodeResult(location, query)

    reason = "hors zone" if out_of_area else "aucun résultat"
    return GeocodeResult(UNLOCATED, last_query, reason)
