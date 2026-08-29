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

Le HTML sert aussi à ce que le texte seul ne dit pas : les dates JSON-LD
(`json_ld_dates`) et l'illustration de la page (`main_image`). Le modèle ne
reçoit que du texte — il ne peut donc pas connaître l'URL d'une image, et
lui en demander une revenait à lui demander de l'inventer.
"""

from __future__ import annotations

import json
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


#: Types schema.org qui décrivent un événement. Les sites de spectacle
#: emploient rarement `Event` tout court.
_EVENT_TYPES = re.compile(r"event$", re.I)


def _ld_blocks(html: str) -> list[object]:
    """Contenu des balises `<script type="application/ld+json">`.

    C'est du JSON dans une balise `script`, donc il faut le lire AVANT le
    nettoyage de `_soup`, qui détruit les scripts.
    """
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[object] = []
    for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        try:
            blocks.append(json.loads(raw))
        except (ValueError, TypeError):
            # Un JSON-LD mal formé est fréquent et sans gravité : la page
            # reste lisible par le modèle, on perd seulement ce raccourci.
            continue
    return blocks


def _walk(node: object) -> list[dict]:
    """Tous les objets d'un JSON-LD, quelle que soit son imbrication.

    Les sites emboîtent librement : liste à la racine, `@graph`, `subEvent`
    pour les représentations d'un même spectacle.
    """
    found: list[dict] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_walk(item))
    elif isinstance(node, dict):
        found.append(node)
        for value in node.values():
            if isinstance(value, (list, dict)):
                found.extend(_walk(value))
    return found


def _is_event(node: dict) -> bool:
    types = node.get("@type")
    types = types if isinstance(types, list) else [types]
    return any(isinstance(t, str) and _EVENT_TYPES.search(t) for t in types)


def json_ld_dates(html: str) -> list[str]:
    """Dates de représentation déclarées en JSON-LD, en clair et gratuitement.

    Beaucoup de sites de spectacle publient un `schema.org/Event` par
    représentation, pour apparaître dans Google Événements — ils ont donc
    intérêt à le tenir à jour. Quand ces objets sont là, ce sont les dates
    exactes, sans exécuter la moindre ligne de JavaScript.

    Encore faut-il que ce soient des représentations. Un `Event` dont la
    `endDate` tombe un autre jour décrit une **période**, pas une séance : sa
    `startDate` n'est que le premier jour de l'affiche. La retenir comme date
    unique serait pire que de ne rien savoir — un spectacle joué tous les
    mercredis et samedis du mois se réduirait à sa première.

    On ne garde donc que les objets d'un seul jour, et c'est `schedule.py` qui
    juge si le lot obtenu constitue vraiment un calendrier.
    """
    dates: list[str] = []
    for block in _ld_blocks(html):
        for node in _walk(block):
            if not _is_event(node):
                continue
            start = node.get("startDate")
            if not isinstance(start, str) or not start.strip():
                continue
            end = node.get("endDate")
            if isinstance(end, str) and end.strip()[:10] != start.strip()[:10]:
                continue
            dates.append(start.strip())
    return dates


#: Fragments d'URL ou d'attribut qui trahissent une image d'habillage plutôt
#: qu'une illustration : logo du site, icône, pixel de suivi, bouton de partage.
_DECORATIVE = re.compile(
    r"logo|icon|favicon|sprite|avatar|placeholder|pixel|spacer|banni?ere|"
    r"header|footer|social|partage|share|facebook|twitter|instagram",
    re.I,
)

#: Extensions qu'un `<img>` peut porter sans être une photo exploitable.
_BAD_IMAGE_SUFFIX = (".svg", ".gif", ".ico")

#: En dessous, l'attribut `width`/`height` annonce une vignette ou une icône.
_MIN_IMAGE_SIDE = 200


def _image_candidates(soup: BeautifulSoup) -> list[str]:
    """URLs d'images déclarées par la page, de la plus fiable à la moins sûre.

    L'ordre n'est pas arbitraire : `og:image` est l'image que le site lui-même
    montre quand on partage la page — c'est exactement l'illustration
    cherchée. Les `<img>` du corps ne viennent qu'après, faute de mieux.
    """
    found: list[str] = []

    for prop in ("og:image:secure_url", "og:image:url", "og:image", "twitter:image"):
        for tag in soup.find_all("meta", attrs={"property": prop}):
            found.append((tag.get("content") or "").strip())
        for tag in soup.find_all("meta", attrs={"name": prop}):
            found.append((tag.get("content") or "").strip())

    for tag in soup.find_all("link", attrs={"rel": "image_src"}):
        found.append((tag.get("href") or "").strip())

    return [url for url in found if url]


def _ld_images(html: str) -> list[str]:
    """Images déclarées en JSON-LD : `image` d'un Event, sous ses trois formes.

    Un site écrit `"image": "https://…"`, une liste d'URLs, ou un `ImageObject`
    avec son `url`. Les trois se rencontrent, aucune n'est plus correcte.
    """
    found: list[str] = []
    for block in _ld_blocks(html):
        for node in _walk(block):
            if not _is_event(node):
                continue
            value = node.get("image")
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, str) and item.strip():
                    found.append(item.strip())
                elif isinstance(item, dict):
                    url = item.get("url") or item.get("contentUrl")
                    if isinstance(url, str) and url.strip():
                        found.append(url.strip())
    return found


def _body_images(soup: BeautifulSoup) -> list[str]:
    """`<img>` du corps de la page, l'habillage évident écarté."""
    found: list[str] = []
    for tag in soup.find_all("img"):
        # Le lazy-loading laisse `src` vide et met la vraie URL ailleurs.
        raw = ""
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            raw = (tag.get(attr) or "").strip()
            if raw:
                break
        if not raw:
            srcset = (tag.get("srcset") or tag.get("data-srcset") or "").strip()
            raw = srcset.split(",")[0].strip().split(" ")[0] if srcset else ""
        if not raw or raw.startswith("data:"):
            continue
        haystack = " ".join(
            filter(None, [raw, tag.get("alt") or "", " ".join(tag.get("class") or [])])
        )
        if _DECORATIVE.search(haystack):
            continue
        if _too_small(tag):
            continue
        found.append(raw)
    return found


