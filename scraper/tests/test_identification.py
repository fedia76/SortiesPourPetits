"""L'étage 2 : constater ce qu'est une page, et l'aiguiller en conséquence.

C'est le premier étage à **décider** quelque chose à partir du HTML. Deux
choses se vérifient ici :

* l'aiguillage — un agenda descend au dépouillement, une sortie saute
  directement à la lecture ;
* le biais assumé — une page qu'on ne sait pas reconnaître part en agenda,
  parce que l'erreur n'y est pas symétrique.

Le recours au modèle n'intervient qu'après le silence des quatre signaux
gratuits, et son échec ne coûte rien : « inconnu » a déjà un comportement.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from sortiesbot.journal import RunLog
from sortiesbot.ledger import Ledger
from sortiesbot.models import FoundPage
from sortiesbot.orchestrator import run
from sortiesbot.providers.base import ProviderError
from sortiesbot.store import SeenStore

from test_pipeline import FakeApi, FakeFetcher, FakeProvider, config, sortie

PAGES = Path(__file__).parent / "fixtures" / "pages"

AGENDA_URL = "https://agenda.exemple-departement.fr/agenda/"
AGENDA_HTML = (PAGES / "agenda-departemental.html").read_text(encoding="utf-8")

FICHE_URL = "https://theatre-du-chapiteau.exemple.fr/saison/le-petit-prince"
FICHE_HTML = (PAGES / "spectacle-avec-json-ld.html").read_text(encoding="utf-8")

#: Ni pagination, ni JSON-LD, ni `og:type` : la seule du jeu qui fasse appeler
#: le modèle.
MUETTE_URL = "https://www.ville-exemple.fr/culture/atelier-cirque-en-famille"
MUETTE_HTML = (PAGES / "atelier-sans-donnees-structurees.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def photo_hors_ligne(monkeypatch):
    """Les pages annoncent une illustration : personne ne la télécharge ici."""
    monkeypatch.setattr(
        "sortiesbot.stages.publication.download",
        lambda url, session=None: ("affiche.jpg", b"\xff\xd8\xff-des-octets", "image/jpeg"),
    )


@pytest.fixture(autouse=True)
def geocodeur_simule(monkeypatch):
    from sortiesbot import geocode as geocoding

    monkeypatch.setattr(
        geocoding, "_search",
        lambda query: [{"properties": {"city": "Vanves", "postcode": "92170"},
                        "geometry": {"coordinates": [2.2896, 48.8226]}}],
    )


@pytest.fixture
def journal():
    events: list[dict] = []
    return RunLog(path=None, verbose=False, stream=io.StringIO(), sink=events.append), events


def kinds(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e["kind"] == kind]


def lance(log, url, html, verdicts=None, ledger=None, extra=None, **conf):
    provider = FakeProvider(
        [FoundPage(url=url, title="Une page")],
        {url: sortie(), **(extra or {})},
        select_all=False,
    )
    provider.verdicts = list(verdicts or [])
    with SeenStore() as store:
        result = run(config(**conf), provider, store, FakeApi(), log,
                     fetcher=FakeFetcher({url: html}), ledger=ledger)
    return provider, result


# ══════════════════════════════════════════════════════════════ l'aiguillage


def test_une_fiche_saute_le_depouillement_et_le_tri(journal):
    """Elle déclare un seul spectacle : inutile d'y chercher des liens."""
    log, events = journal
    provider, result = lance(log, FICHE_URL, FICHE_HTML)

    assert provider.selected == [], "aucun tri : ce n'est pas une liste"
    assert provider.extracted == [FICHE_URL], "elle part droit à la lecture"
    assert kinds(events, "identified")[0]["nature"] == "sortie"


def test_un_agenda_descend_au_depouillement(journal):
    """Sa pagination le trahit, et ses liens partent au tri."""
    log, events = journal
    provider, _ = lance(log, AGENDA_URL, AGENDA_HTML, extra={AGENDA_URL: sortie(relevant=False)})

    assert provider.selected == [AGENDA_URL], "il est bien passé par le tri"
    constat = kinds(events, "identified")[0]
    assert (constat["nature"], constat["signal"]) == ("agenda", "pagination")


