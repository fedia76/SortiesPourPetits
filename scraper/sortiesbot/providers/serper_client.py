"""Serper, réduit à ce qu'il est : une requête, des résultats, un coût.

Ce fichier ne connaît ni le pipeline ni les fournisseurs. Il sait poster une
requête à Google via Serper, lire ce qui revient, et dire ce que ça a coûté.
Rien d'autre.

Il a été sorti de `serper_provider.py` le jour où un **deuxième** appelant en
a eu besoin. La brique d'attribution (étage 7) cherche la page officielle
d'une sortie trouvée chez un agrégateur, et elle doit pouvoir le faire même
quand la configuration tourne avec le fournisseur `anthropic` — c'est-à-dire
quand aucun `SerperProvider` n'existe. Laisser la mécanique HTTP enfermée
dans le fournisseur aurait obligé à choisir entre la dupliquer et forcer tout
le monde à passer au moteur pour un usage qui n'a rien à voir avec la
découverte.

D'où le partage : le **client** est ici, la **politique** reste chez ses
appelants. Le fournisseur en tire des `FoundPage` pour la découverte ; la
brique d'attribution y cherche un domaine officiel. Ni l'un ni l'autre n'a à
savoir comment on facture un crédit.

La forme des réponses est celle vérifiée contre le service, documentée en tête
de `serper_provider.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import requests

from ..models import Usage
from .base import ProviderError

ENDPOINT = "https://google.serper.dev/search"

TIMEOUT = 30

#: Tarif du palier d'entrée : 50 $ les 50 000 crédits.
PRICE_PER_CREDIT_USD = 0.001

#: Ce qu'une requête consomme quand la réponse ne le dit pas. Elle le dit
#: presque toujours — voir `Reply.credits` — et c'est mieux ainsi : combien
#: coûte un appel est une question à laquelle le service répond, pas nous.
CREDITS_FALLBACK = 1

#: Résultats demandés par requête à la découverte. Dix tiennent dans un crédit,
#: et la reconnaissance télécharge chacun d'eux : en demander cent reviendrait
#: à promettre cent téléchargements et cent secondes de politesse.
RESULTS_PER_QUERY = 10


@dataclass(frozen=True)
class Reply:
    """Ce qu'une requête a rendu, et ce qu'elle a coûté."""

    results: list[dict[str, Any]] = field(default_factory=list)
    #: Crédits consommés, tels que la réponse les annonce.
    credits: int = CREDITS_FALLBACK

    @property
    def cost_usd(self) -> float:
        return self.credits * PRICE_PER_CREDIT_USD

    def bill(self, usage: Usage) -> None:
        """Impute la requête au compteur du run, au tarif du moteur.

        Un seul compteur pour tout le run, quel que soit l'étage qui a
        cherché : sinon le plafond de budget n'en surveillerait qu'une part.
        """
        usage.web_searches += 1
        usage.search_cost_usd += self.cost_usd


class SerperClient:
    """Le moteur, et rien de plus. Sans clé, il ne se construit pas."""

    def __init__(self, api_key: str | None = None, session: Any = None):
        if not api_key:
            raise ProviderError(
                "SERPER_API_KEY est requis pour interroger le moteur "
                "(voir .env.example)"
            )
        self._key = api_key
        self._session = session or requests.Session()

    def ask(self, query: str, *, num: int = RESULTS_PER_QUERY) -> Reply:
        """Une requête, ses résultats organiques. Lève `ProviderError` sinon.

        `num` est un souhait, pas un contrat : demander dix résultats peut en
        rendre neuf, ce dont les appelants s'accommodent puisqu'aucun ne compte
        dessus.
        """
        payload = {"q": query, "gl": "fr", "hl": "fr", "num": num}
        try:
            response = self._session.post(
                ENDPOINT,
                headers={"X-API-KEY": self._key, "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=TIMEOUT,
            )
        except requests.RequestException as err:
            raise ProviderError(f"moteur injoignable ({err.__class__.__name__})") from err

        if response.status_code == 403:
            raise ProviderError("clé Serper refusée (403)")
        if response.status_code == 429:
            raise ProviderError("quota Serper dépassé (429)")
        if response.status_code >= 400:
            raise ProviderError(f"moteur en erreur (HTTP {response.status_code})")

        try:
            data = response.json()
        except ValueError as err:
            raise ProviderError("réponse du moteur illisible") from err

        credits = data.get("credits")
        organic = data.get("organic")
        return Reply(
            results=[r for r in organic if isinstance(r, dict)]
            if isinstance(organic, list)
            else [],
            credits=credits if isinstance(credits, int) and credits > 0 else CREDITS_FALLBACK,
        )


def client_or_none(api_key: str | None, session: Any = None) -> SerperClient | None:
    """Le client si la clé est là, `None` sinon — sans lever.

    Le repli de l'attribution est facultatif par nature : une installation sans
    clé Serper doit continuer à tourner, avec les seuls signaux gratuits. C'est
    la différence avec le fournisseur `serper`, que l'absence de clé condamne.
    """
    if not api_key:
        return None
    try:
        return SerperClient(api_key, session=session)
    except ProviderError:
        return None
