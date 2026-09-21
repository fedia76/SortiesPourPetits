"""Un classifieur entraîné, là où le détournement zero-shot ne pouvait rien.

## Pourquoi celui-ci et pas le modèle qu'on a déjà

On a essayé de faire rendre la catégorie par l'étiqueteur de spans, en lui
écrivant les réponses possibles en tête du texte. Résultat mesuré : **0 juste
sur 16**. Ce n'était pas un réglage à reprendre, et la raison est structurelle
— aucune page n'écrit « Catégorie : Spectacles ». La catégorie ne se trouve
pas dans la page, elle s'en **déduit**, et un surligneur de spans n'a alors
rien à surligner, quel que soit son point de contrôle.

Ce qu'il faut pour déduire, c'est un modèle qui a vu des exemples. On en a :
cent soixante fiches dont chaque champ a été vérifié à la main sur le site
d'origine. C'est peu pour entraîner quoi que ce soit de profond ; c'est
largement assez pour un modèle **linéaire sur des traits de surface**, qui est
exactement l'outil de ce régime-là.

## Ce que c'est, concrètement

Un sac de mots pondéré (TF-IDF) et une régression logistique. Rien de plus, et
c'est voulu : le premier modèle qu'on essaie doit être celui qu'on peut
expliquer entièrement, sinon on ne sait pas ce qu'on mesure. Il tient dans un
mégaoctet, s'entraîne en une seconde, et ne charge **aucun réseau de neurones**
— donc rien à ajouter sur une machine que le noyau a déjà tuée une fois.

S'il plafonne, la suite est écrite : remplacer le sac de mots par des
plongements de phrases, sans toucher au reste. C'est le sens de la séparation
entre `traits` et le modèle.

## Ce qu'il refuse de faire

Répondre quand il n'est pas sûr. Un `MANQUE` se corrige à la main ; un `FAUX`
se propage jusqu'à la fiche publiée et range une sortie au mauvais rayon. Le
seuil de confiance n'est donc pas un réglage d'humeur : il est **mesuré à
l'entraînement**, sur les probabilités hors échantillon, et rangé avec le
modèle.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

#: Le champ de la fiche que ce classifieur rend. Un seul pour l'instant ; le
#: cadre se lit sans modèle (`spans.cadre_lu`) et le reste s'extrait.
CHAMP = "category"

#: La variable d'environnement qui dit où est le modèle entraîné.
VARIABLE_CHEMIN = "SPP_CLASSIFIEUR"

#: Hors du dépôt, et ce n'est pas un détail : le déploiement récrit
#: `/opt/sortiespourpetits`, et un modèle rangé là disparaîtrait à chaque mise
#: en ligne — sans erreur, juste un champ qui redeviendrait vide.
CHEMIN_DEFAUT = Path.home() / ".local" / "share" / "sortiesbot" / "categorie.joblib"

#: Combien de fois le titre est répété dans les traits.
#:
#: Le titre d'une page dit sa catégorie bien mieux que son corps — « Le Petit
#: Prince, spectacle jeune public » contre trois mille caractères de mentions
#: légales et d'horaires de parking. Le répéter est la façon la plus bête de
#: le pondérer, et sur un sac de mots c'est exactement équivalent à lui donner
#: un poids : TF-IDF compte les occurrences.
POIDS_TITRE = 3

#: Ce qu'on garde du corps. La page entière noierait le titre sous le pied de
#: page, et l'information de catégorie est presque toujours dans les premiers
#: paragraphes.
CORPS_MAX = 2000

#: En deçà de combien d'exemples une classe est mise de côté — apprise ni
#: mesurée.
#:
#: Ce n'est pas de la prudence statistique, c'est une décision de production.
#: Une classe vue une fois ne s'apprend pas : le modèle retient la page, pas
#: la catégorie, et la ressort sur n'importe quelle page qui lui ressemble de
#: loin. En attendant qu'elle soit étiquetée ailleurs, ses pages valent mieux
#: **manquées que fausses** — c'est le même arbitrage que le seuil de
#: confiance, appliqué au référentiel au lieu de l'être à une prédiction.
#:
#: Cinq, et pas deux : à deux exemples, le découpage de l'évaluation se réduit
#: à deux plis — la moitié du corpus pour apprendre — et le chiffre qui en
#: sort varie plus que ce qu'il mesure.
#:
#: Rien n'est perdu : la classe revient d'elle-même au prochain entraînement
#: dès que le corpus en porte assez.
MINIMUM_PAR_CLASSE = 5

#: La précision qu'on exige avant de laisser le modèle répondre, mesurée hors
#: échantillon. Au-dessous, il se tait.
#:
#: 70 % n'est pas tombé du ciel : sur le banc, un aspect faux et un aspect
#: manqué comptent tous deux comme non-juste, mais en production seul le faux
#: a un coût — une sortie rangée au mauvais rayon, que personne ne va
#: rechercher. À égalité de score, on préfère donc se taire.
PRECISION_VISEE = 0.70

#: Les seuils essayés pour tenir cette précision, du plus permissif au plus
#: prudent. Rien au-delà de 0,90 : un modèle linéaire sur cent soixante
#: exemples n'y arrive jamais, et prétendre le contraire ne ferait que rendre
#: un classifieur muet.
SEUILS_ESSAYES = (0.0, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90)


class ClassifieurIndisponible(RuntimeError):
    """Ni scikit-learn, ni modèle entraîné : le champ reste vide, et on le dit."""


@dataclass(frozen=True)
class Exemple:
    """Une page du corpus, telle qu'elle entre dans l'entraînement.

    `groupe` est le **domaine** de la page, et il n'est pas décoratif : le
    corpus vient d'une poignée de sites, chacun avec son gabarit, son pied de
    page et son vocabulaire. Un découpage au hasard mettrait des pages du même
    site des deux côtés, et le modèle obtiendrait un excellent score en
    apprenant à reconnaître le site plutôt que la sortie. C'est la fuite la
    plus courante en classification de texte, et la seule défense est de
    découper **par groupe**.
    """

    texte: str
    etiquette: str
    groupe: str = ""


def domaine(url: str) -> str:
    """Le site d'où vient une page, sans le `www.`."""
    hote = urlsplit(url).netloc.lower()
    return hote[4:] if hote.startswith("www.") else hote


