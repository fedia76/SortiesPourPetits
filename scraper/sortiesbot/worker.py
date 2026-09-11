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
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any, Callable

from .api import ApiError, SppApi
from .config import Config, ConfigError, Environment, config_from_api, load_dotenv
from .evaluation import (
    capture_pages,
    extract_page,
    harvest_from_html,
    read_from_html,
    select_from_html,
)
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

#: Attentes avant chaque nouvelle tentative de clôture. C'est le seul appel du
#: worker qu'on ne peut pas perdre : sans lui l'exécution reste « En cours »
#: dans la console et bloque toute nouvelle exécution de la configuration,
#: jusqu'à une annulation à la main. Les reprises de connexion de la session
#: (`api.retrying_session`) couvrent la seconde ; celles-ci couvrent la minute
#: — le temps qu'une API redémarrée réponde à nouveau.
FINISH_DELAYS = (2, 4, 8)

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


def finish(
    api: SppApi,
    run_id: int,
    status: str,
    payload: dict[str, Any],
    quiet: bool,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Clôt l'exécution, et insiste : c'est ce qu'on ne peut pas perdre.

    Une clôture perdue ne se rattrape pas — personne ne repasse fermer un run,
    et la configuration reste bloquée. Un déploiement du site suffisait à en
    arriver là : l'API redémarre, la clôture tombe sur une connexion refusée,
    le worker enchaîne. On réessaie donc, de plus en plus loin.

    Rend vrai si le site a pris la clôture. Faux, le worker continue de toute
    façon : le run suivant ne doit pas payer l'échec du précédent, et le
    serveur ferme d'office les exécutions dont il n'a plus de nouvelles.
    """
    last: Exception | None = None
    for attempt, delay in enumerate((0.0, *FINISH_DELAYS)):
        if delay:
            sleep(delay)
        try:
            api.finish_run(run_id, status, **payload)
            if attempt and not quiet:
                print(f"  clôture obtenue au {attempt + 1}e essai.", flush=True)
            return True
        except ApiError as err:
            last = err
    print(
        f"Clôture impossible de l'exécution #{run_id} après {len(FINISH_DELAYS) + 1} "
        f"essais : {last}. Le serveur la fermera d'office.",
        file=sys.stderr,
        flush=True,
    )
    return False


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
        # Même exigence qu'à la sortie normale : une configuration illisible
        # n'est pas une raison pour laisser la ligne « En cours » à vie.
        finish(api, run_id, "FAILED", {"error": str(err)}, quiet)
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
        finish(api, run_id, status, payload, quiet)
        if not quiet:
            done = "terminée" if status == "DONE" else f"en échec ({error})"
            print(f"■ Exécution #{run_id} {done} — {payload['costUsd']} $", flush=True)


def capture(job: dict[str, Any], api: SppApi, quiet: bool) -> None:
    """Gèle une entrée du corpus, et la clôt quoi qu'il arrive.

    Capturer n'est pas mesurer : on télécharge, on archive le HTML, on n'en
    tire aucun relevé. Ce que les briques rendent est l'affaire d'un run, qui
    rejouera plus tard sur ce qui vient d'être gelé — et c'est ce découplage
    qui rend deux runs comparables.

    Le `finally` a la même raison qu'ailleurs : le site a déjà passé l'entrée
    en RUNNING, et sans clôture elle ne serait plus jamais réclamée.
    """
    kind = str(job.get("kind") or "agenda")
    item_id = int(job["id"])
    url = str(job["url"])
    pages = int(job.get("pages") or 1)
    if not quiet:
        print(f"▶ Corpus — {kind} #{item_id} : {url} ({pages} page(s))", flush=True)

    reported = False
    try:
        gelees = capture_pages(url, pages, fetcher=Fetcher())
        api.report_capture(kind, item_id, gelees)
        reported = True
        if not quiet:
            poids = sum(p.get("chars", 0) for p in gelees)
            print(f"■ Corpus — {kind} #{item_id} : {len(gelees)} page(s), {poids} caractères", flush=True)
    except ApiError as err:
        print(f"Capture non rendue pour {kind} #{item_id} : {err}", file=sys.stderr, flush=True)
    except Exception as err:  # noqa: BLE001 — la trace part dans la console du service
        traceback.print_exc()
        if not reported:
            try:
                api.fail_capture(kind, item_id, f"{err.__class__.__name__} : {err}")
            except ApiError as api_err:
                print(f"Clôture impossible de {kind} #{item_id} : {api_err}", file=sys.stderr, flush=True)


def _bench_config() -> Config:
    """La configuration du banc. Une seule, et toujours la même.

    Le banc mesure une brique et son prompt, pas les plafonds d'une recherche
    particulière : c'est pourquoi elle ne vient d'aucun fichier et ne se règle
    pas. Elle est construite **avant** de réclamer un run, et la même instance
    sert à le déclarer puis à le jouer — sinon un run réclamé le 31 à 23 h 59
    serait joué sous la fenêtre du 1er, et sa mesure serait faussée d'un jour.
    """
    return Config(name="banc", theme="sorties enfants")


def _scope(config: Config) -> dict[str, Any]:
    """Ce sous quoi le tri a été joué, dit au site.

    Le site ne peut pas deviner la fenêtre d'un run, et sans elle il ne sait
    pas si une sortie écartée l'a été à raison — elle serait comptée contre le
    modèle. D'où cette déclaration, faite *avant* de jouer et non reconstituée
    après coup.

    La fenêtre, le thème et le plafond sont mot pour mot ce que
    `render_select` met dans le prompt. Les préfixes, eux, sont la zone
    (« $area ») sous la seule forme que le site sache comparer à un code
    postal : c'est la même contrainte, écrite en chiffres.
    """
    return {
        "dateFrom": config.date_from.isoformat(),
        "dateTo": config.date_to.isoformat(),
        "postalPrefixes": list(config.postal_prefixes),
        "maxLinks": config.max_links_per_agenda,
        "theme": config.theme,
    }


def _code_ref() -> str:
    """La révision qui tourne, si le dépôt est là. Vide sinon, et c'est dit.

    Sans elle, un point de la courbe ne s'attribue à rien. On ne la devine pas :
    ou bien git répond, ou bien le run le déclare inconnu.
    """
    try:
        import subprocess

        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip()[:60] if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001 — un dépôt absent n'est pas une panne
        return ""


def play_run(
    run: dict[str, Any],
    api: SppApi,
    env: Environment,
    quiet: bool,
    bench: Config,
) -> None:
    """Joue un run du banc : une brique, sur tout le corpus gelé.

    Le worker ne télécharge rien ici. Chaque entrée arrive **avec son HTML**,
    tel que la capture l'a figé, et la brique est rejouée dessus. Un écart
    entre deux runs ne peut donc venir que du code — ce qui est toute la raison
    d'être d'un banc.

    Les étages 4 et 6 appellent le modèle et se paient ; les étages 3 et 5 sont
    du Python pur. Le coût est compté et rendu à la clôture, parce qu'une
    mesure dont on tait le prix passe pour gratuite.
    """
    run_id = int(run["id"])
    stage = str(run["stage"])
    if not quiet:
        titre = run.get("label") or "sans étiquette"
        print(f"▶ Banc — run #{run_id} · étage {stage} · « {titre} »", flush=True)

    provider = None
    config = None
    log = RunLog(None, verbose=False)
    if stage in ("SELECT", "EXTRACT"):
        # Celle-là même qui a été déclarée au moment de réclamer le run : le
        # site mesurera le tri sous la fenêtre que le modèle a réellement vue.
        config = bench
        provider = get_provider(config, api_key=env.anthropic_key, serper_key=env.serper_key)

    traites = 0
    status, error = "DONE", None
    try:
        while not _stop:
            item = api.next_eval_item(run_id)
            if not item:
                break
            html = str(item.get("html") or "")
            if stage in ("HARVEST", "SELECT"):
                page_id = int(item["pageId"])
                url = str(item["url"])
                if stage == "HARVEST":
                    result = harvest_from_html(html, url)
                else:
                    result = select_from_html(
                        html, url, provider=provider, config=config, log=log
                    )
                result["pageId"] = page_id
                api.report_eval_links(run_id, result)
            elif stage == "READ":
                sortie_id = int(item["sortieId"])
                result = read_from_html(html, str(item["url"]), fetcher=Fetcher())
                result["sortieId"] = sortie_id
                # `url` est l'adresse *lue* — celle que l'échange de langue a
                # pu changer. Le site la range sous `readUrl` ; la clé `url`
                # n'a pas de place dans son schéma.
                result["readUrl"] = result.pop("url", "")
                api.report_eval_read(run_id, result)
            else:
                sortie_id = int(item["sortieId"])
                lecture = read_from_html(html, str(item["url"]), fetcher=Fetcher())
                result = extract_page(
                    str(item["url"]),
                    lecture.get("text", ""),
                    provider=provider,
                    config=config,
                    log=log,
                    declared_dates=lecture.get("dates", []),
                )
                result["sortieId"] = sortie_id
                api.report_eval_extract(run_id, result)
            traites += 1
    except ApiError as err:
        status, error = "FAILED", str(err)
    except Exception as err:  # noqa: BLE001 — la trace part dans la console du service
        traceback.print_exc()
        status, error = "FAILED", f"{err.__class__.__name__} : {err}"
    finally:
        usage = getattr(provider, "usage", None)
        payload: dict[str, Any] = {
            "items": traites,
            "inputTokens": int(getattr(usage, "input_tokens", 0) or 0),
            "outputTokens": int(getattr(usage, "output_tokens", 0) or 0),
            "costUsd": round(float(getattr(usage, "total_usd", 0.0) or 0.0), 4),
        }
        if error:
            payload["error"] = error
        try:
            api.finish_eval_run(run_id, status, **payload)
        except ApiError as err:
            print(f"Clôture impossible du run #{run_id} : {err}", file=sys.stderr, flush=True)
        if not quiet:
            fin = "terminé" if status == "DONE" else f"en échec ({error})"
            print(f"■ Banc — run #{run_id} {fin} — {traites} entrée(s), {payload['costUsd']} $", flush=True)



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
        # sorties que des parents attendent, le banc attend un humain qui le
        # relira quand il pourra. À file égale, c'est la recherche qui passe.
        #
        # Et dans le banc, **capturer avant mesurer** : un run joué sur un
        # corpus incomplet mesure ce qu'on a sous la main, pas ce qu'on voulait
        # mesurer. Geler est en outre gratuit, là où un run des étages 4 et 6
        # se paie.
        try:
            job = api.next_capture()
        except ApiError as err:
            if not args.quiet:
                print(f"Banc injoignable ({err}) — nouvelle tentative.", file=sys.stderr, flush=True)
            job = None
        if job:
            capture(job, api, args.quiet)
            if args.once:
                return 0
            continue

        bench = _bench_config()
        try:
            run = api.next_eval_run(code_ref=_code_ref(), settings=_scope(bench))
        except ApiError as err:
            if not args.quiet:
                print(f"Banc injoignable ({err}) — nouvelle tentative.", file=sys.stderr, flush=True)
            run = None
        if run:
            play_run(run, api, env, args.quiet, bench)
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
