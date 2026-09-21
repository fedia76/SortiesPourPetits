"""Le classifieur entraîné : ce qu'il apprend, et ce qu'il refuse d'affirmer.

Ces tests ne mesurent pas sa qualité — ça, c'est le banc, sur le vrai corpus.
Ils verrouillent les propriétés dont dépend la valeur de cette mesure : qu'il
se taise quand il hésite, qu'il soit jugé sur des pages qu'il n'a pas vues, et
que le découpage par domaine détecte bien la fuite qu'il est là pour détecter.
"""

from __future__ import annotations

import pytest

from sortiesbot.classifieur import (
    MINIMUM_PAR_CLASSE,
    PRECISION_VISEE,
    Classifieur,
    ClassifieurIndisponible,
    Exemple,
    domaine,
    entrainer,
    probas_hors_echantillon,
    retenir,
    seuil_mesure,
    traits,
)

sklearn = pytest.importorskip("sklearn", reason="extra « classifieur » non installé")


# ───────────────────────────────────────────────────────────────── les traits


def test_le_titre_pese_dans_les_traits():
    """« Le Petit Prince, spectacle » dit la catégorie mieux que trois mille
    caractères de mentions légales."""
    sortie = traits("Spectacle de marionnettes", "Venez nombreux.")
    assert sortie.count("marionnettes") == 3
    assert sortie.endswith("Venez nombreux.")


def test_le_corps_est_borne():
    assert len(traits("", "a " * 5000)) <= 2000


def test_une_page_sans_titre_reste_utilisable():
    assert traits("", "Un atelier poterie.") == "Un atelier poterie."


def test_le_domaine_ignore_le_www():
    assert domaine("https://www.exemple.fr/agenda/x") == "exemple.fr"
    assert domaine("https://Agenda.Exemple.FR/x") == "agenda.exemple.fr"


# ─────────────────────────────────────────────── apprendre, puis se prononcer


def _corpus() -> list[Exemple]:
    """Deux classes qu'un sac de mots doit séparer les yeux fermés."""
    spectacles = [
        "spectacle marionnettes théâtre représentation scène comédiens",
        "théâtre jeune public spectacle conte scène marionnettes",
        "représentation théâtrale spectacle famille scène conte",
        "spectacle conte musical théâtre marionnettes représentation",
        "scène nationale spectacle théâtre représentation comédiens conte",
        "marionnettes spectacle théâtre scène représentation famille",
    ]
    ateliers = [
        "atelier poterie argile modelage fabrication manuelle enfants",
        "atelier créatif peinture bricolage fabrication argile",
        "stage atelier modelage poterie argile manuelle",
        "atelier fabrication bricolage peinture créatif argile",
        "atelier manuel poterie modelage argile bricolage",
        "atelier peinture créatif fabrication modelage enfants",
    ]
    return [
        Exemple(texte=t, etiquette="Spectacle", groupe=f"site{i % 3}.fr")
        for i, t in enumerate(spectacles)
    ] + [
        Exemple(texte=t, etiquette="Atelier", groupe=f"site{i % 3}.fr")
        for i, t in enumerate(ateliers)
    ]


def test_il_apprend_a_separer_deux_classes_evidentes():
    modele = entrainer(_corpus(), seuil=0.0)
    classe, score = modele.predire("", "un spectacle de marionnettes sur scène")
    assert classe == "Spectacle"
    assert score > 0.5


def test_sous_le_seuil_il_se_tait():
    """Un manqué se corrige à la main ; un faux range une sortie au mauvais
    rayon et s'y propage."""
    modele = entrainer(_corpus(), seuil=0.99)
    classe, score = modele.predire("", "un spectacle de marionnettes sur scène")
    assert classe == ""
    # Le score est rendu quand même : un champ vide à 0,98 de confiance et un
    # champ vide faute de modèle demandent deux corrections opposées.
    assert score > 0.5


def test_un_corpus_vide_ne_s_entraine_pas():
    with pytest.raises(ClassifieurIndisponible):
        entrainer([], seuil=0.5)


def test_le_modele_fait_l_aller_retour_sur_le_disque(tmp_path):
    modele = entrainer(_corpus(), seuil=0.42)
    chemin = modele.enregistrer(tmp_path / "categorie.joblib")
    relu = Classifieur.charger(chemin)
    assert relu.seuil == 0.42
    assert relu.classes == ["Atelier", "Spectacle"]
    assert relu.meta["exemples"] == 12
    assert relu.predire("", "atelier poterie argile")[0] == "Atelier"


def test_un_modele_absent_le_dit_en_clair(tmp_path):
    """Pas une pile d'exceptions : un administrateur doit lire quoi lancer."""
    with pytest.raises(ClassifieurIndisponible) as err:
        Classifieur.charger(tmp_path / "rien.joblib")
    assert "classifieur_entrainer" in str(err.value)


