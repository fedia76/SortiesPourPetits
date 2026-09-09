"""Le banc d'évaluation, côté worker : les étages 3, 5 et 6.

## Le principe : la brique précoche, l'humain corrige

Le banc relève **tous** les liens d'une page — pas seulement ceux que le
dépouillement a retenus — et marque, pour chacun, ce que la brique en a fait.
L'humain n'a plus qu'à corriger ce qui est faux.

C'est ce qui permet de mesurer les **deux** erreurs. Ne montrer que la moisson
obligerait à retrouver les manqués soi-même, en rouvrant la vraie page : lent,
et incomplet par construction — on ne trouve que ce qu'on a pensé à chercher.
Et surtout, ça ne dirait rien du contraire : un lien retenu qui ne mène nulle
part coûte un appel payant à l'étage 4, et cette erreur-là serait restée
invisible.

## Les quatre verdicts

Chaque lien reçoit une étiquette, et il en faut quatre parce que trois ne
suffisent pas à décrire ce qu'un agenda contient réellement :

* **sortie** — mène à la fiche d'un événement. C'est ce que l'étage 4 doit
  garder.
* **pagination** — la page 2, 3… du même agenda. L'étage 3 la suit, mais
  seulement quand elle se déclare en `rel="next"`.
* **sous-agenda** — « voir aussi les sorties en château », « les sorties
  gratuites » : une **autre liste**, avec d'autres sorties, qui n'est pas la
  page suivante. Ces pages à facettes sont partout, et le pipeline n'en fait
  aujourd'hui **rien** : le dépouillement les rend, et le prompt de sélection
  lui dit d'écarter les liens de catégorie. Les sorties qu'elles portent ne
  sont jamais atteintes, et aucun compteur ne le dit.
* **autre** — navigation, mentions légales, partage. Correctement écarté.

## Ce qui est partagé avec la production, et ce qui ne l'est pas

**Partagé : la fonction.** `links_of` est importée telle quelle, et c'est
**elle** qui décide de la précoche — pas une réimplémentation. `_why` ci-dessous
ne fait qu'expliquer *a posteriori* un rejet déjà prononcé : une erreur dans son
raisonnement fausserait un libellé, jamais la mesure.

**Pas partagé : l'orchestration.** `Harvest`, l'étage 3, journalise, tient les
compteurs du run, dédoublonne entre pages et s'arrête dès que sa moisson
suffit. Le banc a sa propre boucle, plus bête, et un nombre de pages fixe.

## La pagination, vérifiée plutôt que supposée

Chaque page rapporte aussi ce que `next_page()` y a trouvé. Comparé aux liens
que l'humain étiquette « pagination », ça répond à une question que le pipeline
ne pose jamais : **ce site se pagine-t-il d'une façon que l'étage 3 sait
suivre ?** Un agenda qui numérote ses pages sans `rel="next"` n'est jamais
suivi, et rien aujourd'hui ne le signale.

## L'archive

Chaque page part avec son HTML, gzippé : c'est ce qui fait du banc un corpus
gelé plutôt qu'un instantané. Une page qu'on ne peut pas archiver est rapportée
quand même, sans son HTML — la mesure est le travail, l'archive est le confort
du rejeu.

## L'enchaînement des trois étages mesurés

Chacun se mesure sur la **sortie gelée du précédent**, et c'est ce qui permet
d'accuser le bon : l'étage 5 lit une page, l'étage 6 lit le texte que l'étage 5
a produit. Rejouer l'extraction sur la page vivante mêlerait les deux — une
fiche sans tarif ne dirait plus si le modèle l'a raté ou si la lecture l'avait
déjà emporté avec un `<aside>`.
"""

from __future__ import annotations

import base64
import gzip
import re
import unicodedata
from typing import Any
from urllib.parse import urljoin, urlsplit

from .classify import next_page
from .harvest import (
    BORING_PATH,
    MIN_TEXT,
    FetchError,
    Fetcher,
    _context_of,
    _soup,
    json_ld_dates,
    links_of,
    main_image,
    page_text,
)
from .language import french_version
from .models import ExtractedEvent
from .stages.reading import MIN_PAGE_CHARS

#: Plafond de l'archive d'une page, en caractères de base64 — le même que celui
#: du site, qui refuserait au-delà. Un million de caractères font environ 750 ko
#: compressés, soit plusieurs mégaoctets de HTML : au-delà, la page est
#: pathologique et part sans son archive plutôt que de faire échouer tout le
#: compte rendu.
MAX_HTML_B64 = 1_000_000

