"""Fournisseur Claude : trois appels bornés.

`web_search` reste le seul outil serveur utilisé, parce qu'il n'y a pas
d'autre accès à un moteur de recherche. Tout le reste — ouvrir les pages, en
extraire les liens, en tirer le texte — se fait dans `harvest.py`, en Python
et sans jeton.

La conséquence tient en une phrase : **plus aucun appel ne boucle**. La
recherche fait un aller-retour serveur par salve de requêtes ; la sélection et
l'extraction n'ont aucun outil, donc aucune itération. C'est ce qui rend le
coût prévisible, là où un seul appel agentique refacturait tout son contexte à
chacune de ses trente itérations.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..config import Config
from ..harvest import Link
from ..journal import RunLog
from ..models import ExtractedEvent, FoundPage, Usage
from ..store import normalize_url
from .base import ProviderError

#: Version de base de la recherche web : la variante à filtrage dynamique
#: (2026-02-09) réclame un modèle Claude 4.6+, et son intérêt disparaît ici
#: puisqu'on ne fait plus lire de pages au modèle.
WEB_SEARCH_TOOL = "web_search_20250305"

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

#: Reprises acceptées après un `pause_turn`. Seule la recherche peut être mise
#: en pause ; deux reprises suffisent largement pour une salve de requêtes.
MAX_CONTINUATIONS = 2

TIMEOUT_SECONDS = 300.0

SEARCH_MAX_TOKENS = 8_000
SELECT_MAX_TOKENS = 2_000
EXTRACTION_MAX_TOKENS = 4_000

#: Tarifs jetons en dollars par million. La facturation des recherches web
#: (0,01 $ pièce) s'y ajoute et est comptée à part dans `Usage`.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "kind": {"type": "string", "enum": ["agenda", "sortie"]},
                    "reason": {"type": "string"},
                },
                "required": ["url", "title", "kind", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["pages"],
    "additionalProperties": False,
}

SELECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kept": {
            "type": "array",
            "items": {"type": "integer"},
        }
    },
    "required": ["kept"],
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
        "relevant", "skip_reason", "title", "description", "free", "price",
        "age_min", "age_max", "permanent", "date_start", "date_end",
        "open_time", "close_time", "setting", "category", "venue_name",
        "venue_address", "venue_city", "venue_postal_code", "photo_url",
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
        self._client = (
            anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_SECONDS)
            if api_key
            else anthropic.Anthropic(timeout=TIMEOUT_SECONDS)
        )

    # -------------------------------------------------------------- 1. chercher

    def search(self, config: Config, log: RunLog) -> list[FoundPage]:
        seen: set[str] = set()
        data = self._ask(
            model=config.search_model,
            prompt=config.render_search(),
            schema=SEARCH_SCHEMA,
            max_tokens=SEARCH_MAX_TOKENS,
            stage="search",
            log=log,
            tools=[
                {
                    "type": WEB_SEARCH_TOOL,
                    "name": "web_search",
                    "max_uses": config.max_searches,
                    "user_location": USER_LOCATION,
                    **({"blocked_domains": config.blocked_domains} if config.blocked_domains else {}),
                }
            ],
            seen_urls=seen,
        )

        if not seen:
            log.error("search", "aucune recherche lancée : réponse écartée")
            return []

        pages: list[FoundPage] = []
        for raw in data.get("pages") or []:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url", "")).strip()
            if not url.startswith(("http://", "https://")):
                continue
            if normalize_url(url) not in seen:
                log.error("search", "URL absente des résultats de recherche", url=url)
                continue
            pages.append(
                FoundPage(
                    url=url,
                    title=str(raw.get("title", "")).strip(),
                    kind=str(raw.get("kind", "agenda")).strip().lower(),
                    reason=str(raw.get("reason", "")).strip(),
                )
            )
        return pages

    # --------------------------------------------------------------- 2. choisir

    def select(
        self, page: str, links: list[Link], config: Config, log: RunLog
    ) -> list[Link]:
        if not links:
            return []
        listing = "\n".join(
            f"{i}. {link.text} | {link.context}" for i, link in enumerate(links, start=1)
        )
        data = self._ask(
            model=config.select_model,
            prompt=config.render_select(page, listing),
            schema=SELECT_SCHEMA,
            max_tokens=SELECT_MAX_TOKENS,
            stage="select",
            log=log,
        )
        # Le modèle rend des numéros : aucune URL ne peut sortir d'ailleurs que
        # de la page réellement lue.
        kept: list[Link] = []
        for number in data.get("kept") or []:
            if isinstance(number, int) and 1 <= number <= len(links):
                kept.append(links[number - 1])
        return kept[: config.max_links_per_agenda]

    # -------------------------------------------------------------- 3. extraire

    def extract(
        self, url: str, content: str, config: Config, categories: list[str], log: RunLog
    ) -> ExtractedEvent:
        data = self._ask(
            model=config.extraction_model,
            prompt=config.render_extraction(url, content, categories),
            schema=EXTRACTION_SCHEMA,
            max_tokens=EXTRACTION_MAX_TOKENS,
            stage="extraction",
            log=log,
        )
        return ExtractedEvent.from_json(data)

    # ---------------------------------------------------------------- l'appel

    def _ask(
        self,
        *,
        model: str,
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int,
        stage: str,
        log: RunLog,
        tools: list[dict[str, Any]] | None = None,
        seen_urls: set[str] | None = None,
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": SYSTEM,
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        if tools:
            params["tools"] = tools

        for _ in range(MAX_CONTINUATIONS + 1):
            response = self._stream(
                params, messages, stage=stage, model=model, log=log, seen_urls=seen_urls
            )
            if getattr(response, "stop_reason", None) != "pause_turn":
                return _parse_json(response)

            blocks = list(response.content)
            if messages[-1]["role"] == "assistant":
                messages[-1]["content"] = list(messages[-1]["content"]) + blocks
            else:
                messages.append({"role": "assistant", "content": blocks})

        raise ProviderError(f"{stage} : tour toujours en pause après {MAX_CONTINUATIONS} reprises")

    def _stream(
        self,
        params: dict[str, Any],
        messages: list[dict[str, Any]],
        *,
        stage: str,
        model: str,
        log: RunLog,
        seen_urls: set[str] | None = None,
    ) -> Any:
        step = Usage()

        try:
            with self._client.messages.stream(**params, messages=messages) as stream:
                for event in stream:
                    if getattr(event, "type", "") != "content_block_stop":
                        continue
                    block = getattr(event, "content_block", None)
                    if block is not None:
                        self._trace_block(block, stage=stage, log=log, step=step, seen=seen_urls)
                response = stream.get_final_message()
        except ProviderError:
            raise
        except Exception as err:
            # Clé absente, quota dépassé, réseau coupé : le run doit finir sur
            # un message lisible et un journal complet, pas sur une pile.
            raise ProviderError(f"appel à l'API refusé ({err.__class__.__name__}) : {err}") from err

        usage = getattr(response, "usage", None)
        step.input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        step.output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        step.cost_usd = _token_cost(model, step)
        self.usage.add(step)
        log.event("usage", stage=stage, model=model, **step.as_dict())
        return response

    def _trace_block(
        self, block: Any, *, stage: str, log: RunLog, step: Usage, seen: set[str] | None
    ) -> None:
        kind = getattr(block, "type", "")

        if kind == "server_tool_use" and getattr(block, "name", "") == "web_search":
            step.web_searches += 1
            log.event("query", stage=stage, query=(getattr(block, "input", {}) or {}).get("query", ""))

        elif kind == "web_search_tool_result":
            content = getattr(block, "content", None)
            if isinstance(content, list):
                for result in content:
                    url = str(getattr(result, "url", ""))
                    if seen is not None and url.startswith(("http://", "https://")):
                        seen.add(normalize_url(url))
                    log.event(
                        "search_result", stage=stage, url=url,
                        title=getattr(result, "title", ""),
                    )
            else:
                code = getattr(content, "error_code", "") if content is not None else ""
                log.error(stage, f"recherche web en échec : {code}")


# ---------------------------------------------------------------------- outils


def _token_cost(model: str, usage: Usage) -> float:
    rate_in, rate_out = PRICES.get(model, (0.0, 0.0))
    return (usage.input_tokens * rate_in + usage.output_tokens * rate_out) / 1_000_000


def _parse_json(response: Any) -> dict[str, Any]:
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
