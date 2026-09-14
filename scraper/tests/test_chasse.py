"""La chasse : peupler le corpus de l'étage 2 sans le remplir de soi-même.

Une chasse lance les recherches de l'étage 1, ouvre ce qu'elles remontent, et
précoche chaque page avec ce que l'étage 2 en dit. C'est le principe qui vaut
déjà pour les liens d'un agenda — « la brique précoche, l'humain corrige » —
appliqué un étage plus haut, et il y arrive avec un danger de plus.

Ce que ces tests verrouillent :

1. **C'est bien l'étage 2, pas une seconde implémentation.** `classify` et
   `digest` sont importés tels quels, et le recours au modèle se déclenche là
   où `stages/identification.py` le déclenche : quand les quatre signaux
   gratuits se taisent, et nulle part ailleurs.
2. **Un indécis ne propose rien.** Le pipeline traite « inconnu » en agenda —
   et il a raison, l'erreur n'y est pas symétrique —, mais c'est une décision
   d'orchestration. La recopier dans la précoche ferait entrer au corpus ce
   que le pipeline *fait* au lieu de ce que la page *est*, c'est-à-dire
   exactement ce que la mesure cherche. Un corpus rempli comme ça noterait
   l'étage 2 sur sa propre copie.
3. **Une page injoignable n'est pas perdue.** Elle revient sans archive et
   sans précoche : l'adresse vaut d'être vue, et un accident du web ne doit
   pas effacer le travail de la recherche.
4. **Le HTML est gelé au passage.** Sans lui, la page qu'un run rejouera plus
   tard ne serait pas celle sur laquelle la précoche a été faite.
"""

from __future__ import annotations

import base64
import gzip
from pathlib import Path

import pytest
from test_pipeline import FakeFetcher

from sortiesbot.chasse import hunt, hunt_page
from sortiesbot.config import Config
from sortiesbot.journal import RunLog
from sortiesbot.models import FoundPage
from sortiesbot.providers.base import ProviderError

PAGES = Path(__file__).parent / "fixtures" / "pages"

AGENDA_URL = "https://agenda.exemple-departement.fr/agenda/"
AGENDA_HTML = (PAGES / "agenda-departemental.html").read_text(encoding="utf-8")

FICHE_URL = "https://theatre-du-chapiteau.exemple.fr/saison/le-petit-prince"
FICHE_HTML = (PAGES / "spectacle-avec-json-ld.html").read_text(encoding="utf-8")

#: Ni pagination, ni JSON-LD, ni `og:type` : la seule du jeu qui fasse appeler
#: le modèle. C'est aussi la seule qui puisse rester sans précoche.
MUETTE_URL = "https://www.ville-exemple.fr/culture/atelier-cirque-en-famille"
MUETTE_HTML = (PAGES / "atelier-sans-donnees-structurees.html").read_text(encoding="utf-8")


class Moteur:
    """Un fournisseur scripté : des résultats, et un avis quand on le demande."""

    name = "faux"

    def __init__(self, pages: list[FoundPage], verdicts=None, queries=None, boom=False):
        self.pages = pages
        self.verdicts = list(verdicts or [])
        self._queries = queries
        self.boom = boom
        self.demandes: list[str] = []
        self.recherches: list[list[str]] = []

    def queries(self, config, log):
        return list(self._queries) if self._queries is not None else ["une requête formulée"]

    def search(self, queries, config, log):
        self.recherches.append(list(queries))
        return list(self.pages)

    def classify(self, digest, config, log):
        self.demandes.append(digest)
        if self.boom:
            raise ProviderError("le modèle n'a pas répondu")
        return self.verdicts.pop(0) if self.verdicts else ("inconnu", "condensé muet")


def config(**overrides) -> Config:
    base = dict(name="chasse", theme="sorties enfants", max_agendas=10)
    base.update(overrides)
    return Config(**base)


@pytest.fixture
def log() -> RunLog:
    return RunLog(None, verbose=False)


# ═════════════════════════════════════ ce que la chasse rend, page par page


def test_une_fiche_est_precochee_sortie(log):
    """Le JSON-LD déclare un seul événement : la cascade suffit, et rien n'est
    demandé à personne."""
    moteur = Moteur([FoundPage(url=FICHE_URL, title="Le Petit Prince", query="q")])
    found = hunt(config(), moteur, log, fetcher=FakeFetcher({FICHE_URL: FICHE_HTML}))

    page = found["pages"][0]
    assert page["nature"] == "sortie"
    assert page["signal"] == "json-ld"
    assert page["asked"] == ""
    assert moteur.demandes == []


def test_un_agenda_est_precoche_agenda(log):
    moteur = Moteur([FoundPage(url=AGENDA_URL, title="L'agenda", query="q")])
    found = hunt(config(), moteur, log, fetcher=FakeFetcher({AGENDA_URL: AGENDA_HTML}))

    page = found["pages"][0]
    assert page["nature"] == "agenda"
    assert page["confidence"] == "certain"
    # Le condensé part avec, pour juger sans rouvrir la page.
    assert page["links"] > 0
    assert page["heading"]


def test_le_html_part_gele_avec_la_precoche(log):
    """Sans archive, la page qu'un run rejouera ne serait pas celle-ci."""
    moteur = Moteur([FoundPage(url=FICHE_URL)])
    found = hunt(config(), moteur, log, fetcher=FakeFetcher({FICHE_URL: FICHE_HTML}))

    packed = found["pages"][0]["html"]
    assert gzip.decompress(base64.b64decode(packed)).decode("utf-8") == FICHE_HTML
    assert found["pages"][0]["chars"] == len(FICHE_HTML)


