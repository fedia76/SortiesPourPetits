"""Mémoire des pages déjà analysées.

Un run retombe forcément sur les pages des runs précédents : sans cette
mémoire, on paierait la relecture de chaque page à chaque passage et la file
de modération se remplirait de doublons.

Elle est consultée à trois endroits, et chacun répond à une question
différente :

* **étage 2**, sur ce que la recherche web remonte — `seen_as_event`, la plus
  étroite des trois : seule une page déjà jugée *en tant que sortie* est
  écartée, et c'est ce qui évite de condamner un agenda que le dépouillement
  avait raté (voir `DECISIONS_SORTIE`) ;
* **entre les étages 3 et 4**, sur les liens d'un agenda — `seen` : ils
  étaient de toute façon écartés à la lecture, mais après être passés par le
  tri, qui se paie et qui ne rend qu'un nombre borné de liens. Les connus y
  prenaient la place des neufs ;
* **étage 5 puis 8**, à la lecture et à la publication — `seen` encore, le
  dernier filet, et le seul qui sache raisonner sur une sortie de programme.

Le filtre reste donc appliqué AVANT l'extraction, et depuis cette version
avant le tri, donc avant de dépenser le moindre jeton sur la page.

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

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .text import alphanum

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

#: Les décisions qui prouvent que la page a été jugée **en tant que sortie**.
#:
#: La mémoire répond à une question précise — « a-t-on déjà jugé cette page en
#: tant que sortie ? » — et pas à celle qu'on serait tenté de lui poser : « cette
#: page vaut-elle d'être ouverte ? ». Les confondre a une conséquence exacte.
#:
#: Un agenda dont le dépouillement a échoué — aucun lien extrait, ou tri vide —
#: est relu *pour lui-même* (`Orchestrator._itself`), passe à l'extraction, et
#: finit mémorisé en `irrelevant`. C'est un agenda, rangé sous le verdict d'une
#: sortie. L'écarter à la reconnaissance sur ce seul motif le tuerait pour
#: toujours, sans qu'une ligne de journal ne le dise : il ne manquerait pas une
#: sortie, il manquerait un agenda entier.
#:
#: D'où cette liste, et d'où l'absence remarquable d'`irrelevant`. Les quatre
#: qui y figurent supposent toutes qu'une fiche a été **extraite** de la page :
#: elle a donc bien été lue comme une sortie, et le redire coûterait sans rien
#: apprendre.
DECISIONS_SORTIE = frozenset({"submitted", "out_of_area", "out_of_period", "invalid"})


def event_key(page_url: str, title: str) -> str:
    """Clé d'une sortie relevée sur une page qui en porte plusieurs.

    Mémoriser la page entière reviendrait à ne jamais relire le programme d'un
    festival, donc à manquer tout ce qu'il y ajoutera. Mémoriser chaque sortie
    laisse au contraire la page se faire relire : seules les sorties déjà
    proposées sont sautées, et les nouvelles passent.
    """
    slug = alphanum(title, "-")
    key = f"{normalize_url(page_url)}#{slug or 'sans-titre'}"
    return key[:_KEY_MAX]


class Memory(Protocol):
    """Ce que le pipeline attend d'une mémoire, local ou distant."""

    def preload(self, urls: Iterable[str]) -> None:
        """Prépare la réponse à `seen()` pour ces URLs, en un seul aller-retour."""

    def seen(self, url: str, key: str | None = None) -> bool:
        """Cette page a-t-elle déjà été analysée lors d'un run précédent ?

        `key` prend la place de l'URL normalisée quand la page n'est pas
        l'unité pertinente — une sortie parmi les vingt d'un programme.
        """

    def seen_as_event(self, url: str) -> bool:
        """A-t-elle déjà été jugée **en tant que sortie** ?

        Plus étroit que `seen`, et c'est tout l'intérêt : ce qui a été lu par
        défaut, faute d'en avoir tiré des liens, ne compte pas. Voir
        `DECISIONS_SORTIE`.
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


def _jugee_comme_sortie(decision: str | None, event_id: int | None) -> bool:
    """La règle, écrite une fois pour les deux mémoires.

    `event_id` seul suffit : une page devenue une sortie du site a été jugée,
    quelle que soit l'étiquette sous laquelle la décision a été rangée depuis.
    """
    return event_id is not None or (decision or "") in DECISIONS_SORTIE


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

    def __enter__(self) -> SeenStore:
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

    def seen_as_event(self, url: str) -> bool:
        row = self._db.execute(
            "SELECT decision, event_id FROM seen_url WHERE url = ?", (normalize_url(url),)
        ).fetchone()
        return row is not None and _jugee_comme_sortie(row[0], row[1])

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
        #: Clés que le site connaît déjà, et **ce qu'il en sait** : la décision
        #: et la sortie au bout, quand il y en a une. La décision était jetée à
        #: la réception, ce qui interdisait de distinguer une page lue comme
        #: sortie d'une page lue faute de mieux — donc de filtrer tôt sans
        #: risquer d'écarter un agenda pour toujours.
        self._known: dict[str, tuple[str, int | None]] = {}
        #: Clés déjà soumises au site : inutile de les redemander.
        self._asked: set[str] = set()
        self._pending: list[_Item] = []

    def __enter__(self) -> RemoteStore:
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

    def seen_as_event(self, url: str) -> bool:
        key = normalize_url(url)
        self._ask([key])
        connue = self._known.get(key)
        return connue is not None and _jugee_comme_sortie(*connue)

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
            # compte comme vue dès maintenant — et sous la décision qu'on vient
            # de prendre, pour que le filtre du run en cours la lise comme le
            # prochain run la lira.
            self._known[key] = (decision, event_id)
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
