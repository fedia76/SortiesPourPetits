"""Étage 1 — trouver par où commencer. Le seul étage qui dépend du mode.

Deux stratégies, une seule sortie : une liste de `FoundPage`, chacune classée
agenda (à dépouiller) ou sortie (à lire telle quelle). Tout ce qui suit ignore
laquelle a servi, et c'est ce qui évite d'avoir deux scrapers à corriger au
lieu d'un.

* **mode recherche** — le modèle lance des recherches web et classe ce qu'elles
  remontent. C'est le seul endroit du run où une recherche est facturée.
* **mode site** — les URLs sont données par la configuration, aucune recherche
  n'est lancée. L'étage existe quand même, il ne coûte simplement rien : le
  graphe de la console garde ainsi ses six briques dans les deux modes.

Le mode décide aussi de deux détails que l'orchestrateur ne peut pas deviner,
et que cette brique porte donc : sous quel nom une page trouvée sera rattachée
(`source`), et ce qu'on fait d'une page dont on ne tire aucun lien
(`fallback_multiple`).
"""

from __future__ import annotations

from ..models import FoundPage
from . import Stage
from .base import Brick


class Discovery(Brick):
    stage = Stage.DISCOVERY

    def run(self) -> list[FoundPage]:
        """Les pages par où commencer, agendas et sorties mêlés.

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
        """Le modèle cherche et classe ; on plafonne les agendas à ouvrir."""
        with self.opened(
            mode="recherche", theme=self.config.theme, area=self.config.area
        ) as st:
            found = self.ctx.provider.search(self.config, self.log)

            # Une recherche ne remonte pas que des agendas : elle tombe
            # régulièrement sur la page d'une sortie précise, qui part telle
            # quelle à l'extraction.
            candidats = [p for p in found if p.is_agenda]
            agendas = candidats[: self.config.max_agendas]
            recales = candidats[self.config.max_agendas :]
            directes = [p for p in found if not p.is_agenda]

            for page in directes:
                self.log.event("direct", url=page.url, title=page.title, why=page.reason)

            # Le sort de chaque agenda désigné est journalisé avant qu'on
            # l'ouvre : sans ça, un agenda recalé par le plafond ou injoignable
            # disparaissait de la console sans laisser de trace, et on cherchait
            # pourquoi un site remonté par la recherche n'apparaissait nulle part.
            for page in agendas:
                self.log.event(
                    "agenda_planned", url=page.url, title=page.title, why=page.reason
                )
            for page in recales:
                self.log.warn(
                    "discovery",
                    f"plafond de {self.config.max_agendas} agenda(s) atteint : "
                    "celui-ci ne sera pas ouvert",
                    url=page.url,
                    title=page.title,
                    why=page.reason,
                )

            st.produced(
                f"{len(agendas)} agenda(s) à dépouiller, "
                f"{len(directes)} sortie(s) directe(s)"
                + (f", {len(recales)} au-delà du plafond" if recales else ""),
                agendas=len(agendas),
                direct=len(directes),
                over_cap=len(recales),
            )

        # Les sorties directes d'abord : elles ne coûtent aucun dépouillement,
        # autant les avoir en main avant que le budget ne se consomme.
        return directes + agendas

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
                agendas=len(seeds),
            )
        return [FoundPage(url=url) for url in seeds]
