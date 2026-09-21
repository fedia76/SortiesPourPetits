"""Fournisseurs de recherche et d'extraction.

Un fournisseur encapsule les cinq moments où quelqu'un d'autre que Python est
nécessaire : formuler, chercher, reconnaître, choisir, remplir. Le reste du
pipeline — téléchargement, extraction des liens, géocodage, photo, soumission —
n'en sait rien.

Ce fichier promettait qu'on pourrait « ajouter un fournisseur OpenRouter sans
toucher au reste ». C'est fait, et la promesse a tenu : `openrouter_provider.py`
est arrivé sans qu'aucun étage ne bouge. Ce qui a bougé est ailleurs et était
juste : les schémas de sortie, qui vivaient chez le fournisseur Anthropic,
sont passés dans `schemas.py` — deux fournisseurs qui remplissent la même
fiche doivent la remplir d'après le même schéma, sinon le banc mesure notre
code en croyant mesurer des modèles.
"""

from .base import Provider, ProviderError, get_provider

__all__ = ["Provider", "ProviderError", "get_provider"]