def traits(titre: str, texte: str) -> str:
    """Le texte soumis au modèle : le titre, pesé, puis le début du corps.

    Une seule chaîne, et c'est délibéré — c'est la frontière derrière laquelle
    on pourra remplacer le sac de mots par des plongements sans rien changer
    d'autre. Ce qu'on choisit ici vaut pour l'entraînement **et** pour
    l'inférence, et c'est la seule façon de garantir qu'on entraîne sur ce
    qu'on lira.
    """
    tete = " ".join([titre.strip()] * POIDS_TITRE) if titre.strip() else ""
    corps = " ".join(texte.split())[:CORPS_MAX]
    return f"{tete} {corps}".strip()


def _sklearn() -> Any:
    """scikit-learn, importé tard et avec un message utile.

    Il est optionnel : la brique doit pouvoir tourner sans lui, et une pile
    d'`ImportError` ne dit pas à un administrateur quoi installer.
    """
    try:
        import joblib  # noqa: F401
        from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: F401
        from sklearn.linear_model import LogisticRegression  # noqa: F401
        from sklearn.pipeline import Pipeline  # noqa: F401
    except ImportError as err:
        raise ClassifieurIndisponible(
            "scikit-learn manque : « pip install -e '.[classifieur]' » dans "
            f"l'environnement du worker ({err})."
        ) from err
    import sklearn

    return sklearn


def _pipeline(grammes: str = "mot") -> Any:
    """Le sac de mots et le modèle linéaire, assemblés.

    `min_df=2` écarte ce qui n'apparaît qu'une fois — sur cent soixante pages,
    un mot unique est un nom propre ou une coquille, jamais un trait de
    catégorie, et le garder invite le modèle à apprendre par cœur.

    `class_weight="balanced"` parce que le corpus est déséquilibré par nature :
    il y a beaucoup plus de spectacles que de fermes pédagogiques, et sans ce
    rééquilibrage le modèle apprendrait surtout à répondre « spectacle ».
    """
    _sklearn()
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    if grammes == "car":
        # Les n-grammes de caractères encaissent la morphologie française —
        # « atelier », « ateliers », « l'atelier » — et les fautes de frappe,
        # au prix d'un vocabulaire dix fois plus gros.
        vectoriseur = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            min_df=2,
            sublinear_tf=True,
            strip_accents="unicode",
            lowercase=True,
            max_features=60000,
        )
    else:
        vectoriseur = TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=2,
            sublinear_tf=True,
            strip_accents="unicode",
            lowercase=True,
            max_features=40000,
        )
    return Pipeline(
        [
            ("sac", vectoriseur),
            (
                "modele",
                LogisticRegression(
                    max_iter=2000,
                    class_weight="balanced",
                    # Une régularisation franche : à cent soixante exemples pour
                    # des dizaines de milliers de traits, un modèle libre
                    # retiendrait le corpus par cœur.
                    C=1.0,
                ),
            ),
        ]
    )


