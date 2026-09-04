"""L'étage 7 : remonter de l'agrégateur à l'organisateur, et le prouver.

Ce que ces tests verrouillent, dans l'ordre de ce qui compte :

1. **La validation n'est pas contournable.** Une page candidate qui ne parle
   pas de la sortie est écartée, quel que soit le signal qui l'avait désignée.
   C'est la seule chose qui distingue cet étage d'une devinette bien tournée.
2. **La cascade est un ordre, pas un menu.** Le premier signal gratuit qui
   tient l'emporte, et le moteur n'est appelé que lorsque tous se taisent.
3. **Le contrat avec le reste du pipeline.** Ce qui part au site est le
   meilleur lien, la provenance est renseignée quand elle apprend quelque
   chose, et une attribution qui échoue laisse exactement l'état d'avant.

Le moteur est simulé partout : un test qui appellerait Serper mesurerait
Google, pas notre code.
"""

from __future__ import annotations

import io

import pytest

from sortiesbot.config import Config
from sortiesbot.journal import RunLog
from sortiesbot.models import Candidate, SourceLink
from sortiesbot.orchestrator import run
from sortiesbot.providers.base import ProviderError
from sortiesbot.providers.serper_client import Reply
from sortiesbot.stages.attribution import Attribution
from sortiesbot.stages.base import PageContent, RunContext
from sortiesbot.store import SeenStore

from test_pipeline import FakeApi, FakeFetcher, FakeProvider, config, sortie

# ── Un agrégateur, et le musée derrière lui ────────────────────────────────

KIDIKLIK = "https://iledefrance.kidiklik.fr/articles/atelier-modelage-rodin"
MUSEE = "https://www.musee-rodin.fr/fr/agenda/atelier-modelage-en-famille"

#: La page de l'organisateur, telle qu'elle sera vérifiée : elle nomme la
#: sortie, ce qui suffit à prouver qu'on parle bien de la même chose.
MUSEE_HTML = """<html><body><h1>Atelier modelage en famille</h1>
<p>Un atelier de modelage pour les enfants, au musée Rodin, à Paris.</p>
</body></html>"""

#: Une page d'organisateur qui existe mais parle d'autre chose. C'est le cas
#: qui fait tout l'intérêt de la vérification : le lien est plausible, le
#: domaine est le bon, et pourtant ce n'est pas la page de cette sortie.
AUTRE_HTML = """<html><body><h1>Réserver un billet</h1>
<p>Choisissez votre créneau de visite du musée et réglez en ligne.</p>
</body></html>"""


def kidiklik_html(*, json_ld: str = "", liens: str = "") -> str:
    """Une fiche d'agrégateur, dont on choisit les signaux qu'elle porte."""
    bloc = f'<script type="application/ld+json">{json_ld}</script>' if json_ld else ""
    return f"""<html><head>{bloc}</head><body>
    <h1>Atelier modelage en famille</h1>
    <p>Le musée Rodin propose un atelier de modelage aux familles, dans les
    ateliers pédagogiques du musée. Les enfants façonnent l'argile à côté des
    œuvres, accompagnés d'un plasticien. Deux heures, goûter compris, à partir
    de six ans. Réservation conseillée, le nombre de places est limité.</p>
    <a href="/articles/autre-sortie">Une autre sortie près de chez vous</a>
    <a href="https://www.facebook.com/kidiklik">Suivez-nous sur Facebook</a>
    {liens}
    </body></html>"""


ATELIER = sortie(
    title="Atelier modelage en famille",
    venue_name="Musée Rodin",
    venue_city="Paris",
    venue_address="77 rue de Varenne",
)


class FakeEngine:
    """Serper scripté. Compte ses appels : c'est ce qui prouve la gratuité."""

    def __init__(self, results: list[dict] | None = None, fail: bool = False):
        self.results = results if results is not None else [{"link": MUSEE}]
        self.fail = fail
        self.queries: list[str] = []

    def ask(self, query: str, num: int = 5) -> Reply:
        self.queries.append(query)
        if self.fail:
            raise ProviderError("quota Serper dépassé (429)")
        return Reply(results=self.results, credits=1)


