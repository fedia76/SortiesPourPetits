"""Ligne de commande de l'agent.

    python -m agentbot --config configs/agent-exemple.yaml
    python -m agentbot --config configs/agent-exemple.yaml --pilot anthropic/claude-haiku-4.5

Toujours en essai : rien n'est envoyé au site. Le run écrit, comme le
pipeline, un journal JSONL et un JSON des sorties retenues dans `runs/`, avec
`-agent` dans le nom pour ne pas les confondre.

La configuration est celle du pipeline, au même format : c'est ce qui permet
de lancer les deux sur **la même** recherche et de comparer. Deux champs y
changent de rôle : `provider` et `extraction_model` désignent ce qui lit les
pages (l'extraction), et le pilote se choisit ici, avec `--pilot`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sortiesbot.api import SppApi
from sortiesbot.config import ConfigError, Environment, load_config, load_dotenv, with_limit
from sortiesbot.harvest import Fetcher
from sortiesbot.journal import run_log_path
from sortiesbot.providers.base import ProviderError, get_provider
from sortiesbot.providers.serper_client import SerperClient, client_or_none
from sortiesbot.stages.base import RunContext
from sortiesbot.store import SeenStore

from .journal import AgentLog
from .loop import run_agent
from .pilot import PILOTE_DEFAUT, Pilot
from .tools import Limits, Toolbox

ROOT = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    defaults = Limits()
    parser = argparse.ArgumentParser(
        prog="agentbot",
        description="Un agent explore le web à la recherche de sorties pour enfants (essai).",
    )
    parser.add_argument("--config", "-c", required=True, help="fichier YAML, celui du pipeline")
    parser.add_argument(
        "--pilot", default=PILOTE_DEFAUT,
        help=f"modèle OpenRouter qui pilote l'exploration (défaut : {PILOTE_DEFAUT})",
    )
    parser.add_argument(
        "--effort", default="low",
        help="effort de raisonnement du pilote : low, medium, high… vide pour celui du modèle",
    )
    parser.add_argument("--max-turns", type=int, default=defaults.max_turns)
    parser.add_argument("--max-depth", type=int, default=defaults.max_depth)
    parser.add_argument("--max-pages", type=int, default=defaults.max_pages)
    parser.add_argument(
        "--max-searches", type=int,
        help=f"recherches web autorisées (défaut : max_searches de la configuration, "
        f"au moins {defaults.max_searches})",
    )
    parser.add_argument("--limit", "-n", type=int, help="plafonne le nombre de sorties du run")
    parser.add_argument("--quiet", "-q", action="store_true", help="pas de sortie console")
    parser.add_argument("--runs-dir", default=str(ROOT / "runs"))
    parser.add_argument(
        "--state",
        default=str(ROOT / "state" / "agent-seen.sqlite3"),
        help="mémoire des pages vues, **séparée** de celle du pipeline "
        "(défaut : scraper/state/agent-seen.sqlite3)",
    )
    parser.add_argument(
        "--forget", action="store_true", help="ignore la mémoire des pages vues"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env")
    env = Environment.from_env()

    try:
        config = with_limit(load_config(args.config), args.limit)
    except ConfigError as err:
        print(str(err), file=sys.stderr)
        return 2

    limits = Limits(
        max_turns=args.max_turns,
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        max_searches=args.max_searches
        if args.max_searches is not None
        else max(config.max_searches, Limits().max_searches),
    )

    try:
        # Ce qui lit les pages : le fournisseur de la configuration, sans son
        # moteur — c'est l'agent qui cherche, avec son propre outil.
        provider = get_provider(
            config,
            api_key=env.anthropic_key,
            serper_key=env.serper_key,
            openrouter_key=env.openrouter_key,
            search=False,
        )
        pilot = Pilot(args.pilot, provider.usage, api_key=env.openrouter_key, effort=args.effort)
        search = None if config.targets_site else SerperClient(env.serper_key)
    except ProviderError as err:
        print(str(err), file=sys.stderr)
        return 2

    runs_dir = Path(args.runs_dir)
    log_path = run_log_path(runs_dir, f"{config.name}-agent")
    state_path = ":memory:" if args.forget else args.state

    if not args.quiet:
        print(f"Journal : {log_path}")
        print(f"Pilote  : {pilot.model} (effort {args.effort or 'par défaut'})\n")

    with AgentLog(log_path, verbose=not args.quiet) as log, SeenStore(state_path) as store:
        ctx = RunContext(
            config=config,
            provider=provider,
            store=store,
            api=SppApi(env.api_url, env.api_key),
            fetcher=Fetcher(),
            log=log,
            submit=False,
        )
        toolbox = Toolbox(ctx, limits, search=search, engine=client_or_none(env.serper_key))
        result = run_agent(ctx, pilot, toolbox, limits)

    output = log_path.with_suffix(".json")
    output.write_text(
        json.dumps(
            {
                "config": config.name,
                "mode": "agent (dry-run)",
                "pilot": pilot.model,
                "effort": args.effort,
                "limits": vars(limits),
                "turns": result.turns,
                "reason": result.reason,
                "bilan": result.bilan,
                "calls": dict(result.calls),
                "summary": result.run.summary.as_dict(),
                "events": result.run.events,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if not args.quiet:
        print(f"\nJournal : {log_path}")
        print(f"Sorties : {output}")
        print(f"{len(result.run.events)} sortie(s) retenue(s) — {result.reason}.")
    return 1 if result.run.summary.errors and not result.run.events else 0


if __name__ == "__main__":
    raise SystemExit(main())
