"""Le worker piloté par la console : configuration reçue du site, mémoire
partagée en base, compte rendu d'exécution.

Aucun réseau : l'API du site est simulée, comme dans test_pipeline.
"""

from __future__ import annotations

import io

import pytest

from sortiesbot import worker
from sortiesbot.api import ApiError
from sortiesbot.config import Config, ConfigError, config_from_api
from sortiesbot.journal import RunLog
from sortiesbot.models import Summary, Usage
from sortiesbot.store import RemoteStore, normalize_url

from test_pipeline import (  # fakes partagés
    AGENDA_HTML,
    AGENDA_URL,
    EVENT_HTML,
    EVENT_URL,
    FakeApi,
    FakeFetcher,
    FakeProvider,
    geocodeur_simule,  # noqa: F401 — fixture autouse réutilisée telle quelle
    sortie,
)
from sortiesbot.models import FoundPage

API_CONFIG = {
    "id": 4,
    "name": "spectacles du week-end",
    "theme": "des spectacles et contes pour enfants de 0 à 12 ans",
    "area": "Paris",
    "period": "ce week-end",
    "horizonDays": 3,
    "maxEvents": 5,
    "maxSearches": 2,
    "maxAgendas": 2,
    "maxLinksPerAgenda": 4,
    "maxPageChars": 6000,
    "maxCostUsd": 0.5,
    "keepOutOfScope": False,
    "defaultCategory": "Non classé",
    "postalPrefixes": "75, 92 ,",
    "blockedDomains": "facebook.com,instagram.com",
    "searchModel": "claude-haiku-4-5",
    "selectModel": "claude-sonnet-5",
    "extractionModel": "claude-haiku-4-5",
    "searchPrompt": None,
    "selectPrompt": "   ",
    "extractionPrompt": "Lis $url et rends du JSON.",
}


class ScraperApi(FakeApi):
    """L'API du site, côté worker : file d'exécutions et mémoire des pages."""

    def __init__(self, queue=None, known=(), **kwargs):
        super().__init__(**kwargs)
        self.queue = list(queue or [])
        self.known = set(known)
        self.items: list[dict] = []
        self.finished: list[tuple[int, str, dict]] = []
        self.seen_calls: list[list[str]] = []

    def next_run(self):
        return self.queue.pop(0) if self.queue else None

    def known_urls(self, urls):
        self.seen_calls.append(list(urls))
        return {u for u in urls if u in self.known}

    def report_items(self, run_id, items):
        self.items.extend(items)
        for item in items:
            if item.get("remember"):
                self.known.add(item.get("key", item["url"]))

    def finish_run(self, run_id, status, **counters):
        self.finished.append((run_id, status, counters))


@pytest.fixture
def log():
    return RunLog(path=None, verbose=False, stream=io.StringIO())


# ---------------------------------------------------------------- configuration


def test_configuration_du_site_est_traduite():
    config = config_from_api(API_CONFIG)
    assert config.name == "spectacles du week-end"
    assert config.area == "Paris"
    assert config.horizon_days == 3
    assert config.max_cost_usd == 0.5
    assert config.keep_out_of_scope is False
    assert config.select_model == "claude-sonnet-5"
    # Les listes arrivent en texte séparé par des virgules.
    assert config.postal_prefixes == ["75", "92"]
    assert config.blocked_domains == ["facebook.com", "instagram.com"]


def test_prompt_vide_veut_dire_celui_du_scraper():
    config = config_from_api(API_CONFIG)
    assert config.search_prompt == Config(name="x", theme="y").search_prompt
    assert config.select_prompt == Config(name="x", theme="y").select_prompt
    assert config.extraction_prompt == "Lis $url et rends du JSON."


def test_configuration_incomplete_est_refusee():
    with pytest.raises(ConfigError):
        config_from_api({"name": "sans thème"})


def test_defauts_du_scraper_pour_les_cles_absentes():
    config = config_from_api({"name": "minimal", "theme": "des sorties pour enfants"})
    reference = Config(name="minimal", theme="des sorties pour enfants")
    assert config == reference


# ------------------------------------------------------------- mémoire distante


def test_la_memoire_distante_ninterroge_le_site_quune_fois():
    api = ScraperApi(known={normalize_url(EVENT_URL)})
    store = RemoteStore(api, run_id=1)
    store.preload([EVENT_URL, AGENDA_URL])

    assert store.seen(EVENT_URL + "?utm_source=mail")
    assert not store.seen(AGENDA_URL)
    assert len(api.seen_calls) == 1  # le préchargement a tout couvert


def test_une_url_apparue_apres_le_prechargement_est_demandee():
    api = ScraperApi()
    store = RemoteStore(api, run_id=1)
    store.preload([AGENDA_URL])
    store.seen("https://ailleurs.fr/sortie")
    assert len(api.seen_calls) == 2


def test_les_pages_partent_par_lots_et_a_la_fermeture():
    api = ScraperApi()
    with RemoteStore(api, run_id=7, batch=3) as store:
        for i in range(4):
            store.report(f"https://exemple.fr/{i}", "irrelevant")
        assert len(api.items) == 3  # le lot plein est parti, le reste attend
    assert len(api.items) == 4


