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
    "aggregatorDomains": "kidiklik.fr, sortiraparis.com",
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
    # La liste d'agrégateurs est commune au site : le serveur l'envoie telle
    # qu'elle est, la recherche ne la porte plus.
    assert config.aggregator_domains == ["kidiklik.fr", "sortiraparis.com"]


def test_une_liste_dagregateurs_videe_ne_ressuscite_pas_celle_du_scraper():
    """Le site tient la liste : la vider est une décision, pas un oubli."""
    config = config_from_api({**API_CONFIG, "aggregatorDomains": ""})
    assert config.aggregator_domains == []


def test_les_domaines_bloques_ne_sont_plus_un_reglage_de_recherche():
    """Un réseau social est illisible partout : c'est un fait, pas un choix."""
    config = config_from_api(API_CONFIG)
    assert config.blocked_domains == Config(name="x", theme="y").blocked_domains
    assert config.block_aggregators is False


def test_la_case_a_cocher_verse_les_agregateurs_dans_les_domaines_bloques():
    config = config_from_api({**API_CONFIG, "blockAggregators": True})
    assert config.block_aggregators is True
    assert "kidiklik.fr" in config.blocked_domains
    assert "sortiraparis.com" in config.blocked_domains
    # Les domaines illisibles restent : la case ajoute, elle ne remplace pas.
    assert "facebook.com" in config.blocked_domains


def test_bloquer_deux_fois_les_agregateurs_ne_les_duplique_pas():
    """`validated` repasse sur une configuration déjà fusionnée sans l'enfler."""
    from sortiesbot.config import validated

    config = validated(validated(config_from_api({**API_CONFIG, "blockAggregators": True})))
    assert config.blocked_domains.count("kidiklik.fr") == 1


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
    monkeypatch.setattr(worker, "get_provider", lambda config, api_key=None, serper_key=None: provider)
    monkeypatch.setattr(
        worker,
        "run_pipeline",
        lambda config, prov, store, spp, log, submit=False, ledger=None, engine=None: (
            __import__("sortiesbot.orchestrator", fromlist=["run"]).run(
                config, prov, store, spp, log,
                submit=submit, fetcher=fetcher, ledger=ledger, engine=engine,
            )
        ),
    )
    # Le registre du classifieur s'accumule d'un run à l'autre : un test ne
    # doit surtout pas écrire dans celui du dépôt.
    monkeypatch.setattr(worker, "LEDGER_DIR", runs_dir)
    env = type("Env", (), {"anthropic_key": "clé", "serper_key": None})()
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
        worker, "get_provider", lambda config, api_key=None, serper_key=None: (_ for _ in ()).throw(RuntimeError("boum"))
    )
    env = type("Env", (), {"anthropic_key": "clé", "serper_key": None})()
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
        # Le coût des recherches est **porté**, non dérivé du compteur : deux
        # moteurs ne facturent pas au même tarif, et un run peut mêler les deux.
        usage=Usage(
            input_tokens=1000, output_tokens=50, web_searches=2,
            cost_usd=0.01, search_cost_usd=0.02,
        ),
    )
    counters = worker.counters(summary)
    assert counters["skipped"] == 3  # vues + bloquées + hors sujet + inexploitables
    assert counters["duplicates"] == 1
    assert counters["webSearches"] == 2
    assert counters["costUsd"] == pytest.approx(0.03)  # jetons + 2 recherches


# ════════════════════════ le banc d'extraction : la file qui dépense

class BancApi(ScraperApi):
    """Le site vu par le banc : une extraction en file, et ce qu'on lui rend."""

    def __init__(self, job: dict[str, object]):
        super().__init__()
        self.job = job
        self.reported: list[tuple[int, dict[str, object]]] = []
        self.failed: list[tuple[int, str]] = []

    def categories(self):
        return {"Spectacle": 1, "Musée": 2}

    def report_extraction(self, extraction_id, result):
        self.reported.append((extraction_id, result))

    def fail_extraction(self, extraction_id, error):
        self.failed.append((extraction_id, error))