# ──────────────────────────────── juger sans se mentir : la fuite par le site


def test_le_decoupage_par_domaine_demasque_la_fuite():
    """Le test qui justifie tout ce dispositif.

    On fabrique un corpus où **seul le nom du site** prédit la classe : le
    texte utile est identique partout, et chaque page porte en plus un jeton
    propre à son domaine. Un découpage au hasard met des pages du même site
    des deux côtés : le modèle lit le jeton et rend un score parfait. Un
    découpage par domaine ne lui laisse que le texte utile, qui ne dit rien —
    et le score s'effondre.

    Sans cette distinction, on croirait tenir un bon classifieur là où on
    n'aurait qu'un détecteur de pieds de page.
    """
    exemples = []
    sites = (("a.fr", "Spectacle"), ("b.fr", "Spectacle"), ("c.fr", "Atelier"), ("d.fr", "Atelier"))
    for site, classe in sites:
        jeton = f"jeton{site.replace('.', '')}"
        for _ in range(6):
            exemples.append(
                Exemple(texte=f"sortie famille enfants {jeton}", etiquette=classe, groupe=site)
            )

    p_hasard, _, verites = probas_hors_echantillon(exemples, groupe=False)
    p_groupe, _, _ = probas_hors_echantillon(exemples, groupe=True)

    justes_hasard = sum(1 for p, v in zip(p_hasard, verites) if p == v)
    justes_groupe = sum(1 for p, v in zip(p_groupe, verites) if p == v)
    assert justes_hasard == len(verites)
    assert justes_groupe < justes_hasard


def test_un_corpus_concentre_sur_un_site_refuse_d_etre_evalue():
    """Une classe qui ne vit que sur un site ne peut pas être testée hors de lui.

    Écarter ce site pour tester laisse un pli d'entraînement sans cette
    classe. Sauter le pli en silence rendrait un score calculé sur les plis
    qui ont bien voulu tourner — un chiffre qui ne se compare à rien.
    """
    exemples = [
        Exemple(texte=f"spectacle theatre scene {i}", etiquette="Spectacle", groupe="a.fr")
        for i in range(6)
    ] + [
        Exemple(texte=f"atelier poterie argile {i}", etiquette="Atelier", groupe="b.fr")
        for i in range(6)
    ]
    with pytest.raises(ClassifieurIndisponible) as err:
        probas_hors_echantillon(exemples, groupe=True)
    assert "concentré" in str(err.value)


def test_un_corpus_trop_maigre_refuse_d_etre_evalue():
    """Une classe à un seul exemple ne peut pas être à la fois apprise et testée.

    Rendre un chiffre là-dessus serait pire que ne rien rendre : ce serait une
    anecdote présentée comme une mesure.
    """
    exemples = [
        Exemple(texte="spectacle", etiquette="Spectacle", groupe="a.fr"),
        Exemple(texte="atelier", etiquette="Atelier", groupe="b.fr"),
    ]
    with pytest.raises(ClassifieurIndisponible):
        probas_hors_echantillon(exemples)


# ───────────────────────────────────── le seuil : mesuré, et jamais choisi


def test_le_seuil_retenu_est_le_plus_permissif_qui_tienne_la_precision():
    # Trente réponses très sûres et justes, trente hésitantes et fausses. 0,50
    # est le premier cran qui écarte les hésitantes : 100 % sur trente
    # réponses. Monter plus haut n'achèterait plus rien et coûterait du rappel.
    predites = ["A"] * 30 + ["B"] * 30
    verites = ["A"] * 60
    scores = [0.9] * 30 + [0.45] * 30
    seuil, courbe = seuil_mesure(predites, scores, verites)
    assert seuil == 0.50
    a_zero = next(p for p in courbe if p["seuil"] == 0.0)
    assert a_zero["precision"] == pytest.approx(0.5)


def test_un_seuil_qui_repond_deux_fois_n_est_pas_retenu():
    """Le défaut qu'a révélé le vrai corpus, et il rendait le dispositif muet.

    La règle avait retenu un seuil où le modèle répondait deux fois sur cent
    trente-deux, à 100 % de justesse — jetant soixante-quinze bonnes réponses
    pour en garder deux. Deux sur deux n'est pas une précision, c'est une
    coïncidence.
    """
    predites = ["A"] * 2 + ["B"] * 98
    verites = ["A"] * 100
    scores = [0.95, 0.92] + [0.1] * 98
    seuil, courbe = seuil_mesure(predites, scores, verites)
    assert seuil == 0.0
    haut = next(p for p in courbe if p["seuil"] == 0.90)
    assert haut["precision"] == 1.0
    assert haut["assez"] is False


