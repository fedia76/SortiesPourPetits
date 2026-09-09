"""Worker : exécute les recherches mises en file depuis la console du site.

    python -m sortiesbot.worker            # boucle, une passe toutes les 30 s
    python -m sortiesbot.worker --once     # traite au plus une exécution

Le worker ne décide de rien. Il réclame le travail en attente
(`POST /api/scraper/next`), joue le pipeline avec la configuration que le site
lui donne, rend compte page par page (`/runs/:id/items`) puis clôt l'exécution
avec ses compteurs (`/runs/:id/finish`). Tout le reste — créer une recherche,
la lancer, la relire — se passe dans la console.

Sur le VPS il tourne en service systemd (voir deploy/README.md) : c'est lui
qui doit être démarré pour que le bouton « Lancer » de la console fasse
quelque chose.
"""

from __future__ import annotations

import argparse
import signal
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from .api import ApiError, SppApi
from .config import ConfigError, Environment, config_from_api, load_dotenv
from .evaluation import harvest_agenda, read_page
from .harvest import Fetcher
from .journal import RemoteJournal, RunLog, run_log_path
from .ledger import Ledger, ledger_path
from .models import Summary
from .orchestrator import run as run_pipeline
from .orchestrator import run_source
from .providers.serper_client import client_or_none
from .providers.base import ProviderError, get_provider
from .store import RemoteStore

ROOT = Path(__file__).resolve().parent.parent

#: Dossier du registre du classifieur. Volontairement hors de `runs/` : les
#: journaux d'exécution s'oublient depuis la console du site, cette mesure doit
#: s'accumuler sur des semaines. Un fichier horodaté par exécution.
LEDGER_DIR = ROOT / "state"

#: Attente entre deux passages à vide. Une recherche dure des minutes ; une
#: demi-minute de latence au démarrage ne se voit pas dans la console.
POLL_SECONDS = 30

_stop = False


def _handle_signal(*_args: object) -> None:
    """Arrêt propre : on finit l'exécution en cours, on ne prend pas la suivante."""
    global _stop
    _stop = True
    print("Arrêt demandé : le worker s'arrêtera après l'exécution en cours.", flush=True)


def open_log(
    runs_dir: Path,
    name: str,
    quiet: bool,
    sink: Callable[[dict[str, Any]], None] | None = None,
) -> RunLog:
    """Ouvre le journal fichier du run, en insistant un peu.

    Un dossier `runs/` devenu illisible — typiquement créé par root lors d'un
    essai en ligne de commande, alors que le service tourne en `deploy` — ne
    doit pas faire échouer une recherche. Mais s'en passer entièrement, comme
    avant, laissait le run sans aucune trace fichier : on se rabat donc sur un
    dossier temporaire, qui est toujours accessible, avant d'abandonner.

    Le `sink` est l'autre destination du journal : le site, qui l'affiche dans
    sa page de débogage.
    """
    candidates = [runs_dir, Path(tempfile.gettempdir()) / "sortiesbot-runs"]
    for index, directory in enumerate(candidates):
        try:
            log = RunLog(run_log_path(directory, name), verbose=not quiet, sink=sink)
        except OSError as err:
            print(
                f"Journal impossible dans {directory} ({err}).",
                file=sys.stderr,
                flush=True,
            )
            continue
        if index and not quiet:
            print(f"  journal replié sur {log.path}", flush=True)
        return log
    print(
        "Aucun journal fichier : le run continue, le site garde le sien.",
        file=sys.stderr,
        flush=True,
    )
    return RunLog(None, verbose=not quiet, sink=sink)


def counters(summary: Summary) -> dict[str, Any]:
    """Compteurs du run tels que la console les affiche."""
    return {
        "candidates": summary.candidates,
        "pages": summary.pages,
        "nextPages": summary.next_pages,
        "retained": summary.retained,
        "submitted": summary.submitted,
        "duplicates": summary.duplicates,
        "skipped": (
            summary.skipped_seen
            + summary.skipped_blocked
            + summary.skipped_irrelevant
            + summary.skipped_invalid
        ),
        "errors": summary.errors,
        "inputTokens": summary.usage.input_tokens,
        "outputTokens": summary.usage.output_tokens,
        "webSearches": summary.usage.web_searches,
        "costUsd": round(summary.usage.total_usd, 4),
    }


