"""Interface commune aux fournisseurs.

Trois appels, trois tâches bornées. Aucun n'a le droit de dérouler une
procédure : chercher, choisir, remplir. C'est ce découpage qui permet
d'utiliser un modèle bon marché et de garder un coût prévisible — un appel
qui ne boucle pas ne peut pas refacturer son contexte trente fois.
"""

from __future__ import annotations

from typing import Protocol

from ..config import Config
from ..harvest import Link
from ..journal import RunLog
from ..models import Agenda, ExtractedEvent, Usage


class ProviderError(RuntimeError):
    """Échec côté fournisseur (appel refusé, réponse inexploitable…)."""


class Provider(Protocol):
    """Les trois moments où un modèle est nécessaire."""

    name: str
    usage: Usage

    def search(self, config: Config, log: RunLog) -> list[Agenda]:
        """Lance les recherches web et désigne les pages d'agenda à ouvrir."""
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
        self, url: str, content: str, config: Config, categories: list[str], log: RunLog
    ) -> ExtractedEvent:
        """Remplit la fiche d'une sortie à partir du texte de sa page."""
        ...


def get_provider(config: Config, api_key: str | None = None) -> Provider:
    """Instancie le fournisseur nommé dans la configuration."""
    if config.provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=api_key)
    raise ProviderError(f"Fournisseur inconnu : « {config.provider} » (connu : anthropic)")
