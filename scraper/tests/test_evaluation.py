"""Le dépouillement du banc, sur des pages figées.

Ce que ces tests protègent n'est pas `links_of` — il a les siens — mais le
contrat entre le banc et lui : une entrée par page demandée, dans l'ordre,
sans dédoublonnage d'une page à l'autre, et une page injoignable qui **remonte**
au lieu de disparaître.

Ce dernier point est le seul qui compte vraiment. Le banc sert à mesurer un
rappel ; une page qu'on laisse tomber en silence fabrique un rappel de 100 %
sur ce qu'il reste, ce qui est exactement le mensonge qu'on cherche à éviter.
"""

from __future__ import annotations

import pytest

from sortiesbot.evaluation import harvest_agenda
from sortiesbot.harvest import FetchError

AGENDA = "https://agenda.exemple.fr/sorties"


def page(links: str, next_url: str = "") -> str:
    suivant = f'<link rel="next" href="{next_url}">' if next_url else ""
    return f"<html><head>{suivant}</head><body>{links}</body></html>"


def fiche(slug: str, titre: str) -> str:
    """Une carte d'agenda : le lien, et autour de lui la date, le lieu, le tarif.

    Le voisinage est étoffé exprès. `_context_of` ne remonte le contexte que
    s'il apporte au moins vingt caractères de plus que l'ancre — une carte
    réduite au seul titre ne rendrait que le titre, et le test ne dirait plus
    rien de ce que l'étage 4 reçoit réellement.
    """
    return (
        f'<article><a href="/fiches/{slug}">{titre}</a>'
        f"<p>Samedi 3 mai 2026 à Rouen, dès 4 ans, entrée 6 €</p></article>"
    )


