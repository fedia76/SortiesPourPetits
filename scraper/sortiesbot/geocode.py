"""Géocodage des lieux : Photon d'abord, Base Adresse Nationale en secours.

Photon (OpenStreetMap) est le fournisseur du formulaire du site
(`client/src/lib/geocode.ts`), pour que les positions saisies à la main et
celles du scraper viennent de la même source. Il connaît aussi les lieux
d'intérêt — parcs, musées, théâtres — ce qui compte ici : les pages
d'événement donnent souvent un nom de salle plutôt qu'une adresse.

Mais son instance publique est en « fair use » et refuse les clients qu'elle
n'aime pas : un run entier a rendu vingt sorties non géolocalisées sur vingt,
toutes sur des 403. D'où deux précautions — on s'annonce avec un User-Agent
identifiable, et la Base Adresse Nationale prend le relais si Photon se
dérobe. Elle ne connaît que les adresses, mais elle est gratuite, publique et
sans quota.

Le contrôle porte sur le pays : une position hors de France est traitée comme
un échec, parce que c'est le signe d'une homonymie — il y a un Montreuil au
Québec. Le département, lui, n'est plus une condition : une sortie voisine de
la zone visée reste une bonne sortie.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

import requests

from .harvest import USER_AGENT
from .models import UNLOCATED, ExtractedEvent, Location

PHOTON_URL = "https://photon.komoot.io/api/"
BAN_URL = "https://api-adresse.data.gouv.fr/search/"

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


#: Passe à faux dès la première rebuffade de Photon : inutile de rejouer un
#: 403 pour chacune des vingt sorties d'un run.
_photon_available = True


def _photon_search(query: str) -> list[dict[str, Any]]:
    response = requests.get(
        PHOTON_URL,
        params={"q": query, "limit": 5, "lang": "fr", **_BIAS},
        headers={"User-Agent": USER_AGENT},
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    return body.get("features", []) if isinstance(body, dict) else []


def _ban_search(query: str) -> list[dict[str, Any]]:
    """Base Adresse Nationale : adresses françaises uniquement, même forme de
    réponse que Photon (`features` avec `postcode` et `city`)."""
    response = requests.get(
        BAN_URL,
        params={"q": query, "limit": 5},
        headers={"User-Agent": USER_AGENT},
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    return body.get("features", []) if isinstance(body, dict) else []


def _search(query: str) -> list[dict[str, Any]]:
    """Photon, puis la BAN s'il refuse ou ne trouve rien."""
    global _photon_available
    if _photon_available:
        try:
            results = _photon_search(query)
            if results:
                return results
        except requests.RequestException:
            _photon_available = False
    return _ban_search(query)


def _in_france(props: dict[str, Any]) -> bool:
    """Photon donne le pays ; la BAN est française par construction."""
    code = str(props.get("countrycode") or props.get("country") or "").strip().upper()
    return code in ("", "FR", "FRANCE")


def _to_location(feature: dict[str, Any]) -> Location | None:
    props = feature.get("properties") or {}
    if not _in_france(props):
        return None
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
    search: Callable[[str], list[dict[str, Any]]] | None = None,
) -> GeocodeResult:
    """Cherche la position d'un lieu ; retourne `UNLOCATED` en cas d'échec.

    `search` est injectable pour les tests ; par défaut c'est Photon avec
    repli sur la Base Adresse Nationale.
    """
    search = search or _search
    last_query = event.venue_name or event.venue_city or "(lieu inconnu)"

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
                # Sans code postal, la réponse est trop vague : on tente la
                # requête suivante, plus précise.
                continue
            return GeocodeResult(location, query)

    return GeocodeResult(UNLOCATED, last_query, "aucun résultat")
