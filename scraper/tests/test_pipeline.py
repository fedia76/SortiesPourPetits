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
from sortiesbot.models import ExtractedEvent, FoundPage, Usage
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
  <main>
    <h1>Spectacles jeune public dans les Hauts-de-Seine</h1>
    <p>Retrouvez toute la programmation jeune public du département : théâtre,
    contes, marionnettes et spectacles musicaux, salle par salle et mois par
    mois. Les dates sont mises à jour chaque semaine par les salles
    partenaires.</p>
    <article><a href="{EVENT_URL}">Le Petit Chaperon rouge</a>
      <span>jusqu'au 30 septembre — Théâtre de Vanves</span></article>
  </main>
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
        # Le téléchargement de la photo réutilise la session du fetcher : sans
        # notre User-Agent, beaucoup de serveurs refusent l'image.
        self.session = object()

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
        [FoundPage(url=AGENDA_URL, title="Agenda 92")],
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


def test_agenda_dont_aucun_lien_nest_retenu_est_relu_comme_une_sortie(log):
    """Aucun lien retenu sur une vraie page d'agenda : plutôt que de repartir
    les mains vides, on lit la page — elle est déjà téléchargée. Elle sera
    écartée comme « pas une sortie » si c'en est bien une, pour 0,004 $."""
    provider, fetcher = standard(select_all=False)
    provider.extractions[AGENDA_URL] = ExtractedEvent(
        relevant=False, skip_reason="page de liste"
    )
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log, submit=True, fetcher=fetcher)

    assert provider.extracted == [AGENDA_URL]
    assert result.summary.skipped_irrelevant == 1
    assert result.summary.submitted == 0


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


def test_meme_sortie_sur_deux_agendas_nest_traitee_qu_une_fois(log):
    """Constaté : deux pages d'un même site listaient les mêmes spectacles,
    et chacun a été lu, extrait et retenu deux fois."""
    autre = "https://agenda.fr/spectacles/"
    provider = FakeProvider(
        [FoundPage(url=AGENDA_URL), FoundPage(url=autre)],
        {EVENT_URL: sortie()},
    )
    fetcher = FakeFetcher(
        {AGENDA_URL: AGENDA_HTML, autre: AGENDA_HTML, EVENT_URL: EVENT_HTML}
    )
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert result.summary.pages == 2  # les deux agendas sont bien dépouillés
    assert result.summary.duplicates == 1
    assert provider.extracted == [EVENT_URL]  # mais une seule extraction payée
    assert result.summary.submitted == 1


def test_sortie_hors_zone_est_gardee(log, monkeypatch):
    """Un spectacle à Chantilly (Oise) sort d'un run Île-de-France. Sa page a
    été lue et payée : la jeter reviendrait à payer pour rien, alors que le
    site filtre par distance et qu'un modérateur relit. Et le géocodeur ne
    doit plus refuser une position hors des départements visés."""
    from sortiesbot import geocode as geocoding

    monkeypatch.setattr(
        geocoding, "_search",
        lambda q: [{"properties": {"city": "Chantilly", "postcode": "60500",
                                   "countrycode": "FR"},
                    "geometry": {"coordinates": [2.4699, 49.1939]}}],
    )
    provider, fetcher = standard()
    provider.extractions[EVENT_URL] = sortie(
        venue_city="Chantilly", venue_postal_code="60500"
    )
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert result.summary.out_of_area == 1
    assert result.summary.submitted == 1
    assert api.created[0]["venue"]["postalCode"] == "60500"
    assert api.created[0]["venue"]["lat"] != 0  # géolocalisée, pas « à compléter »


def test_sortie_hors_zone_ecartee_si_le_run_est_strict(log):
    provider, fetcher = standard()
    provider.extractions[EVENT_URL] = sortie(
        venue_city="Chantilly", venue_postal_code="60500"
    )
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(keep_out_of_scope=False), provider, store, api, log,
                     submit=True, fetcher=fetcher)

    assert result.summary.out_of_area == 1
    assert api.created == []


def test_sortie_hors_periode_est_gardee(log):
    """Même raisonnement : un spectacle de décembre trouvé par un run « ce
    week-end » est déjà payé, et le site sait filtrer par date."""
    provider, fetcher = standard()
    loin = (date.today() + timedelta(days=120)).isoformat()
    provider.extractions[EVENT_URL] = sortie(date_start=loin, date_end=loin)
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(horizon_days=7), provider, store, api, log,
                     submit=True, fetcher=fetcher)

    assert result.summary.out_of_period == 1
    assert result.summary.submitted == 1
    assert api.created[0]["dateStart"] == loin


