"""Ligne de commande du scraper.

    python -m sortiesbot --config configs/spectacles-weekend.yaml
    python -m sortiesbot --config configs/spectacles-weekend.yaml --submit

Sans `--submit`, rien n'est envoyé au site : le run écrit un JSON de sorties
retenues à relire, et le journal détaillé de ce qu'il a consulté.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .api import SppApi
from .config import ConfigError, Environment, load_config, load_dotenv, with_limit
from .harvest import Fetcher
from .journal import RunLog, run_log_path
from .ledger import Ledger, ledger_path
from .orchestrator import run
from .providers.base import ProviderError, get_provider
from .store import SeenStore

ROOT = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sortiesbot",
        description="Cherche des sorties pour enfants et les propose au site.",
    )
    parser.add_argument("--config", "-c", required=True, help="fichier YAML de configuration")
    parser.add_argument(
        "--submit",
        action="store_true",
        help="soumet réellement les sorties (sinon : dry-run, rien n'est envoyé)",
    )
    parser.add_argument("--limit", "-n", type=int, help="plafonne le nombre de sorties du run")
    parser.add_argument("--quiet", "-q", action="store_true", help="pas de sortie console")
    parser.add_argument(
        "--runs-dir",
        default=str(ROOT / "runs"),
        help="dossier des journaux de run (défaut : scraper/runs)",
    )
    parser.add_argument(
        "--state",
        default=str(ROOT / "state" / "seen.sqlite3"),
        help="base des URLs déjà vues (défaut : scraper/state/seen.sqlite3)",
    )
    parser.add_argument(
        "--classifier-dir",
        default=str(ROOT / "state"),
        help=(
            "dossier du registre du classifieur — un fichier horodaté par run, "
            "hors journaux de run (défaut : scraper/state ; « - » pour ne rien écrire)"
        ),
    )
    parser.add_argument(
        "--save-pages",
        metavar="DOSSIER",
        help="archive chaque page téléchargée, pour en faire des fixtures de test",
    )
    parser.add_argument(
        "--forget",
        action="store_true",
        help="ignore la mémoire des URLs déjà vues (utile pour rejouer un run)",
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

    if args.submit and not env.api_key:
        print("SPP_API_KEY est requis pour --submit (voir .env.example)", file=sys.stderr)
        return 2

    runs_dir = Path(args.runs_dir)
    log_path = run_log_path(runs_dir, config.name)
    state_path = ":memory:" if args.forget else args.state

    try:
        provider = get_provider(config, api_key=env.anthropic_key, serper_key=env.serper_key)
    except ProviderError as err:
        print(str(err), file=sys.stderr)
        return 2

    api = SppApi(env.api_url, env.api_key)

    if not args.quiet:
        print(f"Journal : {log_path}")
        if config.targets_site:
            print(
                f"Mode « site » : aucune recherche web, {len(config.seed_urls)} page(s) de\n"
                "départ. Les lignes ci-dessous arrivent au fur et à mesure, le temps\n"
                "écoulé est indiqué à gauche.\n"
            )
        else:
            print(
                "La découverte enchaîne recherches et lectures de pages dans un seul\n"
                "appel : comptez plusieurs minutes. Les lignes ci-dessous arrivent au\n"
                "fur et à mesure, le temps écoulé est indiqué à gauche.\n"
            )

    registre = (
        None if args.classifier_dir in ("", "-")
        else ledger_path(args.classifier_dir, log_path.stem)
    )
    # Chaque run archive dans son propre dossier : deux captures du même site
    # à deux semaines d'écart sont deux données, pas une qui écrase l'autre.
    pages_dir = Path(args.save_pages) / log_path.stem if args.save_pages else None
    fetcher = Fetcher(archive=pages_dir) if pages_dir else None

    with RunLog(log_path, verbose=not args.quiet) as log, SeenStore(state_path) as store, Ledger(
        registre, run=log_path.stem
    ) as ledger:
        result = run(
            config, provider, store, api, log,
            submit=args.submit, fetcher=fetcher, ledger=ledger,
        )

    output = log_path.with_suffix(".json")
    output.write_text(
        json.dumps(
            {
                "config": config.name,
                "mode": "submit" if args.submit else "dry-run",
                "summary": result.summary.as_dict(),
                "candidates": result.candidates,
                "events": result.events,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if not args.quiet:
        print(f"\nJournal  : {log_path}")
        if registre:
            print(f"Registre : {registre}")
        if pages_dir:
            print(f"Pages    : {pages_dir}")
        print(f"Sorties  : {output}")
        if not args.submit and result.events:
            print("Relisez le JSON, puis relancez avec --submit pour proposer ces sorties.")
        elif result.candidates:
            print(
                f"{len(result.candidates)} page(s) repérée(s) mais non exploitée(s) — "
                "elles sont dans le JSON, sous « candidates »."
            )

    return 1 if result.summary.errors and not result.events else 0


if __name__ == "__main__":
    raise SystemExit(main())
