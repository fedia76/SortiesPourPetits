"""Le gel des pages : ce que le scraper a réellement reçu, gardé pour le relire.

Deux pièces, communes aux deux scrapers — le pipeline et l'agent :

* `TalkativeFetcher`, le `Fetcher` de `harvest.py` avec deux choses de plus :
  ses refus HTTP portent leur code (« HTTP 429 : trop de requêtes »), là où
  le message d'origine ne disait que « HTTPError » ; et un crochet `on_page`
  appelé à chaque **première** lecture d'une adresse, refus compris ;
* `PageFreezer`, le crochet du worker : il envoie chaque page au site,
  gzippée, rattachée à l'exécution. Le journal de la console y renvoie.

Le HTML gelé est **brut, sans JavaScript** — ce que le scraper a lu. C'est
ce qui tranche après coup « est-ce que le scraper voyait cet élément ? » :
s'il n'est pas dans le gel, un script le charge dans le navigateur, et le
scraper ne le verra jamais. La page en ligne, elle, aura changé.

Geler est un confort, lire est le travail : aucune panne du gel ne remonte
jusqu'à la lecture, et au bout de quelques échecs d'envoi on renonce pour le
reste du run.
"""

from __future__ import annotations

import base64
import contextlib
import gzip
from collections.abc import Callable
from typing import Any

import requests

from .api import ApiError
from .harvest import Fetcher, FetchError

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


# ═══════════════════════════════════════════════════════ l'envoi au site

#: Le plafond du site pour une page gelée (`EVAL_MAX_HTML_B64`).
MAX_B64 = 1_000_000
#: Échecs d'affilée après lesquels on cesse d'essayer.
MAX_ECHECS = 3


class PageFreezer:
    """Envoie chaque page au site, rattachée à l'exécution."""

    def __init__(self, api: Any, run_id: int) -> None:
        self.api = api
        self.run_id = run_id
        self.echecs = 0
        self.envoyees = 0

    def __call__(self, url: str, status: int, html: str) -> None:
        if self.echecs >= MAX_ECHECS or not html:
            return
        brut = html.encode("utf-8")
        charge = base64.b64encode(gzip.compress(brut)).decode("ascii")
        if len(charge) > MAX_B64:
            return
        try:
            self.api._post_json(
                f"/api/scraper/runs/{self.run_id}/pages",
                {"url": url[:500], "status": status, "bytes": len(brut), "html": charge},
            )
        except ApiError:
            self.echecs += 1
            return
        self.echecs = 0
        self.envoyees += 1
