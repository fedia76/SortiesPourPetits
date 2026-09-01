"""Interface commune aux fournisseurs.

Cinq appels, cinq tâches bornées. Aucun n'a le droit de dérouler une
procédure : formuler, chercher, reconnaître, choisir, remplir. C'est ce découpage qui
permet d'utiliser un modèle bon marché et de garder un coût prévisible — un
appel qui ne boucle pas ne peut pas refacturer son contexte trente fois.

Le quatrième, `classify`, est le plus petit de tous : quelques centaines de
jetons, un condensé de page en entrée, une étiquette en sortie. Il n'est appelé
que lorsque le HTML ne déclare rien, et il a le droit de répondre « je ne sais
pas ».
"""

from __future__ import annotations

from typing import Protocol

from ..config import Config
from ..harvest import Link
from ..journal import RunLog
from ..models import ExtractedEvent, FoundPage, Usage


class ProviderError(RuntimeError):
    """Échec côté fournisseur (appel refusé, réponse inexploitable…)."""


class Provider(Protocol):
    """Les trois moments où un modèle est nécessaire."""

    name: str
    usage: Usage

    def queries(self, config: Config, log: RunLog) -> list[str]:
        """Formule les requêtes web à lancer, à partir du thème et de la zone.

        Appelé seulement quand la configuration n'en fournit pas. Quelques
        dizaines de jetons : c'est le plus petit appel du lot.
        """
        ...

    def search(self, queries: list[str], config: Config, log: RunLog) -> list[FoundPage]:
        """Lance ces recherches et rend ce qu'elles ont remonté. Sans jugement.

        Ni tri, ni classement : des URL et leurs titres. C'est ce contrat-là
        qu'un moteur de recherche ordinaire sait honorer, et c'est pourquoi il
        pourra prendre la place de celui-ci sans que rien d'autre ne bouge.
        """
        ...

    def classify(self, digest: str, config: Config, log: RunLog) -> tuple[str, str]:
        """Dit ce qu'est une page à partir de son condensé, et pourquoi.

        Rend `(nature, motif)` où nature vaut « agenda », « sortie » ou
        « inconnu ». Aucune URL ne sort de cet appel : le modèle répond par une
        étiquette, et rien d'autre.
        """
        ...

    def select(
        self, page: str, links: list[Link], config: Config, log: RunLog
    ) -> list[Link]:
        """Parmi les liens d'un agenda, retient ceux qui mènent à une sortie.

        Le modèle répond par des numéros de ligne, jamais par des URL : il lui
        est ainsi matériellement impossible d'en inventer une.
        """
        ...

    def extract(
        self,
        url: str,
        content: str,
        config: Config,
        categories: list[str],
        log: RunLog,
        *,
        multiple: bool = False,
    ) -> list[ExtractedEvent]:
        """Remplit les fiches que porte le texte d'une page.

        Une page vaut une sortie, sauf en mode « site » où la page de
        programme d'un festival en porte plusieurs (`multiple`). Le retour est
        une liste dans les deux cas, pour que la suite du pipeline ne connaisse
        qu'un seul chemin.
        """
        ...


def get_provider(
    config: Config, api_key: str | None = None, serper_key: str | None = None
) -> Provider:
    """Instancie le fournisseur nommé dans la configuration.

    « serper » ne remplace que la recherche : le modèle reste derrière pour les
    quatre autres appels, qu'un moteur ne sait pas rendre.
    """
    from .anthropic_provider import AnthropicProvider

    if config.provider == "anthropic":
        return AnthropicProvider(api_key=api_key)
    if config.provider == "serper":
        from .serper_provider import SerperProvider

        return SerperProvider(AnthropicProvider(api_key=api_key), api_key=serper_key)
    raise ProviderError(
        f"Fournisseur inconnu : « {config.provider} » (connus : anthropic, serper)"
    )