@pytest.fixture
def log():
    events: list[dict] = []
    journal = RunLog(path=None, verbose=False, stream=io.StringIO(), sink=events.append)
    return journal, events


def attribuer(pages: dict[str, str], *, engine=None, conf: Config | None = None, log=None):
    """Joue l'étage seul, sur une page d'agrégateur donnée. Rend le `SourceLink`."""
    journal = log or RunLog(path=None, verbose=False, stream=io.StringIO())
    ctx = RunContext(
        config=conf or config(),
        provider=FakeProvider([], {}),
        store=SeenStore(),
        api=FakeApi(),
        fetcher=FakeFetcher(pages),
        log=journal,
        submit=False,
    )
    brick = Attribution(ctx, engine=engine)
    page = PageContent(url=KIDIKLIK, text="", json_ld_dates=[], image="")
    return brick.run(ATELIER, Candidate(url=KIDIKLIK, title=""), page)


# ═════════════════════════════════ 1. la validation, qui n'est pas optionnelle

def test_une_candidate_qui_parle_dautre_chose_est_ecartee():
    """Le cœur de l'étage : un lien plausible n'est pas une source.

    Le domaine est le bon, le lien s'annonce « réserver », et la page ne parle
    pourtant pas de cet atelier. Sans cette épreuve, le parent recevrait un
    lien vers une billetterie générique en croyant tenir sa sortie.
    """
    engine = FakeEngine(results=[])
    source = attribuer(
        {
            KIDIKLIK: kidiklik_html(
                liens=f'<a href="{MUSEE}">Réserver sur le site officiel</a>'
            ),
            MUSEE: AUTRE_HTML,
        },
        engine=engine,
    )
    assert not source.found
    assert source.url == ""


def test_une_candidate_injoignable_nest_pas_retenue():
    """404, robots.txt, serveur muet : pas de page ouverte, pas de source."""
    source = attribuer(
        {KIDIKLIK: kidiklik_html(liens=f'<a href="{MUSEE}">Site officiel</a>')},
        engine=FakeEngine(results=[]),
    )
    assert not source.found


def test_le_lieu_et_une_date_prouvent_aussi():
    """Le recours du programme, qui ne nomme pas chaque atelier comme l'agrégateur.

    Un festival titre « Le petit bal » là où l'agrégateur écrit « Le petit bal
    des tout-petits — spectacle jeune public ». Le titre ne se retrouve pas ;
    le lieu et une date annoncée, si.
    """
    programme = (
        "<html><body><h1>Saison famille</h1>"
        "<p>Musée Rodin — programme du trimestre.</p>"
        f"<p>Rendez-vous le {int(ATELIER.date_start[8:10])} "
        f"{'janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre'.split()[int(ATELIER.date_start[5:7]) - 1]}"
        " au jardin.</p></body></html>"
    )
    source = attribuer(
        {
            KIDIKLIK: kidiklik_html(liens=f'<a href="{MUSEE}">Site officiel</a>'),
            MUSEE: programme,
        },
        engine=FakeEngine(results=[]),
    )
    assert source.found
    assert "lieu et date" in source.detail


# ═══════════════════════════════════════ 2. la cascade, dans son ordre

def test_le_json_ld_passe_avant_tout():
    """Ce que la page déclare vaut mieux que ce qu'on déduit de ses liens."""
    engine = FakeEngine()
    source = attribuer(
        {
            KIDIKLIK: kidiklik_html(
                json_ld=f'{{"@type": "Event", "url": "{MUSEE}"}}',
                liens='<a href="https://billetweb.fr/x">Réserver</a>',
            ),
            MUSEE: MUSEE_HTML,
        },
        engine=engine,
    )
    assert source.found and source.url == MUSEE
    assert source.signal == "json_ld"
    assert engine.queries == []  # gratuit : le moteur n'a pas été dérangé.