# ═══════════════════════════════════════ l'indécis, et ce qu'il ne devient pas


def test_le_modele_est_appele_quand_les_signaux_se_taisent(log):
    """Le cinquième signal, exactement là où l'étage 2 l'appelle."""
    moteur = Moteur([FoundPage(url=MUETTE_URL)], verdicts=[("sortie", "un atelier daté")])
    found = hunt(config(), moteur, log, fetcher=FakeFetcher({MUETTE_URL: MUETTE_HTML}))

    page = found["pages"][0]
    assert len(moteur.demandes) == 1
    assert page["nature"] == "sortie"
    assert page["signal"] == "modele"
    assert page["asked"] == config().classify_model


def test_un_indecis_ne_propose_rien(log):
    """La règle dont tout le reste dépend.

    Le modèle répond « inconnu », et le pipeline en ferait un agenda. La
    précoche, elle, reste vide : mettre « agenda » ici écrirait au corpus le
    repli du pipeline, et la mesure de l'étage 2 vérifierait ensuite que
    l'étage 2 fait ce qu'il fait.
    """
    moteur = Moteur([FoundPage(url=MUETTE_URL)], verdicts=[("inconnu", "rien à en tirer")])
    found = hunt(config(), moteur, log, fetcher=FakeFetcher({MUETTE_URL: MUETTE_HTML}))

    assert found["pages"][0]["nature"] == ""


def test_un_modele_muet_laisse_la_page_indecise(log):
    """Son échec ne coûte rien : la page attendra un humain, comme prévu."""
    moteur = Moteur([FoundPage(url=MUETTE_URL)], boom=True)
    found = hunt(config(), moteur, log, fetcher=FakeFetcher({MUETTE_URL: MUETTE_HTML}))

    assert found["pages"][0]["nature"] == ""
    assert found["pages"][0]["signal"] == "aucun"


def test_sans_modele_declare_personne_nest_interroge(log):
    moteur = Moteur([FoundPage(url=MUETTE_URL)])
    found = hunt(
        config(classify_model=""), moteur, log, fetcher=FakeFetcher({MUETTE_URL: MUETTE_HTML})
    )

    assert moteur.demandes == []
    assert found["pages"][0]["nature"] == ""


# ══════════════════════════════════════════════ ce que le web fait échouer


def test_une_page_injoignable_revient_quand_meme(log):
    """Sans archive et sans précoche — mais elle revient.

    La perdre reviendrait à perdre le travail de la recherche pour un accident
    du web, et l'adresse vaut d'être vue par un humain.
    """
    moteur = Moteur([FoundPage(url=FICHE_URL, title="Le Petit Prince")])
    found = hunt(config(), moteur, log, fetcher=FakeFetcher({}))

    page = found["pages"][0]
    assert page["error"]
    assert "html" not in page
    assert page.get("nature", "") == ""
    # Le titre de la recherche survit : c'est tout ce qu'on sait d'elle.
    assert page["title"] == "Le Petit Prince"


# ═══════════════════════════════════════════════ les requêtes et le plafond


def test_les_requetes_imposees_partent_telles_quelles(log):
    moteur = Moteur([])
    found = hunt(config(queries=["une", "deux"]), moteur, log, fetcher=FakeFetcher({}))

    assert found["queries"] == ["une", "deux"]
    assert moteur.recherches == [["une", "deux"]]


def test_sans_requetes_imposees_le_modele_les_formule(log):
    moteur = Moteur([], queries=["ce que le modèle propose"])
    found = hunt(config(), moteur, log, fetcher=FakeFetcher({}))

    # Rendues à la clôture : une chasse qui tait ses requêtes ne se rejoue pas.
    assert found["queries"] == ["ce que le modèle propose"]


def test_le_plafond_compte_ce_quil_laisse(log):
    """Ce qui dépasse est compté, pas tu.

    « Tous les liens de la recherche » serait une promesse à moitié tenue si
    personne ne savait de quelle moitié.
    """
    moteur = Moteur([FoundPage(url=FICHE_URL), FoundPage(url=AGENDA_URL)])
    found = hunt(
        config(max_agendas=1),
        moteur,
        log,
        fetcher=FakeFetcher({FICHE_URL: FICHE_HTML, AGENDA_URL: AGENDA_HTML}),
    )

    assert len(found["pages"]) == 1
    assert found["overCap"] == 1


# ═══════════════════════════════════════════════════ l'échange de langue


def test_la_page_reconnue_est_la_jumelle_francaise(log, monkeypatch):
    """C'est l'étage 2 qui échange la langue, et c'est la page échangée qui
    entre au corpus : un agenda anglais ne mène qu'à des fiches anglaises."""
    anglaise = "https://exemple.fr/en/whats-on"
    francaise = "https://exemple.fr/fr/agenda"
    monkeypatch.setattr(
        "sortiesbot.chasse.french_version",
        lambda url, html, fetcher, log=None: (francaise, AGENDA_HTML),
    )
    page = hunt_page(
        FoundPage(url=anglaise),
        config(),
        Moteur([]),
        log,
        fetcher=FakeFetcher({anglaise: "<html></html>"}),
    )

    assert page["url"] == francaise
    assert page["foundUrl"] == anglaise