def test_une_page_indecise_part_en_agenda(journal):
    """Le biais assumé : l'erreur n'est pas symétrique.

    Prendre une sortie pour un agenda coûte un tri, et le filet la relit.
    Prendre un agenda pour une sortie coûte tous ses liens, sans rattrapage.
    """
    log, events = journal
    provider, _ = lance(log, MUETTE_URL, MUETTE_HTML, classify_model="")

    assert kinds(events, "identified")[0]["nature"] == "agenda"
    # Elle descend donc au dépouillement, qui ne tire aucun lien de cette
    # fiche — le tri n'est même pas appelé — et le filet la relit pour
    # elle-même. La page est traitée, l'indécision n'a rien coûté.
    assert provider.selected == []
    assert provider.extracted == [MUETTE_URL]


def test_une_page_injoignable_ne_va_nulle_part(journal):
    log, events = journal
    provider = FakeProvider([FoundPage(url=MUETTE_URL)], {}, select_all=False)
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log, fetcher=FakeFetcher({}))

    assert kinds(events, "identified") == []
    assert result.candidates == []
    assert provider.extracted == []


# ═══════════════════════════════════════════════════ le recours au modèle


def test_le_modele_tranche_quand_les_signaux_gratuits_se_taisent(journal):
    log, events = journal
    provider, _ = lance(log, MUETTE_URL, MUETTE_HTML, verdicts=[("sortie", "un atelier daté")])

    envoye = provider.classified[0]
    assert "Atelier cirque en famille" in envoye
    assert "<html" not in envoye, "un condensé, jamais du HTML"

    constat = kinds(events, "identified")[0]
    assert (constat["nature"], constat["signal"]) == ("sortie", "modele")
    assert constat["asked"] == "claude-haiku-4-5"


def test_un_signal_gratuit_ne_coute_aucun_appel(journal):
    log, _ = journal
    provider, _ = lance(log, FICHE_URL, FICHE_HTML, verdicts=[("agenda", "jamais demandé")])
    assert provider.classified == [], "le JSON-LD a tranché, personne n'a payé"


def test_sans_modele_configure_personne_nest_appele(journal):
    log, _ = journal
    provider, _ = lance(log, MUETTE_URL, MUETTE_HTML, classify_model="")
    assert provider.classified == []


def test_un_echec_du_modele_laisse_la_page_en_agenda(journal):
    """Un second appel pour une décision qu'un filet rattrape : non."""
    log, events = journal

    class Cassé(FakeProvider):
        def classify(self, digest, config, log):
            raise ProviderError("quota dépassé")

    provider = Cassé([FoundPage(url=MUETTE_URL)], {MUETTE_URL: sortie()}, select_all=False)
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log,
                     fetcher=FakeFetcher({MUETTE_URL: MUETTE_HTML}))

    assert kinds(events, "identified")[0]["nature"] == "agenda"
    assert result.summary.errors == 0, "une reconnaissance ratée n'est pas une erreur de run"


# ══════════════════════════════════════════════════════════════ le corpus


def test_chaque_page_laisse_son_condense_au_registre(journal, tmp_path):
    """Sans lui, rien à quoi entraîner un classifieur local plus tard."""
    log, _ = journal
    chemin = tmp_path / "classifier.jsonl"
    with Ledger(chemin, run="essai") as ledger:
        lance(log, AGENDA_URL, AGENDA_HTML, ledger=ledger,
              extra={AGENDA_URL: sortie(relevant=False)})

    ligne = json.loads(chemin.read_text().splitlines()[0])
    assert ligne["run"] == "essai"
    assert (ligne["nature"], ligne["signal"], ligne["asked"]) == ("agenda", "pagination", "")
    assert ligne["digest"]["dated"] == 12
    assert ligne["digest"]["heading"] == "Que faire en famille ce mois-ci ?"


# ══════════════════════════════════════════════ le programme d'un festival


def test_un_programme_est_lu_dun_bloc(journal):
    """Il porte plusieurs sorties et ne renvoie nulle part : on l'extrait en
    entier, comme une page de festival dont les entrées sont des ancres."""
    log, events = journal
    provider, _ = lance(log, MUETTE_URL, MUETTE_HTML,
                        verdicts=[("programme", "un week-end, plusieurs rendez-vous")])

    assert kinds(events, "identified")[0]["nature"] == "programme"
    assert provider.selected == [], "un programme ne se dépouille pas"
    # L'extraction est appelée en mode « plusieurs fiches d'un coup ».
    assert provider.extracted == [MUETTE_URL]
    assert kinds(events, "programme"), "la console doit pouvoir le distinguer"


