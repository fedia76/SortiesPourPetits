"""Fournisseur Claude : recherche et lecture de pages par outils serveur.

`web_search` et `web_fetch` sont des outils *serveur* : ce n'est pas le script
qui va sur le web, c'est l'infrastructure d'Anthropic qui exécute la recherche
et le téléchargement, puis réinjecte le contenu dans la conversation. Le script
n'a donc aucun navigateur ni analyseur HTML à maintenir — mais il ne voit du
web que ce que le modèle lui rapporte, d'où le journal détaillé de chaque
requête et de chaque page ouverte.

Deux particularités de ces outils :
  - `web_fetch` ne peut ouvrir qu'une URL déjà présente dans la conversation.
    À la découverte, ce sont les résultats de recherche ; à l'extraction, c'est
    l'URL qu'on lui donne dans le message.
  - la boucle serveur s'arrête au bout de dix itérations avec
    `stop_reason: "pause_turn"` ; on relance alors la requête avec le tour en
    cours, sans rien ajouter, et le serveur reprend où il en était.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..config import Config
from ..journal import RunLog
from ..models import Candidate, ExtractedEvent, Usage
from .base import ProviderError

#: Variantes à filtrage dynamique, disponibles sur Opus 5 / Sonnet 5 et 4.6+.
WEB_SEARCH_TOOL = "web_search_20260209"
WEB_FETCH_TOOL = "web_fetch_20260209"

#: Recherche orientée France, pour des résultats francophones et locaux.
USER_LOCATION = {
    "type": "approximate",
    "city": "Paris",
    "region": "Île-de-France",
    "country": "FR",
    "timezone": "Europe/Paris",
}

SYSTEM = (
    "Tu alimentes un site francophone d'idées de sorties à faire avec des enfants. "
    "Tu ne rapportes que ce que les pages consultées disent réellement : "
    "aucune date, aucun tarif et aucune adresse inventés."
)

#: Nombre de reprises acceptées après un `pause_turn`.
MAX_CONTINUATIONS = 5

DISCOVERY_MAX_TOKENS = 16_000
EXTRACTION_MAX_TOKENS = 8_000

#: Tarifs jetons en dollars par million (documentation Anthropic). La
#: facturation des recherches web s'y ajoute et n'est pas estimée ici : le
#: journal compte les recherches, c'est le relevé de la console qui fait foi.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

DISCOVERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "city": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["url", "title", "city", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "skip_reason": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "free": {"type": "boolean"},
        "price": {"type": ["number", "null"]},
        "age_min": {"type": ["integer", "null"]},
        "age_max": {"type": ["integer", "null"]},
        "permanent": {"type": "boolean"},
        "date_start": {"type": "string"},
        "date_end": {"type": "string"},
        "open_time": {"type": "string"},
        "close_time": {"type": "string"},
        "setting": {"type": "string", "enum": ["INDOOR", "OUTDOOR", "BOTH", ""]},
        "category": {"type": "string"},
        "venue_name": {"type": "string"},
        "venue_address": {"type": "string"},
        "venue_city": {"type": "string"},
        "venue_postal_code": {"type": "string"},
        "photo_url": {"type": "string"},
    },
    "required": [
        "relevant",
        "skip_reason",
        "title",
        "description",
        "free",
        "price",
        "age_min",
        "age_max",
        "permanent",
        "date_start",
        "date_end",
        "open_time",
        "close_time",
        "setting",
        "category",
        "venue_name",
        "venue_address",
        "venue_city",
        "venue_postal_code",
        "photo_url",
    ],
    "additionalProperties": False,
}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, client: Any = None):
        self.usage = Usage()
        if client is not None:
            self._client = client
            return
        try:
            import anthropic
        except ImportError as err:  # pragma: no cover - dépendance déclarée
            raise ProviderError(
                "Le paquet « anthropic » n'est pas installé (pip install -e .)"
            ) from err
        # Sans clé explicite, le SDK lit ANTHROPIC_API_KEY puis les profils
        # d'authentification locaux.
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    # ------------------------------------------------------------------ étages

    def discover(self, config: Config, log: RunLog) -> list[Candidate]:
        tools = [
            {
                "type": WEB_SEARCH_TOOL,
                "name": "web_search",
                "max_uses": config.max_searches,
                "user_location": USER_LOCATION,
                **_blocked(config),
            },
            {
                "type": WEB_FETCH_TOOL,
                "name": "web_fetch",
                "max_uses": config.max_fetches,
                "max_content_tokens": 30_000,
                **_blocked(config),
            },
        ]
        data = self._ask(
            model=config.discovery_model,
            prompt=config.render_discovery(),
            tools=tools,
            schema=DISCOVERY_SCHEMA,
            max_tokens=DISCOVERY_MAX_TOKENS,
            stage="discovery",
            log=log,
        )
        raw = data.get("candidates") or []
        candidates = [Candidate.from_json(c) for c in raw if isinstance(c, dict)]
        return [c for c in candidates if c.url.startswith(("http://", "https://"))]

    def extract(
        self, url: str, config: Config, categories: list[str], log: RunLog
    ) -> ExtractedEvent:
        tools = [
            {
                "type": WEB_FETCH_TOOL,
                "name": "web_fetch",
                "max_uses": 3,
                "max_content_tokens": 30_000,
            }
        ]
        data = self._ask(
            model=config.extraction_model,
            prompt=config.render_extraction(url, categories),
            tools=tools,
            schema=EXTRACTION_SCHEMA,
            max_tokens=EXTRACTION_MAX_TOKENS,
            stage="extraction",
            log=log,
        )
        return ExtractedEvent.from_json(data)

    # ------------------------------------------------------------------ appels

    def _ask(
        self,
        *,
        model: str,
        prompt: str,
        tools: list[dict[str, Any]],
        schema: dict[str, Any],
        max_tokens: int,
        stage: str,
        log: RunLog,
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

        for _ in range(MAX_CONTINUATIONS + 1):
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=SYSTEM,
                messages=messages,
                tools=tools,
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
            self._trace(response, stage=stage, model=model, log=log)

            if getattr(response, "stop_reason", None) != "pause_turn":
                return _parse_json(response)

            # Tour interrompu par la limite d'itérations serveur : on renvoie le
            # même tour, sans message supplémentaire, et le serveur enchaîne.
            blocks = list(response.content)
            if messages[-1]["role"] == "assistant":
                messages[-1]["content"] = list(messages[-1]["content"]) + blocks
            else:
                messages.append({"role": "assistant", "content": blocks})

        raise ProviderError(
            f"{stage} : le tour est toujours en pause après {MAX_CONTINUATIONS} reprises"
        )

    def _trace(self, response: Any, *, stage: str, model: str, log: RunLog) -> None:
        """Journalise ce que le modèle a cherché et lu, puis la consommation."""
        searches = fetches = 0

        for block in getattr(response, "content", []) or []:
            kind = getattr(block, "type", "")

            if kind == "server_tool_use":
                params = getattr(block, "input", {}) or {}
                if getattr(block, "name", "") == "web_search":
                    searches += 1
                    log.event("query", stage=stage, query=params.get("query", ""))
                elif getattr(block, "name", "") == "web_fetch":
                    fetches += 1
                    log.event("visited", stage=stage, url=params.get("url", ""))

            elif kind == "web_search_tool_result":
                content = getattr(block, "content", None)
                if isinstance(content, list):
                    for result in content:
                        log.event(
                            "search_result",
                            stage=stage,
                            url=getattr(result, "url", ""),
                            title=getattr(result, "title", ""),
                        )
                else:
                    log.error(stage, f"recherche web en échec : {_error_code(content)}")

            elif kind == "web_fetch_tool_result":
                content = getattr(block, "content", None)
                code = _error_code(content)
                if code:
                    log.error(stage, f"lecture de page en échec : {code}")

        usage = getattr(response, "usage", None)
        step = Usage(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            web_searches=searches,
            web_fetches=fetches,
        )
        step.cost_usd = _token_cost(model, step)
        self.usage.add(step)
        log.event("usage", stage=stage, model=model, **step.as_dict())


# ---------------------------------------------------------------------- outils


def _blocked(config: Config) -> dict[str, Any]:
    return {"blocked_domains": config.blocked_domains} if config.blocked_domains else {}


def _error_code(content: Any) -> str:
    """Les outils serveur ne lèvent pas d'exception : une erreur arrive sous
    forme d'objet dans le bloc de résultat."""
    if content is None or isinstance(content, list):
        return ""
    return str(getattr(content, "error_code", "") or "")


def _token_cost(model: str, usage: Usage) -> float:
    rate_in, rate_out = PRICES.get(model, (0.0, 0.0))
    return (usage.input_tokens * rate_in + usage.output_tokens * rate_out) / 1_000_000


def _parse_json(response: Any) -> dict[str, Any]:
    """Le format structuré garantit un premier bloc texte en JSON valide ; on
    reste tolérant au cas où un modèle l'entoure de texte."""
    text = next(
        (b.text for b in getattr(response, "content", []) if getattr(b, "type", "") == "text"),
        None,
    )
    if not text:
        raise ProviderError("réponse sans contenu texte exploitable")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ProviderError(f"réponse illisible : {text[:200]}") from None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as err:
            raise ProviderError(f"réponse illisible : {text[:200]}") from err
    if not isinstance(data, dict):
        raise ProviderError("réponse JSON inattendue (objet attendu)")
    return data
