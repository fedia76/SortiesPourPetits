"""L'enchaînement d'un run : qui appelle qui, et combien de fois.

Les six briques vivent dans `stages/`, une par fichier, et aucune ne sait ce
qui vient avant ou après elle. Ce module est le seul endroit où l'ordre existe,
et c'est délibéré : la question « qu'est-ce qui s'exécute, dans quel ordre,
combien de fois ? » se répond ici, en une lecture, sans ouvrir une brique.

L'imbrication est ce qui se voyait le moins dans l'ancien code, parce qu'elle
était répartie sur trois fonctions. Elle tient en deux boucles :

    découverte                                  1 fois par run
      └── pour chaque agenda :
            dépouillement                       1 fois par agenda
            sélection                           1 fois par agenda
      puis, pour chaque page candidate :
            lecture                             1 fois par page
            extraction                          1 fois par page  → n fiches
              └── publication                   1 fois par fiche

Les cardinalités changent à chaque flèche, et c'est pourquoi les briques n'ont
pas de signature commune : une interface uniforme aurait fait croire à une
chaîne de six maillons identiques, alors que la découverte tourne une fois et
la publication vingt.

Le partage du travail, lui, ne change jamais : Python fait ce qui est
mécanique, le modèle fait ce qui demande du jugement, et aucun appel ne boucle.
Le filtre des URLs déjà vues intervient avant l'extraction, la seule étape qui
coûte par page.

Thème, période et zone sont une **stratégie de recherche**, pas un filtre de
sortie : ils orientent les requêtes et le tri des liens, là où ils font gagner
du temps et de l'argent. Une fois la page lue, elle est payée — l'écarter
parce qu'elle déborde de la fenêtre reviendrait à payer pour rien, alors que
le site sait filtrer par date et par distance, et qu'un modérateur relit tout.
Seul ce qui est inexploitable est écarté.

Chaque page traitée est rendue à la mémoire (`store.report`) avec ce qu'on en
a fait. Une décision définitive y est mémorisée — la page ne sera plus jamais
relue, par aucune configuration ; une décision provisoire (déjà connue,
doublon, essai sans soumission, erreur réseau) est seulement journalisée.
"""

from __future__ import annotations

from .api import ApiError, SppApi
from .config import Config, describe
from .harvest import Fetcher
from .journal import RunLog
from .models import Candidate
from .providers.base import Provider, ProviderError
from .stages import describe as describe_stages
from .stages.base import RunContext, RunResult
from .stages.discovery import Discovery
from .stages.extraction import Extraction
from .stages.harvest import Harvest
from .stages.publication import Publication
from .stages.reading import Reading
from .stages.selection import Selection
from .store import Memory, normalize_url


def run(
    config: Config,
    provider: Provider,
    store: Memory,
    api: SppApi,
    log: RunLog,
    submit: bool = False,
    fetcher: Fetcher | None = None,
) -> RunResult:
    """Joue un run complet et rend ce qu'il a produit.

    C'est l'unique porte d'entrée du scraper : le worker, la ligne de commande
    et les tests passent tous par ici.
    """
    ctx = RunContext(
        config=config,
        provider=provider,
        store=store,
        api=api,
        fetcher=fetcher or Fetcher(),
        log=log,
        submit=submit,
    )
    return Run(ctx).go()