def test_sortie_hors_periode_ecartee_si_le_run_est_strict(log):
    provider, fetcher = standard()
    loin = (date.today() + timedelta(days=120)).isoformat()
    provider.extractions[EVENT_URL] = sortie(date_start=loin, date_end=loin)
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(horizon_days=7, keep_out_of_scope=False), provider, store,
                     api, log, submit=True, fetcher=fetcher)

    assert result.summary.out_of_period == 1
    assert api.created == []


def test_sortie_deja_terminee_reste_ecartee(log):
    """La souplesse s'arrête là : une sortie passée n'intéresse personne."""
    provider, fetcher = standard()
    passe = (date.today() - timedelta(days=10)).isoformat()
    provider.extractions[EVENT_URL] = sortie(date_start=passe, date_end=passe)
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert result.summary.skipped_invalid == 1
    assert api.created == []


def test_page_qui_nest_pas_une_sortie_reste_ecartee(log):
    """Et une page de liste ou de billetterie non plus : « hors fenêtre » et
    « pas une sortie » sont deux choses différentes."""
    provider, fetcher = standard()
    provider.extractions[EVENT_URL] = ExtractedEvent(
        relevant=False, skip_reason="page de billetterie"
    )
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert result.summary.skipped_irrelevant == 1
    assert api.created == []


def test_sortie_trouvee_directement_par_la_recherche(log):
    """Une recherche ne remonte pas que des agendas : elle tombe aussi sur la
    page d'une sortie. Elle était téléchargée, dépouillée de ses liens de
    navigation, puis perdue — jamais lue comme une sortie."""
    provider = FakeProvider(
        [FoundPage(url=EVENT_URL, title="Le Petit Chaperon rouge", kind="sortie")],
        {EVENT_URL: sortie()},
    )
    fetcher = FakeFetcher({EVENT_URL: EVENT_HTML})
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert provider.selected == []  # pas de tri de liens : ce n'est pas un agenda
    assert provider.extracted == [EVENT_URL]
    assert result.summary.submitted == 1


def test_agenda_sans_lien_retenu_est_relu_comme_une_sortie(log):
    """Filet de sécurité : si le modèle classe une sortie en « agenda », on ne
    doit pas la perdre. La page est déjà téléchargée."""
    provider = FakeProvider(
        [FoundPage(url=EVENT_URL, title="mal classée", kind="agenda")],
        {EVENT_URL: sortie()},
        select_all=False,
    )
    fetcher = FakeFetcher({EVENT_URL: EVENT_HTML})
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert provider.extracted == [EVENT_URL]
    assert result.summary.submitted == 1


def test_sortie_directe_deja_listee_par_un_agenda_nest_pas_doublee(log):
    provider = FakeProvider(
        [FoundPage(url=EVENT_URL, kind="sortie"), FoundPage(url=AGENDA_URL, kind="agenda")],
        {EVENT_URL: sortie()},
    )
    fetcher = FakeFetcher({AGENDA_URL: AGENDA_HTML, EVENT_URL: EVENT_HTML})
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert result.summary.duplicates == 1
    assert provider.extracted == [EVENT_URL]
    assert result.summary.submitted == 1


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


# --------------------------------------------------------------- calendrier
# Un spectacle joué tous les dimanches ne doit pas ressortir un jeudi. Rien
# n'en dépend encore : le pipeline calcule et journalise, on mesure.

DIMANCHE = "2026-07-05"
DERNIER_DIMANCHE = "2026-08-30"

EVENT_HTML_JSON_LD = (
    '<html><head><script type="application/ld+json">'
    '{"@type": "TheaterEvent", "name": "Le Petit Chaperon rouge",'
    ' "startDate": "2026-07-05T15:00:00+02:00",'
    ' "subEvent": [{"@type": "Event", "startDate": "2026-07-12"}]}'
    "</script></head><body>" + EVENT_HTML + "</body></html>"
)


def joue_le_dimanche(**overrides):
    return sortie(date_start=DIMANCHE, date_end=DERNIER_DIMANCHE, **overrides)