def test_le_domaine_du_lieu_se_reconnait_sans_texte_de_lien():
    """« Musée Rodin » et `musee-rodin.fr` : deux sources indépendantes qui concordent.

    Le lien ne porte qu'un logo, donc aucun texte exploitable. C'est le cas où
    le signal 3 est muet et où le signal 2 tranche quand même.
    """
    engine = FakeEngine()
    source = attribuer(
        {
            KIDIKLIK: kidiklik_html(liens=f'<a href="{MUSEE}"><img src="/logo.png"></a>'),
            MUSEE: MUSEE_HTML,
        },
        engine=engine,
    )
    assert source.found and source.signal == "venue_domain"
    assert engine.queries == []


def test_un_domaine_qui_ressemble_ne_suffit_pas_a_lui_seul():
    """Le plancher de quatre lettres, et la vérification derrière.

    `art-en-herbe.fr` ne partage aucun mot significatif avec « Musée Rodin »,
    et sa page ne parle pas de l'atelier : rien ne doit le désigner.
    """
    source = attribuer(
        {
            KIDIKLIK: kidiklik_html(liens='<a href="https://art-en-herbe.fr/x">Voir</a>'),
            "https://art-en-herbe.fr/x": AUTRE_HTML,
        },
        engine=FakeEngine(results=[]),
    )
    assert not source.found


def test_le_moteur_nest_appele_que_si_la_page_ne_dit_rien():
    """Le repli, et sa condition : aucun signal gratuit n'a tenu.

    C'est le cas réel le plus fréquent — beaucoup d'agrégateurs recopient sans
    jamais citer leur source.
    """
    engine = FakeEngine()
    source = attribuer(
        {KIDIKLIK: kidiklik_html(), MUSEE: MUSEE_HTML},
        engine=engine,
    )
    assert source.found and source.signal == "search"
    assert len(engine.queries) == 1
    # La requête identifie la sortie ; elle ne demande pas « site officiel »,
    # qui ferait remonter la racine du site plutôt que cette page.
    assert "Atelier modelage en famille" in engine.queries[0]
    assert "Musée Rodin" in engine.queries[0]
    assert "officiel" not in engine.queries[0]


def test_le_resultat_du_moteur_est_verifie_comme_les_autres():
    """Un moteur se trompe aussi : sa réponse passe la même épreuve."""
    engine = FakeEngine(results=[{"link": "https://autre-musee.fr/agenda"}])
    source = attribuer(
        {KIDIKLIK: kidiklik_html(), "https://autre-musee.fr/agenda": AUTRE_HTML},
        engine=engine,
    )
    assert not source.found
    assert engine.queries  # il a bien été appelé, et sa réponse rejetée.


def test_le_moteur_absent_nempeche_rien():
    """Sans clé Serper, l'étage tourne sur ses trois signaux gratuits."""
    source = attribuer({KIDIKLIK: kidiklik_html(), MUSEE: MUSEE_HTML}, engine=None)
    assert not source.found
    assert "moteur" in source.detail


def test_la_recherche_se_coupe_par_configuration():
    """`source_search: false` : les signaux gratuits, et rien de payant."""
    engine = FakeEngine()
    source = attribuer(
        {KIDIKLIK: kidiklik_html(), MUSEE: MUSEE_HTML},
        engine=engine,
        conf=config(source_search=False),
    )
    assert not source.found
    assert engine.queries == []


def test_un_moteur_en_panne_ne_fait_pas_perdre_la_sortie():
    """Serper en quota dépassé : la sortie part avec la page lue, sans exception."""
    source = attribuer(
        {KIDIKLIK: kidiklik_html(), MUSEE: MUSEE_HTML}, engine=FakeEngine(fail=True)
    )
    assert not source.found
    assert "moteur indisponible" in source.detail