#: Plafond du relevé. Bien au-dessus des deux cents que `links_of` retient : ici
#: on veut aussi tout ce qu'il écarte, et une page à méga-menu en aligne
#: facilement trois cents avant d'arriver au listing. Au-delà, c'est un humain
#: qu'on noierait.
MAX_AUDIT_LINKS = 600


def _archive(html: str) -> str:
    """Le HTML gzippé puis encodé en base64, ou une chaîne vide.

    Compressé ici plutôt que sur le site : les octets voyagent six à huit fois
    plus petits, et le serveur les écrit tels quels sans avoir à les déballer.
    """
    try:
        packed = base64.b64encode(gzip.compress(html.encode("utf-8"), 6)).decode("ascii")
    except (OSError, MemoryError, UnicodeError):
        return ""
    return packed if len(packed) <= MAX_HTML_B64 else ""


def _why(url: str, text: str, host: str, seen: set[str]) -> str:
    """Pourquoi le dépouillement a écarté ce lien. Un libellé, pas un verdict.

    C'est une explication *a posteriori* : `links_of` a déjà tranché, et son
    verdict est celui qui compte. Cette fonction ne sert qu'à ranger les rejets
    par motif dans la console, pour que l'humain sache où chercher — les
    ratages se concentrent sous « texte trop court » et « hors domaine », pas
    sous « mentions légales ».

    L'ordre suit celui de `links_of` : c'est le premier motif rencontré qui est
    rendu, comme c'est le premier `continue` qui l'a écarté.
    """
    if urlsplit(url).netloc != host:
        return "hors domaine"
    if len(text) < MIN_TEXT:
        return "texte trop court"
    path = urlsplit(url).path
    if not path or path == "/":
        return "racine du site"
    if BORING_PATH.search(path):
        return "chemin de service"
    if url in seen:
        return "doublon"
    return "plafond atteint"


def audit_links(html: str, page_url: str) -> list[dict[str, Any]]:
    """Tous les `<a href>` de la page, avec ce que le dépouillement en a fait.

    Rend, dans l'ordre du document : l'URL, le texte de l'ancre, son contexte,
    `harvested` — vrai si le **vrai** `links_of` l'a retenu — et le motif du
    rejet sinon.

    **Le contexte accompagne tous les liens, y compris les écartés**, et c'est
    une correction. Une première version le réservait aux liens retenus, au
    motif que c'est ce que l'étage 4 reçoit et qu'un lien écarté ne le lui donne
    jamais. L'argument était juste et la conséquence absurde : le contexte ne
    sert pas ici à l'étage 4, il sert à **l'humain pour juger**. Et il manquait
    très exactement là où il est indispensable — un lien écarté pour « texte
    trop court » est, par définition, un lien dont l'intitulé ne dit rien. Sans
    lui, la console affichait soixante-seize URL nues, impossibles à trancher
    sans les ouvrir une par une.

    Le contexte d'un lien de navigation reste maigre, et c'est honnête :
    `_context_of` abandonne dès que le voisinage dépasse la carte, donc un lien
    perdu dans un méga-menu ne rend que son propre texte.

    Les ancres pures (`#`, `javascript:`, `mailto:`, `tel:`) sont écartées d'ici
    aussi : elles ne mènent nulle part, il n'y a rien à étiqueter, et les
    montrer à un humain lui ferait lire deux cents lignes pour rien.
    """
    # La vérité de la précoche vient de la fonction de production, jamais d'une
    # relecture de ses règles : si les deux divergeaient un jour, c'est elle qui
    # aurait raison, et c'est elle qu'on mesure.
    kept = {link.url for link in links_of(html, page_url)}

    soup = _soup(html)
    host = urlsplit(page_url).netloc
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(page_url, href).split("#")[0]
        if url in seen:
            # Un même lien répété — le logo, « accueil » — ne s'étiquette pas
            # trois fois. `links_of` le dédoublonne aussi.
            continue

        text = " ".join(anchor.get_text(" ", strip=True).split())
        harvested = url in kept
        out.append(
            {
                "url": url,
                "text": text[:150],
                "context": _context_of(anchor, text),
                "harvested": harvested,
                "reason": "" if harvested else _why(url, text, host, seen),
            }
        )
        seen.add(url)
        if len(out) >= MAX_AUDIT_LINKS:
            break

    return out


