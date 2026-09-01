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

CLASSIFY_MAX_TOKENS = 300
QUERIES_MAX_TOKENS = 600
#: La réponse ne porte plus que les requêtes lancées : quelques dizaines de
#: jetons là où le classement des pages en demandait des milliers.
SEARCH_MAX_TOKENS = 600
SELECT_MAX_TOKENS = 2_000
EXTRACTION_MAX_TOKENS = 4_000
#: Une page de programme rend jusqu'à `max_events` fiches d'un coup ; le
#: plafond d'une page unique la tronquerait au milieu de la troisième.
EXTRACTION_MULTI_MAX_TOKENS = 16_000

#: Tarifs jetons en dollars par million. La facturation des recherches web
#: (0,01 $ pièce) s'y ajoute et est comptée à part dans `Usage`.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

#: Une étiquette et une phrase. Le modèle n'écrit jamais d'URL ici : il ne
#: peut donc pas en inventer, comme à la sélection.
CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nature": {
            "type": "string",
            "enum": ["agenda", "sortie", "programme", "inconnu"],
        },
        "pourquoi": {"type": "string"},
    },
    "required": ["nature", "pourquoi"],
    "additionalProperties": False,
}

#: Une liste de requêtes, et rien d'autre : c'est tout ce qu'on demande à ce
#: premier appel. Le modèle n'écrit aucune URL, donc il ne peut pas en inventer.
QUERIES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
    "additionalProperties": False,
}

#: La recherche ne rend plus de jugement : ce qu'elle a remonté est relevé sur
#: le flux, bloc par bloc, et la réponse du modèle ne sert qu'à clore le tour.
#: D'où un schéma minuscule et un plafond de jetons de sortie très bas.
SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"lancees": {"type": "array", "items": {"type": "string"}}},
    "required": ["lancees"],
    "additionalProperties": False,
}

#: Le modèle rend des **numéros de ligne**, jamais des URL : c'est ce qui rend
#: matériellement impossible d'en inventer une, et ça ne change pas. Ce qui
#: change, c'est qu'il dit maintenant *pourquoi* — un motif par lien retenu,
#: et une phrase pour ce qu'il a écarté.
#:
#: Un motif par lien écarté coûterait bien trop cher : deux cents liens à
#: quinze jetons font tripler la sortie de cet étage. Une phrase globale suffit
#: à comprendre un tri raté, ce qui est le besoin réel.
SELECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kept": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "why": {"type": "string"},
                },
                "required": ["index", "why"],
                "additionalProperties": False,
            },
        },
        "dropped_reason": {"type": "string"},
    },
    "required": ["kept", "dropped_reason"],
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
        # Les jours de représentation : sans eux, un spectacle du dimanche
        # devient une plage continue, donc proposé un jeudi.
        "weekdays": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "lundi", "mardi", "mercredi", "jeudi",
                    "vendredi", "samedi", "dimanche",
                ],
            },
        },
        "dates": {"type": "array", "items": {"type": "string"}},
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
        "weekdays", "dates",
        "open_time", "close_time", "setting", "category", "venue_name",
        "venue_address", "venue_city", "venue_postal_code", "photo_url",
    ],
    "additionalProperties": False,
}


#: La fiche d'une sortie relevée dans un programme est celle d'une page
#: unique, moins le verdict : une entrée qui ne convient pas n'est simplement
#: pas dans la liste. Dériver le schéma plutôt que le recopier garantit qu'un
#: champ ajouté à l'un existe dans l'autre.
_MULTI_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        k: v for k, v in EXTRACTION_SCHEMA["properties"].items()
        if k not in ("relevant", "skip_reason")
    },
    "required": [k for k in EXTRACTION_SCHEMA["required"] if k not in ("relevant", "skip_reason")],
    "additionalProperties": False,
}

