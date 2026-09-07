"""Le banc d'évaluation, côté worker. Pour l'instant, l'étage 3 seul.

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
"""

from __future__ import annotations

import base64
import gzip
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
    links_of,
)

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