def test_la_cle_memorisee_est_normalisee_le_lien_reste_exact():
    api = ScraperApi()
    with RemoteStore(api, run_id=7) as store:
        store.report("http://www.Exemple.fr/Sortie/?utm_source=x", "submitted", event_id=12)

    item = api.items[0]
    assert item["url"] == "http://www.Exemple.fr/Sortie/?utm_source=x"
    assert item["key"] == "https://exemple.fr/Sortie"
    assert item["eventId"] == 12
    assert item["remember"] is True


def test_une_decision_provisoire_nest_pas_memorisee():
    api = ScraperApi()
    with RemoteStore(api, run_id=7) as store:
        store.report(EVENT_URL, "dry_run", remember=False)
        assert not store.seen(EVENT_URL)
    assert api.items[0]["remember"] is False


# --------------------------------------------------------------------- worker


def job(**overrides):
    payload = {"id": 42, "submit": True, "config": dict(API_CONFIG)}
    payload.update(overrides)
    return payload


def standard():
    provider = FakeProvider(
        [FoundPage(url=AGENDA_URL, title="Agenda")],
        {EVENT_URL: sortie()},
    )
    fetcher = FakeFetcher({AGENDA_URL: AGENDA_HTML, EVENT_URL: EVENT_HTML})
    return provider, fetcher


def run_job(api, monkeypatch, provider, fetcher, runs_dir, payload=None):
    """Joue `worker.execute` avec un fournisseur et un serveur web simulés."""
    monkeypatch.setattr(worker, "get_provider", lambda config, api_key=None: provider)
    monkeypatch.setattr(
        worker,
        "run_pipeline",
        lambda config, prov, store, spp, log, submit=False, ledger=None: __import__(
            "sortiesbot.orchestrator", fromlist=["run"]
        ).run(
            config, prov, store, spp, log, submit=submit, fetcher=fetcher, ledger=ledger
        ),
    )
    # Le registre du classifieur s'accumule d'un run à l'autre : un test ne
    # doit surtout pas écrire dans celui du dépôt.
    monkeypatch.setattr(worker, "LEDGER_PATH", runs_dir / "classifier.jsonl")
    env = type("Env", (), {"anthropic_key": "clé"})()
    worker.execute(payload or job(), api, env, runs_dir=runs_dir, quiet=True)


def test_une_execution_est_jouee_puis_close(tmp_path, monkeypatch, geocodeur_simule):
    provider, fetcher = standard()
    api = ScraperApi()
    run_job(
        api,
        monkeypatch,
        provider,
        fetcher,
        tmp_path,
        job(config={**API_CONFIG, "keepOutOfScope": True}),
    )

    run_id, status, counters = api.finished[0]
    assert (run_id, status) == (42, "DONE")
    assert counters["submitted"] == 1
    assert counters["candidates"] == 1
    # La page soumise est désormais en mémoire, avec l'identifiant de la sortie.
    memorisee = [i for i in api.items if i["decision"] == "submitted"][0]
    assert memorisee["key"] == normalize_url(EVENT_URL)
    assert memorisee["eventId"] == 101


def test_une_configuration_invalide_clot_lexecution(tmp_path):
    api = ScraperApi()
    worker.execute(job(config={"name": "sans thème"}), api, None, runs_dir=tmp_path, quiet=True)
    run_id, status, counters = api.finished[0]
    assert (run_id, status) == (42, "FAILED")
    assert "obligatoire" in counters["error"]


def test_un_plantage_imprevu_clot_quand_meme_lexecution(tmp_path, monkeypatch):
    """Sans clôture, la console resterait bloquée sur « En cours »."""
    api = ScraperApi()
    monkeypatch.setattr(
        worker, "get_provider", lambda config, api_key=None: (_ for _ in ()).throw(RuntimeError("boum"))
    )
    env = type("Env", (), {"anthropic_key": "clé"})()
    worker.execute(job(), api, env, runs_dir=tmp_path, quiet=True)

    run_id, status, counters = api.finished[0]
    assert (run_id, status) == (42, "FAILED")
    assert "boum" in counters["error"]


def test_journal_fichier_impossible_narrete_pas_le_run(tmp_path, monkeypatch, geocodeur_simule):
    """Le vrai journal est en base : un `runs/` inutilisable ne doit pas coûter
    une recherche. En production le cas se présente en droits — le dossier créé
    par root lors d'un essai, alors que le service tourne en `deploy` ; ici on
    le provoque autrement, pour que le test vaille aussi quand il est joué en
    root, qui passe outre les permissions."""
    bouche = tmp_path / "runs"
    bouche.write_text("ceci n'est pas un dossier")
    provider, fetcher = standard()
    api = ScraperApi()
    run_job(api, monkeypatch, provider, fetcher, bouche)

    run_id, status, counters = api.finished[0]
    assert (run_id, status) == (42, "DONE")
    assert counters["candidates"] == 1


def test_compteurs_du_resume():
    summary = Summary(
        candidates=6,
        pages=2,
        retained=3,
        submitted=3,
        duplicates=1,
        skipped_seen=1,
        skipped_blocked=1,
        skipped_irrelevant=1,
        skipped_invalid=0,
        errors=1,
        usage=Usage(input_tokens=1000, output_tokens=50, web_searches=2, cost_usd=0.01),
    )
    counters = worker.counters(summary)
    assert counters["skipped"] == 3  # vues + bloquées + hors sujet + inexploitables
    assert counters["duplicates"] == 1
    assert counters["webSearches"] == 2
    assert counters["costUsd"] == pytest.approx(0.03)  # jetons + 2 recherches
