"""Journal d'un run : une ligne JSONL par événement, et une ligne lisible en console.

Trois destinations pour le même événement, et c'est voulu :

* le **fichier JSONL** de `runs/`, trace complète pour une analyse après coup ;
* la **console**, pour suivre un run lancé à la main ;
* un **puits** (`sink`) facultatif — c'est par lui que le worker renvoie le
  journal au site, qui l'affiche dans sa page de débogage. Sans ce puits, tout
  ce que le run raconte mourait sur la sortie standard du service systemd.

Chaque événement porte l'**étage** qui l'a produit (`stages.Stage`). Il n'est
pas passé en paramètre à chaque appel : `RunLog.stage()` est un gestionnaire
de contexte, et le pipeline ouvre un étage à la fois. C'est ce qui permet à la
console de reconstituer le graphe en six briques sans que le code ait à se
répéter.

Un mot sur le champ `op` : il nomme l'opération technique en cause dans une
erreur ou une consommation de jetons (« search », « select », « extraction »).
Il ne faut pas le confondre avec `stage`, qui est l'étage du pipeline — les
deux coïncident souvent, mais `op` existe aussi hors étage (« categories »).
"""

from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, TextIO

from .stages import ACTOR, IN_OUT, LABEL, NUMBER, Stage

#: Niveaux de gravité. La console de débogage s'en sert pour filtrer.
INFO = "info"
WARN = "warn"
ERROR = "error"

