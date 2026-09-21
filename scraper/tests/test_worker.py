"""Le worker piloté par la console : configuration reçue du site, mémoire
partagée en base, compte rendu d'exécution.

Aucun réseau : l'API du site est simulée, comme dans test_pipeline.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
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

from sortiesbot import worker
from sortiesbot.api import ApiError
from sortiesbot.config import Config, ConfigError, Environment, config_from_api
from sortiesbot.journal import RunLog
from sortiesbot.models import FoundPage, Summary, Usage
from sortiesbot.store import RemoteStore, normalize_url

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
        # Le site rend sa décision avec l'URL : une page connue du faux site
        # l'est comme une sortie soumise, le cas courant en production.
        return {u: ("submitted", None) for u in urls if u in self.known}

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
    monkeypatch.setattr(worker, "get_provider", lambda config, **clés: provider)
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
    env = Environment(api_url="http://site", api_key="spp_x", anthropic_key="clé")
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
    memorisee = next(i for i in api.items if i["decision"] == "submitted")
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
        worker,
        "get_provider",
        lambda config, **clés: (_ for _ in ()).throw(RuntimeError("boum")),
    )
    env = Environment(api_url="http://site", api_key="spp_x", anthropic_key="clé")
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


# --------------------------------------------------- clôture et coupures réseau
# Un déploiement du site redémarre l'API (deploy.yml) : les appels du worker en
# cours tombent sur une connexion refusée. C'est arrivé, et l'exécution #23 est
# restée « En cours » pour toujours — la clôture, elle, n'était pas réessayée.


class ApiCapricieuse(ScraperApi):
    """Refuse les `pannes` premières clôtures, accepte la suivante."""

    def __init__(self, pannes: int, **kwargs):
        super().__init__(**kwargs)
        self.pannes = pannes
        self.essais = 0

    def finish_run(self, run_id, status, **counters):
        self.essais += 1
        if self.essais <= self.pannes:
            raise ApiError("API injoignable : ConnectionError")
        super().finish_run(run_id, status, **counters)


def test_la_cloture_insiste_quand_lapi_redemarre():
    api = ApiCapricieuse(pannes=2)
    attentes: list[float] = []

    assert worker.finish(api, 42, "DONE", {"costUsd": 0.0}, quiet=True, sleep=attentes.append)

    assert api.essais == 3
    assert api.finished == [(42, "DONE", {"costUsd": 0.0})]
    # Les attentes s'espacent : le temps qu'une API redémarrée réponde.
    assert attentes == [2, 4]


def test_une_cloture_definitivement_impossible_ne_leve_pas():
    """Le run suivant ne doit pas payer l'échec du précédent."""
    api = ApiCapricieuse(pannes=99)

    assert worker.finish(api, 42, "DONE", {}, quiet=True, sleep=lambda _: None) is False

    assert api.essais == len(worker.FINISH_DELAYS) + 1
    assert api.finished == []


def test_lexecution_reessaie_sa_cloture(tmp_path, monkeypatch, geocodeur_simule):
    """La ténacité doit être dans le chemin réel, pas seulement dans `finish`."""
    monkeypatch.setattr(worker, "FINISH_DELAYS", (0, 0, 0))
    provider, fetcher = standard()
    api = ApiCapricieuse(pannes=1)
    run_job(api, monkeypatch, provider, fetcher, tmp_path)

    assert api.essais == 2
    assert api.finished[0][:2] == (42, "DONE")


def test_la_session_rejoue_la_connexion_mais_jamais_la_lecture():
    """Une connexion refusée n'est jamais arrivée au site : la rejouer est sûr.

    Une lecture interrompue, non : la requête a pu être exécutée, et
    `POST /api/events` créerait alors une seconde proposition en modération.
    """
    from sortiesbot.api import retrying_session

    retry = retrying_session().get_adapter("https://exemple.fr").max_retries
    assert retry.connect == 3
    assert retry.read == 0
    assert retry.status == 0
    # `None` vaut « toutes les méthodes » : le POST du worker en profite.
    assert retry.allowed_methods is None


# ═══════════════════════════════ ce sous quoi le banc joue le tri


