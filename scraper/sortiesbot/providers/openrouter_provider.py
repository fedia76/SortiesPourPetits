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

Aucun outil, aucune itération : un aller-retour par appel, comme le reste du
pipeline. La mécanique HTTP n'est pas sortie dans un fichier à part — ce
qu'on a fait pour Serper le jour où l'attribution en a eu besoin : ici il n'y
a qu'un appelant, et un fichier de plus ne dirait rien de neuf.

## Ce que le service rend vraiment

**Pas encore confronté au service.** Ce qui est écrit ici vient de la
documentation d'OpenRouter, et les tests simulent cette forme-là : ils
verrouillent ce que le code en fait, pas qu'elle soit la bonne. Le job
`openrouter` de `.github/workflows/verifier.yml` lance
`tools/openrouter_shape.py`, qui interroge le vrai service et affiche ce qu'il
rend — c'est lui qui tranchera, et la ligne ci-dessus est à réécrire le jour
où il aura tourné.
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

#: Ce que la console écrit par défaut dans les quatre champs « modèle », et
#: qui ne veut rien dire pour OpenRouter : là-bas un modèle se nomme
#: « éditeur/modèle ».
#:
#: Traduire plutôt que refuser, parce que le cas normal est de basculer une
#: recherche existante sur OpenRouter pour voir : elle nomme alors les modèles
#: Claude du pipeline, et les router vers les mêmes modèles est la seule
#: lecture raisonnable de cette intention. C'est même la comparaison la plus
#: intéressante — même modèle, autre route.
#:
#: Table écrite d'après la convention de nommage d'OpenRouter, **non
#: confrontée au service** : `tools/openrouter_shape.py` la vérifie, une
#: entrée après l'autre, contre la liste publique des modèles.
EQUIVALENCES = {
    "claude-opus-5": "anthropic/claude-opus-5",
    "claude-opus-4-8": "anthropic/claude-opus-4.8",
    "claude-sonnet-5": "anthropic/claude-sonnet-5",
    "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
    "claude-haiku-4-5": "anthropic/claude-haiku-4.5",
}


def modele_openrouter(nom: str) -> str:
    """Le nom tel qu'OpenRouter l'attend. Lève si on ne sait pas le dire.

    Un nom qui porte déjà un `/` est pris tel quel : c'est un slug OpenRouter,
    et c'est à leur catalogue de dire s'il existe, pas à nous. Un nom sans `/`
    n'est un modèle que dans le vocabulaire d'Anthropic ; on le traduit s'il
    est connu, et on refuse sinon — au chargement de la configuration, donc
    avant la moindre dépense.
    """
    nom = (nom or "").strip()
    if "/" in nom:
        return nom
    if nom in EQUIVALENCES:
        return EQUIVALENCES[nom]
    raise ProviderError(
        f"modèle « {nom or '(vide)'} » inconnu d'OpenRouter : un modèle s'y nomme "
        "« éditeur/modèle » (par exemple « anthropic/claude-haiku-4.5 », "
        "« google/gemini-2.5-flash », « mistralai/mistral-small »)"
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
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": nom_schema, "strict": True, "schema": schema},
            },
            # Ne router que vers un hébergeur qui sait contraindre la sortie.
            "provider": {"require_parameters": True},
            # Et qu'il dise ce que ça a coûté.
            "usage": {"include": True},
        }
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
            f"modèle inconnu, ou aucun hébergeur ne sait contraindre sa sortie "
            f"(404){detail}"
        )
    if code == 429:
        return f"quota OpenRouter dépassé (429){detail}"
    return f"OpenRouter en erreur (HTTP {code}){detail}"


def _entier(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
