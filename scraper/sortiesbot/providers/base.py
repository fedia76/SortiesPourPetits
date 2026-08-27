"""Interface commune aux fournisseurs."""

from __future__ import annotations

from typing import Protocol

from ..config import Config
from ..journal import RunLog
from ..models import Candidate, ExtractedEvent, Usage


class ProviderError(RuntimeError):
    """Échec côté fournisseur (appel refusé, réponse inexploitable…)."""


class Provider(Protocol):
    """Les deux étages de la recherche.

    `discover` coûte cher et tourne une fois par run ; `extract` tourne une fois
    par page retenue, sur un modèle plus modeste, une fois les pages déjà vues
    écartées.
    """

    name: str
    usage: Usage

    def discover(self, config: Config, log: RunLog) -> list[Candidate]:
        """Cherche sur le web et retourne les pages à examiner."""
        ...

    def extract(
        self, url: str, config: Config, categories: list[str], log: RunLog
    ) -> ExtractedEvent:
        """Lit une page et en tire une sortie structurée."""
        ...


def get_provider(config: Config, api_key: str | None = None) -> Provider:
    """Instancie le fournisseur nommé dans la configuration."""
    if config.provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=api_key)
    raise ProviderError(
        f"Fournisseur inconnu : « {config.provider} » (connu : anthropic)"
    )
