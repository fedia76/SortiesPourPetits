"""Le worker de l'agent : réclamer ses exécutions, jouer, rendre compte, clore.

Même simulation que pour le worker du pipeline — l'API du site, le serveur
web, le moteur et le pilote sont scriptés. Ce qui est vérifié, c'est le
contrat avec le site : c'est lui qui fait apparaître l'origine d'une sortie en
modération.
"""

from __future__ import annotations

from test_agent import FakeRouter, FakeSearch, appel, tour
from test_pipeline import (  # fakes partagés
    AGENDA_HTML,
    AGENDA_URL,
    EVENT_HTML,
    EVENT_URL,
    FakeFetcher,
    FakeProvider,
    geocodeur_simule,  # noqa: F401 — fixture autouse : Photon simulé
    sortie,
)
from test_worker import API_CONFIG, ScraperApi

from agentbot import worker
from agentbot.pilot import Pilot
from sortiesbot.config import Environment

PARCOURS = [
    tour(appel("search", query="spectacle enfant")),
    tour(appel("open", ref="r1")),
    tour(appel("links", page="p1")),
    tour(appel("open", ref="l1")),
    tour(appel("extract", page="p2")),
    tour(appel("propose", fiche="f1")),
    tour(appel("finish", bilan="Une sortie.")),
]


class AgentApi(ScraperApi):
    """L'API du site, telle que le worker de l'agent la voit."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.paths: list[str] = []
        self.logs: list[dict] = []

    def _post_json(self, path, payload=None):
        self.paths.append(path)
        return {"run": self.queue.pop(0) if self.queue else None}

    def report_logs(self, run_id, entries):
        self.logs.extend(entries)


def branche(monkeypatch, turns):
    """Remplace ce qui touche au réseau : fournisseur, pilote, moteur, pages."""
    provider = FakeProvider([], {EVENT_URL: sortie()})
    router = FakeRouter(turns)
    pilots: list[str] = []

    def pilote(model, usage, **kwargs):
        pilots.append(model)
        return Pilot(model, usage, router=router, effort=kwargs.get("effort", "low"))

    monkeypatch.setattr(worker, "get_provider", lambda *a, **k: provider)
    monkeypatch.setattr(worker, "Pilot", pilote)
    monkeypatch.setattr(worker, "SerperClient", lambda key: FakeSearch())
    monkeypatch.setattr(
        worker, "Fetcher", lambda: FakeFetcher({AGENDA_URL: AGENDA_HTML, EVENT_URL: EVENT_HTML})
    )
    return pilots


ENV = Environment(
    api_url="http://site", api_key="spp_x", anthropic_key=None,
    serper_key="serper", openrouter_key="or",
)


def test_le_worker_ne_reclame_que_les_executions_de_lagent():
    api = AgentApi(queue=[{"id": 1}])
    assert worker.next_agent_run(api) == {"id": 1}
    assert api.paths == ["/api/scraper/next?engine=agent"]


def test_une_execution_soumise_part_en_moderation_rattachee_a_son_run(monkeypatch, tmp_path):
    pilots = branche(monkeypatch, PARCOURS)
    api = AgentApi()
    job = {"id": 7, "submit": True, "engine": "agent", "pilot": "anthropic/claude-haiku-4.5",
           "config": API_CONFIG}

    worker.execute(job, api, ENV, tmp_path, quiet=True)

    # Le pilote demandé depuis la console, pas le défaut.
    assert pilots == ["anthropic/claude-haiku-4.5"]
    # Proposée au site, et rendue au run avec son identifiant : c'est ce lien
    # qui dit, en modération, qu'elle vient de l'agent.
    assert len(api.created) == 1
    soumis = [i for i in api.items if i["decision"] == "submitted"]
    assert soumis and soumis[0]["eventId"] == 101
    run_id, status, compteurs = api.finished[0]
    assert (run_id, status) == (7, "DONE")
    assert compteurs["submitted"] == 1
    # Le journal remonte au site, tours de l'agent compris.
    assert any(entry["kind"] == "agent_turn" for entry in api.logs)


def test_une_execution_dessai_ne_propose_rien(monkeypatch, tmp_path):
    branche(monkeypatch, PARCOURS)
    api = AgentApi()

    worker.execute({"id": 8, "submit": False, "config": API_CONFIG}, api, ENV, tmp_path, quiet=True)

    assert api.created == []
    assert api.finished[0][1] == "DONE"
    assert api.finished[0][2]["retained"] == 1


def test_sans_pilote_demande_le_worker_prend_le_defaut(monkeypatch, tmp_path):
    pilots = branche(monkeypatch, PARCOURS)
    worker.execute({"id": 9, "config": API_CONFIG}, AgentApi(), ENV, tmp_path, quiet=True)
    assert pilots == [worker.PILOTE_DEFAUT]


def test_une_panne_du_pilote_clot_lexecution_en_echec(monkeypatch, tmp_path):
    branche(monkeypatch, PARCOURS)

    def boom(*a, **k):
        raise RuntimeError("pilote cassé")

    monkeypatch.setattr(worker, "run_agent", boom)
    api = AgentApi()
    worker.execute({"id": 10, "config": API_CONFIG}, api, ENV, tmp_path, quiet=True)

    _, status, compteurs = api.finished[0]
    assert status == "FAILED" and "pilote cassé" in compteurs["error"]


def test_le_quota_de_recherches_de_la_console_ne_descend_pas_sous_celui_de_lagent():
    assert worker.limits_for(6).max_searches == 20
    assert worker.limits_for(30).max_searches == 30