class CompteurProvider:
    """Un fournisseur qui compte ses appels et déclare une consommation.

    C'est le point du test : il n'y a pas d'autre façon de mesurer l'étage 6
    que d'appeler le modèle. Si ce compteur reste à zéro, aucune fiche du banc
    n'a coûté un jeton — et aucune n'a été mesurée non plus.
    """

    def __init__(self):
        self.calls: list[dict[str, object]] = []
        self.usage = Usage()

    def extract(self, url, content, config, categories, log, *, multiple=False):
        self.calls.append({"url": url, "content": content, "categories": list(categories)})
        self.usage.input_tokens += 2130
        self.usage.output_tokens += 410
        self.usage.cost_usd += 0.0031
        return [sortie()]


def banc_job(**extra):
    return {
        "id": 7,
        "url": "https://theatre.exemple.fr/le-petit-prince",
        "model": "claude-haiku-4-5",
        "text": "Le Petit Prince, spectacle de marionnettes. Du 3 août au 23 août 2026. "
        "Tarif : 8 €, à partir de 3 ans. Théâtre municipal, 12 rue des Arts, 76000 Rouen.",
        "dates": [],
        **extra,
    }


def run_extraction(monkeypatch, provider, job=None):
    api = BancApi(job or banc_job())
    monkeypatch.setattr(
        worker, "get_provider", lambda config, api_key=None, serper_key=None: provider
    )
    env = type("Env", (), {"anthropic_key": "clé", "serper_key": None})()
    worker.extract(api.job, api, env, quiet=True)
    return api


def test_la_file_dextraction_appelle_vraiment_le_modele(monkeypatch):
    """Le banc de l'étage 6 **dépense**, et c'est le seul du banc à le faire.

    Ce test existe pour qu'une consommation nulle sur la facture ne puisse
    jamais vouloir dire « le code ne l'appelait pas » : il vérifie l'appel, son
    entrée, et le coût rapporté au site.
    """
    provider = CompteurProvider()
    api = run_extraction(monkeypatch, provider)

    assert len(provider.calls) == 1
    extraction_id, result = api.reported[0]
    assert extraction_id == 7
    assert result["inputTokens"] == 2130
    assert result["outputTokens"] == 410
    assert result["costUsd"] == 0.0031


def test_le_texte_envoye_au_modele_est_celui_que_le_site_a_gele(monkeypatch):
    """L'entrée de l'étage 6 est la sortie de l'étage 5, pas la page.

    Si le worker retéléchargeait, une fiche fautive ne dirait plus lequel des
    deux étages est en cause.
    """
    provider = CompteurProvider()
    job = banc_job()
    run_extraction(monkeypatch, provider, job)

    assert provider.calls[0]["content"] == job["text"]
    assert provider.calls[0]["url"] == job["url"]


def test_le_referentiel_des_categories_vient_du_site(monkeypatch):
    """Le prompt impose au modèle de choisir dans la liste du site : une liste
    inventée dans le worker mesurerait autre chose que ce que le pipeline fait."""
    provider = CompteurProvider()
    run_extraction(monkeypatch, provider)

    assert provider.calls[0]["categories"] == ["Musée", "Spectacle"]


def test_le_modele_demande_par_la_console_est_celui_qui_repond(monkeypatch):
    """Une mesure sans le nom du modèle ne se compare à rien : c'est la première
    chose qui change entre deux campagnes."""
    provider = CompteurProvider()
    api = run_extraction(monkeypatch, provider, banc_job(model="un-autre-modele"))

    assert api.reported[0][1]["model"] == "un-autre-modele"


def test_un_appel_qui_echoue_clot_quand_meme_lextraction(monkeypatch):
    """Sans clôture, la console resterait sur « en cours » et le worker
    repasserait à côté indéfiniment."""

    class Cassé(CompteurProvider):
        def extract(self, *a, **kw):
            raise RuntimeError("quota dépassé")

    api = run_extraction(monkeypatch, Cassé())

    # `extract_page` attrape l'erreur du fournisseur et la rapporte : c'est une
    # réponse, pas une panne du banc.
    assert "quota dépassé" in str(api.reported[0][1]["error"])


def test_un_fournisseur_introuvable_clot_lextraction_en_echec(monkeypatch):
    monkeypatch.setattr(
        worker,
        "get_provider",
        lambda config, api_key=None, serper_key=None: (_ for _ in ()).throw(RuntimeError("pas de clé")),
    )
    api = BancApi(banc_job())
    env = type("Env", (), {"anthropic_key": None, "serper_key": None})()
    worker.extract(api.job, api, env, quiet=True)

    assert api.failed[0][0] == 7
    assert "pas de clé" in api.failed[0][1]
