"""La couche pure : des spans à une fiche, sans modèle et sans réseau.

Ces tests sont le vrai filet de l'expérience GLiNER. Ce qui casse dans une
extraction par spans n'est presque jamais l'étiqueteur — il rend des morceaux
de page, et il les rend bien ou mal, ce qui se mesure au banc. Ce qui casse,
c'est la **normalisation** : une date française mal lue, un tarif pris pour
un code postal, une plage « du 3 au 12 » réduite au 12. Ça, ça se teste ici,
à la milliseconde et sans carte graphique.
"""

from __future__ import annotations

from datetime import date

from sortiesbot.spans import (
    LABELS,
    Span,
    parse_age,
    parse_dates,
    parse_heure,
    parse_jours,
    parse_tarif,
    to_event,
    unfilled_fields,
)

AUJOURD_HUI = date(2026, 7, 1)


def span(label: str, text: str, score: float = 0.9) -> Span:
    return Span(label=label, text=text, score=score)


# ─────────────────────────────────────────────────────────────────── les dates


def test_plage_rend_ses_deux_bornes():
    """« du 3 au 12 août » : sans traitement de la plage, le 3 serait perdu."""
    assert parse_dates("du 3 au 12 août 2026", AUJOURD_HUI) == [
        date(2026, 8, 3),
        date(2026, 8, 12),
    ]


def test_plage_a_cheval_sur_deux_mois():
    assert parse_dates("du 28 juillet au 2 août 2026", AUJOURD_HUI) == [
        date(2026, 7, 28),
        date(2026, 8, 2),
    ]


def test_les_quatre_ecritures():
    assert parse_dates("3 août 2026", AUJOURD_HUI) == [date(2026, 8, 3)]
    assert parse_dates("03/08/2026", AUJOURD_HUI) == [date(2026, 8, 3)]
    assert parse_dates("2026-08-03", AUJOURD_HUI) == [date(2026, 8, 3)]
    assert parse_dates("1er août 2026", AUJOURD_HUI) == [date(2026, 8, 1)]


def test_annee_absente_prend_l_annee_en_cours():
    assert parse_dates("12 août", AUJOURD_HUI) == [date(2026, 8, 12)]


def test_annee_absente_bien_passee_bascule_sur_l_an_prochain():
    """Une affiche parle de ce qui vient : « 3 février » vu en juillet, c'est 2027."""
    assert parse_dates("3 février", AUJOURD_HUI) == [date(2027, 2, 3)]


def test_annee_absente_juste_passee_reste_cette_annee():
    """La tolérance évite de projeter en 2027 un festival commencé la semaine dernière."""
    assert parse_dates("20 juin", AUJOURD_HUI) == [date(2026, 6, 20)]


def test_date_impossible_est_ignoree():
    assert parse_dates("32 août 2026", AUJOURD_HUI) == []
    assert parse_dates("30/02/2026", AUJOURD_HUI) == []


def test_texte_sans_date():
    assert parse_dates("spectacle pour toute la famille", AUJOURD_HUI) == []


# ─────────────────────────────────────────────────────────────── tarif et âge


def test_gratuit_se_lit_en_toutes_lettres():
    assert parse_tarif("Entrée libre") == (True, None)
    assert parse_tarif("Gratuit pour tous") == (True, None)


def test_tarif_exige_une_monnaie():
    """Un nombre nu ne prouve rien : « 8 » traîne dans n'importe quel texte."""
    assert parse_tarif("8 €") == (False, 8.0)
    assert parse_tarif("8,50 €") == (False, 8.5)
    assert parse_tarif("12 euros") == (False, 12.0)
    assert parse_tarif("salle 8") == (False, None)


def test_age_en_annees_et_en_mois():
    assert parse_age("à partir de 3 ans") == 3
    assert parse_age("dès 18 mois") == 1
    assert parse_age("tout public") is None


def test_heures():
    assert parse_heure("14h30") == "14:30"
    assert parse_heure("14 h") == "14:00"
    assert parse_heure("9:05") == "09:05"
    assert parse_heure("25h") == ""


