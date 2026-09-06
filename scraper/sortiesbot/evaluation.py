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

## Pourquoi ça tourne ici et pas côté site

Parce que c'est le **vrai** `links_of` qu'il faut interroger. Une extraction
réécrite en Node donnerait la vérité de cette réécriture, et une vérité de
référence qui décrit autre chose que le code en production ne mesure rien.
C'est aussi pourquoi ce module n'a pas le droit de « corriger » quoi que ce
soit au passage : il appelle la fonction et rapporte, sans filtrer ni
compléter. Compléter, c'est le travail de l'humain, dans la console.

## Ce qui reste partagé avec un run

Le `Fetcher`, donc `robots.txt` et le délai par hôte. Le banc lit de vraies
pages chez de vrais gens ; il n'a aucune raison d'être moins poli que le
scraper.
"""

from __future__ import annotations

from typing import Any

from .classify import next_page
from .harvest import FetchError, Fetcher, links_of


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
        out.append(
            {
                "pageNo": page_no,
                "url": current,
                "chars": len(html),
                "links": [
                    {"url": link.url, "text": link.text, "context": link.context} for link in found
                ],
            }
        )

    if not out:
        # Défensif : `pages` est validé côté site, mais un agenda sans la
        # moindre entrée laisserait la console incapable de dire ce qui s'est
        # passé — et le compte rendu serait refusé.
        out.append({"pageNo": 1, "url": url, "chars": 0, "error": "aucune page lue", "links": []})
    return out
