"""Le gel des pages : chaque page reçue par l'agent part au site, telle quelle.

Le HTML **brut**, sans JavaScript — ce que le scraper a réellement lu. C'est
ce qui permet de trancher après coup « est-ce que le scraper voyait cet
élément ? » : s'il n'est pas dans le gel, un script le charge, et aucun des
deux scrapers ne le verra jamais. La page en ligne, elle, aura changé.

Gzippé et en base64, comme au banc : le site l'écrit sans le déballer. Une
page trop lourde, même compressée, n'est pas gelée ; un site injoignable non
plus, et au bout de quelques échecs on renonce pour le reste du run — le gel
ne doit jamais ralentir le travail.
"""

from __future__ import annotations

import base64
import gzip
from typing import Any

from sortiesbot.api import ApiError

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
