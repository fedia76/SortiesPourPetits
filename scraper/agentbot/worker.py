"""Worker de l'agent : joue les exécutions « agent » mises en file depuis la console.

    python -m agentbot.worker            # boucle, une passe toutes les 30 s
    python -m agentbot.worker --once     # traite au plus une exécution

Le jumeau de `sortiesbot.worker`, pour l'autre scraper. Même contrat avec le
site — réclamer (`POST /api/scraper/next?engine=agent`), rendre compte page
par page, clore quoi qu'il arrive —, ce qui donne à l'agent, sans une ligne de
plus côté console, la page d'exécution, le journal, les statistiques et la
modération filtrée par origine.

Deux workers plutôt qu'un qui ferait les deux, pour la raison qui a fait un
second paquet : `sortiesbot` ne bouge pas. Son worker réclame `/next` sans rien
préciser, et le site ne lui sert que les exécutions du pipeline. Celui-ci
précise `engine=agent`, et ne reçoit que les siennes.

Ce qui diffère de la ligne de commande :

* **la mémoire est celle du site** (`RemoteStore`), commune aux deux
  scrapers. C'est ce qui empêche l'agent de reproposer une sortie que le
  pipeline a déjà mise en modération, et l'inverse. Le prix : pour comparer
  les deux sur une même recherche, il faut oublier la mémoire entre les deux
  runs — sinon le second saute ce que le premier a lu ;
* **il soumet**, quand la console le demande (« Lancer et proposer »). Les
  sorties arrivent en modération rattachées à l'exécution, donc à son moteur.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from sortiesbot.api import ApiError, SppApi
from sortiesbot.config import ConfigError, Environment, config_from_api, load_dotenv
from sortiesbot.harvest import Fetcher
from sortiesbot.journal import RemoteJournal, run_log_path
from sortiesbot.models import Summary
from sortiesbot.providers.base import ProviderError, get_provider
from sortiesbot.providers.serper_client import SerperClient, client_or_none
from sortiesbot.stages.base import RunContext
from sortiesbot.store import RemoteStore
from sortiesbot.worker import POLL_SECONDS, counters, finish

from .journal import AgentLog
from .loop import run_agent
from .pilot import PILOTE_DEFAUT, Pilot
from .tools import Limits, Toolbox

ROOT = Path(__file__).resolve().parent.parent

#: L'effort de raisonnement du pilote. « low » : c'est ce qu'ont joué les deux
#: premiers runs réels, et ce qui tient GLM à quelques centimes le run.
EFFORT = "low"

_stop = False


def _handle_signal(*_args: object) -> None:
    global _stop
    _stop = True
    print("Arrêt demandé : le worker s'arrêtera après l'exécution en cours.", flush=True)


def next_agent_run(api: SppApi) -> dict[str, Any] | None:
    """Réclame la prochaine exécution de l'agent, ou None."""
    body = api._post_json("/api/scraper/next?engine=agent")
    return body.get("run")


def limits_for(config_max_searches: int) -> Limits:
    """Les plafonds par défaut, le quota de recherches relevé si la recherche le demande."""
    defaults = Limits()
    return Limits(
        max_turns=defaults.max_turns,
        max_depth=defaults.max_depth,
        max_pages=defaults.max_pages,
        max_searches=max(config_max_searches, defaults.max_searches),
    )


def open_agent_log(runs_dir: Path, name: str, quiet: bool, sink) -> AgentLog:
    """Le journal fichier, ou à défaut un dossier temporaire, ou rien que le site."""
    import tempfile

    for directory in (runs_dir, Path(tempfile.gettempdir()) / "agentbot-runs"):
        try:
            return AgentLog(run_log_path(directory, f"{name}-agent"), verbose=not quiet, sink=sink)
        except OSError as err:
            print(f"Journal impossible dans {directory} ({err}).", file=sys.stderr, flush=True)
    return AgentLog(None, verbose=not quiet, sink=sink)


