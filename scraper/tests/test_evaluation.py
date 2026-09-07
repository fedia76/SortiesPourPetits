"""Le relevé du banc, sur des pages figées.

Ce que ces tests protègent n'est pas `links_of` — il a les siens — mais le
contrat entre le banc et lui :

* **la précoche ne peut pas diverger de la production.** C'est l'invariant
  central : `harvested` vient de `links_of` lui-même, et un test le vérifie
  terme à terme. Si les deux divergeaient, le banc mesurerait une
  réimplémentation, c'est-à-dire rien ;
* tous les liens remontent, pas seulement la moisson — sinon on ne mesure que
  le rappel, et jamais le contraire ;
* une entrée par page demandée, dans l'ordre, sans dédoublonnage entre pages ;
* une page injoignable **remonte** au lieu de disparaître. Une page escamotée
  en silence fabrique un rappel de 100 % sur ce qu'il reste, ce qui est
  exactement le mensonge qu'on cherche à éviter.
"""

from __future__ import annotations

import pytest

from sortiesbot.evaluation import audit_links, harvest_agenda
from sortiesbot.harvest import links_of
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
    assert {link["url"] for link in out[0]["links"] if link["harvested"]} == {
        "https://agenda.exemple.fr/fiches/cirque",
        "https://agenda.exemple.fr/fiches/conte",
    }
    # Le contexte part avec le lien retenu : c'est là que vivent la date et le
    # lieu, et c'est ce que l'étage 4 recevra.
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

    # Les deux liens sont *relevés* — c'est tout l'intérêt du banc — mais un
    # seul est retenu par la brique, et l'autre porte son motif.
    par_url = {link["url"]: link for link in out[0]["links"]}
    assert par_url["https://agenda.exemple.fr/fiches/cirque"]["harvested"] is True
    manque = par_url["https://agenda.exemple.fr/fiches/peterpan"]
    assert manque["harvested"] is False
    assert manque["reason"] == "texte trop court"


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
    assert any(link["harvested"] for link in out[0]["links"])


# ═══════════════════════════════════ le relevé : tous les liens, et la précoche


#: Les intitulés sont longs à dessein. `_is_boring` teste la longueur du texte
#: **avant** le chemin : un « Accueil » de sept caractères serait écarté pour
#: « texte trop court », et le test ne dirait plus rien du motif qu'il vise.
NAV = (
    '<nav><a href="/">Retour à la page d\'accueil</a>'
    '<a href="/mentions-legales">Mentions légales du site</a>'
    '<a href="https://facebook.com/agenda">Retrouvez-nous sur Facebook</a></nav>'
)


def test_la_precoche_ne_peut_pas_diverger_de_la_production():
    """L'invariant central du banc, et le seul qui soit non négociable.

    `harvested` vient de `links_of` lui-même, pas d'une relecture de ses règles.
    Si les deux divergeaient, la console précocherait autre chose que ce que le
    pipeline fait, et le banc mesurerait une réimplémentation — c'est-à-dire
    rien du tout.
    """
    html = page(
        NAV
        + fiche("cirque", "Le cirque des petits")
        + fiche("peterpan", "Peter Pan")
        + fiche("conte", "Les contes du soir")
    )

    releve = audit_links(html, AGENDA)

    assert {link["url"] for link in releve if link["harvested"]} == {
        link.url for link in links_of(html, AGENDA)
    }


def test_tout_est_releve_pas_seulement_la_moisson():
    """C'est ce qui permet de mesurer les deux erreurs, pas seulement le rappel."""
    html = page(NAV + fiche("cirque", "Le cirque des petits"))

    releve = audit_links(html, AGENDA)
    urls = {link["url"] for link in releve}

    assert "https://agenda.exemple.fr/mentions-legales" in urls
    assert "https://facebook.com/agenda" in urls
    assert "https://agenda.exemple.fr/fiches/cirque" in urls
    assert sum(1 for link in releve if link["harvested"]) == 1


def test_chaque_rejet_porte_son_motif():
    """Les motifs rangent les rejets, et disent où les ratages se cachent.

    Ils ne décident de rien — `links_of` a déjà tranché — mais ils permettent à
    l'humain de filtrer : les fiches manquées se concentrent sous « texte trop
    court » et « hors domaine », jamais sous « chemin de service ».
    """
    html = page(NAV + fiche("peterpan", "Peter Pan"))

    par_url = {link["url"]: link for link in audit_links(html, AGENDA)}

    assert par_url["https://facebook.com/agenda"]["reason"] == "hors domaine"
    assert par_url["https://agenda.exemple.fr/fiches/peterpan"]["reason"] == "texte trop court"
    assert par_url["https://agenda.exemple.fr/"]["reason"] == "racine du site"
    assert par_url["https://agenda.exemple.fr/mentions-legales"]["reason"] == "chemin de service"


def test_les_ancres_pures_ne_sont_pas_relevees():
    """Elles ne mènent nulle part : il n'y a rien à étiqueter, et les montrer
    ferait lire deux cents lignes pour rien."""
    html = page(
        '<a href="#contenu">Aller au contenu principal</a>'
        '<a href="mailto:bonjour@exemple.fr">Nous écrire un courriel</a>'
        '<a href="javascript:void(0)">Ouvrir le menu de navigation</a>'
        + fiche("cirque", "Le cirque des petits")
    )

    assert [link["url"] for link in audit_links(html, AGENDA)] == [
        "https://agenda.exemple.fr/fiches/cirque"
    ]


