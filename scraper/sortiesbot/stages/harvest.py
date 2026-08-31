"""Étage 2 — le dépouillement d'un agenda. Python pur, donc gratuit.

Télécharger la page, en extraire les liens, les débruiter : rien là-dedans ne
demande de jugement, et c'est exactement pourquoi le modèle n'y a pas sa
place. Il n'intervient qu'à l'étage suivant, sur une liste déjà courte.

Deux issues se ressemblent et ne veulent pas dire la même chose, d'où le
`None` : une page **injoignable** n'a rien donné et ne donnera rien, alors
qu'une page **sans lien** est peut-être la sortie elle-même, mal classée par
la recherche. La première s'abandonne, la seconde se relit.
"""

from __future__ import annotations

from ..harvest import FetchError, Link, links_of
from . import Stage
from .base import Brick


class Harvest(Brick):
    stage = Stage.HARVEST

    def run(self, url: str, announced: str = "") -> list[Link] | None:
        """Rend les liens de l'agenda, ou `None` s'il est injoignable.

        La liste vide est une réponse : la page a bien été lue, elle ne mène
        simplement nulle part. `None` dit que la question n'a pas pu être
        posée — l'appelant ne doit alors rien conclure de cette page.

        `announced` est le classement rendu par la découverte, uniquement pour
        le confronter à ce que le HTML dit de la page. Il n'entre dans aucune
        décision de cette brique.
        """
        with self.opened(url=url, agenda=url) as st:
            self.log.event("fetching", url=url)
            try:
                html = self.ctx.fetcher.get_html(url)
            except FetchError as err:
                self.log.error("agenda", str(err), url=url)
                st.produced(f"non dépouillé : {err}", links=0)
                return None

            links = links_of(html, url)
            # Le HTML est là et les liens sont comptés : la classification ne
            # coûte donc rien de plus qu'une lecture de plus du même texte.
            self.observed(url, html, announced=announced, links=len(links))
            self.summary.pages += 1
            self.log.event("harvested", url=url, links=len(links), chars=len(html))
            st.produced(f"{len(links)} lien(s) extrait(s)", links=len(links))
            return links
