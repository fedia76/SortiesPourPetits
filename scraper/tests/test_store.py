"""Mémoire des URLs et journal de run."""

import json
from pathlib import Path

from sortiesbot.journal import RemoteJournal, RunLog, run_log_path
from sortiesbot.stages import Stage
from sortiesbot.store import RemoteStore, SeenStore, normalize_url


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

    lignes = [json.loads(ligne) for ligne in path.read_text(encoding="utf-8").splitlines()]
    assert [ligne["kind"] for ligne in lignes] == ["query", "error"]
    assert lignes[0]["query"] == "spectacle enfant Paris"
    # `op` nomme l'opération technique ; `stage` est réservé à l'étage du
    # pipeline, et vaut None hors de tout `log.stage(...)`.
    assert lignes[1]["op"] == "extraction"
    assert lignes[1]["level"] == "error"
    assert lignes[0]["stage"] is None
    assert [ligne["seq"] for ligne in lignes] == [1, 2]
    assert "at" in lignes[0]


def test_nom_du_journal(tmp_path: Path):
    path = run_log_path(tmp_path, "Spectacles Week-end")
    assert path.suffix == ".jsonl"
    assert path.name.endswith("_spectacles-week-end.jsonl")


def test_le_journal_marque_l_etage_courant(tmp_path: Path):
    """Un événement journalisé dans un étage lui est rattaché, sans le dire.

    C'est ce qui permet à la console de reconstituer le graphe : le code
    n'écrit jamais `stage=` à la main, il ouvre un étage et journalise dedans.
    """
    path = tmp_path / "runs" / "run.jsonl"
    with RunLog(path, verbose=False) as log:
        with log.stage(Stage.SELECT, url="https://exemple.fr/agenda") as st:
            log.event("link", index=1, url="https://exemple.fr/a")
            st.produced("1 lien retenu sur 12", kept=1, among=12)
        log.event("run_end")

    lignes = [json.loads(ligne) for ligne in path.read_text(encoding="utf-8").splitlines()]
    assert [ligne["kind"] for ligne in lignes] == ["stage_start", "link", "stage_end", "run_end"]
    assert [ligne["stage"] for ligne in lignes] == ["select", "select", "select", None]
    fin = lignes[2]
    assert fin["produced"] == "1 lien retenu sur 12"
    assert fin["kept"] == 1 and fin["among"] == 12


def test_le_journal_distant_renonce_apres_trois_echecs():
    """Un site injoignable ne doit jamais faire échouer un run."""

    class ApiCassee:
        appels = 0

        def report_logs(self, run_id, entries):
            ApiCassee.appels += 1
            raise RuntimeError("site injoignable")

    journal = RemoteJournal(ApiCassee(), run_id=1, batch=1)
    for i in range(10):
        journal.add({"seq": i, "kind": "skip"})

    assert journal.given_up is True
    assert ApiCassee.appels == RemoteJournal.MAX_FAILURES


def test_le_journal_distant_imbrique_les_champs_sous_data():
    """Le site range l'enveloppe à plat et le reste dans une colonne JSON.

    Sans cette mise en forme, la validation côté serveur jette silencieusement
    tout ce qui n'est pas une colonne connue : les lignes arrivent, mais vides.
    C'est exactement le bug qu'a montré la première mise en production.
    """
    envoyes: list[list[dict]] = []

    class ApiCapture:
        def report_logs(self, run_id, entries):
            envoyes.append(entries)

    journal = RemoteJournal(ApiCapture(), run_id=1, batch=1)
    journal.add(
        {
            "seq": 3,
            "at": "2026-08-31T04:13:28+00:00",
            "stage": "discovery",
            "kind": "prompt",
            "level": "info",
            "op": "search",
            "chars": 1196,
        }
    )

    (entry,) = envoyes[0]
    # L'enveloppe reste à plat : ce sont les colonnes de `ScraperRunLog`.
    assert entry["seq"] == 3
    assert entry["stage"] == "discovery"
    assert entry["kind"] == "prompt"
    assert entry["level"] == "info"
    # Le reste est imbriqué, et rien ne se perd en route.
    assert entry["data"] == {"op": "search", "chars": 1196}


def test_le_journal_distant_tronque_ce_qui_ferait_refuser_le_paquet():
    """Une URL trop longue ferait perdre les trente-neuf autres événements."""
    envoyes: list[list[dict]] = []

    class ApiCapture:
        def report_logs(self, run_id, entries):
            envoyes.append(entries)

    journal = RemoteJournal(ApiCapture(), run_id=1, batch=1)
    journal.add({"seq": 1, "kind": "skip", "url": "https://exemple.fr/" + "a" * 900})

    (entry,) = envoyes[0]
    assert len(entry["url"]) == 500


