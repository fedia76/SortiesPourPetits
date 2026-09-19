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


def test_un_seuil_n_existe_que_mesure():
    """La leçon vaut plus que les valeurs.

    `price` et `times` avaient été montés à 0,6 sur un raisonnement qui se
    tenait : un tarif faux part en ligne, une page affiche des heures partout.
    Le banc a dit non — le tarif est passé de 35 justes à 29, les horaires de
    50 à 43. Monter une barre n'améliore pas un choix : elle retire des
    candidats, et retirer le mauvais ne laisse pas le bon, ça laisse le
    suivant. Ces deux-là sont revenus au défaut, et ce test existe pour qu'on
    ne les remette pas sans mesure.
    """
    assert "price" not in SEUILS
    assert "times" not in SEUILS
    assert seuil_de("price") == seuil_de("venue_name")


def test_l_age_garde_le_sien_parce_qu_un_run_l_a_confirme():
    # 73 valeurs manquées sur 140 avant, 35 après l'avoir baissé.
    assert seuil_de("age_min") < seuil_de("venue_name")


def test_un_span_sous_le_seuil_de_son_champ_est_ecarte():
    sous = seuil_de("venue_name") - 0.05
    event = to_event([span("title", "Atelier"), span("venue_name", "Théâtre", score=sous)])
    assert event.venue_name == ""
    # Le même score passe sur un champ plus tolérant.
    assert to_event([span("age_min", "3 ans", score=sous)]).age_min == 3


# ───────────────────────────────── les bornes que la page déclare elle-même


def test_les_bornes_declarees_battent_la_prose():
    """L'aspect « dates » n'avait pas bougé d'un point : 20 justes sur 140.

    Même cause que le titre, même remède — la page annonce ses dates dans son
    JSON-LD, on les calculait déjà, et personne ne les donnait à l'extraction.
    """
    event = to_event(
        [span("dates", "du 3 au 12 septembre 2026")],
        hints={"date_start": "2026-08-03", "date_end": "2026-08-12"},
    )
    assert (event.date_start, event.date_end) == ("2026-08-03", "2026-08-12")


def test_sans_borne_declaree_la_prose_reste_la_source():
    from datetime import date

    event = to_event([span("dates", "du 3 au 12 août 2026")], today=date(2026, 7, 1))
    assert (event.date_start, event.date_end) == ("2026-08-03", "2026-08-12")


def test_une_borne_impossible_est_refusee():
    """Un JSON-LD vient d'un générateur tiers : « 30 février » passe sa forme."""
    event = to_event([span("title", "Atelier")], hints={"date_start": "2026-02-30"})
    assert event.date_start == ""


def test_une_fin_avant_le_debut_est_ecartee():
    """Puis la sortie tient sur son seul jour connu, comme partout ailleurs."""
    event = to_event([], hints={"date_start": "2026-08-12", "date_end": "2026-08-03"})
    assert (event.date_start, event.date_end) == ("2026-08-12", "2026-08-12")


def test_une_sortie_d_un_jour_a_une_date_de_fin():
    """Et c'est le même jour — c'est ainsi que le site la stocke.

    `payload._clean_dates` fait `end = end or start`, donc le corpus porte
    toujours une date de fin. Rendre une fin vide comptait faux **toute**
    sortie d'un jour, quelles que soient ses dates par ailleurs.
    """
    event = to_event([], hints={"date_start": "2026-08-12"})
    assert (event.date_start, event.date_end) == ("2026-08-12", "2026-08-12")


def test_connaitre_une_plage_c_est_savoir_qu_elle_n_est_pas_permanente():
    """Le `null` de trop, et ce qu'il a coûté.

    Le corpus porte toujours un booléen — `isPermanent` est une colonne du
    site — et la comparaison d'un aspect exige que **tous** ses champs
    concordent. Un `null` en face d'un `false` faisait donc échouer l'aspect
    entier, dates justes comprises : vingt fiches justes devenues zéro.
    """
    assert to_event([], hints={"date_start": "2026-08-12"}).permanent is False
    # Sans la moindre date, en revanche, on ne se prononce toujours pas.
    assert to_event([span("title", "Atelier")]).permanent is None


