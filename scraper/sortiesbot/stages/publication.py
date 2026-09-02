"""Étage 6 — une fiche devient une proposition, ou est écartée en le disant.

Le plus long des six, et le plus délicat : géocodage, dates réelles, tarif,
illustration, puis soumission. C'est aussi le seul qui tourne une fois par
**fiche** et non par page — une page de programme en porte vingt, et chacune
mérite sa propre brique dans le graphe. C'est ce qui permet de voir laquelle
des vingt sorties d'un festival a échoué au géocodage.

Ce qui ne peut pas être déterminé part avec une valeur convenue plutôt que de
faire perdre la sortie : adresse non géocodée en (0, 0), tarif introuvable à
-1. Le site connaît la convention et la modération refuse l'approbation tant
qu'elles ne sont pas corrigées.
"""

from __future__ import annotations

import unicodedata

from .. import geocode as geocoding
from ..api import ApiError
from ..models import Candidate, ExtractedEvent
from ..payload import UNKNOWN_PRICE, OutOfPeriod, Rejected, build_payload
from ..photo import PhotoError, download
from ..schedule import Schedule, resolve as resolve_schedule
from ..store import event_key
from . import Stage
from .base import Brick, PageContent


def _fold(text: str) -> str:
    """Compare des noms de catégories sans se soucier de la casse ni des accents."""
    stripped = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in stripped if not unicodedata.combining(c))


def resolve_category(name: str, categories: dict[str, int], default: str) -> int:
    """Rattache la catégorie annoncée par le modèle à une catégorie du site."""
    if not categories:
        return 0  # dry-run sans API joignable : identifiant symbolique.
    by_fold = {_fold(k): v for k, v in categories.items()}
    for candidate in (name, default):
        found = by_fold.get(_fold(candidate or ""))
        if found is not None:
            return found
    raise Rejected(f"catégorie « {name or '?'} » inconnue et « {default} » absente du site")


def _out_of_area(postal_code: str, prefixes: list[str]) -> bool:
    """Un code postal connu hors zone écarte la sortie.

    Un géocodage hors zone échoue déjà, mais la sortie partait quand même en
    (0, 0) « adresse à compléter » — un spectacle à Chantilly, dans l'Oise,
    s'est retrouvé dans un run Île-de-France.
    """
    code = postal_code.strip()
    return bool(code and prefixes and not code.startswith(tuple(prefixes)))


def describe_schedule(schedule: Schedule, payload: dict) -> str:
    """Le calendrier en une ligne, pour la colonne « Détail » de la console."""
    plage = " → ".join(d for d in (payload["dateStart"], payload["dateEnd"]) if d)
    if not schedule.precise:
        return f"{plage} — tous les jours" if plage else "sortie permanente"
    jours = ", ".join(schedule.weekdays)
    detail = f"{len(schedule.dates)} date(s) [{schedule.source}]"
    return f"{plage} — {detail}" + (f" : {jours}" if jours else "")


