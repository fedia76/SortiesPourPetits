"""Objets échangés entre les étages du pipeline.

Les noms de champs suivent ceux de l'API du site (`server/src/lib/validators.ts`)
quand ils s'y rapportent, pour que la construction du payload reste lisible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FoundPage:
    """Une page remontée par la recherche. Rien de plus.

    La découverte ne juge pas : elle rend ce que le moteur a trouvé, et c'est
    la reconnaissance qui constate, sur le HTML, si la page liste des sorties
    ou en est une. C'est ce qui permet de remplacer le moteur sans toucher au
    reste — un moteur rend des URL, il ne rend pas des avis.
    """

    url: str
    title: str = ""
    #: La requête qui l'a remontée. Sert la filiation, pas la décision.
    query: str = ""


@dataclass(frozen=True)
class Candidate:
    """Une page à lire, repérée dans un agenda ou donnée en point de départ."""

    url: str
    title: str
    source: str = ""
    context: str = ""
    #: Page de programme : elle porte plusieurs sorties, à relever d'un coup.
    #: Seul le mode « site » en produit ; ailleurs une page vaut une sortie.
    multiple: bool = False



#: Les signaux de l'attribution, du plus sûr au moins sûr. L'ordre est celui
#: de la cascade, et il voyage jusqu'au site : le modérateur voit d'où sort le
#: lien qu'on lui propose, ce qui n'est pas la même confiance selon la ligne.
SIGNAL_JSON_LD = "json_ld"
SIGNAL_VENUE_DOMAIN = "venue_domain"
SIGNAL_PAGE_LINK = "page_link"
SIGNAL_SEARCH = "search"


@dataclass(frozen=True)
class SourceLink:
    """La page qui fait autorité sur une sortie, quand on a su la trouver.

    Trois champs, et le troisième est le plus important : `checked` dit que la
    page a été **ouverte et reconnue**, pas seulement devinée. Sans lui, ce
    serait une URL plausible — et une source fausse est pire qu'une source
    absente, parce qu'elle a l'air d'une réponse.

    `SourceLink()` vide est le cas normal quand la page lue est déjà celle de
    l'organisateur : il n'y avait rien à remonter.
    """

    url: str = ""
    #: Lequel des quatre signaux a désigné cette page.
    signal: str = ""
    #: Ce qui a décidé, en une poignée de mots, pour le journal et le registre.
    detail: str = ""
    #: La page a été téléchargée et parle bien de cette sortie.
    checked: bool = False

    @property
    def found(self) -> bool:
        """Une source n'existe que vérifiée. C'est toute la règle de l'étage."""
        return bool(self.url) and self.checked


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
    #: La page ne décrit pas *une* sortie : elle en présente plusieurs. C'est
    #: la reconnaissance qui s'est trompée, et l'extraction s'en aperçoit la
    #: première — elle a lu le texte, ce que personne n'avait fait avant elle.
    #: L'orchestrateur la requalifie alors en programme et la relit d'un bloc.
    several: bool = False
    title: str = ""
    description: str = ""
    free: bool = False
    price: float | None = None
    age_min: int | None = None
    age_max: int | None = None
    permanent: bool = False
    date_start: str = ""
    date_end: str = ""
    #: Jours de représentation lus dans la prose (« tous les dimanches »).
    #: C'est ce qui distingue un spectacle du dimanche d'une plage continue.
    weekdays: tuple[str, ...] = ()
    #: Dates annoncées une à une par la page (« les 3, 7 et 12 août »).
    dates: tuple[str, ...] = ()
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

        def strings(key: str) -> tuple[str, ...]:
            value = data.get(key)
            if not isinstance(value, (list, tuple)):
                return ()
            return tuple(str(v).strip() for v in value if str(v).strip())

        return cls(
            relevant=bool(data.get("relevant", False)),
            skip_reason=text("skip_reason"),
            several=bool(data.get("several")),
            title=text("title"),
            description=text("description"),
            free=bool(data.get("free", False)),
            price=number("price"),
            age_min=integer("age_min"),
            age_max=integer("age_max"),
            permanent=bool(data.get("permanent", False)),
            date_start=text("date_start"),
            date_end=text("date_end"),
            weekdays=strings("weekdays"),
            dates=strings("dates"),
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
#: Ce que coûte une recherche web, par défaut. C'est le tarif de l'outil
#: serveur d'Anthropic ; un moteur ordinaire facture bien moins, et pose donc
#: son propre prix. D'où un montant **porté** par l'usage plutôt que dérivé
#: d'un compteur : deux fournisseurs ne facturent pas au même tarif.
SEARCH_PRICE_USD = 0.01


@dataclass
class Usage:
    """Consommation cumulée d'un run, pour le résumé de fin."""

    input_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0
    #: Coût des jetons. Les recherches se facturent à part.
    cost_usd: float = 0.0
    #: Coût des recherches, au tarif du moteur qui les a lancées. Porté et non
    #: calculé : Anthropic facture dix dollars les mille, un moteur ordinaire
    #: bien moins, et un run peut mêler les deux.
    search_cost_usd: float = 0.0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.web_searches += other.web_searches
        self.cost_usd += other.cost_usd
        self.search_cost_usd += other.search_cost_usd

    @property
    def total_usd(self) -> float:
        return self.cost_usd + self.search_cost_usd

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "web_searches": self.web_searches,
            "token_cost_usd": round(self.cost_usd, 4),
            "search_cost_usd": round(self.search_cost_usd, 4),
            "total_usd": round(self.total_usd, 4),
        }


@dataclass
class Summary:
    """Compteurs d'un run, repris tels quels par la console d'administration."""

    candidates: int = 0
    #: Pages d'agenda téléchargées et dépouillées (gratuit).
    pages: int = 0
    retained: int = 0
    skipped_seen: int = 0
    skipped_blocked: int = 0
    skipped_irrelevant: int = 0
    #: Sorties listées par deux agendas différents.
    duplicates: int = 0
    #: Sorties gardées bien qu'en dehors de la fenêtre visée : la
    #: configuration oriente la recherche, elle ne filtre pas le résultat.
    out_of_period: int = 0
    out_of_area: int = 0
    skipped_invalid: int = 0
    ungeocoded: int = 0
    unpriced: int = 0
    #: Sorties dont on connaît les dates réelles, et non la seule plage.
    #: Mesure de l'étape en cours : savoir si ça vaut une table en base.
    scheduled: int = 0
    submitted: int = 0
    errors: int = 0
    #: Vrai si le plafond de coût a écourté le run.
    stopped_on_budget: bool = False
    usage: Usage = field(default_factory=Usage)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidates": self.candidates,
            "pages": self.pages,
            "retained": self.retained,
            "skipped_seen": self.skipped_seen,
            "skipped_blocked": self.skipped_blocked,
            "skipped_irrelevant": self.skipped_irrelevant,
            "duplicates": self.duplicates,
            "out_of_period": self.out_of_period,
            "out_of_area": self.out_of_area,
            "skipped_invalid": self.skipped_invalid,
            "ungeocoded": self.ungeocoded,
            "unpriced": self.unpriced,
            "scheduled": self.scheduled,
            "submitted": self.submitted,
            "errors": self.errors,
            "stopped_on_budget": self.stopped_on_budget,
            "usage": self.usage.as_dict(),
        }
