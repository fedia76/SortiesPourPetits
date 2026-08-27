"""Mémoire des URLs déjà vues.

Un run retombe forcément sur les pages des runs précédents : sans cette
mémoire, on paierait la relecture de chaque page à chaque passage et la file
de modération se remplirait de doublons. Le filtre est appliqué AVANT
l'extraction, donc avant de dépenser le moindre jeton sur la page.

En v1 c'est un SQLite local au scraper ; ce sera une table du site quand les
runs seront déclenchés depuis la console d'administration — d'où l'interface
réduite à `seen()` / `remember()`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_url (
  url        TEXT PRIMARY KEY,
  title      TEXT,
  decision   TEXT NOT NULL,
  event_id   INTEGER,
  first_seen TEXT NOT NULL,
  last_seen  TEXT NOT NULL
);
"""

#: Paramètres de suivi ajoutés par les campagnes : ils ne changent pas la page.
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "_ga")


def normalize_url(url: str) -> str:
    """Ramène deux liens vers la même page à une seule clé."""
    parts = urlsplit(url.strip())
    # Le schéma est ramené à https : http://exemple.fr/a et https://exemple.fr/a
    # sont la même page, et cette valeur ne sert que de clé.
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(query), ""))


class SeenStore:
    """Table des URLs déjà traitées, quelle qu'ait été l'issue."""

    def __init__(self, path: Path | str = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "SeenStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def seen(self, url: str) -> bool:
        key = normalize_url(url)
        row = self._db.execute("SELECT 1 FROM seen_url WHERE url = ?", (key,)).fetchone()
        return row is not None

    def remember(
        self,
        url: str,
        decision: str,
        title: str = "",
        event_id: int | None = None,
    ) -> None:
        """Enregistre l'issue d'une URL (`submitted`, `irrelevant`, `invalid`,
        `error`, `dry_run`…). Une URL revue voit sa date de dernière vue
        rafraîchie, mais garde sa première décision utile."""
        key = normalize_url(url)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._db.execute(
            """
            INSERT INTO seen_url (url, title, decision, event_id, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
              last_seen = excluded.last_seen,
              title     = COALESCE(NULLIF(excluded.title, ''), seen_url.title),
              decision  = excluded.decision,
              event_id  = COALESCE(excluded.event_id, seen_url.event_id)
            """,
            (key, title, decision, event_id, now, now),
        )
        self._db.commit()

    def count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM seen_url").fetchone()[0])
