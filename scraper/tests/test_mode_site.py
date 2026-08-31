"""Le mode « site » : partir d'une adresse connue, sans chercher.

Deux formes de site, et le pipeline doit s'accommoder des deux sans qu'on ait
à les déclarer :

* un site qui a **une page par sortie** — on dépouille ses liens, exactement
  comme un agenda trouvé par une recherche ;
* un site **d'une seule page** — le programme d'un festival, où les entrées
  ne sont reliées que par des ancres. On en tire alors plusieurs sorties d'un
  coup.

Ce qui est vérifié ici en plus de l'enchaînement : qu'aucune recherche web
n'est lancée, et que la mémoire porte sur les sorties et non sur la page —
sans quoi un programme lu une fois ne serait plus jamais relu, et tout ce
qu'il annoncerait ensuite serait perdu.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest

from sortiesbot.config import Config, ConfigError, validated
from sortiesbot.journal import RunLog
from sortiesbot.models import ExtractedEvent, Usage
from sortiesbot.pipeline import run
from sortiesbot.store import SeenStore, event_key

from test_pipeline import FakeApi, FakeFetcher

DEMAIN = (date.today() + timedelta(days=1)).isoformat()
APRES = (date.today() + timedelta(days=3)).isoformat()

FESTIVAL_URL = "https://formulabula.fr/"
FICHE_URL = "https://formulabula.fr/programme/atelier-bd.html"

#: Un festival d'une seule page : les entrées ne sont reliées que par des
#: ancres, que `links_of` écarte. Aucun lien à suivre, donc.
UNE_SEULE_PAGE = """
<html><head><meta property="og:image" content="https://formulabula.fr/affiche.jpg"></head>
<body><main>
<h1>Formula Bula 2026</h1>
<p>Le festival de bande dessinée revient pour sa quatorzième édition, du
vendredi au dimanche, à la Halle des Blancs Manteaux, 48 rue Vieille du
Temple, 75004 Paris. Trois jours de dessin, de lectures et d'ateliers, en
entrée libre.</p>
<h2><a href="#atelier">Atelier BD à quatre mains</a></h2>
<p>Un atelier de dessin pour les enfants dès 6 ans, animé par les auteurs
invités du festival. Chaque binôme repart avec sa planche.</p>
<h2><a href="#lecture">Lecture dessinée pour les tout-petits</a></h2>
<p>Une lecture en musique, dessinée en direct, pour les 3 à 6 ans.</p>
</main></body></html>
"""

#: Un site classique : une page de programme qui renvoie vers des fiches.
PAGE_DE_LIENS = f"""
<html><body><main>
<h1>Le programme du festival</h1>
<p>Toutes les rencontres, ateliers et lectures de cette quatorzième édition,
jour par jour, à la Halle des Blancs Manteaux.</p>
<article><a href="{FICHE_URL}">Atelier BD à quatre mains</a>
  <span>samedi 14 h — dès 6 ans</span></article>