def harvest_agenda(url: str, pages: int, fetcher: Fetcher | None = None) -> list[dict[str, Any]]:
    """Relève un agenda et ses pages suivantes. Une entrée par page demandée.

    Rend toujours au moins une entrée : une page injoignable en est une, avec
    son motif et zéro lien. C'est la même distinction que fait l'étage 3 entre
    `None` et la liste vide — sauf qu'ici les deux doivent **remonter**, parce
    qu'une page qu'on n'a pas pu lire est un fait mesurable, pas un trou.

    Les liens ne sont **pas** dédoublonnés d'une page à l'autre. `links_of`
    travaille page par page, et c'est page par page que la vérité s'établit :
    un lien présent sur les pages 1 et 2 a été vu deux fois, et fusionner les
    deux ferait disparaître une moitié du travail qu'on cherche à noter.
    """
    fetcher = fetcher or Fetcher()
    out: list[dict[str, Any]] = []
    seen_pages = {url}
    current = url
    html = ""

    for page_no in range(1, max(1, pages) + 1):
        if page_no > 1:
            # On ne suit que `rel="next"`, comme l'étage 3. Reconstruire
            # « page 2 » à partir de liens numérotés reviendrait à inventer une
            # URL, et le banc mentirait alors sur ce que le pipeline visite.
            following = next_page(html, current) if html else ""
            if not following or following in seen_pages:
                break
            seen_pages.add(following)
            current = following

        try:
            html = fetcher.get_html(current)
        except FetchError as err:
            out.append(
                {"pageNo": page_no, "url": current, "chars": 0, "error": str(err), "links": []}
            )
            break

        entry: dict[str, Any] = {
            "pageNo": page_no,
            "url": current,
            "chars": len(html),
            # Ce que l'étage 3 saurait suivre depuis cette page. Comparé aux
            # liens que l'humain étiquettera « pagination », c'est la mesure de
            # la pagination : un agenda qui numérote ses pages sans `rel="next"`
            # n'est jamais suivi, et rien aujourd'hui ne le signale.
            "nextUrl": next_page(html, current),
            "links": audit_links(html, current),
        }
        packed = _archive(html)
        if packed:
            entry["html"] = packed
        out.append(entry)

    if not out:
        # Défensif : `pages` est validé côté site, mais un agenda sans la
        # moindre entrée laisserait la console incapable de dire ce qui s'est
        # passé — et le compte rendu serait refusé.
        out.append({"pageNo": 1, "url": url, "chars": 0, "error": "aucune page lue", "links": []})
    return out


# ═══════════════════════════════════════════════ étage 5 — la lecture d'une page

#: Ce qui, dans une adresse d'image, trahit un logo plutôt qu'une illustration.
#: Un libellé, pas une décision : `main_image` a déjà tranché, et c'est son
#: choix qu'on mesure. Ça sert seulement à dire à l'humain où regarder.
_LOGO_HINT = re.compile(r"(logo|favicon|sprite|icone?|icon|placeholder|default)", re.I)

#: Le texte gardé pour la console. `page_text` plafonne déjà à 8 000, mais la
#: configuration peut monter : on borne ici pour ne pas faire voyager un roman.
MAX_TEXT_KEPT = 20_000


def _first_heading(soup) -> str:
    """Le premier `h1` de la page, ou son `title` à défaut.

    C'est l'étalon du signal le plus utile de cet étage : si le titre de la page
    ne se retrouve pas dans le texte extrait, c'est que `page_text` a emporté le
    bloc qui le portait — presque toujours un `<header>`.
    """
    for tag in ("h1", "title"):
        node = soup.find(tag)
        if node:
            text = " ".join(node.get_text(" ", strip=True).split())
            if text:
                return text[:200]
    return ""


