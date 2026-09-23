"""L'agent, avec un pilote scripté : aucun modèle, aucun réseau.

Ce qui est vérifié, c'est la mécanique — les outils rendent des résumés et des
références, refusent ce qui dépasse, et la boucle s'arrête quand il faut. Ce
que vaut un vrai pilote ne se teste pas ici : c'est aux runs de le dire.
"""

from __future__ import annotations

import io
import json

import pytest
from test_pipeline import (  # fakes partagés
    AGENDA_HTML,
    AGENDA_URL,
    EVENT_HTML,
    EVENT_URL,
    FakeApi,
    FakeFetcher,
    FakeProvider,
    config,
    geocodeur_simule,  # noqa: F401 — fixture autouse : Photon simulé
    sortie,
)

from agentbot.journal import AgentLog
from agentbot.loop import ELAGUE, prune, run_agent
from agentbot.pilot import Pilot, read_turn
from agentbot.tools import Limits, Toolbox
from sortiesbot.models import Usage
from sortiesbot.providers.serper_client import Reply
from sortiesbot.stages.base import RunContext
from sortiesbot.store import SeenStore

# ───────────────────────────────────────────────────────────────── les fakes


class FakeSearch:
    """Serper scripté : une requête rend l'agenda."""

    def __init__(self, results=None):
        self.asked: list[str] = []
        self.results = results if results is not None else [
            {"link": AGENDA_URL, "title": "Agenda 92", "snippet": "Spectacles jeune public"}
        ]

    def ask(self, query, num=10):
        self.asked.append(query)
        return Reply(results=list(self.results), credits=1)


def appel(name: str, **args) -> dict:
    return {"name": name, "args": args}


