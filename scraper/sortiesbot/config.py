"""Configuration d'une recherche, chargée depuis un fichier YAML.

En v1 les configurations sont des fichiers ; elles deviendront des lignes de
la table `ScraperConfig` quand la console d'administration pilotera les runs.
Les champs sont donc volontairement plats et sérialisables tels quels.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from string import Template
from typing import Any

import yaml

from . import prompts

# Départements d'Île-de-France : un géocodage qui tombe en dehors est traité
# comme un échec, mieux vaut pas de position qu'une position fausse.
IDF_POSTAL_PREFIXES = ["75", "77", "78", "91", "92", "93", "94", "95"]

DEFAULT_BLOCKED_DOMAINS = [
    # Pages non lisibles ou sans contenu exploitable.
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "youtube.com",
    "pinterest.fr",
]


@dataclass(frozen=True)
class Config:
    """Une recherche paramétrée, telle qu'un modérateur la décrira plus tard
    dans la console d'administration."""

    name: str
    theme: str
    area: str = "Île-de-France"
    period: str = "les prochaines semaines"
    horizon_days: int = 30
    max_events: int = 20
    # Plafonds passés aux outils serveur. Ils comptent bien plus qu'il n'y
    # paraît : pendant un tour, la boucle serveur refacture en entrée tout le
    # contexte accumulé à CHACUNE de ses itérations. Chaque page lue est donc
    # payée plusieurs fois, et c'est `max_page_tokens` qui pèse le plus lourd.
    max_searches: int = 6
    max_fetches: int = 5
    #: Taille maximale d'une page lue à la découverte. On n'y cherche que des
    #: liens et des titres, mais trop court tronque la page avant sa liste
    #: d'événements — c'est-à-dire avant ce qu'on est venu chercher.
    max_page_tokens: int = 12_000
    #: Le run s'arrête s'il dépasse ce coût en jetons (dollars). Garde-fou de
    #: dernier recours, vérifié entre deux étages.
    max_cost_usd: float = 0.50
    default_category: str = "Non classé"
    postal_prefixes: list[str] = field(default_factory=lambda: list(IDF_POSTAL_PREFIXES))
    blocked_domains: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_DOMAINS))
    provider: str = "anthropic"
    discovery_model: str = "claude-haiku-4-5"
    extraction_model: str = "claude-haiku-4-5"
    discovery_prompt: str = prompts.DISCOVERY
    extraction_prompt: str = prompts.EXTRACTION

    @property
    def date_from(self) -> date:
        return date.today()

    @property
    def date_to(self) -> date:
        return date.today() + timedelta(days=self.horizon_days)

    def render_discovery(self) -> str:
        return Template(self.discovery_prompt).safe_substitute(
            theme=self.theme,
            area=self.area,
            period=self.period,
            today=date.today().isoformat(),
            date_from=self.date_from.isoformat(),
            date_to=self.date_to.isoformat(),
            max_events=self.max_events,
            # Le prompt doit annoncer le même quota que celui imposé aux
            # outils : sinon le modèle tente des recherches qui échouent en
            # `max_uses_exceeded`.
            max_searches=self.max_searches,
            max_fetches=self.max_fetches,
        )

    def render_extraction(self, url: str, categories: list[str]) -> str:
        return Template(self.extraction_prompt).safe_substitute(
            url=url,
            today=date.today().isoformat(),
            categories=", ".join(categories) if categories else self.default_category,
        )


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> Config:
    """Lit un YAML de configuration. Les clés absentes prennent leur défaut."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as err:
        raise ConfigError(f"Configuration introuvable : {path}") from err
    except yaml.YAMLError as err:
        raise ConfigError(f"YAML invalide dans {path} : {err}") from err

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} doit contenir un dictionnaire de clés")

    known = {f for f in Config.__dataclass_fields__}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(
            f"Clés inconnues dans {path} : {', '.join(unknown)}. "
            f"Clés acceptées : {', '.join(sorted(known))}"
        )
    for required in ("name", "theme"):
        if not raw.get(required):
            raise ConfigError(f"{path} : la clé « {required} » est obligatoire")

    config = Config(**raw)
    if config.max_events < 1:
        raise ConfigError("max_events doit valoir au moins 1")
    if config.horizon_days < 1:
        raise ConfigError("horizon_days doit valoir au moins 1")
    return config


def with_limit(config: Config, limit: int | None) -> Config:
    """Applique un plafond de sorties venu de la ligne de commande.

    Le budget de recherche suit la même réduction : sans ça, un essai à trois
    sorties coûterait autant qu'un run complet — la découverte, qui est la
    partie chère, tournerait à pleine taille pour ne rien en faire.
    """
    if limit is None:
        return config
    events = min(config.max_events, max(1, limit))
    ratio = events / config.max_events
    return replace(
        config,
        max_events=events,
        max_searches=max(2, round(config.max_searches * ratio)),
        # Plancher à trois pages : une page refusée (robots.txt) ou pauvre en
        # liens ne doit pas suffire à faire échouer toute la découverte.
        max_fetches=max(3, round(config.max_fetches * ratio)),
    )


@dataclass(frozen=True)
class Environment:
    """Secrets et points d'entrée, lus dans l'environnement (voir .env.example)."""

    api_url: str
    api_key: str | None
    anthropic_key: str | None

    @classmethod
    def from_env(cls) -> "Environment":
        return cls(
            api_url=os.environ.get("SPP_API_URL", "http://localhost:3000").rstrip("/"),
            api_key=os.environ.get("SPP_API_KEY") or None,
            anthropic_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        )


def load_dotenv(path: str | Path) -> None:
    """Charge un fichier .env sans écraser l'environnement déjà en place.

    Volontairement minimal (pas de dépendance supplémentaire) : `CLE=valeur`,
    lignes vides et commentaires.
    """
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def describe(config: Config) -> dict[str, Any]:
    """Résumé de la configuration pour l'en-tête du journal de run."""
    return {
        "name": config.name,
        "theme": config.theme,
        "area": config.area,
        "period": config.period,
        "date_from": config.date_from.isoformat(),
        "date_to": config.date_to.isoformat(),
        "max_events": config.max_events,
        "provider": config.provider,
        "discovery_model": config.discovery_model,
        "extraction_model": config.extraction_model,
    }
