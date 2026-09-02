"""Les huit étages d'un run : leur nom ici, leur code dans les modules voisins.

Ce fichier est le **vocabulaire** — l'identité de chaque brique, son numéro,
son libellé, qui la fait travailler et ce qu'elle prend et rend. Chaque module
voisin en implémente une, et une seule : `discovery.py`, `identification.py`,
`harvest.py`, `selection.py`, `reading.py`, `extraction.py`, `attribution.py`,
`publication.py`. Le socle
commun est dans `base.py`, l'enchaînement dans `sortiesbot/orchestrator.py`,
méthode `Run.chain()` — les huit appels s'y suivent, numérotés, à leur
profondeur d'imbrication.

Séparer les deux n'est pas une coquetterie : le vocabulaire voyage jusqu'au
site (l'événement `run_start` le transporte, et la console dessine le graphe
avec), alors que le code, lui, ne sort jamais d'ici.

Le pipeline a toujours eu six étages, mais ils n'existaient que dans la
documentation : le code les enchaînait sans jamais les nommer, et le journal
ne disait pas de quel étage venait une ligne. Impossible, dès lors, de
répondre à « qu'est-ce qui entre et qu'est-ce qui sort de chaque brique ? »
autrement qu'en relisant le code.

Ce module est la référence unique. `journal.RunLog` marque chaque événement
de l'étage courant, chaque brique ouvre le sien avec `log.stage(...)` — par
`Brick.opened(...)`, qui s'en charge — et la console d'administration lit les
mêmes identifiants pour dessiner le graphe.

Trois étages appellent le modèle à chaque passage et sont donc facturés (1, 4,
6) ; trois sont du Python pur et ne coûtent rien (3, 5, 8). Deux sont **mixtes**
— gratuits tant qu'un signal certain tranche, facturés quand ils se taisent
tous : la reconnaissance (2) et l'attribution (7). C'est ce que porte `ACTOR`,
et c'est la seule chose qu'il faut savoir pour lire une facture.

La reconnaissance est arrivée avant-dernière, et elle est arrivée d'un constat :
la découverte classait les pages parce que le fournisseur savait le faire au
passage, pas parce que c'était sa place. La nature d'une page est une propriété
de la page, pas de la façon dont on l'a trouvée — d'où un étage à elle, entre
celui qui trouve et ceux qui exploitent.

L'**attribution** est arrivée en dernier, d'un constat du même ordre. La page
qu'on a lue et la page qui fait autorité ne sont pas la même chose : un atelier
du musée Rodin se trouve sur kidiklik, mais il se passe au musée Rodin, et
c'est sa page à lui qu'un parent veut ouvrir. Jusque-là le pipeline n'avait
qu'une URL et la donnait aux deux rôles, faute d'avoir jamais posé la question.
Il en a maintenant deux, et un étage dont le seul travail est de remonter de
l'une à l'autre — puis de **vérifier** que la page trouvée parle bien de cette
sortie, parce qu'une source fausse est pire qu'une source absente.
"""

from __future__ import annotations

from enum import Enum


class Stage(str, Enum):
    """Un étage du pipeline. La valeur est l'identifiant stable, côté API."""

    DISCOVERY = "discovery"
    IDENTIFY = "identify"
    HARVEST = "harvest"
    SELECT = "select"
    READ = "read"
    EXTRACT = "extract"
    ATTRIBUTE = "attribute"
    PUBLISH = "publish"


#: Ordre d'exécution. Sert à numéroter et à ranger le graphe.
ORDER: tuple[Stage, ...] = (
    Stage.DISCOVERY,
    Stage.IDENTIFY,
    Stage.HARVEST,
    Stage.SELECT,
    Stage.READ,
    Stage.EXTRACT,
    Stage.ATTRIBUTE,
    Stage.PUBLISH,
)

NUMBER: dict[Stage, int] = {stage: i for i, stage in enumerate(ORDER, start=1)}

LABEL: dict[Stage, str] = {
    Stage.DISCOVERY: "Découverte",
    Stage.IDENTIFY: "Reconnaissance",
    Stage.HARVEST: "Dépouillement",
    Stage.SELECT: "Sélection",
    Stage.READ: "Lecture",
    Stage.EXTRACT: "Extraction",
    Stage.ATTRIBUTE: "Attribution",
    Stage.PUBLISH: "Publication",
}

#: Qui travaille, donc qui paie. « modele » = un appel facturé.
ACTOR: dict[Stage, str] = {
    Stage.DISCOVERY: "modele",
    #: Gratuit tant qu'un signal certain tranche — URL, pagination, JSON-LD —
    #: et facturé seulement quand ils se taisent tous. D'où « mixte ».
    Stage.IDENTIFY: "mixte",
    Stage.HARVEST: "python",
    Stage.SELECT: "modele",
    Stage.READ: "python",
    Stage.EXTRACT: "modele",
    #: Gratuit tant que la page lue porte elle-même le lien de l'organisateur —
    #: JSON-LD, domaine du lieu, texte du lien. Facturé seulement quand elle ne
    #: le porte pas et qu'il faut chercher. D'où « mixte », comme l'étage 2.
    Stage.ATTRIBUTE: "mixte",
    Stage.PUBLISH: "python",
}

#: Ce qui entre et ce qui sort, en une ligne — le contrat de chaque brique.
IN_OUT: dict[Stage, tuple[str, str]] = {
    Stage.DISCOVERY: ("des requêtes web", "les URL qu'elles ont remontées"),
    Stage.IDENTIFY: ("une URL trouvée", "sa nature : agenda, ou sortie"),
    Stage.HARVEST: ("URL d'agenda", "liens et leur contexte"),
    Stage.SELECT: ("liens numérotés", "numéros retenus"),
    Stage.READ: ("URL de page", "texte, dates JSON-LD, image"),
    Stage.EXTRACT: ("texte de la page", "fiche(s) JSON"),
    Stage.ATTRIBUTE: ("une fiche et la page qui la portait", "l'URL de la source, vérifiée"),
    Stage.PUBLISH: ("fiche JSON", "sortie en attente de modération"),
}


def describe() -> list[dict[str, object]]:
    """Le graphe des huit étages, tel que la console le dessine."""
    return [
        {
            "stage": stage.value,
            "number": NUMBER[stage],
            "label": LABEL[stage],
            "actor": ACTOR[stage],
            "takes": IN_OUT[stage][0],
            "gives": IN_OUT[stage][1],
        }
        for stage in ORDER
    ]