def test_le_graphe_part_avec_le_premier_evenement():
    """`run_start` porte les huit étages : la console dessine sans rien deviner."""
    from sortiesbot.journal import _wire
    from sortiesbot.stages import describe

    entry = _wire({"seq": 1, "kind": "run_start", "level": "info", "stages": describe()})
    assert [s["number"] for s in entry["data"]["stages"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    # L'attribution est la septième, entre l'extraction et la publication : sa
    # place dans le graphe est ce que la console dessine.
    assert [s["label"] for s in entry["data"]["stages"]][6:] == ["Attribution", "Publication"]


def test_la_filiation_descend_sur_toute_la_piste():
    """C'est elle qui permet de répondre à « d'où vient cette sortie ? »."""
    recs: list[dict] = []
    log = RunLog(path=None, verbose=False)
    log.sink = recs.append

    with log.trail(agenda="https://agenda.fr/jeune-public"):
        with log.stage(Stage.SELECT) as st:
            log.event("link", index=1, url="https://agenda.fr/spectacle")
            st.produced("1 retenu")
        with log.trail(page="https://agenda.fr/spectacle"):
            log.event("submit", event_id=42)
    log.event("run_end")

    par_type = {r["kind"]: r for r in recs}
    # Un lien sait sur quel agenda il a été relevé.
    assert par_type["link"]["agenda"] == "https://agenda.fr/jeune-public"
    # Une sortie sait de quelle page ET de quel agenda elle descend.
    assert par_type["submit"]["page"] == "https://agenda.fr/spectacle"
    assert par_type["submit"]["agenda"] == "https://agenda.fr/jeune-public"
    # Et la piste se referme : `run_end` n'appartient à personne.
    assert "agenda" not in par_type["run_end"]
    assert "page" not in par_type["run_end"]


def test_un_champ_explicite_prime_sur_la_piste():
    """La piste est un défaut, pas une contrainte."""
    recs: list[dict] = []
    log = RunLog(path=None, verbose=False)
    log.sink = recs.append
    with log.trail(agenda="https://a.fr"):
        log.event("candidate", agenda="https://b.fr")
    assert recs[0]["agenda"] == "https://b.fr"


# ───────────────────────────── jugée comme sortie, ou seulement déjà vue
#
# La distinction sur laquelle repose le filtre de la reconnaissance. Elle ne se
# voit dans aucun compteur : s'y tromper ne fait pas tomber un run, ça retire
# silencieusement un agenda du champ de la recherche, pour toujours.


def test_une_page_soumise_a_ete_jugee_comme_sortie():
    with SeenStore() as store:
        store.remember("https://exemple.fr/spectacle", "submitted", event_id=12)
        assert store.seen_as_event("https://exemple.fr/spectacle")


def test_les_verdicts_de_fiche_valent_jugement():
    # Tous supposent qu'une fiche a été extraite de la page : elle a donc bien
    # été lue comme une sortie, et la rouvrir n'apprendrait rien.
    for decision in ("submitted", "out_of_area", "out_of_period", "invalid"):
        with SeenStore() as store:
            store.remember(f"https://exemple.fr/{decision}", decision)
            assert store.seen_as_event(f"https://exemple.fr/{decision}"), decision


def test_hors_sujet_ne_vaut_pas_jugement():
    # C'est le déguisement d'un agenda dont le dépouillement a échoué : la page
    # reste « déjà vue » — on ne la relira pas comme une sortie — mais elle
    # garde le droit d'être reconnue et dépouillée.
    with SeenStore() as store:
        store.remember("https://agenda.fr/", "irrelevant")
        assert store.seen("https://agenda.fr/")
        assert not store.seen_as_event("https://agenda.fr/")


def test_une_page_inconnue_na_ete_jugee_par_personne():
    with SeenStore() as store:
        assert not store.seen_as_event("https://jamais-vue.fr/")


def test_la_memoire_distante_garde_le_verdict_du_site():
    """La décision voyageait déjà sur le réseau ; elle était jetée à l'arrivée.

    Sans elle, `RemoteStore` ne savait répondre qu'à « connue ou pas », et le
    filtre de la reconnaissance aurait dû choisir entre ne rien filtrer et
    écarter des agendas pour toujours.
    """

    class ApiMemoire:
        def known_urls(self, urls):
            verdicts = {
                "https://exemple.fr/spectacle": ("submitted", 12),
                "https://agenda.fr/": ("irrelevant", None),
            }
            return {u: verdicts[u] for u in urls if u in verdicts}

        def report_items(self, run_id, items):
            pass

    store = RemoteStore(ApiMemoire(), run_id=1)
    store.preload(["https://exemple.fr/spectacle", "https://agenda.fr/"])

    assert store.seen_as_event("https://exemple.fr/spectacle")
    # Connue, mais pas comme une sortie : elle reste dépouillable.
    assert store.seen("https://agenda.fr/")
    assert not store.seen_as_event("https://agenda.fr/")


def test_la_memoire_distante_relit_ses_propres_verdicts():
    """Ce que le run vient de décider vaut pour la suite du run.

    Une sortie soumise à la première page d'un agenda ne doit pas être reproposée
    à la seconde — et le site, lui, n'en sait encore rien : la vidange n'a pas eu
    lieu.
    """

    class ApiVide:
        def known_urls(self, urls):
            return {}

        def report_items(self, run_id, items):
            pass

    store = RemoteStore(ApiVide(), run_id=1)
    store.report("https://exemple.fr/spectacle", "submitted", event_id=7)
    assert store.seen_as_event("https://exemple.fr/spectacle")