def read_page(url: str, fetcher: Fetcher | None = None) -> dict[str, Any]:
    """Rejoue l'étage 5 sur une page, et rapporte ce qu'il en tire.

    Les trois lectures sont celles de la production — `page_text`,
    `json_ld_dates`, `main_image` — importées telles quelles, et l'échange de
    langue est rejoué lui aussi : c'est lui qui décide *quelle* page est
    finalement lue, et l'oublier ferait mesurer une autre page que celle que le
    pipeline aurait choisie.

    ## Les signaux, qui ne décident de rien

    Comme les motifs de rejet de l'étage 3, ce sont des libellés : la brique a
    déjà rendu ce qu'elle rend, et c'est ce rendu qu'on mesure. Ils disent
    seulement à l'humain **où regarder**, parce qu'une page qui se lit mal se
    reconnaît presque toujours à l'un de ces quatre indices :

    * `h1InText` — le titre de la page ne se retrouve pas dans le texte. Presque
      toujours un `<header>` emporté par le décapage, et avec lui les dates et
      l'adresse ;
    * `truncated` — le texte est au plafond : la fin de la page n'a jamais
      atteint le modèle, ce qui se déguise en « l'extraction multi en rate la
      moitié » ;
    * `tooShort` — sous le seuil de l'étage 5, donc **la page serait
      abandonnée** avant le moindre appel payant. C'est le ratage le plus cher
      et le plus silencieux ;
    * `imageLooksLogo` — l'adresse de l'illustration ressemble à celle d'un
      logo.
    """
    fetcher = fetcher or Fetcher()
    out: dict[str, Any] = {"url": url}
    try:
        html = fetcher.get_html(url)
    except FetchError as err:
        out["error"] = str(err)
        return out

    # L'échange de langue fait partie de l'étage : c'est lui qui décide quelle
    # page est lue, et son adresse est celle qui sera proposée au site.
    read_url, html = french_version(url, html, fetcher)
    out["url"] = read_url
    out["swapped"] = read_url != url

    text = page_text(html)
    dates = json_ld_dates(html)
    image = main_image(html, read_url)
    heading = _first_heading(_soup(html))

    out.update(
        {
            "chars": len(html),
            "text": text[:MAX_TEXT_KEPT],
            "textChars": len(text),
            "heading": heading,
            "dates": dates,
            "imageUrl": image,
            # `page_text` tronque à sa limite : y être exactement, c'est y avoir
            # été coupé. Le cas limite d'une page qui fait pile la taille est
            # rarissime, et se tromper dans ce sens ne coûte qu'un signal de
            # trop — jamais une mesure fausse.
            "truncated": len(text) >= 8000,
            "tooShort": len(text) < MIN_PAGE_CHARS,
            "h1InText": bool(heading) and _normalise(heading) in _normalise(text),
            "imageLooksLogo": bool(image) and bool(_LOGO_HINT.search(image)),
        }
    )
    packed = _archive(html)
    if packed:
        out["html"] = packed
    return out


def _normalise(text: str) -> str:
    """Minuscules et espaces normalisés : comparer un titre à un texte extrait
    ne doit pas échouer sur une espace insécable ou une capitale."""
    return " ".join(text.lower().replace("\u00a0", " ").split())


# ═════════════════════════════════════════ étage 6 — l'extraction des champs

# ## Pourquoi cet étage se mesure autrement que les deux précédents
#
# Les étages 3 et 5 sont du Python : ils rendent toujours la même chose sur la
# même page, et ce qu'on mesure est une **fonction**. L'étage 6 est un appel de
# modèle : il rend une **fiche**, il coûte de l'argent, et il peut inventer.
#
# D'où trois différences de méthode :
#
# 1. **Champ par champ, jamais fiche par fiche.** Une fiche « fausse » ne dit pas
#    quel champ a lâché, donc ne dit pas quoi réparer. Douze aspects, chacun jugé
#    séparément, disent « le tarif se rate une fois sur trois » — et c'est une
#    ligne de prompt à réécrire.
#
# 2. **Trois instruments gratuits avant le premier clic.** L'ancrage (toute
#    valeur doit se retrouver dans le texte), la cohérence interne (un âge
#    minimum au-dessus du maximum), l'accord avec les dates JSON-LD relevées par
#    l'étage 5. Aucun des trois ne demande d'étiquette humaine, et à eux trois
#    ils désignent la plupart des fautes.
#
# 3. **Le corpus est le texte de l'étage 5, pas la page.** L'extraction est
#    rejouée sur le texte exact que le banc de lecture a archivé. C'est ce qui
#    fait qu'une mauvaise fiche accuse bien l'étage 6 : si le texte était amputé,
#    c'est l'étage 5 qui est en cause, et le banc de lecture l'a déjà dit.
#
# ## Ce que les instruments ne peuvent pas faire
#
# `setting` — intérieur ou extérieur — n'a **aucun** instrument gratuit. Une page
# ne l'écrit presque jamais : elle dit « au parc de la Villette » ou « salle
# Jean-Vilar », et c'est le lecteur qui conclut. C'est donc l'aspect qui coûtera
# toujours une étiquette humaine, et il faut le savoir plutôt que d'imaginer une
# heuristique qui donnerait l'illusion d'une mesure.

