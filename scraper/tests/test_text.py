"""Une seule notion d'égalité entre textes, pour tout le scraper.

Cinq définitions cohabitaient — `_fold` dans quatre modules, `_flat` dans
`evaluation` — écrites à quelques mois d'intervalle et déjà divergentes. Elles
ne servent pas à faire joli : ce sont des **clés de dédoublonnage**
(`store.event_key`), des clés de rattachement (la catégorie d'une fiche contre
celles du site) et le test d'ancrage du banc (ce qu'un modèle a écrit se lit-il
dans la page ?). Deux d'entre elles qui divergent d'un accent, c'est une sortie
publiée deux fois ou un tarif déclaré inventé — et personne ne remonte jamais
ça jusqu'à une différence entre `NFD` et `NFKD`.
"""

from __future__ import annotations

import pytest

from sortiesbot.text import alphanum, flatten, fold


@pytest.mark.parametrize(
    "gauche, droite",
    [
        ("Théâtre", "theatre"),
        ("LE HAVRE", "le havre"),
        ("  Niort  ", "niort"),
        ("Forêt de Sénart", "foret de senart"),
        ("Nancy", "NANCY"),
    ],
)
def test_les_accents_et_la_casse_ne_separent_pas(gauche, droite):
    assert fold(gauche) == fold(droite)


def test_deux_villes_differentes_restent_differentes():
    assert fold("Le Havre") != fold("Le Mans")


@pytest.mark.parametrize(
    "page, saisi",
    [
        # Les ordinaux en exposant : « le 1ᵉʳ mai » se lit partout sur les
        # pages d'événement, et `NFD` ne le repliait pas.
        ("le 1ᵉʳ mai", "le 1er mai"),
        # Les ligatures typographiques d'une affiche.
        ("aﬃche du ﬁlm", "affiche du film"),
        # Les chiffres romains d'un seul caractère.
        ("Ⅻ siècle", "XII siecle"),
        # Le pleine chasse, qu'on récupère de certains CMS.
        ("ＰＡＲＩＳ", "Paris"),
    ],
)
def test_la_decomposition_de_compatibilite_replie_ce_que_nfd_laissait(page, saisi):
    assert flatten(page) == flatten(saisi)


def test_flatten_ecrase_les_blancs_y_compris_insecables():
    # `str.split` découpe sur tous les blancs Unicode : l'espace fine
    # insécable de « 8 € » comme le saut de ligne d'une mise en page.
    assert flatten("Tarif : 8 €\n\n  par   enfant") == "tarif : 8 € par enfant"


def test_fold_ne_touche_pas_aux_blancs_internes():
    # C'est la différence avec `flatten`, et elle est voulue : un libellé se
    # compare tel quel, un texte de page se met à plat.
    assert fold("Maison  des   arts") == "maison  des   arts"


def test_alphanum_decoupe_en_mots():
    assert alphanum("Les Caprices de l'enfant-roi") == "les caprices de l enfant roi"
    assert alphanum("  ¡ Olé !  ") == "ole"


def test_alphanum_fabrique_une_cle_stable():
    # C'est ce que `store.event_key` en fait : deux graphies d'un même titre
    # doivent donner la même clé, sinon la sortie est proposée deux fois.
    assert alphanum("Les Caprices de l'enfant-roi", "-") == "les-caprices-de-l-enfant-roi"
    assert alphanum("LES CAPRICES DE L’ENFANT ROI", "-") == alphanum(
        "Les caprices de l'enfant-roi", "-"
    )


def test_alphanum_ne_laisse_pas_de_separateur_aux_bords():
    assert alphanum("— Spectacle ! —", "-") == "spectacle"
    assert alphanum("", "-") == ""


def test_les_trois_fonctions_partagent_la_meme_base():
    # `flatten` et `alphanum` sont `fold` plus quelque chose : si l'une se met
    # à replier autrement, c'est que la base a bougé sous les trois.
    for texte in ("Théâtre du Châtelet", "le 1ᵉʳ mai", "ＰＡＲＩＳ"):
        assert flatten(texte) == " ".join(fold(texte).split())
        assert alphanum(texte).replace(" ", "") == "".join(
            c for c in fold(texte) if c.isalnum()
        )