def run_avec(extraction, event_html=EVENT_HTML, log=None):
    provider = FakeProvider(
        [FoundPage(url=AGENDA_URL, title="Agenda 92")], {EVENT_URL: extraction}
    )
    fetcher = FakeFetcher({AGENDA_URL: AGENDA_HTML, EVENT_URL: event_html})
    with SeenStore() as store:
        return run(config(), provider, store, FakeApi(), log, submit=False, fetcher=fetcher)


def test_les_jours_de_representation_donnent_les_vraies_dates(log):
    result = run_avec(joue_le_dimanche(weekdays=("dimanche",)), log=log)

    calendrier = result.events[0]["schedule"]
    assert calendrier["source"] == "récurrence"
    assert calendrier["weekdays"] == ["dimanche"]
    assert "2026-08-13" not in calendrier["dates"]  # un jeudi d'août
    assert "2026-08-16" in calendrier["dates"]
    assert result.summary.scheduled == 1


def test_le_json_ld_de_la_page_prime(log):
    """Il est dans le HTML déjà téléchargé : ni requête, ni jeton, ni JavaScript."""
    result = run_avec(
        joue_le_dimanche(weekdays=("dimanche",)), event_html=EVENT_HTML_JSON_LD, log=log
    )

    calendrier = result.events[0]["schedule"]
    assert calendrier["source"] == "json-ld"
    assert calendrier["dates"] == ["2026-07-05", "2026-07-12"]


def test_sans_indication_le_comportement_ne_change_pas(log):
    result = run_avec(sortie(), log=log)

    assert result.events[0]["schedule"]["source"] == "plage"
    assert result.summary.scheduled == 0


def test_le_calendrier_est_journalise():
    journal = RunLog(path=None, verbose=True, stream=io.StringIO())
    run_avec(joue_le_dimanche(weekdays=("mercredi", "samedi")), log=journal)

    trace = journal.stream.getvalue()
    assert "🗓" in trace
    assert "mercredi, samedi" in trace


def test_les_jours_de_representation_partent_au_site(log):
    """Ce que le site reçoit, et sur quoi sa recherche s'appuiera."""
    provider = FakeProvider(
        [FoundPage(url=AGENDA_URL, title="Agenda 92")],
        {EVENT_URL: joue_le_dimanche(weekdays=("dimanche",))},
    )
    fetcher = FakeFetcher({AGENDA_URL: AGENDA_HTML, EVENT_URL: EVENT_HTML})
    api = FakeApi()
    with SeenStore() as store:
        run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    envoye = api.created[0]
    assert envoye["dateStart"] == DIMANCHE
    assert envoye["dateEnd"] == DERNIER_DIMANCHE
    assert envoye["dates"][0] == DIMANCHE
    assert "2026-08-13" not in envoye["dates"]  # un jeudi


def test_une_sortie_sans_jours_connus_nenvoie_aucune_date(log):
    """Liste vide = tous les jours de la période, comme avant cette table."""
    provider, fetcher = standard()
    api = FakeApi()
    with SeenStore() as store:
        run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert api.created[0]["dates"] == []


# ------------------------------------------------------------------ la photo
#
# Le modèle ne voit que le texte de la page : il ne pouvait donc jamais donner
# l'URL d'une image, et toutes les sorties importées arrivaient sans photo.

PAGE_ILLUSTREE = EVENT_HTML.replace(
    "<html><body>",
    '<html><head><meta property="og:image" content="/media/chaperon.jpg"></head><body>',
)


def test_l_image_de_la_page_est_relevee_et_telechargee(log, monkeypatch):
    telecharge = {}

    def faux_download(url, session=None):
        telecharge["url"] = url
        telecharge["session"] = session
        return ("chaperon.jpg", b"\xff\xd8\xff-des-octets", "image/jpeg")

    monkeypatch.setattr("sortiesbot.pipeline.download", faux_download)

    provider = FakeProvider([FoundPage(url=AGENDA_URL, title="Agenda 92")], {EVENT_URL: sortie()})
    fetcher = FakeFetcher({AGENDA_URL: AGENDA_HTML, EVENT_URL: PAGE_ILLUSTREE})
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert telecharge["url"] == "https://agenda.fr/media/chaperon.jpg"
    assert telecharge["session"] is fetcher.session
    assert result.events[0]["photo_url"] == "https://agenda.fr/media/chaperon.jpg"


def test_une_page_sans_image_se_soumet_quand_meme(log):
    provider, fetcher = standard()
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert result.summary.submitted == 1
    assert result.events[0]["photo_url"] == ""
