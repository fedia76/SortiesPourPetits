"""Fournisseur Claude : recherche et lecture de pages par outils serveur.

`web_search` et `web_fetch` sont des outils *serveur* : ce n'est pas le script
qui va sur le web, c'est l'infrastructure d'Anthropic qui exécute la recherche
et le téléchargement, puis réinjecte le contenu dans la conversation. Le script
n'a donc aucun navigateur ni analyseur HTML à maintenir — mais il ne voit du
web que ce que le modèle lui rapporte, d'où le journal détaillé de chaque
requête et de chaque page ouverte.

Trois particularités de ces outils :
  - `web_fetch` ne peut ouvrir qu'une URL déjà présente dans la conversation.
    À la découverte, ce sont les résultats de recherche ; à l'extraction, c'est
    l'URL qu'on lui donne dans le message.
  - la boucle serveur s'arrête au bout de dix itérations avec
    `stop_reason: "pause_turn"` ; on relance alors la requête avec le tour en
    cours, sans rien ajouter, et le serveur reprend où il en était.
  - une découverte enchaîne une dizaine de recherches et de lectures **dans un
    seul appel** : elle dure plusieurs minutes. D'où le streaming — sans lui,
    la requête reste muette du début à la fin, on ne sait pas si elle avance,
    et le journal du run n'est écrit qu'une fois tout terminé.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..config import Config
from ..journal import RunLog
from ..models import Candidate, ExtractedEvent, Usage
from ..store import normalize_url
from .base import ProviderError

#: Toute adresse http(s) dans le texte d'une page ouverte. Sert à savoir ce
#: que le modèle a réellement vu, pour rejeter ce qu'il aurait inventé.
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>)\]]+")

#: Les outils serveur sont versionnés, et la version dépend du modèle.
#:
#: Les variantes 2026-02-09 ajoutent le « filtrage dynamique » : le modèle
#: écrit du code qui trie les résultats avant qu'ils n'entrent en contexte, ce
#: qui réduit la facture sur les requêtes chargées en recherches. Elles
#: réclament un modèle Claude 4.6 ou plus récent ; ailleurs, il faut les
#: variantes de base, sous peine de 400.
WEB_TOOLS_MODERN = ("web_search_20260209", "web_fetch_20260209")
WEB_TOOLS_BASIC = ("web_search_20250305", "web_fetch_20250910")

#: Modèles Claude 4.6 et suivants. Deux capacités s'y rattachent : le filtrage
#: dynamique des outils web, et `thinking: {"type": "adaptive"}`.
CLAUDE_4_6_PLUS = {
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
}


def web_tools_for(model: str) -> tuple[str, str]:
    """`(type de web_search, type de web_fetch)` adaptés au modèle."""
    return WEB_TOOLS_MODERN if model in CLAUDE_4_6_PLUS else WEB_TOOLS_BASIC

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

#: Nombre de reprises acceptées après un `pause_turn`. Chaque reprise renvoie
#: tout le contexte accumulé, donc repart pour une dizaine d'itérations
#: serveur facturées sur ce contexte : au-delà de deux, la note s'envole.
MAX_CONTINUATIONS = 2

#: Un tour de découverte est long : on laisse largement de marge, le streaming
#: garantissant que la connexion n'est jamais silencieuse très longtemps.
TIMEOUT_SECONDS = 900.0

#: Longueur d'un fragment de raisonnement journalisé.
THINKING_CHUNK = 160

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
        self._client = (
            anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_SECONDS)
            if api_key
            else anthropic.Anthropic(timeout=TIMEOUT_SECONDS)
        )

    # ------------------------------------------------------------------ étages

    def discover(self, config: Config, log: RunLog) -> list[Candidate]:
        search_tool, fetch_tool = web_tools_for(config.discovery_model)
        tools = [
            {
                "type": search_tool,
                "name": "web_search",
                "max_uses": config.max_searches,
                "user_location": USER_LOCATION,
                **_blocked(config),
            },
            {
                "type": fetch_tool,
                "name": "web_fetch",
                "max_uses": config.max_fetches,
                # À la découverte on ne cherche que des liens : une page
                # entière serait refacturée à chaque itération de la boucle.
                "max_content_tokens": config.max_page_tokens,
                **_blocked(config),
            },
        ]
        seen: set[str] = set()
        data = self._ask(
            model=config.discovery_model,
            prompt=config.render_discovery(),
            tools=tools,
            schema=DISCOVERY_SCHEMA,
            max_tokens=DISCOVERY_MAX_TOKENS,
            stage="discovery",
            log=log,
            seen_urls=seen,
        )
        raw = data.get("candidates") or []
        candidates = [Candidate.from_json(c) for c in raw if isinstance(c, dict)]
        candidates = [c for c in candidates if c.url.startswith(("http://", "https://"))]

        if not seen:
            # Aucune recherche, aucune page ouverte : le modèle a répondu de
            # mémoire. Ses URL sont des souvenirs, presque toujours morts.
            log.error(
                "discovery",
                "aucune recherche lancée : la réponse vient de la mémoire du "
                "modèle, les candidats sont écartés",
            )
            return []

        return [c for c in candidates if _was_seen(c, seen, log)]

    def extract(
        self, url: str, config: Config, categories: list[str], log: RunLog
    ) -> ExtractedEvent:
        tools = [
            {
                "type": web_tools_for(config.extraction_model)[1],
                "name": "web_fetch",
                "max_uses": 2,
                # L'extraction lit vraiment la page, mais une seule, dans une
                # conversation neuve et sur un modèle bon marché.
                "max_content_tokens": 15_000,
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
        seen_urls: set[str] | None = None,
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": SYSTEM,
            "tools": tools,
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        if model in CLAUDE_4_6_PLUS:
            # Un résumé du raisonnement : c'est la seule chose qui bouge à
            # l'écran pendant que le modèle prépare ses recherches.
            params["thinking"] = {"type": "adaptive", "display": "summarized"}

        for _ in range(MAX_CONTINUATIONS + 1):
            response = self._stream(
                params, messages, stage=stage, model=model, log=log, seen_urls=seen_urls
            )

            if getattr(response, "stop_reason", None) != "pause_turn":
                return _parse_json(response)

            # Tour interrompu par la limite d'itérations serveur : on renvoie le
            # même tour, sans message supplémentaire, et le serveur enchaîne.
            # C'est coûteux (tout le contexte repart), donc ça se voit.
            log.event("paused", stage=stage, cost_usd=round(self.usage.cost_usd, 4))
            blocks = list(response.content)
            if messages[-1]["role"] == "assistant":
                messages[-1]["content"] = list(messages[-1]["content"]) + blocks
            else:
                messages.append({"role": "assistant", "content": blocks})

        raise ProviderError(
            f"{stage} : le tour est toujours en pause après {MAX_CONTINUATIONS} reprises"
        )

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
        """Un tour, journalisé au fil de l'eau plutôt qu'à la fin."""
        step = Usage()
        thinking = ""
        # `tool_use_id` → URL demandée, pour nommer la page dans le résultat :
        # un échec de lecture qui ne dit pas quelle page est inexploitable.
        asked: dict[str, str] = {}

        with self._client.messages.stream(**params, messages=messages) as stream:
            for event in stream:
                kind = getattr(event, "type", "")

                if kind == "content_block_stop":
                    block = getattr(event, "content_block", None)
                    if block is not None:
                        self._trace_block(
                            block,
                            stage=stage,
                            log=log,
                            step=step,
                            asked=asked,
                            seen_urls=seen_urls,
                        )
                    continue

                if kind == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if getattr(delta, "type", "") == "thinking_delta":
                        thinking += getattr(delta, "thinking", "")
                        thinking = _flush_thinking(thinking, stage, log)

            response = stream.get_final_message()

        if thinking.strip():
            log.event("thinking", stage=stage, text=thinking.strip()[:THINKING_CHUNK])

        usage = getattr(response, "usage", None)
        step.input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        step.output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        step.cost_usd = _token_cost(model, step)
        self.usage.add(step)
        log.event("usage", stage=stage, model=model, **step.as_dict())
        return response

    def _trace_block(
        self,
        block: Any,
        *,
        stage: str,
        log: RunLog,
        step: Usage,
        asked: dict[str, str],
        seen_urls: set[str] | None = None,
    ) -> None:
        """Journalise un bloc dès qu'il est complet : c'est ce qui donne à
        l'utilisateur la liste des recherches et des pages, en direct."""
        kind = getattr(block, "type", "")

        if kind == "server_tool_use":
            params = getattr(block, "input", {}) or {}
            name = getattr(block, "name", "")
            if name == "web_search":
                step.web_searches += 1
                log.event("query", stage=stage, query=params.get("query", ""))
            elif name == "web_fetch":
                step.web_fetches += 1
                url = str(params.get("url", ""))
                asked[str(getattr(block, "id", ""))] = url
                log.event("fetching", stage=stage, url=url)

        elif kind == "web_search_tool_result":
            content = getattr(block, "content", None)
            if isinstance(content, list):
                for result in content:
                    url = str(getattr(result, "url", ""))
                    _remember(seen_urls, url)
                    log.event("search_result", stage=stage, url=url, title=getattr(result, "title", ""))
            else:
                log.error(stage, f"recherche web en échec : {_error_code(content)}")

        elif kind == "web_fetch_tool_result":
            url = asked.get(str(getattr(block, "tool_use_id", "")), "")
            code = _error_code(getattr(block, "content", None))
            if code:
                # Une page refusée (robots.txt, filtrage de domaine) consomme
                # quand même un quota : il faut savoir laquelle.
                log.error(stage, f"page refusée ({code})", url=url)
            else:
                step.pages_read += 1
                _remember(seen_urls, url)
                # Les liens contenus dans la page comptent aussi : c'est là que
                # le modèle est censé trouver les pages d'événement.
                for found in URL_IN_TEXT.findall(_document_text(block)):
                    _remember(seen_urls, found)
                log.event("visited", stage=stage, url=url)