class Run:
    """Une exécution. Tient les six briques et l'ordre dans lequel elles vont.

    Les briques sont construites une fois pour toutes : elles ne portent aucun
    état propre, seulement le contexte du run, et les instancier à chaque tour
    de boucle n'aurait rien dit de plus.
    """

    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.log = ctx.log
        self.config = ctx.config
        self.summary = ctx.summary

        self.discovery = Discovery(ctx)
        self.harvest = Harvest(ctx)
        self.selection = Selection(ctx)
        self.reading = Reading(ctx)
        self.extraction = Extraction(ctx)
        self.publication = Publication(ctx)

    # ------------------------------------------------------------ le run

    def go(self) -> RunResult:
        # Le graphe part avec le premier événement : la console peut dessiner
        # les six briques avant même que la première ait produit quoi que ce
        # soit.
        self.log.event(
            "run_start",
            config=describe(self.config),
            mode="soumission" if self.ctx.submit else "dry-run",
            stages=describe_stages(),
        )

        if not self._load_categories():
            return self._finish()

        try:
            trouvees = self._collect()
        except ProviderError as err:
            # Une recherche impossible n'est pas rattrapable : sans page de
            # départ, il n'y a rien à lire.
            self.log.error("search", str(err))
            self.summary.errors += 1
            return self._finish()

        candidates = self._dedupe(trouvees)
        self._announce(candidates)

        # Une seule question à la mémoire pour tout le lot : la suite ne fait
        # plus que consulter le résultat. Une page de programme n'en est pas :
        # ce sont ses sorties qui se mémorisent, une par une, et leurs clés
        # n'existent qu'une fois la page lue.
        self.ctx.store.preload([c.url for c in candidates if not c.multiple])

        for candidate in candidates:
            if self.ctx.full:
                break
            if self.ctx.budget_reached:
                self.summary.stopped_on_budget = True
                self.log.event(
                    "budget",
                    spent=round(self.ctx.provider.usage.total_usd, 4),
                    limit=self.config.max_cost_usd,
                    candidates=len(candidates),
                )
                break
            self._read_and_publish(candidate)

        self.summary.retained = len(self.ctx.result.events)
        self.summary.usage.add(self.ctx.provider.usage)
        self.ctx.store.flush()
        return self._finish()

    def _load_categories(self) -> bool:
        """Charge les catégories du site. Faux si le run ne peut pas continuer.

        En dry-run, une API injoignable n'empêche rien : on lit et on montre.
        En soumission, la catégorie est obligatoire côté site — inutile de
        payer des extractions qui seront toutes refusées.
        """
        try:
            self.ctx.categories = self.ctx.api.categories()
        except ApiError as err:
            self.log.error("categories", str(err))
            if self.ctx.submit:
                self.summary.errors += 1
                return False
        return True

    def _finish(self) -> RunResult:
        self.log.event("run_end", summary=self.summary.as_dict())
        return self.ctx.result

    # ------------------------------------- étages 1 à 3 : trouver les pages

    def _collect(self) -> list[Candidate]:
        """Découverte, puis dépouillement et sélection de chaque agenda.

        C'est ici que l'imbrication se voit : un tour de boucle par agenda, et
        deux briques dedans. Une sortie remontée telle quelle par la recherche
        court-circuite les deux.
        """
        trouvees: list[Candidate] = []
        for source in self.discovery.run():
            if not source.is_agenda:
                trouvees.append(
                    Candidate(
                        url=source.url,
                        title=source.title,
                        source=self.discovery.source,
                        context=source.reason,
                    )
                )
                continue

            # Tout ce qui se journalise dans cette piste descend de cet
            # agenda : c'est ce qui permet à la console de répondre à « quels
            # liens venaient de quelle page ? ».
            with self.log.trail(agenda=source.url):
                trouvees.extend(self._from_agenda(source.url))
        return trouvees

    def _from_agenda(self, url: str) -> list[Candidate]:
        """Les pages à lire tirées d'un agenda — étages 2 puis 3."""
        links = self.harvest.run(url)
        if links is None:
            # Injoignable : rien à en tirer, et rien à en conclure non plus.
            return []
        if not links:
            # Pas un seul lien exploitable : ce n'est pas un agenda. La page
            # est téléchargée, autant la lire pour ce qu'elle est.
            return [self._itself(url)]

        kept = self.selection.run(url, links)
        if kept is None:
            return []
        if not kept:
            # Un agenda dont on ne tire aucun lien est peut-être une page de
            # sortie que la recherche a mal classée. Elle est déjà
            # téléchargée : la lire coûte une extraction, l'ignorer coûte la
            # sortie.
            return [self._itself(url)]

        return [
            Candidate(url=link.url, title=link.text, source=url, context=link.context)
            for link in kept
        ]

    def _itself(self, url: str) -> Candidate:
        """La page d'agenda relue pour elle-même, faute d'en tirer des liens."""
        multiple = self.discovery.fallback_multiple
        self.log.event("fallback", url=url, multiple=multiple)
        return Candidate(
            url=url, title="", source=self.discovery.source, context="", multiple=multiple
        )

    def _dedupe(self, trouvees: list[Candidate]) -> list[Candidate]:
        """Écarte les pages repérées deux fois dans le même run.

        Deux agendas listent souvent la même sortie — parfois la même page
        sous deux URLs. Sans ce filtre, elle est lue, extraite et soumise deux
        fois.
        """
        candidates: list[Candidate] = []
        vues: set[str] = set()
        for candidate in trouvees:
            key = normalize_url(candidate.url)
            if key in vues:
                self.summary.duplicates += 1
                self.log.event("skip", reason="déjà repérée ailleurs", url=candidate.url)
                # Provisoire : c'est le premier exemplaire qui décidera du sort
                # de la page, pas ce doublon.
                self.ctx.store.report(
                    candidate.url,
                    "duplicate",
                    title=candidate.title,
                    reason="déjà repérée ailleurs dans ce run",
                    remember=False,
                )
                continue
            vues.add(key)
            candidates.append(candidate)
        return candidates

    def _announce(self, candidates: list[Candidate]) -> None:
        """Publie la liste des pages à lire, au journal et au résultat."""
        self.summary.candidates = len(candidates)
        self.ctx.result.candidates = [
            {
                "url": c.url,
                "title": c.title,
                "source": c.source,
                "context": c.context,
                "multiple": c.multiple,
            }
            for c in candidates
        ]
        for candidate in candidates:
            self.log.event(
                "candidate",
                url=candidate.url,
                title=candidate.title,
                why=candidate.context,
                agenda=candidate.source,
            )
        if not candidates:
            self.log.event(
                "nothing_found",
                searches=self.ctx.provider.usage.web_searches,
                pages=self.summary.pages,
            )

    # ------------------------------------ étages 4 à 6 : une page à la fois

    def _read_and_publish(self, candidate: Candidate) -> None:
        """Lit une page et publie ce qu'elle porte : une sortie, ou vingt.

        Trois briques s'enchaînent ici, et la cardinalité change à chaque
        flèche : on lit **une** page, on en extrait **n** fiches, on en publie
        **n**. C'est précisément ce qu'une interface uniforme aurait caché.
        """
        with self.log.trail(page=candidate.url, agenda=candidate.source):
            page = self.reading.run(candidate)
            if page is None:
                return

            for extracted in self.extraction.run(page, candidate):
                if self.ctx.full:
                    self.log.event(
                        "skip", reason="plafond de sorties atteint", url=candidate.url
                    )
                    break
                self.publication.run(extracted, candidate, page)
