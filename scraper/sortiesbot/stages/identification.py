"""Étage 2 — constater ce qu'est une page. Gratuit le plus souvent.

La découverte rend des URL, sans rien en dire. C'est ici qu'on décide où
chacune va :

* un **agenda** part au dépouillement — il renvoie vers des fiches ;
* une **sortie** saute directement à la lecture ;
* un **programme** saute lui aussi à la lecture, mais on en attend plusieurs
  fiches d'un coup : c'est le festival qui tient sur une page, où les entrées
  ne sont reliées que par des ancres. Le HTML est téléchargé une fois pour toutes, et le
`Fetcher` le rend à qui le redemandera.

La cascade est dans `classify.py` : URL, pagination, JSON-LD, métadonnées, et
un appel au modèle sur le seul condensé de la page quand tout se tait. Les
quatre premiers signaux ne coûtent rien ; le cinquième coûte quelques centaines
de jetons, jamais la page entière — celle-là, l'extraction la paie déjà.

C'est aussi ici que se règle la langue. Une page qui se déclare anglaise, ou
dont l'adresse l'annonce (`/en/`), est échangée contre sa jumelle française
quand le site en déclare une : voir [`language.py`](../language.py). Le faire
à cet étage plutôt qu'à la lecture n'est pas indifférent — un agenda anglais
ne mène qu'à des fiches anglaises, alors que le même agenda en français mène
aux fiches françaises. Corriger la racine corrige la branche.

Une page qu'on ne sait pas reconnaître part **en agenda**, et c'est délibéré :
l'erreur n'est pas symétrique. Prendre une sortie pour un agenda coûte un appel
de sélection et se rattrape tout seul — le dépouillement ne donne rien, et
l'orchestrateur relit la page pour elle-même. Prendre un agenda pour une sortie
coûte tous ses liens, sans rattrapage.

Chaque page reconnue laisse au registre son condensé et son verdict. C'est le
corpus : de quoi, un jour, entraîner de quoi se passer du cinquième signal.
"""

from __future__ import annotations

from dataclasses import replace

from ..classify import AGENDA, INCONNU, PROGRAMME, SORTIE, Digest, Verdict, classify, digest
from ..harvest import FetchError, links_of
from ..language import french_version
from ..models import FoundPage
from ..providers.base import ProviderError
from . import Stage
from .base import Brick


class Identification(Brick):
    stage = Stage.IDENTIFY

    def run(self, source: FoundPage) -> tuple[str, FoundPage] | None:
        """Rend la nature de la page et l'adresse retenue. `None` si injoignable.

        La nature vaut « agenda », « sortie » ou « programme ». `None` n'est
        pas un verdict : c'est l'absence de question posée, une page qu'on n'a
        pas pu lire ne va nulle part.

        L'adresse rendue n'est pas toujours celle qu'on a reçue : c'est le
        premier étage qui tient le HTML, donc le premier qui peut constater
        qu'une page anglaise a une jumelle française — et c'est celle-là qu'il
        faut dépouiller, puisque ses liens mèneront eux aussi au français.
        """
        url = source.url
        with self.opened(url=url, title=source.title) as st:
            try:
                html = self.ctx.fetcher.get_html(url)
            except FetchError as err:
                self.log.error("identify", str(err), url=url)
                st.produced(f"injoignable : {err}")
                return None

            url, html = french_version(url, html, self.ctx.fetcher, self.log)
            source = source if url == source.url else replace(source, url=url)

            liens = links_of(html, url)
            verdict = classify(html, url, links=len(liens))
            card = digest(html, url, liens)
            asked = ""
            if verdict.kind == INCONNU:
                verdict, asked = self._asked(card, verdict)

            # « Inconnu » part en agenda : c'est le seul des trois chemins
            # qui se rattrape tout seul si l'on s'est trompé.
            nature = verdict.kind if verdict.kind in (SORTIE, PROGRAMME) else AGENDA
            self._record(url, verdict, card, asked, nature)
            st.produced(
                f"{nature} — {verdict.detail}"
                + (" (indécis, traité en agenda)" if verdict.kind == INCONNU else ""),
                nature=nature,
                signal=verdict.signal,
            )
            return nature, source

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