class Publication(Brick):
    stage = Stage.PUBLISH

    def run(
        self, extracted: ExtractedEvent, candidate: Candidate, page: PageContent
    ) -> None:
        """Publie une fiche, ou l'écarte en journalisant pourquoi."""
        with self.opened(url=page.url, title=extracted.title) as st:
            self._publish(extracted, candidate, page, st)

    def _publish(
        self,
        extracted: ExtractedEvent,
        candidate: Candidate,
        page: PageContent,
        st,
    ) -> None:
        config, log, store = self.config, self.log, self.ctx.store
        summary = self.summary
        # L'adresse de la page **lue**, qui n'est pas toujours celle qu'on
        # avait repérée : la lecture a pu lui préférer sa version française.
        # C'est celle-là qu'on mémorise et qu'on propose au site, sans quoi la
        # sortie partirait avec un lien dont le contenu n'est pas celui d'où
        # elle a été tirée.
        url = page.url
    
        # Sur une page de programme, l'unité mémorisable n'est pas la page mais
        # chacune de ses sorties : sinon un programme lu une fois ne serait plus
        # jamais relu, et tout ce qu'il annoncera ensuite serait perdu.
        key = event_key(url, extracted.title) if candidate.multiple else None
    
        if not extracted.relevant:
            summary.skipped_irrelevant += 1
            log.event("skip", reason=extracted.skip_reason or "hors sujet", url=url)
            store.report(
                url,
                "irrelevant",
                key=key,
                title=candidate.title,
                reason=extracted.skip_reason or "hors sujet",
            )
            st.produced(f"écartée : {extracted.skip_reason or 'hors sujet'}")
            return
    
        if key is not None:
            if key in self.ctx.keys or store.seen(url, key):
                summary.duplicates += 1
                log.event("skip", reason="sortie déjà connue", url=url, title=extracted.title)
                store.report(
                    url,
                    "duplicate",
                    key=key,
                    title=extracted.title,
                    reason="déjà relevée sur ce programme",
                    remember=False,
                )
                st.produced("écartée : sortie déjà connue")
                return
            self.ctx.keys.add(key)
    
        log.event(
            "extract",
            url=url,
            title=extracted.title,
            venue=f"{extracted.venue_name} — {extracted.venue_city}".strip(" —"),
        )
    
        if _out_of_area(extracted.venue_postal_code, config.postal_prefixes):
            summary.out_of_area += 1
            if not config.keep_out_of_scope:
                reason = f"code postal {extracted.venue_postal_code} hors zone"
                log.event("skip", reason=reason, url=url)
                store.report(url, "out_of_area", key=key, title=extracted.title, reason=reason)
                st.produced(f"écartée : {reason}")
                return
            log.event("out_of_scope", field="zone", url=url, detail=extracted.venue_postal_code)
    
        geo = geocoding.geocode(extracted)
        log.event(
            "geocode", url=url, address=geo.query, located=geo.located,
            lat=geo.location.lat, lng=geo.location.lng, reason=geo.reason,
        )
        if not geo.located:
            summary.ungeocoded += 1
    
        try:
            category_id = resolve_category(extracted.category, self.ctx.categories, config.default_category)
            payload = build_payload(
                extracted,
                geo.location,
                category_id,
                url,
                until=None if config.keep_out_of_scope else config.date_to,
            )
        except OutOfPeriod as err:
            summary.out_of_period += 1
            log.event("skip", reason=str(err), url=url)
            store.report(url, "out_of_period", key=key, title=extracted.title, reason=str(err))
            st.produced(f"écartée : {err}")
            return
        except Rejected as err:
            summary.skipped_invalid += 1
            log.event("skip", reason=str(err), url=url)
            store.report(
                url,
                "invalid",
                key=key,
                title=extracted.title or candidate.title,
                reason=str(err),
            )
            st.produced(f"écartée : {err}")
            return
    
        if payload["dateStart"] and payload["dateStart"] > config.date_to.isoformat():
            summary.out_of_period += 1
            log.event("out_of_scope", field="période", url=url, detail=payload["dateStart"])
    
        # Dates réelles de la sortie.
        schedule = resolve_schedule(
            payload["dateStart"] or "",
            payload["dateEnd"] or "",
            weekdays=extracted.weekdays,
            announced=extracted.dates,
            json_ld=page.json_ld_dates,
        )
        # Le site ne reçoit des jours que s'ils apprennent quelque chose : sinon
        # la liste reste vide, et sa période vaut pour tous ses jours.
        payload["dates"] = list(schedule.dates)
        if schedule.precise:
            summary.scheduled += 1
        # La plage est journalisée avec le calendrier : sans elle, impossible de
        # rejuger après coup si une date isolée était une séance ou un premier jour.
        log.event(
            "schedule",
            url=url,
            title=payload["title"],
            start=payload["dateStart"],
            end=payload["dateEnd"],
            **schedule.as_dict(),
        )
    
        if payload["price"] == UNKNOWN_PRICE:
            summary.unpriced += 1
            log.event("incomplete", field="tarif", url=url, title=payload["title"])
        if not geo.located:
            log.event("incomplete", field="adresse", url=url, title=payload["title"])
    
        # Ce que la page déclare passe avant ce que le modèle a pu écrire : lui ne
        # voit que du texte, donc une URL de sa part est au mieux une devinette.
        # Les sorties d'un même programme partagent l'illustration de la page :
        # c'est la seule que le HTML donne, et une vignette juste vaut mieux que
        # vingt fiches nues.
        photo_url = page.image or extracted.photo_url
        if not photo_url:
            log.event("photo", status="aucune image sur la page", url=url)
    
        photo = None
        if self.ctx.submit and photo_url:
            try:
                # Même session que les pages : sans notre User-Agent, beaucoup de
                # serveurs refusent l'image qu'ils viennent pourtant d'annoncer.
                photo = download(photo_url, self.ctx.fetcher.session)
                log.event("photo", status="téléchargée", url=photo_url)
            except PhotoError as err:
                log.event("photo", status=f"ignorée ({err})", url=photo_url)
    
        record = {
            "payload": payload,
            "source_url": url,
            "found_on": candidate.source,
            "photo_url": photo_url,
            "located": geo.located,
            "schedule": schedule.as_dict(),
        }
    
        if not self.ctx.submit:
            self.ctx.result.events.append(record)
            log.event("dry_run", title=payload["title"], url=url)
            # Un essai ne mémorise pas : sinon la sortie qu'il vient de repérer ne
            # serait jamais proposée, le run réel la sautant comme « déjà vue ».
            store.report(
                url,
                "dry_run",
                key=key,
                title=payload["title"],
                reason=describe_schedule(schedule, payload),
                remember=False,
            )
            st.produced(f"retenue sans soumission : {payload['title']}", retained=1)
            return
    
        try:
            event = self.ctx.api.create_event(payload, photo)
        except ApiError as err:
            summary.errors += 1
            log.error("submit", str(err), url=url)
            store.report(
                url, "error", key=key, title=payload["title"], reason=str(err), remember=False
            )
            st.produced(f"soumission en échec : {err}")
            return
    
        event_id = event.get("id")
        record["event_id"] = event_id
        self.ctx.result.events.append(record)
        summary.submitted += 1
        store.report(
            url,
            "submitted",
            key=key,
            title=payload["title"],
            reason=describe_schedule(schedule, payload),
            event_id=event_id,
        )
        log.event("submit", event_id=event_id, title=payload["title"], url=url)
        st.produced(f"proposée à la modération (#{event_id})", submitted=1)
