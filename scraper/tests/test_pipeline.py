"""Le pipeline complet, avec un fournisseur, un serveur web et une API simulés.

Aucun appel réseau : c'est l'enchaînement des cinq étapes qui est vérifié —
recherche, téléchargement, extraction des liens, sélection, fiche — puis le
filtrage, le géocodage et la soumission.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest

from sortiesbot.api import ApiError
from sortiesbot.config import Config
from sortiesbot.harvest import FetchError, Link
from sortiesbot.journal import RunLog
from sortiesbot.models import Agenda, ExtractedEvent, Usage
from sortiesbot.payload import Rejected
from sortiesbot.pipeline import resolve_category, run
from sortiesbot.store import SeenStore

DEMAIN = (date.today() + timedelta(days=1)).isoformat()
APRES = (date.today() + timedelta(days=3)).isoformat()

AGENDA_URL = "https://agenda.fr/jeune-public/"
EVENT_URL = "https://agenda.fr/jeune-public/vanves/le-chaperon.html"

AGENDA_HTML = f"""
<html><body>
  <nav><a href="/">Accueil</a></nav>
  <article><a href="{EVENT_URL}">Le Petit Chaperon rouge</a>
    <span>jusqu'au 30 septembre — Théâtre de Vanves</span></article>
</body></html>
"""

EVENT_HTML = """
<html><body><main>
<h1>Le Petit Chaperon rouge</h1>
<p>Spectacle de marionnettes pour les tout-petits, dès 3 ans, au Théâtre de
Vanves. Le Petit Chaperon rouge s'aventure dans la forêt, où l'attendent un
loup bavard et une grand-mère facétieuse. Une heure de rires et de frissons
doux, portée par trois marionnettistes et un accordéoniste.</p>
<p>Théâtre de Vanves, 12 rue des Lilas, 92170 Vanves. Tous les mercredis à
15 h, entrée libre dans la limite des places disponibles.</p>
</main></body></html>
"""


class FakeFetcher:
    """Serveur web scripté, sans réseau."""

    def __init__(self, pages: dict[str, str], failing: set[str] | None = None):
        self.pages = pages
        self.failing = failing or set()
        self.asked: list[str] = []

    def get_html(self, url: str) -> str:
        self.asked.append(url)
        if url in self.failing:
            raise FetchError("interdit par robots.txt")
        if url not in self.pages:
            raise FetchError("page inaccessible")
        return self.pages[url]


class FakeProvider:
    """Fournisseur scripté : des agendas, une sélection, des extractions."""

    name = "fake"

    def __init__(self, agendas, extractions, select_all=True):
        self.agendas = agendas
        self.extractions = extractions
        self.select_all = select_all
        self.usage = Usage(input_tokens=100, output_tokens=20)
        self.extracted: list[str] = []
        self.selected: list[str] = []

    def search(self, config, log):
        return list(self.agendas)

    def select(self, page, links, config, log):
        self.selected.append(page)
        return list(links) if self.select_all else []

    def extract(self, url, content, config, categories, log):
        self.extracted.append(url)
        return self.extractions[url]


class FakeApi:
    def __init__(self, categories=None, fail=False):
        self._categories = categories if categories is not None else {"Spectacle": 3, "Non classé": 9}
        self.fail = fail
        self.created: list[dict] = []

    def categories(self):
        return dict(self._categories)

    def create_event(self, payload, photo=None):
        if self.fail:
            raise ApiError("HTTP 400 — Titre trop court")
        self.created.append(payload)
        return {"id": 100 + len(self.created), "status": "PENDING"}


def sortie(**overrides) -> ExtractedEvent:
    base = dict(
        relevant=True,
        title="Le Petit Chaperon rouge",
        description="Un joli spectacle de marionnettes pour les tout-petits, au chaud.",
        free=True,
        date_start=DEMAIN,
        date_end=APRES,
        venue_name="Théâtre de Vanves",
        venue_address="12 rue des Lilas",
        venue_city="Vanves",
        category="Spectacle",
    )
    base.update(overrides)
    return ExtractedEvent(**base)


@pytest.fixture(autouse=True)
def geocodeur_simule(monkeypatch):
    """Photon répond « 92170 » pour tout, sans réseau."""
    from sortiesbot import geocode as geocoding

    monkeypatch.setattr(
        geocoding, "_search",
        lambda query: [{"properties": {"city": "Vanves", "postcode": "92170"},
                        "geometry": {"coordinates": [2.2896, 48.8226]}}],
    )


@pytest.fixture
def log():
    return RunLog(path=None, verbose=False, stream=io.StringIO())


def config(**overrides) -> Config:
    base = dict(name="test", theme="spectacles", blocked_domains=["facebook.com"])
    base.update(overrides)
    return Config(**base)


def standard(select_all=True):
    provider = FakeProvider(
        [Agenda(url=AGENDA_URL, title="Agenda 92")],
        {EVENT_URL: sortie()},
        select_all=select_all,
    )
    fetcher = FakeFetcher({AGENDA_URL: AGENDA_HTML, EVENT_URL: EVENT_HTML})
    return provider, fetcher


def test_chaine_complete_en_dry_run(log):
    provider, fetcher = standard()
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=False, fetcher=fetcher)
        # Rien n'est mémorisé tant que rien n'est soumis.
        assert store.count() == 0

    # L'agenda a été téléchargé, ses liens triés, la sortie lue.
    assert fetcher.asked == [AGENDA_URL, EVENT_URL]
    assert provider.selected == [AGENDA_URL]
    assert provider.extracted == [EVENT_URL]
    assert api.created == []
    assert result.summary.pages == 1
    assert result.summary.candidates == 1
    assert result.events[0]["payload"]["title"] == "Le Petit Chaperon rouge"
    assert result.events[0]["found_on"] == AGENDA_URL


def test_soumission_et_memoire(log):
    provider, fetcher = standard()
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)
        assert store.seen(EVENT_URL + "?utm_source=x")

    assert result.summary.submitted == 1
    assert api.created[0]["categoryId"] == 3
    assert api.created[0]["venue"]["postalCode"] == "92170"


def test_agenda_refuse_par_robots(log):
    provider, _ = standard()
    fetcher = FakeFetcher({}, failing={AGENDA_URL})
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log, submit=True, fetcher=fetcher)

    assert result.summary.candidates == 0
    assert provider.selected == []  # aucun appel payant sur une page inaccessible
    assert result.summary.pages == 0


def test_aucun_lien_retenu(log):
    provider, fetcher = standard(select_all=False)
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log, submit=True, fetcher=fetcher)

    assert result.summary.candidates == 0
    assert provider.extracted == []  # rien à extraire, donc rien à payer


def test_url_deja_vue_nest_pas_relue(log):
    provider, fetcher = standard()
    with SeenStore() as store:
        store.remember(EVENT_URL, "submitted")
        result = run(config(), provider, store, FakeApi(), log, submit=True, fetcher=fetcher)

    # Ni téléchargement de la page, ni appel au modèle : le filtre est en amont.
    assert EVENT_URL not in fetcher.asked
    assert provider.extracted == []
    assert result.summary.skipped_seen == 1


def test_page_de_sortie_inaccessible(log):
    provider, _ = standard()
    fetcher = FakeFetcher({AGENDA_URL: AGENDA_HTML}, failing={EVENT_URL})
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log, submit=True, fetcher=fetcher)

    assert provider.extracted == []
    assert result.summary.errors == 1


def test_page_hors_sujet(log):
    provider, fetcher = standard()
    provider.extractions[EVENT_URL] = ExtractedEvent(relevant=False, skip_reason="page de liste")
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log, submit=True, fetcher=fetcher)
        assert store.seen(EVENT_URL)
    assert result.summary.skipped_irrelevant == 1


def test_tarif_inconnu_est_soumis_a_completer(log):
    provider, fetcher = standard()
    provider.extractions[EVENT_URL] = sortie(free=False, price=None)
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert result.summary.unpriced == 1
    assert result.summary.submitted == 1
    assert api.created[0]["price"] == -1


def test_echec_de_geocodage_passe_en_zero(log, monkeypatch):
    from sortiesbot import geocode as geocoding

    monkeypatch.setattr(geocoding, "_search", lambda query: [])
    provider, fetcher = standard()
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert result.summary.ungeocoded == 1
    assert api.created[0]["venue"]["lat"] == 0


def test_erreur_api_est_comptee(log):
    provider, fetcher = standard()
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(fail=True), log, submit=True, fetcher=fetcher)
    assert result.summary.errors == 1
    assert result.summary.submitted == 0


def test_budget_ecourte_le_run(log):
    """Le plafond arrête les extractions, jamais la conservation de ce qui a
    déjà été trouvé et payé."""
    provider, fetcher = standard()
    provider.usage = Usage(cost_usd=1.20)
    with SeenStore() as store:
        result = run(config(max_cost_usd=0.50), provider, store, FakeApi(), log,
                     submit=True, fetcher=fetcher)

    assert provider.extracted == []
    assert result.summary.stopped_on_budget is True
    assert result.summary.candidates == 1
    assert result.candidates[0]["url"] == EVENT_URL


def test_categorie_inconnue_bascule_sur_le_defaut():
    categories = {"Spectacle": 3, "Non classé": 9}
    assert resolve_category("Ferme pédagogique", categories, "Non classé") == 9
    assert resolve_category("non classe", categories, "Non classé") == 9
    assert resolve_category("spectacle", categories, "Non classé") == 3


def test_categorie_defaut_absente_du_site():
    with pytest.raises(Rejected):
        resolve_category("Cirque", {"Spectacle": 3}, "Non classé")


def test_le_prompt_de_recherche_annonce_le_quota_reel():
    from sortiesbot.config import with_limit

    c = with_limit(Config(name="t", theme="x"), 3)
    assert f"Lance {c.max_searches} recherches" in c.render_search()
