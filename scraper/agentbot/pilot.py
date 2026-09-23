"""Le pilote : un modèle d'OpenRouter qui choisit l'outil suivant.

Un tour, c'est un appel au format de l'API d'OpenAI qu'imite OpenRouter :
l'historique, la liste des outils, et une réponse qui porte soit du texte,
soit des `tool_calls`. Rien de propre à un éditeur : GLM, Gemini, Qwen ou
Claude (`anthropic/claude-haiku-4.5`) répondent tous à la même forme, et c'est
ce qui rend le pilote interchangeable.

La mécanique HTTP n'est pas réécrite : c'est celle du fournisseur OpenRouter
de `sortiesbot` — ses nouvelles tentatives sur les erreurs passagères, ses
messages d'erreur qui disent quoi faire, sa lecture du coût annoncé par le
service. On l'emprunte par ses deux méthodes internes (`_post`, `_facturer`).
C'est un couplage assumé : l'autre choix était de dupliquer cent lignes qui
ont été mises au point contre le vrai service, et la première divergence
aurait été un bug de facturation.

**Ce qui n'a pas pu être vérifié d'ici** : la forme exacte d'une réponse à
outils renvoyée par le service. Le code suit le format OpenAI documenté
(`message.tool_calls[].function.arguments`, en chaîne JSON) et renvoie au tour
suivant le message de l'assistant **tel qu'il est venu**, `reasoning_details`
compris — c'est ce que demandent les modèles qui raisonnent pour garder le fil
d'un tour à l'autre. Le premier run réel dira s'il manque quelque chose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sortiesbot.journal import RunLog
from sortiesbot.models import Usage
from sortiesbot.providers.base import ProviderError
from sortiesbot.providers.openrouter_provider import (
    MARGE_RAISONNEMENT,
    OpenRouterProvider,
    modele_openrouter,
)

#: Le pilote par défaut. **Sans** `:floor` : le pipeline s'en sert pour payer
#: le moins possible des appels isolés, mais un agent enchaîne soixante tours,
#: et changer d'hébergeur — donc de quantisation — au milieu d'une exploration
#: ajoute une variable qu'on ne saurait pas isoler.
PILOTE_DEFAUT = "z-ai/glm-5.3-flash"

#: Ce qu'un tour a le droit d'écrire : une ou deux lignes de pensée et quelques
#: appels d'outils. Le raisonnement, lui, a sa marge à part — voir
#: `MARGE_RAISONNEMENT` dans le fournisseur.
REPONSE_MAX_TOKENS = 1_500

#: Clés du message de l'assistant renvoyées telles quelles au tour suivant.
#: `reasoning` (le texte du raisonnement) n'en fait pas partie : il est long,
#: il se paierait à chaque tour, et `reasoning_details` porte ce dont le
#: modèle a besoin pour enchaîner.
CLES_RENVOYEES = ("role", "content", "tool_calls", "reasoning_details")


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    #: Les arguments tels que le modèle les a écrits : une chaîne JSON, qu'il
    #: peut rater. C'est l'outil qui la lit, et qui dit au modèle s'il s'est
    #: trompé.
    arguments: str


@dataclass
class Turn:
    """Ce qu'un tour a rendu."""

    #: Le message à remettre dans l'historique.
    message: dict[str, Any]
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    finish: str = ""


class Pilot:
    """Un modèle d'OpenRouter, appelé avec des outils."""

    def __init__(
        self,
        model: str,
        usage: Usage,
        *,
        api_key: str | None = None,
        effort: str = "low",
        router: OpenRouterProvider | None = None,
    ) -> None:
        self.model = modele_openrouter(model, defaut=PILOTE_DEFAUT)
        self.effort = effort
        self._router = router or OpenRouterProvider(api_key=api_key)
        # Un seul compteur pour tout le run : le pilote, les recherches et les
        # extractions paient dans la même caisse, et c'est elle que le plafond
        # de budget surveille.
        self._router.usage = usage

    def turn(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], log: RunLog) -> Turn:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": REPONSE_MAX_TOKENS + MARGE_RAISONNEMENT,
            # Seulement vers un hébergeur qui sait appeler des outils : sans
            # ça, OpenRouter pourrait router vers un hébergeur qui les ignore
            # et rendrait du texte là où on attendait un appel.
            "provider": {"require_parameters": True},
            "usage": {"include": True},
        }
        if self.effort:
            payload["reasoning"] = {"effort": self.effort}
        data = self._router._post(payload, op="pilote", modele=self.model, log=log)
        self._router._facturer(data, op="pilote", modele=self.model, log=log)
        return read_turn(data)


def read_turn(data: dict[str, Any]) -> Turn:
    """Lit la réponse du service. Lève `ProviderError` si elle est vide."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderError("réponse du pilote sans choix")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}

    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    text = content.strip() if isinstance(content, str) else ""

    calls: list[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        if not isinstance(raw, dict):
            continue
        fn = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        arguments = fn.get("arguments")
        if not isinstance(arguments, str):
            # Quelques hébergeurs rendent déjà un objet : on le remet en
            # chaîne, c'est la forme que l'historique doit garder.
            arguments = json.dumps(arguments or {}, ensure_ascii=False)
        calls.append(
            ToolCall(id=str(raw.get("id") or ""), name=str(fn.get("name") or ""), arguments=arguments)
        )

    kept = {k: message[k] for k in CLES_RENVOYEES if message.get(k) is not None}
    kept["role"] = "assistant"
    kept.setdefault("content", text)
    return Turn(message=kept, text=text, calls=calls, finish=str(choice.get("finish_reason") or ""))