def execute(job: dict[str, Any], api: SppApi, env: Environment, runs_dir: Path, quiet: bool) -> None:
    """Joue une exécution réclamée au site, et la clôt quoi qu'il arrive.

    Le site l'a déjà passée en RUNNING : la laisser sans clôture la figerait
    dans la console, et bloquerait toute nouvelle exécution de la même
    configuration. D'où le `finally` — même sur une erreur imprévue.

    Deux sortes d'exécution passent par ici, et c'est le site qui les
    distingue : une exécution qui porte une **sortie** est une recherche de
    source — l'étage 7 rejoué seul, sur une fiche déjà publiée — et tout le
    reste est le pipeline entier. Elles partagent tout ce qui les entoure : le
    journal renvoyé au site, le registre, la clôture, les compteurs. Seule la
    ligne qui joue change, et elle est visible à l'œil nu ci-dessous.
    """
    run_id = int(job["id"])
    submit = bool(job.get("submit"))
    event = job.get("event") or None
    status, error = "FAILED", "Interrompu avant la fin"
    summary = Summary()

    try:
        config = config_from_api(job.get("config") or {})
    except ConfigError as err:
        api.finish_run(run_id, "FAILED", error=str(err))
        return

    if not quiet:
        quoi = f"source de « {event.get('title')} »" if event else f"« {config.name} »"
        print(f"▶ Exécution #{run_id} — {quoi}", flush=True)

    store = RemoteStore(api, run_id)
    # Le journal détaillé part au site au fil de l'eau : c'est lui que la page
    # de débogage affiche, étage par étage.
    journal = RemoteJournal(api, run_id)
    try:
        provider = get_provider(config, api_key=env.anthropic_key, serper_key=env.serper_key)
        with open_log(runs_dir, config.name, quiet, sink=journal.add) as log:
            if log.path and not quiet:
                print(f"  journal : {log.path}", flush=True)
            # Le service tourne des semaines : c'est lui qui alimente
            # vraiment le registre du classifieur, à côté des journaux de run
            # que le site peut oublier.
            with Ledger(ledger_path(LEDGER_DIR, run_id), run=str(run_id)) as ledger:
                # Le moteur du repli de l'attribution : présent dès qu'une clé
                # Serper l'est, quel que soit le fournisseur de la recherche
                # que la console a choisi.
                engine = client_or_none(env.serper_key)
                if event is None:
                    summary = run_pipeline(
                        config, provider, store, api, log, submit=submit,
                        ledger=ledger, engine=engine,
                    ).summary
                else:
                    found = run_source(
                        config, provider, store, api, log, event,
                        ledger=ledger, engine=engine,
                    )
                    summary = found.summary
                    # Le rapport fait partie du travail : une recherche qui
                    # trouve sans le dire n'a rien fait. S'il échoue, le run
                    # est en échec — et la fiche garde le lien qu'elle avait.
                    api.report_source(
                        run_id,
                        url=found.source.url,
                        signal=found.source.signal,
                        detail=found.source.detail,
                        checked=found.source.checked,
                        found_on=str(event.get("pageUrl") or ""),
                    )
        status, error = "DONE", None
    except ProviderError as err:
        error = str(err)
    except ApiError as err:
        error = str(err)
    except Exception as err:  # noqa: BLE001 — la trace part dans la console du service
        traceback.print_exc()
        error = f"{err.__class__.__name__} : {err}"
    finally:
        # Le journal d'abord : la console doit pouvoir montrer ce qui s'est
        # passé, y compris — surtout — quand l'exécution se termine en échec.
        journal.flush()
        try:
            store.flush()
        except ApiError as err:
            print(f"Journal du run incomplet : {err}", file=sys.stderr, flush=True)
        payload = counters(summary)
        if error:
            payload["error"] = error[:2000]
        try:
            api.finish_run(run_id, status, **payload)
        except ApiError as err:
            # Sans clôture, la console reste sur « En cours » : c'est visible,
            # et le bouton « Annuler » permet de débloquer la configuration.
            print(f"Clôture impossible de l'exécution #{run_id} : {err}", file=sys.stderr, flush=True)
        if not quiet:
            done = "terminée" if status == "DONE" else f"en échec ({error})"
            print(f"■ Exécution #{run_id} {done} — {payload['costUsd']} $", flush=True)


def evaluate(agenda: dict[str, Any], api: SppApi, quiet: bool) -> None:
    """Dépouille un agenda du banc d'évaluation, et le clôt quoi qu'il arrive.

    Beaucoup plus court qu'`execute`, et ça en dit long sur ce que coûte le
    pipeline : ici il n'y a ni modèle, ni journal, ni mémoire, ni sortie
    soumise. Seulement des pages téléchargées et `links_of` appelé dessus.

    Le `finally` a la même raison qu'ailleurs : le site a déjà passé l'agenda
    en RUNNING, et sans clôture il ne serait plus jamais réclamé.
    """
    agenda_id = int(agenda["id"])
    url = str(agenda["url"])
    pages = int(agenda.get("pages") or 1)
    if not quiet:
        print(f"▶ Banc — agenda #{agenda_id} : {url} ({pages} page(s))", flush=True)

    reported = False
    try:
        found = harvest_agenda(url, pages, fetcher=Fetcher())
        api.report_harvest(agenda_id, found)
        reported = True
        if not quiet:
            total = sum(len(p.get("links") or []) for p in found)
            print(f"■ Banc — agenda #{agenda_id} : {total} lien(s) sur {len(found)} page(s)", flush=True)
    except ApiError as err:
        # Le compte rendu n'est pas passé. Tenter de clore par la même API a
        # peu de chances d'aboutir, mais rien à casser si elle revient.
        print(f"Compte rendu impossible pour l'agenda #{agenda_id} : {err}", file=sys.stderr, flush=True)
    except Exception as err:  # noqa: BLE001 — la trace part dans la console du service
        traceback.print_exc()
        if not reported:
            try:
                api.fail_harvest(agenda_id, f"{err.__class__.__name__} : {err}")
            except ApiError as api_err:
                print(f"Clôture impossible de l'agenda #{agenda_id} : {api_err}", file=sys.stderr, flush=True)