</main></body></html>
"""

FICHE_HTML = """
<html><body><main>
<h1>Atelier BD à quatre mains</h1>
<p>Un atelier de dessin pour les enfants dès 6 ans, animé par les auteurs
invités du festival. Chaque binôme repart avec sa planche imprimée sur place.
Le matériel est fourni, il suffit de venir avec ses idées.</p>
<p>Halle des Blancs Manteaux, 48 rue Vieille du Temple, 75004 Paris. Entrée
libre dans la limite des places disponibles.</p>
</main></body></html>
"""


def sortie(titre: str, **extra) -> ExtractedEvent:
    champs = dict(
        relevant=True,
        title=titre,
        description="Un atelier de dessin pour les enfants, animé par les auteurs du festival.",
        free=True,
        date_start=DEMAIN,
        date_end=APRES,
        category="Spectacle",
        venue_name="Halle des Blancs Manteaux",
        venue_address="48 rue Vieille du Temple",
        venue_city="Paris",
        venue_postal_code="75004",
    )
    champs.update(extra)
    return ExtractedEvent(**champs)


class SiteProvider:
    """Fournisseur scripté qui refuse de chercher.

    C'est la vérification la plus importante du mode : une recherche lancée
    est une recherche facturée, et l'adresse est déjà connue.
    """

    name = "fake-site"

    def __init__(self, extractions, select_all=True):
        self.extractions = extractions
        self.select_all = select_all
        self.usage = Usage(input_tokens=100, output_tokens=20)
        self.extracted: list[tuple[str, bool]] = []

    def search(self, config, log):
        raise AssertionError("le mode « site » ne doit lancer aucune recherche web")

    def select(self, page, links, config, log):
        return list(links) if self.select_all else []

    def extract(self, url, content, config, categories, log, *, multiple=False):
        self.extracted.append((url, multiple))
        found = self.extractions[url]
        return list(found) if isinstance(found, list) else [found]


@pytest.fixture
def log():
    return RunLog(None, verbose=False, stream=io.StringIO())


@pytest.fixture(autouse=True)
def photo_hors_ligne(monkeypatch):
    """La page du festival annonce une affiche : personne ne la télécharge ici."""
    monkeypatch.setattr(
        "sortiesbot.stages.publication.download",
        lambda url, session=None: ("affiche.jpg", b"\xff\xd8\xff-des-octets", "image/jpeg"),
    )


def config(**extra) -> Config:
    champs = dict(
        name="formula-bula",
        theme="les rendez-vous jeune public d'un festival de bande dessinée",
        mode="site",
        seed_urls=[FESTIVAL_URL],
        postal_prefixes=["75", "92"],
    )
    champs.update(extra)
    return validated(Config(**champs))


def lance(conf, provider, fetcher, store, api, log, submit=True):
    return run(conf, provider, store, api, log, submit=submit, fetcher=fetcher)


# ------------------------------------------------------- site d'une seule page


def test_une_page_unique_donne_toutes_ses_sorties(log):
    """Le cas qui motivait tout : un festival dont le programme tient sur une
    page, et dont on veut les vingt sorties — pas une."""
    provider = SiteProvider(
        {FESTIVAL_URL: [sortie("Atelier BD à quatre mains"), sortie("Lecture dessinée")]}
    )
    fetcher = FakeFetcher({FESTIVAL_URL: UNE_SEULE_PAGE})
    api = FakeApi()
    with SeenStore() as store:
        result = lance(config(), provider, fetcher, store, api, log)

    # La page n'ayant aucun lien à suivre, elle est lue comme un programme.
    assert provider.extracted == [(FESTIVAL_URL, True)]
    assert result.summary.submitted == 2
    assert [e["payload"]["title"] for e in result.events] == [
        "Atelier BD à quatre mains",
        "Lecture dessinée",
    ]


def test_les_sorties_dun_programme_partagent_lillustration_de_la_page(log):
    provider = SiteProvider({FESTIVAL_URL: [sortie("Atelier BD"), sortie("Lecture")]})
    fetcher = FakeFetcher({FESTIVAL_URL: UNE_SEULE_PAGE})
    with SeenStore() as store:
        result = lance(config(), provider, fetcher, store, FakeApi(), log)

    assert {e["photo_url"] for e in result.events} == {"https://formulabula.fr/affiche.jpg"}


def test_un_programme_sans_sortie_exploitable_est_ecarte(log):
    provider = SiteProvider(
        {FESTIVAL_URL: [ExtractedEvent(relevant=False, skip_reason="page d'accueil")]}
    )
    fetcher = FakeFetcher({FESTIVAL_URL: UNE_SEULE_PAGE})
    with SeenStore() as store:
        result = lance(config(), provider, fetcher, store, FakeApi(), log)

    assert result.events == []
    assert result.summary.skipped_irrelevant == 1


def test_le_plafond_de_sorties_sapplique_a_un_programme(log):
    provider = SiteProvider({FESTIVAL_URL: [sortie(f"Atelier {i}") for i in range(5)]})
    fetcher = FakeFetcher({FESTIVAL_URL: UNE_SEULE_PAGE})
    with SeenStore() as store:
        result = lance(config(max_events=2), provider, fetcher, store, FakeApi(), log)

    assert result.summary.submitted == 2


# ------------------------------------------------------ site à une page par sortie


def test_un_site_qui_a_une_page_par_sortie_est_depouille_comme_un_agenda(log):
    provider = SiteProvider({FICHE_URL: sortie("Atelier BD à quatre mains")})
    fetcher = FakeFetcher({FESTIVAL_URL: PAGE_DE_LIENS, FICHE_URL: FICHE_HTML})
    with SeenStore() as store:
        result = lance(config(), provider, fetcher, store, FakeApi(), log)

    # La fiche est lue seule, comme n'importe quelle page de sortie : pas
    # d'extraction multiple là où il n'y a qu'une sortie.
    assert provider.extracted == [(FICHE_URL, False)]
    assert result.summary.submitted == 1


def test_le_nombre_de_pages_de_depart_est_plafonne(log):
    """Le même réglage que les agendas d'une recherche : la console le
    présente sous les deux noms, il doit valoir dans les deux cas."""
    autre = "https://formulabula.fr/archives/"
    provider = SiteProvider(
        {FESTIVAL_URL: [sortie("Atelier BD")], autre: [sortie("Vieille expo")]}
    )
    fetcher = FakeFetcher({FESTIVAL_URL: UNE_SEULE_PAGE, autre: UNE_SEULE_PAGE})
    with SeenStore() as store:
        conf = config(seed_urls=[FESTIVAL_URL, autre], max_agendas=1)
        result = lance(conf, provider, fetcher, store, FakeApi(), log)

    assert provider.extracted == [(FESTIVAL_URL, True)]
    assert result.summary.submitted == 1


# ---------------------------------------------------------------- la mémoire


def test_le_programme_est_relu_mais_ses_sorties_ne_sont_pas_redoublees(log):
    """Le point délicat du mode : mémoriser la page interdirait d'y revenir,
    et un festival ajoute des dates jusqu'au dernier moment."""
    fetcher = FakeFetcher({FESTIVAL_URL: UNE_SEULE_PAGE})
    api = FakeApi()
    with SeenStore() as store:
        premier = SiteProvider({FESTIVAL_URL: [sortie("Atelier BD"), sortie("Lecture")]})
        lance(config(), premier, fetcher, store, api, log)

        # Deuxième run : le programme s'est étoffé d'une sortie.
        second = SiteProvider(
            {FESTIVAL_URL: [sortie("Atelier BD"), sortie("Lecture"), sortie("Dédicaces")]}
        )
        result = lance(config(), second, fetcher, store, api, log)

    # La page a bien été relue…
    assert second.extracted == [(FESTIVAL_URL, True)]
    # …mais seule la nouveauté est proposée.
    assert [e["payload"]["title"] for e in result.events] == ["Dédicaces"]
    assert [p["title"] for p in api.created] == ["Atelier BD", "Lecture", "Dédicaces"]


