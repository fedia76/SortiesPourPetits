"""L'enchaînement d'un run : qui appelle qui, et combien de fois.

Les sept briques vivent dans `stages/`, une par fichier, et aucune ne sait ce
qui vient avant ou après elle. Ce module est le seul endroit où l'ordre
existe, et c'est délibéré : la question « qu'est-ce qui s'exécute, dans quel
ordre, combien de fois ? » se répond ici, en une lecture, sans ouvrir une
brique.

La réponse tient dans une seule méthode, `Run.chain()`, où les sept appels se
suivent de haut en bas, à leur profondeur d'imbrication :

    1  découverte                              1 fois par run
         2  reconnaissance                     1 fois par URL trouvée
           si agenda :
             3  dépouillement                  1 fois par agenda
             4  sélection                      1 fois par agenda
           si sortie : elle saute 3 et 4
       puis, pour chaque page retenue :
         5  lecture                            1 fois par page
         6  extraction                         1 fois par page → n fiches
              7  publication                   1 fois par fiche

Rien d'autre n'est dans `chain()` : ce qui décide *si* une page est lue
(doublons, plafonds, budget) est en amont dans `_to_read()`, ce qui décide de
ce qu'on *fait* d'un résultat est dans la brique elle-même, et l'intendance du
run — catégories, comptes finaux, journal d'ouverture et de clôture — est
groupée en bas de la classe. Ce partage est la seule raison d'être de ce
fichier : la chaîne doit se lire sans être coupée par autre chose qu'elle.

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

from typing import Iterator

from .api import ApiError, SppApi
from .config import Config, describe
from .harvest import Fetcher, Link
from .journal import RunLog
from .ledger import Ledger
from .classify import SORTIE
from .models import Candidate, FoundPage
from .providers.base import Provider, ProviderError
from .stages import ORDER, describe as describe_stages
from .stages.base import Brick, RunContext, RunResult
from .stages.discovery import Discovery
from .stages.extraction import Extraction
from .stages.harvest import Harvest
from .stages.identification import Identification
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
    ledger: Ledger | None = None,
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
        ledger=ledger or Ledger(),
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

        # Les sept briques, déclarées dans l'ordre où `chain()` les appelle.
        self.discovery = Discovery(ctx)          # 1
        self.identification = Identification(ctx)  # 2
        self.harvest = Harvest(ctx)              # 3
        self.selection = Selection(ctx)          # 4
        self.reading = Reading(ctx)              # 5
        self.extraction = Extraction(ctx)        # 6
        self.publication = Publication(ctx)      # 7

        # Le même ordre, mais parcourable — et vérifié identique à celui du
        # vocabulaire. La console dessine son graphe d'après `stages.ORDER` :
        # si les deux divergeaient, elle dessinerait un pipeline qui n'est pas
        # celui qui tourne, et le journal serait numéroté de travers.
        self.bricks: tuple[Brick, ...] = (
            self.discovery,
            self.identification,
            self.harvest,
            self.selection,
            self.reading,
            self.extraction,
            self.publication,
        )
        assert tuple(brick.stage for brick in self.bricks) == ORDER

    # ═══════════════════════════════════════════════════════════ le run

    def go(self) -> RunResult:
        """Ouvre le run, joue la chaîne, referme. Rien de plus.

        Deux choses peuvent l'écourter, et elles sont ici plutôt que dans la
        chaîne : une API sans catégories en mode soumission, et une recherche
        impossible. La clôture, elle, a lieu dans tous les cas.
        """
        self._start()

        if not self._load_categories():
            return self._finish()

        try:
            self.chain()
        except ProviderError as err:
            # Une recherche impossible n'est pas rattrapable : sans page de
            # départ, il n'y a rien à lire. Seule la découverte peut la lever,
            # les deux autres briques du modèle rendent compte elles-mêmes.
            self.log.error("search", str(err))
            self.summary.errors += 1
            return self._finish()

        self._record()
        return self._finish()

    # ═══════════════════════════════════════════════════════════ la chaîne

    def chain(self) -> None:
        """Les six étages, dans l'ordre et à leur profondeur d'imbrication.

        Seul endroit du projet où l'ordre du pipeline est écrit. Chaque appel
        de brique est précédé de son numéro ; ce qui le suit ne fait que
        décider de la suite (continuer, abandonner cette page, retomber sur la
        page elle-même), jamais du travail lui-même — celui-ci est tout entier
        dans la brique appelée.

        L'indentation dit la cardinalité : ce qui est plus à droite tourne plus
        souvent. La découverte tourne une fois, la publication vingt.
        """
        trouvees: list[Candidate] = []

        # ── ÉTAGE 1/7 · Découverte ─────────────────── 1 fois par run ──────
        for source in self.discovery.run():
            # Tout ce qui se journalise dans cette piste descend de cette
            # page : c'est ce qui permet à la console de répondre à « quels
            # liens venaient de quelle page ? ».
            with self.log.trail(agenda=source.url):
                # ── ÉTAGE 2/7 · Reconnaissance ──── 1 fois par URL ─────────
                nature = self.identification.run(source)
                if nature is None:
                    continue  # injoignable : rien à en tirer, rien à conclure.
                if nature == SORTIE:
                    # Elle saute le dépouillement et le tri : c'est la page
                    # qu'on cherchait, pas une liste qui y mène.
                    trouvees.append(self._direct(source))
                    continue

                # ── ÉTAGE 3/7 · Dépouillement ───── 1 fois par agenda ──────
                links = self.harvest.run(source.url)
                if links is None:
                    continue  # injoignable : rien à en tirer, rien à conclure.
                if not links:
                    # Pas un seul lien exploitable : ce n'est pas un agenda.
                    # La page est téléchargée, autant la lire pour ce qu'elle est.
                    trouvees.append(self._itself(source.url))
                    continue

                # ── ÉTAGE 4/7 · Sélection ───────── 1 fois par agenda ──────
                kept = self.selection.run(source.url, links)
                if kept is None:
                    continue  # le modèle n'a pas répondu : on n'invente rien.
                if not kept:
                    # Un agenda dont on ne tire aucun lien est peut-être une
                    # page de sortie mal reconnue. Elle est déjà téléchargée :
                    # la lire coûte une extraction, l'ignorer coûte la sortie.
                    trouvees.append(self._itself(source.url))
                    continue

                trouvees.extend(self._listed(source.url, kept))

        # Les quatre premiers étages ont dit *où* lire, les trois suivants
        # lisent. `_to_read` tranche entre les deux — doublons du run,
        # plafonds, budget — pour que la chaîne n'ait pas à s'en occuper.
        for candidate in self._to_read(trouvees):
            with self.log.trail(page=candidate.url, agenda=candidate.source):
                # ── ÉTAGE 5/7 · Lecture ───────────── 1 fois par page ──────
                page = self.reading.run(candidate)
                if page is None:
                    continue  # écartée : la brique a journalisé le motif.

                # ── ÉTAGE 6/7 · Extraction ────────── 1 fois par page ──────
                #    Une page de spectacle rend une fiche, un programme vingt.
                for extracted in self.extraction.run(page, candidate):
                    if self.ctx.full:
                        self.log.event(
                            "skip", reason="plafond de sorties atteint", url=candidate.url
                        )
                        break

                    # ── ÉTAGE 7/7 · Publication ──── 1 fois par fiche ──────
                    self.publication.run(extracted, candidate, page)

    # ═════════════════════════════════════════ ce qui entre dans la chaîne

    def _direct(self, source: FoundPage) -> Candidate:
        """Une sortie remontée telle quelle par la découverte, sans agenda."""
        return Candidate(
            url=source.url,
            title=source.title,
            source=self.discovery.source,
            context=source.query,
        )

    def _itself(self, url: str) -> Candidate:
        """La page d'agenda relue pour elle-même, faute d'en tirer des liens."""
        multiple = self.discovery.fallback_multiple
        self.log.event("fallback", url=url, multiple=multiple)
        return Candidate(
            url=url, title="", source=self.discovery.source, context="", multiple=multiple
        )

    def _listed(self, agenda: str, kept: list[Link]) -> list[Candidate]:
        """Les liens retenus sur un agenda, prêts à être lus."""
        return [
            Candidate(url=link.url, title=link.text, source=agenda, context=link.context)
            for link in kept
        ]

    def _to_read(self, trouvees: list[Candidate]) -> Iterator[Candidate]:
        """Les pages qui seront effectivement lues, dans l'ordre.

        Tout ce qui décide *si* une page est lue est ici, et pas dans la
        chaîne : doublons du run, annonce au journal, question unique à la
        mémoire, puis les deux plafonds. La chaîne ne montre ainsi que ce qui
        se fait sur une page, jamais l'arbitrage qui a mené jusqu'à elle.
        """
        candidates = self._dedupe(trouvees)
        self._announce(candidates)

        # Une seule question à la mémoire pour tout le lot : la suite ne fait
        # plus que consulter le résultat. Une page de programme n'en est pas :
        # ce sont ses sorties qui se mémorisent, une par une, et leurs clés
        # n'existent qu'une fois la page lue.
        self.ctx.store.preload([c.url for c in candidates if not c.multiple])

        for candidate in candidates:
            if self.ctx.full:
                return
            if self.ctx.budget_reached:
                self.summary.stopped_on_budget = True
                self.log.event(
                    "budget",
                    spent=round(self.ctx.provider.usage.total_usd, 4),
                    limit=self.config.max_cost_usd,
                    candidates=len(candidates),
                )
                return
            yield candidate

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

    # ═══════════════════════════════════ l'intendance, autour de la chaîne

    def _start(self) -> None:
        """Annonce le run et le graphe de ses six étages.

        Le graphe part avec le premier événement : la console peut dessiner
        les six briques avant même que la première ait produit quoi que ce
        soit.
        """
        self.log.event(
            "run_start",
            config=describe(self.config),
            mode="soumission" if self.ctx.submit else "dry-run",
            stages=describe_stages(),
        )

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

    def _record(self) -> None:
        """Arrête les comptes de la chaîne et rend la mémoire au disque."""
        self.summary.retained = len(self.ctx.result.events)
        self.summary.usage.add(self.ctx.provider.usage)
        self.ctx.store.flush()

    def _finish(self) -> RunResult:
        self.log.event("run_end", summary=self.summary.as_dict())
        return self.ctx.result
