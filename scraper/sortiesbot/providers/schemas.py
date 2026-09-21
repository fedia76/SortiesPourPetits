"""Ce qu'on demande au modèle, quel qu'il soit.

Les schémas de sortie vivaient dans `anthropic_provider.py`, où ils étaient
nés. Ils n'y avaient plus leur place le jour où un **second** fournisseur de
modèle est arrivé : un champ ajouté à l'un et oublié à l'autre aurait fait
deux briques d'extraction qui ne rendent pas la même fiche, et le banc aurait
mesuré cette différence-là en croyant mesurer les modèles.

D'où ce module, qui ne connaît ni HTTP ni SDK : cinq schémas, quatre plafonds
de jetons, et les deux gestes que tout fournisseur de modèle refait — lire du
JSON qui peut être enrobé, tourner une page de programme en fiches.

Ce qui reste chez chaque fournisseur est ce qui lui appartient vraiment : la
façon d'appeler son service, de réclamer du JSON structuré, et de compter ce
que ça coûte.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..models import ExtractedEvent

CLASSIFY_MAX_TOKENS = 300
QUERIES_MAX_TOKENS = 600
SELECT_MAX_TOKENS = 2_000
EXTRACTION_MAX_TOKENS = 4_000
#: Une page de programme rend jusqu'à `max_events` fiches d'un coup ; le
#: plafond d'une page unique la tronquerait au milieu de la troisième.
EXTRACTION_MULTI_MAX_TOKENS = 16_000

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
        # Le seul champ qui puisse renvoyer la page en arrière : elle n'est
        # pas une sortie, mais elle en porte plusieurs.
        "several": {"type": "boolean"},
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
        "relevant", "skip_reason", "several", "title", "description", "free", "price",
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
        if k not in ("relevant", "skip_reason", "several")
    },
    "required": [
        k for k in EXTRACTION_SCHEMA["required"]
        if k not in ("relevant", "skip_reason", "several")
    ],
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


def loads_json(text: str, erreur: type[Exception]) -> dict[str, Any]:
    """Le JSON que porte une réponse, même mal emballé.

    Un service qui garantit le JSON structuré rend du JSON nu, et la recherche
    d'accolades ne sert jamais. Les autres — un modèle qui préfixe « Voici »,
    un autre qui entoure de trois accents graves — la rendent nécessaire, et
    elle ne coûte rien quand elle ne sert pas.

    `erreur` est la classe à lever : chaque fournisseur a la sienne, et ce
    module n'a pas à connaître celle qui l'appelle.
    """
    text = (text or "").strip()
    if not text:
        raise erreur("réponse sans contenu texte exploitable")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise erreur(f"réponse illisible : {text[:200]}") from None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as err:
            raise erreur(f"réponse illisible : {text[:200]}") from err
    if not isinstance(data, dict):
        raise erreur("réponse JSON inattendue (objet attendu)")
    return data


def events_from_multi(data: dict[str, Any], max_events: int) -> list[ExtractedEvent]:
    """Les fiches d'une page de programme, ou une seule qui dit pourquoi aucune.

    Le retour n'est jamais vide : une page de programme sans programme est
    traitée comme une page hors sujet, avec la raison donnée par le modèle. La
    suite du pipeline ne connaît ainsi qu'un seul chemin.
    """
    raw = data.get("events")
    events = [
        ExtractedEvent.from_json({**item, "relevant": True})
        for item in (raw if isinstance(raw, list) else [])
        if isinstance(item, dict)
    ]
    if not events:
        reason = str(data.get("skip_reason") or "").strip()
        return [
            ExtractedEvent(
                relevant=False,
                skip_reason=reason or "aucune sortie relevée sur cette page",
            )
        ]
    return events[:max_events]
