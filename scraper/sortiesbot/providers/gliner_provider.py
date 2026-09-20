"""L'étage 6 sans appel payant : un étiqueteur de spans, en local.

GLiNER est un **encodeur**, pas un générateur. Il fait une passe avant sur la
page et rend des morceaux de texte ; il ne produit pas un jeton après l'autre.
C'est ce qui décide tout le reste :

* une page se lit en une fraction de seconde sur un processeur ordinaire, là
  où un décodeur de 1,7 Md refait une passe par jeton écrit — cinq cents
  jetons de fiche, cinq cents passes ;
* il ne peut **pas** inventer une valeur : ce qu'il rend est, par
  construction, une sous-chaîne de la page ;
* il est *zero-shot* : les champs qu'on lui demande sont des phrases en
  français passées à l'appel (`spans.LABELS`), pas des classes gelées dans
  les poids. Changer de champ ne demande pas de réentraîner, seulement de
  réécrire une phrase.

## Ce que ce fournisseur remplace, et ce qu'il ne remplace pas

**Un seul des cinq appels du `Protocol` : l'extraction.** Les quatre autres —
formuler, chercher, reconnaître, trier — restent au modèle qu'on lui passe,
exactement comme `SerperProvider` ne remplace que la recherche. Un étiqueteur
ne sait pas formuler une requête web.

Et même à l'extraction, il ne rend pas la fiche entière : `description`,
`setting`, `category` restent vides, parce que ce ne sont pas des morceaux de
page. Le détail et la raison de ne pas les combler au jugé sont dans
`spans.py`.

## Pourquoi la bibliothèque est optionnelle

`gliner` tire `torch`, soit environ deux gigaoctets. L'imposer à tout le monde
— à l'intégration continue, au VPS qui ne fait tourner que le worker — pour
une expérience qui ne concerne qu'un banc serait un mauvais marché. La
dépendance est donc un extra (`pip install -e ".[gliner]"`), l'import est
paresseux, et le message d'erreur dit quoi installer.

C'est aussi ce qui rend ce fournisseur testable : `tagger` s'injecte, et les
tests passent un objet qui rend des spans écrits à la main. Aucun test
n'installe torch, aucun ne touche au réseau.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import date
from typing import Any, Protocol, runtime_checkable

from ..config import Config
from ..harvest import Link
from ..journal import RunLog
from ..models import ExtractedEvent, FoundPage, Usage
from ..spans import (
    LABELS,
    SEUIL_DEFAUT,
    SEUIL_PLANCHER,
    Span,
    cadre_lu,
    to_event,
    unfilled_fields,
)
from .base import Provider, ProviderError

#: Le point de départ raisonnable : multilingue, français compris, Apache 2.0,
#: et taillé pour tourner sur processeur. Se change par `glinerModel` dans la
#: configuration, ou par `SPP_GLINER_MODEL` pour un run de banc.
MODELE_DEFAUT = "urchade/gliner_multi-v2.1"

#: Jetons que l'encodeur regarde d'un coup, quand le modèle ne le dit pas.
#:
#: C'est **384** chez GLiNER (`gliner/config.py`, `max_len`), pas 512 ni 4 000 :
#: la fenêtre d'un encodeur, pas celle d'un LLM. Au-delà, le modèle ne tronque
#: pas bruyamment — il regarde le début et ignore le reste en silence.
FENETRE_JETONS_DEFAUT = 384

#: Ce que les libellés prennent sur cette fenêtre, en jetons.
#:
#: Le point qui n'a rien d'évident : dans un GLiNER mono-encodeur, **les
#: libellés et le texte partagent la même séquence**. Onze libellés français
#: pèsent quelques dizaines de jetons, et ce sont autant de jetons que la page
#: n'aura pas. C'est aussi pourquoi des libellés courts valent mieux que des
#: phrases : ils coûtent moins cher *et* ressemblent davantage à ce sur quoi le
#: modèle a été entraîné.
JETONS_RESERVES = 110

#: Caractères par jeton, en français, avec un vocabulaire multilingue.
#:
#: Volontairement **prudent** : trois plutôt que quatre. Sous-estimer coupe un
#: tronçon un peu tôt, ce qui ne coûte qu'une passe de plus ; surestimer laisse
#: le modèle tronquer en silence, ce qui coûte la moitié de la page — et c'est
#: exactement la faute que ce module a commise, avec une fenêtre de 6 000
#: caractères là où le modèle en lisait environ 1 200.
CARACTERES_PAR_JETON = 3

#: Part d'un tronçon que le suivant reprend, pour qu'une valeur à cheval sur la
#: coupe soit entière dans au moins l'un des deux.
PART_RECOUVREMENT = 0.15

#: Tronçons traités en un seul passage groupé.
#:
#: Grouper fait gagner du temps, et **coûte de la mémoire** : les activations
#: d'un encodeur croissent avec la taille du lot. Tant que la fenêtre était
#: (faussement) large, une page tenait en deux tronçons et le lot était de deux.
#: La fenêtre corrigée en produit une dizaine, et les passer d'un bloc a
#: multiplié par cinq le pic d'un seul appel — sur une machine de quatre
#: gigaoctets qui fait déjà tourner une base et un serveur Node, et **sans
#: swap**, c'est la différence entre un run qui finit et un processus que le
#: noyau tue.
#:
#: Quatre : assez pour que le groupage serve encore, assez peu pour que le pic
#: ne dépende plus de la longueur de la page.
LOT_MAX = 4

#: Fils de calcul laissés à torch. `0` : ce qu'il décide lui-même.
#:
#: Par défaut il en prend autant qu'il y a de cœurs — quatre ici, c'est-à-dire
#: tous, y compris ceux dont MySQL et l'API ont besoin pour répondre pendant que
#: le banc tourne. Le worker n'est pas pressé : une passe deux fois plus lente
#: sur un run qui dure de toute façon des minutes ne coûte rien, quand un site
#: qui ne répond plus se voit tout de suite.
FILS_TORCH = 2


def _rendre_la_memoire() -> None:
    """Rend au système les pages que l'allocateur garde pour lui.

    Le symptôme, mesuré : le worker a été tué par le noyau à la **44ᵉ** entrée
    sur 141, à 2,6 Go de RSS — après en avoir tenu 43. Un pic par appel aurait
    frappé tôt, sur la première page un peu longue ; tenir quarante-trois
    entrées puis mourir, c'est une **croissance**, pas un pic.

    Rien ne s'accumule dans ce code — les spans, les tronçons et les réponses
    sont tous par appel. Ce qui grossit est l'allocateur de la glibc : des
    milliers d'allocations de tailles toutes différentes (un tronçon fait la
    longueur que la coupe lui a donnée), réparties sur plusieurs arènes, une
    par fil de calcul. La mémoire est bien libérée côté Python ; elle reste
    simplement réservée au processus, et le RSS monte en cliquet.

    `malloc_trim(0)` est ce qui la rend. Une fois par page, coût négligeable
    devant une passe d'encodeur. L'autre moitié du remède ne peut pas s'écrire
    ici : `MALLOC_ARENA_MAX` doit être posé **avant** le démarrage du
    processus, et vit donc dans l'unité systemd.
    """
    try:
        import ctypes
        import ctypes.util

        nom = ctypes.util.find_library("c")
        if not nom:
            return
        libc = ctypes.CDLL(nom)
        if hasattr(libc, "malloc_trim"):
            libc.malloc_trim(0)
    except Exception:  # noqa: BLE001 — une hygiène qui échoue ne casse rien
        pass


def fenetre_caracteres(tagger: Any = None, labels: list[str] | None = None) -> tuple[int, int]:
    """Combien de caractères par tronçon, et combien les tronçons partagent.

    Dérivé du modèle plutôt que codé en dur : `max_len` change d'un point de
    contrôle à l'autre, et une constante écrite ici serait fausse au premier
    modèle essayé. Ce que le modèle ne dit pas, on le prend prudemment.
    """
    jetons = FENETRE_JETONS_DEFAUT
    config = getattr(tagger, "config", None)
    declare = getattr(config, "max_len", None)
    if isinstance(declare, int) and declare > 0:
        jetons = declare
    # Les libellés mangent la fenêtre : on estime leur part sur les vrais
    # libellés quand on les a, plutôt que sur une moyenne.
    reserve = JETONS_RESERVES
    if labels:
        reserve = min(jetons // 2, sum(len(lb) // 3 + 2 for lb in labels) + 10)
    budget = max(200, (jetons - reserve) * CARACTERES_PAR_JETON)
    return budget, max(60, int(budget * PART_RECOUVREMENT))


@runtime_checkable
class Tagger(Protocol):
    """Ce qu'on attend d'un étiqueteur : des spans, pour des libellés donnés.

    C'est exactement la signature de `GLiNER.predict_entities`, réduite à ce
    dont on se sert. La déclarer ici plutôt que d'importer GLiNER permet aux
    tests — et à un futur second étiqueteur — de s'y conformer sans la
    bibliothèque.
    """

    def predict_entities(
        self, text: str, labels: list[str], threshold: float = ...
    ) -> list[dict[str, Any]]:
        ...


def charger(nom: str = MODELE_DEFAUT) -> Tagger:
    """Le modèle, téléchargé au premier appel puis mis en cache par la bibliothèque.

    Import à l'intérieur de la fonction : le module doit s'importer sans
    `gliner` installé, sinon le worker refuserait de démarrer chez tous ceux
    qui ne font pas l'expérience.
    """
    try:
        from gliner import GLiNER  # type: ignore[import-not-found]
    except ImportError as err:  # pragma: no cover — dépend de l'installation
        raise ProviderError(
            "le fournisseur « gliner » réclame la bibliothèque du même nom : "
            'pip install -e ".[gliner]" (elle tire torch, ~2 Go)'
        ) from err
    if FILS_TORCH > 0:
        try:
            import torch

            torch.set_num_threads(FILS_TORCH)
        except Exception:  # noqa: BLE001 — un réglage de confort ne casse rien
            pass
    try:
        # `GLiNER` est un aiguilleur : `from_pretrained` rend une sous-classe
        # concrète (`UniEncoderSpanGLiNER` et consorts) selon ce que la
        # configuration du dépôt annonce. C'est elle qui porte
        # `predict_entities` — d'où le `Protocol` plutôt qu'un type importé.
        return GLiNER.from_pretrained(nom)
    except Exception as err:
        # Le premier lancement télécharge les poids. Sans réseau, avec un
        # dépôt mal orthographié ou un pare-feu devant huggingface.co, la
        # bibliothèque remonte une exception de sa couche HTTP — et le worker
        # se prenait une trace au lieu d'un run proprement en échec. L'étage 6
        # sait déjà traiter un `ProviderError` : il le rapporte et continue.
        raise ProviderError(
            f"modèle « {nom} » indisponible ({err.__class__.__name__} : {err}). "
            "Premier lancement : les poids se téléchargent depuis huggingface.co."
        ) from err


def _decouper(text: str, budget: int, recouvrement: int) -> list[tuple[int, str]]:
    """Le texte en tronçons qui tiennent dans la fenêtre, avec leur décalage.

    Le décalage voyage avec le tronçon : sans lui, les positions rendues par
    l'étiqueteur seraient celles du tronçon et non de la page, et un span ne
    se relierait plus à ce qu'il désigne.

    La coupe cherche une espace pour ne pas trancher un mot en deux — un mot
    coupé est un jeton inconnu, et l'entité qui le contenait est perdue.
    """
    if len(text) <= budget:
        return [(0, text)]
    morceaux: list[tuple[int, str]] = []
    depart = 0
    pas = max(1, budget - recouvrement)
    while depart < len(text):
        fin = min(depart + budget, len(text))
        if fin < len(text):
            espace = text.rfind(" ", depart + pas, fin)
            if espace > depart:
                fin = espace
        morceaux.append((depart, text[depart:fin]))
        if fin >= len(text):
            break
        depart += max(1, (fin - depart) - recouvrement)
    return morceaux


class GlinerProvider:
    """Un étiqueteur pour l'extraction, un modèle pour les quatre autres appels."""

    name = "gliner"

    def __init__(
        self,
        model: Provider | None = None,
        *,
        tagger: Tagger | None = None,
        gliner_model: str = MODELE_DEFAUT,
        seuil: float = SEUIL_DEFAUT,
        today: date | None = None,
    ):
        self._model = model
        self._tagger = tagger
        self._nom = gliner_model
        self._seuil = seuil
        # On interroge l'étiqueteur au **plancher** des seuils par champ, et on
        # trie ensuite : demander au seuil par défaut jetterait, côté modèle,
        # les spans qu'un champ plus tolérant aurait gardés.
        self._plancher = min(seuil, SEUIL_PLANCHER)
        self._today = today
        # Le sien, et il reste à zéro : c'est le fait saillant de ce
        # fournisseur. Quand un modèle est branché derrière pour les quatre
        # autres appels, c'est *son* compteur qu'on expose, sans quoi le
        # plafond de budget ne surveillerait plus rien.
        self._usage = Usage()

    @property
    def usage(self) -> Usage:
        return self._model.usage if self._model is not None else self._usage

    def _charger(self) -> Tagger:
        if self._tagger is None:
            self._tagger = charger(self._nom)
        return self._tagger

    # ------------------------------------------------------------ l'extraction

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
        """Les spans de cette page, assemblés en une fiche.

        `hints` porte ce que la page déclare d'elle-même — son `h1`, son
        `schema.org/Event`. Ces valeurs **l'emportent** sur les spans : elles
        sont exactes, écrites par l'organisateur, et le modèle n'a alors plus
        à deviner ce qu'on sait déjà.

        `multiple` est **refusé**, et bruyamment : un étiqueteur rendrait les
        vingt titres d'un programme de festival sans savoir qu'ils appartiennent
        à vingt sorties. Découper une page en entrées est une tâche de
        segmentation que ce modèle ne fait pas, et rendre une fiche unique
        bricolée à partir de vingt sorties mélangées serait pire qu'un échec :
        ce serait un échec silencieux.
        """
        if multiple:
            raise ProviderError(
                "« gliner » ne sait pas relever un programme (plusieurs sorties "
                "sur une page) : un étiqueteur ne segmente pas. Mode « site » à "
                "laisser au fournisseur « anthropic »."
            )

        tagger = self._charger()
        libelles = list(LABELS)
        depart = time.monotonic()
        budget, recouvrement = fenetre_caracteres(tagger, libelles)
        morceaux = _decouper(content, budget, recouvrement)
        try:
            rendus = self._etiqueter(tagger, [m for _, m in morceaux], libelles)
        except ProviderError:
            raise
        except Exception as err:
            raise ProviderError(f"étiquetage impossible ({err.__class__.__name__} : {err})") from err

        # Les tronçons se recouvrent : une valeur posée dans la zone commune
        # est vue deux fois. Ça ne change pas la fiche — tout se dédoublonne
        # plus loin — mais ça gonflerait le compte porté au journal, et c'est
        # lui qu'on lira pour diagnostiquer un étiquetage avare ou bavard.
        vus: set[tuple[str, int, int]] = set()
        spans: list[Span] = []
        for (decalage, _), bruts in zip(morceaux, rendus):
            for brut in bruts:
                span = Span(
                    label=str(brut.get("label", "")),
                    text=str(brut.get("text", "")),
                    # Le décalage ramène la position à la page : sans lui, un
                    # span du second tronçon pointerait le début du texte, et
                    # ne désignerait plus ce qu'il a lu.
                    start=int(brut.get("start", 0)) + decalage,
                    end=int(brut.get("end", 0)) + decalage,
                    score=float(brut.get("score", 1.0)),
                )
                cle = (span.label, span.start, span.end)
                if cle not in vus:
                    vus.add(cle)
                    spans.append(span)

        # Le texte part avec les spans : sans lui, les positions ne désignent
        # rien. C'est ce qui permet de lire « relâche le » devant un lundi, ou
        # « tarif enfant » devant un prix — le span, lui, ne porte que la
        # valeur.
        event = to_event(
            spans, today=self._today, seuil=self._seuil, hints=hints, text=content
        )

        # Puis le cadre, quand la page l'écrit — sans modèle, et c'est mesuré :
        # les deux passes de classification zero-shot qui étaient ici rendaient
        # 0 juste sur 16 pour la catégorie, et pour le cadre dix justes que ce
        # simple appariement retrouve. Le détail est dans `spans.py`.
        #
        # `categories` reste au contrat du fournisseur sans être lu : la
        # catégorie n'est pas sur la page, elle s'infère, et un surligneur de
        # spans ne l'atteindra pas. `unfilled_fields` l'annonce au banc.
        event = replace(event, setting=cadre_lu(content))
        # Une fois la page finie, et pas au milieu : à ce point tout ce que
        # l'encodeur a alloué est libéré côté Python, et il n'y a plus qu'à le
        # rendre au système.
        _rendre_la_memoire()
        # Ce que le journal doit garder : le modèle, ce qu'il a coûté (rien),
        # combien de spans il a posés, et **les champs qu'il ne remplit pas**.
        # Sans cette dernière ligne, un `MANQUE` sur `setting` se lirait comme
        # une faute du modèle plutôt que comme une limite annoncée de la brique.
        log.event(
            "gliner",
            op="extraction",
            url=url,
            model=self._nom,
            chars=len(content),
            spans=len(spans),
            retenus=sum(1 for s in spans if s.score >= self._seuil),
            # La fenêtre réellement appliquée, et en combien de passes. Sans
            # elle, une page à moitié lue ressemble à un modèle qui ne trouve
            # rien — c'est arrivé, avec une fenêtre cinq fois trop large.
            fenetre=budget,
            passes=len(morceaux),
            ms=int((time.monotonic() - depart) * 1000),
            non_rendus=",".join(unfilled_fields()),
            # Ce que la page déclarait d'elle-même, et que le modèle n'a donc
            # pas eu à deviner. Sans cette ligne, un titre juste se lirait
            # comme une réussite de l'étiquetage.
            declares=",".join(sorted(hints or {})) or "aucun",
        )
        return [event]

    def _etiqueter(
        self, tagger: Tagger, morceaux: list[str], libelles: list[str]
    ) -> list[list[dict[str, Any]]]:
        """Les spans de chaque tronçon, en un seul lot quand l'étiqueteur sait.

        `batch_predict_entities` fait une passe pour tous les tronçons au lieu
        d'une par tronçon : sur une page assez longue pour être découpée, c'est
        le gros de la différence, et un processeur de VPS n'a pas de marge à
        gaspiller. Elle reste **facultative** — le `Protocol` n'exige que
        `predict_entities`, pour qu'un second étiqueteur, ou un objet de test,
        n'ait pas à l'implémenter.
        """
        groupe = getattr(tagger, "batch_predict_entities", None)
        if not callable(groupe) or len(morceaux) < 2:
            return [
                tagger.predict_entities(m, libelles, threshold=self._plancher) for m in morceaux
            ]
        # Par paquets bornés, jamais d'un bloc : le pic mémoire d'un appel ne
        # doit pas dépendre de la longueur de la page.
        rendus: list[list[dict[str, Any]]] = []
        for debut in range(0, len(morceaux), LOT_MAX):
            lot = morceaux[debut : debut + LOT_MAX]
            if len(lot) == 1:
                rendus.append(
                    tagger.predict_entities(lot[0], libelles, threshold=self._plancher)
                )
            else:
                rendus.extend(groupe(lot, libelles, threshold=self._plancher))
        return rendus

    # ------------------------- les quatre autres appels restent à un modèle

    def _delegue(self) -> Provider:
        if self._model is None:
            raise ProviderError(
                "« gliner » ne remplace que l'extraction ; les quatre autres "
                "appels réclament un modèle. Ce fournisseur ne convient donc "
                "qu'à un run de banc d'extraction, pas à un run complet."
            )
        return self._model

    def queries(self, config: Config, log: RunLog) -> list[str]:
        return self._delegue().queries(config, log)

    def search(self, queries: list[str], config: Config, log: RunLog) -> list[FoundPage]:
        return self._delegue().search(queries, config, log)

    def classify(self, digest: str, config: Config, log: RunLog) -> tuple[str, str]:
        return self._delegue().classify(digest, config, log)

    def select(self, page: str, links: list[Link], config: Config, log: RunLog) -> list[Link]:
        return self._delegue().select(page, links, config, log)
