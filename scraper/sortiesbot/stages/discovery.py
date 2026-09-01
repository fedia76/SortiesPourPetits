"""Étage 1 — trouver par où commencer. Des URL, et rien d'autre.

Cet étage **ne juge plus**. Il rend ce que les recherches ont remonté, sans
dire d'aucune page si elle liste des sorties ou en est une : c'est le travail
de la reconnaissance, à l'étage suivant, sur le HTML.

Ce n'est pas une coquetterie. Un moteur de recherche ordinaire rend des URL et
des titres — pas des avis. En ramenant la découverte à ce contrat, on la rend
remplaçable : brancher un autre moteur ne demande plus qu'il sache classer une
page, seulement qu'il sache en trouver.

Les requêtes viennent de la configuration quand elle en donne — le run est
alors reproductible d'une semaine sur l'autre, et comparable. Sinon un appel au
modèle les formule, pour quelques dizaines de jetons : c'est le plus petit
appel du pipeline.

* **mode recherche** — les requêtes partent au moteur.
* **mode site** — les URL sont données, aucune recherche n'est lancée.
  L'étage existe quand même, il ne coûte simplement rien : le graphe de la
  console garde ainsi ses sept briques dans les deux modes.
"""

from __future__ import annotations

from ..models import FoundPage
from . import Stage
from .base import Brick


class Discovery(Brick):
    stage = Stage.DISCOVERY

    def run(self) -> list[FoundPage]:
        """Les pages par où commencer. Leur nature reste à constater.

        Peut lever `ProviderError` : une recherche impossible arrête le run,
        et c'est l'orchestrateur qui en rend compte.
        """
        return self._seeds() if self.config.targets_site else self._search()

    @property
    def source(self) -> str:
        """Le nom sous lequel une page trouvée hors agenda sera rattachée."""
        return "site" if self.config.targets_site else "recherche"

    @property
    def fallback_multiple(self) -> bool:
        """Ce qu'est une page dont on ne tire aucun lien.

        En mode site, c'est le cas normal du festival qui tient sur une page :
        elle porte plusieurs sorties. En mode recherche, c'est un agenda mal
        classé, donc une sortie unique.
        """
        return self.config.targets_site

    # ------------------------------------------------------------- recherche

    def _search(self) -> list[FoundPage]:
        """Les requêtes partent au moteur ; on garde ce qu'il remonte.

        Le plafond porte désormais sur **toutes** les pages retenues, et non
        sur les seuls agendas : la découverte ne sait plus lesquelles en sont.
        """
        with self.opened(
            mode="recherche", theme=self.config.theme, area=self.config.area
        ) as st:
            queries = self._queries()
            found = self.ctx.provider.search(queries, self.config, self.log)

            gardees = found[: self.config.max_agendas]
            recalees = found[self.config.max_agendas :]
            for page in gardees:
                self.log.event("found", url=page.url, title=page.title, query=page.query)
            for page in recalees:
                self.log.warn(
                    "discovery",
                    f"plafond de {self.config.max_agendas} page(s) atteint : "
                    "celle-ci ne sera pas ouverte",
                    url=page.url,
                    title=page.title,
                )
            st.produced(
                f"{len(queries)} recherche(s), {len(gardees)} page(s) à reconnaître"
                + (f", {len(recalees)} au-delà du plafond" if recalees else ""),
                queries=len(queries),
                pages=len(gardees),
                over_cap=len(recalees),
            )
            return gardees

    def _queries(self) -> list[str]:
        """Celles de la configuration, ou celles que le modèle formule.

        Les figer dans le YAML rend deux runs comparables ; les faire formuler
        varie les angles. Le choix appartient à la configuration, et le journal
        garde trace des requêtes réellement lancées dans les deux cas.
        """
        if self.config.queries:
            self.log.event("queries", source="configuration", count=len(self.config.queries))
            return list(self.config.queries)
        queries = self.ctx.provider.queries(self.config, self.log)
        self.log.event("queries", source="modele", count=len(queries))
        return queries

    # ------------------------------------------------------------------ site

    def _seeds(self) -> list[FoundPage]:
        """Part des URLs données, sans la moindre recherche web.

        La forme du site n'a pas à être déclarée : elle se constate. Une page
        qui mène à des fiches est un agenda, une page qui ne mène nulle part
        est le programme lui-même. Un festival tient souvent sur une seule
        page, où les entrées ne sont reliées que par des ancres — donc sans
        lien à suivre.
        """
        # Même plafond que les agendas d'une recherche : c'est le même travail,
        # et la console présente le réglage sous les deux noms.
        seeds = self.config.seed_urls[: self.config.max_agendas]
        with self.opened(mode="site", seeds=len(seeds)) as st:
            for url in seeds:
                self.log.event("seed", url=url)
            st.produced(
                f"{len(seeds)} point(s) de départ, aucune recherche lancée",
                pages=len(seeds),
            )
        return [FoundPage(url=url) for url in seeds]
