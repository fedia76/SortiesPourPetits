"""La boucle : le pilote choisit, les outils exécutent, jusqu'à la fin.

    tant que ni fini, ni plafond :
        tour = pilote(historique, outils)       ← un appel facturé
        pour chaque appel d'outil du tour :
            résultat = outil(arguments)         ← du Python, ou une brique
            historique += résultat

C'est tout le mécanisme d'un agent. Le reste de ce fichier est ce qui le rend
supportable en coût.

## Pourquoi élaguer, et pourquoi par paquets

À chaque tour, **tout l'historique est renvoyé et facturé**. Sans rien faire,
le coût croît comme le carré du nombre de tours. Deux défenses :

1. les outils ne rendent que des résumés (voir `tools.py`) ;
2. passé quelques tours, un résultat ancien est réduit à sa première ligne,
   qui a été écrite pour se suffire : « p3 — agenda · « Saison 2026 » ». Le
   pilote garde la trace de ce qu'il a fait sans repayer le détail ; s'il en
   a besoin, il rappelle l'outil, qui est gratuit sur une page déjà ouverte.

L'élagage se fait **par paquets** (tous les `ELAGUER_TOUS` tours) et non à
chaque tour. Modifier un message ancien invalide le cache de tout ce qui le
suit, chez les hébergeurs qui en ont un : élaguer à chaque tour reviendrait à
ne jamais profiter du cache. Par paquets, le préfixe reste stable entre deux
élagages.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sortiesbot.api import ApiError
from sortiesbot.config import describe
from sortiesbot.providers.base import ProviderError
from sortiesbot.stages import describe as describe_stages
from sortiesbot.stages.base import RunContext, RunResult

from .journal import AgentLog
from .pilot import Pilot
from .prompts import SYSTEM, objective
from .tools import Limits, Toolbox

#: Tours entre deux élagages de l'historique.
ELAGUER_TOUS = 8
#: Tours récents dont les résultats restent entiers.
GARDER = 4

#: Tours de préavis avant le plafond, pour que le pilote conclue lui-même.
PREAVIS = 5

ELAGUE = " [détail élagué : rappelle l'outil si besoin]"


@dataclass
class AgentResult:
    run: RunResult
    turns: int = 0
    reason: str = ""
    bilan: str = ""
    calls: Counter = field(default_factory=Counter)


def run_agent(ctx: RunContext, pilot: Pilot, toolbox: Toolbox, limits: Limits) -> AgentResult:
    """Joue l'agent du premier au dernier tour. Rend ce qu'il a produit."""
    log: AgentLog = ctx.log  # type: ignore[assignment]
    config = ctx.config
    result = AgentResult(run=ctx.result)

    seeds = toolbox.seed(config.seed_urls) if config.targets_site else []
    log.event(
        "run_start",
        config=describe(config),
        mode="agent — essai, rien n'est proposé au site",
        stages=describe_stages(),
        pilot=pilot.model,
        limits=vars(limits),
    )
    try:
        ctx.categories = ctx.api.categories()
    except ApiError as err:
        # En essai, une API injoignable n'empêche rien : les fiches partent
        # avec une catégorie symbolique, comme dans le pipeline.
        log.warn("categories", str(err))

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": objective(
                config, limits, [f"{t.ref} — {t.url}" for t in seeds] or None
            ),
        },
    ]

    relance = False
    budget_annonce = False
    for turn in range(1, limits.max_turns + 1):
        if toolbox.finished is not None:
            break
        if ctx.budget_reached:
            if budget_annonce:
                result.reason = "budget épuisé"
                break
            # Un dernier tour, pour que le pilote écrive son bilan.
            budget_annonce = True
            messages.append({"role": "user", "content": "Budget épuisé : appelle finish maintenant."})
        if turn == limits.max_turns - PREAVIS + 1 and toolbox.finished is None:
            # Le deuxième run réel a été coupé au 60e tour en pleine
            # exploration, sans bilan : le pilote ne voyait pas venir la fin.
            messages.append(
                {
                    "role": "user",
                    "content": f"Il te reste {PREAVIS} tours. Termine ce qui est en "
                    "cours (extraire, proposer), puis appelle finish avec ton bilan.",
                }
            )
        if turn % ELAGUER_TOUS == 0:
            prune(messages, GARDER)

        result.turns = turn
        try:
            reply = pilot.turn(messages, toolbox.schemas, log)
        except ProviderError as err:
            log.error("pilote", str(err))
            ctx.summary.errors += 1
            result.reason = f"pilote en erreur : {err}"
            break
        messages.append(reply.message)
        log.event(
            "agent_turn",
            turn=turn,
            thought=reply.text,
            calls=[c.name for c in reply.calls],
            finish=reply.finish,
        )

        if not reply.calls:
            if relance:
                result.reason = "le pilote a cessé d'appeler des outils"
                break
            relance = True
            messages.append(
                {
                    "role": "user",
                    "content": "Tu n'as appelé aucun outil. Continue l'exploration, "
                    "ou appelle finish si tu as terminé.",
                }
            )
            continue
        relance = False

        for call in reply.calls:
            output, args = toolbox.call(call.name, call.arguments)
            result.calls[call.name] += 1
            log.event(
                "agent_tool",
                turn=turn,
                tool=call.name,
                args=args or call.arguments,
                digest=output.splitlines()[0] if output else "",
                content=output,
            )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
        messages[-1]["content"] += "\n" + toolbox.status()
    else:
        result.reason = f"plafond de {limits.max_turns} tours atteint"

    if toolbox.finished is not None:
        result.reason = "le pilote a conclu"
        result.bilan = toolbox.finished
    return _close(ctx, result)


def prune(messages: list[dict[str, Any]], keep: int) -> int:
    """Réduit à leur première ligne les résultats d'outils des tours anciens.

    Rend le nombre de messages élagués. Idempotent : un résultat déjà élagué
    n'est pas retouché — le retoucher invaliderait le cache pour rien.
    """
    assistants = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    if len(assistants) <= keep:
        return 0
    frontier = assistants[-keep]
    pruned = 0
    for message in messages[:frontier]:
        if message.get("role") != "tool":
            continue
        content = str(message.get("content") or "")
        if content.endswith(ELAGUE) or "\n" not in content:
            continue
        message["content"] = content.splitlines()[0] + ELAGUE
        pruned += 1
    return pruned


def _close(ctx: RunContext, result: AgentResult) -> AgentResult:
    summary = ctx.summary
    summary.retained = len(ctx.result.events)
    summary.usage.add(ctx.provider.usage)
    ctx.store.flush()
    ctx.log.event(
        "agent_end",
        reason=result.reason,
        turns=result.turns,
        bilan=result.bilan,
        calls=dict(result.calls),
        spent_usd=round(ctx.provider.usage.total_usd, 4),
    )
    ctx.log.event("run_end", summary=summary.as_dict())
    return result
