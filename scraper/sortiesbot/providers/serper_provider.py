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

La mécanique HTTP elle-même — poster, lire, facturer — est dans
`serper_client.py`, parce qu'un second appelant en a eu besoin : l'étage
attribution cherche la page officielle d'une sortie, et il doit pouvoir le
faire même quand la configuration tourne avec le fournisseur `anthropic`. Ce
qui reste ici est la seule chose que le moteur ne sait pas faire tout seul :
tourner des résultats en pages à reconnaître.

## Ce que le service rend vraiment

Vérifié le 1er septembre 2026 contre le service, par
`tools/serper_shape.py` — les tests, eux, simulent :

    HTTP 200
    Clés de premier niveau : ['credits', 'organic', 'searchParameters']
    Résultats organiques   : 9   (pour `num: 10` : Google en rend ce qu'il veut)
    Champs d'un résultat   : ['link', 'position', 'snippet', 'title']

Deux enseignements. La réponse **annonce ce qu'elle a coûté** (`credits`), et
on le lit plutôt que de le déduire. Et `num` est un souhait, pas un contrat :
demander dix résultats peut en rendre neuf, ce dont la suite s'accommode
puisqu'elle ne compte jamais dessus.
"""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..harvest import Link, in_domains
from ..journal import RunLog
from ..models import ExtractedEvent, FoundPage, Usage
from ..store import normalize_url
from .base import Provider, ProviderError
from .serper_client import RESULTS_PER_QUERY, SerperClient


class SerperProvider:
    """Serper pour chercher, un modèle pour tout le reste."""

    name = "serper"

    def __init__(self, model: Provider, api_key: str | None = None, session: Any = None):
        self._model = model
        # Sans clé, `SerperClient` refuse de se construire : une configuration
        # qui nomme ce fournisseur et n'a pas de clé doit échouer tout de
        # suite, pas au premier run.
        self._client = SerperClient(api_key, session=session)

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
        """Une requête, ses résultats organiques, et sa facture au compteur.

        Le nombre de crédits est **lu dans la réponse** plutôt que déduit du
        nombre de résultats demandés : le service le dit, et une règle de notre
        cru finirait par diverger de sa grille.
        """
        reply = self._client.ask(query, num=RESULTS_PER_QUERY)
        reply.bill(self.usage)
        return reply.results

    @staticmethod
    def _blocked(url: str, config: Config) -> bool:
        """Le moteur ne connaît pas nos domaines bloqués : on filtre ici.

        L'outil serveur d'Anthropic prenait la liste en paramètre. Serper ne le
        propose pas, et un `-site:` par domaine dans la requête la rallongerait
        sans garantie. Une ligne de Python fait le même travail.
        """
        return in_domains(url, config.blocked_domains)

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
