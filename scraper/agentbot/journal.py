"""Le journal du pipeline, avec deux choses de plus.

`RunLog` est repris tel quel : même fichier JSONL, même format, donc les mêmes
outils pour le relire. Il lui manque deux choses pour un agent, et on les
ajoute par héritage plutôt qu'en touchant `sortiesbot` :

* **une mémoire courte de ce qui vient d'être journalisé.** Les briques disent
  pourquoi elles écartent une page — au journal, pas à l'appelant. Le pipeline
  n'a pas besoin de le savoir : il passe à la suite. Le pilote, lui, doit
  l'apprendre, sinon il rouvrira la même page en croyant à une panne ;
* **un rendu console pour les tours de l'agent**, qui sont les lignes qu'on a
  envie de lire en premier : ce qu'il a pensé, ce qu'il a demandé.
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Any

from sortiesbot.journal import INFO, RunLog

#: Événements gardés en mémoire courte. Une brique en émet une dizaine au plus
#: par appel : de quoi retrouver son motif sans tout garder.
RECENT = 200

_CONSOLE = {
    "agent_turn": lambda f: (
        f"◆ Tour {f.get('turn')} — "
        + (f"« {_court(f.get('thought'), 200)} » " if f.get("thought") else "")
        + (f"→ {', '.join(f.get('calls') or [])}" if f.get("calls") else "→ aucun outil")
    ),
    "agent_tool": lambda f: (
        f"  ⚙ {f.get('tool')}({_court(f.get('args'), 120)}) : {_court(f.get('digest'), 160)}"
    ),
    "agent_end": lambda f: (
        f"◆ Fin de l'agent — {f.get('reason')} après {f.get('turns')} tour(s), "
        f"{f.get('spent_usd')} $"
    ),
}


def _court(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class AgentLog(RunLog):
    """Un `RunLog` qui se souvient de ses derniers événements."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.recent: deque[tuple[int, str, dict[str, Any]]] = deque(maxlen=RECENT)
        self._count = 0

    @property
    def mark(self) -> int:
        """Un repère, à passer à `since()` pour relire ce qui a suivi."""
        return self._count

    def since(self, mark: int) -> list[tuple[str, dict[str, Any]]]:
        return [(kind, fields) for n, kind, fields in self.recent if n > mark]

    def why(self, mark: int) -> str:
        """Le dernier motif d'écart ou d'erreur journalisé depuis `mark`."""
        for kind, fields in reversed(self.since(mark)):
            if kind == "skip" and fields.get("reason"):
                return str(fields["reason"])
            if kind == "error" and fields.get("message"):
                return str(fields["message"])
        return ""

    def event(self, kind: str, level: str = INFO, **fields: Any) -> None:
        self._count += 1
        self.recent.append((self._count, kind, fields))
        render = _CONSOLE.get(kind)
        if render is None:
            super().event(kind, level, **fields)
            return
        # Le fichier et le puits comme d'habitude ; la console, à notre façon.
        verbose, self.verbose = self.verbose, False
        try:
            super().event(kind, level, **fields)
        finally:
            self.verbose = verbose
        if verbose:
            elapsed = int(time.monotonic() - self.started_at)
            print(
                f"[{elapsed // 60:d}:{elapsed % 60:02d}] {render(fields)}",
                file=self.stream,
                flush=True,
            )