#: L'énuméré du cadre, en français. Le schéma impose l'anglais au modèle ; la
#: console parle la langue du site.
_SETTINGS = {"INDOOR": "intérieur", "OUTDOOR": "extérieur", "BOTH": "les deux"}

#: Les mois en toutes lettres, pour reconnaître « 3 août » dans une page quand
#: le modèle a rendu « 2026-08-03 ».
_MONTHS = (
    "janvier", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
)

#: Part des mots d'un titre qu'il faut retrouver dans la page pour le tenir pour
#: ancré. La moitié : un titre est souvent reformulé — un article retiré, une
#: majuscule changée — mais un titre dont la moitié des mots sont absents de la
#: page n'a pas été lu, il a été composé.
_OVERLAP_MIN = 0.5


def _flat(text: str) -> str:
    """Minuscules, sans accents, espaces normalisés.

    L'ancrage compare ce qu'un modèle a écrit à ce qu'une page dit, et les deux
    ne s'accordent jamais sur les accents ni sur les espaces insécables. Comparer
    à la lettre ferait crier à l'invention sur « Théâtre » contre « theatre ».
    """
    lowered = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(c for c in lowered if unicodedata.category(c) != "Mn")
    return " ".join(stripped.split())


def _price_in(price: float, hay: str) -> bool:
    """Ce tarif se lit-il dans la page ?

    Un nombre nu ne prouve rien : « 8 » se trouve dans n'importe quel texte
    assez long. On exige donc le voisinage d'une monnaie — c'est ce qui fait la
    différence entre un tarif lu et un tarif plausible.
    """
    money = r"(?:€|eur\b|euros?\b)"
    if price == int(price):
        whole = int(price)
        return bool(
            re.search(rf"\b{whole}\s*(?:[.,]\s*0{{1,2}})?\s*{money}", hay)
            or re.search(rf"{money}\s*{whole}\b", hay)
            or re.search(rf"\b{whole}\s*(?:[.,]\s*0{{1,2}})?\s*(?:e\b)", hay)
        )
    whole, cents = f"{price:.2f}".split(".")
    return bool(re.search(rf"\b{whole}\s*[.,]\s*{cents}\b", hay))


def _age_in(age: int, hay: str) -> bool:
    """Cet âge se lit-il dans la page ?

    Même précaution que pour le tarif, avec deux tournures : « 3 ans », et
    « à partir de 3 » — les pages écrivent volontiers l'une ou l'autre.
    """
    return bool(
        re.search(rf"\b{age}\s*(?:ans?|mois)\b", hay)
        or re.search(
            rf"(?:des|a partir de|partir de|plus de|moins de|jusqu a|des l age de)"
            rf"\s*(?:l age de\s*)?{age}\b",
            hay,
        )
    )


