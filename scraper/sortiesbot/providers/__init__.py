"""Fournisseurs de recherche et d'extraction.

Un fournisseur encapsule tout ce qui dépend d'un modèle : la recherche sur le
web et la lecture d'une page. Le reste du pipeline (mémoire des URLs,
géocodage, photo, soumission) n'en sait rien, ce qui permettra d'ajouter un
fournisseur OpenRouter — et donc d'autres modèles — sans y toucher.
"""

from .base import Provider, ProviderError, get_provider

__all__ = ["Provider", "ProviderError", "get_provider"]
