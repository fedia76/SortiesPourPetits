"""Étage 3 — le dépouillement d'un agenda. Python pur, donc gratuit.

Télécharger la page, en extraire les liens, les débruiter : rien là-dedans ne
demande de jugement, et c'est exactement pourquoi le modèle n'y a pas sa
place. Il n'intervient qu'à l'étage suivant, sur une liste déjà courte.

Deux issues se ressemblent et ne veulent pas dire la même chose, d'où le
`None` : une page **injoignable** n'a rien donné et ne donnera rien, alors
qu'une page **sans lien** est peut-être la sortie elle-même, mal reconnue. La
première s'abandonne, la seconde se relit.

Un agenda peut se paginer, et sa deuxième page porte des sorties que la
première n'a pas. On la suit — mais **seulement tant qu'on manque de liens**.
C'est ce qui borne la dépense : les liens partent ensuite au tri, qui est
facturé, et tripler leur nombre triplerait cet appel. Un agenda déjà riche
s'arrête donc à sa première page ; un agenda maigre va en chercher davantage,
ce qui est exactement l'inverse d'un gaspillage.
"""

from __future__ import annotations

from ..classify import next_page
from ..harvest import FetchError, Link, links_of
from . import Stage
from .base import Brick


#: Au-delà, la moisson suffit : les liens partent au tri, qui est facturé, et
#: en ajouter revient à gonfler cet appel. C'est le même plafond que celui
#: qu'une page seule atteint déjà dans `links_of`.
LINK_LIMIT = 200


class Harvest(Brick):
    stage = Stage.HARVEST

    def run(self, url: str) -> list[Link] | None:
        """Rend les liens de l'agenda, ou `None` s'il est injoignable.

        La liste vide est une réponse : la page a bien été lue, elle ne mène
        simplement nulle part. `None` dit que la question n'a pas pu être
        posée — l'appelant ne doit alors rien conclure de cette page.
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
            self.summary.pages += 1
            self.log.event("harvested", url=url, links=len(links), chars=len(html))

            pages = 1 + self._follow(html, url, links)
            st.produced(
                f"{len(links)} lien(s) extrait(s)"
                + (f" sur {pages} pages" if pages > 1 else ""),
                links=len(links),
                pages=pages,
            )
            return links

    def _follow(self, html: str, url: str, links: list[Link]) -> int:
        """Suit `rel="next"` tant que la moisson est maigre. Rend le nombre de
        pages suivantes réellement dépouillées.

        `links` est complété sur place. Deux plafonds, et ils ne disent pas la
        même chose : `max_next_pages` borne le nombre de pages, `LINK_LIMIT`
        borne la récolte — c'est ce dernier qui fait qu'un agenda déjà bien
        fourni ne coûte pas une requête de plus.

        On ne suit que `rel="next"`. Reconstruire « page 2 » à partir de liens
        numérotés reviendrait à inventer une URL, et c'est précisément ce
        qu'on interdit partout ailleurs.
        """
        vues = {link.url for link in links}
        suivies = 0
        while suivies < self.config.max_next_pages and len(links) < LINK_LIMIT:
            suivante = next_page(html, url)
            if not suivante or suivante in vues:
                break
            self.log.event("next_page", url=suivante, page=suivies + 2, links=len(links))
            try:
                html = self.ctx.fetcher.get_html(suivante)
            except FetchError as err:
                self.log.warn("agenda", f"page suivante injoignable : {err}", url=suivante)
                break

            vues.add(suivante)
            url = suivante
            suivies += 1
            self.summary.pages += 1
            for link in links_of(html, suivante):
                if link.url not in vues:
                    vues.add(link.url)
                    links.append(link)
            self.log.event("harvested", url=suivante, links=len(links), chars=len(html))
        return suivies
