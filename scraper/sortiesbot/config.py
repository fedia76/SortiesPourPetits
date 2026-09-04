"""Configuration d'une recherche.

Deux modes, décidés par le champ `mode` et jamais mélangés :

* `recherche` — le mode historique : le modèle lance des recherches web, on
  dépouille les agendas qu'elles remontent ;
* `site` — on connaît déjà l'adresse (le site d'un festival, la saison d'un
  théâtre) : aucune recherche web n'est lancée, `seed_urls` sert de point de
  départ. Une page qui ne mène à rien est lue comme un programme, c'est-à-dire
  qu'on en tire plusieurs sorties d'un coup.

Une configuration écrite avant l'ajout du mode ne porte pas ce champ : elle
prend le défaut, `recherche`, et emprunte exactement le chemin d'avant.

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

#: Mode historique : le modèle cherche sur le web, puis on dépouille.
MODE_SEARCH = "recherche"
#: Mode ciblé : on part d'URLs connues, sans la moindre recherche web.
MODE_SITE = "site"
MODES = (MODE_SEARCH, MODE_SITE)

#: Qui lance les recherches. Le modèle reste derrière dans les deux cas.
PROVIDERS = ("anthropic", "serper")

#: Sites qui **republient** l'information sans en être la source. On les lit
#: volontiers — ce sont d'excellents agendas, c'est même pour ça qu'ils
#: remontent en tête des recherches — mais leur URL n'est jamais celle qu'on
#: propose au parent : derrière chaque fiche il y a un musée, un théâtre, une
#: mairie, et c'est sa page qui fait autorité. Distincte de
#: `DEFAULT_BLOCKED_DOMAINS`, qui, elle, empêche de lire.
DEFAULT_AGGREGATOR_DOMAINS = [
    "kidiklik.fr",
    "citizenkid.com",
    "parismomes.fr",
    "familyinparis.fr",
    "sortiraparis.com",
    "parisetudiant.com",
    "unjourdeplusaparis.com",
    "offi.fr",
    "timeout.fr",
    "lylo.fr",
    "petitfute.com",
    "tripadvisor.fr",
    "infolocale.fr",
    "wherevent.com",
    "agendaculturel.fr",
]

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
    #: `recherche` (défaut) ou `site` — voir l'en-tête du module.
    mode: str = MODE_SEARCH
    #: Points de départ du mode `site`. Sans objet en mode `recherche`.
    seed_urls: list[str] = field(default_factory=list)
    area: str = "Île-de-France"
    period: str = "les prochaines semaines"
    horizon_days: int = 30
    max_events: int = 20
    #: Recherches web lancées (0,01 $ pièce, plus les résultats en contexte).
    max_searches: int = 6
    #: Pages d'agenda ouvertes. Elles sont téléchargées en Python : gratuites.
    max_agendas: int = 6
    #: Pages suivantes d'un même agenda. Zéro : on s'arrête à la première.
    #: Chacune coûte un téléchargement, une seconde d'attente polie, et un
    #: appel de tri — d'où un plafond bas par défaut.
    max_next_pages: int = 2
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
    #: Sites dont l'URL ne peut jamais servir de source (voir la constante).
    #: Les vider ne désactive pas l'attribution : une fiche d'organisateur qui
    #: renvoie chez lui reste préférable, d'où qu'elle vienne.
    #:
    #: Côté site, cette liste n'appartient plus à une recherche : elle est
    #: commune, tenue dans la page « Agrégateurs » de la console, et le serveur
    #: l'envoie ici telle qu'elle est au moment du run.
    aggregator_domains: list[str] = field(
        default_factory=lambda: list(DEFAULT_AGGREGATOR_DOMAINS)
    )
    #: Ne pas seulement remonter à la source depuis un agrégateur : ne pas le
    #: lire du tout. Les agrégateurs rejoignent alors `blocked_domains`, donc
    #: la recherche les exclut et le dépouillement les refuse. À réserver aux
    #: recherches qui veulent du premier ressort — c'est aussi renoncer aux
    #: meilleurs agendas du web francophone.
    block_aggregators: bool = False
    #: Autorise l'étage attribution à **chercher** la page officielle quand la
    #: page lue ne la porte pas. C'est le seul appel payant de cet étage
    #: (~0,001 $ la fiche) et le seul qui puisse être coupé : les signaux
    #: gratuits, eux, tournent toujours.
    source_search: bool = True
    provider: str = "anthropic"
    #: Chacun des trois appels est borné : Haiku suffit partout.
    #: Modèle qui tranche la nature d'une page quand les signaux certains se
    #: taisent. Vide : on ne demande à personne, la page reste « inconnue » —
    #: et l'orchestrateur la traite en agenda, comme avant.
    classify_model: str = "claude-haiku-4-5"
    search_model: str = "claude-haiku-4-5"
    select_model: str = "claude-haiku-4-5"
    extraction_model: str = "claude-haiku-4-5"
    search_prompt: str = prompts.SEARCH
    #: Requêtes web à lancer. Vides : un appel au modèle les formule, ce qui
    #: coûte quelques centimes de centime et varie d'un run à l'autre. Les
    #: fournir les fige — donc les rend comparables d'une semaine sur l'autre.
    queries: list[str] = field(default_factory=list)
    queries_prompt: str = prompts.QUERIES
    classify_prompt: str = prompts.CLASSIFY
    select_prompt: str = prompts.SELECT
    extraction_prompt: str = prompts.EXTRACTION
    #: Lecture d'une page de programme, qui porte plusieurs sorties.
    extraction_multi_prompt: str = prompts.EXTRACTION_MULTI

    @property
    def targets_site(self) -> bool:
        return self.mode == MODE_SITE

    @property
    def date_from(self) -> date:
        return date.today()

    @property
    def date_to(self) -> date:
        return date.today() + timedelta(days=self.horizon_days)

    def render_search(self, queries: list[str]) -> str:
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
            queries="\n".join(f"- {q}" for q in queries),
        )

    def render_queries(self) -> str:
        return Template(self.queries_prompt).safe_substitute(
            theme=self.theme,
            area=self.area,
            period=self.period,
            today=date.today().isoformat(),
            date_from=self.date_from.isoformat(),
            date_to=self.date_to.isoformat(),
            max_searches=self.max_searches,
        )

    def render_classify(self, digest: str) -> str:
        return Template(self.classify_prompt).safe_substitute(digest=digest)

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

    def render_extraction_multi(self, url: str, content: str, categories: list[str]) -> str:
        return Template(self.extraction_multi_prompt).safe_substitute(
            url=url,
            content=content,
            today=date.today().isoformat(),
            categories=", ".join(categories) if categories else self.default_category,
            theme=self.theme,
            max_events=self.max_events,
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
    return validated(config)


def validated(config: Config) -> Config:
    """Vérifie ce qui lie le mode au reste de la configuration.

    Un mode `site` sans URL de départ ne peut rien faire : il n'a pas de
    recherche pour en trouver. Autant le dire au chargement plutôt que de
    laisser un run vide le découvrir.
    """
    if config.mode not in MODES:
        raise ConfigError(
            f"mode inconnu : « {config.mode} » (connus : {', '.join(MODES)})"
        )
    if config.provider not in PROVIDERS:
        # Au chargement plutôt qu'au premier appel : une faute de frappe dans
        # la console ne doit pas se découvrir à mi-run, après des dépenses.
        raise ConfigError(
            f"fournisseur inconnu : « {config.provider} » "
            f"(connus : {', '.join(PROVIDERS)})"
        )
    urls = [u.strip() for u in config.seed_urls if u.strip()]
    for url in urls:
        if not url.startswith(("http://", "https://")):
            raise ConfigError(f"URL de départ invalide : « {url} » (http:// ou https:// attendu)")
    if config.mode == MODE_SITE and not urls:
        raise ConfigError("le mode « site » réclame au moins une URL de départ (seed_urls)")
    return replace(config, seed_urls=urls, blocked_domains=_blocked(config))


def _blocked(config: Config) -> list[str]:
    """Les domaines qu'on refuse de lire, agrégateurs compris s'il le faut.

    La case « bloquer les agrégateurs » ne tient pas une seconde liste : elle
    verse la liste commune dans celle des domaines bloqués, une fois pour
    toutes, au chargement. Les quatre endroits qui refusent une page — la
    recherche, le dépouillement, la lecture, l'attribution — continuent de ne
    connaître que `blocked_domains`, et le réglage n'a pas eu à s'y répandre.

    Idempotent : recharger une configuration déjà fusionnée ne la duplique pas.
    """
    blocked = list(config.blocked_domains)
    if config.block_aggregators:
        blocked += [d for d in config.aggregator_domains if d not in blocked]
    return blocked


def _lines(value: Any) -> list[str]:
    """Les requêtes, qu'elles viennent d'une liste YAML ou d'un texte à lignes.

    La console offre un champ libre — une requête par ligne, c'est ce qu'on
    tape naturellement — et le YAML une liste. Les deux disent la même chose.
    """
    items = value if isinstance(value, list) else str(value or "").splitlines()
    return [str(item).strip() for item in items if str(item).strip()]


def _split(value: Any, fallback: list[str]) -> list[str]:
    """« 75, 77,78 » → ["75", "77", "78"]. Vide : on garde la liste par défaut."""
    if isinstance(value, list):
        items = [str(v).strip() for v in value]
    else:
        items = [part.strip() for part in str(value or "").split(",")]
    items = [item for item in items if item]
    return items or fallback


def _urls(value: Any) -> list[str]:
    """Les URLs de départ, saisies dans la console une par ligne.

    La virgule est acceptée aussi : elle sépare déjà les autres listes de la
    console, et personne ne devrait avoir à se souvenir laquelle prend quoi.
    """
    if isinstance(value, list):
        items = [str(v) for v in value]
    else:
        items = str(value or "").replace(",", "\n").splitlines()
    return [item.strip() for item in items if item.strip()]


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
    return validated(
        replace(
            defaults,
            mode=str(raw.get("mode") or defaults.mode).strip().lower(),
            seed_urls=_urls(raw.get("seedUrls")),
            area=str(raw.get("area") or defaults.area),
            period=str(raw.get("period") or defaults.period),
            horizon_days=integer("horizonDays", defaults.horizon_days),
            max_events=integer("maxEvents", defaults.max_events),
            max_searches=integer("maxSearches", defaults.max_searches),
            max_agendas=integer("maxAgendas", defaults.max_agendas),
            max_next_pages=integer("maxNextPages", defaults.max_next_pages),
            max_links_per_agenda=integer("maxLinksPerAgenda", defaults.max_links_per_agenda),
            max_page_chars=integer("maxPageChars", defaults.max_page_chars),
            max_cost_usd=number("maxCostUsd", defaults.max_cost_usd),
            keep_out_of_scope=bool(raw.get("keepOutOfScope", defaults.keep_out_of_scope)),
            default_category=str(raw.get("defaultCategory") or defaults.default_category),
            postal_prefixes=_split(raw.get("postalPrefixes"), defaults.postal_prefixes),
            # Pas de `blockedDomains` : les pages illisibles (réseaux sociaux)
            # sont un fait du web, pas un réglage de recherche, et restent
            # celles du scraper. Ce qu'une recherche décide, c'est d'y ajouter
            # ou non les agrégateurs — d'où la case ci-dessous.
            #
            # `aggregatorDomains` présent fait foi, même vide : c'est le site
            # qui tient la liste, et l'avoir vidée exprès ne doit pas
            # ressusciter celle du scraper. Absent (un appel qui l'ignore) :
            # le défaut intégré, comme avant.
            aggregator_domains=(
                _split(raw["aggregatorDomains"], [])
                if "aggregatorDomains" in raw
                else list(defaults.aggregator_domains)
            ),
            block_aggregators=bool(
                raw.get("blockAggregators", defaults.block_aggregators)
            ),
            source_search=bool(raw.get("sourceSearch", defaults.source_search)),
            provider=str(raw.get("provider") or defaults.provider).strip().lower(),
            queries=_lines(raw.get("queries")),
            classify_model=str(raw.get("classifyModel", defaults.classify_model)),
            search_model=str(raw.get("searchModel") or defaults.search_model),
            select_model=str(raw.get("selectModel") or defaults.select_model),
            extraction_model=str(raw.get("extractionModel") or defaults.extraction_model),
            search_prompt=prompt("searchPrompt", defaults.search_prompt),
            queries_prompt=prompt("queriesPrompt", defaults.queries_prompt),
            classify_prompt=prompt("classifyPrompt", defaults.classify_prompt),
            select_prompt=prompt("selectPrompt", defaults.select_prompt),
            extraction_prompt=prompt("extractionPrompt", defaults.extraction_prompt),
            extraction_multi_prompt=prompt(
                "extractionMultiPrompt", defaults.extraction_multi_prompt
            ),
        )
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
    if config.targets_site:
        # Pas de découverte à réduire : les URLs sont données, et les lire ne
        # coûte rien. Seul le nombre de sorties retenues est plafonné.
        return replace(config, max_events=events)
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
    #: Clé du moteur de recherche, quand la configuration en nomme un.
    serper_key: str | None = None

    @classmethod
    def from_env(cls) -> "Environment":
        return cls(
            api_url=os.environ.get("SPP_API_URL", "http://localhost:3000").rstrip("/"),
            api_key=os.environ.get("SPP_API_KEY") or None,
            anthropic_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            serper_key=os.environ.get("SERPER_API_KEY") or None,
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
        "mode": config.mode,
        "seed_urls": list(config.seed_urls),
        "area": config.area,
        "period": config.period,
        "date_from": config.date_from.isoformat(),
        "date_to": config.date_to.isoformat(),
        "max_events": config.max_events,
        "max_searches": config.max_searches,
        "max_agendas": config.max_agendas,
        "max_next_pages": config.max_next_pages,
        "provider": config.provider,
        "aggregator_domains": list(config.aggregator_domains),
        "block_aggregators": config.block_aggregators,
        "blocked_domains": list(config.blocked_domains),
        "source_search": config.source_search,
        "queries": list(config.queries),
        "classify_model": config.classify_model,
        "search_model": config.search_model,
        "select_model": config.select_model,
        "extraction_model": config.extraction_model,
    }