def execute(job: dict[str, Any], api: SppApi, env: Environment, runs_dir: Path, quiet: bool) -> None:
    """Joue une exécution de l'agent, et la clôt quoi qu'il arrive."""
    run_id = int(job["id"])
    submit = bool(job.get("submit"))
    status, error = "FAILED", "Interrompu avant la fin"
    summary = Summary()

    try:
        config = config_from_api(job.get("config") or {})
    except ConfigError as err:
        finish(api, run_id, "FAILED", {"error": str(err)}, quiet)
        return

    if not quiet:
        print(f"▶ Exécution #{run_id} — agent, « {config.name} »", flush=True)

    store = RemoteStore(api, run_id)
    journal = RemoteJournal(api, run_id)
    try:
        # Ce qui lit les pages : le fournisseur de la recherche, sans son
        # moteur — c'est l'agent qui cherche, avec son propre outil.
        provider = get_provider(
            config,
            api_key=env.anthropic_key,
            serper_key=env.serper_key,
            openrouter_key=env.openrouter_key,
            search=False,
        )
        pilot = Pilot(
            str(job.get("pilot") or PILOTE_DEFAUT),
            provider.usage,
            api_key=env.openrouter_key,
            effort=EFFORT,
        )
        search = None if config.targets_site else SerperClient(env.serper_key)
        limits = limits_for(config.max_searches)

        with open_agent_log(runs_dir, config.name, quiet, journal.add) as log:
            ctx = RunContext(
                config=config,
                provider=provider,
                store=store,
                api=api,
                fetcher=Fetcher(),
                log=log,
                submit=submit,
            )
            toolbox = Toolbox(ctx, limits, search=search, engine=client_or_none(env.serper_key))
            result = run_agent(ctx, pilot, toolbox, limits)
            summary = result.run.summary
            if not quiet:
                print(f"  {result.reason} — {len(result.run.events)} sortie(s)", flush=True)
        status, error = "DONE", None
    except (ProviderError, ApiError) as err:
        error = str(err)
    except Exception as err:  # noqa: BLE001 — la trace part dans la console du service
        traceback.print_exc()
        error = f"{err.__class__.__name__} : {err}"
    finally:
        journal.flush()
        try:
            store.flush()
        except ApiError as err:
            print(f"Journal du run incomplet : {err}", file=sys.stderr, flush=True)
        payload = counters(summary)
        if error:
            payload["error"] = error[:2000]
        finish(api, run_id, status, payload, quiet)
        if not quiet:
            done = "terminée" if status == "DONE" else f"en échec ({error})"
            print(f"■ Exécution #{run_id} {done} — {payload['costUsd']} $", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentbot.worker",
        description="Joue les exécutions de l'agent mises en file depuis la console.",
    )
    parser.add_argument("--once", action="store_true", help="au plus une exécution, puis sortir")
    parser.add_argument("--interval", type=int, default=POLL_SECONDS)
    parser.add_argument("--quiet", "-q", action="store_true", help="pas de sortie console")
    parser.add_argument("--runs-dir", default=str(ROOT / "runs"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env")
    env = Environment.from_env()

    missing = [
        name
        for name, value in (
            ("SPP_API_KEY", env.api_key),
            # Le pilote passe toujours par OpenRouter, quel que soit le
            # fournisseur qui lit les pages.
            ("OPENROUTER_API_KEY", env.openrouter_key),
            ("SERPER_API_KEY", env.serper_key),
        )
        if not value
    ]
    if missing:
        print(f"Clé(s) requise(s) : {', '.join(missing)} (voir .env.example)", file=sys.stderr)
        return 2

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    api = SppApi(env.api_url, env.api_key)
    runs_dir = Path(args.runs_dir)
    if not args.quiet:
        print(f"Worker de l'agent en écoute sur {env.api_url} (toutes les {args.interval} s).", flush=True)

    while not _stop:
        try:
            job = next_agent_run(api)
        except ApiError as err:
            if not args.quiet:
                print(f"Site injoignable ({err}) — nouvelle tentative.", file=sys.stderr, flush=True)
            job = None
        if job:
            execute(job, api, env, runs_dir, args.quiet)
            if args.once:
                return 0
            continue
        if args.once:
            if not args.quiet:
                print("Rien en file.", flush=True)
            return 0
        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
