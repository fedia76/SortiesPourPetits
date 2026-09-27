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

import contextlib
from collections.abc import Callable
from typing import Any

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


#: Ce qu'on garde du corps d'un refus : une page de blocage tient en quelques
#: kilo-octets, et au-delà c'est une page d'erreur décorée.
REFUS_MAX = 200_000

#: Appelée pour chaque page reçue : (adresse demandée, code HTTP, HTML).
OnPage = Callable[[str, int, str], None]


class TalkativeFetcher(Fetcher):
    """Un `Fetcher` dont les refus HTTP portent leur code, et qui peut geler ce qu'il reçoit.

    `on_page` reçoit chaque page **au premier téléchargement** — la même
    adresse relue dans le run sort du cache et n'est pas regelée —, refus
    compris : la page de blocage d'un pare-feu dit souvent qui bloque et
    pourquoi. Une erreur dans `on_page` ne fait jamais échouer la lecture.
    """

    def __init__(self, *args: Any, on_page: OnPage | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.on_page = on_page
        self._refus: tuple[int, str] | None = None

    def _follow(self, url: str) -> requests.Response:
        response = super()._follow(url)
        code = response.status_code
        if code >= 400:
            self._refus = (code, _corps(response))
            response.close()
            sens = SENS.get(code, "refus du site")
            raise FetchError(f"page inaccessible (HTTP {code} : {sens})")
        return response

    def get_html(self, url: str) -> str:
        if url in self._pages:
            return super().get_html(url)
        self._refus = None
        try:
            html = super().get_html(url)
        except FetchError:
            if self._refus is not None:
                self._geler(url, *self._refus)
                self._refus = None
            raise
        self._geler(url, 200, html)
        return html

    def _geler(self, url: str, code: int, html: str) -> None:
        if self.on_page is None:
            return
        # Geler est un confort, lire est le travail : une panne du gel ne
        # remonte jamais jusqu'à la lecture.
        with contextlib.suppress(Exception):
            self.on_page(url, code, html)


def _corps(response: requests.Response) -> str:
    """Le début du corps d'un refus, décodé au mieux. Vide s'il est illisible."""
    try:
        morceaux: list[bytes] = []
        taille = 0
        for morceau in response.iter_content(64 * 1024):
            morceaux.append(morceau)
            taille += len(morceau)
            if taille >= REFUS_MAX:
                break
        return b"".join(morceaux)[:REFUS_MAX].decode(response.encoding or "utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — un corps illisible ne change rien au refus
        return ""
