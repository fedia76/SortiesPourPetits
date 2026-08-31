"""Étage 3 — le modèle trie les liens d'un agenda. Facturé.

Une page d'agenda porte deux cents liens dont une poignée mènent à une sortie ;
les autres sont des menus, des mentions légales, des partages. Décider lesquels
demande de comprendre un intitulé, donc un modèle — mais sur une liste, pas sur
une page : c'est l'étage le moins cher des trois qui appellent le modèle.

La liste est **numérotée** et le modèle répond par des numéros. Il ne voit
jamais l'occasion d'écrire une URL, donc il ne peut pas en inventer une : la
correspondance numéro → lien se fait ici, en Python.

Comme au dépouillement, `None` et la liste vide ne disent pas la même chose :
`None`, c'est l'appel qui a échoué ; `[]`, c'est le modèle qui n'a rien retenu.
"""

from __future__ import annotations

from ..harvest import Link
from ..providers.base import ProviderError
from . import Stage
from .base import Brick


class Selection(Brick):
    stage = Stage.SELECT

    def run(self, url: str, links: list[Link]) -> list[Link] | None:
        """Rend les liens retenus, ou `None` si le modèle n'a pas répondu."""
        with self.opened(url=url, agenda=url, among=len(links)) as st:
            try:
                kept = self.ctx.provider.select(url, links, self.config, self.log)
            except ProviderError as err:
                self.summary.errors += 1
                self.log.error("select", str(err), url=url)
                st.produced("échec de la sélection", kept=0, among=len(links))
                return None

            st.produced(
                f"{len(kept)} lien(s) retenu(s) sur {len(links)}",
                kept=len(kept),
                among=len(links),
            )
            return kept
