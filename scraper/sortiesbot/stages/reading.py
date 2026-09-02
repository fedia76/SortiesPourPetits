"""Étage 4 — la lecture d'une page. Python pur, donc gratuit.

C'est le dernier point où une page peut être abandonnée sans avoir rien coûté,
et c'est pour ça que les trois filtres sont ici et nulle part ailleurs :
domaine bloqué, page déjà vue, page vide. Passé cet étage, le modèle est
appelé et la page est payée.

C'est aussi le dernier point où l'adresse peut encore changer : une page
anglaise dont le site déclare la version française est remplacée par
celle-ci (voir [`language.py`](../language.py)), et c'est l'adresse retenue
ici qui sera proposée au site. Les deux filtres se rejouent alors sur elle —
la jumelle n'a pas la même adresse, donc pas la même mémoire.

Un même HTML est lu trois fois, et une seule de ces lectures part au modèle :
le texte. Les dates JSON-LD et l'illustration ne le voient jamais — d'où
`PageContent`, qui les rend ensemble plutôt que de laisser l'appelant les
oublier en chemin.
"""

from __future__ import annotations

from ..harvest import FetchError, json_ld_dates, main_image, page_text
from ..language import french_version
from ..models import Candidate
from . import Stage
from .base import Brick, PageContent

#: En dessous, la page n'a pas de contenu exploitable (mur de cookies, page
#: vide, redirection JavaScript) : inutile de payer une extraction dessus.
MIN_PAGE_CHARS = 200


class Reading(Brick):
    stage = Stage.READ

    def run(self, candidate: Candidate) -> PageContent | None:
        """Rend le contenu de la page, ou `None` si elle est écartée.

        Le motif de l'écart est journalisé et mémorisé ici : l'appelant n'a
        qu'à constater l'absence de contenu.
        """
        url = candidate.url
        store = self.ctx.store

        with self.opened(url=url, source=candidate.source) as st:
            if self._blocked(url):
                self.summary.skipped_blocked += 1
                self.log.event("skip", reason="domaine bloqué", url=url)
                # Provisoire : la liste des domaines bloqués est un réglage,
                # pas un jugement sur la page. La retirer doit suffire à la lire.
                store.report(url, "blocked", title=candidate.title, remember=False)
                st.produced("écartée : domaine bloqué", chars=0)
                return None

            # Une page de programme échappe à ce filtre, et c'est le but : le
            # programme d'un festival s'étoffe, et ce sont ses sorties qui sont
            # mémorisées une à une, pas lui. Le relire est ce qu'on veut.
            if not candidate.multiple and store.seen(url):
                self.summary.skipped_seen += 1
                self.log.event("skip", reason="déjà vue lors d'un run précédent", url=url)
                store.report(url, "seen", title=candidate.title, remember=False)
                st.produced("écartée : déjà vue", chars=0)
                return None

            try:
                html = self.ctx.fetcher.get_html(url)
            except FetchError as err:
                self.summary.errors += 1
                self.log.error("extraction", str(err), url=url)
                # Un site injoignable aujourd'hui peut répondre demain : on ne
                # mémorise pas, le prochain run réessaiera.
                store.report(
                    url, "error", title=candidate.title, reason=str(err), remember=False
                )
                st.produced(f"page inaccessible ({err})", chars=0)
                return None

            # La page a peut-être une jumelle française : c'est elle qu'on lit,
            # et c'est son adresse qui sera proposée au site.
            url, html = french_version(url, html, self.ctx.fetcher, self.log)
            if url != candidate.url and self._again(url, candidate, st):
                return None

            text = page_text(html, limit=self.config.max_page_chars)
            declared = json_ld_dates(html)
            image = main_image(html, url)

            if len(text) < MIN_PAGE_CHARS:
                self.summary.skipped_invalid += 1
                self.log.event("skip", reason="page vide ou illisible", url=url)
                store.report(
                    url, "invalid", title=candidate.title, reason="page vide ou illisible"
                )
                st.produced("écartée : page vide ou illisible", chars=len(text))
                return None

            self.log.event(
                "page",
                url=url,
                chars=len(text),
                json_ld=len(declared),
                image=bool(image),
                image_url=image,
            )
            st.produced(
                f"{len(text)} caractères, {len(declared)} date(s) JSON-LD",
                chars=len(text),
                json_ld=len(declared),
            )
            return PageContent(url=url, text=text, json_ld_dates=declared, image=image)

    def _again(self, url: str, candidate: Candidate, st) -> bool:
        """Les deux filtres, rejoués sur la version française retenue.

        La jumelle n'a pas la même adresse, et c'est la sienne qui sera
        mémorisée à la publication. Sans ce second passage, une sortie déjà
        proposée sous son adresse française reviendrait à chaque run par sa
        porte anglaise — et un site dont la version française est hébergée sur
        un domaine bloqué échapperait au filtre.
        """
        store = self.ctx.store
        if self._blocked(url):
            self.summary.skipped_blocked += 1
            self.log.event("skip", reason="domaine bloqué", url=url)
            store.report(url, "blocked", title=candidate.title, remember=False)
            st.produced("écartée : domaine bloqué", chars=0)
            return True
        if not candidate.multiple and store.seen(url):
            self.summary.skipped_seen += 1
            self.log.event("skip", reason="déjà vue lors d'un run précédent", url=url)
            store.report(url, "seen", title=candidate.title, remember=False)
            st.produced("écartée : déjà vue", chars=0)
            return True
        return False

    def _blocked(self, url: str) -> bool:
        from urllib.parse import urlsplit

        host = urlsplit(url).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        return any(
            host == d or host.endswith(f".{d}") for d in self.config.blocked_domains
        )