#: Rendu console d'un événement du journal, par type.
_CONSOLE = {
    "run_start": lambda f: f"▶ Run « {f.get('config', {}).get('name', '?')} » — {f.get('mode')}",
    "stage_start": lambda f: (
        f"┌ Étage {f.get('number')} · {f.get('label')} [{f.get('actor')}] — "
        f"reçoit : {f.get('takes')}"
    ),
    "stage_end": lambda f: (
        f"└ Étage {f.get('number')} · {f.get('label')} — {f.get('produced')} en "
        f"{f.get('seconds')} s"
    ),
    "query": lambda f: f"  🔎 recherche : {f.get('query')}",
    "fetching": lambda f: f"  ↓ ouverture : {f.get('url')}",
    "direct": lambda f: f"  ★ sortie trouvée directement : {f.get('title')} — {f.get('url')}",
    "fallback": lambda f: (
        f"  ↺ aucun lien retenu, la page est lue comme un programme : {f.get('url')}"
        if f.get("multiple")
        else f"  ↺ aucun lien retenu, la page est relue comme une sortie : {f.get('url')}"
    ),
    "seed": lambda f: f"  ⌖ point de départ : {f.get('url')}",
    "agenda_planned": lambda f: f"  ▦ agenda à dépouiller : {f.get('title')} — {f.get('url')}",
    "programme": lambda f: (
        f"  ▤ programme dépouillé : {f.get('found')} sortie(s) relevée(s) "
        f"sur {f.get('chars')} caractères"
    ),
    "harvested": lambda f: f"  🔗 {f.get('links')} lien(s) extrait(s) : {f.get('url')}",
    "link": lambda f: f"     · [{f.get('index')}] {f.get('text')} → {f.get('url')}",
    "link_kept": lambda f: (
        f"     ✔ retenu : {f.get('text')}"
        + (f" — {f.get('why')}" if f.get("why") else "")
        + f" → {f.get('url')}"
    ),
    "selected": lambda f: (
        f"  ✔ {f.get('kept')} retenu(s) sur {f.get('among')} : {f.get('url')}"
        + (f"\n     ↳ écartés : {f.get('dropped_reason')}" if f.get("dropped_reason") else "")
    ),
    "visited": lambda f: f"  📄 page lue : {f.get('url')}",
    "page": lambda f: (
        f"  📄 page lue : {f.get('chars')} caractères, {f.get('json_ld')} date(s) JSON-LD, "
        f"image {'oui' if f.get('image') else 'non'} — {f.get('url')}"
    ),
    "nothing_found": lambda f: (
        "  ∅ aucun candidat retenu — "
        f"{f.get('searches')} recherche(s), {f.get('pages')} agenda(s) dépouillé(s)"
    ),
    "search_result": lambda f: f"     · {f.get('url')}",
    "candidate": lambda f: f"  ★ candidat : {f.get('title')} — {f.get('url')}",
    "skip": lambda f: f"  ⊘ ignoré ({f.get('reason')}) : {f.get('url')}",
    "extract": lambda f: f"  ✎ extrait : {f.get('title')} — {f.get('venue')}",
    "geocode": lambda f: (
        f"  📍 {f.get('address')} → {f.get('lat')}, {f.get('lng')}"
        if f.get("located")
        else f"  📍 non géolocalisé ({f.get('reason')}) : {f.get('address')}"
    ),
    "out_of_scope": lambda f: (
        f"  ± hors {f.get('field')} ({f.get('detail')}) mais gardée : {f.get('url')}"
    ),
    "schedule": lambda f: (
        f"  🗓 {f.get('count')} date(s) [{f.get('source')}]"
        + (f" — {', '.join(f.get('weekdays') or [])}" if f.get("weekdays") else "")
        + f" : {f.get('title')}"
        if f.get("source") != "plage"
        else f"  🗓 plage entière, jours de représentation inconnus : {f.get('title')}"
    ),
    "incomplete": lambda f: f"  ⚑ {f.get('field')} à compléter par la modération : {f.get('title')}",
    "paused": lambda f: (
        f"  ⏸ tour en pause (limite serveur), reprise — {f.get('cost_usd')} $ déjà engagés"
    ),
    "budget": lambda f: (
        f"  ⛔ budget atteint ({f.get('spent')} $ / {f.get('limit')} $) : extractions arrêtées, "
        f"les {f.get('candidates')} page(s) trouvée(s) sont conservées dans le JSON"
    ),
    "thinking": lambda f: f"     … {f.get('text')}",
    "photo": lambda f: f"  🖼 photo {f.get('status')} : {f.get('url')}",
    "submit": lambda f: f"  ✅ soumise (#{f.get('event_id')}) : {f.get('title')}",
    "dry_run": lambda f: f"  ○ retenue (dry-run) : {f.get('title')}",
    "usage": lambda f: (
        f"  ⚙ {f.get('op')} [{f.get('model')}] "
        f"{f.get('input_tokens')} entrée / {f.get('output_tokens')} sortie jetons"
        f" · {f.get('web_searches')} recherche(s) · {f.get('total_usd')} $"
    ),
    "prompt": lambda f: f"  ✉ prompt {f.get('op')} : {f.get('chars')} caractères",
    "error": lambda f: (
        f"  ✗ erreur ({f.get('op')}) : {f.get('message')}"
        + (f" — {f.get('url')}" if f.get("url") else "")
    ),
    "run_end": lambda f: f"■ Fin du run — {json.dumps(f.get('summary', {}), ensure_ascii=False)}",
}

#: Champs dont la valeur peut être longue : on les tronque avant d'envoyer le
#: journal au site, qui n'a pas besoin de la page entière pour la déboguer.
_LONG_FIELDS = (
    "text", "content", "prompt", "reason", "message", "detail", "context",
    "why", "dropped_reason",
)
_LONG_MAX = 2000