def test_le_worker_joue_la_recherche_que_le_run_declare():
    """La console fixe la recherche, le worker obéit.

    Le sens de la flèche compte. Le worker inventait autrefois une fenêtre et
    la déclarait au site ; c'est désormais la console qui la fixe au lancement,
    en dates absolues, et le worker la reçoit avec le run.

    Ces valeurs servent **deux fois** : elles partent dans le prompt du tri, et
    elles servent à juger ce qu'il a rendu. Venant de la même ligne en base,
    elles ne peuvent plus se contredire — ce que ce test vérifie par le prompt
    lui-même plutôt que par une copie des mêmes valeurs.
    """
    run = {
        "id": 7,
        "stage": "SELECT",
        "recherche": {
            "dateFrom": "2027-03-01",
            "dateTo": "2027-03-31",
            "postalPrefixes": ["77", "78"],
            "maxLinks": 3,
            "theme": "ateliers",
        },
    }
    config = worker._config_du_run(run, quiet=True)

    assert config.date_from.isoformat() == "2027-03-01"
    assert config.date_to.isoformat() == "2027-03-31"
    assert config.postal_prefixes == ["77", "78"]
    assert config.max_links_per_agenda == 3

    prompt = config.render_select("https://exemple.fr/agenda", "1. a | b")
    assert "du 2027-03-01 au 2027-03-31" in prompt
    assert "ateliers" in prompt
    assert "Au plus 3." in prompt


def test_une_fenetre_absolue_ne_bouge_pas_avec_le_calendrier():
    """C'est toute la raison des dates absolues.

    Une fenêtre relative — « les trente prochains jours » — ferait qu'un même
    run ne mesure plus la même chose selon le jour où on le rejoue : il
    mesurerait le calendrier plutôt que la brique.
    """
    run = {
        "id": 8,
        "stage": "SELECT",
        "recherche": {
            "dateFrom": "2020-01-01",
            "dateTo": "2020-01-31",
            "postalPrefixes": ["75"],
            "maxLinks": 8,
            "theme": "sorties enfants",
        },
    }
    config = worker._config_du_run(run, quiet=True)

    # Une fenêtre de 2020 reste en 2020, six ans après.
    assert config.date_from.year == 2020
    assert config.date_to.isoformat() == "2020-01-31"


def test_un_run_sans_recherche_retombe_sur_le_banc():
    """Ceux mis en file avant que la console ne déclare sa recherche.

    Les laisser échouer serait pire : ils ont un corpus à jouer, et une
    configuration de repli dit au moins quelque chose de vrai — le prompt
    annoncera fidèlement la fenêtre utilisée.
    """
    config = worker._config_du_run({"id": 9, "stage": "SELECT"}, quiet=True)

    assert config.theme == "sorties enfants"
    assert config.date_from == date.today()


def test_une_date_illisible_ne_fait_pas_echouer_le_run():
    """Elle retombe sur le calcul relatif, et le prompt le dira."""
    run = {"id": 10, "stage": "SELECT", "recherche": {"dateFrom": "hier", "dateTo": ""}}
    config = worker._config_du_run(run, quiet=True)

    assert config.date_from == date.today()


# ═══════════════════════════════ de quoi un run du banc est le run


def test_un_run_declare_son_modele_et_l_empreinte_de_son_prompt():
    """Sans eux, deux points d'une courbe ne sont pas comparables — et le savoir
    après coup est impossible : un run joué ne dira jamais ce qu'il était.

    Ils partent à la **clôture** parce que le worker ne les connaît qu'une fois
    le run réclamé : c'est l'étage de ce run qui dit quel modèle il interroge.
    """
    config = worker._config_du_run({"id": 11, "stage": "EXTRACT"}, quiet=True)

    declare = worker._declare("EXTRACT", config)

    assert declare["model"] == config.extraction_model
    assert len(declare["promptHash"]) == 16


