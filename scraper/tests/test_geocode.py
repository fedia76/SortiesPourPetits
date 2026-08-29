"""Le géocodage, et surtout ce qu'il doit refuser.

Un run « Seine-Maritime » a rendu des sorties correctes… situées à Paris. Trois
causes cumulées : un biais de recherche figé sur le centre de Paris, des
requêtes de repli très lâches (le nom de la salle seul), et plus aucun contrôle
de concordance depuis qu'on avait retiré le filtre par zone.

Ce fichier verrouille la réponse : ce que la page affirme fait foi, et un
résultat qui la contredit est refusé plutôt que publié.
"""

from __future__ import annotations

import pytest

from sortiesbot.geocode import agrees_with_page, geocode
from sortiesbot.models import ExtractedEvent, Location


def lieu(**champs) -> ExtractedEvent:
    base = dict(relevant=True, title="Un spectacle", venue_name="Le Volcan")
    base.update(champs)
    return ExtractedEvent(**base)


def reponse(city: str, postcode: str, lat: float = 49.49, lng: float = 0.10) -> list[dict]:
    return [
        {
            "properties": {"city": city, "postcode": postcode, "countrycode": "FR"},
            "geometry": {"coordinates": [lng, lat]},
        }
    ]


# ------------------------------------------------------- la concordance seule


def test_un_departement_different_est_refuse():
    havre = lieu(venue_city="Le Havre", venue_postal_code="76600")
    assert not agrees_with_page(Location(48.85, 2.35, "Paris", "75011"), havre)


def test_le_meme_departement_suffit():
    """« 76000 Rouen » géocodé « 76100 » reste la même ville : on compare le
    département, pas le code postal entier."""
    rouen = lieu(venue_city="Rouen", venue_postal_code="76000")
    assert agrees_with_page(Location(49.44, 1.09, "Rouen", "76100"), rouen)


def test_sans_code_postal_la_ville_tranche():
    havre = lieu(venue_city="Le Havre")
    assert not agrees_with_page(Location(48.85, 2.35, "Paris", "75011"), havre)
    assert agrees_with_page(Location(49.49, 0.10, "Le Havre", "76600"), havre)


def test_un_arrondissement_est_la_meme_ville():
    paris = lieu(venue_city="Paris")
    assert agrees_with_page(Location(48.85, 2.35, "Paris 11e Arrondissement", "75011"), paris)


def test_une_page_muette_ne_permet_aucun_controle():
    """Rien à quoi comparer : on accepte, et c'est le seul cas où une
    homonymie française passe encore."""
    assert agrees_with_page(Location(48.85, 2.35, "Paris", "75011"), lieu())


def test_l_outre_mer_tient_sur_trois_chiffres():
    reunion = lieu(venue_city="Saint-Denis", venue_postal_code="97400")
    assert agrees_with_page(Location(-20.88, 55.45, "Saint-Denis", "97490"), reunion)
    assert not agrees_with_page(Location(16.24, -61.53, "Saint-Denis", "97100"), reunion)


# ---------------------------------------------------- le géocodage de bout en bout


def test_un_homonyme_parisien_ne_passe_plus():
    """Le cas qui a motivé le correctif : la salle est au Havre, le géocodeur
    répond Paris, et la sortie partait à Paris avec ses coordonnées."""
    havre = lieu(venue_city="Le Havre", venue_postal_code="76600")
    result = geocode(havre, search=lambda q: reponse("Paris", "75011", 48.85, 2.35))

    assert not result.located
    assert "homonymie" in result.reason


def test_une_position_hors_de_france_reste_refusee():
    montreuil = lieu(venue_city="Montreuil", venue_postal_code="93100")
    quebec = [
        {
            "properties": {"city": "Montréal", "postcode": "H2X", "countrycode": "CA"},
            "geometry": {"coordinates": [-73.56, 45.50]},
        }
    ]
    assert not geocode(montreuil, search=lambda q: quebec).located


def test_le_bon_resultat_passe():
    havre = lieu(venue_city="Le Havre", venue_postal_code="76600")
    result = geocode(havre, search=lambda q: reponse("Le Havre", "76600"))

    assert result.located
    assert result.location.city == "Le Havre"


def test_une_requete_plus_precise_rattrape_un_homonyme():
    """La première tentative tombe à Paris, la suivante trouve la bonne : le
    run ne doit pas s'arrêter sur le premier résultat refusé."""
    havre = lieu(venue_address="12 rue de Paris", venue_city="Le Havre", venue_postal_code="76600")
    essais: list[str] = []

    def search(query: str) -> list[dict]:
        essais.append(query)
        return reponse("Paris", "75010") if len(essais) == 1 else reponse("Le Havre", "76600")

    result = geocode(havre, search=search)
    assert result.located and result.location.postal_code == "76600"
    assert len(essais) >= 2


def test_aucun_biais_geographique_n_est_envoye(monkeypatch):
    """Le biais valait « préférez Paris » pour toutes les recherches, quelle
    que soit leur zone. Il ne doit plus rien partir de tel."""
    from sortiesbot import geocode as g

    envoye: dict = {}

    class FausseReponse:
        @staticmethod
        def raise_for_status() -> None: ...

        @staticmethod
        def json() -> dict:
            return {"features": []}

    def fausse_requete(url, params=None, **kwargs):
        envoye.update(params or {})
        return FausseReponse()

    monkeypatch.setattr(g.requests, "get", fausse_requete)
    g._photon_search("Le Volcan, Le Havre")

    assert "lat" not in envoye and "lon" not in envoye


@pytest.mark.parametrize("champ", ["venue_city", "venue_postal_code"])
def test_le_geocodeur_ne_reecrit_pas_ce_que_la_page_dit(champ):
    """Garde-fou du payload : c'est là que l'écrasement se produisait."""
    from sortiesbot.payload import build_payload

    event = lieu(
        title="Un spectacle au Havre",
        description="Une description bien assez longue pour passer la validation du payload.",
        free=True,
        venue_address="1 place du Général de Gaulle",
        venue_city="Le Havre",
        venue_postal_code="76600",
        permanent=True,
    )
    payload = build_payload(event, Location(48.85, 2.35, "Paris", "75011"), 1, "https://x.fr/a")

    attendu = {"venue_city": ("city", "Le Havre"), "venue_postal_code": ("postalCode", "76600")}
    cle, valeur = attendu[champ]
    assert payload["venue"][cle] == valeur
