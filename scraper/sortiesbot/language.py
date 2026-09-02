"""Préférer la version française d'une page à sa version anglaise.

Un moteur remonte volontiers l'adresse anglaise d'un site pourtant
francophone : le musée, le théâtre ou l'office de tourisme publie les deux, et
c'est parfois `/en/` qui est le mieux indexé. La page décrit la même sortie,
mais elle arriverait sur le site avec une description en anglais et un lien
que les parents n'attendaient pas. Beaucoup de sites servent d'ailleurs les
deux versions **à la même adresse** et tranchent sur l'en-tête
`Accept-Language` — c'est pourquoi le `Fetcher` en envoie un, et c'est la
moitié gratuite du problème.

L'autre moitié se règle ici. Rien n'y demande de jugement : une page dit
elle-même sa langue, et déclare le plus souvent où trouver sa jumelle. C'est
donc du Python, pas un appel au modèle.

Trois signaux, du plus fiable au moins sûr :

1. `<link rel="alternate" hreflang="fr">` — la traduction déclarée par le
   site, c'est-à-dire la réponse de celui qui la connaît ;
2. l'adresse elle-même — `/en/`, `en.exemple.fr`, `?lang=en` se transposent ;
3. la langue du texte, quelques mots outils suffisant à distinguer le français
   de l'anglais quand la page ne déclare rien.

Le troisième ne fabrique jamais d'adresse : il sert à **vérifier** un candidat
proposé par les deux premiers, et à reconnaître une page anglaise qui ne le
déclare pas mais annonce sa traduction. On ne change d'adresse que si la page
obtenue est réellement en français : c'est la règle du reste du scraper — on
ne devine pas une URL, on constate.

Une page qui se déclare française, ou qui ne déclare rien du tout sans que son
adresse ni une balise de traduction n'appellent la question, est laissée telle
quelle sans une requête de plus. C'est le cas de l'immense majorité d'entre
elles, et c'est ce qui rend ce détour gratuit.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .harvest import FetchError, page_text
from .store import normalize_url

FRENCH = "fr"
ENGLISH = "en"

#: Adresses essayées au plus pour une page. Chacune coûte une requête au site
#: et une seconde de délai de politesse : au-delà de trois, on s'acharne.
MAX_CANDIDATES = 3

#: Segments d'adresse qui désignent une version anglaise, et ce par quoi on
#: les remplace — dans l'ordre de vraisemblance.
_SEGMENTS = {
    "en": ("fr",),
    "eng": ("fr",),
    "en-us": ("fr-fr", "fr"),
    "en-gb": ("fr-fr", "fr"),
    "en_us": ("fr_fr", "fr"),
    "en_gb": ("fr_fr", "fr"),
    "english": ("francais", "fr"),
}

#: Paramètres par lesquels un site passe sa langue en clair.
_QUERY_KEYS = ("lang", "langue", "language", "locale", "hl", "l")

#: Mots outils : les plus fréquents de chaque langue, et ceux qu'aucune page ne
#: peut éviter. On ne cherche pas à reconnaître une langue en général — juste à
#: trancher entre deux.
_FRENCH_WORDS = frozenset(
    "le la les des une un du au aux et est sont pour avec dans sur par vous "
    "nous plus tout tous cette ses son leur mais ou où que qui ne pas".split()
)
_ENGLISH_WORDS = frozenset(
    "the and of to for with you your our this that these from are is was will "
    "have has all more about their there which what when".split()
)

#: En dessous, le décompte ne prouve rien : une page de trois phrases peut
#: contenir « the » sans être anglaise.
_MIN_WORDS = 5

#: Une langue ne l'emporte que si elle devance nettement l'autre. Une page
#: bilingue, ou truffée de titres d'œuvres, ne doit pas nous faire déménager.
_MARGIN = 2.0

_WORD = re.compile(r"[a-zàâäçéèêëîïôöùûüÿœæ]+", re.I)


# ------------------------------------------------------------ la langue d'une page


def _code(value: str) -> str:
    """« fr-FR », « fr_fr », « FR » → « fr ». Vide si ce n'en est pas un."""
    head = re.split(r"[-_]", (value or "").strip().lower())[0]
    return head if len(head) == 2 and head.isalpha() else ""


def declared_language(html: str) -> str:
    """La langue que la page déclare : `<html lang>`, puis `og:locale`.

    C'est la réponse de l'auteur du site. Vide quand il ne dit rien, ce qui
    reste fréquent — d'où le repli sur le texte.
    """
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("html")
    if root is not None:
        code = _code(root.get("lang") or root.get("xml:lang") or "")
        if code:
            return code
    for tag in soup.find_all("meta", attrs={"property": "og:locale"}):
        code = _code(tag.get("content") or "")
        if code:
            return code
    for tag in soup.find_all("meta", attrs={"http-equiv": re.compile("language$", re.I)}):
        code = _code(tag.get("content") or "")
        if code:
            return code
    return ""