class FakeFetcher:
    """Rend le HTML qu'on lui a donné, et lève sur ce qu'il ne connaît pas."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.asked: list[str] = []

    def get_html(self, url: str) -> str:
        self.asked.append(url)
        if url not in self.pages:
            raise FetchError("page inaccessible (ConnectionError)")
        return self.pages[url]


def test_une_seule_page_demandee_une_seule_page_lue():
    html = page(fiche("cirque", "Le cirque des petits") + fiche("conte", "Les contes du soir"))
    fetcher = FakeFetcher({AGENDA: html})

    out = harvest_agenda(AGENDA, 1, fetcher=fetcher)

    assert len(out) == 1
    assert out[0]["pageNo"] == 1
    assert out[0]["url"] == AGENDA
    assert out[0]["chars"] == len(html)
    assert {link["url"] for link in out[0]["links"]} == {
        "https://agenda.exemple.fr/fiches/cirque",
        "https://agenda.exemple.fr/fiches/conte",
    }
    # Le contexte part avec le lien : c'est là que vivent la date et le lieu,
    # et c'est ce que l'étage 4 recevra.
    assert "3 mai" in out[0]["links"][0]["context"]


def test_un_titre_trop_court_ne_ressort_pas_et_c_est_le_sujet_du_banc():
    """`MIN_TEXT = 15` : « Peter Pan » ne passe pas, « Le cirque des petits » si.

    Ce test ne dénonce pas un bug — le seuil est délibéré, il écarte du bruit
    de navigation. Il fige le fait que le seuil **coûte des fiches**, et donc
    ce qu'un humain aura à rattraper dans la console. C'est très exactement la
    mesure que le banc rend possible : sans elle, cette perte-là ne se voit
    nulle part, le run se termine normalement, et c'est le prompt de la
    sélection qu'on ira accuser.
    """
    fetcher = FakeFetcher(
        {AGENDA: page(fiche("peterpan", "Peter Pan") + fiche("cirque", "Le cirque des petits"))}
    )

    out = harvest_agenda(AGENDA, 1, fetcher=fetcher)

    urls = {link["url"] for link in out[0]["links"]}
    assert "https://agenda.exemple.fr/fiches/cirque" in urls
    assert "https://agenda.exemple.fr/fiches/peterpan" not in urls


def test_la_pagination_est_suivie_jusqu_au_nombre_demande():
    p2 = "https://agenda.exemple.fr/sorties?page=2"
    p3 = "https://agenda.exemple.fr/sorties?page=3"
    fetcher = FakeFetcher(
        {
            AGENDA: page(fiche("un", "Spectacle numéro un"), next_url=p2),
            p2: page(fiche("deux", "Spectacle numéro deux"), next_url=p3),
            p3: page(fiche("trois", "Spectacle numéro trois")),
        }
    )

    out = harvest_agenda(AGENDA, 2, fetcher=fetcher)

    # Deux pages demandées, deux pages lues : la troisième existe et n'est pas
    # ouverte. Le banc fixe son nombre de pages, il ne l'arbitre pas.
    assert [entry["pageNo"] for entry in out] == [1, 2]
    assert [entry["url"] for entry in out] == [AGENDA, p2]
    assert fetcher.asked == [AGENDA, p2]


def test_un_lien_present_sur_deux_pages_compte_deux_fois():
    """Pas de dédoublonnage entre pages : `links_of` travaille page par page.

    Fusionner ferait disparaître la moitié du travail qu'on cherche à noter —
    et laisserait croire que la page 2 n'a rien donné.
    """
    p2 = "https://agenda.exemple.fr/sorties?page=2"
    commun = fiche("commun", "La sortie qui revient")
    fetcher = FakeFetcher({AGENDA: page(commun, next_url=p2), p2: page(commun)})

    out = harvest_agenda(AGENDA, 2, fetcher=fetcher)

    assert len(out) == 2
    assert out[0]["links"][0]["url"] == out[1]["links"][0]["url"]


def test_sans_rel_next_on_s_arrete_meme_si_on_demandait_plus():
    fetcher = FakeFetcher({AGENDA: page(fiche("seul", "Un spectacle isolé"))})

    out = harvest_agenda(AGENDA, 5, fetcher=fetcher)

    # On ne reconstruit jamais « page 2 » : ce serait inventer une URL.
    assert len(out) == 1
    assert fetcher.asked == [AGENDA]


def test_une_page_injoignable_remonte_avec_son_motif():
    """Le point qui compte : elle est rapportée, pas escamotée."""
    fetcher = FakeFetcher({})

    out = harvest_agenda(AGENDA, 1, fetcher=fetcher)

    assert len(out) == 1
    assert out[0]["links"] == []
    assert out[0]["chars"] == 0
    assert "inaccessible" in out[0]["error"]


def test_une_page_suivante_injoignable_n_efface_pas_la_premiere():
    p2 = "https://agenda.exemple.fr/sorties?page=2"
    fetcher = FakeFetcher({AGENDA: page(fiche("un", "Spectacle numéro un"), next_url=p2)})

    out = harvest_agenda(AGENDA, 3, fetcher=fetcher)

    assert len(out) == 2
    assert out[0]["links"] and not out[0].get("error")
    assert out[1]["pageNo"] == 2 and out[1]["error"]


def test_une_page_qui_se_declare_sa_propre_suite_ne_boucle_pas():
    fetcher = FakeFetcher({AGENDA: page(fiche("un", "Spectacle numéro un"), next_url=AGENDA)})

    out = harvest_agenda(AGENDA, 4, fetcher=fetcher)

    assert len(out) == 1


@pytest.mark.parametrize("demande", [0, -3])
def test_un_nombre_de_pages_absurde_en_lit_quand_meme_une(demande: int):
    """Le site valide déjà l'entrée ; le module ne rend jamais zéro page.

    Un compte rendu vide serait refusé par l'API et l'agenda resterait
    « en cours » — un garde-fou de plus vaut mieux qu'un agenda figé.
    """
    fetcher = FakeFetcher({AGENDA: page(fiche("un", "Spectacle numéro un"))})

    out = harvest_agenda(AGENDA, demande, fetcher=fetcher)

    assert len(out) == 1


def test_le_html_part_avec_la_page_et_se_relit():
    """L'archive : c'est elle qui fait du banc un corpus gelé.

    Sans elle, rejouer la mesure après avoir touché à `links_of` obligerait à
    retélécharger — donc à comparer un nouveau code à une nouvelle page, et
    l'écart ne dirait plus lequel des deux a bougé.
    """
    import base64
    import gzip

    html = page(fiche("un", "Spectacle numéro un"))
    fetcher = FakeFetcher({AGENDA: html})

    out = harvest_agenda(AGENDA, 1, fetcher=fetcher)

    assert gzip.decompress(base64.b64decode(out[0]["html"])).decode("utf-8") == html


def test_une_page_injoignable_n_emporte_aucune_archive():
    fetcher = FakeFetcher({})

    out = harvest_agenda(AGENDA, 1, fetcher=fetcher)

    assert "html" not in out[0]


def test_une_page_demesuree_est_rapportee_sans_son_archive(monkeypatch):
    """La mesure est le travail, l'archive est le confort du rejeu.

    On ne perd pas la première pour avoir manqué la seconde : la page remonte
    avec ses liens, simplement privée de rejeu hors ligne.
    """
    from sortiesbot import evaluation

    monkeypatch.setattr(evaluation, "MAX_HTML_B64", 1)
    fetcher = FakeFetcher({AGENDA: page(fiche("un", "Spectacle numéro un"))})

    out = harvest_agenda(AGENDA, 1, fetcher=fetcher)

    assert "html" not in out[0]
    assert len(out[0]["links"]) == 1