def test_une_page_qui_nest_pas_un_agregateur_nest_pas_creusee():
    """Pas d'agrégateur, pas de question : la page lue est déjà la source.

    C'est ce qui rend l'étage presque toujours gratuit — la plupart des runs
    lisent des pages d'organisateurs.
    """
    engine = FakeEngine()
    ctx = RunContext(
        config=config(),
        provider=FakeProvider([], {}),
        store=SeenStore(),
        api=FakeApi(),
        fetcher=FakeFetcher({MUSEE: MUSEE_HTML}),
        log=RunLog(path=None, verbose=False, stream=io.StringIO()),
        submit=False,
    )
    page = PageContent(url=MUSEE, text="", json_ld_dates=[], image="")
    source = Attribution(ctx, engine=engine).run(ATELIER, Candidate(url=MUSEE, title=""), page)
    assert not source.found
    assert engine.queries == []


def test_un_autre_agregateur_nest_jamais_une_source():
    """Remonter de kidiklik à citizenkid ne remonte à rien."""
    engine = FakeEngine(results=[{"link": "https://www.citizenkid.com/atelier-rodin"}])
    source = attribuer(
        {
            KIDIKLIK: kidiklik_html(
                liens='<a href="https://www.citizenkid.com/atelier-rodin">Site officiel</a>'
            ),
            "https://www.citizenkid.com/atelier-rodin": MUSEE_HTML,
        },
        engine=engine,
    )
    assert not source.found


# ══════════════════════════════ 3. le contrat avec le reste du pipeline

def test_la_sortie_part_avec_la_source_et_sa_provenance(log):
    """Le pipeline entier : ce que le site reçoit quand l'attribution a trouvé.

    `sourceUrl` porte le musée — c'est lui que le parent ouvrira — et
    `foundOnUrl` porte kidiklik, pour le modérateur qui veut savoir d'où ça
    vient. La mémoire, elle, reste indexée sur la page lue.
    """
    journal, _ = log
    from sortiesbot.models import FoundPage

    provider = FakeProvider([FoundPage(url=KIDIKLIK, title="Atelier")], {KIDIKLIK: ATELIER})
    # La fiche d'agrégateur est reconnue comme une sortie : elle saute le
    # dépouillement et le tri, ce qui est le chemin réel d'une page de fiche.
    provider.verdicts = [("sortie", "une fiche d'événement")]
    fetcher = FakeFetcher({KIDIKLIK: kidiklik_html(), MUSEE: MUSEE_HTML})
    with SeenStore() as store:
        result = run(
            config(),
            provider,
            store,
            FakeApi(),
            journal,
            submit=False,
            fetcher=fetcher,
            engine=FakeEngine(),
        )

    (event,) = result.events
    assert event["payload"]["sourceUrl"] == MUSEE
    assert event["payload"]["foundOnUrl"] == KIDIKLIK
    assert event["payload"]["sourceUrlSignal"] == "search"
    # La page lue reste la référence de la mémoire : c'est elle qu'un prochain
    # run retrouvera, pas la source qu'on vient de lui attribuer.
    assert event["source_url"] == KIDIKLIK


def test_sans_source_la_sortie_part_comme_avant(log):
    """Le repli complet : rien trouvé, rien cassé.

    C'est la garantie qui autorisait à brancher cet étage sans filet — une
    attribution muette rend exactement l'état d'avant elle, `foundOnUrl` vide
    plutôt que répétant `sourceUrl`.
    """
    journal, _ = log
    from sortiesbot.models import FoundPage

    provider = FakeProvider([FoundPage(url=KIDIKLIK, title="Atelier")], {KIDIKLIK: ATELIER})
    provider.verdicts = [("sortie", "une fiche d'événement")]
    fetcher = FakeFetcher({KIDIKLIK: kidiklik_html()})
    with SeenStore() as store:
        result = run(
            config(), provider, store, FakeApi(), journal,
            submit=False, fetcher=fetcher, engine=FakeEngine(results=[]),
        )

    (event,) = result.events
    assert event["payload"]["sourceUrl"] == KIDIKLIK
    assert event["payload"]["foundOnUrl"] is None
    assert event["payload"]["sourceUrlSignal"] is None


