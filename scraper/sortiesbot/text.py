"""Comparer deux textes qui disent la même chose sans s'écrire pareil.

Quatre modules avaient chacun leur `_fold`, plus un `_flat` dans `evaluation` :
cinq définitions d'une même notion d'égalité, écrites à quelques mois
d'intervalle et déjà divergentes — NFKD ici, NFD là, les espaces normalisés
dans deux d'entre elles et pas dans les trois autres.

Ce n'est pas une coquetterie de rangement. Ces fonctions servent de **clés de
dédoublonnage** (`store.event_key`), de clés de rattachement (la catégorie
qu'une fiche annonce contre celles du site) et de test d'ancrage (ce qu'un
modèle a écrit se lit-il vraiment dans la page ?). Deux notions d'égalité qui
divergent d'un accent, c'est une sortie publiée deux fois ou un tarif déclaré
inventé — et personne ne remonte jamais ça jusqu'à une différence entre `NFD`
et `NFKD`.

Trois fonctions, et les deux dernières sont la première plus quelque chose :

* `fold` pour comparer des **libellés** — un nom de ville, une catégorie, un
  titre ;
* `flatten` pour comparer du **texte de page**, où les espaces sont un bruit de
  plus ;
* `alphanum` pour ce qui se découpe en mots ou en identifiants — la ponctuation
  y devient un séparateur.
"""

from __future__ import annotations

import re
import unicodedata


def fold(text: str) -> str:
    """Minuscules, sans accents, sans blancs de bord.

    `NFKD` plutôt que `NFD` : quatre des cinq copies le faisaient déjà, et la
    décomposition de compatibilité vaut ce qu'elle coûte sur de vraies pages
    d'événement. Elle ramène à leur forme ordinaire les ligatures
    (« aﬃche »), les **ordinaux en exposant** — « le 1ᵉʳ mai », qu'on lit
    partout —, les chiffres romains typographiques et les caractères pleine
    chasse. `NFD` les laisse tels quels, et deux textes identiques à l'œil ne
    se comparaient pas.

    Les espaces insécables, eux, ne sont pas le sujet : `flatten` les traite
    déjà, `str.split` découpant sur tous les blancs Unicode.
    """
    stripped = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in stripped if not unicodedata.combining(c))


def flatten(text: str) -> str:
    """`fold`, plus les blancs ramenés à une espace simple.

    Pour tout ce qui se compare à du texte de page : sauts de ligne, tabulations
    et espaces multiples y sont de la mise en forme, pas du contenu.
    """
    return " ".join(fold(text).split())


def alphanum(text: str, separator: str = " ") -> str:
    """`fold`, puis tout ce qui n'est ni lettre ni chiffre ramené au séparateur.

    Deux usages, et le séparateur est tout ce qui les distingue : découper un
    texte en mots pour l'apparier (`separator=" "`), ou en fabriquer une clé
    stable (`separator="-"`).
    """
    return re.sub(r"[^a-z0-9]+", separator, fold(text)).strip(separator)