def test_quand_rien_ne_tient_la_precision_le_modele_repond_quand_meme():
    """Et c'est un choix, pas un repli.

    Se rabattre sur le seuil le plus prudent laissait un classifieur qui ne
    répondait jamais **tout en ayant l'air branché** — le pire des deux mondes,
    puisqu'un champ toujours vide ne rend pas une catégorie de plus qu'un champ
    faux une fois sur deux. Le script le dit alors franchement, et « --seuil »
    permet de l'éteindre en le sachant.
    """
    predites = ["A"] * 40
    verites = ["B"] * 40
    scores = [0.5 + i / 100 for i in range(40)]
    seuil, _ = seuil_mesure(predites, scores, verites)
    assert seuil == 0.0


def test_la_precision_visee_prefere_le_silence_a_l_erreur():
    """70 % n'est pas un réglage d'humeur : c'est le prix qu'on accepte de payer
    en rappel pour ne pas ranger une sortie au mauvais rayon."""
    assert 0.5 < PRECISION_VISEE < 1.0


# ─────────────────────────── les classes trop rares, mises de côté et non subies


def _distribution(comptes: dict[str, int]) -> list[Exemple]:
    return [
        Exemple(texte=f"{classe} {i}", etiquette=classe, groupe=f"site{i}.fr")
        for classe, n in comptes.items()
        for i in range(n)
    ]


def test_une_classe_trop_rare_est_ecartee_et_rendue_a_part():
    """Rendue à part, pas filtrée en silence : un corpus qui rétrécit sans le
    dire est la meilleure façon de ne pas comprendre pourquoi un champ a cessé
    d'être rendu."""
    gardes, ecartees = retenir(_distribution({"Spectacle": 39, "Concert": 1, "Parc": 2}))
    assert ecartees == {"Concert": 1, "Parc": 2}
    assert {e.etiquette for e in gardes} == {"Spectacle"}
    assert len(gardes) == 39


def test_une_classe_pile_au_minimum_est_gardee():
    _, ecartees = retenir(_distribution({"Sport": MINIMUM_PAR_CLASSE}))
    assert ecartees == {}


def test_deux_pages_rares_ne_bloquent_plus_la_mesure_des_autres():
    """Le défaut que ce garde-fou avait : refuser d'évaluer cent trente-huit
    pages parce que deux classes n'en avaient qu'une.

    Le diagnostic était juste — une classe vue une fois ne s'apprend pas — et
    la sanction disproportionnée.
    """
    corpus = [*_corpus(), Exemple(texte="concert musique groupe", etiquette="Concert", groupe="rare.fr")]
    gardes, ecartees = retenir(corpus, minimum=5)
    assert ecartees == {"Concert": 1}
    # Et ce qui reste s'évalue, là où tout le corpus était refusé avant.
    predites, _, verites = probas_hors_echantillon(gardes)
    assert len(predites) == len(verites) == 12


def test_le_plancher_ne_descend_pas_sous_deux():
    """À un seul exemple, une classe ne peut être ni apprise ni testée : le
    garde-fou du découpage la refuse de toute façon, et c'est le bon endroit."""
    gardes, _ = retenir(_distribution({"A": 6, "B": 6, "C": 1}), minimum=1)
    assert any(e.etiquette == "C" for e in gardes)
    with pytest.raises(ClassifieurIndisponible):
        probas_hors_echantillon(gardes)


def test_le_meme_tri_vaut_pour_apprendre_et_pour_mesurer():
    """Sinon on mesurerait un modèle qui n'est pas celui qu'on livre."""
    gardes, _ = retenir([*_corpus(), Exemple(texte="rare", etiquette="Rare", groupe="z.fr")])
    modele = entrainer(gardes, seuil=0.0)
    assert "Rare" not in modele.classes


def test_un_zero_retenu_se_distingue_d_un_zero_par_defaut():
    """Zéro veut dire deux choses opposées, et les confondre trompe.

    « répondre toujours tient la précision visée » est un bon résultat ;
    « aucun seuil ne la tient, on répond quand même » est un avertissement. Le
    drapeau `assez` et la précision du point retenu les séparent.
    """
    bon = seuil_mesure(["A"] * 40, [0.2] * 40, ["A"] * 40)
    assert bon[0] == 0.0
    a_zero = next(p for p in bon[1] if p["seuil"] == 0.0)
    assert a_zero["assez"] and a_zero["precision"] == 1.0

    mauvais = seuil_mesure(["A"] * 40, [0.2] * 40, ["B"] * 40)
    assert mauvais[0] == 0.0
    a_zero = next(p for p in mauvais[1] if p["seuil"] == 0.0)
    assert a_zero["assez"] and a_zero["precision"] == 0.0