def test_chaque_etage_declare_le_prompt_qu_il_a_vraiment_posé():
    """Le tri et l'extraction ne posent pas la même question : une empreinte
    commune ferait passer deux runs incomparables pour comparables."""
    config = worker._config_du_run({"id": 12, "stage": "SELECT"}, quiet=True)

    assert worker._declare("SELECT", config)["promptHash"] != (
        worker._declare("EXTRACT", config)["promptHash"]
    )
    assert worker._declare("SELECT", config)["model"] == config.select_model


def test_l_empreinte_change_avec_le_gabarit_et_pas_avec_la_page():
    """C'est le gabarit qu'on empreinte, pas le prompt rendu : celui-ci change à
    chaque page, et ce qu'on veut savoir est si deux runs ont posé la même
    question."""
    from dataclasses import replace as dc_replace

    config = worker._config_du_run({"id": 13, "stage": "EXTRACT"}, quiet=True)
    autre = dc_replace(config, extraction_prompt=config.extraction_prompt + "\nUne règle de plus.")

    assert worker._declare("EXTRACT", config) != worker._declare("EXTRACT", autre)


def test_un_etage_de_python_pur_ne_declare_aucun_modele():
    """Annoncer un modèle qu'on n'a pas appelé serait une déclaration fausse, et
    la colonne servirait à comparer ce qui ne se compare pas."""
    assert worker._declare("HARVEST", None) == {"model": "", "promptHash": ""}


# ───────────────────────────── l'étage 6 rejoué par un autre fournisseur
#
# L'expérience « extraction en local » ne tient qu'à une chose : pouvoir
# rejouer la même brique sur le même corpus gelé avec un autre fournisseur, et
# que les deux runs restent distinguables dans la console. Le choix vient du
# **run**, comme la recherche — c'est la console qui décide sous quoi on
# mesure, pas la machine qui mesure.


def test_sans_declaration_le_banc_ne_change_pas_de_fournisseur():
    """Un run lancé avant ce changement n'a pas la clé, et garde le bon défaut."""
    config = worker._config_du_run({"id": 20, "stage": "EXTRACT"}, quiet=True)
    assert config.provider == "anthropic"


def test_le_run_impose_son_fournisseur():
    config = worker._config_du_run(
        {"id": 21, "stage": "EXTRACT", "extraction": {"provider": "gliner"}}, quiet=True
    )
    assert config.provider == "gliner"


def test_le_point_de_controle_se_choisit_aussi():
    config = worker._config_du_run(
        {
            "id": 22,
            "stage": "EXTRACT",
            "extraction": {"provider": "gliner", "model": "fastino/gliner2-multi-v1"},
        },
        quiet=True,
    )
    assert config.gliner_model == "fastino/gliner2-multi-v1"


def test_un_point_de_controle_vide_garde_celui_par_defaut():
    config = worker._config_du_run(
        {"id": 23, "stage": "EXTRACT", "extraction": {"provider": "gliner", "model": ""}},
        quiet=True,
    )
    assert config.gliner_model == Config(name="x", theme="x").gliner_model


def test_un_fournisseur_inattendu_arrete_le_run_avant_le_corpus():
    with pytest.raises(ConfigError, match="fournisseur inconnu"):
        worker._config_du_run(
            {"id": 24, "stage": "EXTRACT", "extraction": {"provider": "glinerr"}}, quiet=True
        )


def test_le_fournisseur_survit_a_une_recherche_declaree():
    """Les deux réglages voyagent ensemble : l'un ne doit pas effacer l'autre."""
    run = {
        "id": 25,
        "stage": "EXTRACT",
        "recherche": {"theme": "spectacles", "dateFrom": "2026-07-01", "dateTo": "2026-07-31"},
        "extraction": {"provider": "gliner"},
    }
    config = worker._config_du_run(run, quiet=True)
    assert config.provider == "gliner"
    assert config.theme == "spectacles"


def test_un_run_gliner_ne_se_declare_pas_joue_par_haiku():
    """Deux points de la courbe doivent porter deux modèles différents.

    Sans ça, la comparaison que ce run existe pour rendre serait irrattrapable
    après coup : un run joué ne dit jamais ce qu'il était.
    """
    config = worker._config_du_run(
        {"id": 26, "stage": "EXTRACT", "extraction": {"provider": "gliner"}}, quiet=True
    )
    declare = worker._declare("EXTRACT", config)
    assert declare["model"].startswith("gliner:")
    assert "haiku" not in declare["model"]


