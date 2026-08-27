"""Le pipeline complet, avec un fournisseur et une API simulés.

Aucun appel réseau : c'est l'enchaînement des étages qui est vérifié —
filtrage, extraction, géocodage, construction, mémoire des URLs.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest

from sortiesbot.api import ApiError
from sortiesbot.config import Config
from sortiesbot.journal import RunLog
from sortiesbot.models import Candidate, ExtractedEvent, Usage
from sortiesbot.pipeline import resolve_category, run
from sortiesbot.payload import Rejected
from sortiesbot.store import SeenStore

DEMAIN = (date.today() + timedelta(days=1)).isoformat()
APRES = (date.today() + timedelta(days=3)).isoformat()


class FakeProvider:
    """Fournisseur scripté : une liste de candidats, une extraction par URL."""

    name = "fake"

    def __init__(self, candidates, extractions):
        self.candidates = candidates
        self.extractions = extractions
        self.usage = Usage(input_tokens=100, output_tokens=20)
        self.extracted: list[str] = []

    def discover(self, config, log):
        return list(self.candidates)

    def extract(self, url, config, categories, log):
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
        title="Spectacle de marionnettes",
        description="Un joli spectacle de marionnettes pour les tout-petits, au chaud.",
        free=True,
        date_start=DEMAIN,
        date_end=APRES,
        venue_name="Théâtre du Parc",
        venue_address="12 rue des Lilas",
        venue_city="Paris",
        category="Spectacle",
    )
    base.update(overrides)
    return ExtractedEvent(**base)


@pytest.fixture(autouse=True)
def geocodeur_simule(monkeypatch):
    """Photon répond « 75001 » pour tout, sans réseau."""
    from sortiesbot import geocode as geocoding

    def fake_search(query):
        return [
            {
                "properties": {"city": "Paris", "postcode": "75001"},
                "geometry": {"coordinates": [2.3522, 48.8566]},
            }
        ]

    monkeypatch.setattr(geocoding, "_photon_search", fake_search)


@pytest.fixture
def log():
    return RunLog(path=None, verbose=False, stream=io.StringIO())


def config(**overrides) -> Config:
    base = dict(name="test", theme="spectacles", blocked_domains=["facebook.com"])
    base.update(overrides)
    return Config(**base)


def test_dry_run_ne_soumet_rien(log):
    provider = FakeProvider(
        [Candidate(url="https://exemple.fr/a", title="A")],
        {"https://exemple.fr/a": sortie()},
    )
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=False)
        # Une URL seulement retenue n'est pas mémorisée : le run suivant doit
        # pouvoir la soumettre pour de bon.
        assert store.count() == 0

    assert api.created == []
    assert result.summary.retained == 1
    assert result.summary.submitted == 0
    assert result.events[0]["payload"]["title"] == "Spectacle de marionnettes"


def test_soumission_et_memoire(log):
    provider = FakeProvider(
        [Candidate(url="https://exemple.fr/a", title="A")],
        {"https://exemple.fr/a": sortie()},
    )
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True)
        assert store.seen("https://exemple.fr/a?utm_source=x")

    assert result.summary.submitted == 1
    assert api.created[0]["categoryId"] == 3
    assert result.events[0]["event_id"] == 101


def test_url_deja_vue_nest_pas_relue(log):
    provider = FakeProvider(
        [Candidate(url="https://exemple.fr/a", title="A")],
        {"https://exemple.fr/a": sortie()},
    )
    with SeenStore() as store:
        store.remember("https://exemple.fr/a", "submitted")
        result = run(config(), provider, store, FakeApi(), log, submit=True)

    assert provider.extracted == []  # aucun jeton dépensé sur cette page
    assert result.summary.skipped_seen == 1


def test_domaine_bloque(log):
    provider = FakeProvider([Candidate(url="https://www.facebook.com/evt", title="A")], {})
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log, submit=True)
    assert result.summary.skipped_blocked == 1
    assert provider.extracted == []


def test_page_hors_sujet(log):
    provider = FakeProvider(
        [Candidate(url="https://exemple.fr/liste", title="Top 10")],
        {"https://exemple.fr/liste": ExtractedEvent(relevant=False, skip_reason="page de liste")},
    )
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log, submit=True)
        assert store.seen("https://exemple.fr/liste")
    assert result.summary.skipped_irrelevant == 1


def test_sortie_inexploitable_est_ecartee(log):
    provider = FakeProvider(
        [Candidate(url="https://exemple.fr/a", title="A")],
        {"https://exemple.fr/a": sortie(description="Court")},
    )
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log, submit=True)
    assert result.summary.skipped_invalid == 1
    assert result.summary.submitted == 0


def test_tarif_inconnu_est_soumis_a_completer(log):
    """Une sortie sans tarif est proposée quand même : c'est le modérateur qui
    tranche, le serveur refusant de l'approuver telle quelle."""
    provider = FakeProvider(
        [Candidate(url="https://exemple.fr/a", title="A")],
        {"https://exemple.fr/a": sortie(free=False, price=None)},
    )
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True)

    assert result.summary.unpriced == 1
    assert result.summary.submitted == 1
    assert api.created[0]["price"] == -1


