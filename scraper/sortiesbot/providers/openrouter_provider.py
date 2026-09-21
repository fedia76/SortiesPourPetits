"""Le modèle change, le moteur reste.

OpenRouter est un **routeur** : une seule clé, une seule adresse, et derrière
des centaines de modèles — ceux d'Anthropic, mais aussi Gemini, Qwen, Mistral,
Llama. L'intérêt ici n'est pas la variété pour elle-même, c'est qu'un étage du
pipeline puisse changer de modèle sans changer de code, et qu'on puisse
comparer ce que ça donne : les quatre appels du modèle sont bornés et
mesurables, c'est exactement ce qui se compare bien.

## Ce que ce fournisseur remplace, et ce qu'il ne remplace pas

**Quatre des cinq appels du `Protocol` : formuler, reconnaître, trier,
remplir.** Le cinquième, la recherche, ne le concerne pas — OpenRouter n'est
pas un moteur. C'est Serper qui la lance, comme pour le fournisseur du même
nom, et `get_provider` compose les deux :

    serper      = Serper pour chercher  + Claude pour les quatre autres appels
    openrouter  = Serper pour chercher  + OpenRouter pour les quatre autres

Les deux lignes disent la même chose d'un seul champ `provider`, qui nomme en
réalité **deux** choix — le moteur et le modèle. C'est une conflation, et elle
est assumée tant qu'il n'y a que ces trois combinaisons : le jour où l'on
voudra « outil serveur Anthropic + modèle OpenRouter », il faudra deux champs
au lieu d'un, en base, dans la console et ici. Rien de ce fichier ne s'y
opposera.

## Quel modèle

Celui que la configuration nomme, quand elle en nomme un qu'OpenRouter
comprend — c'est-à-dire un slug `éditeur/modèle`. Sinon `MODELE_DEFAUT`, et
c'est le cas normal : la console pré-remplit ses quatre champs avec un nom du
vocabulaire d'Anthropic, qui ne veut rien dire là-bas. Les noms du pipeline ne
sont donc pas traduits, ils valent « au choix du scraper » — on ne passe pas à
un routeur pour continuer à payer le même modèle par un intermédiaire.

## Ce qu'on demande au service, et pourquoi

* **Du JSON structuré** (`response_format: json_schema`, `strict`). Les
  schémas sont ceux de `schemas.py` — les mêmes, exactement, que ceux envoyés
  à Claude : sans ça, deux fournisseurs rendraient deux fiches différentes et
  le banc mesurerait notre code en croyant mesurer des modèles.
* **Un routage qui les honore** (`provider: {require_parameters: true}`). Tous
  les hébergeurs d'un même modèle ne savent pas contraindre une sortie ;
  OpenRouter, laissé libre, choisirait parfois l'un d'eux et rendrait du texte
  approchant. Mieux vaut un 404 lisible qu'une fiche plausible.
* **La facture** (`usage: {include: true}`). Le service dit ce que l'appel a
  coûté, en dollars, tous modèles confondus ; on le lit plutôt que de tenir
  une table de tarifs pour trois cents modèles qui bougent chaque semaine.
  C'est la même règle que chez Serper, et pour la même raison.
* **Le moins de raisonnement possible** (`reasoning: {effort: "low"}`). Le
  couper franchement est refusé par le modèle par défaut —
  `Reasoning is mandatory for this endpoint and cannot be disabled`, HTTP 400 —
  mais le régler ne l'est pas. Et c'est la seule prise qu'on ait sur la seule
  chose qui coûte cher ici : sans ce réglage, une reconnaissance dépensait
  1 312 jetons de sortie à réfléchir pour choisir une étiquette parmi quatre.
  Le plafond de l'appel lui laisse tout de même la place de le faire, voir
  `MARGE_RAISONNEMENT` : un modèle qui déborde doit échouer sur un message
  clair, pas sur une fiche tronquée.

Aucun outil, aucune itération : un aller-retour par appel, comme le reste du
pipeline. La mécanique HTTP n'est pas sortie dans un fichier à part — ce
qu'on a fait pour Serper le jour où l'attribution en a eu besoin : ici il n'y
a qu'un appelant, et un fichier de plus ne dirait rien de neuf.

## Ce que le service rend vraiment

Vérifié le 21 septembre 2026 contre le service, par `tools/openrouter_shape.py`
— les tests, eux, simulent :

    HTTP 200
    Clés de premier niveau : ['choices', 'created', 'id', 'model', 'object',
                              'provider', 'service_tier', 'system_fingerprint',
                              'usage']
    Champs d'un choix      : ['finish_reason', 'index', 'logprobs', 'message',
                              'native_finish_reason']
    Champs d'un message    : ['content', 'reasoning', 'reasoning_details',
                              'refusal', 'role']
    Champs de « usage »    : ['completion_tokens', 'completion_tokens_details',
                              'cost', 'cost_details', 'is_byok',
                              'prompt_tokens', 'prompt_tokens_details',
                              'total_tokens']
    Hébergeur              : CoreWeave  (le modèle par défaut, en `:floor`)

Trois enseignements, et le troisième a coûté un appel pour rien.

La réponse **annonce ce qu'elle a coûté** (`usage.cost`, en dollars) : on le
lit plutôt que de le déduire, comme chez Serper. Elle **nomme l'hébergeur**
(`provider`) et le modèle réellement servi, ce qui n'est pas cosmétique avec un
suffixe `:floor` — il change d'un appel à l'autre.

Et un message porte `reasoning` à côté de `content`. Le tout premier appel réel
est revenu avec `content: null`, `finish_reason: length` et 0,0002 $ facturés :
le modèle avait dépensé les 300 jetons de la reconnaissance à raisonner, sans
rien écrire. Le suivant a tenté de le désactiver, et s'est fait répondre que
c'était impossible sur cet endpoint. D'où `MARGE_RAISONNEMENT`, qui lui en
laisse la place, et un message d'erreur qui nomme ce cas s'il déborde encore.

## Ce que ça coûte, mesuré

La même reconnaissance — le plus petit des quatre appels, sur le modèle par
défaut — avant et après avoir réglé l'effort de raisonnement :

    sans réglage    476 jetons d'entrée, 2 807 de sortie dont 1 312 de
                    raisonnement                              0,001475 $
    effort « low »  476 jetons d'entrée, 37 de sortie dont
                    **zéro** de raisonnement                  0,000090 $

Seize fois moins cher, pour la même page et la même question. Ce n'est pas un
réglage fin : le raisonnement **était** le coût de cet appel, et « low » suffit
à l'annuler tout à fait sur ce modèle-là, là où `enabled: false` se faisait
refuser en 400.

Les deux mesures donnent le tarif par soustraction — 2 770 jetons de sortie de
plus pour 0,001385 $ — soit environ **0,15 $ le million en entrée et 0,50 $ en
sortie**. C'est ce qu'affiche sa page OpenRouter, et ça situe ce modèle face à
Haiku 4.5 (1 $ et 5 $) : sept fois moins cher à l'entrée, dix fois à la sortie.

De quoi estimer les deux étages qui comptent, en ordre de grandeur :

    reconnaissance    GLM 0,000090 $   Haiku ~0,00098 $    ~11 fois moins
    extraction        GLM ~0,00076 $   Haiku ~0,0062 $      ~8 fois moins

**Ce que ces chiffres ne disent pas, et qui décide de tout** : si les fiches
valent les siennes. Les deux appels de la vérification ont d'ailleurs rendu
deux natures différentes pour la même page — « programme » puis « agenda » —,
ce qui s'explique en partie (le premier n'envoie pas la consigne système) mais
ne rassure pas. Un modèle dix fois moins cher qui se trompe une fois sur cinq
coûte plus cher que celui qu'il remplace, en modération. C'est au banc de le
dire, étage par étage, et il sait désormais jouer ce fournisseur.

Réserve de méthode : ces chiffres viennent d'**un appel par réglage**. Les
totaux en dollars sont des mesures ; les tarifs unitaires en sont déduits, et
les deux lignes du tableau ci-dessus en découlent.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from ..config import Config
from ..harvest import Link
from ..journal import RunLog
from ..models import ExtractedEvent, FoundPage, Usage
from ..prompts import SYSTEM
from .anthropic_provider import PRICES
from .base import ProviderError
from .schemas import (
    CLASSIFY_MAX_TOKENS,
    CLASSIFY_SCHEMA,
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_MULTI_MAX_TOKENS,
    EXTRACTION_MULTI_SCHEMA,
    EXTRACTION_SCHEMA,
    QUERIES_MAX_TOKENS,
    QUERIES_SCHEMA,
    SELECT_MAX_TOKENS,
    SELECT_SCHEMA,
    events_from_multi,
    loads_json,
)

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

#: Le même que chez Anthropic : une extraction de page de programme peut
#: rester muette plusieurs minutes, et le worker a son propre chien de garde.
TIMEOUT = 300

#: Attribution facultative, affichée par OpenRouter sur ses classements. Elle
#: ne change ni le routage ni le prix ; elle dit seulement qui appelle.
REFERER = "https://sortiespourpetits.fr"
TITLE = "SortiesPourPetits"

#: Tentatives par appel, la première comprise. Ne se déclenche que sur ce qui
#: est manifestement passager — trop d'appels, hébergeur en carafe. Une erreur
#: de clé, de crédit ou de modèle ne se répare pas en réessayant.
TENTATIVES = 3

#: Secondes avant de réessayer, doublées à chaque fois.
ATTENTE = 2.0

#: Codes qu'on réessaie. 429 : le quota de la minute. 408 : l'hébergeur n'a
#: pas répondu à temps. 502/503 : il est tombé, et OpenRouter en a peut-être
#: un autre sous la main au tour suivant.
CODES_PASSAGERS = (408, 429, 502, 503, 504)

#: Ce qu'on facture quand la réponse ne dit pas ce qu'elle a coûté, en dollars
#: par million de jetons.
#:
#: Elle le dit presque toujours — c'est à ça que sert `usage.include`. Mais le
#: plafond `max_cost_usd` est le seul garde-fou financier du run, et il se
#: compare à un total : un coût manquant compté zéro le désarmerait en
#: silence. Le tarif retenu est donc **volontairement haut**, celui d'un grand
#: modèle, pour que le run s'arrête trop tôt plutôt que jamais. Le journal dit
#: pourquoi son coût est faux — même règle et même raison que
#: `UNKNOWN_MODEL_PRICE` chez Anthropic.
TARIF_INCONNU = (5.0, 25.0)

#: Combien le modèle a le droit de réfléchir, quand il ne sait pas faire
#: autrement. `""` : on ne demande rien, et c'est l'hébergeur qui décide.
#:
#: Le modèle par défaut refuse qu'on lui coupe le raisonnement — voir
#: `MARGE_RAISONNEMENT` —, mais il accepte qu'on le **règle** : sa page
#: OpenRouter expose « low », « high » et « max ». Un appel qui choisit une
#: étiquette parmi quatre, ou qui recopie des numéros de ligne, n'a besoin
#: d'aucun des trois ; à défaut de zéro, c'est « low ».
#:
#: Ce que ça change, mesuré sur la reconnaissance : 1 312 jetons de raisonnement
#: et 0,001475 $ sans réglage, **zéro** jeton et 0,000090 $ avec « low ». Seize
#: fois moins cher pour la même page et la même question — le raisonnement
#: *était* le coût de cet appel. Et « low » l'annule tout à fait sur ce
#: modèle-là, là où `enabled: false` se faisait refuser en 400.
#:
#: Le réglage est envoyé à **tous** les modèles, et ce n'est pas sans risque :
#: il voyage à côté de `require_parameters`, qui ne route que vers un hébergeur
#: honorant tout ce qu'on demande. Un modèle sans raisonnement du tout peut
#: donc n'avoir plus personne à qui être routé, et rendre un 404 — dont le
#: message nomme cette piste. Le videz-le alors : c'est un réglage, pas une
#: fatalité.
EFFORT_RAISONNEMENT = "low"

#: Jetons ajoutés au plafond de chaque appel, pour que le raisonnement ne
#: mange pas la réponse.
#:
#: Deux appels réels ont écrit cette constante, et aucune lecture de
#: documentation ne l'aurait donnée. Le premier est revenu en HTTP 200 avec
#: `content: null` et `finish_reason: length` : le modèle par défaut avait
#: dépensé les 300 jetons de la reconnaissance à raisonner, sans écrire un
#: caractère, et facturé 0,0002 $ pour rien. Le second a demandé
#: `reasoning: {enabled: false}` et s'est fait renvoyer un 400 sans appel :
#:
#:     Reasoning is mandatory for this endpoint and cannot be disabled.
#:
#: Ce modèle-là raisonne, donc, et il n'y a pas à discuter. Restait à lui en
#: laisser la place : les plafonds de `schemas.py` disent la taille d'une
#: **réponse**, et c'est la bonne unité — un JSON de fiche fait ce qu'il fait,
#: quel que soit le modèle. Le monologue, lui, s'ajoute.
#:
#: Quatre mille, et non un facteur : le raisonnement d'une tâche bornée ne
#: croît pas avec la longueur de la réponse attendue. Reconnaître une page en
#: demande autant que remplir une fiche, et multiplier les plafonds aurait
#: donné seize mille jetons de marge à l'extraction d'un programme pour rien.
#:
#: **Mesuré depuis** : une reconnaissance réelle en a consommé 1 312. La marge
#: tient, avec un facteur trois devant elle — assez pour une page que le modèle
#: trouverait plus embarrassante, et c'est bien la marge qu'on veut ici : une
#: reconnaissance qui échoue rend la page « inconnue », donc traitée en agenda.
#:
#: Un plafond n'est pas une dépense : ce qui n'est pas produit n'est pas
#: facturé. Le vrai garde-fou reste `max_cost_usd`, qui compte ce qui l'a été.
MARGE_RAISONNEMENT = 4_000

#: Le modèle employé quand la configuration n'en nomme aucun qu'OpenRouter
#: comprenne — c'est-à-dire le cas normal : la console pré-remplit ses quatre
#: champs avec un nom du vocabulaire d'Anthropic, qui ne veut rien dire là-bas.
#:
#: Le suffixe `:floor` n'est pas un modèle, c'est une **consigne de routage** :
#: parmi les hébergeurs qui servent ce modèle, prendre le moins cher. Deux
#: choses à en savoir, et la seconde n'est pas anodine :
#:
#: * elle peut entrer en tension avec `require_parameters` ci-dessous. Si
#:   aucun hébergeur bon marché ne sait contraindre une sortie au schéma, il ne
#:   reste personne à qui router, et l'appel rend un 404 lisible plutôt qu'une
#:   fiche approximative — ce qui est le bon sens de l'erreur, mais c'est un
#:   404 qu'on n'aurait pas sans `:floor` ;
#: * **l'hébergeur n'est plus le même d'un appel à l'autre.** Quantisations,
#:   fenêtres et réglages diffèrent de l'un à l'autre. Pour la production c'est
#:   sans conséquence ; pour un run du banc, c'est une variable de plus dans
#:   une mesure qui existe pour n'en faire varier qu'une. Un run qui veut être
#:   reproductible nomme le modèle **sans** le suffixe.
MODELE_DEFAUT = "z-ai/glm-5.3-flash:floor"

#: Les noms de modèles que ce dépôt écrit — ceux d'Anthropic, tels que la
#: console et les YAML les portent. Ils n'existent pas chez OpenRouter.
#:
#: Ils **ne sont pas traduits**. Il y avait ici une table d'équivalences, qui
#: envoyait `claude-haiku-4-5` sur `anthropic/claude-haiku-4.5` ; elle est
#: partie avec ce qu'elle promettait sans pouvoir le tenir. D'abord parce que
#: ces slugs étaient écrits d'après une convention de nommage et non d'après le
#: catalogue, donc invérifiables d'ici. Ensuite et surtout parce qu'on ne passe
#: pas à OpenRouter pour continuer à payer Claude par un intermédiaire : on y
#: passe pour changer de modèle. Un de ces noms vaut donc « je n'ai rien
#: choisi » et retombe sur `MODELE_DEFAUT`.
#:
#: Pour employer un modèle précis — Claude compris —, il s'écrit à la façon
#: d'OpenRouter : `anthropic/claude-haiku-4.5`.
NOMS_DU_PIPELINE = frozenset(PRICES)


def modele_openrouter(nom: str, defaut: str = MODELE_DEFAUT) -> str:
    """Le nom tel qu'OpenRouter l'attend. Lève si celui-ci n'en est pas un.

    Trois cas, et le troisième est celui qui compte :

    * un nom qui porte un `/` est pris tel quel — c'est un slug, et c'est au
      catalogue d'OpenRouter de dire s'il existe, pas à nous ;
    * un nom de modèle du pipeline vaut « je n'ai rien choisi » : c'est ce que
      la console écrit par défaut, et on retombe sur `defaut` ;
    * tout le reste est refusé, au chargement de la configuration, donc avant
      la moindre dépense. Sans ce refus, une faute de frappe — `gemini-2.5` au
      lieu de `google/gemini-2.5-flash` — passerait pour « rien choisi » et le
      run tournerait tout entier sur un modèle qu'on n'a pas demandé.
    """
    nom = (nom or "").strip()
    if "/" in nom:
        return nom
    if nom in NOMS_DU_PIPELINE:
        return defaut
    raise ProviderError(
        f"modèle « {nom or '(vide)'} » inconnu d'OpenRouter : un modèle s'y nomme "
        "« éditeur/modèle » (par exemple « z-ai/glm-5.3-flash », "
        "« google/gemini-2.5-flash », « anthropic/claude-haiku-4.5 »). "
        f"Un modèle du pipeline y vaut « au choix du scraper » : {defaut}"
    )


class OpenRouterProvider:
    """Un routeur de modèles pour les quatre appels du modèle. Pas pour la recherche."""

    name = "openrouter"

    def __init__(self, api_key: str | None = None, session: Any = None):
        if not api_key:
            # Comme pour Serper : une configuration qui nomme ce fournisseur
            # et n'a pas de clé doit échouer tout de suite, pas au premier run.
            raise ProviderError(
                "OPENROUTER_API_KEY est requis pour le fournisseur « openrouter » "
                "(voir .env.example)"
            )
        self.usage = Usage()
        self._key = api_key
        self._session = session or requests.Session()
        #: Appels déjà facturés à l'estime : on le dit une fois par modèle.
        self._sans_tarif: set[str] = set()

    # ------------------------------------------------------------- 1. chercher

    def queries(self, config: Config, log: RunLog) -> list[str]:
        """Formule les requêtes. Le plus petit appel du pipeline."""
        data = self._ask(
            model=config.search_model,
            prompt=config.render_queries(),
            schema=QUERIES_SCHEMA,
            nom_schema="requetes",
            max_tokens=QUERIES_MAX_TOKENS,
            op="queries",
            log=log,
        )
        found = [str(q).strip() for q in (data.get("queries") or []) if str(q).strip()]
        return found[: config.max_searches]

    def search(self, queries: list[str], config: Config, log: RunLog) -> list[FoundPage]:
        """Personne ici ne sait chercher, et c'est dit plutôt que deviné.

        En production ce fournisseur est enveloppé dans `SerperProvider`, qui
        intercepte cet appel : celui-ci ne se déclenche donc que si quelqu'un
        emploie `OpenRouterProvider` tout seul. Rendre une liste vide lui
        ferait croire à une recherche infructueuse et lui coûterait un run
        entier à comprendre pourquoi.
        """
        raise ProviderError(
            "le fournisseur « openrouter » ne cherche pas : la découverte revient "
            "au moteur (Serper), et OpenRouter aux quatre appels du modèle"
        )

    # ------------------------------------------------------------ 2. reconnaître

    def classify(self, digest: str, config: Config, log: RunLog) -> tuple[str, str]:
        """Le plus petit des quatre appels : un condensé, une étiquette."""
        data = self._ask(
            model=config.classify_model,
            prompt=config.render_classify(digest),
            schema=CLASSIFY_SCHEMA,
            nom_schema="nature",
            max_tokens=CLASSIFY_MAX_TOKENS,
            op="classify",
            log=log,
        )
        nature = str(data.get("nature", "")).strip().lower()
        if nature not in ("agenda", "sortie", "programme", "inconnu"):
            # Le schéma l'interdit, mais tous les modèles ne l'honorent pas
            # aussi strictement : on ne devine pas à leur place.
            return "inconnu", f"réponse inattendue ({nature or 'vide'})"
        return nature, str(data.get("pourquoi", "")).strip()

    # --------------------------------------------------------------- 3. choisir

    def select(
        self, page: str, links: list[Link], config: Config, log: RunLog
    ) -> list[Link]:
        """Des numéros de ligne, jamais des URL — la règle ne dépend pas du modèle."""
        if not links:
            return []
        listing = "\n".join(
            f"{i}. {link.text} | {link.context}" for i, link in enumerate(links, start=1)
        )
        for i, link in enumerate(links, start=1):
            log.event(
                "link", index=i, url=link.url, text=link.text,
                context=link.context, agenda=page,
            )
        data = self._ask(
            model=config.select_model,
            prompt=config.render_select(page, listing),
            schema=SELECT_SCHEMA,
            nom_schema="tri",
            max_tokens=SELECT_MAX_TOKENS,
            op="select",
            log=log,
        )
        kept: list[tuple[Link, str]] = []
        for raw in data.get("kept") or []:
            number = raw.get("index") if isinstance(raw, dict) else raw
            why = str(raw.get("why", "")).strip() if isinstance(raw, dict) else ""
            if isinstance(number, int) and 1 <= number <= len(links):
                kept.append((links[number - 1], why))
        kept = kept[: config.max_links_per_agenda]

        dropped = str(data.get("dropped_reason") or "").strip()
        log.event(
            "selected", url=page, kept=len(kept), among=len(links), dropped_reason=dropped,
        )
        for link, why in kept:
            log.event("link_kept", url=link.url, text=link.text, why=why, agenda=page)
        return [link for link, _ in kept]

    # -------------------------------------------------------------- 4. extraire

    def extract(
        self,
        url: str,
        content: str,
        config: Config,
        categories: list[str],
        log: RunLog,
        *,
        multiple: bool = False,
        hints: dict | None = None,
    ) -> list[ExtractedEvent]:
        """Lit une page. Une fiche, ou plusieurs si c'est un programme.

        `hints` est ignoré, pour la raison qui le fait ignorer chez Anthropic :
        ce que la page déclare d'elle-même n'entre pas dans le prompt de
        production, sans quoi son empreinte changerait et les runs du banc ne
        se compareraient plus. Les deux fournisseurs de modèle posent donc
        exactement la même question, ce qui est la condition pour que le banc
        mesure autre chose que nous.
        """
        if not multiple:
            data = self._ask(
                model=config.extraction_model,
                prompt=config.render_extraction(url, content, categories),
                schema=EXTRACTION_SCHEMA,
                nom_schema="fiche",
                max_tokens=EXTRACTION_MAX_TOKENS,
                op="extraction",
                log=log,
            )
            return [ExtractedEvent.from_json(data)]

        data = self._ask(
            model=config.extraction_model,
            prompt=config.render_extraction_multi(url, content, categories),
            schema=EXTRACTION_MULTI_SCHEMA,
            nom_schema="programme",
            max_tokens=EXTRACTION_MULTI_MAX_TOKENS,
            op="extraction",
            log=log,
        )
        return events_from_multi(data, config.max_events)

    # ---------------------------------------------------------------- l'appel

    def _ask(
        self,
        *,
        model: str,
        prompt: str,
        schema: dict[str, Any],
        nom_schema: str,
        max_tokens: int,
        op: str,
        log: RunLog,
    ) -> dict[str, Any]:
        """Un aller-retour, son JSON, sa facture. Aucun outil, aucune boucle."""
        modele = modele_openrouter(model)
        log.event("prompt", op=op, chars=len(prompt), model=modele, prompt=prompt)
        payload = {
            "model": modele,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            # Le plafond de l'appel, **plus** de quoi raisonner : voir
            # `MARGE_RAISONNEMENT`. Les plafonds de `schemas.py` disent la
            # taille d'une réponse, pas celle d'un monologue intérieur.
            "max_tokens": max_tokens + MARGE_RAISONNEMENT,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": nom_schema, "strict": True, "schema": schema},
            },
            # Ne router que vers un hébergeur qui sait contraindre la sortie.
            "provider": {"require_parameters": True},
            # Et qu'il dise ce que ça a coûté.
            "usage": {"include": True},
        }
        if EFFORT_RAISONNEMENT:
            # Le couper est refusé par le modèle par défaut ; le régler ne
            # l'est pas. C'est la seule prise qu'on ait sur la seule chose qui
            # coûte cher dans ces quatre appels.
            payload["reasoning"] = {"effort": EFFORT_RAISONNEMENT}
        data = self._post(payload, op=op, modele=modele, log=log)
        self._facturer(data, op=op, modele=modele, log=log)
        return loads_json(_texte(data), ProviderError)

    def _post(
        self, payload: dict[str, Any], *, op: str, modele: str, log: RunLog
    ) -> dict[str, Any]:
        """Poste l'appel et rend la réponse décodée. Lève `ProviderError` sinon.

        Ne réessaie que ce qui est passager, et le dit au journal : une panne
        rattrapée en silence est une panne qu'on ne verra jamais venir.
        """
        attente = ATTENTE
        for tentative in range(1, TENTATIVES + 1):
            try:
                response = self._session.post(
                    ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {self._key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": REFERER,
                        "X-Title": TITLE,
                    },
                    json=payload,
                    timeout=TIMEOUT,
                )
            except requests.RequestException as err:
                raise ProviderError(
                    f"OpenRouter injoignable ({err.__class__.__name__})"
                ) from err

            code = response.status_code
            if code in CODES_PASSAGERS and tentative < TENTATIVES:
                log.warn(
                    op,
                    f"OpenRouter répond {code} — nouvelle tentative dans {attente:.0f} s "
                    f"({tentative}/{TENTATIVES - 1})",
                    model=modele,
                )
                time.sleep(attente)
                attente *= 2
                continue
            if code >= 400:
                raise ProviderError(_message_erreur(code, response))

            try:
                data = response.json()
            except ValueError as err:
                raise ProviderError("réponse d'OpenRouter illisible") from err
            # Le service rend parfois 200 en portant l'échec dans le corps :
            # modération de l'hébergeur, modèle indisponible au dernier moment.
            erreur = data.get("error")
            if isinstance(erreur, dict):
                raise ProviderError(
                    f"OpenRouter en erreur : {erreur.get('message') or erreur}"
                )
            return data

        # Inatteignable : la dernière tentative lève ou rend.
        raise ProviderError(f"{op} : OpenRouter n'a pas répondu")  # pragma: no cover

    def _facturer(
        self, data: dict[str, Any], *, op: str, modele: str, log: RunLog
    ) -> None:
        """Impute l'appel au compteur du run, au coût que le service annonce."""
        step = Usage()
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        step.input_tokens = _entier(usage.get("prompt_tokens"))
        step.output_tokens = _entier(usage.get("completion_tokens"))

        cost = usage.get("cost")
        if isinstance(cost, (int, float)) and cost >= 0:
            step.cost_usd = float(cost)
        else:
            step.cost_usd = (
                step.input_tokens * TARIF_INCONNU[0]
                + step.output_tokens * TARIF_INCONNU[1]
            ) / 1_000_000
            self._prevenir(modele, op, log)

        self.usage.add(step)
        log.event("usage", op=op, model=modele, **step.as_dict())

    def _prevenir(self, modele: str, op: str, log: RunLog) -> None:
        """Dit, une fois par modèle, que son coût est une estimation haute."""
        if modele in self._sans_tarif:
            return
        self._sans_tarif.add(modele)
        entree, sortie = TARIF_INCONNU
        log.warn(
            op,
            f"OpenRouter n'a pas annoncé le coût de l'appel à « {modele} » : facturé "
            f"à l'estime ({entree} $ / {sortie} $ le million de jetons). Le coût "
            "affiché est majoré et le plafond du run peut tomber trop tôt.",
            model=modele,
        )


