"""La boîte à outils du pilote.

Six outils, et chacun rend **un résumé**, jamais une page. La première ligne
de chaque résultat se suffit à elle-même : c'est elle qui reste quand
l'historique est élagué (voir `loop.py`).

| Outil     | Ce qu'il fait                                  | Brique de `sortiesbot`  |
|-----------|------------------------------------------------|-------------------------|
| search    | une requête Serper                             | `SerperClient`          |
| open      | télécharge une page, dit ce qu'elle est        | étage 2, reconnaissance |
| links     | liste les liens d'une page ouverte, filtrés    | étage 3, dépouillement  |
| extract   | tire les fiches d'une page ouverte             | étages 5 et 6           |
| propose   | remonte à la source, valide, retient une fiche | étages 7 et 8           |
| finish    | clôt l'exploration                             | —                       |

Le pilote ne manipule que des **références** : `r3` pour un résultat de
recherche, `l14` pour un lien, `p2` pour une page ouverte, `f5` pour une
fiche. `open` n'accepte qu'une référence (ou l'adresse exacte d'une
référence) : une URL que le modèle aurait écrite de lui-même est refusée. C'est
la règle de la sélection du pipeline — des numéros, jamais des adresses —
transposée à un agent.

Tous les refus sont des réponses, pas des exceptions : un outil qui dépasse
un plafond le dit au pilote, qui peut en tenir compte. Une exception
arrêterait le run pour une faute que le modèle aurait pu corriger.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit

from sortiesbot.classify import PROGRAMME
from sortiesbot.harvest import Link, first_heading, json_ld_dates, links_of, page_text
from sortiesbot.models import Candidate, ExtractedEvent, FoundPage
from sortiesbot.providers.base import ProviderError
from sortiesbot.providers.serper_client import SerperClient
from sortiesbot.stages.attribution import Attribution
from sortiesbot.stages.base import PageContent, RunContext
from sortiesbot.stages.extraction import Extraction
from sortiesbot.stages.harvest import Harvest
from sortiesbot.stages.identification import Identification
from sortiesbot.stages.publication import Publication
from sortiesbot.stages.reading import Reading
from sortiesbot.store import normalize_url
from sortiesbot.text import fold

from .journal import AgentLog

#: Liens rendus par appel à `links`. Au-delà, le pilote demande la suite.
LIENS_PAR_APPEL = 25
#: Résultats rendus par recherche.
RESULTATS_PAR_RECHERCHE = 8
#: Caractères du début de page montrés à l'ouverture. Assez pour reconnaître
#: un sujet, trop peu pour que la page entre dans le contexte.
EXTRAIT = 280


@dataclass(frozen=True)
class Limits:
    """Les plafonds du run. Vérifiés par le code, pas confiés au prompt."""

    max_turns: int = 60
    #: Clics depuis un résultat de recherche : 0 pour le résultat lui-même.
    max_depth: int = 3
    max_pages: int = 40
    max_searches: int = 8


@dataclass
class Target:
    """Une adresse que le pilote a le droit d'ouvrir, parce qu'un outil la lui a donnée."""

    ref: str
    url: str
    title: str
    depth: int
    #: La page ou la requête d'où elle vient — la filiation du journal.
    origin: str = ""


@dataclass
class Page:
    """Une page ouverte. Son texte ne quitte jamais cet objet."""

    ref: str
    url: str
    title: str
    nature: str
    depth: int
    origin: str
    links: list[Link] | None = None
    #: Les liens déjà connus de la mémoire, écartés du listing.
    known: int = 0
    content: PageContent | None = None
    fiches: list[str] | None = None


@dataclass
class Fiche:
    ref: str
    event: ExtractedEvent
    candidate: Candidate
    page: PageContent
    outcome: str = ""


@dataclass
class Counters:
    searches: int = 0
    opened: int = 0
    calls: dict[str, int] = field(default_factory=dict)


class Toolbox:
    """Les outils, leur état, et les plafonds qui les bornent."""

    def __init__(
        self,
        ctx: RunContext,
        limits: Limits,
        *,
        search: SerperClient | None,
        engine: SerperClient | None = None,
    ) -> None:
        self.ctx = ctx
        self.limits = limits
        self.search_client = search
        self.log: AgentLog = ctx.log  # type: ignore[assignment]
        self.counters = Counters()
        self.finished: str | None = None

        self.targets: dict[str, Target] = {}
        self.by_url: dict[str, str] = {}
        self.pages: dict[str, Page] = {}
        self.opened: dict[str, str] = {}
        self.fiches: dict[str, Fiche] = {}
        self._next = {"r": 0, "l": 0, "p": 0, "f": 0}

        self.identification = Identification(ctx)
        self.harvest = Harvest(ctx)
        self.reading = Reading(ctx)
        self.extraction = Extraction(ctx)
        self.attribution = Attribution(ctx, engine=engine)
        self.publication = Publication(ctx)

        self._tools: dict[str, Callable[..., str]] = {
            "open": self.open,
            "links": self.links,
            "extract": self.extract,
            "propose": self.propose,
            "finish": self.finish,
        }
        if search is not None:
            self._tools["search"] = self.search

    # ════════════════════════════════════════════════════ l'aiguillage

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [s for s in SCHEMAS if s["function"]["name"] in self._tools]

    def call(self, name: str, arguments: str) -> tuple[str, dict[str, Any]]:
        """Exécute un appel du pilote. Rend le résultat et les arguments lus.

        Jamais d'exception : un nom inconnu, un JSON raté, un argument manquant
        sont rendus au modèle comme des réponses, pour qu'il se corrige.
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"Outil inconnu : « {name} ». Outils : {', '.join(sorted(self._tools))}.", {}
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return f"Arguments illisibles pour {name} : ce n'est pas du JSON valide.", {}
        if not isinstance(args, dict):
            return f"Arguments illisibles pour {name} : un objet JSON est attendu.", {}
        self.counters.calls[name] = self.counters.calls.get(name, 0) + 1
        try:
            return tool(**args), args
        except (TypeError, ValueError) as err:
            return f"Arguments invalides pour {name} : {err}.", args

    def status(self) -> str:
        """Où en est le run, en une ligne. Ajoutée au dernier résultat de chaque tour."""
        usage = self.ctx.provider.usage
        return (
            f"[état : {usage.total_usd:.3f} $ sur {self.ctx.config.max_cost_usd:.2f} $ · "
            f"recherches {self.counters.searches}/{self.limits.max_searches} · "
            f"pages {self.counters.opened}/{self.limits.max_pages} · "
            f"retenues {len(self.ctx.result.events)}/{self.ctx.config.max_events}]"
        )

    # ═══════════════════════════════════════════════════════ les outils

    def search(self, query: str) -> str:
        query = " ".join(str(query).split())
        if not query:
            return "Requête vide."
        if self.counters.searches >= self.limits.max_searches:
            return f"Refusé : plafond de {self.limits.max_searches} recherches atteint."
        if self.ctx.budget_reached:
            return "Refusé : budget épuisé. Appelle finish."
        self.counters.searches += 1
        self.log.event("query", query=query)
        try:
            reply = self.search_client.ask(query)  # type: ignore[union-attr]
        except ProviderError as err:
            self.log.error("search", str(err))
            return f"Recherche impossible : {err}."
        reply.bill(self.ctx.provider.usage)

        lines: list[str] = []
        for result in reply.results:
            url = str(result.get("link") or "")
            if not url.startswith(("http://", "https://")) or self._blocked(url):
                continue
            target = self._target("r", url, str(result.get("title") or ""), 0, origin=query)
            snippet = " ".join(str(result.get("snippet") or "").split())[:160]
            lines.append(f"{target.ref} · {target.title} — {url}\n    {snippet}")
            if len(lines) >= RESULTATS_PAR_RECHERCHE:
                break
        if not lines:
            return f"Recherche « {query} » : aucun résultat exploitable."
        return f"Recherche « {query} » : {len(lines)} résultat(s).\n" + "\n".join(lines)

    def open(self, ref: str) -> str:
        target = self._resolve(str(ref))
        if target is None:
            return (
                f"Refusé : « {ref} » n'est pas une référence connue. N'ouvre que des "
                "références rendues par search ou links (r…, l…)."
            )
        key = normalize_url(target.url)
        if key in self.opened:
            page = self.pages[self.opened[key]]
            return f"Déjà ouverte : {page.ref} ({page.nature}, « {page.title} »)."
        if target.depth > self.limits.max_depth:
            return f"Refusé : profondeur {target.depth} au-delà du maximum ({self.limits.max_depth})."
        if self.counters.opened >= self.limits.max_pages:
            return f"Refusé : plafond de {self.limits.max_pages} pages ouvertes atteint."
        if self._blocked(target.url):
            return "Refusé : domaine écarté par la configuration."
        if self.ctx.store.seen_as_event(target.url):
            return "Déjà traitée comme sortie lors d'un run précédent : inutile de l'ouvrir."

        self.counters.opened += 1
        with self.log.trail(page=target.url, agenda=target.origin):
            found = self.identification.run(
                FoundPage(url=target.url, title=target.title, query=target.origin)
            )
        if found is None:
            return f"{target.ref} injoignable."
        nature, source = found
        try:
            html = self.ctx.fetcher.get_html(source.url)  # en cache depuis l'étage 2
        except Exception as err:  # noqa: BLE001 — une page qui disparaît entre deux lectures
            return f"{target.ref} illisible : {err}."

        ref = self._ref("p")
        title = first_heading(html) or target.title
        page = Page(
            ref=ref, url=source.url, title=title, nature=nature,
            depth=target.depth, origin=target.origin,
        )
        self.pages[ref] = page
        self.opened[key] = ref
        self.opened[normalize_url(source.url)] = ref

        dates = json_ld_dates(html)
        excerpt = " ".join(page_text(html, limit=EXTRAIT).split())
        return "\n".join(
            [
                f"{ref} — {nature} · « {title} » · profondeur {page.depth}",
                f"    adresse : {source.url}",
                f"    liens : {len(links_of(html, source.url))}"
                + (f" · dates déclarées : {', '.join(dates[:6])}" if dates else ""),
                f"    début du texte : {excerpt}",
            ]
        )

    def links(self, page: str, filtre: str = "", suite: int = 0) -> str:
        found = self.pages.get(str(page))
        if found is None:
            return f"Refusé : « {page} » n'est pas une page ouverte (p…)."
        if found.depth >= self.limits.max_depth:
            return (
                f"{found.ref} est à la profondeur maximale ({self.limits.max_depth}) : "
                "ses liens ne pourraient pas être ouverts."
            )
        if found.links is None:
            with self.log.trail(agenda=found.url):
                harvested = self.harvest.run(found.url)
            if harvested is None:
                return f"{found.ref} injoignable, pas de liens."
            store = self.ctx.store
            store.preload([link.url for link in harvested])
            here = normalize_url(found.url)
            fresh = [
                link
                for link in harvested
                if normalize_url(link.url) != here
                and not self._blocked(link.url)
                and not store.seen(link.url)
            ]
            found.known = len(harvested) - len(fresh)
            found.links = fresh

        pool = found.links
        motif = fold(str(filtre))
        if motif:
            pool = [
                link for link in pool
                if motif in fold(f"{link.text} {link.context} {link.url}")
            ]
        start = max(0, int(suite)) * LIENS_PAR_APPEL
        chunk = pool[start : start + LIENS_PAR_APPEL]
        if not chunk:
            return f"{found.ref} : aucun lien" + (f" pour « {filtre} »" if motif else "") + (
                " à cette position." if start else "."
            )

        lines = []
        for link in chunk:
            target = self._target("l", link.url, link.text, found.depth + 1, origin=found.url)
            context = " ".join(link.context.split())[:120]
            lines.append(f"{target.ref} · {link.text[:80]} | {context} — {link.url[:110]}")
        rest = len(pool) - start - len(chunk)
        head = (
            f"{found.ref} : liens {start + 1} à {start + len(chunk)} sur {len(pool)}"
            + (f" pour « {filtre} »" if motif else "")
            + (f" ({found.known} déjà connus, écartés)" if found.known else "")
            + (f" — suite={int(suite) + 1} pour la suite." if rest > 0 else ".")
        )
        return head + "\n" + "\n".join(lines)

    def extract(self, page: str) -> str:
        found = self.pages.get(str(page))
        if found is None:
            return f"Refusé : « {page} » n'est pas une page ouverte (p…)."
        if found.fiches is not None:
            return self._describe_fiches(found, again=True)
        if self.ctx.budget_reached:
            return "Refusé : budget épuisé. Appelle finish."

        candidate = Candidate(
            url=found.url, title=found.title, source=found.origin,
            multiple=found.nature == PROGRAMME,
        )
        mark = self.log.mark
        with self.log.trail(page=found.url, agenda=found.origin):
            content = self.reading.run(candidate)
            if content is None:
                found.fiches = []
                return f"{found.ref} non lue : {self.log.why(mark) or 'écartée'}."
            events = self.extraction.run(content, candidate)
            if not candidate.multiple and len(events) == 1 and events[0].several:
                # Même reprise que le pipeline (`Run._requalified`) : l'extraction
                # a lu le texte entier, elle en sait plus que la reconnaissance.
                candidate = replace(candidate, multiple=True)
                self.log.event("requalified", url=found.url, was="sortie", now="programme")
                events = self.extraction.run(content, candidate)
        found.content = content

        found.fiches = []
        for event in events:
            ref = self._ref("f")
            self.fiches[ref] = Fiche(ref=ref, event=event, candidate=candidate, page=content)
            found.fiches.append(ref)
        if not events:
            return f"{found.ref} : aucune fiche ({self.log.why(mark) or 'extraction vide'})."
        return self._describe_fiches(found)

    def propose(self, fiche: str) -> str:
        found = self.fiches.get(str(fiche))
        if found is None:
            return f"Refusé : « {fiche} » n'est pas une fiche connue (f…)."
        if found.outcome:
            return f"{found.ref} déjà traitée : {found.outcome}"
        if self.ctx.full:
            return "Refusé : plafond de sorties atteint. Appelle finish."
        if not found.event.relevant:
            found.outcome = f"écartée par l'extraction ({found.event.skip_reason or 'hors sujet'})."
            return f"{found.ref} {found.outcome}"

        before = len(self.ctx.result.events)
        mark = self.log.mark
        with self.log.trail(page=found.page.url, agenda=found.candidate.source):
            source = self.attribution.run(found.event, found.candidate, found.page)
            self.publication.run(found.event, found.candidate, found.page, source)
        if len(self.ctx.result.events) > before:
            found.outcome = "retenue" + (f", source : {source.url}" if source.found else "") + "."
        else:
            found.outcome = f"écartée : {self.log.why(mark) or 'refusée à la publication'}."
        return f"{found.ref} {found.outcome}"

    def finish(self, bilan: str = "") -> str:
        self.finished = str(bilan).strip() or "sans bilan"
        return "Exploration close."

    # ═════════════════════════════════════════════════════ l'intendance

    def _describe_fiches(self, page: Page, again: bool = False) -> str:
        refs = page.fiches or []
        lines = [
            f"{page.ref} : {len(refs)} fiche(s)"
            + (" (déjà extraites)" if again else "")
            + (" — lue comme programme" if self.fiches[refs[0]].candidate.multiple else "")
            if refs
            else f"{page.ref} : aucune fiche."
        ]
        for ref in refs:
            lines.append(f"{ref} · {_resume(self.fiches[ref].event)}")
        return "\n".join(lines)

    def _ref(self, prefix: str) -> str:
        self._next[prefix] += 1
        return f"{prefix}{self._next[prefix]}"

    def _target(self, prefix: str, url: str, title: str, depth: int, origin: str) -> Target:
        """Enregistre une adresse ouvrable. La même adresse garde sa référence."""
        key = normalize_url(url)
        known = self.by_url.get(key)
        if known is not None:
            target = self.targets[known]
            # Retrouvée plus près de la surface : c'est la profondeur la plus
            # courte qui compte, sinon l'ordre des appels déciderait de ce qui
            # peut s'ouvrir.
            target.depth = min(target.depth, depth)
            return target
        target = Target(ref=self._ref(prefix), url=url, title=" ".join(title.split()), depth=depth, origin=origin)
        self.targets[target.ref] = target
        self.by_url[key] = target.ref
        return target

    def _resolve(self, ref: str) -> Target | None:
        ref = ref.strip()
        if ref in self.targets:
            return self.targets[ref]
        known = self.by_url.get(normalize_url(ref)) if ref.startswith("http") else None
        return self.targets[known] if known else None

    def _blocked(self, url: str) -> bool:
        host = urlsplit(url).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        return any(host == d or host.endswith(f".{d}") for d in self.ctx.config.blocked_domains)

    def seed(self, urls: list[str]) -> list[Target]:
        """Les points de départ du mode « site », offerts comme des résultats."""
        return [self._target("r", url, "", 0, origin="") for url in urls]