def test_echec_de_geocodage_passe_en_zero(log, monkeypatch):
    from sortiesbot import geocode as geocoding

    monkeypatch.setattr(geocoding, "_photon_search", lambda query: [])
    provider = FakeProvider(
        [Candidate(url="https://exemple.fr/a", title="A")],
        {"https://exemple.fr/a": sortie()},
    )
    api = FakeApi()
    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True)

    assert result.summary.ungeocoded == 1
    assert api.created[0]["venue"]["lat"] == 0
    assert api.created[0]["venue"]["lng"] == 0


def test_geocodage_hors_zone_refuse(log, monkeypatch):
    from sortiesbot import geocode as geocoding

    monkeypatch.setattr(
        geocoding,
        "_photon_search",
        lambda query: [
            {
                "properties": {"city": "Lyon", "postcode": "69002"},
                "geometry": {"coordinates": [4.8357, 45.7640]},
            }
        ],
    )
    provider = FakeProvider(
        [Candidate(url="https://exemple.fr/a", title="A")],
        {"https://exemple.fr/a": sortie()},
    )
    api = FakeApi()
    with SeenStore() as store:
        run(config(), provider, store, api, log, submit=True)

    assert api.created[0]["venue"]["lat"] == 0


def test_erreur_api_est_comptee(log):
    provider = FakeProvider(
        [Candidate(url="https://exemple.fr/a", title="A")],
        {"https://exemple.fr/a": sortie()},
    )
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(fail=True), log, submit=True)
    assert result.summary.errors == 1
    assert result.summary.submitted == 0


def test_plafond_de_sorties(log):
    candidats = [Candidate(url=f"https://exemple.fr/{i}", title=str(i)) for i in range(5)]
    extractions = {c.url: sortie() for c in candidats}
    provider = FakeProvider(candidats, extractions)
    with SeenStore() as store:
        result = run(config(max_events=2), provider, store, FakeApi(), log, submit=True)
    assert result.summary.submitted == 2


def test_decouverte_vide_est_signalee():
    """Zéro candidat n'est pas un run réussi : il faut le dire, avec de quoi
    comprendre (combien de recherches, combien de pages vraiment lues)."""
    import io as _io

    stream = _io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    provider = FakeProvider([], {})
    provider.usage = Usage(web_searches=2, web_fetches=2, pages_read=1)

    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log, submit=False)

    assert result.summary.candidates == 0
    console = stream.getvalue()
    assert "aucun candidat retenu" in console
    assert "1 page(s) réellement lue(s)" in console


def test_budget_ecourte_le_run(log):
    """La découverte a coûté plus que le plafond : on n'enchaîne pas les
    extractions par-dessus — mais on garde ce qu'elle a trouvé, c'est payé."""
    candidats = [Candidate(url=f"https://exemple.fr/{i}", title=str(i)) for i in range(3)]
    provider = FakeProvider(candidats, {c.url: sortie() for c in candidats})
    provider.usage = Usage(input_tokens=0, output_tokens=0, cost_usd=1.20)

    with SeenStore() as store:
        result = run(config(max_cost_usd=0.50), provider, store, FakeApi(), log, submit=True)

    assert provider.extracted == []  # aucune page relue après le dépassement
    assert result.summary.stopped_on_budget is True
    assert result.summary.submitted == 0
    # Le résultat de la découverte survit : c'est l'étage le plus cher.
    assert result.summary.candidates == 3
    assert [c["url"] for c in result.candidates] == [c.url for c in candidats]


def test_limite_reduit_aussi_le_budget_de_recherche():
    """Un essai à trois sorties ne doit pas payer une découverte pleine taille."""
    from sortiesbot.config import with_limit

    complet = Config(name="t", theme="x")
    essai = with_limit(complet, 3)
    assert essai.max_events == 3
    assert essai.max_searches < complet.max_searches
    assert essai.max_fetches < complet.max_fetches
    assert essai.max_searches >= 2  # mais pas au point de ne rien chercher


def test_le_prompt_annonce_le_meme_quota_que_les_outils():
    """Le prompt et `max_uses` doivent dire la même chose : un prompt qui
    réclame six recherches alors que l'outil en autorise deux fait échouer
    les quatre dernières en `max_uses_exceeded`."""
    from sortiesbot.config import with_limit

    config = with_limit(Config(name="t", theme="x"), 3)
    rendu = config.render_discovery()
    assert f"lancer {config.max_searches} recherches" in rendu
    assert f"Ouvre-en jusqu'à\n   {config.max_fetches}" in rendu


def test_categorie_inconnue_bascule_sur_le_defaut():
    categories = {"Spectacle": 3, "Non classé": 9}
    assert resolve_category("Ferme pédagogique", categories, "Non classé") == 9
    # Insensible à la casse et aux accents.
    assert resolve_category("non classe", categories, "Non classé") == 9
    assert resolve_category("spectacle", categories, "Non classé") == 3


def test_categorie_defaut_absente_du_site():
    with pytest.raises(Rejected):
        resolve_category("Cirque", {"Spectacle": 3}, "Non classé")
