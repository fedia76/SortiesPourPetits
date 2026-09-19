"""Ce que la page déclare d'elle-même, et pourquoi ça l'emporte sur le modèle.

Le banc a chiffré le trou : sur 140 pages, l'étiquetage seul a rendu un titre
**15 fois**. Non pas parce qu'il lit mal, mais parce qu'il ne l'a jamais vu —
`page_text` décompose les `<header>`, où vit presque toujours le `h1`. Un
modèle génératif compense en devinant du corps de la page ; un étiqueteur de
spans ne rend que ce qu'il lit.

Et cette seule absence en coûtait deux au tableau : `relevant` suit le titre,
donc 125 titres manqués faisaient 125 verdicts faux.
"""

from __future__ import annotations

from sortiesbot.harvest import first_heading, json_ld_facts
from sortiesbot.spans import LABELS, SEUILS, Span, seuil_de, to_event

PAR_CHAMP = {champ: libelle for libelle, champ in LABELS.items()}


def span(champ: str, text: str, score: float = 0.9) -> Span:
    return Span(label=PAR_CHAMP[champ], text=text, score=score)


# ────────────────────────────────────────────── ce que le HTML déclare


def test_le_h1_se_lit_meme_quand_page_text_l_emporte():
    html = """
    <html><body>
      <header><h1>Le Petit Chaperon rouge</h1></header>
      <main><p>Un spectacle pour les enfants.</p></main>
    </body></html>
    """
    from sortiesbot.harvest import page_text

    assert first_heading(html) == "Le Petit Chaperon rouge"
    # La démonstration du trou : le titre n'est pas dans ce qu'on soumet.
    assert "Chaperon" not in page_text(html)


def test_le_title_sert_de_repli_sans_h1():
    assert first_heading("<html><head><title>Atelier poterie</title></head></html>") == (
        "Atelier poterie"
    )


def test_une_page_sans_rien_ne_declare_rien():
    assert first_heading("<html><body><p>bonjour</p></body></html>") == ""
    assert json_ld_facts("<html><body><p>bonjour</p></body></html>") == {}


def test_le_json_ld_rend_le_lieu_et_le_tarif():
    html = """
    <html><body><script type="application/ld+json">
    {"@type": "TheaterEvent", "name": "Le Petit Prince",
     "location": {"@type": "Place", "name": "Théâtre du Chapiteau",
       "address": {"streetAddress": "14 rue des Écoles",
                   "addressLocality": "Créteil", "postalCode": "94000"}},
     "offers": {"@type": "Offer", "price": "8"}}
    </script></body></html>
    """
    faits = json_ld_facts(html)
    assert faits["title"] == "Le Petit Prince"
    assert faits["venue_name"] == "Théâtre du Chapiteau"
    assert faits["venue_city"] == "Créteil"
    assert faits["venue_postal_code"] == "94000"
    assert faits["price"] == 8.0


def test_un_prix_a_zero_annonce_la_gratuite():
    """« 0 € » sur une fiche, c'est ce qu'un parent ne doit jamais lire."""
    html = """
    <html><body><script type="application/ld+json">
    {"@type": "Event", "name": "Contes au parc",
     "offers": {"price": 0}}</script></body></html>
    """
    faits = json_ld_facts(html)
    assert faits["free"] is True
    assert "price" not in faits


def test_un_json_ld_casse_ne_fait_rien_perdre_d_autre():
    html = """
    <html><body>
      <script type="application/ld+json">{ ceci n'est pas du JSON</script>
      <script type="application/ld+json">{"@type":"Event","name":"Atelier"}</script>
    </body></html>
    """
    assert json_ld_facts(html)["title"] == "Atelier"


def test_ce_qui_n_est_pas_un_evenement_est_ignore():
    html = """
    <html><body><script type="application/ld+json">
    {"@type": "Organization", "name": "Ville de Nancy"}</script></body></html>
    """
    assert json_ld_facts(html) == {}


# ──────────────────────────────── les faits déclarés l'emportent sur les spans


def test_le_titre_declare_bat_le_span():
    """Une valeur écrite par l'organisateur n'est pas une opinion de plus."""
    event = to_event(
        [span("title", "Billetterie en ligne", score=0.99)],
        hints={"title": "Le Petit Chaperon rouge"},
    )
    assert event.title == "Le Petit Chaperon rouge"
    # Et le verdict suit : sans titre, la page était déclarée « pas une sortie ».
    assert event.relevant is True


def test_sans_fait_declare_le_span_reste_la_source():
    event = to_event([span("title", "Le Petit Chaperon rouge")])
    assert event.title == "Le Petit Chaperon rouge"


def test_le_tarif_declare_bat_le_span():
    event = to_event([span("price", "4 €")], hints={"price": 8.0})
    assert (event.free, event.price) == (False, 8.0)


def test_la_gratuite_declaree_ecarte_le_span():
    event = to_event([span("price", "12 €")], hints={"free": True})
    assert event.free is True
    assert event.price is None


def test_l_adresse_declaree_bat_les_spans():
    event = to_event(
        [span("venue_city", "Paris"), span("venue_postal_code", "75001")],
        hints={"venue_city": "Créteil", "venue_postal_code": "94000"},
    )
    assert event.venue_city == "Créteil"
    assert event.venue_postal_code == "94000"


def test_un_code_postal_declare_reste_valide_ou_disparait():
    """Le site refuse ce qui n'a pas cinq chiffres : autant le voir ici."""
    assert to_event([], hints={"venue_postal_code": "Cedex 9"}).venue_postal_code == ""
    assert to_event([], hints={"venue_postal_code": "94000"}).venue_postal_code == "94000"


def test_des_faits_vides_ne_masquent_pas_les_spans():
    event = to_event([span("title", "Atelier")], hints={"title": "   "})
    assert event.title == "Atelier"


# ────────────────────────────────────────────── les seuils, champ par champ


def test_chaque_champ_a_son_seuil():
    # Une heure fausse part en ligne ; un lieu faux se corrige en modération.
    assert seuil_de("times") > seuil_de("venue_name")
    assert seuil_de("price") > seuil_de("venue_name")
    # L'âge manquait 73 fois sur 140 : il était trop timide.
    assert seuil_de("age_min") < seuil_de("venue_name")


def test_un_span_sous_le_seuil_de_son_champ_est_ecarte():
    sous = SEUILS["times"] - 0.05
    event = to_event([span("title", "Atelier"), span("times", "14h30", score=sous)])
    assert event.open_time == ""
    # Le même score passerait sur un champ plus tolérant.
    assert to_event([span("age_min", "3 ans", score=sous)]).age_min == 3
