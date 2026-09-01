"""Le fournisseur Serper : un moteur pour chercher, un modèle pour le reste.

Aucun appel réseau. Les réponses sont simulées à la forme documentée de
l'API — un objet portant un tableau `organic` dont chaque entrée a `title`,
`link`, `snippet` et `position`.

La forme a été **confrontée au service le 1er septembre 2026**, par le job
`serper` de `.github/workflows/verifier.yml` — le détail est en tête de
`serper_provider.py`. Elle concorde, à un détail près qu'on ignorait : la
réponse annonce elle-même ce qu'elle a coûté, en crédits.

Ces tests verrouillent ce que le code fait de cette forme. Ce n'est pas eux
qui garantissent qu'elle soit la bonne — ça, seul un appel réel le dit, et
c'est à quoi sert ce job.
"""

from __future__ import annotations

import io
import json

import pytest

from sortiesbot.config import Config
from sortiesbot.harvest import Link
from sortiesbot.journal import RunLog
from sortiesbot.models import ExtractedEvent, Usage
from sortiesbot.providers.base import ProviderError
from sortiesbot.providers.serper_provider import SerperProvider


class Reponse:
    def __init__(self, payload, status: int = 200, illisible: bool = False):
        self._payload = payload
        self.status_code = status
        self._illisible = illisible

    def json(self):
        if self._illisible:
            raise ValueError("pas du JSON")
        return self._payload


class MoteurSimule:
    """Enregistre les requêtes et sert des réponses scriptées."""

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.appels: list[dict] = []

    def post(self, url, headers=None, data=None, timeout=None):
        self.appels.append(
            {"url": url, "headers": headers or {}, "body": json.loads(data), "timeout": timeout}
        )
        return self.reponses.pop(0) if self.reponses else Reponse({"organic": []})


class ModeleSimule:
    """Le modèle derrière le moteur : on vérifie qu'il reçoit bien le reste."""

    name = "modele"

    def __init__(self):
        self.usage = Usage()
        self.appels: list[str] = []

    def queries(self, config, log):
        self.appels.append("queries")
        return ["une requête"]

    def search(self, queries, config, log):
        raise AssertionError("le moteur cherche, pas le modèle")

    def classify(self, digest, config, log):
        self.appels.append("classify")
        return ("sortie", "une fiche")

    def select(self, page, links, config, log):
        self.appels.append("select")
        return list(links)

    def extract(self, url, content, config, categories, log, *, multiple=False):
        self.appels.append("extract")
        return [ExtractedEvent(relevant=True, title="Une sortie")]


def organique(*urls: str, credits: int = 1) -> dict:
    """Une réponse à la forme réellement observée le 1er septembre 2026."""
    return {
        "searchParameters": {"q": "spectacle enfant", "gl": "fr", "hl": "fr"},
        "credits": credits,
        "organic": [
            {"title": f"Titre de {u}", "link": u, "snippet": "un extrait", "position": i + 1}
            for i, u in enumerate(urls)
        ],
    }


@pytest.fixture
def log():
    return RunLog(path=None, verbose=False, stream=io.StringIO())


def provider(moteur, modele=None) -> SerperProvider:
    return SerperProvider(modele or ModeleSimule(), api_key="clé", session=moteur)


def config(**extra) -> Config:
    base = dict(name="t", theme="spectacles", provider="serper")
    base.update(extra)
    return Config(**base)


# ═══════════════════════════════════════════════════════════ la requête


def test_la_requete_part_a_la_bonne_adresse_avec_la_cle(log):
    moteur = MoteurSimule(Reponse(organique("https://agenda.fr/a")))
    provider(moteur).search(["spectacle enfant"], config(), log)

    appel = moteur.appels[0]
    assert appel["url"] == "https://google.serper.dev/search"
    assert appel["headers"]["X-API-KEY"] == "clé"
    assert appel["body"]["q"] == "spectacle enfant"
    # Résultats francophones et localisés : c'est ce que l'outil serveur
    # obtenait par `user_location`.
    assert (appel["body"]["gl"], appel["body"]["hl"]) == ("fr", "fr")


def test_une_requete_par_appel(log):
    moteur = MoteurSimule(
        Reponse(organique("https://a.fr/1")), Reponse(organique("https://b.fr/1"))
    )
    pages = provider(moteur).search(["une", "deux"], config(), log)

    assert [a["body"]["q"] for a in moteur.appels] == ["une", "deux"]
    assert {p.url for p in pages} == {"https://a.fr/1", "https://b.fr/1"}


def test_sans_cle_le_fournisseur_refuse_de_se_construire():
    with pytest.raises(ProviderError, match="SERPER_API_KEY"):
        SerperProvider(ModeleSimule(), api_key=None)


# ═══════════════════════════════════════════════════════════ les résultats


def test_chaque_resultat_porte_son_titre_et_sa_requete(log):
    moteur = MoteurSimule(Reponse(organique("https://agenda.fr/a")))
    pages = provider(moteur).search(["spectacle enfant"], config(), log)

    assert (pages[0].url, pages[0].title, pages[0].query) == (
        "https://agenda.fr/a", "Titre de https://agenda.fr/a", "spectacle enfant",
    )


