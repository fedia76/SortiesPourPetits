"""Le moteur change, le modèle reste.

Serper interroge Google et rend du JSON. Il ne sait ni formuler une requête, ni
reconnaître une page, ni trier des liens, ni remplir une fiche — ce n'est pas
un modèle, c'est un moteur. Ce fournisseur ne remplace donc **qu'un seul des
cinq appels**, la recherche, et délègue les quatre autres à un modèle.

C'est précisément ce que l'étage 1 a rendu possible en cessant de juger : il ne
demande plus que des URL, et un moteur sait en rendre. Aucune autre brique ne
change.

Ce qui se gagne au change :

* **le prix** — au palier d'entrée, une requête coûte de l'ordre du millième de
  dollar contre un centime chez Anthropic, et surtout le contenu des résultats
  n'entre plus dans le contexte d'un modèle, donc plus un jeton d'entrée ;
* **l'index** — Google est nettement plus profond que Brave sur le long tail
  francophone local, qui est exactement ce qu'on cherche ;
* **le filtre par date** — `tbs` restreint aux pages récentes, ce que l'outil
  serveur ne sait pas faire.

Ce qui se perd : les résultats ne portent plus qu'un titre et un extrait de
deux cents caractères. C'est sans conséquence ici, puisque la reconnaissance
télécharge la page et juge sur son HTML.

Une requête par appel : la documentation publique ne garantit pas qu'un envoi
groupé soit accepté, et six requêtes de plus ne valent pas un pari sur une
forme non vérifiée.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import requests

from ..config import Config
from ..harvest import Link
from ..journal import RunLog
from ..models import ExtractedEvent, FoundPage, Usage
from ..store import normalize_url
from .base import Provider, ProviderError

ENDPOINT = "https://google.serper.dev/search"

TIMEOUT = 30

#: Tarif du palier d'entrée : 50 $ les 50 000 crédits. Un crédit couvre dix
#: résultats ; au-delà de dix, la requête en consomme deux. C'est ce que
#: `_credits` calcule, pour que la facture affichée soit la vraie.
PRICE_PER_CREDIT_USD = 0.001

#: Résultats demandés par requête. Dix tiennent dans un crédit, et la
#: reconnaissance télécharge chacun d'eux : en demander cent reviendrait à
#: promettre cent téléchargements et cent secondes de politesse.
RESULTS_PER_QUERY = 10


class SerperProvider:
    """Serper pour chercher, un modèle pour tout le reste."""

    name = "serper"

    def __init__(self, model: Provider, api_key: str | None = None, session: Any = None):
        if not api_key:
            raise ProviderError(
                "SERPER_API_KEY est requis pour le fournisseur « serper » "
                "(voir .env.example)"
            )
        self._model = model
        self._key = api_key
        self._session = session or requests.Session()

    @property
    def usage(self) -> Usage:
        """Celui du modèle : la recherche y ajoute son coût au fil de l'eau.

        Un seul compteur pour tout le run, sinon le plafond de budget n'en
        surveillerait qu'une moitié.
        """
        return self._model.usage

    # ------------------------------------------------------------- 1. chercher

    def search(self, queries: list[str], config: Config, log: RunLog) -> list[FoundPage]:
        """Lance chaque requête et rend ce que Google a remonté.

        Un échec de requête n'arrête pas les autres : cinq résultats sur six
        valent mieux qu'une exception. En revanche, si aucune n'aboutit, il n'y
        a rien à faire du run et l'appelant doit le savoir.
        """
        found: dict[str, FoundPage] = {}
        echecs: list[str] = []

        for query in queries:
            log.event("query", op="search", query=query)
            try:
                results = self._ask(query, config)
            except ProviderError as err:
                log.error("search", str(err), query=query)
                echecs.append(query)
                continue

            for item in results:
                url = str(item.get("link", "")).strip()
                if not url.startswith(("http://", "https://")):
                    continue
                if self._blocked(url, config):
                    continue
                title = str(item.get("title", "") or "").strip()
                log.event("search_result", op="search", url=url, title=title, query=query)
                # Deux requêtes remontent souvent la même page : la première
                # garde la paternité, comme du côté de l'outil serveur.
                found.setdefault(normalize_url(url), FoundPage(url=url, title=title, query=query))

        if echecs and len(echecs) == len(queries):
            raise ProviderError(f"aucune recherche n'a abouti ({echecs[0]})")
        if not found:
            log.error("search", "aucun résultat de recherche")
        return list(found.values())

    def _ask(self, query: str, config: Config) -> list[dict[str, Any]]:
        """Une requête, ses résultats organiques. Lève `ProviderError` sinon."""
        payload = {
            "q": query,
            "gl": "fr",
            "hl": "fr",
            "num": RESULTS_PER_QUERY,
        }
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

        self._charge()
        organic = data.get("organic")
        return [r for r in organic if isinstance(r, dict)] if isinstance(organic, list) else []

    def _charge(self) -> None:
        """Impute une requête au compteur du run, au tarif du moteur."""
        self.usage.web_searches += 1
        self.usage.search_cost_usd += self._credits() * PRICE_PER_CREDIT_USD

    def _credits(self) -> int:
        """Un crédit jusqu'à dix résultats, deux au-delà."""
        return 1 if RESULTS_PER_QUERY <= 10 else 2

    @staticmethod
    def _blocked(url: str, config: Config) -> bool:
        """Le moteur ne connaît pas nos domaines bloqués : on filtre ici.

        L'outil serveur d'Anthropic prenait la liste en paramètre. Serper ne le
        propose pas, et un `-site:` par domaine dans la requête la rallongerait
        sans garantie. Trois lignes de Python font le même travail.
        """
        host = urlsplit(url).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        return any(host == d or host.endswith(f".{d}") for d in config.blocked_domains)

    # ---------------------------- les quatre autres appels restent au modèle

    def queries(self, config: Config, log: RunLog) -> list[str]:
        return self._model.queries(config, log)

    def classify(self, digest: str, config: Config, log: RunLog) -> tuple[str, str]:
        return self._model.classify(digest, config, log)

    def select(self, page: str, links: list[Link], config: Config, log: RunLog) -> list[Link]:
        return self._model.select(page, links, config, log)

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
        return self._model.extract(url, content, config, categories, log, multiple=multiple)
