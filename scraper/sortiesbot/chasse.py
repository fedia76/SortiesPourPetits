"""La chasse : peupler le corpus de l'étage 2 depuis un prompt.

Étiqueter est le seul travail coûteux du banc, et le corpus de l'étage 2 se
remplissait une adresse à la fois, collée à la main dans la console. Une
chasse fait le trajet d'un coup : elle lance les recherches de l'étage 1,
télécharge ce qu'elles remontent, et **précoche** chaque page avec ce que
l'étage 2 en dit. Il ne reste qu'à corriger ce qui est faux.

C'est le principe qui vaut déjà pour les liens d'un agenda — « la brique
précoche, l'humain corrige » — appliqué un étage plus haut. Avec le même
danger, et il faut le nommer : un corpus rempli en acceptant les propositions
de la brique mesurerait la brique contre elle-même, et le taux serait flatteur
par construction. D'où deux choses, et elles ne sont pas décoratives :

* la précoche **n'est jamais un verdict** — un candidat que l'étage 2 ne sait
  pas reconnaître part sans proposition, et attend un humain. Le pipeline,
  lui, tranche : il traite « inconnu » en agenda. Reprendre ce repli ici
  écrirait au corpus ce que le pipeline *fait* au lieu de ce que la page
  *est*, c'est-à-dire exactement ce qu'on cherche à mesurer ;
* ce qu'un humain a **corrigé** est noté à part de ce qu'il a laissé passer
  (`EvalNature.origin`, côté site). Les renseignements sont dans les corrigés.

Une chasse est en ligne, et c'est assumé : elle construit le corpus, elle ne
le mesure pas. Le HTML qu'elle télécharge est gelé au passage — la page qu'un
run rejouera est donc exactement celle sur laquelle la précoche a été faite,
et non celle que le site servira le jour où quelqu'un validera.
"""

from __future__ import annotations

from typing import Any

from .classify import AGENDA, INCONNU, PROGRAMME, SORTIE, Digest, Verdict, classify, digest
from .config import Config
from .evaluation import archive_html
from .harvest import Fetcher, FetchError, links_of
from .journal import RunLog
from .language import french_version
from .models import FoundPage
from .providers.base import Provider, ProviderError

# `archive_html` vient de `evaluation` : geler une page est le même geste,
# qu'on gèle un agenda du corpus ou une candidate de chasse, et c'est là que
# la capture vit.

#: Plafond dur du nombre de pages ouvertes par une chasse. Chacune est un
#: téléchargement chez quelqu'un, et surtout une ligne qu'un humain devra
#: relire : au-delà, on ne peuple plus un corpus, on le noie.
MAX_HUNT_PAGES = 100


def hunt(
    config: Config,
    provider: Provider,
    log: RunLog,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    """Lance les recherches, ouvre ce qu'elles remontent, et précoche.

    Les deux premières lignes sont l'étage 1 tel quel — `provider.queries` et
    `provider.search`, importés, pas réécrits. La suite est l'étage 2 sur
    chaque page : la cascade de `classify`, et le recours au modèle quand elle
    se tait, exactement comme `stages/identification.py`.

    Ce qui n'est **pas** repris de l'étage 1, c'est son plafond : la découverte
    coupe à `max_agendas` parce qu'elle ne peut pas tout ouvrir dans un run
    payant. Ici le plafond est celui de la chasse, et ce qui le dépasse est
    compté plutôt que tu — sans quoi « tous les liens de la recherche » serait
    une promesse à moitié tenue, et personne ne saurait de quelle moitié.

    Peut lever `ProviderError` : une recherche impossible n'a rien à rendre, et
    c'est le worker qui en rend compte.
    """
    fetcher = fetcher or Fetcher()

    queries = list(config.queries) or provider.queries(config, log)
    log.event(
        "queries",
        source="configuration" if config.queries else "modele",
        count=len(queries),
    )

    found = provider.search(queries, config, log)
    plafond = max(1, min(config.max_agendas, MAX_HUNT_PAGES))
    gardees, au_dela = found[:plafond], found[plafond:]
    for page in au_dela:
        log.warn(
            "chasse",
            f"plafond de {plafond} page(s) atteint : celle-ci ne sera pas ouverte",
            url=page.url,
        )

    pages = [hunt_page(page, config, provider, log, fetcher) for page in gardees]
    return {"queries": queries, "overCap": len(au_dela), "pages": pages}


def hunt_page(
    page: FoundPage,
    config: Config,
    provider: Provider,
    log: RunLog,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    """Ce qu'une page candidate est, d'après l'étage 2, et son HTML gelé.

    Une page injoignable est rendue **quand même**, sans archive et sans
    proposition : l'adresse vaut d'être vue par un humain, qui la mettra au
    corpus si elle l'intéresse — la file de capture la gèlera alors plus tard.
    La perdre parce qu'un site répondait mal ce jour-là serait perdre le
    travail de la recherche pour un accident du web.
    """
    fetcher = fetcher or Fetcher()
    out: dict[str, Any] = {
        "url": page.url,
        "foundUrl": page.url,
        "title": page.title,
        "query": page.query,
    }
    try:
        html = fetcher.get_html(page.url)
    except FetchError as err:
        out["error"] = str(err)[:300]
        log.warn("chasse", f"injoignable : {err}", url=page.url)
        return out

    # L'échange de langue fait partie de l'étage : c'est lui qui décide quelle
    # page est reconnue, et un agenda anglais ne mène qu'à des fiches anglaises.
    url, html = french_version(page.url, html, fetcher, log)
    out["url"] = url

    liens = links_of(html, url)
    verdict = classify(html, url, links=len(liens))
    card = digest(html, url, liens)
    asked = ""
    if verdict.kind == INCONNU:
        verdict, asked = _hunt_asked(card, verdict, config, provider, log)

    out.update(
        {
            # Vide quand l'étage 2 ne sait pas : une case à cocher de moins,
            # et un humain de plus. Le repli « dans le doute, agenda » est une
            # décision d'orchestration, pas une observation sur la page.
            "nature": "" if verdict.kind == INCONNU else verdict.kind,
            "signal": verdict.signal,
            "detail": verdict.detail[:300],
            "confidence": verdict.confidence,
            "asked": asked,
            "links": card.links,
            "dated": card.dated,
            "heading": card.heading,
            "opening": card.opening,
            "chars": len(html),
        }
    )
    packed = archive_html(html)
    if packed:
        out["html"] = packed
    log.event("chasse", url=url, nature=out["nature"] or "indecis", signal=verdict.signal)
    return out


def _hunt_asked(
    card: Digest, fallback: Verdict, config: Config, provider: Provider, log: RunLog
) -> tuple[Verdict, str]:
    """Le recours au modèle, dans les mêmes termes qu'en production.

    Son échec ne coûte rien : sans réponse, la page reste indécise et part sans
    précoche — ce qui est déjà son sort quand aucun signal ne tranche. Et un
    modèle qui répond « inconnu » est **cru sur parole** : c'est une réponse
    utile, pas une panne, et la page revient à un humain.
    """
    if not config.classify_model:
        return fallback, ""
    try:
        nature, pourquoi = provider.classify(card.as_prompt(), config, log)
    except ProviderError as err:
        log.warn("chasse", f"reconnaissance impossible : {err}", url=card.url)
        return fallback, ""
    if nature not in (AGENDA, SORTIE, PROGRAMME):
        return fallback, config.classify_model
    verdict = Verdict(nature, "modele", pourquoi or "sans motif", "probable")
    return verdict, config.classify_model