def _time_in(hhmm: str, hay: str) -> bool:
    """Cet horaire se lit-il dans la page ? « 14:30 », « 14h30 », « 14 h 30 »."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", hhmm.strip())
    if not match:
        return False
    hour, minute = match.group(1).lstrip("0") or "0", match.group(2)
    if minute == "00":
        return bool(re.search(rf"\b{hour}\s*[h:]\s*(?:00)?\b", hay))
    return bool(re.search(rf"\b{hour}\s*[h:]\s*{minute}\b", hay))


def _date_in(iso: str, hay: str) -> bool:
    """Cette date se lit-elle dans la page, sous l'une de ses écritures ?

    Une page française écrit « 3 août », « 03/08/2026 » ou « 2026-08-03 ». Ne
    chercher que la forme ISO ferait déclarer inventée toute date correctement
    lue, ce qui est le contraire de ce qu'on veut mesurer.
    """
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso.strip()[:10])
    if not match:
        return False
    year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
    if not 1 <= month <= 12:
        return False
    forms = [
        f"{year}-{month:02d}-{day:02d}",
        f"{day:02d}/{month:02d}/{year}",
        f"{day}/{month}/{year}",
        f"{day:02d}/{month:02d}",
        f"{day}/{month}",
        f"{day} {_MONTHS[month - 1]}",
        f"{day:02d} {_MONTHS[month - 1]}",
    ]
    # Le 1er du mois s'écrit « 1er août » et jamais « 1 août ».
    if day == 1:
        forms.append(f"1er {_MONTHS[month - 1]}")
    return any(form in hay for form in forms)


def _overlap(value: str, hay: str) -> float:
    """Part des mots significatifs de `value` qui se retrouvent dans la page.

    Les mots de moins de quatre lettres sont ignorés : « de », « la », « les »
    se trouvent partout et gonfleraient le score de n'importe quelle invention.
    Une valeur qui n'a aucun mot long est tenue pour ancrée — il n'y a rien à
    vérifier, et crier à l'invention sur « Noël » serait faux.
    """
    words = re.findall(r"[a-z0-9]{4,}", _flat(value))
    if not words:
        return 1.0
    return sum(1 for word in words if word in hay) / len(words)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)


def fiche_payload(event: ExtractedEvent) -> dict[str, Any]:
    """La fiche telle que la console la reçoit : les champs du modèle, en camelCase.

    Gardée entière, y compris les champs qu'aucun aspect ne juge : c'est la
    pièce à conviction, et une mesure dont on ne peut plus relire l'objet n'est
    pas vérifiable.
    """
    return {
        _camel(key): (list(value) if isinstance(value, tuple) else value)
        for key, value in vars(event).items()
    }


def _date_range(start: str, end: str) -> tuple[str, str]:
    """Les deux bornes réduites à leur jour, pour comparer sans se soucier des heures."""
    return start.strip()[:10], (end.strip()[:10] or start.strip()[:10])


def audit_fiche(
    event: ExtractedEvent,
    text: str,
    declared_dates: list[str] | tuple[str, ...] = (),
    categories: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Les douze aspects d'une fiche, chacun avec ce que les instruments en disent.

    Rend, pour chaque aspect : son libellé, la valeur rendue par le modèle en
    clair, si elle est renseignée, quel instrument l'a examinée, et les défauts
    relevés.

    **Ce ne sont pas des verdicts.** Comme les motifs de rejet de l'étage 3 et
    les signaux de l'étage 5, ce sont des libellés : le modèle a rendu ce qu'il
    a rendu, et c'est ce rendu qu'on mesure. Un drapeau dit à l'humain *où
    regarder d'abord* — et c'est beaucoup, parce que douze aspects sur trente
    fiches font trois cent soixante décisions dont l'écrasante majorité est
    « juste ».

    Trois instruments, aucun ne coûtant d'étiquette :

    * **ancrage** — la valeur se retrouve-t-elle dans le texte ? C'est le seul
      qui attrape une invention, et il l'attrape sans savoir ce qui est vrai ;
    * **cohérence** — la fiche se contredit-elle toute seule ? Un âge minimum
      au-dessus du maximum est faux sans qu'on ait lu la page ;
    * **accord** — les dates rendues rencontrent-elles celles que l'étage 5 a
      relevées en JSON-LD ? Deux lectures indépendantes de la même page qui se
      contredisent : l'une des deux se trompe, et il faut un humain pour dire
      laquelle.
    """
    hay = _flat(text)
    known = {_flat(c) for c in categories}
    out: list[dict[str, Any]] = []

    def add(
        key: str,
        label: str,
        value: str,
        filled: bool,
        instrument: str,
        flags: list[str],
    ) -> None:
        out.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "filled": filled,
                "instrument": instrument,
                # Un champ vide n'a rien à ancrer : les drapeaux ne valent que
                # pour ce que le modèle a osé écrire.
                "flags": flags if filled else [],
            }
        )

    # ── 1. le verdict sur la page elle-même. Le plus lourd de conséquences :
    #    une page écartée à tort ne coûte rien et ne se voit nulle part.
    if not event.relevant:
        verdict = f"écartée — {event.skip_reason}" if event.skip_reason else "écartée, sans motif"
    elif event.several:
        verdict = "programme : plusieurs sorties, à relire d'un bloc"
    else:
        verdict = "une sortie"
    add(
        "verdict",
        "La page",
        verdict,
        True,
        "aucun",
        ["incoherent"] if not event.relevant and not event.skip_reason.strip() else [],
    )

    # ── 2. le titre
    add(
        "titre",
        "Le titre",
        event.title,
        bool(event.title),
        "ancrage",
        ["hors_texte"] if _overlap(event.title, hay) < _OVERLAP_MIN else [],
    )

    # ── 3. la description. Une reformulation, donc jugée sur le vocabulaire :
    #    une description dont la moitié des mots longs sont absents de la page
    #    n'a pas été tirée d'elle.
    add(
        "description",
        "La description",
        event.description,
        bool(event.description),
        "ancrage",
        ["hors_texte"] if _overlap(event.description, hay) < _OVERLAP_MIN else [],
    )

    # ── 4. le tarif. Deux colonnes pour un seul fait : les juger séparément
    #    compterait deux fois la même erreur.
    tarif_flags: list[str] = []
    if event.free and event.price:
        tarif_flags.append("incoherent")
    if event.price is not None and not _price_in(event.price, hay):
        tarif_flags.append("hors_texte")
    if event.free and not re.search(r"\bgratui|entree libre|acces libre|offert", hay):
        tarif_flags.append("hors_texte")
    if event.free:
        tarif = "gratuit"
    elif event.price is not None:
        tarif = f"{event.price:g} €"
    else:
        tarif = ""
    add("tarif", "Le tarif", tarif, bool(tarif), "ancrage + cohérence", sorted(set(tarif_flags)))

    # ── 5. l'âge
    age_flags: list[str] = []
    if event.age_min is not None and event.age_max is not None and event.age_min > event.age_max:
        age_flags.append("incoherent")
    if any(age is not None and not _age_in(age, hay) for age in (event.age_min, event.age_max)):
        age_flags.append("hors_texte")
    if event.age_min is not None and event.age_max is not None:
        age = f"{event.age_min} à {event.age_max} ans"
    elif event.age_min is not None:
        age = f"dès {event.age_min} ans"
    elif event.age_max is not None:
        age = f"jusqu'à {event.age_max} ans"
    else:
        age = ""
    add("age", "L'âge", age, bool(age), "ancrage + cohérence", sorted(set(age_flags)))

    # ── 6. les dates
    start, end = _date_range(event.date_start, event.date_end)
    dates_flags: list[str] = []
    if event.permanent and (start or end):
        dates_flags.append("incoherent")
    if start and end and end < start:
        dates_flags.append("incoherent")
    absentes = [d for d in (start, end) if d and not _date_in(d, hay)]
    # Une page qui n'annonce qu'une fin — « jusqu'au 23 octobre » — vaut au
    # prompt de mettre *aujourd'hui* en date de début. Cette date-là n'est donc
    # pas dans la page, et c'est réglementaire : ne pas l'excepter ferait crier
    # à l'invention sur le cas même que le prompt décrit noir sur blanc.
    regle_du_jusqu_au = absentes == [start] and bool(end) and end != start
    if absentes and not regle_du_jusqu_au:
        dates_flags.append("hors_texte")
    if declared_dates and start:
        jours = {d.strip()[:10] for d in declared_dates}
        if not any(start <= jour <= (end or start) for jour in jours):
            dates_flags.append("divergent")
    if event.permanent:
        plage = "toute l'année"
    elif start and end and end != start:
        plage = f"du {start} au {end}"
    elif start:
        plage = f"le {start}"
    else:
        plage = ""
    add(
        "dates",
        "Les dates",
        plage,
        bool(plage),
        "ancrage + cohérence + accord",
        sorted(set(dates_flags)),
    )

    # ── 7. les jours. Sans eux, un spectacle du dimanche devient une plage
    #    continue, donc proposé un jeudi.
    jours_flags: list[str] = []
    if any(_flat(day) not in hay for day in event.weekdays):
        jours_flags.append("hors_texte")
    if any(not _date_in(d, hay) for d in event.dates):
        jours_flags.append("hors_texte")
    morceaux = list(event.weekdays) + list(event.dates)
    add(
        "jours",
        "Les jours",
        ", ".join(morceaux),
        bool(morceaux),
        "ancrage",
        sorted(set(jours_flags)),
    )

    # ── 8. les horaires
    horaires = " – ".join(t for t in (event.open_time, event.close_time) if t)
    add(
        "horaires",
        "Les horaires",
        horaires,
        bool(horaires),
        "ancrage",
        (
            ["hors_texte"]
            if any(t and not _time_in(t, hay) for t in (event.open_time, event.close_time))
            else []
        ),
    )

    # ── 9. intérieur ou extérieur. **Aucun instrument**, et c'est le sujet :
    #    une page ne l'écrit presque jamais, elle dit « au parc de la Villette »
    #    et c'est le lecteur qui conclut.
    add(
        "cadre",
        "Intérieur / extérieur",
        _SETTINGS.get(event.setting, event.setting),
        bool(event.setting),
        "aucun",
        [],
    )

    # ── 10. la catégorie : un référentiel, donc vérifiable sans humain.
    add(
        "categorie",
        "La catégorie",
        event.category,
        bool(event.category),
        "référentiel",
        ["hors_liste"] if known and _flat(event.category) not in known else [],
    )

    # ── 11. le lieu
    add(
        "lieu",
        "Le lieu",
        event.venue_name,
        bool(event.venue_name),
        "ancrage",
        ["hors_texte"] if _overlap(event.venue_name, hay) < _OVERLAP_MIN else [],
    )

    # ── 12. l'adresse
    adresse_flags: list[str] = []
    if event.venue_postal_code and not re.fullmatch(r"\d{5}", event.venue_postal_code.strip()):
        adresse_flags.append("incoherent")
    if event.venue_postal_code and _flat(event.venue_postal_code) not in hay:
        adresse_flags.append("hors_texte")
    if event.venue_city and _overlap(event.venue_city, hay) < _OVERLAP_MIN:
        adresse_flags.append("hors_texte")
    if event.venue_address and _overlap(event.venue_address, hay) < _OVERLAP_MIN:
        adresse_flags.append("hors_texte")
    adresse = ", ".join(
        p for p in (event.venue_address, event.venue_postal_code, event.venue_city) if p
    )
    add(
        "adresse",
        "L'adresse",
        adresse,
        bool(adresse),
        "ancrage + cohérence",
        sorted(set(adresse_flags)),
    )

    return out