# ---------------------------------------------------------------------- outils


def _blocked(config: Config) -> dict[str, Any]:
    return {"blocked_domains": config.blocked_domains} if config.blocked_domains else {}


def _flush_thinking(buffer: str, stage: str, log: RunLog) -> str:
    """Journalise le raisonnement par fragments lisibles, et rend le reste."""
    while len(buffer) >= THINKING_CHUNK or "\n" in buffer:
        cut = buffer.find("\n") + 1
        if not 0 < cut <= THINKING_CHUNK:
            cut = buffer.rfind(" ", 0, THINKING_CHUNK) + 1 or THINKING_CHUNK
        chunk, buffer = buffer[:cut].strip(), buffer[cut:]
        if chunk:
            log.event("thinking", stage=stage, text=chunk)
    return buffer


#: Ponctuation qui colle à une URL dans du texte courant, sans en faire partie.
_TRAILING = ".,;:!?\"')]}»"


def _remember(seen: set[str] | None, url: str) -> None:
    url = url.rstrip(_TRAILING)
    if seen is not None and url.startswith(("http://", "https://")):
        seen.add(normalize_url(url))


def _was_seen(candidate: Candidate, seen: set[str], log: RunLog) -> bool:
    """Écarte une URL que le modèle n'a jamais eue sous les yeux.

    Sans ce filtre, un modèle qui « se souvient » d'une adresse plausible fait
    payer une extraction sur une page qui n'existe pas.
    """
    if normalize_url(candidate.url) in seen:
        return True
    log.error(
        "discovery",
        "URL absente des résultats de recherche et des pages ouvertes "
        "(inventée par le modèle)",
        url=candidate.url,
    )
    return False


def _document_text(block: Any) -> str:
    """Texte d'une page ouverte, si l'API l'a renvoyé sous forme de texte."""
    source = getattr(getattr(getattr(block, "content", None), "content", None), "source", None)
    data = getattr(source, "data", "")
    return data if isinstance(data, str) else ""


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