# ───────────────────────────── le même banc, un modèle d'OpenRouter
#
# L'étiqueteur ne sait remplir qu'une fiche ; le routeur, lui, sait jouer les
# **deux** étages qui appellent quelqu'un — le tri et l'extraction. C'est ce
# qui fait l'intérêt de la mesure : quel modèle tient l'étage 6 pour combien,
# et lequel s'effondre sur le tri.


def test_un_run_openrouter_impose_son_modele_aux_deux_etages():
    """Un run ne joue qu'un étage, et on ne sait pas encore lequel ici."""
    config = worker._config_du_run(
        {
            "id": 30,
            "stage": "EXTRACT",
            "extraction": {"provider": "openrouter", "model": "google/gemini-2.5-flash"},
        },
        quiet=True,
    )
    assert config.provider == "openrouter"
    assert config.extraction_model == "google/gemini-2.5-flash"
    assert config.select_model == "google/gemini-2.5-flash"


def test_un_run_openrouter_sans_modele_garde_celui_de_la_production():
    """Même modèle, autre route : la comparaison la plus propre qui soit."""
    config = worker._config_du_run(
        {"id": 31, "stage": "EXTRACT", "extraction": {"provider": "openrouter"}}, quiet=True
    )
    assert config.extraction_model == Config(name="x", theme="x").extraction_model


def test_un_modele_openrouter_intraduisible_arrete_le_run_avant_le_corpus():
    """Pas à la première entrée : le worker aurait déjà été occupé pour rien."""
    with pytest.raises(ConfigError, match="modèle du run"):
        worker._config_du_run(
            {
                "id": 32,
                "stage": "EXTRACT",
                "extraction": {"provider": "openrouter", "model": "gemini-tout-court"},
            },
            quiet=True,
        )


def test_un_run_openrouter_declare_le_modele_reellement_appele():
    """« claude-haiku-4-5 » et « anthropic/claude-haiku-4.5 » sont deux routes.

    Les deux points porteraient sinon le même nom de modèle, et la courbe
    mélangerait l'appel direct et le passage par le routeur.
    """
    config = worker._config_du_run(
        {"id": 33, "stage": "EXTRACT", "extraction": {"provider": "openrouter"}}, quiet=True
    )
    assert worker._declare("EXTRACT", config)["model"] == "anthropic/claude-haiku-4.5"


def test_un_run_openrouter_de_tri_declare_son_modele_aussi():
    config = worker._config_du_run(
        {
            "id": 34,
            "stage": "SELECT",
            "recherche": {"theme": "spectacles", "dateFrom": "2026-07-01", "dateTo": "2026-07-31"},
            "extraction": {"provider": "openrouter", "model": "mistralai/mistral-small"},
        },
        quiet=True,
    )
    assert worker._declare("SELECT", config)["model"] == "mistralai/mistral-small"


def test_un_run_de_banc_ne_monte_pas_le_moteur():
    """Il rejoue une brique sur un corpus gelé : l'étage 1 n'en fait pas partie.

    Sans ça, un run joué par OpenRouter réclamerait une clé Serper pour une
    recherche qu'il ne lancera jamais.
    """
    from sortiesbot.providers.base import get_provider
    from sortiesbot.providers.openrouter_provider import OpenRouterProvider

    config = worker._config_du_run(
        {"id": 35, "stage": "EXTRACT", "extraction": {"provider": "openrouter"}}, quiet=True
    )
    provider = get_provider(
        config, api_key=None, serper_key=None, openrouter_key="sk-or-x", search=False
    )
    assert isinstance(provider, OpenRouterProvider)


# ───────────────────────────────── un run de banc ne doit plus être muet
#
# Un run de deux cents pages écrivait un écran vide pendant une heure : « il est
# bloqué » ne se distinguait pas de « il travaille ». Ces deux tests verrouillent
# le minimum — une ligne par entrée, et un témoin qui crache la pile quand une
# entrée s'éternise.