def tour(*calls: dict, text: str = "", reasoning_details=None) -> dict:
    """Une réponse du service au format OpenAI, telle qu'OpenRouter la rend."""
    message: dict = {"role": "assistant", "content": text or None, "reasoning": "long monologue"}
    if calls:
        message["tool_calls"] = [
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": c["name"], "arguments": json.dumps(c["args"])},
            }
            for i, c in enumerate(calls)
        ]
    if reasoning_details is not None:
        message["reasoning_details"] = reasoning_details
    return {
        "choices": [{"message": message, "finish_reason": "tool_calls" if calls else "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "cost": 0.0002},
    }


class FakeRouter:
    """Le fournisseur OpenRouter, sans réseau : rend les tours un à un."""

    def __init__(self, turns: list[dict]):
        self.turns = list(turns)
        self.usage = Usage()
        self.payloads: list[dict] = []

    def _post(self, payload, *, op, modele, log):
        # Une copie : la boucle continue d'allonger la même liste de messages.
        self.payloads.append(json.loads(json.dumps(payload)))
        if not self.turns:
            return tour(appel("finish", bilan="script épuisé"))
        return self.turns.pop(0)

    def _facturer(self, data, *, op, modele, log):
        self.usage.add(Usage(input_tokens=1000, output_tokens=50, cost_usd=0.0002))


def outils(turns, **kwargs) -> Toolbox:
    """La boîte à outils seule, pour les tests qui appellent les outils à la main."""
    return monte(turns, **kwargs)[2]


def monte(turns, *, limits=None, provider=None, search=None, pages=None, cfg=None):
    provider = provider or FakeProvider([], {EVENT_URL: sortie()})
    fetcher = FakeFetcher(pages or {AGENDA_URL: AGENDA_HTML, EVENT_URL: EVENT_HTML})
    log = AgentLog(path=None, verbose=False, stream=io.StringIO())
    store = SeenStore(":memory:")
    ctx = RunContext(
        config=cfg or config(max_cost_usd=1.0),
        provider=provider,
        store=store,
        api=FakeApi(),
        fetcher=fetcher,
        log=log,
        submit=False,
    )
    limits = limits or Limits()
    router = FakeRouter(turns)
    pilot = Pilot("z-ai/glm-5.3-flash", provider.usage, router=router)
    toolbox = Toolbox(ctx, limits, search=search if search is not None else FakeSearch())
    return ctx, pilot, toolbox, limits, router


# ─────────────────────────────────────────────────────────── le parcours


def test_parcours_complet_de_la_recherche_a_la_sortie_retenue():
    turns = [
        tour(appel("search", query="spectacle enfant Vanves"), text="Je cherche."),
        tour(appel("open", ref="r1")),
        tour(appel("links", page="p1")),
        tour(appel("open", ref="l1")),
        tour(appel("extract", page="p2")),
        tour(appel("propose", fiche="f1")),
        tour(appel("finish", bilan="Un agenda, une sortie.")),
    ]
    ctx, pilot, toolbox, limits, _ = monte(turns)

    result = run_agent(ctx, pilot, toolbox, limits)

    assert result.reason == "le pilote a conclu"
    assert result.bilan == "Un agenda, une sortie."
    assert len(ctx.result.events) == 1
    assert ctx.result.events[0]["payload"]["title"] == "Le Petit Chaperon rouge"
    assert dict(result.calls) == {
        "search": 1, "open": 2, "links": 1, "extract": 1, "propose": 1, "finish": 1,
    }
    # Le pilote paie dans la caisse du run : c'est elle que le plafond surveille.
    assert ctx.summary.usage.cost_usd == pytest.approx(0.0002 * 7)
    assert ctx.summary.usage.web_searches == 1


def test_le_pilote_ne_voit_jamais_le_texte_entier_dune_page():
    turns = [
        tour(appel("search", query="q")),
        tour(appel("open", ref="r1")),
        tour(appel("finish", bilan="ok")),
    ]
    ctx, pilot, toolbox, limits, router = monte(turns)
    run_agent(ctx, pilot, toolbox, limits)

    envoye = json.dumps(router.payloads[-1]["messages"], ensure_ascii=False)
    assert "Retrouvez toute la programmation" in envoye  # le début, oui
    # La suite, non : l'extrait s'arrête à `EXTRAIT` caractères, au milieu du
    # premier lien, avant le contexte qui l'accompagne sur la page.
    assert "jusqu'au 30 septembre" not in envoye


def test_le_raisonnement_long_nest_pas_renvoye_mais_ses_details_le_sont():
    turns = [
        tour(appel("search", query="q"), reasoning_details=[{"type": "reasoning.encrypted", "data": "x"}]),
        tour(appel("finish", bilan="ok")),
    ]
    ctx, pilot, toolbox, limits, router = monte(turns)
    run_agent(ctx, pilot, toolbox, limits)

    assistant = next(m for m in router.payloads[1]["messages"] if m["role"] == "assistant")
    assert "reasoning" not in assistant
    assert assistant["reasoning_details"] == [{"type": "reasoning.encrypted", "data": "x"}]
    assert assistant["tool_calls"][0]["function"]["name"] == "search"


def test_chaque_tour_se_termine_par_letat_du_run():
    turns = [tour(appel("search", query="q")), tour(appel("finish", bilan="ok"))]
    ctx, pilot, toolbox, limits, router = monte(turns)
    run_agent(ctx, pilot, toolbox, limits)

    dernier = router.payloads[1]["messages"][-1]
    assert dernier["role"] == "tool"
    assert "[état :" in dernier["content"] and "recherches 1/" in dernier["content"]


# ──────────────────────────────────────────────────────────── les refus


def test_une_adresse_inventee_ne_souvre_pas():
    toolbox = outils([])
    sortie_texte = toolbox.open("https://site-invente.fr/spectacle")
    assert sortie_texte.startswith("Refusé")
    assert toolbox.ctx.fetcher.asked == []


def test_une_adresse_rendue_par_un_outil_souvre_par_son_url():
    toolbox = outils([])
    toolbox.search("q")
    assert toolbox.open(AGENDA_URL).startswith("p1 — ")


def test_la_profondeur_est_bornee():
    toolbox = outils([], limits=Limits(max_depth=0))
    toolbox.search("q")
    toolbox.open("r1")
    assert "profondeur maximale" in toolbox.links("p1")


def test_le_quota_de_recherches_est_tenu_par_le_code():
    toolbox = outils([], limits=Limits(max_searches=1))
    toolbox.search("une")
    assert toolbox.search("deux").startswith("Refusé")
    assert toolbox.search_client.asked == ["une"]


def test_budget_epuise_refuse_les_outils_payants():
    provider = FakeProvider([], {EVENT_URL: sortie()})
    provider.usage.cost_usd = 5.0
    toolbox = outils([], provider=provider)
    assert "budget épuisé" in toolbox.search("q")


def test_budget_epuise_laisse_un_tour_pour_conclure_puis_arrete():
    provider = FakeProvider([], {EVENT_URL: sortie()})
    provider.usage.cost_usd = 5.0
    turns = [tour(appel("links", page="p9")), tour(appel("links", page="p9"))]
    ctx, pilot, toolbox, limits, router = monte(turns, provider=provider)

    result = run_agent(ctx, pilot, toolbox, limits)

    assert result.reason == "budget épuisé"
    assert result.turns == 1
    assert "appelle finish" in router.payloads[0]["messages"][-1]["content"]


def test_une_fiche_hors_sujet_nest_pas_proposee():
    provider = FakeProvider([], {EVENT_URL: sortie(relevant=False, skip_reason="pour adultes")})
    toolbox = outils([], provider=provider)
    toolbox.search("q")
    toolbox.open("r1")
    toolbox.links("p1")
    toolbox.open("l1")
    assert "hors sujet (pour adultes)" in toolbox.extract("p2")
    assert "pour adultes" in toolbox.propose("f1")
    assert toolbox.ctx.result.events == []


def test_une_page_ouverte_deux_fois_ne_se_retelecharge_pas():
    toolbox = outils([])
    toolbox.search("q")
    toolbox.open("r1")
    assert toolbox.open("r1").startswith("Déjà ouverte : p1")
    assert toolbox.counters.opened == 1


def test_le_filtre_des_liens_ignore_accents_et_majuscules():
    toolbox = outils([])
    toolbox.search("q")
    toolbox.open("r1")
    assert "l1 · Le Petit Chaperon rouge" in toolbox.links("p1", filtre="THEATRE de vanves")
    assert "aucun lien" in toolbox.links("p1", filtre="opéra")


# ──────────────────────────────────────────────── ce que le modèle rate


def test_des_arguments_illisibles_sont_rendus_au_pilote_pas_leves():
    toolbox = outils([])
    texte, _ = toolbox.call("search", "{pas du json")
    assert "pas du JSON valide" in texte
    texte, _ = toolbox.call("search", json.dumps({"requete": "q"}))
    assert texte.startswith("Arguments invalides")
    texte, _ = toolbox.call("voler", "{}")
    assert texte.startswith("Outil inconnu")


def test_un_pilote_qui_cesse_dappeler_des_outils_est_relance_une_fois():
    turns = [tour(text="Je pense avoir fini."), tour(text="Vraiment fini.")]
    ctx, pilot, toolbox, limits, router = monte(turns)

    result = run_agent(ctx, pilot, toolbox, limits)

    assert result.reason == "le pilote a cessé d'appeler des outils"
    assert result.turns == 2
    assert "aucun outil" in router.payloads[1]["messages"][-1]["content"]


def test_le_plafond_de_tours_arrete_le_run():
    turns = [tour(appel("links", page="p9")) for _ in range(5)]
    ctx, pilot, toolbox, limits, _ = monte(turns, limits=Limits(max_turns=3))
    result = run_agent(ctx, pilot, toolbox, limits)
    assert result.reason == "plafond de 3 tours atteint"
    assert result.turns == 3


# ───────────────────────────────────────────────────────────── l'élagage


def test_lelagage_garde_la_premiere_ligne_et_les_tours_recents():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    for i in range(6):
        messages.append({"role": "assistant", "content": f"tour {i}"})
        messages.append({"role": "tool", "tool_call_id": str(i), "content": f"résumé {i}\ndétail {i}"})

    assert prune(messages, keep=2) == 4
    outils = [m["content"] for m in messages if m["role"] == "tool"]
    assert outils[0] == "résumé 0" + ELAGUE
    assert outils[3] == "résumé 3" + ELAGUE
    assert outils[4] == "résumé 4\ndétail 4"
    # Idempotent : un second passage ne retouche rien, donc n'invalide aucun cache.
    avant = json.dumps(messages)
    assert prune(messages, keep=2) == 0
    assert json.dumps(messages) == avant


def test_lecture_dune_reponse_a_outils():
    turn = read_turn(tour(appel("open", ref="r2"), text="J'ouvre."))
    assert turn.text == "J'ouvre."
    assert [(c.name, json.loads(c.arguments)) for c in turn.calls] == [("open", {"ref": "r2"})]
    assert turn.message["role"] == "assistant"


def test_un_nom_de_modele_sans_editeur_est_refuse_avant_toute_depense():
    from sortiesbot.providers.base import ProviderError

    with pytest.raises(ProviderError):
        Pilot("glm-flash", Usage(), router=FakeRouter([]))