def test_jours_dans_l_ordre_de_la_semaine():
    assert parse_jours("les samedis et mercredis") == ["mercredi", "samedi"]


# ──────────────────────────────────────────────────────────── l'assemblage


def _spans_complets() -> list[Span]:
    par_champ = {v: k for k, v in LABELS.items()}
    return [
        span(par_champ["title"], "Petits Pas dans les Bois"),
        span(par_champ["venue_name"], "Théâtre de la Clairière"),
        span(par_champ["venue_address"], "12 rue des Lilas"),
        span(par_champ["venue_city"], "Nancy"),
        span(par_champ["venue_postal_code"], "54000"),
        span(par_champ["price"], "8 €"),
        span(par_champ["age_min"], "3 ans"),
        span(par_champ["dates"], "du 3 au 12 août 2026"),
        span(par_champ["times"], "14h30"),
        span(par_champ["weekdays"], "tous les dimanches"),
    ]


def test_fiche_complete():
    event = to_event(_spans_complets(), today=AUJOURD_HUI)
    assert event.relevant is True
    assert event.title == "Petits Pas dans les Bois"
    assert event.venue_name == "Théâtre de la Clairière"
    assert event.venue_postal_code == "54000"
    assert (event.free, event.price) == (False, 8.0)
    assert event.age_min == 3
    assert (event.date_start, event.date_end) == ("2026-08-03", "2026-08-12")
    assert event.dates == ("2026-08-03", "2026-08-12")
    assert event.weekdays == ("dimanche",)
    assert event.open_time == "14:30"


def test_les_champs_hors_portee_restent_vides():
    """Le point de toute l'expérience : ne pas fabriquer un chiffre vert.

    `description`, `setting` et `category` ne sont pas des morceaux de page. Le
    banc comptera `MANQUE`, et c'est la mesure juste — les remplir au jugé
    donnerait un aspect vert sans rien apprendre, `evalMetrics.pareil` rendant
    `true` sans condition sur le genre `prose`.
    """
    event = to_event(_spans_complets(), today=AUJOURD_HUI)
    assert event.description == ""
    assert event.setting == ""
    assert event.category == ""
    assert event.several is False
    assert event.photo_url == ""
    assert "description" in unfilled_fields()


def test_sous_le_seuil_rien_n_est_retenu():
    faibles = [Span(label=lbl, text="n'importe quoi", score=0.1) for lbl in LABELS]
    event = to_event(faibles, today=AUJOURD_HUI)
    assert event.relevant is False
    assert event.skip_reason


def test_le_mieux_note_gagne():
    par_champ = {v: k for k, v in LABELS.items()}
    event = to_event(
        [
            span(par_champ["title"], "Navigation du site", score=0.55),
            span(par_champ["title"], "Le Petit Chaperon rouge", score=0.95),
        ],
        today=AUJOURD_HUI,
    )
    assert event.title == "Le Petit Chaperon rouge"


def test_une_seule_date_ne_fabrique_pas_de_calendrier():
    """Une date unique est la date de la sortie, pas une liste de représentations.

    La **plage**, elle, existe bien : elle tient sur ce jour-là, début et fin
    confondus. C'est ainsi que le site la stocke, et donc ainsi que le corpus
    la porte — voir `payload._clean_dates`.
    """
    par_champ = {v: k for k, v in LABELS.items()}
    event = to_event(
        [span(par_champ["title"], "Atelier"), span(par_champ["dates"], "12 août 2026")],
        today=AUJOURD_HUI,
    )
    assert (event.date_start, event.date_end) == ("2026-08-12", "2026-08-12")
    # Le calendrier, lui, reste vide : une date n'est pas une récurrence.
    assert event.dates == ()


def test_label_inconnu_est_ignore():
    par_champ = {v: k for k, v in LABELS.items()}
    event = to_event(
        [span(par_champ["title"], "Atelier"), span("couleur préférée", "bleu")],
        today=AUJOURD_HUI,
    )
    assert event.title == "Atelier"


def test_fiche_vide_sur_aucun_span():
    event = to_event([], today=AUJOURD_HUI)
    assert event.relevant is False
    assert event.title == ""