EXTRACTION_MULTI_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {"type": "array", "items": _MULTI_ITEM_SCHEMA},
        #: Renseigné quand la liste est vide : la console dira pourquoi.
        "skip_reason": {"type": "string"},
    },
    "required": ["events", "skip_reason"],
    "additionalProperties": False,
}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, client: Any = None):
        self.usage = Usage()
        #: Requête de chaque `server_tool_use`, par identifiant de bloc.
        #: C'est ce qui relie un résultat à la recherche qui l'a remonté.
        self._queries: dict[str, str] = {}
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

    def queries(self, config: Config, log: RunLog) -> list[str]:
        """Formule les requêtes. Le plus petit appel du pipeline."""
        data = self._ask(
            model=config.search_model,
            prompt=config.render_queries(),
            schema=QUERIES_SCHEMA,
            max_tokens=QUERIES_MAX_TOKENS,
            op="queries",
            log=log,
        )
        found = [str(q).strip() for q in (data.get("queries") or []) if str(q).strip()]
        return found[: config.max_searches]

    def search(self, queries: list[str], config: Config, log: RunLog) -> list[FoundPage]:
        """Lance ces recherches et rend ce qu'elles ont remonté, sans jugement.

        Les résultats ne sont pas lus dans la réponse du modèle mais relevés
        sur le flux, bloc par bloc — c'est `_trace_block` qui les collecte. Le
        modèle sert ici de télécommande à l'outil serveur, rien de plus : il ne
        classe rien, il ne résume rien, et il ne peut donc rien inventer.

        La contrepartie, avec cet outil-ci, est qu'il **voit** tout de même le
        contenu des résultats — c'est ainsi que `web_search` fonctionne, et ces
        jetons d'entrée restent facturés. C'est précisément ce qu'un moteur
        ordinaire n'imposerait pas.
        """
        if not queries:
            return []
        seen: dict[str, FoundPage] = {}
        self._ask(
            model=config.search_model,
            prompt=config.render_search(queries),
            schema=SEARCH_SCHEMA,
            max_tokens=SEARCH_MAX_TOKENS,
            op="search",
            log=log,
            tools=[
                {
                    "type": WEB_SEARCH_TOOL,
                    "name": "web_search",
                    "max_uses": max(len(queries), config.max_searches),
                    "user_location": USER_LOCATION,
                    **({"blocked_domains": config.blocked_domains} if config.blocked_domains else {}),
                }
            ],
            found=seen,
        )
        if not seen:
            log.error("search", "aucun résultat de recherche")
        return list(seen.values())

    # ------------------------------------------------------------ 2. reconnaître

    def classify(self, digest: str, config: Config, log: RunLog) -> tuple[str, str]:
        """Le plus petit des quatre appels : un condensé, une étiquette."""
        data = self._ask(
            model=config.classify_model,
            prompt=config.render_classify(digest),
            schema=CLASSIFY_SCHEMA,
            max_tokens=CLASSIFY_MAX_TOKENS,
            op="classify",
            log=log,
        )
        nature = str(data.get("nature", "")).strip().lower()
        if nature not in ("agenda", "sortie", "programme", "inconnu"):
            # Le schéma l'interdit, mais une réponse tronquée peut passer au
            # travers : on ne devine pas à sa place.
            return "inconnu", f"réponse inattendue ({nature or 'vide'})"
        return nature, str(data.get("pourquoi", "")).strip()

    # --------------------------------------------------------------- 3. choisir

    def select(
        self, page: str, links: list[Link], config: Config, log: RunLog
    ) -> list[Link]:
        if not links:
            return []
        listing = "\n".join(
            f"{i}. {link.text} | {link.context}" for i, link in enumerate(links, start=1)
        )
        for i, link in enumerate(links, start=1):
            log.event("link", index=i, url=link.url, text=link.text, context=link.context, agenda=page)
        data = self._ask(
            model=config.select_model,
            prompt=config.render_select(page, listing),
            schema=SELECT_SCHEMA,
            max_tokens=SELECT_MAX_TOKENS,
            op="select",
            log=log,
        )
        # Le modèle rend des numéros : aucune URL ne peut sortir d'ailleurs que
        # de la page réellement lue.
        kept: list[tuple[Link, str]] = []
        for raw in data.get("kept") or []:
            number = raw.get("index") if isinstance(raw, dict) else raw
            why = str(raw.get("why", "")).strip() if isinstance(raw, dict) else ""
            if isinstance(number, int) and 1 <= number <= len(links):
                kept.append((links[number - 1], why))
        kept = kept[: config.max_links_per_agenda]

        dropped = str(data.get("dropped_reason") or "").strip()
        log.event(
            "selected",
            url=page,
            kept=len(kept),
            among=len(links),
            dropped_reason=dropped,
        )
        for link, why in kept:
            log.event("link_kept", url=link.url, text=link.text, why=why, agenda=page)
        return [link for link, _ in kept]

    # -------------------------------------------------------------- 4. extraire

    def extract(
        self,
        url: str,
        content: str,
        config: Config,
        categories: list[str],
        log: RunLog,
        *,
        multiple: bool = False,
    ) -> list[ExtractedEvent]:
        """Lit une page. Une fiche, ou plusieurs si c'est un programme.

        Le retour est une liste dans les deux cas : c'est ce qui permet à la
        suite du pipeline — géocodage, dates, photo, soumission — d'être
        exactement le même code pour les deux modes.
        """
        if not multiple:
            data = self._ask(
                model=config.extraction_model,
                prompt=config.render_extraction(url, content, categories),
                schema=EXTRACTION_SCHEMA,
                max_tokens=EXTRACTION_MAX_TOKENS,
                op="extraction",
                log=log,
            )
            return [ExtractedEvent.from_json(data)]

        data = self._ask(
            model=config.extraction_model,
            prompt=config.render_extraction_multi(url, content, categories),
            schema=EXTRACTION_MULTI_SCHEMA,
            max_tokens=EXTRACTION_MULTI_MAX_TOKENS,
            op="extraction",
            log=log,
        )
        raw = data.get("events")
        events = [
            ExtractedEvent.from_json({**item, "relevant": True})
            for item in (raw if isinstance(raw, list) else [])
            if isinstance(item, dict)
        ]
        if not events:
            # Une page de programme sans programme : le pipeline la traite
            # comme une page hors sujet, avec la raison donnée par le modèle.
            reason = str(data.get("skip_reason") or "").strip()
            return [
                ExtractedEvent(
                    relevant=False,
                    skip_reason=reason or "aucune sortie relevée sur cette page",
                )
            ]
        return events[: config.max_events]

    # ---------------------------------------------------------------- l'appel

    def _ask(
        self,
        *,
        model: str,
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int,
        op: str,
        log: RunLog,
        tools: list[dict[str, Any]] | None = None,
        found: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        log.event("prompt", op=op, chars=len(prompt), model=model, prompt=prompt)
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
                params, messages, op=op, model=model, log=log, found=found
            )
            if getattr(response, "stop_reason", None) != "pause_turn":
                return _parse_json(response)

            blocks = list(response.content)
            if messages[-1]["role"] == "assistant":
                messages[-1]["content"] = list(messages[-1]["content"]) + blocks
            else:
                messages.append({"role": "assistant", "content": blocks})

        raise ProviderError(f"{op} : tour toujours en pause après {MAX_CONTINUATIONS} reprises")

    def _stream(
        self,
        params: dict[str, Any],
        messages: list[dict[str, Any]],
        *,
        op: str,
        model: str,
        log: RunLog,
        found: dict[str, Any] | None = None,
    ) -> Any:
        step = Usage()

        try:
            with self._client.messages.stream(**params, messages=messages) as stream:
                for event in stream:
                    if getattr(event, "type", "") != "content_block_stop":
                        continue
                    block = getattr(event, "content_block", None)
                    if block is not None:
                        self._trace_block(block, op=op, log=log, step=step, found=found)
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
        log.event("usage", op=op, model=model, **step.as_dict())
        return response

    def _trace_block(
        self, block: Any, *, op: str, log: RunLog, step: Usage, found: dict[str, Any] | None
    ) -> None:
        kind = getattr(block, "type", "")

        if kind == "server_tool_use" and getattr(block, "name", "") == "web_search":
            step.web_searches += 1
            query = str((getattr(block, "input", {}) or {}).get("query", ""))
            # C'est `id` qui relie une requête à ses résultats, et rien d'autre.
            # Se fier à l'ordre serait faux : le modèle lance volontiers ses
            # recherches en salve, auquel cas toutes les requêtes sortent avant
            # le premier résultat — et tout se retrouverait attribué à la
            # dernière.
            tool_use_id = str(getattr(block, "id", "") or "")
            if tool_use_id:
                self._queries[tool_use_id] = query
            log.event("query", op=op, query=query, tool_use_id=tool_use_id)

        elif kind == "web_search_tool_result":
            tool_use_id = str(getattr(block, "tool_use_id", "") or "")
            query = self._queries.get(tool_use_id, "")
            content = getattr(block, "content", None)
            if isinstance(content, list):
                if not query:
                    # Sans rattachement, l'arbre du run ne saurait plus dire
                    # quelle formulation a remonté quoi : autant le signaler.
                    log.warn(op, f"résultats non rattachés à une requête ({tool_use_id or '?'})")
                for result in content:
                    url = str(getattr(result, "url", ""))
                    title = str(getattr(result, "title", "") or "")
                    if found is not None and url.startswith(("http://", "https://")):
                        # Dédupliqué à la clé normalisée : deux requêtes
                        # remontent souvent la même page, et c'est la première
                        # qui garde la paternité.
                        found.setdefault(
                            normalize_url(url), FoundPage(url=url, title=title, query=query)
                        )
                    log.event(
                        "search_result", op=op, url=url,
                        title=getattr(result, "title", ""),
                        query=query,
                        tool_use_id=tool_use_id,
                    )
            else:
                code = getattr(content, "error_code", "") if content is not None else ""
                log.error(op, f"recherche web en échec : {code}", query=query)


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
