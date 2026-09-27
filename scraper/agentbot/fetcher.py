"""Le téléchargeur du pipeline, qui dit en plus **pourquoi** une page refuse.

`sortiesbot.harvest.Fetcher` rend « page inaccessible (HTTPError) » pour
toute réponse 4xx ou 5xx : le code est perdu en chemin. Or c'est lui qui dit
quoi faire — 404, l'adresse est morte ; 403, le site refuse les robots ; 429,
il nous trouve trop pressés et il faut revenir plus tard ; 503, il est tombé.

Le premier cas réel l'a montré : une page lue sans peine par le pipeline,
refusée à l'agent quelques minutes plus tard, et rien dans le journal pour
dire si c'était le site qui nous bloquait ou l'adresse qui avait changé.

Ce n'est qu'un message plus précis : le comportement ne change pas, la page
est refusée dans les mêmes cas.
"""

from __future__ import annotations

import requests

from sortiesbot.harvest import Fetcher, FetchError

#: Ce qu'un code veut dire, pour le pilote comme pour qui lit le journal.
SENS = {
    401: "accès réservé",
    403: "le site refuse l'accès",
    404: "page introuvable",
    410: "page supprimée",
    429: "trop de requêtes, le site nous freine",
    500: "erreur du site",
    502: "site en panne",
    503: "site indisponible",
    504: "site trop lent",
}


class TalkativeFetcher(Fetcher):
    """Un `Fetcher` dont les refus HTTP portent leur code."""

    def _follow(self, url: str) -> requests.Response:
        response = super()._follow(url)
        code = response.status_code
        if code >= 400:
            response.close()
            sens = SENS.get(code, "refus du site")
            raise FetchError(f"page inaccessible (HTTP {code} : {sens})")
        return response
