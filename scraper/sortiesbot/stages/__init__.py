"""Les six étages d'un run : leur nom ici, leur code dans les modules voisins.

Ce fichier est le **vocabulaire** — l'identité de chaque brique, son numéro,
son libellé, qui la fait travailler et ce qu'elle prend et rend. Chaque module
voisin en implémente une, et une seule : `discovery.py`, `harvest.py`,
`selection.py`, `reading.py`, `extraction.py`, `publication.py`. Le socle
commun est dans `base.py`, l'enchaînement dans `sortiesbot/orchestrator.py`.

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

Trois étages appellent le modèle et sont donc facturés (1, 3, 5) ; les trois
autres sont du Python pur et ne coûtent rien (2, 4, 6). C'est ce que porte
`ACTOR`, et c'est la seule chose qu'il faut savoir pour lire une facture.
"""

from __future__ import annotations

from enum import Enum


class Stage(str, Enum):
    """Un étage du pipeline. La valeur est l'identifiant stable, côté API."""

    DISCOVERY = "discovery"
    HARVEST = "harvest"
    SELECT = "select"
    READ = "read"
    EXTRACT = "extract"
    PUBLISH = "publish"


#: Ordre d'exécution. Sert à numéroter et à ranger le graphe.
ORDER: tuple[Stage, ...] = (
    Stage.DISCOVERY,
    Stage.HARVEST,
    Stage.SELECT,
    Stage.READ,
    Stage.EXTRACT,
    Stage.PUBLISH,
)

NUMBER: dict[Stage, int] = {stage: i for i, stage in enumerate(ORDER, start=1)}

LABEL: dict[Stage, str] = {
    Stage.DISCOVERY: "Découverte",
    Stage.HARVEST: "Dépouillement",
    Stage.SELECT: "Sélection",
    Stage.READ: "Lecture",
    Stage.EXTRACT: "Extraction",
    Stage.PUBLISH: "Publication",
}

#: Qui travaille, donc qui paie. « modele » = un appel facturé.
ACTOR: dict[Stage, str] = {
    Stage.DISCOVERY: "modele",
    Stage.HARVEST: "python",
    Stage.SELECT: "modele",
    Stage.READ: "python",
    Stage.EXTRACT: "modele",
    Stage.PUBLISH: "python",
}

#: Ce qui entre et ce qui sort, en une ligne — le contrat de chaque brique.
IN_OUT: dict[Stage, tuple[str, str]] = {
    Stage.DISCOVERY: ("thème, zone, période", "URL classées agenda ou sortie"),
    Stage.HARVEST: ("URL d'agenda", "liens et leur contexte"),
    Stage.SELECT: ("liens numérotés", "numéros retenus"),
    Stage.READ: ("URL de page", "texte, dates JSON-LD, image"),
    Stage.EXTRACT: ("texte de la page", "fiche(s) JSON"),
    Stage.PUBLISH: ("fiche JSON", "sortie en attente de modération"),
}


def describe() -> list[dict[str, object]]:
    """Le graphe des six étages, tel que la console le dessine."""
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