def test_deux_fois_la_meme_sortie_dans_un_run_ne_compte_quune_fois(log):
    provider = SiteProvider(
        {FESTIVAL_URL: [sortie("Atelier BD"), sortie("Atelier BD"), sortie("Lecture")]}
    )
    fetcher = FakeFetcher({FESTIVAL_URL: UNE_SEULE_PAGE})
    with SeenStore() as store:
        result = lance(config(), provider, fetcher, store, FakeApi(), log)

    assert [e["payload"]["title"] for e in result.events] == ["Atelier BD", "Lecture"]
    assert result.summary.duplicates == 1


def test_un_essai_ne_memorise_rien(log):
    """Sinon le run réel qui suit sauterait les sorties que l'essai a repérées."""
    fetcher = FakeFetcher({FESTIVAL_URL: UNE_SEULE_PAGE})
    with SeenStore() as store:
        essai = SiteProvider({FESTIVAL_URL: [sortie("Atelier BD")]})
        lance(config(), essai, fetcher, store, FakeApi(), log, submit=False)

        reel = SiteProvider({FESTIVAL_URL: [sortie("Atelier BD")]})
        result = lance(config(), reel, fetcher, store, FakeApi(), log, submit=True)

    assert result.summary.submitted == 1


def test_la_cle_dune_sortie_distingue_les_titres_pas_les_graphies():
    meme = {
        event_key(FESTIVAL_URL, "Atelier BD à 4 mains"),
        event_key(FESTIVAL_URL, "  atelier bd a 4 mains  "),
    }
    assert len(meme) == 1
    assert event_key(FESTIVAL_URL, "Atelier BD") != event_key(FESTIVAL_URL, "Lecture")
    # La clé reste sous la limite de la colonne du site (VARCHAR(500)).
    assert len(event_key(FESTIVAL_URL, "x" * 900)) <= 500


# -------------------------------------------------------------- configuration


def test_le_mode_site_reclame_une_url():
    with pytest.raises(ConfigError, match="au moins une URL"):
        validated(Config(name="f", theme="un festival", mode="site"))


def test_une_url_de_depart_doit_etre_une_url():
    with pytest.raises(ConfigError, match="URL de départ invalide"):
        validated(Config(name="f", theme="un festival", mode="site", seed_urls=["formulabula.fr"]))


def test_un_mode_inconnu_est_refuse():
    with pytest.raises(ConfigError, match="mode inconnu"):
        validated(Config(name="f", theme="un festival", mode="siteweb"))


def test_le_mode_par_defaut_reste_la_recherche():
    assert Config(name="f", theme="x").mode == "recherche"
    assert not Config(name="f", theme="x").targets_site