def test_le_journal_dit_ce_qui_a_ete_ecarte(log):
    """Une candidate rejetée laisse une trace : c'est ce qui rendra la mesure possible."""
    journal, events = log
    attribuer(
        {
            KIDIKLIK: kidiklik_html(liens=f'<a href="{MUSEE}">Site officiel</a>'),
            MUSEE: AUTRE_HTML,
        },
        engine=FakeEngine(results=[]),
        log=journal,
    )
    ecartees = [
        e for e in events
        if e.get("kind") == "attribution" and e.get("status") == "candidate écartée"
    ]
    assert len(ecartees) == 1
    assert ecartees[0]["candidate"] == MUSEE
    # Le domaine du lieu l'avait désignée avant le texte du lien : c'est
    # l'ordre de la cascade, et le journal dit lequel a parlé.
    assert ecartees[0]["signal"] == "venue_domain"


def test_le_journal_compte_ce_que_le_moteur_a_rendu(log):
    """Zéro résultat et cinq résultats tous refusés doivent se distinguer.

    C'est le cas qui a motivé cet événement : les deux se soldent par une
    sortie sans source, et se corrigent à deux endroits opposés — élargir la
    requête d'un côté, revoir le tamis de l'autre.
    """
    journal, events = log
    attribuer({KIDIKLIK: kidiklik_html()}, engine=FakeEngine(results=[]), log=journal)

    interroge = [
        e for e in events
        if e.get("kind") == "attribution" and e.get("status") == "moteur interrogé"
    ]
    assert len(interroge) == 1
    assert interroge[0]["results"] == 0


def test_le_journal_dit_pourquoi_un_resultat_est_refuse_sans_etre_ouvert(log):
    """Le motif du refus, résultat par résultat — le diagnostic est cette liste.

    Un organisateur sans site et une cascade trop sévère se ressemblent
    exactement, vues du seul résultat. Vues de ces motifs, non.
    """
    journal, events = log
    source = attribuer(
        {KIDIKLIK: kidiklik_html()},
        engine=FakeEngine(
            results=[
                {"link": "https://www.citizenkid.com/atelier-modelage"},   # agrégateur
                {"link": "https://www.facebook.com/museerodin"},           # bloqué
                {"link": f"{KIDIKLIK}?utm_source=x"},                      # déjà chez soi
                {"link": "pas-une-url"},
            ]
        ),
        log=journal,
    )
    assert not source.found

    ecartes = [
        e for e in events
        if e.get("kind") == "attribution" and e.get("status") == "résultat écarté"
    ]
    assert [e["candidate"] for e in ecartes] == [
        "https://www.citizenkid.com/atelier-modelage",
        "https://www.facebook.com/museerodin",
        f"{KIDIKLIK}?utm_source=x",
        "pas-une-url",
    ]
    motifs = [e["reason"] for e in ecartes]
    assert "agrégateur" in motifs[0] and "citizenkid.com" in motifs[0]
    assert "bloqué" in motifs[1]
    assert "page lue" in motifs[2]
    assert "adresse web" in motifs[3]
    # Aucune n'a été téléchargée : un refus au tamis ne coûte rien, et ne doit
    # pas se confondre avec une candidate ouverte puis jetée.
    assert not any(e.get("status") == "candidate écartée" for e in events)


def test_un_resultat_exploitable_nest_pas_journalise_comme_ecarte(log):
    """Le journal ne dit « écarté » que de ce qui l'a été."""
    journal, events = log
    source = attribuer(
        {KIDIKLIK: kidiklik_html(), MUSEE: MUSEE_HTML},
        engine=FakeEngine(results=[{"link": MUSEE}]),
        log=journal,
    )
    assert source.found
    assert not any(e.get("status") == "résultat écarté" for e in events)


def test_une_source_non_verifiee_ne_passe_jamais_a_la_publication():
    """La règle, énoncée sur l'objet lui-même : `found` exige `checked`."""
    assert not SourceLink(url=MUSEE, signal="search").found
    assert SourceLink(url=MUSEE, signal="search", checked=True).found
