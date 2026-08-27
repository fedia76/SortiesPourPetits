"""Mémoire des URLs et journal de run."""

import json
from pathlib import Path

from sortiesbot.journal import RunLog, run_log_path
from sortiesbot.store import SeenStore, normalize_url


def test_normalisation_des_urls():
    memes = [
        "https://exemple.fr/sortie",
        "https://www.exemple.fr/sortie/",
        "http://Exemple.fr/sortie#programme",
        "https://exemple.fr/sortie?utm_source=newsletter&utm_medium=mail",
    ]
    assert len({normalize_url(u) for u in memes}) == 1
    # Un paramètre porteur de sens, lui, distingue bien deux pages.
    assert normalize_url("https://exemple.fr/a?id=1") != normalize_url("https://exemple.fr/a?id=2")


def test_memoire_persiste_sur_disque(tmp_path: Path):
    db = tmp_path / "state" / "seen.sqlite3"
    with SeenStore(db) as store:
        store.remember("https://exemple.fr/a", "submitted", title="A", event_id=12)
    with SeenStore(db) as store:
        assert store.seen("https://www.exemple.fr/a/")
        assert store.count() == 1


def test_revoir_une_url_conserve_lidentifiant(tmp_path: Path):
    with SeenStore(tmp_path / "s.sqlite3") as store:
        store.remember("https://exemple.fr/a", "submitted", title="A", event_id=12)
        store.remember("https://exemple.fr/a", "irrelevant")
        row = store._db.execute("SELECT title, event_id FROM seen_url").fetchone()
    assert row == ("A", 12)


def test_journal_jsonl(tmp_path: Path):
    path = tmp_path / "runs" / "run.jsonl"
    with RunLog(path, verbose=False) as log:
        log.event("query", query="spectacle enfant Paris")
        log.error("extraction", "page illisible", url="https://exemple.fr/a")

    lignes = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    assert [l["kind"] for l in lignes] == ["query", "error"]
    assert lignes[0]["query"] == "spectacle enfant Paris"
    assert lignes[1]["stage"] == "extraction"
    assert "at" in lignes[0]


def test_nom_du_journal(tmp_path: Path):
    path = run_log_path(tmp_path, "Spectacles Week-end")
    assert path.suffix == ".jsonl"
    assert path.name.endswith("_spectacles-week-end.jsonl")
