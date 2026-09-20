"""Classer, et non extraire : la catégorie et le cadre.

Deux champs de la fiche ne sont pas des morceaux de page. La **catégorie** est
un choix dans un référentiel de six entrées, le **cadre** une déduction qu'une
page n'écrit presque jamais. Ils restaient vides, et coûtaient à eux deux un
sixième du score — 280 verdicts « manqué » sur 1 680.

Je les avais rangés parmi les impossibles, ce qui était faux : ce ne sont pas
des rédactions, ce sont des **choix**, et un encodeur sait choisir. Le
détournement est celui que la bibliothèque de GLiNER emploie elle-même — on
écrit les réponses possibles en tête du texte, et le modèle surligne la
bonne.
"""

from __future__ import annotations

from sortiesbot.spans import (
    CADRES,
    GABARIT_CLASSES,
    Span,
    classe_retenue,
    prompt_de_classes,
)

CATEGORIES = ["Parc", "Musée", "Spectacle", "Sport", "Atelier", "Non classé"]


def span(text: str, score: float = 0.9) -> Span:
    return Span(label="classe", text=text, score=score)


# ─────────────────────────────────────────────── le prompt qu'on soumet


def test_les_reponses_possibles_precedent_le_texte():
    prompt = prompt_de_classes("Un spectacle de marionnettes.", CATEGORIES)
    assert prompt.startswith(GABARIT_CLASSES.format(", ".join(CATEGORIES)))
    assert "marionnettes" in prompt


def test_le_titre_passe_avant_le_corps():
    """C'est le signal le plus dense, et les premiers caractères d'une page
    scrapée sont souvent un fil d'Ariane et un bandeau de cookies."""
    prompt = prompt_de_classes(
        "Nous utilisons des cookies. Accueil > Agenda > Fiche.",
        CATEGORIES,
        entete="Le Petit Prince, spectacle jeune public",
    )
    corps = prompt.split("\n", 1)[1]
    assert corps.index("Petit Prince") < corps.index("cookies")


def test_le_corps_est_borne():
    """La fenêtre de l'encodeur ne se négocie pas : ce qui dépasse est ignoré
    en silence, et un texte trop long noierait le gabarit."""
    prompt = prompt_de_classes("a " * 5000, CATEGORIES, limite=300)
    corps = prompt.split("\n", 1)[1]
    assert len(corps) <= 300


# ───────────────────────────────────────── la classe qu'on en retire


def test_la_classe_surlignee_est_rendue():
    assert classe_retenue([span("Spectacle")], CATEGORIES) == "Spectacle"


def test_la_mieux_notee_l_emporte():
    retenue = classe_retenue([span("Parc", 0.4), span("Musée", 0.9)], CATEGORIES)
    assert retenue == "Musée"


def test_la_casse_et_les_accents_ne_comptent_pas():
    assert classe_retenue([span("musee")], CATEGORIES) == "Musée"


def test_un_morceau_de_libelle_est_rendu_canonique():
    """Le modèle surligne souvent un bout : « plein air » pour « en plein air ».

    Une fiche qui porterait ce morceau ne s'apparierait à rien côté site.
    """
    assert classe_retenue([span("plein air")], list(CADRES)) == "en plein air"


def test_un_morceau_ambigu_est_refuse():
    """Deux candidats possibles, aucune raison de trancher : on ne devine pas."""
    assert classe_retenue([span("e")], ["Musée", "Spectacle"]) == ""


def test_aucun_libelle_du_cadre_n_en_contient_un_autre():
    """Un référentiel dont les entrées s'emboîtent ne peut pas être tranché.

    « en intérieur et en plein air » englobait les deux autres : un modèle
    surlignant « plein air » désignait alors deux réponses et se faisait
    refuser, rendant BOTH inatteignable.
    """
    libelles = list(CADRES)
    for cle in libelles:
        autres = [c for c in libelles if c != cle]
        assert not any(cle in autre for autre in autres), cle


def test_rien_de_reconnaissable_ne_rend_rien():
    """Classer au hasard dans six entrées, c'est se tromper cinq fois sur six."""
    assert classe_retenue([span("billetterie")], CATEGORIES) == ""
    assert classe_retenue([], CATEGORIES) == ""


def test_sans_referentiel_rien_n_est_rendu():
    assert classe_retenue([span("Spectacle")], []) == ""


# ──────────────────────────────────────────── le cadre, jusqu'à l'énuméré


def test_le_cadre_se_traduit_pour_le_site():
    """Le modèle lit du français, le site stocke un énuméré."""
    assert CADRES["en plein air"] == "OUTDOOR"
    assert CADRES["en intérieur"] == "INDOOR"
    assert CADRES["les deux"] == "BOTH"


def test_les_libelles_du_cadre_sont_des_tournures_de_page():
    """Une page écrit « en plein air », jamais « OUTDOOR ».

    C'est la leçon des spans — les libellés sont un réglage, et ils doivent
    ressembler à ce que le modèle a vu — appliquée d'emblée ici.
    """
    assert all(cle.islower() and " " in cle for cle in CADRES)
