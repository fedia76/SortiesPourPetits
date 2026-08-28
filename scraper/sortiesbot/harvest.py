"""Téléchargement des pages et extraction de leurs liens.

C'est la brique qui remplace `web_fetch` à la découverte. Le raisonnement :
une page d'agenda, ce qu'on y cherche, ce sont ses liens d'événements. Les
faire lire au modèle coûte des milliers de jetons refacturés à chaque
itération de la boucle serveur ; les extraire ici ne coûte rien.

Le modèle intervient après, sur une liste compacte de liens — un jugement à
rendre, pas une page à lire.

Puisqu'on télécharge nous-mêmes, on assume ce qu'Anthropic assumait pour
nous : `robots.txt` est lu et respecté, on s'annonce, et on ne martèle pas
un serveur.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

#: On s'annonce : un administrateur de site doit pouvoir nous identifier et
#: nous écrire. C'est la moindre des politesses quand on lit ses pages.
USER_AGENT = (
    "SortiesPourPetitsBot/0.1 (+https://sortiespourpetits.fr ; "
    "recherche de sorties familiales)"
)

TIMEOUT = 20
#: Délai minimum entre deux requêtes vers le même hôte.
CRAWL_DELAY = 1.0
#: Au-delà, on arrête de lire : aucune page d'agenda utile ne pèse 5 Mo.
MAX_BYTES = 5 * 1024 * 1024

#: Chemins qui ne sont jamais un événement.
BORING_PATH = re.compile(
    r"/(mentions?-legales?|cgu|cgv|contact|faq|aide|newsletter|abonnement|"
    r"connexion|inscription|login|panier|compte|rss|sitemap|plan-du-site|"
    r"a-propos|qui-sommes-nous|publicite|cookies|confidentialite|recherche|"
    r"tag|tags|categorie|categories|page)(/|$|\.)",
    re.I,
)

#: Un lien dont le texte est plus court n'est pas un titre de sortie.
MIN_TEXT = 15
#: Contexte gardé autour du lien : c'est là que sont la date et le lieu.
CONTEXT_CHARS = 200
#: Un conteneur qui n'ajoute pas au moins ça au texte du lien n'apporte rien :
#: sur la plupart des agendas, le parent immédiat n'enveloppe que le titre.
CONTEXT_MIN_GAIN = 20
#: Au-delà, on a dépassé la carte de l'événement et attrapé toute la liste.
CONTEXT_MAX = 600


class FetchError(RuntimeError):
    """Page inaccessible, refusée par robots.txt, ou inexploitable."""


@dataclass(frozen=True)
class Link:
    """Un lien d'une page, avec le texte qui l'entoure.

    Le contexte fait toute la différence avec ce que rendait `web_fetch` :
    les agendas affichent la date et le lieu juste à côté du titre, donc le
    modèle peut trancher sans ouvrir la page.
    """

    text: str
    url: str
    context: str


class Fetcher:
    """Client HTTP poli : robots.txt respecté, un hôte à la fois."""

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_call: dict[str, float] = {}

    # ------------------------------------------------------------- politesse

    def _robots_for(self, url: str) -> RobotFileParser | None:
        root = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        if root not in self._robots:
            parser = RobotFileParser()
            parser.set_url(f"{root}/robots.txt")
            try:
                # `read()` utilise urllib et ignore notre session : on lit le
                # fichier nous-mêmes pour garder le même User-Agent.
                response = self.session.get(f"{root}/robots.txt", timeout=TIMEOUT)
                if response.status_code >= 400:
                    parser = None  # type: ignore[assignment]
                else:
                    parser.parse(response.text.splitlines())
            except requests.RequestException:
                # Pas de robots.txt lisible : on considère l'accès autorisé,
                # comme le veut la convention.
                parser = None  # type: ignore[assignment]
            self._robots[root] = parser
        return self._robots[root]

    def allowed(self, url: str) -> bool:
        parser = self._robots_for(url)
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    def _wait_turn(self, url: str) -> None:
        host = urlsplit(url).netloc
        since = time.monotonic() - self._last_call.get(host, 0.0)
        if since < CRAWL_DELAY:
            time.sleep(CRAWL_DELAY - since)
        self._last_call[host] = time.monotonic()

    # ---------------------------------------------------------- récupération

    def get_html(self, url: str) -> str:
        """Télécharge une page HTML, ou lève `FetchError`."""
        if not url.startswith(("http://", "https://")):
            raise FetchError("URL invalide")
        if not self.allowed(url):
            raise FetchError("interdit par robots.txt")

        self._wait_turn(url)
        try:
            response = self.session.get(url, timeout=TIMEOUT, stream=True)
            response.raise_for_status()
            kind = (response.headers.get("Content-Type") or "").split(";")[0].strip()
            if kind and not kind.startswith(("text/html", "application/xhtml")):
                raise FetchError(f"type de contenu inexploitable ({kind})")

            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(64 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise FetchError("page trop lourde")
                chunks.append(chunk)
        except requests.RequestException as err:
            raise FetchError(f"page inaccessible ({err.__class__.__name__})") from err

        encoding = response.encoding or "utf-8"
        return b"".join(chunks).decode(encoding, errors="replace")


# --------------------------------------------------------------- extraction


def _soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return soup


def _is_boring(url: str, text: str) -> bool:
    """Écarte le bruit évident : navigation, pieds de page, pages de service."""
    if len(text) < MIN_TEXT:
        return True
    parts = urlsplit(url)
    if not parts.path or parts.path == "/":
        return True
    return bool(BORING_PATH.search(parts.path))


def links_of(html: str, page_url: str, limit: int = 200) -> list[Link]:
    """Liens d'une page, débruités et accompagnés de leur contexte.

    On ne cherche pas à décider ici ce qui est un événement — juste à retirer
    ce qui n'en est certainement pas, pour que la liste soumise au modèle
    reste courte. Le jugement, c'est son travail.
    """
    soup = _soup(html)
    host = urlsplit(page_url).netloc
    found: dict[str, Link] = {}

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(page_url, href).split("#")[0]
        if urlsplit(url).netloc != host:
            # Un agenda renvoie vers ses propres fiches ; les liens sortants
            # sont des partenaires, des réseaux sociaux, de la publicité.
            continue

        text = " ".join(anchor.get_text(" ", strip=True).split())
        if _is_boring(url, text) or url in found:
            continue

        found[url] = Link(text=text[:150], url=url, context=_context_of(anchor, text))

        if len(found) >= limit:
            break

    return list(found.values())


def _context_of(anchor, text: str) -> str:
    """Texte qui entoure le lien — date, lieu, tarif.

    On remonte les ancêtres jusqu'à la carte de l'événement. Le parent
    immédiat n'enveloppe souvent que le titre, et s'y arrêter fait perdre
    précisément ce qui permet de trier sans ouvrir la page.
    """
    node = anchor
    for _ in range(4):
        node = node.parent
        if node is None or node.name in ("body", "html", "[document]"):
            break
        around = " ".join(node.get_text(" ", strip=True).split())
        if len(around) > CONTEXT_MAX:
            break  # on a dépassé la carte : la liste entière n'apprend rien
        if len(around) >= len(text) + CONTEXT_MIN_GAIN:
            return around[:CONTEXT_CHARS]
    return text[:CONTEXT_CHARS]


def page_text(html: str, limit: int = 8000) -> str:
    """Texte lisible d'une page, pour l'extraction d'une sortie."""
    soup = _soup(html)
    for tag in soup(["nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return text[:limit]