@dataclass
class Classifieur:
    """Le modèle entraîné, son seuil, et de quoi savoir d'où il sort.

    `meta` n'est pas de la décoration : un modèle sérialisé sans la taille du
    corpus ni la date de son entraînement devient, au bout de trois mois, un
    fichier binaire dont personne ne sait s'il vaut encore quelque chose.
    """

    pipeline: Any
    classes: list[str]
    seuil: float
    meta: dict[str, Any] = field(default_factory=dict)

    # ───────────────────────────────────────────────────────── l'inférence

    def predire(self, titre: str, texte: str) -> tuple[str, float]:
        """La classe et sa probabilité — ou `("", p)` s'il n'est pas assez sûr.

        Se taire est une réponse, et souvent la bonne : un modèle qui répond à
        tout sur six classes se trompe cinq fois sur six dès qu'il hésite.
        """
        probas = self.pipeline.predict_proba([traits(titre, texte)])[0]
        meilleur = max(range(len(probas)), key=lambda i: probas[i])
        score = float(probas[meilleur])
        classe = str(self.pipeline.classes_[meilleur])
        return (classe if score >= self.seuil else "", score)

    # ─────────────────────────────────────────────────────── la persistance

    def enregistrer(self, chemin: Path) -> Path:
        _sklearn()
        import joblib

        chemin.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "pipeline": self.pipeline,
                "classes": self.classes,
                "seuil": self.seuil,
                "meta": self.meta,
            },
            chemin,
        )
        return chemin

    @classmethod
    def charger(cls, chemin: Path | None = None) -> Classifieur:
        """Relit un modèle entraîné.

        Le fichier est un pickle, donc du code exécutable : il n'est relu que
        depuis un chemin qu'on a nous-mêmes écrit, jamais depuis le réseau.
        """
        _sklearn()
        import joblib

        chemin = chemin or chemin_du_modele()
        if not chemin.exists():
            raise ClassifieurIndisponible(
                f"aucun modèle entraîné en « {chemin} » : lancer "
                "« python tools/classifieur_entrainer.py » sur le VPS."
            )
        etat = joblib.load(chemin)
        return cls(
            pipeline=etat["pipeline"],
            classes=list(etat.get("classes") or []),
            seuil=float(etat.get("seuil", PRECISION_VISEE)),
            meta=dict(etat.get("meta") or {}),
        )


def chemin_du_modele() -> Path:
    """Où le modèle entraîné est attendu."""
    declare = os.environ.get(VARIABLE_CHEMIN, "").strip()
    return Path(declare) if declare else CHEMIN_DEFAUT


# ═══════════════════════════════════════════════════════════ l'entraînement


def retenir(
    exemples: list[Exemple], minimum: int = MINIMUM_PAR_CLASSE
) -> tuple[list[Exemple], dict[str, int]]:
    """Les exemples des classes assez peuplées, et ce qu'on met de côté.

    Rendu en deux morceaux plutôt qu'en un seul filtré : ce qu'on écarte doit
    être **affiché**, pas disparaître. Un corpus qui rétrécit en silence entre
    deux entraînements est la meilleure façon de ne pas comprendre pourquoi un
    champ a cessé d'être rendu.

    Le même tri vaut pour l'apprentissage et pour la mesure, sans quoi on
    mesurerait un modèle qui n'est pas celui qu'on livre.
    """
    comptes: dict[str, int] = {}
    for e in exemples:
        comptes[e.etiquette] = comptes.get(e.etiquette, 0) + 1
    ecartees = {c: n for c, n in comptes.items() if n < minimum}
    gardes = [e for e in exemples if e.etiquette not in ecartees]
    return gardes, ecartees


def entrainer(exemples: list[Exemple], *, seuil: float, grammes: str = "mot") -> Classifieur:
    """Ajuste le modèle sur tout le corpus, au seuil qu'on lui donne.

    Le seuil vient de `seuil_mesure`, jamais d'une intuition : c'est la leçon
    de la dernière fois, où deux seuils choisis à l'œil ont coûté treize
    aspects justes.
    """
    if not exemples:
        raise ClassifieurIndisponible("corpus vide : rien à apprendre.")
    pipeline = _pipeline(grammes)
    textes = [e.texte for e in exemples]
    etiquettes = [e.etiquette for e in exemples]
    pipeline.fit(textes, etiquettes)
    return Classifieur(
        pipeline=pipeline,
        classes=sorted(set(etiquettes)),
        seuil=seuil,
        meta={"exemples": len(exemples), "grammes": grammes},
    )


