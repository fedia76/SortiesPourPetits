"""Le registre d'observation : ce qui doit survivre à l'oubli d'un journal.

Le journal d'un run répond à « que s'est-il passé cette fois-ci ? », et le
site offre un bouton pour l'oublier — il est verbeux, et c'est très bien
ainsi. Une mesure qui s'accumule sur des semaines n'a donc rien à y faire :
elle disparaîtrait au premier ménage, et c'est précisément le mois de données
qui aurait servi à trancher.

D'où ce fichier à part, en dehors de `runs/` : une ligne JSON par observation,
ajoutée et jamais réécrite. Il n'est lu par personne pendant un run ; il
s'analyse après coup, avec `jq` ou trois lignes de Python.

Sans chemin, le registre ne fait rien. C'est le cas des tests et des runs
lancés à la main : on ne veut pas qu'une exécution jetable pollue une mesure.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


def ledger_path(directory: Path | str, run: str = "") -> Path:
    """`state/classifier_2026-09-01T03-38-29_14.jsonl`

    Un fichier par exécution, horodaté comme les journaux de `runs/` : deux
    runs ne se marchent jamais dessus, et un fichier se copie, s'archive ou
    s'envoie sans emporter les autres. L'analyse les relit d'un coup —
    `state/classifier_*.jsonl` — donc rien n'est perdu à les séparer.
    """
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    slug = "".join(c for c in str(run) if c.isalnum() or c in "-_")
    return Path(directory) / f"classifier_{stamp}{'_' + slug if slug else ''}.jsonl"


class Ledger:
    """Un JSONL en ajout seul. Muet si aucun chemin n'est donné."""

    def __init__(self, path: Path | str | None = None, *, run: str = "") -> None:
        self.path = str(path) if path else ""
        self.run = run
        self._file: TextIO | None = None
        if not self.path:
            return
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.path, "a", encoding="utf-8")
        except OSError as err:
            # Un instrument de mesure ne fait pas échouer ce qu'il mesure :
            # dossier illisible, disque plein, droits refusés — on perd le
            # registre, jamais la collecte.
            print(f"Registre indisponible ({err}) : le run continue sans.", file=sys.stderr)

    def record(self, topic: str, **fields: Any) -> None:
        """Ajoute une observation. Une écriture ratée ne casse pas le run.

        Un registre est un instrument de mesure, pas une dépendance : un
        disque plein doit faire perdre la mesure, jamais la collecte.
        """
        if self._file is None:
            return
        line = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run": self.run,
            "topic": topic,
            **fields,
        }
        try:
            self._file.write(json.dumps(line, ensure_ascii=False) + "\n")
            self._file.flush()
        except OSError:
            pass

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