class FauxBanc:
    """Le strict nécessaire pour dérouler `play_run` sur un étage de Python pur.

    L'étage 5 plutôt que l'étage 6 : il ne demande ni fournisseur ni clé, donc
    ce qu'on mesure ici est bien la boucle et rien d'autre.
    """

    def __init__(self, entrees):
        self.entrees = list(entrees)
        self.rendus: list[dict] = []
        self.cloture: dict | None = None

    def next_eval_item(self, run_id):
        return self.entrees.pop(0) if self.entrees else None

    def report_eval_read(self, run_id, result):
        self.rendus.append(result)

    def finish_eval_run(self, run_id, status, **counters):
        self.cloture = {"status": status, **counters}

    def categories(self):
        return []


def _entree(sortie_id: int) -> dict:
    return {"kind": "sortie", "sortieId": sortie_id, "url": EVENT_URL, "html": EVENT_HTML}


def _env_banc():
    return worker.Environment(api_url="http://x", api_key="k", anthropic_key="a")


def test_le_temoin_est_desarme_entre_deux_entrees(monkeypatch):
    """Un témoin qui survit à l'entrée dumperait au milieu de la suivante."""
    armes: list[float] = []
    desarmes: list[int] = []
    monkeypatch.setattr(
        worker.faulthandler,
        "dump_traceback_later",
        lambda s, repeat=False, **kw: armes.append(s),
    )
    monkeypatch.setattr(
        worker.faulthandler, "cancel_dump_traceback_later", lambda: desarmes.append(1)
    )

    api = FauxBanc([_entree(1), _entree(2)])
    worker.play_run({"id": 1, "stage": "READ", "items": 2}, api, _env_banc(), quiet=True)

    assert api.cloture and api.cloture["status"] == "DONE"
    # Deux entrées, deux armements — et au moins autant de désarmements : un par
    # entrée, plus celui de la clôture.
    assert armes == [worker.ENTREE_LENTE_S, worker.ENTREE_LENTE_S]
    assert len(desarmes) >= 3


def test_un_temoin_impossible_a_armer_ne_casse_pas_le_run(monkeypatch):
    """La règle, et elle vaut plus que le témoin lui-même.

    `faulthandler` écrit sur un descripteur de fichier. Quand `sys.stderr` n'en
    a pas — un harnais de test, un superviseur qui le détourne —, l'armement
    lève. Le run s'arrêtait alors à la **première** entrée, avec un message
    parlant de `fileno` : l'instrument mettait en échec ce qu'il observait.
    """
    def refuse(*a, **kw):
        raise OSError("pas de descripteur")

    monkeypatch.setattr(worker.faulthandler, "dump_traceback_later", refuse)
    monkeypatch.setattr(worker.faulthandler, "cancel_dump_traceback_later", refuse)

    api = FauxBanc([_entree(1), _entree(2)])
    worker.play_run({"id": 4, "stage": "READ", "items": 2}, api, _env_banc(), quiet=True)

    assert api.cloture and api.cloture["status"] == "DONE"
    assert api.cloture["items"] == 2
    assert len(api.rendus) == 2


def test_le_temoin_renonce_une_fois_pour_toutes(monkeypatch):
    """Une tentative, pas une par entrée : sinon on paye l'exception à chaque tour."""
    essais: list[int] = []

    def refuse(*a, **kw):
        essais.append(1)
        raise OSError("pas de descripteur")

    monkeypatch.setattr(worker.faulthandler, "dump_traceback_later", refuse)
    temoin = worker._Temoin()
    for _ in range(5):
        temoin.armer()
    assert essais == [1]
    assert temoin.possible is False


def test_chaque_entree_dit_ou_on_en_est(capsys):
    api = FauxBanc([_entree(1)])
    worker.play_run({"id": 2, "stage": "READ", "items": 160}, api, _env_banc(), quiet=False)
    sortie = capsys.readouterr().out
    # Le total vient du run : un compteur sans lui ne dit pas s'il reste dix
    # entrées ou cent.
    assert "1/160" in sortie
    assert EVENT_URL in sortie


