"""Construction du corps envoyé à `POST /api/events`.

Les règles reproduites ici sont celles de `server/src/lib/validators.ts` : on
les applique avant l'envoi pour transformer une extraction imparfaite en
proposition acceptable — ou pour l'écarter en le disant, plutôt que de
collectionner des 400 côté serveur.

Ce qui peut être réparé sans mentir l'est (troncatures, bornes d'âge, horaires
incohérents). Ce qui manque et ne peut pas être deviné part avec une valeur
convenue que la modération sait reconnaître (tarif à `UNKNOWN_PRICE`, position
à zéro). Restent les sorties inexploitables — sans titre, sans description,
sans date — écartées avec leur motif dans le journal du run.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .models import ExtractedEvent, Location

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SETTINGS = {"INDOOR", "OUTDOOR", "BOTH"}

TITLE_MAX = 150
DESCRIPTION_MIN = 10
DESCRIPTION_MAX = 10_000
VENUE_NAME_MAX = 120
ADDRESS_MAX = 255
CITY_MAX = 120
SOURCE_URL_MAX = 500
PRICE_MAX = 100_000

#: Valeurs de remplissage pour une sortie soumise sans géocodage : le serveur
#: exige une ville et un code postal, le modérateur les corrigera avec l'adresse.
CITY_PLACEHOLDER = "À préciser"
POSTAL_PLACEHOLDER = "00000"

#: Tarif qu'aucune lecture n'a permis de déterminer. Le site connaît cette
#: convention (server/src/lib/incomplete.ts) : la sortie est proposée, la
#: modération la signale et refuse de l'approuver tant qu'elle n'est pas
#: corrigée. Un prix négatif est impossible à confondre avec la gratuité.
UNKNOWN_PRICE = -1


class Rejected(Exception):
    """La sortie ne peut pas être proposée sans inventer une information."""


class OutOfPeriod(Rejected):
    """La sortie est bonne, mais commence après la fenêtre demandée.

    Distincte de `Rejected` : elle n'a rien d'inexploitable, et une
    configuration qui ne se veut pas stricte la garde.
    """


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip(" ,;:.") + "…"


def _parse_date(value: str) -> date | None:
    if not DATE_RE.match(value or ""):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _clean_times(open_time: str, close_time: str) -> tuple[str | None, str | None]:
    start = open_time if TIME_RE.match(open_time or "") else None
    end = close_time if TIME_RE.match(close_time or "") else None
    # Le serveur refuse une fermeture qui précède l'ouverture : dans le doute,
    # on préfère une sortie sans horaires à une sortie rejetée.
    if start and end and start >= end:
        return None, None
    return start, end


def _clean_ages(age_min: int | None, age_max: int | None) -> tuple[int | None, int | None]:
    if age_min is not None and age_max is not None and age_min > age_max:
        age_min, age_max = age_max, age_min
    if age_min is not None:
        age_min = max(0, min(17, age_min))
    if age_max is not None:
        age_max = max(0, min(18, age_max))
    if age_min is not None and age_max is not None and age_min > age_max:
        return None, None
    return age_min, age_max


def _clean_postal_code(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits if 4 <= len(digits) <= 10 else POSTAL_PLACEHOLDER


def _clean_dates(
    event: ExtractedEvent, today: date, until: date | None
) -> tuple[bool, str | None, str | None]:
    if event.permanent:
        return True, None, None

    start = _parse_date(event.date_start)
    end = _parse_date(event.date_end)
    if start is None and end is None:
        raise Rejected("ni dates ni caractère permanent")
    # Une seule date connue : la sortie tient sur ce jour-là.
    start = start or end
    end = end or start
    assert start is not None and end is not None
    if end < start:
        start, end = end, start
    if end < today:
        raise Rejected(f"sortie déjà terminée le {end.isoformat()}")
    # La période de la configuration est une contrainte : une sortie qui
    # commence après n'a rien à faire dans ce run, même si elle est bonne.
    if until is not None and start > until:
        raise OutOfPeriod(f"commence le {start.isoformat()}, après la période demandée")
    return False, start.isoformat(), end.isoformat()


def build_payload(
    event: ExtractedEvent,
    location: Location,
    category_id: int,
    source_url: str,
    today: date | None = None,
    until: date | None = None,
) -> dict[str, Any]:
    """Corps prêt pour l'API, ou `Rejected` avec le motif."""
    today = today or date.today()

    title = _truncate(event.title, TITLE_MAX)
    if len(title) < 3:
        raise Rejected("titre absent ou trop court")

    description = _truncate(event.description, DESCRIPTION_MAX)
    if len(description) < DESCRIPTION_MIN:
        raise Rejected("description absente ou trop courte")

    price = event.price
    if price is not None and not (0 <= price <= PRICE_MAX):
        price = None
    # Un tarif introuvable ne fait pas perdre la sortie : elle part avec la
    # valeur convenue et c'est le modérateur qui tranche.
    if not event.free and price is None:
        price = UNKNOWN_PRICE

    permanent, date_start, date_end = _clean_dates(event, today, until)
    open_time, close_time = _clean_times(event.open_time, event.close_time)
    age_min, age_max = _clean_ages(event.age_min, event.age_max)

    venue_name = _truncate(event.venue_name or event.venue_city or title, VENUE_NAME_MAX)
    if not venue_name:
        raise Rejected("lieu absent")
    address = _truncate(event.venue_address or venue_name, ADDRESS_MAX)
    city = _truncate(location.city or event.venue_city or CITY_PLACEHOLDER, CITY_MAX)
    postal_code = _clean_postal_code(location.postal_code or event.venue_postal_code)

    return {
        "title": title,
        "description": description,
        "sourceUrl": source_url[:SOURCE_URL_MAX] if source_url.startswith("http") else None,
        "isFree": bool(event.free),
        "price": None if event.free else round(float(price), 2),  # type: ignore[arg-type]
        "ageMin": age_min,
        "ageMax": age_max,
        "isPermanent": permanent,
        "dateStart": date_start,
        "dateEnd": date_end,
        # Jours de représentation, remplis juste après par le pipeline : ils se
        # déduisent des dates ci-dessus, une fois celles-ci nettoyées. Vide =
        # tous les jours de la période, ce que le site sait interpréter.
        "dates": [],
        "openTime": open_time,
        "closeTime": close_time,
        "setting": event.setting if event.setting in SETTINGS else None,
        "categoryId": category_id,
        "venue": {
            "name": venue_name,
            "address": address,
            "city": city,
            "postalCode": postal_code,
            "lat": location.lat,
            "lng": location.lng,
        },
    }