def _trim(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key in _LONG_FIELDS and isinstance(value, str) and len(value) > _LONG_MAX:
            out[key] = value[:_LONG_MAX] + f"… (+{len(value) - _LONG_MAX} caractères)"
        else:
            out[key] = value
    return out


class RunLog:
    """Écrit le journal d'un run. Utilisable en gestionnaire de contexte."""

    def __init__(
        self,
        path: Path | None,
        verbose: bool = True,
        stream: TextIO | None = None,
        sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.path = path
        self.verbose = verbose
        self.stream = stream if stream is not None else sys.stdout
        #: Appelé pour chaque événement, en plus du fichier et de la console.
        self.sink = sink
        # Un run dure plusieurs minutes : le temps écoulé en tête de chaque
        # ligne dit d'un coup d'œil que ça avance encore.
        self.started_at = time.monotonic()
        #: Numéro d'ordre : c'est lui qui permet à la console de paginer sans
        #: rien perdre ni rien répéter, là où l'horodatage a des ex æquo.
        self._seq = 0
        self._stage: Stage | None = None
        #: Filiation courante — voir `trail()`.
        self._trail: dict[str, Any] = {}
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

    # ------------------------------------------------------------- étages

    @property
    def current_stage(self) -> Stage | None:
        return self._stage

    @contextmanager
    def stage(self, stage: Stage, **fields: Any) -> Iterator["_StageScope"]:
        """Ouvre un étage : tout ce qui est journalisé dedans lui est rattaché.

        Rend un objet sur lequel l'appelant pose ce que l'étage a produit
        (`scope.produced(...)`), pour que la console puisse afficher, sur
        chaque brique du graphe, ce qui entre et ce qui sort.

        Les étages ne s'imbriquent pas dans le pipeline, mais la sauvegarde et
        la restauration de l'étage précédent rendent l'appel sûr de toute façon.
        """
        previous = self._stage
        self._stage = stage
        scope = _StageScope()
        started = time.monotonic()
        self.event(
            "stage_start",
            number=NUMBER[stage],
            label=LABEL[stage],
            actor=ACTOR[stage],
            takes=IN_OUT[stage][0],
            gives=IN_OUT[stage][1],
            **fields,
        )
        try:
            yield scope
        finally:
            self.event(
                "stage_end",
                number=NUMBER[stage],
                label=LABEL[stage],
                seconds=round(time.monotonic() - started, 1),
                produced=scope.summary or "—",
                **scope.counts,
            )
            self._stage = previous

    @contextmanager
    def trail(self, **keys: Any) -> Iterator[None]:
        """Marque tout ce qui est journalisé dedans comme descendant de `keys`.

        Un journal plat répond à « qu'est-ce qui s'est passé ? » mais pas à
        « d'où vient cette sortie ? ». Les deux questions n'ont rien à voir :
        la seconde demande la **filiation** — quelle requête a remonté cet
        agenda, quel agenda a donné ce lien, quel lien a donné cette fiche.

        Plutôt que de répéter `agenda=…` sur quarante appels, on ouvre une
        piste : l'orchestrateur déclare l'agenda qu'il dépouille avant les
        étages 2 et 3, puis la page et l'agenda dont elle vient avant les
        étages 4 à 6, et tout ce qui est journalisé à l'intérieur en hérite. C'est ce qui permet à la console
        de reconstruire l'arbre du run.

        Les pistes s'imbriquent, et une clé vide n'écrase pas celle du dessus.
        """
        previous = self._trail
        self._trail = {**previous, **{k: v for k, v in keys.items() if v}}
        try:
            yield
        finally:
            self._trail = previous

    # ---------------------------------------------------------- événements

    def event(self, kind: str, level: str = INFO, **fields: Any) -> None:
        self._seq += 1
        record = {
            "seq": self._seq,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "stage": self._stage.value if self._stage else None,
            "kind": kind,
            "level": level,
            # La filiation d'abord : un champ explicite de l'appelant la
            # remplace, jamais l'inverse.
            **self._trail,
            **_trim(fields),
        }
        if self._file is not None:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()
        if self.sink is not None:
            try:
                self.sink(record)
            except Exception:  # noqa: BLE001 — un journal ne doit jamais casser un run
                self.sink = None
                print(
                    "Journal distant abandonné : le run continue sans lui.",
                    file=sys.stderr,
                    flush=True,
                )
        if self.verbose:
            render = _CONSOLE.get(kind)
            line = render(fields) if render else f"  {kind}: {json.dumps(fields, ensure_ascii=False)}"
            elapsed = int(time.monotonic() - self.started_at)
            print(f"[{elapsed // 60:d}:{elapsed % 60:02d}] {line}", file=self.stream, flush=True)

    def warn(self, op: str, message: str, **fields: Any) -> None:
        self.event("error", level=WARN, op=op, message=message, **fields)

    def error(self, op: str, message: str, **fields: Any) -> None:
        """Une erreur. `op` nomme l'opération, pas l'étage — voir l'en-tête."""
        self.event("error", level=ERROR, op=op, message=message, **fields)


class _StageScope:
    """Ce qu'un étage a produit, renseigné par l'appelant avant sa fermeture."""

    def __init__(self) -> None:
        self.summary = ""
        self.counts: dict[str, Any] = {}

    def produced(self, summary: str, **counts: Any) -> None:
        self.summary = summary
        self.counts.update(counts)


def run_log_path(directory: Path, config_name: str) -> Path:
    """`runs/2026-08-27T14-30-05_spectacles-weekend.jsonl`"""
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in config_name.lower())
    return directory / f"{stamp}_{slug}.jsonl"


#: Les colonnes que le site range à plat dans `ScraperRunLog`. Tout le reste
#: d'un événement part dans `data`, en JSON.
_ENVELOPE = ("seq", "at", "stage", "kind", "level", "url", "message")

#: Plafonds des colonnes correspondantes côté site. Les dépasser ferait
#: refuser le paquet entier — donc perdre quarante événements pour une seule
#: URL trop longue.
_URL_MAX = 500
_MESSAGE_MAX = 4000


def _wire(record: dict[str, Any]) -> dict[str, Any]:
    """Met un événement à la forme attendue par `POST /runs/:id/logs`.

    Le journal manipule des enregistrements **plats** — c'est ce qui rend
    `log.event("skip", reason=..., url=...)` agréable à écrire. Le site, lui,
    a des colonnes : il range l'enveloppe à plat et le reste dans une colonne
    JSON. Sans cette conversion, tout ce qui n'est pas une colonne connue est
    silencieusement jeté à la validation, et la page de débogage n'affiche que
    des lignes vides.
    """
    entry: dict[str, Any] = {"seq": record.get("seq", 0), "kind": record.get("kind", "?")}
    if record.get("at"):
        entry["at"] = record["at"]
    if record.get("stage"):
        entry["stage"] = record["stage"]
    entry["level"] = record.get("level") or INFO
    url = record.get("url")
    if isinstance(url, str) and url:
        entry["url"] = url[:_URL_MAX]
    message = record.get("message")
    if isinstance(message, str) and message:
        entry["message"] = message[:_MESSAGE_MAX]

    data = {k: v for k, v in record.items() if k not in _ENVELOPE}
    if data:
        entry["data"] = data
    return entry


class RemoteJournal:
    """Renvoie le journal du run au site, par paquets.

    C'est ce qui manquait : le worker tourne en service systemd, et tout ce
    que `RunLog` racontait finissait dans le journal du système, invisible
    depuis la console. Les événements passent maintenant aussi par ici, et la
    page de débogage du site les affiche.

    Un journal ne doit jamais faire échouer un run : une erreur d'envoi coûte
    le paquet en cours, pas l'exécution. Après quelques échecs d'affilée on
    renonce — le site est probablement en cours de redéploiement, et
    s'acharner ralentirait le run pour rien.
    """

    #: Un paquet par tranche d'événements. Assez petit pour que la console se
    #: remplisse au fil de l'eau, assez gros pour ne pas marteler l'API.
    BATCH = 40
    #: Échecs consécutifs après lesquels on cesse d'essayer.
    MAX_FAILURES = 3

    def __init__(self, api: Any, run_id: int, batch: int | None = None):
        self.api = api
        self.run_id = run_id
        self.batch = batch or self.BATCH
        self._pending: list[dict[str, Any]] = []
        self._failures = 0
        self.given_up = False

    def add(self, record: dict[str, Any]) -> None:
        if self.given_up:
            return
        self._pending.append(_wire(record))
        if len(self._pending) >= self.batch:
            self.flush()

    def flush(self) -> None:
        if self.given_up or not self._pending:
            return
        batch, self._pending = self._pending, []
        try:
            self.api.report_logs(self.run_id, batch)
            self._failures = 0
        except Exception as err:  # noqa: BLE001 — un journal ne casse pas un run
            self._failures += 1
            if self._failures >= self.MAX_FAILURES:
                self.given_up = True
                print(
                    f"Journal distant abandonné après {self._failures} échecs ({err}) : "
                    "le run continue, le fichier JSONL garde tout.",
                    file=sys.stderr,
                    flush=True,
                )