def test_sans_total_le_compteur_reste_lisible(capsys):
    """Un run mis en file avant que le total voyage n'a pas la clé."""
    api = FauxBanc([_entree(1)])
    worker.play_run({"id": 3, "stage": "READ"}, api, _env_banc(), quiet=False)
    assert "  1 · " in capsys.readouterr().out


# ─────────────────── cent fois la même panne ne font pas cent renseignements
#
# Le premier run GLiNER : la bibliothèque n'était pas dans le venv du worker,
# les cent entrées ont rendu la même `ProviderError` en une minute, et le run
# s'est **clos en DONE** avec un taux calculé sur cent fiches vides. Rien, dans
# la console, ne le distinguait d'une mesure — et de l'extérieur, un worker
# revenu à sa veille ressemble exactement à un worker gelé.


class FauxBancEnPanne(FauxBanc):
    """Un banc dont chaque entrée revient en échec, toujours pour la même raison."""

    MOTIF = "ProviderError : le fournisseur « gliner » réclame la bibliothèque du même nom"

    def __init__(self, entrees):
        super().__init__(entrees)
        self.vus = 0

    def report_eval_read(self, run_id, result):
        self.vus += 1
        super().report_eval_read(run_id, result)


def test_une_brique_qui_ne_tourne_pas_arrete_le_run(monkeypatch):
    """Et le run échoue — il ne se clôt pas en DONE sur cent fiches vides."""
    monkeypatch.setattr(
        worker, "read_from_html", lambda *a, **kw: {"error": FauxBancEnPanne.MOTIF}
    )
    api = FauxBancEnPanne([_entree(i) for i in range(1, 21)])
    worker.play_run({"id": 30, "stage": "READ", "items": 20}, api, _env_banc(), quiet=True)

    assert api.cloture["status"] == "FAILED"
    # Le motif arrive entier : il porte d'ordinaire la commande à taper.
    assert "gliner" in api.cloture["error"]
    # Et surtout : on s'est arrêté au seuil, pas au bout du corpus.
    assert api.vus == worker.ECHECS_CONSECUTIFS_MAX
    assert api.cloture["items"] == worker.ECHECS_CONSECUTIFS_MAX


def test_un_echec_isole_ne_fait_pas_tomber_le_run(monkeypatch):
    """Une page qui échoue est une mesure : elle se range et le run continue.

    C'est tout l'intérêt de ne pas s'arrêter au premier accident, et c'est ce
    que le seuil doit préserver en coupant la panne répétée.
    """
    appels = {"n": 0}

    def lecture(*a, **kw):
        appels["n"] += 1
        # Une entrée sur trois échoue : jamais cinq d'affilée.
        return {"error": "boum"} if appels["n"] % 3 == 0 else {"text": "bonjour"}

    monkeypatch.setattr(worker, "read_from_html", lecture)
    api = FauxBanc([_entree(i) for i in range(1, 16)])
    worker.play_run({"id": 31, "stage": "READ", "items": 15}, api, _env_banc(), quiet=True)

    assert api.cloture["status"] == "DONE"
    assert api.cloture["items"] == 15


def test_le_compteur_d_echecs_se_remet_a_zero(monkeypatch):
    """Quatre échecs, une réussite, quatre échecs : ce n'est pas une panne."""
    suite = iter([True] * 4 + [False] + [True] * 4)

    monkeypatch.setattr(
        worker,
        "read_from_html",
        lambda *a, **kw: {"error": "boum"} if next(suite) else {"text": "ok"},
    )
    api = FauxBanc([_entree(i) for i in range(1, 10)])
    worker.play_run({"id": 32, "stage": "READ", "items": 9}, api, _env_banc(), quiet=True)

    assert api.cloture["status"] == "DONE"
    assert api.cloture["items"] == 9


def test_l_echec_d_une_entree_se_lit_dans_le_journal(capsys, monkeypatch):
    monkeypatch.setattr(worker, "read_from_html", lambda *a, **kw: {"error": "texte illisible"})
    api = FauxBanc([_entree(1)])
    worker.play_run({"id": 33, "stage": "READ", "items": 1}, api, _env_banc(), quiet=False)
    assert "texte illisible" in capsys.readouterr().out