# ──────────────────────────────────────── l'adresse, réduite à son contrat


def test_l_adresse_perd_le_code_postal_et_la_ville():
    """Le champ vaut « numéro et rue » — le corpus est étiqueté ainsi.

    Un span qui ramène l'adresse entière n'est pas faux, il est trop long. Le
    comparer tel quel comptait « faux » une adresse correctement lue.
    """
    event = to_event([], hints={"venue_address": "14 rue des Écoles, 94000 Créteil"})
    assert event.venue_address == "14 rue des Écoles"


def test_une_adresse_deja_courte_ne_bouge_pas():
    event = to_event([], hints={"venue_address": "14 rue des Écoles"})
    assert event.venue_address == "14 rue des Écoles"


def test_le_code_postal_reste_dans_son_champ():
    event = to_event(
        [],
        hints={"venue_address": "14 rue des Écoles 94000 Créteil", "venue_postal_code": "94000"},
    )
    assert event.venue_address == "14 rue des Écoles"
    assert event.venue_postal_code == "94000"


# ──────────────────────────── ne rien affirmer quand on n'a rien lu


def test_un_tarif_jamais_lu_reste_inconnu():
    """`False` affirme « ce n'est pas gratuit ». C'est un jugement, pas un défaut.

    Le banc lisait 111 « tarifs faux » sur une brique qui, la plupart du
    temps, n'avait rien trouvé. Détecter mieux et choisir mieux ne se
    corrigent pas au même endroit, et le tableau ne les distinguait pas.
    """
    event = to_event([span("title", "Atelier")])
    assert event.free is None
    assert event.price is None


def test_un_tarif_lu_se_prononce():
    assert to_event([span("price", "8 €")]).free is False
    assert to_event([span("price", "8 €")]).price == 8.0
    assert to_event([span("price", "entrée libre")]).free is True


def test_un_span_de_tarif_illisible_ne_fait_pas_affirmer():
    """« salle 8 » n'est pas un tarif : on n'en conclut pas « payant »."""
    event = to_event([span("price", "salle 8")])
    assert event.free is None


def test_la_permanence_n_est_jamais_affirmee_par_l_etiqueteur():
    """Un étiqueteur ne rend que des morceaux de page ; la permanence n'en est pas un."""
    assert to_event([span("title", "Atelier")]).permanent is None


def test_le_modele_qui_tranche_garde_son_verdict():
    """Rien ne change pour le fournisseur dont le schéma exige le champ."""
    from sortiesbot.models import ExtractedEvent

    rendu = ExtractedEvent.from_json({"relevant": True, "free": False, "permanent": False})
    assert rendu.free is False
    assert rendu.permanent is False


def test_une_cle_absente_vaut_inconnu():
    from sortiesbot.models import ExtractedEvent

    rendu = ExtractedEvent.from_json({"relevant": True})
    assert rendu.free is None
    assert rendu.permanent is None


def test_la_production_ne_voit_aucune_difference():
    """Tout ce qui consomme ces champs teste leur vérité : `None` y vaut `False`."""
    from datetime import date

    from sortiesbot.models import ExtractedEvent, Location
    from sortiesbot.payload import build_payload

    event = ExtractedEvent(
        relevant=True,
        title="Atelier poterie",
        description="Un atelier pour les enfants, à partir de six ans.",
        date_start="2026-08-03",
        venue_name="Maison des arts",
        venue_address="2 rue des Lilas",
        venue_city="Nancy",
        venue_postal_code="54000",
    )
    payload = build_payload(
        event,
        Location(lat=48.7, lng=6.2, city="Nancy", postal_code="54000"),
        category_id=1,
        source_url="https://exemple.fr/atelier",
        today=date(2026, 7, 1),
    )
    assert payload["isFree"] is False
    assert payload["isPermanent"] is False
