"""La recherche de source : l'étage 7 rejoué seul, sur une sortie déjà en base.

Le scraper ne remonte à l'organisateur qu'au fil d'une recherche. Une sortie
publiée dont le lien pointe sur un agrégateur restait donc comme ça pour
toujours, et un modérateur n'avait rien d'autre à faire que de chercher à la
main. `run_source` est ce que son bouton déclenche.

Ce que ces tests verrouillent :

1. **C'est bien l'étage 7, pas une seconde implémentation.** La cascade, la
   vérification et le refus des agrégateurs valent ici comme ailleurs — un
   test qui passerait ici et pas dans `test_attribution.py` dirait qu'on a
   dupliqué la règle.
2. **Rien n'est deviné de la sortie.** Titre, lieu et dates viennent du site :
   ce qui n'y est pas ne doit pas être inventé.
3. **Le journal permet la page de débogage.** Sans `run_start` portant le
   graphe des étages, la console n'a rien à dessiner.
"""

from __future__ import annotations

import io

import pytest

from sortiesbot.journal import RunLog
from sortiesbot.orchestrator import run_source
from sortiesbot.store import SeenStore

from test_attribution import AUTRE_HTML, FakeEngine, KIDIKLIK, MUSEE, MUSEE_HTML, kidiklik_html
from test_pipeline import FakeApi, FakeFetcher, FakeProvider, config

#: Ce que le site envoie au worker : la fiche telle qu'elle est en base, et la
#: page dont il faut repartir — celle qui a été lue, pas celle qu'on montre.
FICHE = {
    "id": 42,
    "title": "Atelier modelage en famille",
    "venueName": "Musée Rodin",
    "venueCity": "Paris",
    "dateStart": "2026-04-12",
    "dateEnd": "2026-04-12",
    "pageUrl": KIDIKLIK,
}


def chercher(pages: dict[str, str], *, event=None, engine=None, journal=None):
    """Joue une recherche de source, sans réseau. Rend le `SourceResult`."""
    return run_source(
        config(),
        FakeProvider([], {}),
        SeenStore(),
        FakeApi(),
        journal or RunLog(path=None, verbose=False, stream=io.StringIO()),
        {**FICHE, **(event or {})},
        fetcher=FakeFetcher(pages),
        engine=engine,
    )


@pytest.fixture
def journal():
    events: list[dict] = []
    return RunLog(path=None, verbose=False, stream=io.StringIO(), sink=events.append), events


# ═══════════════════════════════════ 1. c'est bien l'étage 7 qui travaille

def test_la_source_est_remontee_et_verifiee():
    """Le cas nominal : le lien de l'agrégateur mène au musée, le musée le confirme."""
    lien = f'<a href="{MUSEE}">Site officiel du musée</a>'
    result = chercher({KIDIKLIK: kidiklik_html(liens=lien), MUSEE: MUSEE_HTML})

    assert result.source.found
    assert result.source.url == MUSEE
    assert result.source.checked


def test_une_candidate_qui_parle_dautre_chose_est_ecartee():
    """La vérification n'est pas contournable ici non plus."""
    lien = f'<a href="{MUSEE}">Réserver</a>'
    result = chercher({KIDIKLIK: kidiklik_html(liens=lien), MUSEE: AUTRE_HTML})

    assert not result.source.found
    assert not result.source.checked


def test_une_page_deja_a_la_source_ne_coute_rien():
    """Une fiche dont le lien n'est pas un agrégateur : il n'y a rien à remonter.

    C'est le cas le plus fréquent d'un clic curieux, et il doit être gratuit :
    pas une requête au moteur, pas un téléchargement de candidate.
    """
    engine = FakeEngine()
    result = chercher(
        {MUSEE: MUSEE_HTML},
        event={"pageUrl": MUSEE},
        engine=engine,
    )

    assert not result.source.found
    assert engine.queries == []
    assert "organisateur" in result.source.detail


def test_le_moteur_prend_le_relais_quand_la_page_ne_dit_rien():
    """Aucun signal gratuit : le repli payant, puis la même vérification."""
    engine = FakeEngine([{"link": MUSEE}])
    result = chercher({KIDIKLIK: kidiklik_html(), MUSEE: MUSEE_HTML}, engine=engine)

    assert result.source.url == MUSEE
    assert engine.queries, "le moteur devait être interrogé"
    # La requête identifie la sortie : titre et lieu, pas « site officiel ».
    assert "Atelier modelage en famille" in engine.queries[0]
    assert "Musée Rodin" in engine.queries[0]


def test_la_depense_du_moteur_est_comptee():
    """Le seul appel payant de l'étage doit se retrouver dans les compteurs."""
    result = chercher(
        {KIDIKLIK: kidiklik_html(), MUSEE: MUSEE_HTML},
        engine=FakeEngine([{"link": MUSEE}]),
    )

    assert result.summary.usage.web_searches == 1
    assert result.summary.usage.total_usd > 0


# ═════════════════════════════════════════ 2. rien n'est deviné de la sortie

def test_une_page_de_depart_illisible_ne_fait_pas_tomber_la_recherche():
    """Sans HTML, les signaux gratuits sont muets — ce n'est pas une panne."""
    result = chercher({}, engine=None)

    assert not result.source.found


def test_la_page_de_depart_nest_jamais_proposee_comme_source():
    """Se citer soi-même n'apprend rien : `_usable` écarte le site courant."""
    lien = f'<a href="{KIDIKLIK}">Site officiel</a>'
    result = chercher({KIDIKLIK: kidiklik_html(liens=lien)})

    assert result.source.url != KIDIKLIK


# ═══════════════════════════════════ 3. le journal, pour la page de débogage

def test_le_journal_porte_le_graphe_et_la_piste(journal):
    """Sans `run_start` ni piste, la console n'a ni graphe ni filtre."""
    log, events = journal
    lien = f'<a href="{MUSEE}">Site officiel du musée</a>'
    chercher({KIDIKLIK: kidiklik_html(liens=lien), MUSEE: MUSEE_HTML}, journal=log)

    debut = next(e for e in events if e["kind"] == "run_start")
    assert debut["mode"] == "recherche de source"
    assert [s["stage"] for s in debut["stages"]][6] == "attribute"

    # Tout ce que l'étage journalise descend de la page de départ : c'est ce
    # qui permet de filtrer la piste depuis la console.
    attributions = [e for e in events if e["kind"] == "attribution"]
    assert attributions, "l'étage devait journaliser son verdict"
    assert all(e.get("page") == KIDIKLIK for e in attributions)

    assert any(e["kind"] == "run_end" for e in events)


def test_letage_7_est_le_seul_traverse(journal):
    """Une chaîne d'un maillon : aucun autre étage ne doit s'ouvrir."""
    log, events = journal
    chercher({KIDIKLIK: kidiklik_html()}, journal=log)

    ouverts = {e["stage"] for e in events if e["kind"] == "stage_start"}
    assert ouverts == {"attribute"}
