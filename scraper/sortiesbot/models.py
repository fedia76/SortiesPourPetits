"""Objets échangés entre les étages du pipeline.

Les noms de champs suivent ceux de l'API du site (`server/src/lib/validators.ts`)
quand ils s'y rapportent, pour que la construction du payload reste lisible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Candidate:
    """Une page repérée à l'étage découverte, pas encore lue en détail."""

    url: str
    title: str
    city: str = ""
    reason: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Candidate":
        return cls(
            url=str(data.get("url", "")).strip(),
            title=str(data.get("title", "")).strip(),
            city=str(data.get("city", "")).strip(),
            reason=str(data.get("reason", "")).strip(),
        )


@dataclass(frozen=True)
class Location:
    """Position obtenue auprès du géocodeur."""

    lat: float
    lng: float
    city: str
    postal_code: str

    @property
    def located(self) -> bool:
        return self.lat != 0 or self.lng != 0


#: Convention partagée avec le site : une sortie dont l'adresse n'a pas pu être
#: géocodée part avec (0, 0). Le serveur refuse alors de l'approuver tant qu'un
#: modérateur n'a pas complété l'adresse (voir server/src/lib/geo.ts).
UNLOCATED = Location(lat=0.0, lng=0.0, city="", postal_code="")


@dataclass(frozen=True)
class ExtractedEvent:
    """Sortie telle que le modèle l'a lue sur une page."""

    relevant: bool
    skip_reason: str = ""
    title: str = ""
    description: str = ""
    free: bool = False
    price: float | None = None
    age_min: int | None = None
    age_max: int | None = None
    permanent: bool = False
    date_start: str = ""
    date_end: str = ""
    open_time: str = ""
    close_time: str = ""
    setting: str = ""
    category: str = ""
    venue_name: str = ""
    venue_address: str = ""
    venue_city: str = ""
    venue_postal_code: str = ""
    photo_url: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ExtractedEvent":
        def text(key: str) -> str:
            value = data.get(key)
            return "" if value is None else str(value).strip()

        def number(key: str) -> float | None:
            value = data.get(key)
            if value is None or value == "":
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def integer(key: str) -> int | None:
            value = number(key)
            return None if value is None else int(value)

        return cls(
            relevant=bool(data.get("relevant", False)),
            skip_reason=text("skip_reason"),
            title=text("title"),
            description=text("description"),
            free=bool(data.get("free", False)),
            price=number("price"),
            age_min=integer("age_min"),
            age_max=integer("age_max"),
            permanent=bool(data.get("permanent", False)),
            date_start=text("date_start"),
            date_end=text("date_end"),
            open_time=text("open_time"),
            close_time=text("close_time"),
            setting=text("setting").upper(),
            category=text("category"),
            venue_name=text("venue_name"),
            venue_address=text("venue_address"),
            venue_city=text("venue_city"),
            venue_postal_code=text("venue_postal_code"),
            photo_url=text("photo_url"),
        )


#: Tarif d'une recherche web : 10 $ les 1000.
SEARCH_PRICE_USD = 0.01


@dataclass
class Usage:
    """Consommation cumulée d'un run, pour le résumé de fin."""

    input_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0
    web_fetches: int = 0
    #: Coût des jetons. Les recherches web se facturent à part (voir total_usd).
    cost_usd: float = 0.0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.web_searches += other.web_searches
        self.web_fetches += other.web_fetches
        self.cost_usd += other.cost_usd

    @property
    def search_cost_usd(self) -> float:
        """10 $ les 1000 recherches, facturés en plus des jetons."""
        return self.web_searches * SEARCH_PRICE_USD

    @property
    def total_usd(self) -> float:
        return self.cost_usd + self.search_cost_usd

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "web_searches": self.web_searches,
            "web_fetches": self.web_fetches,
            "token_cost_usd": round(self.cost_usd, 4),
            "search_cost_usd": round(self.search_cost_usd, 4),
            "total_usd": round(self.total_usd, 4),
        }


@dataclass
class Summary:
    """Compteurs d'un run, repris tels quels par la console d'administration."""

    candidates: int = 0
    retained: int = 0
    skipped_seen: int = 0
    skipped_blocked: int = 0
    skipped_irrelevant: int = 0
    skipped_invalid: int = 0
    ungeocoded: int = 0
    unpriced: int = 0
    submitted: int = 0
    errors: int = 0
    #: Vrai si le plafond de coût a écourté le run.
    stopped_on_budget: bool = False
    usage: Usage = field(default_factory=Usage)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidates": self.candidates,
            "retained": self.retained,
            "skipped_seen": self.skipped_seen,
            "skipped_blocked": self.skipped_blocked,
            "skipped_irrelevant": self.skipped_irrelevant,
            "skipped_invalid": self.skipped_invalid,
            "ungeocoded": self.ungeocoded,
            "unpriced": self.unpriced,
            "submitted": self.submitted,
            "errors": self.errors,
            "stopped_on_budget": self.stopped_on_budget,
            "usage": self.usage.as_dict(),
        }