# ─────────────────── quatre défauts que la comparaison avec le modèle a révélés
#
# Haiku ratait 11 âges sur 81, l'étiqueteur 52 sur 140. Un tel écart sur un
# champ aussi simple ne se règle pas au seuil : c'était du code fautif.


def test_un_nombre_nu_n_est_pas_un_age():
    """« tarif 8 € » rendait « 8 ans », « salle 3 » rendait « 3 ans »."""
    assert parse_age("tarif 8 €") is None
    assert parse_age("salle 3") is None
    assert parse_age("réservation au 06") is None


def test_un_age_annonce_reste_lu():
    assert parse_age("à partir de 3 ans") == 3
    assert parse_age("dès 18 mois") == 1
    # Sans unité, mais avec la tournure qui l'annonce — celle que le prompt
    # de production décrit, et qu'`ancrage._age_in` cherche déjà dans la page.
    assert parse_age("à partir de 6") == 6
    # Deux âges dans un morceau : on prend le premier. Une sortie annoncée
    # trop jeune se corrige en modération, une annoncée trop vieille se cache
    # aux parents à qui elle convenait.
    assert parse_age("pour les 3 à 6 ans") == 3
    assert parse_age("jusqu'à 12 ans") == 12


def test_une_exclusion_n_est_pas_une_representation():
    """La pire faute de l'étage : elle n'est pas approximative, elle est inversée.

    « relâche le lundi » enregistrait le lundi comme jour de représentation,
    c'est-à-dire exactement le jour où la sortie ne se joue pas.
    """
    assert parse_jours("relâche le lundi") == []
    assert parse_jours("fermé le mardi") == []
    assert parse_jours("tous les jours sauf le mercredi") == []
    assert parse_jours("pas de séance le jeudi") == []


def test_une_ferme_pedagogique_n_est_pas_une_fermeture():
    """`flatten` retire les accents : « fermé » et « ferme » se confondent.

    Un lieu de sortie très fréquent ne doit pas faire taire un jour réel.
    """
    assert parse_jours("la ferme pédagogique ouvre le samedi") == ["samedi"]


def test_une_plage_de_jours_se_deroule():
    """« du mardi au jeudi » perdait le mercredi."""
    assert parse_jours("du mardi au jeudi") == ["mardi", "mercredi", "jeudi"]


def test_une_plage_peut_enjamber_la_semaine():
    assert parse_jours("du vendredi au lundi") == ["vendredi", "samedi", "dimanche", "lundi"]


def test_l_horaire_retenu_est_le_mieux_note():
    """Et non le minimum et le maximum de toute la page.

    Sur « ouvert de 9h à 18h, spectacle à 14h30 », l'ancienne règle rendait
    09:00–18:00 quand le modèle avait désigné 14h30 avec le meilleur score.
    Une page affiche des heures partout, et les agréger mélange des faits qui
    n'ont rien à voir.
    """
    par_champ = {v: k for k, v in LABELS.items()}
    event = to_event(
        [
            span(par_champ["title"], "Spectacle"),
            span(par_champ["times"], "9h", score=0.55),
            span(par_champ["times"], "14h30", score=0.95),
            span(par_champ["times"], "18h", score=0.60),
        ],
        today=AUJOURD_HUI,
    )
    assert event.open_time == "14:30"
    # Deux spans distincts sont deux faits distincts : pas de fermeture ici.
    assert event.close_time == ""


def test_une_fermeture_se_lit_dans_le_meme_morceau():
    par_champ = {v: k for k, v in LABELS.items()}
    event = to_event(
        [span(par_champ["times"], "de 14h30 à 16h")],
        today=AUJOURD_HUI,
    )
    assert (event.open_time, event.close_time) == ("14:30", "16:00")


def test_les_heures_gardent_l_ordre_du_texte():
    """Trier échangerait ouverture et fermeture sur une séance qui passe minuit."""
    from sortiesbot.spans import parse_heures

    assert parse_heures("de 22h30 à 01h") == ["22:30", "01:00"]
