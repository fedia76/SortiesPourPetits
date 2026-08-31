"""Le socle commun aux six briques : leur contexte, et ce qu'elles partagent.

Deux objets, deux rôles.

`RunContext` est **ce qu'un run a sous la main** : sa configuration, son
fournisseur de modèle, sa mémoire, son client d'API, son téléchargeur, son
journal, et ce qu'il a produit jusque-là. Il remplace le sac de dix paramètres
qui voyageait de fonction en fonction, et il donne un nom à ce qui n'en avait
pas : l'état d'une exécution.

`Brick` est **ce que toute brique sait faire sans qu'on le lui redise** :
s'annoncer au journal en ouvrant son étage, se refermer en disant ce qu'elle a
produit, et atteindre le contexte sans le trimballer. Le reste — ce qu'elle
prend et ce qu'elle rend — lui est propre, et c'est délibéré : les six briques
n'ont pas la même cardinalité. La découverte tourne une fois par run, le
dépouillement une fois par agenda, la lecture une fois par page, la
publication une fois par fiche. Une signature unique aurait été un mensonge
commode ; on préfère six signatures honnêtes et un orchestrateur qui montre
l'imbrication.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterator

from . import Stage
from ..api import SppApi
from ..config import Config
from ..harvest import Fetcher
from ..journal import RunLog
from ..models import Summary
from ..providers.base import Provider
from ..store import Memory


@dataclass
class RunResult:
    """Ce qu'une exécution laisse derrière elle, en mémoire."""

    summary: Summary = field(default_factory=Summary)
    #: Pages de sortie repérées, conservées même si la suite s'arrête.
    candidates: list[dict[str, Any]] = field(default_factory=list)
    #: Sorties retenues : payload prêt pour l'API, plus de quoi les relire.
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PageContent:
    """Une page téléchargée, telle que l'étage 4 la rend à l'étage 5.

    Trois lectures d'un même HTML, et c'est ce qui justifie cet objet : le
    texte part au modèle, les dates JSON-LD et l'illustration ne le voient
    jamais. Les rendre séparément laissait la porte ouverte à ce qu'on les
    oublie en chemin.
    """

    url: str
    text: str
    #: Dates de représentation déclarées en JSON-LD, gratuites et exactes.
    json_ld_dates: list[str]
    #: L'illustration relevée dans le HTML — le modèle ne peut pas la connaître.
    image: str


@dataclass
class RunContext:
    """Ce qu'un run a sous la main, du début à la fin."""

    config: Config
    provider: Provider
    store: Memory
    api: SppApi
    fetcher: Fetcher
    log: RunLog
    submit: bool
    #: Catégories du site, par nom. Vide en dry-run si l'API est injoignable.
    categories: dict[str, int] = field(default_factory=dict)
    result: RunResult = field(default_factory=RunResult)
    #: Clés des sorties déjà publiées par ce run. Deux programmes d'un même
    #: festival annoncent souvent les mêmes séances.
    keys: set[str] = field(default_factory=set)

    @property
    def summary(self) -> Summary:
        return self.result.summary

    @property
    def budget_reached(self) -> bool:
        return self.provider.usage.total_usd >= self.config.max_cost_usd

    @property
    def full(self) -> bool:
        """Le plafond de sorties du run est atteint."""
        return len(self.result.events) >= self.config.max_events


class Brick:
    """Une brique du pipeline. Une classe, un étage, un fichier.

    Les sous-classes déclarent leur `stage` et écrivent la méthode qui leur va
    — `run(...)`, avec les paramètres que leur travail réclame. Tout ce qui est
    journalisé dans `opened()` est automatiquement rattaché à l'étage, et à la
    piste qu'on lui donne : c'est ce qui permet à la console de reconstituer le
    graphe et l'arbre sans que le code ait à se répéter.
    """

    #: L'étage que cette brique incarne. Obligatoire dans chaque sous-classe.
    stage: ClassVar[Stage]

    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx

    # Raccourcis : ces trois-là servent dans presque chaque ligne d'une brique,
    # et `self.ctx.log` partout rendrait le code illisible.

    @property
    def config(self) -> Config:
        return self.ctx.config

    @property
    def log(self) -> RunLog:
        return self.ctx.log

    @property
    def summary(self) -> Summary:
        return self.ctx.summary

    @contextmanager
    def opened(self, **fields: Any) -> Iterator[Any]:
        """Ouvre l'étage. Rendre `scope.produced(...)` avant de sortir.

        Les clés de filiation — `agenda`, `page` — passent par `trail` plutôt
        que par les champs de l'étage : elles doivent marquer *tout* ce qui est
        journalisé dedans, pas seulement l'ouverture.
        """
        trail = {k: fields.pop(k) for k in ("agenda", "page", "query") if k in fields}
        with self.log.trail(**trail):
            with self.log.stage(self.stage, **fields) as scope:
                yield scope
