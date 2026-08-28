"""Configuration d'une recherche.

Deux origines, un seul objet `Config` :

* un fichier YAML (`configs/*.yaml`), pour les runs lancés à la main ;
* une ligne de la table `ScraperConfig` du site, que la console
  d'administration édite et que le worker reçoit en JSON.

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
    #: Recherches web lancées (0,01 $ pièce, plus les résultats en contexte).
    max_searches: int = 6
    #: Pages d'agenda ouvertes. Elles sont téléchargées en Python : gratuites.
    max_agendas: int = 6
    #: Liens retenus par agenda, pour ne pas noyer l'étage extraction.
    max_links_per_agenda: int = 8
    #: Caractères de page transmis au modèle à l'extraction (~4 jetons pour
    #: 3 caractères en français).
    max_page_chars: int = 8_000
    #: Plafond de coût du run, en dollars. Vérifié avant chaque appel payant.
    max_cost_usd: float = 1.00
    default_category: str = "Non classé"
    #: Le thème, la période et la zone orientent les recherches et le tri des
    #: liens — c'est là qu'ils servent. Une fois la page lue, elle est payée :
    #: la garder ne coûte plus rien, et le site sait filtrer par date et par
    #: distance. Passer à false pour un run strictement cantonné à sa fenêtre.
    keep_out_of_scope: bool = True
    #: Départements visés par la recherche. Sert au tri, et au filtre strict
    #: si `keep_out_of_scope` est désactivé.
    postal_prefixes: list[str] = field(default_factory=lambda: list(IDF_POSTAL_PREFIXES))
    blocked_domains: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_DOMAINS))
    provider: str = "anthropic"
    #: Chacun des trois appels est borné : Haiku suffit partout.
    search_model: str = "claude-haiku-4-5"
    select_model: str = "claude-haiku-4-5"
    extraction_model: str = "claude-haiku-4-5"
    search_prompt: str = prompts.SEARCH
    select_prompt: str = prompts.SELECT
    extraction_prompt: str = prompts.EXTRACTION

    @property
    def date_from(self) -> date:
        return date.today()

    @property
    def date_to(self) -> date:
        return date.today() + timedelta(days=self.horizon_days)

    def render_search(self) -> str:
        return Template(self.search_prompt).safe_substitute(
            theme=self.theme,
            area=self.area,
            period=self.period,
            today=date.today().isoformat(),
            date_from=self.date_from.isoformat(),
            date_to=self.date_to.isoformat(),
            # Le prompt annonce le même quota que celui imposé à l'outil,
            # sinon le modèle tente des recherches qui échouent.
            max_searches=self.max_searches,
        )

    def render_select(self, page: str, links: str) -> str:
        return Template(self.select_prompt).safe_substitute(
            page=page,
            links=links,
            theme=self.theme,
            area=self.area,
            today=date.today().isoformat(),
            date_from=self.date_from.isoformat(),
            date_to=self.date_to.isoformat(),
            max_links=self.max_links_per_agenda,
        )

    def render_extraction(self, url: str, content: str, categories: list[str]) -> str:
        return Template(self.extraction_prompt).safe_substitute(
            url=url,
            content=content,
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


def _split(value: Any, fallback: list[str]) -> list[str]:
    """« 75, 77,78 » → ["75", "77", "78"]. Vide : on garde la liste par défaut."""
    if isinstance(value, list):
        items = [str(v).strip() for v in value]
    else:
        items = [part.strip() for part in str(value or "").split(",")]
    items = [item for item in items if item]
    return items or fallback


def config_from_api(raw: dict[str, Any]) -> Config:
    """Traduit une configuration du site (JSON camelCase) en `Config`.

    Une clé absente reprend le défaut du dataclass, et un prompt vide veut
    dire « garde celui du scraper » — la console l'affiche ainsi.
    """
    if not raw.get("name") or not raw.get("theme"):
        raise ConfigError("Configuration incomplète : « name » et « theme » sont obligatoires")

    def prompt(key: str, default: str) -> str:
        value = raw.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else default

    def number(key: str, default: float) -> float:
        value = raw.get(key)
        try:
            return default if value is None else float(value)
        except (TypeError, ValueError):
            return default

    def integer(key: str, default: int) -> int:
        return int(number(key, default))

    defaults = Config(name=str(raw["name"]), theme=str(raw["theme"]))
    return replace(
        defaults,
        area=str(raw.get("area") or defaults.area),
        period=str(raw.get("period") or defaults.period),
        horizon_days=integer("horizonDays", defaults.horizon_days),
        max_events=integer("maxEvents", defaults.max_events),
        max_searches=integer("maxSearches", defaults.max_searches),
        max_agendas=integer("maxAgendas", defaults.max_agendas),
        max_links_per_agenda=integer("maxLinksPerAgenda", defaults.max_links_per_agenda),
        max_page_chars=integer("maxPageChars", defaults.max_page_chars),
        max_cost_usd=number("maxCostUsd", defaults.max_cost_usd),
        keep_out_of_scope=bool(raw.get("keepOutOfScope", defaults.keep_out_of_scope)),
        default_category=str(raw.get("defaultCategory") or defaults.default_category),
        postal_prefixes=_split(raw.get("postalPrefixes"), defaults.postal_prefixes),
        blocked_domains=_split(raw.get("blockedDomains"), defaults.blocked_domains),
        search_model=str(raw.get("searchModel") or defaults.search_model),
        select_model=str(raw.get("selectModel") or defaults.select_model),
        extraction_model=str(raw.get("extractionModel") or defaults.extraction_model),
        search_prompt=prompt("searchPrompt", defaults.search_prompt),
        select_prompt=prompt("selectPrompt", defaults.select_prompt),
        extraction_prompt=prompt("extractionPrompt", defaults.extraction_prompt),
    )


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
        # Plancher à deux agendas : un site refusé par robots.txt ou pauvre en
        # liens ne doit pas suffire à faire échouer tout le run.
        max_agendas=max(2, round(config.max_agendas * ratio)),
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
        "max_searches": config.max_searches,
        "max_agendas": config.max_agendas,
        "provider": config.provider,
        "search_model": config.search_model,
        "select_model": config.select_model,
        "extraction_model": config.extraction_model,
    }
