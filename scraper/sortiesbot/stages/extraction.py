"""Étage 5 — le modèle remplit la ou les fiches que porte une page.

Un appel, sans outil, avec un schéma JSON imposé : c'est le seul étage dont le
coût dépend de la longueur de la page, et le seul qui puisse rendre plusieurs
fiches d'un coup. Une page de programme de festival en porte vingt ; une page
de spectacle, une seule. Le retour est une liste dans les deux cas, pour que
la publication ne connaisse qu'un chemin.
"""

from __future__ import annotations

from ..models import Candidate, ExtractedEvent
from ..providers.base import ProviderError
from . import Stage
from .base import Brick, PageContent


class Extraction(Brick):
    stage = Stage.EXTRACT

    def run(self, page: PageContent, candidate: Candidate) -> list[ExtractedEvent]:
        """Rend les fiches lues sur la page. Liste vide si l'appel échoue."""
        with self.opened(
            url=page.url, chars=len(page.text), multiple=candidate.multiple
        ) as st:
            try:
                extracted = self.ctx.provider.extract(
                    page.url,
                    page.text,
                    self.config,
                    sorted(self.ctx.categories),
                    self.log,
                    multiple=candidate.multiple,
                )
            except ProviderError as err:
                self.summary.errors += 1
                self.log.error("extraction", str(err), url=page.url)
                self.ctx.store.report(
                    page.url,
                    "error",
                    title=candidate.title,
                    reason=str(err),
                    remember=False,
                )
                st.produced(f"extraction en échec ({err})", fiches=0)
                return []

            retenues = len([e for e in extracted if e.relevant])
            if candidate.multiple:
                self.log.event(
                    "programme", url=page.url, found=retenues, chars=len(page.text)
                )
            st.produced(
                f"{retenues} fiche(s) exploitable(s) sur {len(extracted)}", fiches=retenues
            )
            return extracted