def extract_page(
    url: str,
    text: str,
    *,
    provider: Any,
    config: Any,
    log: Any,
    categories: list[str] | tuple[str, ...] = (),
    declared_dates: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Rejoue l'étage 6 sur un texte déjà gelé, et rapporte la fiche et ses défauts.

    ## Le texte vient du banc de lecture, jamais du web

    C'est ce qui fait qu'une fiche fautive accuse **cet** étage. Retélécharger
    la page mêlerait deux variables : une fiche sans tarif dirait aussi bien
    « le modèle n'a pas vu le tarif » que « l'étage 5 l'avait déjà emporté avec
    un `<aside>` ». Le banc de lecture a mesuré cela séparément et l'a déjà dit ;
    ici, l'entrée est acquise.

    ## Un seul appel, en mode « page unique »

    Le mode programme — une page qui porte vingt sorties — pose une autre
    question : non pas « les champs sont-ils justes ? » mais « le découpage
    est-il le bon ? ». C'est une mesure de segmentation, avec sa propre table et
    ses propres taux, et la mélanger à celle-ci donnerait un chiffre qui ne
    voudrait rien dire. Ce que le banc mesure quand même, c'est la **décision**
    qui y mène : `several`, rendu par l'appel simple, est le premier aspect
    jugé.

    Le retour porte aussi ce que l'appel a coûté. C'est le premier étage du banc
    dont la mesure se paie, et le taire donnerait l'impression qu'elle est
    gratuite comme les deux précédentes.
    """
    before = getattr(provider, "usage", None)
    spent_in = getattr(before, "input_tokens", 0)
    spent_out = getattr(before, "output_tokens", 0)
    spent_usd = getattr(before, "cost_usd", 0.0)

    try:
        fiches = provider.extract(url, text, config, sorted(categories), log, multiple=False)
    except Exception as err:  # noqa: BLE001 — remonté tel quel à la console
        return {"error": f"{err.__class__.__name__} : {err}"}

    event = fiches[0] if fiches else ExtractedEvent(relevant=False, skip_reason="aucune fiche rendue")
    after = getattr(provider, "usage", None)
    return {
        "model": getattr(config, "extraction_model", ""),
        "fiche": fiche_payload(event),
        "aspects": audit_fiche(event, text, list(declared_dates), list(categories)),
        "inputTokens": getattr(after, "input_tokens", 0) - spent_in,
        "outputTokens": getattr(after, "output_tokens", 0) - spent_out,
        "costUsd": round(getattr(after, "cost_usd", 0.0) - spent_usd, 6),
    }
