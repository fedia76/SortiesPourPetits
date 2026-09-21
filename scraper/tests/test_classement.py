"""Le cadre, et la leçon d'une classification qui n'a rien rendu.

Deux champs de la fiche ne sont pas des morceaux de page : la **catégorie**
est un choix dans un référentiel, le **cadre** une déduction. On a essayé de
les faire rendre par le modèle, en écrivant les réponses possibles en tête du
texte — le détournement que la bibliothèque de GLiNER emploie elle-même.

Mesuré sur le banc : **0 juste sur 16** pour la catégorie, 10 sur 140 pour le
cadre. Le détournement ne tient qu'avec un point de contrôle entraîné à ce
format ; `urchade/gliner_multi-v2.1` est un modèle d'entités pur, et il
surlignait une réponse au hasard parmi celles que le gabarit lui énumérait.

Ce qui reste, c'est ce que les dix justes du cadre étaient réellement : de
l'appariement de chaîne sur des pages qui écrivent « en plein air » en toutes
lettres. Fait ici sans modèle.
"""

from __future__ import annotations

from sortiesbot.spans import CADRES, cadre_lu, unfilled_fields

# ────────────────────────────────────────────── ce que la page écrit vraiment


def test_le_plein_air_est_lu():
    assert cadre_lu("Une chasse au trésor en plein air dans le parc.") == "OUTDOOR"


def test_l_interieur_est_lu():
    assert cadre_lu("Atelier en intérieur, salle chauffée.") == "INDOOR"


def test_les_deux_tournures_ensemble_valent_both():
    """« Spectacle en salle puis goûter en plein air » : pas la première venue."""
    lu = cadre_lu("Le spectacle se tient en salle, le goûter en plein air.")
    assert lu == "BOTH"


def test_les_variantes_courantes_sont_lues():
    assert cadre_lu("La visite se déroule en extérieur.") == "OUTDOOR"
    assert cadre_lu("Le musée est à l'intérieur.") == "INDOOR"


def test_la_casse_et_les_accents_ne_comptent_pas():
    """Un titre crie parfois : « SPECTACLE EN PLEIN AIR »."""
    assert cadre_lu("SPECTACLE EN PLEIN AIR") == "OUTDOOR"
    assert cadre_lu("Atelier en interieur") == "INDOOR"


# ────────────────────────────────────────────── et ce qu'on refuse de deviner


def test_une_page_muette_ne_rend_rien():
    """Un `MANQUE` se corrige, un `FAUX` se propage jusqu'à la fiche publiée.

    Trancher au hasard entre trois valeurs, c'est se tromper deux fois sur
    trois : le silence vaut mieux.
    """
    assert cadre_lu("Venez nombreux à la fête du village, entrée libre.") == ""
    assert cadre_lu("") == ""


def test_un_mot_isole_ne_suffit_pas():
    """« air », « salle des fêtes », « intérieur du château » : pas une tournure
    de cadre, et chacune coûterait un faux."""
    assert cadre_lu("Rendez-vous salle des fêtes.") == ""
    assert cadre_lu("Visite de l'intérieur du château.") == ""


# ──────────────────────────────────── la catégorie, annoncée comme hors portée


def test_la_categorie_est_annoncee_non_remplie():
    """0 juste sur 16 en zero-shot : ce n'est pas un réglage à reprendre.

    La catégorie n'est écrite nulle part sur la page — aucun site n'annonce
    « Catégorie : Spectacles ». C'est une inférence sur la page entière, et un
    surligneur de spans n'a pas de span à surligner. Le banc doit lire
    `MANQUE` comme une limite annoncée, pas comme une faute du modèle.
    """
    assert "category" in unfilled_fields()


# ────────────────────────────────────────────── jusqu'à l'énuméré que le site attend


def test_le_cadre_se_traduit_pour_le_site():
    assert set(CADRES.values()) == {"INDOOR", "OUTDOOR"}
    assert cadre_lu("en plein air") in set(CADRES.values()) | {"BOTH"}