def text_language(html: str) -> str:
    """« fr », « en », ou vide — d'après les mots outils du texte.

    Un décompte, pas une détection de langue : la question posée n'a que deux
    réponses possibles, et les mots grammaticaux les séparent sans ambiguïté
    dès quelques phrases.
    """
    mots = [m.lower() for m in _WORD.findall(page_text(html, limit=4000))]
    francais = sum(1 for m in mots if m in _FRENCH_WORDS)
    anglais = sum(1 for m in mots if m in _ENGLISH_WORDS)
    if max(francais, anglais) < _MIN_WORDS:
        return ""
    if francais >= anglais * _MARGIN:
        return FRENCH
    if anglais >= francais * _MARGIN:
        return ENGLISH
    return ""


def language_of(html: str) -> str:
    """Ce que la page déclare, sinon ce que son texte trahit."""
    return declared_language(html) or text_language(html)


# ------------------------------------------------------- les adresses candidates


def french_alternates(html: str, page_url: str) -> list[str]:
    """Les `<link rel="alternate" hreflang="fr…">` de la page, en absolu.

    Le signal le plus sûr : le site nous donne lui-même l'adresse de sa
    traduction, il n'y a rien à deviner.
    """
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    for tag in soup.find_all("link", href=True):
        rel = " ".join(tag.get("rel") or []).lower()
        if "alternate" not in rel:
            continue
        if _code(tag.get("hreflang") or "") != FRENCH:
            continue
        found.append(urljoin(page_url, tag["href"].strip()))
    return found


def _by_path(parts) -> list[str]:
    """`/en/agenda` → `/fr/agenda`."""
    segments = parts.path.split("/")
    found: list[str] = []
    for index, segment in enumerate(segments):
        for replacement in _SEGMENTS.get(segment.lower(), ()):
            other = list(segments)
            other[index] = replacement
            found.append(
                urlunsplit((parts.scheme, parts.netloc, "/".join(other), parts.query, ""))
            )
    return found


def _by_host(parts) -> list[str]:
    """`en.exemple.fr` → `fr.exemple.fr`."""
    host = parts.netloc
    if not host.lower().startswith("en."):
        return []
    return [urlunsplit((parts.scheme, "fr." + host[3:], parts.path, parts.query, ""))]


def _by_query(parts) -> list[str]:
    """`?lang=en` → `?lang=fr`."""
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    found: list[str] = []
    for index, (key, value) in enumerate(pairs):
        if key.lower() not in _QUERY_KEYS or _code(value) != ENGLISH:
            continue
        for replacement in _SEGMENTS.get(value.lower(), (FRENCH,)):
            other = list(pairs)
            other[index] = (key, replacement)
            found.append(
                urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(other), ""))
            )
    return found


def english_url(url: str) -> bool:
    """L'adresse elle-même annonce-t-elle une version anglaise ?"""
    parts = urlsplit(url)
    return bool(_by_path(parts) or _by_host(parts) or _by_query(parts))


def candidates(url: str, html: str) -> list[str]:
    """Les adresses où la version française pourrait se trouver, dans l'ordre.

    La traduction déclarée d'abord, les transpositions d'adresse ensuite : on
    n'essaie de deviner que si le site n'a pas répondu.
    """
    parts = urlsplit(url)
    proposees = (
        french_alternates(html, url) + _by_path(parts) + _by_host(parts) + _by_query(parts)
    )
    retenues: list[str] = []
    vues = {normalize_url(url)}
    for candidate in proposees:
        if not candidate.startswith(("http://", "https://")):
            continue
        key = normalize_url(candidate)
        if key in vues:
            continue
        vues.add(key)
        retenues.append(candidate)
    return retenues[:MAX_CANDIDATES]


# ----------------------------------------------------------------- le remplacement


def _foreign(url: str, html: str) -> bool:
    """Cette page mérite-t-elle qu'on cherche sa version française ?

    Trois questions, de la moins chère à la plus chère : ce que la page
    déclare, ce que son adresse annonce, et — seulement si le site déclare une
    traduction française, donc seulement si la question peut avoir une réponse
    — ce que son texte trahit. Une page qui ne dit rien, dont l'adresse ne dit
    rien et qui ne déclare aucune traduction ne coûte ainsi qu'une lecture
    d'en-tête.
    """
    declaree = declared_language(html)
    if declaree == FRENCH:
        return False
    if declaree or english_url(url):
        return True
    return bool(french_alternates(html, url)) and text_language(html) == ENGLISH


def french_version(url: str, html: str, fetcher, log=None) -> tuple[str, str]:
    """L'adresse française de cette page et son HTML — ou le couple reçu.

    On ne cherche que si la page se dit d'une autre langue ou si son adresse
    l'annonce : ailleurs, il n'y a pas de question, et pas une requête n'est
    lancée. Un candidat n'est retenu que s'il répond **et** qu'il est en
    français : une redirection vers l'anglais ou une page absente ne change
    rien.
    """
    if not _foreign(url, html):
        return url, html

    for candidate in candidates(url, html):
        try:
            autre = fetcher.get_html(candidate)
        except FetchError:
            continue
        if language_of(autre) != FRENCH:
            continue
        if log is not None:
            log.event("french", url=candidate, was=url)
        return candidate, autre

    if log is not None:
        log.event("no_french", url=url)
    return url, html
