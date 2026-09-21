"""Interface commune aux fournisseurs.

Cinq appels, cinq tâches bornées. Aucun n'a le droit de dérouler une
procédure : formuler, chercher, reconnaître, choisir, remplir. C'est ce découpage qui
permet d'utiliser un modèle bon marché et de garder un coût prévisible — un
appel qui ne boucle pas ne peut pas refacturer son contexte trente fois.

Le quatrième, `classify`, est le plus petit de tous : quelques centaines de
jetons, un condensé de page en entrée, une étiquette en sortie. Il n'est appelé
que lorsque le HTML ne déclare rien, et il a le droit de répondre « je ne sais
pas ».
"""

from __future__ import annotations

from typing import Protocol

from ..config import PROVIDERS, Config
from ..harvest import Link
from ..journal import RunLog
from ..models import ExtractedEvent, FoundPage, Usage


class ProviderError(RuntimeError):
    """Échec côté fournisseur (appel refusé, réponse inexploitable…)."""


class Provider(Protocol):
    """Les trois moments où un modèle est nécessaire."""

    name: str
    usage: Usage

    def queries(self, config: Config, log: RunLog) -> list[str]:
        """Formule les requêtes web à lancer, à partir du thème et de la zone.

        Appelé seulement quand la configuration n'en fournit pas. Quelques
        dizaines de jetons : c'est le plus petit appel du lot.
        """
        ...

    def search(self, queries: list[str], config: Config, log: RunLog) -> list[FoundPage]:
        """Lance ces recherches et rend ce qu'elles ont remonté. Sans jugement.

        Ni tri, ni classement : des URL et leurs titres. C'est ce contrat-là
        qu'un moteur de recherche ordinaire sait honorer, et c'est pourquoi il
        pourra prendre la place de celui-ci sans que rien d'autre ne bouge.
        """
        ...

    def classify(self, digest: str, config: Config, log: RunLog) -> tuple[str, str]:
        """Dit ce qu'est une page à partir de son condensé, et pourquoi.

        Rend `(nature, motif)` où nature vaut « agenda », « sortie » ou
        « inconnu ». Aucune URL ne sort de cet appel : le modèle répond par une
        étiquette, et rien d'autre.
        """
        ...

    def select(
        self, page: str, links: list[Link], config: Config, log: RunLog
    ) -> list[Link]:
        """Parmi les liens d'un agenda, retient ceux qui mènent à une sortie.

        Le modèle répond par des numéros de ligne, jamais par des URL : il lui
        est ainsi matériellement impossible d'en inventer une.
        """
        ...

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
        """Remplit les fiches que porte le texte d'une page.

        Une page vaut une sortie, sauf en mode « site » où la page de
        programme d'un festival en porte plusieurs (`multiple`). Le retour est
        une liste dans les deux cas, pour que la suite du pipeline ne connaisse
        qu'un seul chemin.

        `hints` porte ce que la page **déclare d'elle-même** et que le texte
        n'emporte pas : son `h1`, et les champs d'un `schema.org/Event`. Ce
        n'est pas une aide au modèle, c'est du travail qu'on lui retire —
        libre à chaque fournisseur de s'en servir ou non. Celui d'Anthropic
        l'ignore : lui donner ces valeurs changerait le prompt de production,
        donc son empreinte, donc la comparabilité de tous les runs passés.
        """
        ...


def get_provider(
    config: Config,
    api_key: str | None = None,
    serper_key: str | None = None,
    openrouter_key: str | None = None,
) -> Provider:
    """Instancie le fournisseur nommé dans la configuration.

    Le champ `provider` nomme en réalité **deux** choix, le moteur et le
    modèle, et les quatre valeurs se lisent comme deux colonnes :

        anthropic   outil serveur Claude   +  Claude
        serper      Serper (Google)        +  Claude
        openrouter  Serper (Google)        +  OpenRouter
        gliner      (aucun moteur)         +  GLiNER à l'extraction, Claude ailleurs

    Un seul champ pour deux choix tient tant que le tableau est celui-là. Une
    cinquième ligne qui croiserait autrement — l'outil serveur avec un modèle
    d'OpenRouter, par exemple — réclamerait deux champs, en base, dans la
    console et ici. Personne n'en a eu besoin jusqu'ici.

    Le moteur n'est monté que si quelqu'un doit chercher. En mode « site »,
    aucune recherche n'est lancée — les adresses sont données, voir
    `stages/discovery.py` — et le moteur n'y sert à rien ; réclamer sa clé
    faisait échouer au démarrage un run qui ne s'en serait jamais servi. Seul
    le modèle compte alors, et le champ garde son sens : il dit lequel.
    """
    from .anthropic_provider import AnthropicProvider

    cherche = not config.targets_site

    if config.provider == "anthropic":
        return AnthropicProvider(api_key=api_key)
    if config.provider == "serper":
        from .serper_provider import SerperProvider

        modele = AnthropicProvider(api_key=api_key)
        return SerperProvider(modele, api_key=serper_key) if cherche else modele
    if config.provider == "openrouter":
        from .openrouter_provider import OpenRouterProvider
        from .serper_provider import SerperProvider

        # Même composition que « serper », l'autre modèle derrière : la
        # découverte revient au moteur, les quatre appels du modèle au routeur.
        # Les deux clés sont donc requises — celle d'OpenRouter toujours, celle
        # du moteur dès qu'il y a une recherche à lancer.
        routeur = OpenRouterProvider(api_key=openrouter_key)
        return SerperProvider(routeur, api_key=serper_key) if cherche else routeur
    if config.provider == "gliner":
        from .gliner_provider import GlinerProvider

        # Un modèle reste branché derrière pour les quatre autres appels, qu'un
        # étiqueteur ne sait pas rendre — mais seulement si une clé est là. Sans
        # clé, le fournisseur se construit quand même et ne saura faire que
        # l'extraction : c'est exactement ce dont un run de banc a besoin, et
        # réclamer une clé pour ne jamais s'en servir aurait fermé la porte au
        # seul cas d'usage de cette expérience.
        return GlinerProvider(
            AnthropicProvider(api_key=api_key) if api_key else None,
            gliner_model=config.gliner_model,
        )
    raise ProviderError(
        f"Fournisseur inconnu : « {config.provider} » "
        f"(connus : {', '.join(PROVIDERS)})"
    )
