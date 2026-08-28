"""Fournisseurs de recherche et d'extraction.

Un fournisseur encapsule les trois moments où un modèle est nécessaire :
chercher, choisir des liens, remplir une fiche. Le reste du pipeline —
téléchargement, extraction des liens, géocodage, photo, soumission — n'en sait
rien, ce qui permettra d'ajouter un fournisseur OpenRouter sans y toucher.
"""

from .base import Provider, ProviderError, get_provider

__all__ = ["Provider", "ProviderError", "get_provider"]