def probas_hors_echantillon(
    exemples: list[Exemple], *, grammes: str = "mot", groupe: bool = True
) -> tuple[list[str], list[float], list[str]]:
    """Ce que le modèle prédirait sur des pages qu'il n'a **pas** vues.

    C'est la seule mesure qui veuille dire quelque chose : un modèle noté sur
    ses propres exemples d'entraînement rend toujours un score superbe et
    complètement faux.

    `groupe=True` découpe par domaine. Sans ça, des pages du même site se
    retrouvent des deux côtés du découpage, et le score mesure la capacité du
    modèle à reconnaître un pied de page. Le tableau de bord doit montrer les
    deux : l'écart entre eux **est** le diagnostic.

    Rend, pour chaque exemple : la classe prédite, sa probabilité, la vérité.
    """
    _sklearn()
    import numpy as np
    from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold

    textes = [e.texte for e in exemples]
    verites = [e.etiquette for e in exemples]
    groupes = [e.groupe or str(i) for i, e in enumerate(exemples)]

    # Moins de deux exemples d'une classe, et aucun découpage stratifié n'est
    # possible : on ne peut pas à la fois l'apprendre et la tester.
    comptes: dict[str, int] = {}
    for v in verites:
        comptes[v] = comptes.get(v, 0) + 1
    plis = min(5, min(comptes.values()) if comptes else 1, len(set(groupes)))
    if plis < 2:
        raise ClassifieurIndisponible(
            "corpus trop maigre pour être évalué honnêtement : il reste moins "
            "de deux exemples d'une classe, ou un seul site. Baisser "
            "« --minimum » ne réglera rien ; il faut étiqueter davantage."
        )

    # `StratifiedGroupKFold` plutôt que `GroupKFold` : le second ne regarde que
    # les groupes, et sur un corpus concentré il fabrique des plis
    # d'entraînement où une classe entière manque — le modèle ne peut alors même
    # pas être ajusté. Le premier respecte les groupes *en essayant* de garder
    # les classes réparties.
    decoupe = (
        StratifiedGroupKFold(n_splits=plis, shuffle=True, random_state=0).split(
            textes, verites, groupes
        )
        if groupe
        else StratifiedKFold(n_splits=plis, shuffle=True, random_state=0).split(textes, verites)
    )

    predites = [""] * len(exemples)
    scores = [0.0] * len(exemples)
    for apprend, teste in decoupe:
        # Il reste des corpus qu'aucun découpage ne sauve : celui où une classe
        # ne vit que sur un seul site. Le dire franchement vaut mieux que de
        # sauter le pli en silence — un score calculé sur les plis qui ont bien
        # voulu tourner ne se compare à rien.
        if len({verites[i] for i in apprend}) < 2:
            raise ClassifieurIndisponible(
                "corpus trop concentré : une classe ne vit que sur un seul "
                "site, et l'écarter pour tester laisse un pli sans elle. Il "
                "faut étiqueter la même catégorie sur un deuxième site."
            )
        pipeline = _pipeline(grammes)
        pipeline.fit([textes[i] for i in apprend], [verites[i] for i in apprend])
        probas = pipeline.predict_proba([textes[i] for i in teste])
        for rang, i in enumerate(teste):
            meilleur = int(np.argmax(probas[rang]))
            predites[i] = str(pipeline.classes_[meilleur])
            scores[i] = float(probas[rang][meilleur])
    return predites, scores, verites


def seuil_mesure(
    predites: list[str], scores: list[float], verites: list[str]
) -> tuple[float, list[dict[str, Any]]]:
    """Le seuil le plus permissif qui tienne la précision visée, et la courbe.

    Une règle énoncée, appliquée à des chiffres hors échantillon — par
    opposition à un nombre choisi parce qu'il avait l'air raisonnable. Si
    aucun seuil ne tient la précision, on rend le plus prudent essayé, et
    l'appelant verra dans la courbe que le modèle n'y arrive pas.
    """
    courbe: list[dict[str, Any]] = []
    for seuil in SEUILS_ESSAYES:
        repond = [i for i, s in enumerate(scores) if s >= seuil]
        justes = sum(1 for i in repond if predites[i] == verites[i])
        courbe.append(
            {
                "seuil": seuil,
                "repond": len(repond),
                "justes": justes,
                "precision": justes / len(repond) if repond else 0.0,
                "couverture": len(repond) / len(scores) if scores else 0.0,
            }
        )
    tenables = [p for p in courbe if p["repond"] and p["precision"] >= PRECISION_VISEE]
    retenu = tenables[0]["seuil"] if tenables else SEUILS_ESSAYES[-1]
    return float(retenu), courbe


__all__ = [
    "CHAMP",
    "MINIMUM_PAR_CLASSE",
    "Classifieur",
    "ClassifieurIndisponible",
    "Exemple",
    "chemin_du_modele",
    "domaine",
    "entrainer",
    "probas_hors_echantillon",
    "retenir",
    "seuil_mesure",
    "traits",
]
