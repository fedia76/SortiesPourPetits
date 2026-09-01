"""Étage 2 — constater ce qu'est une page. Gratuit le plus souvent.

La découverte rend des URL, sans rien en dire. C'est ici qu'on décide où
chacune va : un **agenda** part au dépouillement, une **sortie** saute
directement à la lecture. Le HTML est téléchargé une fois pour toutes, et le
`Fetcher` le rend à qui le redemandera.

La cascade est dans `classify.py` : URL, pagination, JSON-LD, métadonnées, et
un appel au modèle sur le seul condensé de la page quand tout se tait. Les
quatre premiers signaux ne coûtent rien ; le cinquième coûte quelques centaines
de jetons, jamais la page entière — celle-là, l'extraction la paie déjà.

Une page qu'on ne sait pas reconnaître part **en agenda**, et c'est délibéré :
l'erreur n'est pas symétrique. Prendre une sortie pour un agenda coûte un appel
de sélection et se rattrape tout seul — le dépouillement ne donne rien, et
l'orchestrateur relit la page pour elle-même. Prendre un agenda pour une sortie
coûte tous ses liens, sans rattrapage.

Chaque page reconnue laisse au registre son condensé et son verdict. C'est le
corpus : de quoi, un jour, entraîner de quoi se passer du cinquième signal.
"""

from __future__ import annotations

from ..classify import AGENDA, INCONNU, SORTIE, Digest, Verdict, classify, digest
from ..harvest import FetchError, links_of
from ..models import FoundPage
from ..providers.base import ProviderError
from . import Stage
from .base import Brick


class Identification(Brick):
    stage = Stage.IDENTIFY

    def run(self, source: FoundPage) -> str | None:
        """Rend « agenda » ou « sortie », ou `None` si la page est injoignable.

        `None` n'est pas un verdict : c'est l'absence de question posée. Une
        page qu'on n'a pas pu lire ne va nulle part.
        """
        url = source.url
        with self.opened(url=url, title=source.title) as st:
            try:
                html = self.ctx.fetcher.get_html(url)
            except FetchError as err:
                self.log.error("identify", str(err), url=url)
                st.produced(f"injoignable : {err}")
                return None

            liens = links_of(html, url)
            verdict = classify(html, url, links=len(liens))
            card = digest(html, url, liens)
            asked = ""
            if verdict.kind == INCONNU:
                verdict, asked = self._asked(card, verdict)

            nature = SORTIE if verdict.kind == SORTIE else AGENDA
            self._record(url, verdict, card, asked, nature)
            st.produced(
                f"{nature} — {verdict.detail}"
                + (" (indécis, traité en agenda)" if verdict.kind == INCONNU else ""),
                nature=nature,
                signal=verdict.signal,
            )
            return nature

    # ------------------------------------------------------------ le recours

    def _asked(self, card: Digest, fallback: Verdict) -> tuple[Verdict, str]:
        """Fait trancher le modèle sur le condensé. Rend le verdict et le modèle.

        Un échec n'est pas rattrapé : « inconnu » a déjà un comportement défini,
        et un second appel coûterait sans rien garantir de plus.
        """
        model = self.config.classify_model
        if not model:
            return fallback, ""
        if self.ctx.budget_reached:
            self.log.event("skip", reason="budget atteint, page non reconnue", url=card.url)
            return fallback, ""
        try:
            nature, pourquoi = self.ctx.provider.classify(card.as_prompt(), self.config, self.log)
        except ProviderError as err:
            self.log.warn("identify", f"reconnaissance impossible : {err}", url=card.url)
            return fallback, ""
        return Verdict(nature, "modele", pourquoi or "sans motif", "probable"), model

    # ----------------------------------------------------------- la trace

    def _record(
        self, url: str, verdict: Verdict, card: Digest, asked: str, nature: str
    ) -> None:
        """Au journal pour la console, au registre pour les mois à venir."""
        fields = verdict.as_dict()
        self.log.event("identified", url=url, nature=nature, asked=asked, **fields)
        self.ctx.ledger.record(
            "classify",
            url=url,
            stage=self.stage.value,
            nature=nature,
            asked=asked,
            digest=card.as_dict(),
            **fields,
        )
