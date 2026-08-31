"""Le classifieur en observation : il note, il ne décide pas.

Deux choses à prouver, et la première est la plus importante :

1. **rien ne change.** Le pipeline suit toujours le classement du modèle, y
   compris quand le HTML le contredit. Tant qu'on mesure, on ne touche à rien ;
2. le désaccord laisse une trace, dans le journal *et* dans le registre — qui
   lui survit à l'oubli d'un run.
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
from sortiesbot.store import SeenStore

from test_pipeline import FakeApi, FakeFetcher, FakeProvider, config, sortie

PAGES = Path(__file__).parent / "fixtures" / "pages"
FICHE_URL = "https://theatre-du-chapiteau.exemple.fr/saison/le-petit-prince"
FICHE_HTML = (PAGES / "spectacle-avec-json-ld.html").read_text(encoding="utf-8")


@pytest.fixture
def journal():
    """Un journal qui garde ses événements sous la main."""
    events: list[dict] = []
    log = RunLog(path=None, verbose=False, stream=io.StringIO(), sink=events.append)
    return log, events


def kinds(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e["kind"] == kind]


def test_une_fiche_annoncee_agenda_est_signalee_mais_traitee_comme_avant(journal, tmp_path):
    """Le cas qui justifie tout : le modèle se trompe, on le note, on le suit.

    Cette page déclare un seul spectacle en JSON-LD — c'est une fiche. La
    découverte l'a pourtant classée « agenda ». Le pipeline la dépouille quand
    même, comme avant ; seul le journal en garde la trace.
    """
    log, events = journal
    provider = FakeProvider(
        [FoundPage(url=FICHE_URL, title="Le Petit Prince", kind="agenda")],
        {FICHE_URL: sortie()},
        # Le modèle retient les deux liens « vous aimerez aussi » de la page :
        # elle passe donc bel et bien pour un agenda, désaccord ou pas.
        select_all=True,
    )
    fetcher = FakeFetcher({FICHE_URL: FICHE_HTML})
    ledger_path = tmp_path / "classifier.jsonl"

    with SeenStore() as store, Ledger(ledger_path, run="essai") as ledger:
        run(config(), provider, store, api := FakeApi(), log,
            fetcher=fetcher, ledger=ledger)

    desaccords = kinds(events, "classify_disagreement")
    assert len(desaccords) == 1
    assert desaccords[0]["announced"] == "agenda"
    assert desaccords[0]["verdict"] == "sortie"
    assert desaccords[0]["signal"] == "json-ld"

    # Et malgré ce désaccord : la page a été dépouillée et ses liens suivis,
    # exactement comme si le classifieur n'existait pas.
    assert provider.selected == [FICHE_URL]
    assert api.created == []


def test_une_page_sans_declaration_ne_contredit_personne(journal):
    """Le classifieur s'abstient sur cet agenda : abstention n'est pas désaccord.

    Aucun de ces sites d'agenda ne déclare de `ItemList` en JSON-LD — c'est ce
    que la première mesure a montré. La cascade répond donc « inconnu », et
    `agrees` vaut `None` : il n'y a rien à confronter, et surtout rien à
    signaler comme un désaccord.
    """
    log, events = journal
    agenda_url = "https://agenda.exemple-departement.fr/agenda/"
    agenda_html = (PAGES / "agenda-departemental.html").read_text(encoding="utf-8")
    provider = FakeProvider(
        [FoundPage(url=agenda_url, title="Agenda", kind="agenda")],
        # Aucun lien retenu : le filet relit la page, qui se révèle être une
        # liste. Elle est donc classée deux fois — au dépouillement puis à la
        # lecture — et les deux fois d'accord avec la découverte.
        {agenda_url: sortie(relevant=False, skip_reason="page de liste")},
        select_all=False,
    )

    with SeenStore() as store:
        run(config(), provider, store, FakeApi(), log,
            fetcher=FakeFetcher({agenda_url: agenda_html}))

    constats = kinds(events, "classified")
    assert constats, "chaque page téléchargée doit être constatée"
    assert all(c["agrees"] is not False for c in constats)
    assert kinds(events, "classify_disagreement") == []


def test_le_registre_survit_au_run_et_dit_qui_a_dit_quoi(journal, tmp_path):
    """Ce que le registre doit contenir pour qu'on puisse trancher plus tard."""
    log, _ = journal
    provider = FakeProvider(
        [FoundPage(url=FICHE_URL, title="Le Petit Prince", kind="agenda")],
        {FICHE_URL: sortie()},
    )
    ledger_path = tmp_path / "classifier.jsonl"

    with SeenStore() as store, Ledger(ledger_path, run="essai-42") as ledger:
        run(config(), provider, store, FakeApi(), log,
            fetcher=FakeFetcher({FICHE_URL: FICHE_HTML}), ledger=ledger)

    lignes = [json.loads(l) for l in ledger_path.read_text().splitlines()]
    assert lignes, "le registre doit porter au moins une observation"
    observation = lignes[0]
    assert observation["run"] == "essai-42"
    assert observation["topic"] == "classify"
    assert observation["url"] == FICHE_URL
    assert (observation["announced"], observation["verdict"]) == ("agenda", "sortie")
    assert observation["agrees"] is False
    assert observation["stage"] == "harvest"
    assert observation["at"]


def test_sans_chemin_le_registre_ne_fait_rien(tmp_path):
    """Un run jetable ne doit pas polluer une mesure qui court sur des semaines."""
    muet = Ledger(None)
    muet.record("classify", url="https://exemple.fr")
    muet.close()
    assert list(tmp_path.iterdir()) == []


def test_un_registre_impossible_ne_casse_pas_le_run(tmp_path, capsys):
    """Un instrument de mesure ne fait jamais échouer ce qu'il mesure."""
    bouche = tmp_path / "bouche"
    bouche.write_text("ceci n'est pas un dossier")

    ledger = Ledger(bouche / "classifier.jsonl")
    ledger.record("classify", url="https://exemple.fr")
    ledger.close()

    assert "Registre indisponible" in capsys.readouterr().err
