"""Le trajet du corpus jusqu'aux exemples, sur de vraies pages gelées.

Ce que ces tests verrouillent n'est pas la qualité du modèle — ça se mesure
sur le banc — mais la seule chose qui puisse la ruiner en silence : qu'on
entraîne sur autre chose que ce qu'on lira. Le texte soumis à l'entraînement
doit être celui que l'étage 5 produira en production, et le titre celui que
l'étage 6 recevra.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("sklearn", reason="extra « classifieur » non installé")

from tools.classifieur_entrainer import _exemples, _recolter

PAGES = Path(__file__).parent / "fixtures" / "pages"


class FauxSite:
    """Le corpus servi par tranches, comme la vraie route le fait."""

    def __init__(self, items, tranche=2):
        self.items, self.tranche = items, tranche
        self.demandes: list[tuple[int, int]] = []

    def labelled_sorties(self, after=0, limit=10):
        self.demandes.append((after, limit))
        restants = [i for i in self.items if i["sortieId"] > after][: self.tranche]
        suivant = restants[-1]["sortieId"] if len(restants) == self.tranche else 0
        return restants, suivant


def _page(nom: str) -> str:
    return (PAGES / nom).read_text(encoding="utf-8")


def _item(sortie_id: int, nom: str, url: str, categorie: str, *, brut=False) -> dict:
    etiquette = {"category": categorie, "title": "peu importe"}
    return {
        "sortieId": sortie_id,
        "url": url,
        # La route rend le JSON tel qu'il est stocké — une chaîne. Le worker
        # doit accepter les deux : un test qui n'essaierait qu'un objet
        # laisserait passer la seule forme qui arrive vraiment.
        "expected": json.dumps(etiquette) if brut else etiquette,
        "html": _page(nom),
    }


def test_le_corpus_se_parcourt_par_curseur_jusqu_au_bout():
    site = FauxSite(
        [
            _item(1, "spectacle-avec-json-ld.html", "https://a.fr/1", "Spectacle"),
            _item(2, "atelier-sans-donnees-structurees.html", "https://b.fr/2", "Atelier"),
            _item(3, "spectacle-avec-json-ld.html", "https://a.fr/3", "Spectacle", brut=True),
        ]
    )
    recolte = _recolter(site, limite=10)
    assert len(recolte) == 3
    # Le curseur avance sur le dernier identifiant **servi**, jamais sur un
    # décalage : le corpus grossit pendant qu'on le parcourt. Et une tranche
    # incomplète clôt le parcours — sans ça, on redemanderait indéfiniment.
    assert [d[0] for d in site.demandes] == [0, 2]


def test_la_limite_arrete_la_recolte():
    site = FauxSite([_item(i, "spectacle-avec-json-ld.html", f"https://a.fr/{i}", "S") for i in range(1, 8)])
    assert len(_recolter(site, limite=3)) == 3


def test_le_texte_appris_est_celui_que_l_etage_5_rend():
    """Le piège que ce test ferme : entraîner sur le HTML, ou sur un texte
    recalculé autrement, puis servir à l'inférence le texte de l'étage 5."""
    site = FauxSite([_item(1, "spectacle-avec-json-ld.html", "https://a.fr/1", "Spectacle")])
    exemples, ecartes = _exemples(_recolter(site, limite=10))
    assert ecartes == 0
    assert len(exemples) == 1
    assert "<html" not in exemples[0].texte
    assert exemples[0].etiquette == "Spectacle"
    assert exemples[0].groupe == "a.fr"


def test_le_titre_declare_par_la_page_pese_dans_les_traits():
    """Le même titre qu'à l'inférence — `facts["title"]`, le JSON-LD ou le h1.

    Prendre ici le titre de l'**étiquette** ferait un modèle superbe à
    l'entraînement et sans valeur en production : ce titre-là est la réponse,
    et il n'existe pas quand la page arrive.
    """
    site = FauxSite([_item(1, "spectacle-avec-json-ld.html", "https://a.fr/1", "Spectacle")])
    exemples, _ = _exemples(_recolter(site, limite=10))
    assert "peu importe" not in exemples[0].texte


def test_une_page_sans_categorie_etiquetee_est_ecartee_et_comptee():
    """Clé absente veut dire « personne n'a regardé », pas « aucune catégorie » :
    l'apprendre comme une classe vide enseignerait le contraire de la vérité."""
    site = FauxSite(
        [
            _item(1, "spectacle-avec-json-ld.html", "https://a.fr/1", ""),
            _item(2, "atelier-sans-donnees-structurees.html", "https://b.fr/2", "Atelier"),
        ]
    )
    exemples, ecartes = _exemples(_recolter(site, limite=10))
    assert ecartes == 1
    assert [e.etiquette for e in exemples] == ["Atelier"]


def test_une_page_dont_le_html_a_disparu_ne_devient_pas_un_exemple_vide():
    site = FauxSite([{"sortieId": 1, "url": "https://a.fr/1", "expected": {}, "html": ""}])
    assert _recolter(site, limite=10) == []


def test_l_entrainement_ne_va_pas_sur_le_reseau():
    """Deux entraînements lancés à un mois d'intervalle doivent porter sur le
    même corpus. Un échange de langue qui interroge un site tiers rendrait ça
    faux sans prévenir."""
    html = gzip.decompress(gzip.compress(_page("spectacle-avec-json-ld.html").encode())).decode()
    site = FauxSite([{"sortieId": 1, "url": "https://a.fr/1", "expected": {"category": "S"}, "html": html}])
    # Aucune exception : le lecteur hors ligne refuse la requête, et l'étage 5
    # se rabat sur la page qu'on lui a donnée.
    assert len(_recolter(site, limite=10)) == 1


def test_l_exemple_porte_son_adresse_et_la_presence_d_un_lieu():
    """Deux renseignements qui ne servent pas au modèle, seulement au diagnostic.

    L'adresse, pour pouvoir **ouvrir** les pages qu'il rate : un tableau de
    confusions dit qu'on prend onze musées pour des ateliers, il ne dit pas si
    le modèle a tort ou si la frontière n'est pas tenable depuis le texte.

    La présence d'un lieu, pour savoir **quelles classes** le trait couvre :
    une couverture globale de 37 % ne dit rien s'il manque précisément aux
    pages qu'il devait sauver.
    """
    site = FauxSite([_item(1, "spectacle-avec-json-ld.html", "https://a.fr/1", "Spectacle")])
    exemples, _ = _exemples(_recolter(site, limite=10))
    assert exemples[0].url == "https://a.fr/1"
    assert isinstance(exemples[0].lieu, bool)


def test_sans_lieu_le_trait_disparait_des_traits_mais_pas_du_diagnostic():
    """On doit pouvoir dire « ce corpus déclare des lieux » tout en mesurant
    sans eux : sinon la comparaison des deux runs perd son repère."""
    site = FauxSite([_item(1, "spectacle-avec-json-ld.html", "https://a.fr/1", "Spectacle")])
    recolte = _recolter(site, limite=10)
    avec, _ = _exemples(recolte)
    sans, _ = _exemples(recolte, sans_lieu=True)
    assert avec[0].lieu == sans[0].lieu
    if avec[0].lieu:
        assert avec[0].texte != sans[0].texte
