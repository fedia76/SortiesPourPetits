"""Mémoire des pages déjà analysées.

Un run retombe forcément sur les pages des runs précédents : sans cette
mémoire, on paierait la relecture de chaque page à chaque passage et la file
de modération se remplirait de doublons. Le filtre est appliqué AVANT
l'extraction, donc avant de dépenser le moindre jeton sur la page.

Deux implémentations, une seule interface (`Memory`) :

* `SeenStore` — un SQLite local, pour les runs lancés à la main en ligne de
  commande ;
* `RemoteStore` — la table `ScrapedUrl` du site, commune à toutes les
  configurations et à tous les runs, pour le worker piloté par la console.
  C'est elle qui fait foi en production : une page lue par la recherche
  « spectacles » ne sera pas relue par la recherche « musées ».

La clé de mémorisation est normalement l'URL normalisée de la page. Une page
de programme fait exception : elle porte plusieurs sorties, et sa relecture au
prochain run est justement ce qu'on veut (le programme s'étoffe). C'est alors
`event_key()` qui donne la clé — une par sortie, pas une par page — et le
`url` transmis reste celui de la page, cliquable dans la console.

Les deux distinguent la mémoire (ce qu'on ne relira plus) du journal (ce que
le run a fait). Une décision provisoire — page déjà connue, doublon, essai,
erreur réseau — est journalisée mais pas mémorisée : elle ne doit pas
empêcher un run ultérieur de traiter la page.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol
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


#: Longueur maximale d'une clé : la colonne du site est un VARCHAR(500).
_KEY_MAX = 500


def event_key(page_url: str, title: str) -> str:
    """Clé d'une sortie relevée sur une page qui en porte plusieurs.

    Mémoriser la page entière reviendrait à ne jamais relire le programme d'un
    festival, donc à manquer tout ce qu'il y ajoutera. Mémoriser chaque sortie
    laisse au contraire la page se faire relire : seules les sorties déjà
    proposées sont sautées, et les nouvelles passent.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", _fold(title)).strip("-")
    key = f"{normalize_url(page_url)}#{slug or 'sans-titre'}"
    return key[:_KEY_MAX]


def _fold(text: str) -> str:
    """Minuscules sans accents : deux graphies d'un titre donnent une clé."""
    stripped = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in stripped if not unicodedata.combining(c))


class Memory(Protocol):
    """Ce que le pipeline attend d'une mémoire, local ou distant."""

    def preload(self, urls: Iterable[str]) -> None:
        """Prépare la réponse à `seen()` pour ces URLs, en un seul aller-retour."""

    def seen(self, url: str, key: str | None = None) -> bool:
        """Cette page a-t-elle déjà été analysée lors d'un run précédent ?

        `key` prend la place de l'URL normalisée quand la page n'est pas
        l'unité pertinente — une sortie parmi les vingt d'un programme.
        """

    def report(
        self,
        url: str,
        decision: str,
        *,
        key: str | None = None,
        title: str = "",
        reason: str = "",
        event_id: int | None = None,
        remember: bool = True,
    ) -> None:
        """Journalise l'issue d'une page, et la mémorise si `remember`."""

    def flush(self) -> None:
        """Écrit ce qui reste en attente."""


class SeenStore:
    """Mémoire locale : un SQLite dans `scraper/state/`."""

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

    def preload(self, urls: Iterable[str]) -> None:
        """Sans objet : la base est locale, chaque `seen()` est immédiat."""

    def flush(self) -> None:
        """Sans objet : chaque écriture est déjà validée."""

    def seen(self, url: str, key: str | None = None) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM seen_url WHERE url = ?", (key or normalize_url(url),)
        ).fetchone()
        return row is not None

    def report(
        self,
        url: str,
        decision: str,
        *,
        key: str | None = None,
        title: str = "",
        reason: str = "",
        event_id: int | None = None,
        remember: bool = True,
    ) -> None:
        # Le journal détaillé est le fichier JSONL du run ; ici on ne garde que
        # ce qui sert à ne pas relire la page.
        if remember:
            self.remember(url, decision, title=title, event_id=event_id, key=key)

    def remember(
        self,
        url: str,
        decision: str,
        title: str = "",
        event_id: int | None = None,
        key: str | None = None,
    ) -> None:
        """Enregistre l'issue d'une URL (`submitted`, `irrelevant`, `invalid`,
        `out_of_area`…). Une URL revue voit sa date de dernière vue
        rafraîchie, mais garde sa première décision utile."""
        key = key or normalize_url(url)
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


#: Lignes accumulées avant un envoi au site. Assez pour ne pas bavarder,
#: assez peu pour que la console suive le run en direct.
_BATCH = 10


@dataclass
class _Item:
    url: str
    key: str
    decision: str
    title: str
    reason: str
    event_id: int | None
    remember: bool

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "url": self.url,
            "key": self.key,
            "decision": self.decision,
            "remember": self.remember,
        }
        if self.title:
            payload["title"] = self.title[:190]
        if self.reason:
            payload["reason"] = self.reason[:1000]
        if self.event_id is not None:
            payload["eventId"] = self.event_id
        return payload


class RemoteStore:
    """Mémoire partagée : la table `ScrapedUrl` du site, via l'API.

    Le journal du run part par la même route (`/runs/:id/items`) : la console
    affiche donc les pages au fil de l'eau, avec ce qu'on en a fait.
    """

    def __init__(self, api: Any, run_id: int, batch: int = _BATCH):
        self.api = api
        self.run_id = run_id
        self.batch = batch
        #: Clés que le site connaît déjà, parmi celles qu'on lui a soumises.
        self._known: set[str] = set()
        #: Clés déjà soumises au site : inutile de les redemander.
        self._asked: set[str] = set()
        self._pending: list[_Item] = []

    def __enter__(self) -> "RemoteStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.flush()

    def preload(self, urls: Iterable[str]) -> None:
        self._ask(sorted({normalize_url(u) for u in urls}))

    def _ask(self, keys: list[str]) -> None:
        todo = [k for k in keys if k not in self._asked]
        if not todo:
            return
        self._asked.update(todo)
        self._known.update(self.api.known_urls(todo))

    def seen(self, url: str, key: str | None = None) -> bool:
        key = key or normalize_url(url)
        # Un candidat apparu après le préchargement vaut une question ciblée :
        # ça reste moins cher qu'une page relue. Les sorties d'un programme y
        # passent forcément : leur clé n'existe qu'une fois la page lue.
        self._ask([key])
        return key in self._known

    def report(
        self,
        url: str,
        decision: str,
        *,
        key: str | None = None,
        title: str = "",
        reason: str = "",
        event_id: int | None = None,
        remember: bool = True,
    ) -> None:
        key = key or normalize_url(url)
        if remember:
            # Mémorisée côté site à la prochaine vidange ; côté worker, elle
            # compte comme vue dès maintenant.
            self._known.add(key)
            self._asked.add(key)
        self._pending.append(
            _Item(
                url=url,
                key=key,
                decision=decision,
                title=title,
                reason=reason,
                event_id=event_id,
                remember=remember,
            )
        )
        if len(self._pending) >= self.batch:
            self.flush()

    def remember(
        self,
        url: str,
        decision: str,
        title: str = "",
        event_id: int | None = None,
        key: str | None = None,
    ) -> None:
        self.report(url, decision, title=title, event_id=event_id, key=key, remember=True)

    def flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        self.api.report_items(self.run_id, [item.as_json() for item in batch])
