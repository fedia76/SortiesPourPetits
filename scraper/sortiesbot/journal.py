"""Journal d'un run : une ligne JSONL par événement, et une ligne lisible en console.

Le fichier JSONL est la trace détaillée de ce que le run a consulté — requêtes
lancées, pages ouvertes, pages ignorées et pourquoi, extractions, géocodages,
soumissions. C'est ce qui alimentera la table `ScraperRunItem` quand les runs
seront pilotés depuis la console d'administration : chaque ligne y est déjà un
enregistrement autonome.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

#: Rendu console d'un événement du journal, par type.
_CONSOLE = {
    "run_start": lambda f: f"▶ Run « {f.get('config', {}).get('name', '?')} » — {f.get('mode')}",
    "query": lambda f: f"  🔎 recherche : {f.get('query')}",
    "visited": lambda f: f"  📄 page lue : {f.get('url')}",
    "search_result": lambda f: f"     · {f.get('url')}",
    "candidate": lambda f: f"  ★ candidat : {f.get('title')} — {f.get('url')}",
    "skip": lambda f: f"  ⊘ ignoré ({f.get('reason')}) : {f.get('url')}",
    "extract": lambda f: f"  ✎ extrait : {f.get('title')} — {f.get('venue')}",
    "geocode": lambda f: (
        f"  📍 {f.get('query')} → {f.get('lat')}, {f.get('lng')}"
        if f.get("located")
        else f"  📍 non géolocalisé ({f.get('reason')}) : {f.get('query')}"
    ),
    "incomplete": lambda f: f"  ⚑ {f.get('field')} à compléter par la modération : {f.get('title')}",
    "paused": lambda f: (
        f"  ⏸ tour en pause (limite serveur), reprise — {f.get('cost_usd')} $ déjà engagés"
    ),
    "budget": lambda f: f"  ⛔ budget atteint ({f.get('spent')} $ / {f.get('limit')} $) : run arrêté",
    "thinking": lambda f: f"     … {f.get('text')}",
    "photo": lambda f: f"  🖼 photo {f.get('status')} : {f.get('url')}",
    "submit": lambda f: f"  ✅ soumise (#{f.get('event_id')}) : {f.get('title')}",
    "dry_run": lambda f: f"  ○ retenue (dry-run) : {f.get('title')}",
    "usage": lambda f: (
        f"  ⚙ {f.get('stage')} [{f.get('model')}] "
        f"{f.get('input_tokens')} entrée / {f.get('output_tokens')} sortie jetons"
    ),
    "error": lambda f: f"  ✗ erreur ({f.get('stage')}) : {f.get('message')}",
    "run_end": lambda f: f"■ Fin du run — {json.dumps(f.get('summary', {}), ensure_ascii=False)}",
}


class RunLog:
    """Écrit le journal d'un run. Utilisable en gestionnaire de contexte."""

    def __init__(self, path: Path | None, verbose: bool = True, stream: TextIO | None = None):
        self.path = path
        self.verbose = verbose
        self.stream = stream if stream is not None else sys.stdout
        # Un run dure plusieurs minutes : le temps écoulé en tête de chaque
        # ligne dit d'un coup d'œil que ça avance encore.
        self.started_at = time.monotonic()
        self._file: TextIO | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("a", encoding="utf-8")

    def __enter__(self) -> "RunLog":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def event(self, kind: str, **fields: Any) -> None:
        record = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind,
            **fields,
        }
        if self._file is not None:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()
        if self.verbose:
            render = _CONSOLE.get(kind)
            line = render(fields) if render else f"  {kind}: {json.dumps(fields, ensure_ascii=False)}"
            elapsed = int(time.monotonic() - self.started_at)
            print(f"[{elapsed // 60:d}:{elapsed % 60:02d}] {line}", file=self.stream, flush=True)

    def error(self, stage: str, message: str, **fields: Any) -> None:
        self.event("error", stage=stage, message=message, **fields)


def run_log_path(directory: Path, config_name: str) -> Path:
    """`runs/2026-08-27T14-30-05_spectacles-weekend.jsonl`"""
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in config_name.lower())
    return directory / f"{stamp}_{slug}.jsonl"