def test_la_meme_page_remontee_deux_fois_ne_compte_quune(log):
    """La première requête garde la paternité, comme du côté de l'outil serveur."""
    moteur = MoteurSimule(
        Reponse(organique("https://agenda.fr/a")),
        Reponse(organique("https://agenda.fr/a?utm_source=x")),
    )
    pages = provider(moteur).search(["une", "deux"], config(), log)

    assert len(pages) == 1
    assert pages[0].query == "une"


def test_les_domaines_bloques_sont_ecartes_ici(log):
    """Serper ne prend pas de liste d'exclusion : trois lignes de Python font
    le même travail que le paramètre de l'outil serveur."""
    moteur = MoteurSimule(
        Reponse(organique("https://www.facebook.com/evt", "https://agenda.fr/a"))
    )
    pages = provider(moteur).search(["x"], config(blocked_domains=["facebook.com"]), log)

    assert [p.url for p in pages] == ["https://agenda.fr/a"]


def test_une_reponse_sans_resultats_organiques_ne_casse_rien(log):
    moteur = MoteurSimule(Reponse({"searchParameters": {}, "answerBox": {"answer": "42"}}))
    assert provider(moteur).search(["x"], config(), log) == []


# ═══════════════════════════════════════════════════════════ les pannes


@pytest.mark.parametrize(
    "status, attendu",
    [(403, "refusée"), (429, "quota"), (500, "HTTP 500")],
)
def test_une_requete_en_erreur_est_journalisee_sans_tuer_les_autres(status, attendu):
    stream = io.StringIO()
    journal = RunLog(path=None, verbose=True, stream=stream)
    moteur = MoteurSimule(Reponse(None, status=status), Reponse(organique("https://b.fr/1")))
    pages = provider(moteur).search(["une", "deux"], config(), journal)

    assert [p.url for p in pages] == ["https://b.fr/1"], "la seconde requête aboutit"
    assert attendu in stream.getvalue()


def test_si_aucune_requete_naboutit_le_run_doit_le_savoir(log):
    """Sans page de départ, il n'y a rien à lire : autant s'arrêter net."""
    moteur = MoteurSimule(Reponse(None, status=500), Reponse(None, status=500))
    with pytest.raises(ProviderError, match="aucune recherche"):
        provider(moteur).search(["une", "deux"], config(), log)


def test_une_reponse_illisible_est_une_panne_de_requete(log):
    moteur = MoteurSimule(Reponse(None, illisible=True))
    with pytest.raises(ProviderError):
        provider(moteur).search(["une"], config(), log)


# ═══════════════════════════════════════════════════════════ la facture


def test_chaque_requete_est_imputee_au_compteur_du_run(log):
    """Un seul compteur pour tout le run : sinon le plafond de budget n'en
    surveillerait qu'une moitié."""
    modele = ModeleSimule()
    moteur = MoteurSimule(Reponse(organique("https://a.fr/1")), Reponse(organique("https://b.fr/1")))
    p = provider(moteur, modele)
    p.search(["une", "deux"], config(), log)

    assert p.usage is modele.usage, "le moteur et le modèle partagent la facture"
    assert p.usage.web_searches == 2
    assert p.usage.search_cost_usd == pytest.approx(0.002)
    # Dix fois moins que l'outil serveur d'Anthropic, qui facture un centime.
    assert p.usage.search_cost_usd < 2 * 0.01


def test_le_cout_est_celui_que_la_reponse_annonce(log):
    """Serper dit combien de crédits il a pris : on le lit, on ne le déduit pas.

    Une règle de notre cru — « un crédit jusqu'à dix résultats » — finirait par
    diverger de sa grille sans que rien ne le signale.
    """
    moteur = MoteurSimule(Reponse(organique("https://a.fr/1", credits=2)))
    p = provider(moteur)
    p.search(["une"], config(), log)

    assert p.usage.search_cost_usd == pytest.approx(0.002)


def test_sans_le_champ_credits_on_retombe_sur_une_requete(log):
    """Repli : si le champ disparaissait, la facture resterait plausible."""
    reponse = organique("https://a.fr/1")
    del reponse["credits"]
    p = provider(MoteurSimule(Reponse(reponse)))
    p.search(["une"], config(), log)

    assert p.usage.search_cost_usd == pytest.approx(0.001)


def test_moins_de_resultats_que_demande_ne_gene_personne(log):
    """`num` est un souhait, pas un contrat : dix demandés, neuf rendus."""
    moteur = MoteurSimule(Reponse(organique(*[f"https://a.fr/{i}" for i in range(9)])))
    assert len(provider(moteur).search(["une"], config(), log)) == 9


def test_une_requete_en_erreur_nest_pas_facturee(log):
    moteur = MoteurSimule(Reponse(None, status=500))
    p = provider(moteur)
    try:
        p.search(["une"], config(), log)
    except ProviderError:
        pass
    assert p.usage.web_searches == 0


# ═══════════════════════════════════════════ les quatre autres appels


def test_le_modele_garde_tout_ce_qui_demande_du_jugement(log):
    modele = ModeleSimule()
    p = provider(MoteurSimule(), modele)

    assert p.queries(config(), log) == ["une requête"]
    assert p.classify("URL : x", config(), log) == ("sortie", "une fiche")
    assert p.select("https://a.fr", [Link("un lien", "https://a.fr/1", "")], config(), log)
    assert p.extract("https://a.fr/1", "du texte", config(), [], log)
    assert modele.appels == ["queries", "classify", "select", "extract"]