# ---------------------------------------------------------------------- outils


def _texte(data: dict[str, Any]) -> str:
    """Le contenu du premier choix, ou de quoi comprendre pourquoi il manque."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("réponse d'OpenRouter sans réponse (aucun choix)")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    fin = str(choice.get("finish_reason") or "")
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    contenu = message.get("content")
    if isinstance(contenu, list):
        # Quelques modèles rendent le contenu en morceaux, à la façon
        # d'Anthropic, là où l'API d'OpenAI qu'imite OpenRouter donne une
        # chaîne. Recoller coûte une ligne ; ne pas le faire coûterait une
        # page perdue avec « réponse sans contenu texte » pour toute
        # explication.
        contenu = "".join(
            str(part.get("text", "")) for part in contenu if isinstance(part, dict)
        )
    if fin == "length":
        # Le JSON est coupé net : `loads_json` dirait « réponse illisible », ce
        # qui enverrait chercher du côté du modèle une faute qui est la nôtre.
        #
        # Reste à dire **laquelle**. Un modèle qui raisonne dépense son budget
        # de sortie avant d'écrire un seul caractère de réponse : le plafond
        # est atteint, `content` est vide, et rien dans « réponse tronquée » ne
        # mettait sur la piste. C'est le premier appel réel au service qui l'a
        # appris, et il a coûté un job d'intégration continue à comprendre.
        if str(message.get("reasoning") or "").strip():
            raise ProviderError(
                "le modèle a dépensé son budget de sortie en raisonnement sans "
                f"écrire de réponse, malgré les {MARGE_RAISONNEMENT} jetons de "
                "marge prévus pour ça. Relevez MARGE_RAISONNEMENT, ou employez "
                "un modèle qui raisonne moins — celui-ci se paie deux fois par "
                "page, et ces jetons-là sont les plus chers"
            )
        raise ProviderError(
            "réponse tronquée par le plafond de jetons — la fiche est incomplète"
        )
    if not isinstance(contenu, str) or not contenu.strip():
        raise ProviderError(f"réponse d'OpenRouter sans contenu texte ({fin or 'sans motif'})")
    return contenu


def _message_erreur(code: int, response: Any) -> str:
    """Un message qui dise quoi faire, plutôt qu'un numéro.

    Le détail du service est repris quand il y en a un : c'est lui qui nomme
    le modèle fautif ou l'hébergeur tombé.
    """
    detail = ""
    try:
        corps = response.json()
        erreur = corps.get("error") if isinstance(corps, dict) else None
        if isinstance(erreur, dict):
            detail = str(erreur.get("message") or "")
        elif isinstance(corps, dict):
            detail = str(corps.get("message") or "")
    except ValueError:
        detail = ""
    detail = f" : {detail}" if detail else ""

    if code == 401:
        return f"clé OpenRouter refusée (401){detail}"
    if code == 402:
        return f"crédits OpenRouter épuisés (402){detail}"
    if code == 403:
        return f"appel refusé par OpenRouter (403){detail}"
    if code == 404:
        return (
            "modèle inconnu, ou aucun hébergeur ne sait honorer ce qu'on demande "
            f"(404){detail}. Deux exigences peuvent ne trouver personne : la "
            "sortie contrainte par un schéma, et l'effort de raisonnement — "
            "videz EFFORT_RAISONNEMENT si ce modèle ne raisonne pas"
        )
    if code == 429:
        return f"quota OpenRouter dépassé (429){detail}"
    return f"OpenRouter en erreur (HTTP {code}){detail}"


def _entier(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
