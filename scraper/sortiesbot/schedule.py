"""Dates réelles d'une sortie, quand la page permet de les connaître.

Le site ne stocke aujourd'hui qu'une plage : un spectacle joué tous les
dimanches de juillet et août y devient « du 1er juillet au 31 août », donc
proposé un jeudi. C'est faux, pas approximatif.

Trois sources, de la plus sûre à la plus faible :

1. le **JSON-LD** `schema.org/Event` que beaucoup de sites publient pour
   Google — chaque représentation y a sa date exacte. Gratuit, déterministe,
   aucun JavaScript à exécuter : c'est dans le HTML qu'on a déjà téléchargé ;
2. les **dates annoncées** en clair sur la page (« les 3, 7 et 12 août »),
   que le modèle relève à l'extraction ;
3. la **récurrence** lue dans la prose (« tous les dimanches à 15h »), que le
   modèle rend sous forme de jours de la semaine et qu'on déroule ici.

Faute des trois, on retombe sur le comportement actuel : la plage vaut pour
tous ses jours.

Ce module ne fait que calculer et mesurer — rien n'est encore envoyé au site.
Le but de cette étape est de savoir, sur de vrais runs, à quelle fréquence
chaque source répond, avant de toucher au schéma de la base.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

#: Jours de la semaine tels que le modèle les rend, vers leur numéro ISO.
WEEKDAYS: dict[str, int] = {
    "lundi": 1,
    "mardi": 2,
    "mercredi": 3,
    "jeudi": 4,
    "vendredi": 5,
    "samedi": 6,
    "dimanche": 7,
}

#: Au-delà, dérouler n'apprend plus rien : c'est une sortie permanente qui
#: s'ignore, et on ne va pas fabriquer mille dates pour le dire.
MAX_OCCURRENCES = 400

#: D'où viennent les dates, du plus sûr au plus faible.
SOURCE_JSON_LD = "json-ld"
SOURCE_ANNOUNCED = "dates annoncées"
SOURCE_WEEKDAYS = "récurrence"
SOURCE_RANGE = "plage"


@dataclass(frozen=True)
class Schedule:
    """Ce qu'on sait des dates réelles d'une sortie."""

    dates: tuple[str, ...] = ()
    weekdays: tuple[str, ...] = ()
    source: str = SOURCE_RANGE

    @property
    def precise(self) -> bool:
        """Vrai si on sait mieux que « tous les jours de la plage »."""
        return self.source != SOURCE_RANGE

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "count": len(self.dates),
            "weekdays": list(self.weekdays),
            "dates": list(self.dates),
        }


def parse_date(value: str) -> date | None:
    """Une date ISO, éventuellement suivie d'une heure et d'un fuseau.

    Le JSON-LD écrit aussi bien `2026-07-05` que
    `2026-07-05T15:00:00+02:00` : seule la partie date nous intéresse ici.
    """
    text = (value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def normalize_weekdays(values: object) -> tuple[str, ...]:
    """Garde les jours reconnus, dans l'ordre de la semaine, sans doublon."""
    if not isinstance(values, (list, tuple)):
        return ()
    kept = {
        str(v).strip().lower()
        for v in values
        if str(v).strip().lower() in WEEKDAYS
    }
    return tuple(sorted(kept, key=lambda day: WEEKDAYS[day]))


def expand(start: date, end: date, weekdays: tuple[str, ...]) -> list[str]:
    """Déroule une plage en ne gardant que les jours de représentation."""
    wanted = {WEEKDAYS[day] for day in weekdays}
    dates: list[str] = []
    day = start
    while day <= end and len(dates) < MAX_OCCURRENCES:
        if day.isoweekday() in wanted:
            dates.append(day.isoformat())
        day += timedelta(days=1)
    return dates


def _clean(values: object, start: date | None, end: date | None) -> list[str]:
    """Dates valides, triées, dédoublonnées, et dans la plage si on la connaît.

    Une page de spectacle liste souvent les représentations d'autres salles ou
    d'autres saisons ; la plage sert de garde-fou.
    """
    if not isinstance(values, (list, tuple)):
        return []
    kept: set[date] = set()
    for value in values:
        day = parse_date(str(value))
        if day is None:
            continue
        if start and day < start:
            continue
        if end and day > end:
            continue
        kept.add(day)
    return [day.isoformat() for day in sorted(kept)]


def resolve(
    date_start: str,
    date_end: str,
    weekdays: object = (),
    announced: object = (),
    json_ld: object = (),
) -> Schedule:
    """Meilleure connaissance possible des dates, source la plus sûre d'abord."""
    start = parse_date(date_start)
    end = parse_date(date_end) or start
    days = normalize_weekdays(weekdays)

    for values, source in ((json_ld, SOURCE_JSON_LD), (announced, SOURCE_ANNOUNCED)):
        dates = _clean(values, start, end)
        if dates:
            return Schedule(dates=tuple(dates), weekdays=days, source=source)

    # Sept jours sur sept, c'est la plage elle-même : autant le dire ainsi.
    if days and len(days) < 7 and start and end:
        dates = expand(start, end, days)
        if dates:
            return Schedule(dates=tuple(dates), weekdays=days, source=SOURCE_WEEKDAYS)

    return Schedule(weekdays=days, source=SOURCE_RANGE)