def test_un_programme_memorise_ses_sorties_et_non_sa_page(journal):
    """Sinon un programme lu une fois ne serait plus jamais relu, et tout ce
    qu'il annoncerait ensuite serait perdu."""
    log, _ = journal
    provider = FakeProvider([FoundPage(url=MUETTE_URL)], {MUETTE_URL: [sortie()]})
    provider.verdicts = [("programme", "plusieurs rendez-vous")]
    with SeenStore() as store:
        run(config(), provider, store, FakeApi(), log,
            fetcher=FakeFetcher({MUETTE_URL: MUETTE_HTML}), submit=True)
        # La page n'est pas mémorisée : ce sont ses sorties qui le sont.
        assert not store.seen(MUETTE_URL)


# ═══════════════════════════════ quand l'extraction corrige la reconnaissance


class Requalifiant(FakeProvider):
    """L'extraction dit « ce n'est pas une sortie, il y en a plusieurs ici ».

    Puis, relue en programme, elle rend les fiches. C'est le cas réel : la
    reconnaissance juge sur un condensé, l'extraction a lu tout le texte.
    """

    def extract(self, url, content, config, categories, log, *, multiple=False):
        self.extracted.append((url, multiple))
        if not multiple:
            return [sortie(relevant=False, skip_reason="c'est un programme", several=True)]
        return [sortie(title="Premier rendez-vous"), sortie(title="Second rendez-vous")]


def test_une_page_prise_pour_une_sortie_est_relue_en_programme(journal):
    log, events = journal
    provider = Requalifiant([FoundPage(url=MUETTE_URL)], {}, select_all=False)
    provider.verdicts = [("sortie", "on dirait une fiche")]
    with SeenStore() as store:
        result = run(config(), provider, store, FakeApi(), log,
                     fetcher=FakeFetcher({MUETTE_URL: MUETTE_HTML}), submit=True)

    assert provider.extracted == [(MUETTE_URL, False), (MUETTE_URL, True)]
    assert len(result.events) == 2, "les deux sorties du programme sont retenues"

    trace = kinds(events, "requalified")
    assert len(trace) == 1
    assert (trace[0]["was"], trace[0]["now"]) == ("sortie", "programme")


def test_la_page_nest_relue_quune_fois(journal):
    """La garantie tient à la structure, pas à un compteur : la relecture pose
    `multiple`, et la condition de reprise exige qu'il soit faux."""
    log, _ = journal

    class Insistant(Requalifiant):
        def extract(self, url, content, config, categories, log, *, multiple=False):
            self.extracted.append((url, multiple))
            # Même en programme, elle réclame encore une relecture.
            return [sortie(relevant=False, skip_reason="encore", several=True)]

    provider = Insistant([FoundPage(url=MUETTE_URL)], {}, select_all=False)
    provider.verdicts = [("sortie", "on dirait une fiche")]
    with SeenStore() as store:
        run(config(), provider, store, FakeApi(), log,
            fetcher=FakeFetcher({MUETTE_URL: MUETTE_HTML}))

    assert provider.extracted == [(MUETTE_URL, False), (MUETTE_URL, True)]


def test_un_programme_deja_reconnu_ne_repasse_pas(journal):
    """Il est déjà lu d'un bloc : il n'y a rien à requalifier."""
    log, events = journal
    provider = Requalifiant([FoundPage(url=MUETTE_URL)], {}, select_all=False)
    provider.verdicts = [("programme", "un festival sur une page")]
    with SeenStore() as store:
        run(config(), provider, store, FakeApi(), log,
            fetcher=FakeFetcher({MUETTE_URL: MUETTE_HTML}))

    assert provider.extracted == [(MUETTE_URL, True)]
    assert kinds(events, "requalified") == []


def test_la_correction_part_au_registre(journal, tmp_path):
    """« L'étage 6 a corrigé l'étage 2 » : la meilleure étiquette qu'on ait."""
    log, _ = journal
    chemin = tmp_path / "classifier.jsonl"
    provider = Requalifiant([FoundPage(url=MUETTE_URL)], {}, select_all=False)
    provider.verdicts = [("sortie", "on dirait une fiche")]
    with SeenStore() as store, Ledger(chemin, run="essai") as ledger:
        run(config(), provider, store, FakeApi(), log,
            fetcher=FakeFetcher({MUETTE_URL: MUETTE_HTML}), ledger=ledger)

    lignes = [json.loads(l) for l in chemin.read_text().splitlines()]
    correction = [l for l in lignes if l["topic"] == "requalify"]
    assert len(correction) == 1
    assert (correction[0]["was"], correction[0]["now"]) == ("sortie", "programme")
    assert correction[0]["url"] == MUETTE_URL