def read(reading: dict[str, Any], api: SppApi, quiet: bool) -> None:
    """Rejoue l'étage 5 sur une page du banc, et la clôt quoi qu'il arrive.

    Une page injoignable n'est pas un échec du banc : c'est une réponse, et
    `read_page` la rapporte avec son motif. L'échec, ici, c'est de ne pas
    réussir à rendre compte — et le `finally` est là pour ça, comme ailleurs.
    """
    reading_id = int(reading["id"])
    url = str(reading["url"])
    if not quiet:
        print(f"▶ Banc — lecture #{reading_id} : {url}", flush=True)

    try:
        result = read_page(url, fetcher=Fetcher())
        api.report_reading(reading_id, result)
        if not quiet:
            if result.get("error"):
                print(f"■ Banc — lecture #{reading_id} : {result['error']}", flush=True)
            else:
                print(
                    f"■ Banc — lecture #{reading_id} : {result['textChars']} caractères, "
                    f"{len(result['dates'])} date(s), illustration "
                    f"{'oui' if result['imageUrl'] else 'non'}",
                    flush=True,
                )
    except ApiError as err:
        print(f"Compte rendu impossible pour la lecture #{reading_id} : {err}", file=sys.stderr, flush=True)
    except Exception as err:  # noqa: BLE001 — la trace part dans la console du service
        traceback.print_exc()
        try:
            api.fail_reading(reading_id, f"{err.__class__.__name__} : {err}")
        except ApiError as api_err:
            print(f"Clôture impossible de la lecture #{reading_id} : {api_err}", file=sys.stderr, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sortiesbot.worker",
        description="Exécute les recherches mises en file depuis la console du site.",
    )
    parser.add_argument("--once", action="store_true", help="au plus une exécution, puis sortir")
    parser.add_argument(
        "--interval",
        type=int,
        default=POLL_SECONDS,
        help=f"secondes entre deux passages à vide (défaut : {POLL_SECONDS})",
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="pas de sortie console")
    parser.add_argument(
        "--runs-dir",
        default=str(ROOT / "runs"),
        help="dossier des journaux de run (défaut : scraper/runs)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env")
    env = Environment.from_env()

    # Le worker soumet des sorties et écrit dans la mémoire partagée : sans
    # clé d'API il ne peut rien faire, autant le dire tout de suite.
    if not env.api_key:
        print("SPP_API_KEY est requis (voir .env.example)", file=sys.stderr)
        return 2
    if not env.anthropic_key:
        print("ANTHROPIC_API_KEY est requis (voir .env.example)", file=sys.stderr)
        return 2

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    api = SppApi(env.api_url, env.api_key)
    runs_dir = Path(args.runs_dir)
    if not args.quiet:
        print(f"Worker en écoute sur {env.api_url} (toutes les {args.interval} s).", flush=True)

    while not _stop:
        try:
            job = api.next_run()
        except ApiError as err:
            # Site en cours de redéploiement, base indisponible : on réessaie.
            if not args.quiet:
                print(f"Site injoignable ({err}) — nouvelle tentative.", file=sys.stderr, flush=True)
            job = None
        if job:
            execute(job, api, env, runs_dir, args.quiet)
            if args.once:
                return 0
            continue

        # Les recherches d'abord, le banc ensuite : une recherche produit des
        # sorties que des parents attendent, un agenda du banc attend un humain
        # qui le relira quand il pourra. À file égale, c'est la recherche qui
        # passe.
        try:
            agenda = api.next_harvest()
        except ApiError as err:
            if not args.quiet:
                print(f"Banc injoignable ({err}) — nouvelle tentative.", file=sys.stderr, flush=True)
            agenda = None
        if agenda:
            evaluate(agenda, api, args.quiet)
            if args.once:
                return 0
            continue

        # Le banc de lecture en dernier : c'est la file la moins pressée des
        # trois, une page qui attend son humain n'attend pas à la minute.
        try:
            reading = api.next_reading()
        except ApiError as err:
            if not args.quiet:
                print(f"Banc injoignable ({err}) — nouvelle tentative.", file=sys.stderr, flush=True)
            reading = None
        if reading:
            read(reading, api, args.quiet)
            if args.once:
                return 0
        elif args.once:
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