def _too_small(tag) -> bool:
    """Une image dont la page annonce elle-même la petite taille est une icône."""
    for attr in ("width", "height"):
        value = (tag.get(attr) or "").strip().rstrip("px")
        if value.isdigit() and int(value) < _MIN_IMAGE_SIDE:
            return True
    return False


def _usable_image(url: str, page_url: str) -> str:
    """URL absolue et exploitable, ou chaîne vide."""
    if not url or url.startswith("data:"):
        return ""
    absolute = urljoin(page_url, url).split("#")[0]
    if not absolute.startswith(("http://", "https://")):
        return ""
    path = urlsplit(absolute).path.lower()
    if path.endswith(_BAD_IMAGE_SUFFIX):
        return ""
    return absolute


def main_image(html: str, page_url: str) -> str:
    """URL absolue de l'illustration de la page, ou chaîne vide.

    C'est le pendant de `json_ld_dates` pour la photo : ce que le HTML dit
    lui-même, gratuitement et sans risque d'invention. Le modèle, qui ne voit
    que le texte de la page, ne pouvait pas répondre à cette question — d'où
    des sorties importées systématiquement sans image.
    """
    soup = BeautifulSoup(html, "html.parser")
    for url in _image_candidates(soup) + _ld_images(html) + _body_images(soup):
        usable = _usable_image(url, page_url)
        if usable:
            return usable
    return ""


def page_text(html: str, limit: int = 8000) -> str:
    """Texte lisible d'une page, pour l'extraction d'une sortie."""
    soup = _soup(html)
    for tag in soup(["nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return text[:limit]