def _resume(event: ExtractedEvent) -> str:
    """Une fiche en une ligne : de quoi décider de la proposer, pas plus."""
    if not event.relevant:
        return f"hors sujet ({event.skip_reason or 'sans motif'})"
    parts = [f"« {event.title or 'sans titre'} »"]
    dates = " → ".join(d for d in (event.date_start, event.date_end) if d)
    if dates:
        parts.append(dates)
    elif event.permanent:
        parts.append("permanente")
    lieu = ", ".join(x for x in (event.venue_name, event.venue_city) if x)
    if lieu:
        parts.append(lieu)
    if event.age_min is not None or event.age_max is not None:
        parts.append(f"{event.age_min if event.age_min is not None else '?'}-"
                     f"{event.age_max if event.age_max is not None else '?'} ans")
    if event.free:
        parts.append("gratuit")
    elif event.price is not None:
        parts.append(f"{event.price:g} €")
    return " · ".join(parts)


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


#: Les descriptions sont le mode d'emploi que le pilote lit. Elles disent ce
#: que l'outil rend et ce qu'il coûte : c'est ce qui lui permet d'arbitrer.
SCHEMAS: list[dict[str, Any]] = [
    _fn(
        "search",
        "Lance une recherche web (Google). Rend des résultats numérotés r1, r2… "
        "avec titre, adresse et extrait. Coûte une recherche sur un quota limité : "
        "formule des requêtes précises (lieu, public, type de sortie).",
        {"query": {"type": "string", "description": "La requête, en français."}},
        ["query"],
    ),
    _fn(
        "open",
        "Télécharge une page et dit ce qu'elle est : « sortie » (un événement), "
        "« programme » (plusieurs sorties sur une même page) ou « agenda » (une "
        "liste de liens vers des sorties). Rend une référence de page p1, p2…, "
        "son titre, son nombre de liens et le début de son texte. N'accepte que "
        "des références r… ou l… rendues par search ou links.",
        {"ref": {"type": "string", "description": "Une référence r… ou l…"}},
        ["ref"],
    ),
    _fn(
        "links",
        "Liste les liens d'une page ouverte (déjà vus par un run précédent : "
        "écartés), 25 à la fois, avec le texte qui les entoure. Gratuit. Le "
        "filtre garde les liens dont le texte, le contexte ou l'adresse "
        "contient ce mot (sans accents ni majuscules) : « enfant », « jeune "
        "public », « famille », un nom de salle…",
        {
            "page": {"type": "string", "description": "Une référence p…"},
            "filtre": {"type": "string", "description": "Mot à chercher. Vide : tous."},
            "suite": {"type": "integer", "description": "0 pour les 25 premiers, 1 pour les suivants…"},
        },
        ["page"],
    ),
    _fn(
        "extract",
        "Lit une page ouverte et en tire les fiches de sortie (titre, dates, lieu, "
        "âge, tarif), f1, f2… Une page de sortie en donne une, un programme "
        "plusieurs. Coûte un appel à un modèle : à réserver aux pages de sortie "
        "ou de programme, pas aux agendas.",
        {"page": {"type": "string", "description": "Une référence p…"}},
        ["page"],
    ),
    _fn(
        "propose",
        "Retient une fiche : cherche la page de l'organisateur si la fiche vient "
        "d'un agrégateur, vérifie les dates, la zone et les doublons, géocode "
        "l'adresse. Rend « retenue » ou le motif du refus.",
        {"fiche": {"type": "string", "description": "Une référence f…"}},
        ["fiche"],
    ),
    _fn(
        "finish",
        "Clôt l'exploration. À appeler quand l'objectif est atteint, quand le "
        "budget est épuisé, ou quand continuer ne rapporterait plus rien.",
        {"bilan": {"type": "string", "description": "Deux ou trois phrases : ce qui a marché, ce qui n'a rien donné."}},
        ["bilan"],
    ),
]
