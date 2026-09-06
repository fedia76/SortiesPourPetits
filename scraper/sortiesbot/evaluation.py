"""Le banc d'évaluation, côté worker. Pour l'instant, l'étage 3 seul.

## Ce que ce module mesure, et ce qu'il ne mesure pas

Il mesure **`links_of`** : ce que le dépouillement tire d'une page donnée. Il
ne mesure pas la politique de l'étage 3 — celle qui décide d'ouvrir une page
suivante *tant qu'il manque de liens*. Ce sont deux questions distinctes, et
les confondre rendrait les deux inexploitables :

* « ce site a-t-il des liens que je ne sais pas voir ? » se répond page par
  page, sur une page fixée ;
* « fallait-il ouvrir la page 3 ? » est un arbitrage de budget, qui se juge
  sur un run entier et son coût.

D'où le nombre de pages **fixe**, donné par la console, là où `Harvest`
s'arrête dès que sa moisson suffit. Demander deux pages ici veut dire « je
veux la vérité de ces deux pages-là », pas « le pipeline en aurait ouvert
deux ».

## Ce qui est partagé avec la production, et ce qui ne l'est pas

Il faut être précis, parce que la distinction porte toute la validité du banc.

**Partagé : la fonction.** `links_of` est importée d'ici telle quelle, avec ses
seuils et son plafond. C'est elle qu'on mesure, et c'est la raison pour
laquelle ce module tourne dans le worker plutôt que sur le site : réécrire
l'extraction en Node aurait donné la vérité de cette réécriture, et une vérité
de référence qui décrit autre chose que le code en production ne mesure rien.

**Pas partagé : l'orchestration.** `Harvest`, l'étage 3, fait davantage
qu'appeler `links_of` — il journalise, tient les compteurs du run, dédoublonne
entre pages, et surtout s'arrête dès que sa moisson suffit. Rien de tout cela
n'a sa place ici, et la boucle ci-dessous en est une seconde, délibérément plus
bête. On mesure la fonction, pas la brique.

Ce module n'a par ailleurs pas le droit de « corriger » quoi que ce soit au
passage : il appelle et rapporte, sans filtrer ni compléter. Compléter est le
travail de l'humain, dans la console.

## Ce qui reste partagé avec un run

Le `Fetcher`, donc `robots.txt` et le délai par hôte. Le banc lit de vraies
pages chez de vrais gens ; il n'a aucune raison d'être moins poli que le
scraper.

## L'archive

Chaque page part avec son HTML, gzippé. C'est ce qui fait du banc un **corpus
gelé** plutôt qu'un instantané : sans lui, rejouer la mesure après avoir touché
à `links_of` obligerait à retélécharger, donc à comparer un nouveau code à une
nouvelle page — et l'écart ne dirait plus lequel des deux a bougé.

Une page qu'on ne peut pas archiver est rapportée quand même, sans son HTML :
la mesure est le travail, l'archive est le confort du rejeu, et on ne perd pas
la première pour avoir manqué la seconde.
"""

from __future__ import annotations

import base64
import gzip
from typing import Any

from .classify import next_page
from .harvest import FetchError, Fetcher, links_of

#: Plafond de l'archive d'une page, en caractères de base64 — le même que celui
#: du site, qui refuserait au-delà. Un million de caractères font environ 750 ko
#: compressés, soit plusieurs mégaoctets de HTML : au-delà, la page est
#: pathologique et part sans son archive plutôt que de faire échouer tout le
#: compte rendu.
MAX_HTML_B64 = 1_000_000


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


def harvest_agenda(url: str, pages: int, fetcher: Fetcher | None = None) -> list[dict[str, Any]]:
    """Dépouille un agenda et ses pages suivantes. Une entrée par page demandée.

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
            out.append({"pageNo": page_no, "url": current, "chars": 0, "error": str(err), "links": []})
            break

        found = links_of(html, current)
        entry: dict[str, Any] = {
            "pageNo": page_no,
            "url": current,
            "chars": len(html),
            "links": [
                {"url": link.url, "text": link.text, "context": link.context} for link in found
            ],
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