def test_un_lien_repete_n_est_releve_qu_une_fois():
    """Le logo, « accueil » : les étiqueter trois fois ne mesurerait rien de plus."""
    accueil = '<a href="/agenda/tout-le-programme">Tout le programme</a>'
    html = page(accueil + fiche("cirque", "Le cirque des petits") + accueil)

    urls = [link["url"] for link in audit_links(html, AGENDA)]

    assert urls.count("https://agenda.exemple.fr/agenda/tout-le-programme") == 1


def test_le_contexte_accompagne_aussi_les_liens_ecartes():
    """Sans lui, les écartés sont injugeables — et c'est là qu'est le travail.

    Un lien rejeté pour « texte trop court » est, par définition, un lien dont
    l'intitulé ne dit rien. « Peter Pan » sur une URL opaque ne permet de
    trancher qu'en ouvrant la page ; le voisinage, lui, porte la date et le
    lieu. Une première version réservait le contexte aux liens retenus, au motif
    que c'est ce que l'étage 4 reçoit — l'argument était juste et la conséquence
    absurde : ici le contexte sert à l'humain, pas à l'étage 4.
    """
    html = page(NAV + fiche("peterpan", "Peter Pan"))

    par_url = {link["url"]: link for link in audit_links(html, AGENDA)}
    ecarte = par_url["https://agenda.exemple.fr/fiches/peterpan"]

    assert ecarte["harvested"] is False
    assert "3 mai" in ecarte["context"]
    assert "Rouen" in ecarte["context"]


def test_une_ancre_sans_texte_reste_jugeable_par_son_contexte():
    """Le cas le plus fréquent des vrais agendas : la carte est une image.

    L'ancre n'a aucun texte, `links_of` l'écarte pour « texte trop court », et
    la console n'aurait qu'une URL à montrer. Le contexte remonte la carte
    entière, et c'est ce qui rend la ligne jugeable.
    """
    html = page(
        '<article><a href="/fiches/affiche"><img src="/a.jpg"></a>'
        "<p>Le bal des marionnettes Dimanche 12 mai à Rouen, dès 3 ans</p></article>"
    )

    releve = audit_links(html, AGENDA)

    assert len(releve) == 1
    assert releve[0]["harvested"] is False
    assert "marionnettes" in releve[0]["context"]


def test_la_page_rapporte_ce_que_next_page_a_trouve():
    """La vérification de la pagination : ce que l'étage 3 saurait suivre.

    Comparé aux liens que l'humain étiquettera « pagination », c'est ce qui dit
    si un agenda se pagine d'une façon que le pipeline sait suivre — un site qui
    numérote ses pages sans `rel="next"` n'est jamais suivi, et rien
    aujourd'hui ne le signale.
    """
    p2 = "https://agenda.exemple.fr/sorties?page=2"
    fetcher = FakeFetcher(
        {AGENDA: page(fiche("un", "Spectacle numéro un"), next_url=p2), p2: page("")}
    )

    out = harvest_agenda(AGENDA, 2, fetcher=fetcher)

    assert out[0]["nextUrl"] == p2
    assert out[1]["nextUrl"] == ""


def test_une_pagination_numerotee_sans_rel_next_ne_remonte_rien():
    """Le cas que le banc existe pour attraper.

    La page offre visiblement une suite ; `next_page` ne la voit pas. L'humain
    étiquettera ces liens « pagination », et l'écart avec `nextUrl` vide dira
    que ce site-là n'est jamais paginé par le pipeline.
    """
    html = page(
        '<a href="/sorties?page=2">Page 2 des sorties</a>'
        '<a href="/sorties?page=3">Page 3 des sorties</a>'
        + fiche("un", "Spectacle numéro un")
    )
    fetcher = FakeFetcher({AGENDA: html})

    out = harvest_agenda(AGENDA, 3, fetcher=fetcher)

    assert out[0]["nextUrl"] == ""
    assert len(out) == 1
    # Les liens sont bien relevés : c'est l'humain qui dira que c'en est.
    assert "https://agenda.exemple.fr/sorties?page=2" in {
        link["url"] for link in out[0]["links"]
    }


def test_un_sous_agenda_est_releve_comme_les_autres():
    """La page à facettes — « voir aussi les sorties en château ».

    Le dépouillement la rend, la sélection l'écarte parce qu'on lui dit
    d'écarter les catégories, et les sorties qu'elle porte ne sont jamais
    atteintes. Le banc ne corrige pas ça : il le rend visible, ce qui est le
    premier pas.
    """
    html = page(
        '<a href="/sorties/en-chateau">Voir aussi les sorties en château</a>'
        + fiche("cirque", "Le cirque des petits")
    )

    par_url = {link["url"]: link for link in audit_links(html, AGENDA)}
    facette = par_url["https://agenda.exemple.fr/sorties/en-chateau"]

    # Retenue par le dépouillement, donc précochée « sortie » — et c'est
    # justement l'erreur que l'humain vient corriger en « sous-agenda ».
    assert facette["harvested"] is True


def test_le_releve_est_plafonne():
    from sortiesbot.evaluation import MAX_AUDIT_LINKS

    liens = "".join(
        f'<a href="/rubrique-numero-{i}">Rubrique numéro {i} du site</a>'
        for i in range(MAX_AUDIT_LINKS + 50)
    )

    assert len(audit_links(page(liens), AGENDA)) == MAX_AUDIT_LINKS
