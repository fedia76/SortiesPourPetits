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

from dataclasses import replace

import pytest

from sortiesbot.evaluation import audit_fiche, audit_links, extract_page, fiche_payload, harvest_agenda
from sortiesbot.harvest import links_of
from sortiesbot.harvest import FetchError
from sortiesbot.models import ExtractedEvent

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


# ═════════════════════════════════════════════ étage 5 — la lecture d'une page


from sortiesbot.evaluation import read_page  # noqa: E402

FICHE = "https://theatre.exemple.fr/saison/le-petit-prince"


def fiche_page(corps: str, tete: str = "") -> str:
    return f"<html><head><title>Le Petit Prince</title>{tete}</head><body>{corps}</body></html>"


CORPS = (
    "<main><h1>Le Petit Prince</h1>"
    "<p>Un spectacle de marionnettes pour les enfants dès quatre ans, joué au "
    "Théâtre du Chapiteau à Rouen. La séance dure cinquante minutes et se termine "
    "par une rencontre avec les marionnettistes. Tarif unique de huit euros, "
    "réservation conseillée auprès de la billetterie du théâtre.</p></main>"
)


def test_la_lecture_rend_ce_que_la_brique_rend():
    fetcher = FakeFetcher({FICHE: fiche_page(CORPS)})

    out = read_page(FICHE, fetcher=fetcher)

    assert "marionnettes" in out["text"]
    assert out["heading"] == "Le Petit Prince"
    assert out["h1InText"] is True
    assert out["truncated"] is False
    assert out["tooShort"] is False


def test_un_titre_dans_un_header_disparait_et_le_signal_le_dit():
    """Le ratage le plus fréquent de l'étage 5, et le plus discret.

    `page_text` décape `nav header footer aside form`. Beaucoup de gabarits
    mettent le titre et les dates dans un `<header>` : ils partent avec, le
    texte reste non vide, et c'est l'extraction qu'on ira accuser de rendre une
    fiche sans date.
    """
    # Le titre et les dates sont dans le `<header>`, et nulle part ailleurs —
    # c'est le gabarit courant, et c'est ce qui rend la perte invisible.
    #
    # Le `<title>` du document porte autre chose, et ce n'est pas un détail :
    # `page_text` prend le texte du document **entier**, `<head>` compris, donc
    # un `<title>` identique au `h1` masquerait la perte à lui seul.
    html = (
        "<html><head><title>Théâtre du Chapiteau — saison</title></head><body>"
        "<header><h1>Le Petit Prince</h1><p>Samedi 3 mai à 15h, Rouen</p></header>"
        + CORPS.replace("<h1>Le Petit Prince</h1>", "")
        + "</body></html>"
    )
    fetcher = FakeFetcher({FICHE: html})

    out = read_page(FICHE, fetcher=fetcher)

    # Le texte survit — c'est bien le problème : rien ne proteste, et la page
    # passe même le seuil qui l'aurait sauvée en l'écartant.
    assert out["tooShort"] is False
    assert "Samedi 3 mai" not in out["text"]
    assert out["heading"] == "Le Petit Prince"
    assert out["h1InText"] is False


def test_une_page_sous_le_seuil_serait_abandonnee():
    """Le ratage le plus cher : la page est écartée avant tout appel payant."""
    fetcher = FakeFetcher({FICHE: fiche_page("<main><p>Bientôt.</p></main>")})

    out = read_page(FICHE, fetcher=fetcher)

    assert out["tooShort"] is True


def test_les_dates_json_ld_remontent_telles_que_la_brique_les_lit():
    ld = (
        '<script type="application/ld+json">'
        '{"@type":"Event","name":"Le Petit Prince","startDate":"2026-05-03T15:00",'
        '"endDate":"2026-05-03T16:00"}</script>'
    )
    fetcher = FakeFetcher({FICHE: fiche_page(CORPS, tete=ld)})

    out = read_page(FICHE, fetcher=fetcher)

    assert out["dates"] == ["2026-05-03T15:00"]


def test_une_illustration_qui_ressemble_a_un_logo_est_signalee():
    """Le signal ne décide de rien : `main_image` a déjà tranché, et c'est son
    choix qu'on mesure. Il dit seulement à l'humain où regarder."""
    tete = '<meta property="og:image" content="https://theatre.exemple.fr/img/logo-site.png">'
    fetcher = FakeFetcher({FICHE: fiche_page(CORPS, tete=tete)})

    out = read_page(FICHE, fetcher=fetcher)

    assert out["imageUrl"].endswith("logo-site.png")
    assert out["imageLooksLogo"] is True


def test_une_page_injoignable_remonte_son_motif_et_rien_d_autre():
    out = read_page(FICHE, fetcher=FakeFetcher({}))

    assert "inaccessible" in out["error"]
    assert "text" not in out


def test_l_echange_de_langue_est_rejoue():
    """C'est lui qui décide quelle page est lue : l'oublier ferait mesurer une
    autre page que celle que le pipeline aurait choisie."""
    en = "https://theatre.exemple.fr/en/season/the-little-prince"
    fr = "https://theatre.exemple.fr/saison/le-petit-prince"
    anglais = (
        '<html lang="en"><head><title>The Little Prince</title>'
        f'<link rel="alternate" hreflang="fr" href="{fr}">'
        "</head><body><main><p>A puppet show for children.</p></main></body></html>"
    )
    fetcher = FakeFetcher({en: anglais, fr: fiche_page(CORPS)})

    out = read_page(en, fetcher=fetcher)

    assert out["url"] == fr
    assert out["swapped"] is True
    assert "marionnettes" in out["text"]


# ═══════════════════════════════════ étage 6 — les instruments de l'extraction

#: Une page de spectacle, telle que l'étage 5 la rendrait. Tout ce que la fiche
#: de référence prétend s'y trouve, et rien d'autre : c'est ce qui permet aux
#: tests d'invention d'être des tests, et pas des coïncidences.
PAGE = (
    "Le Petit Prince — spectacle de marionnettes pour enfants au théâtre "
    "municipal de Rouen. Du 3 août au 23 août 2026, tous les mercredis à 14h30. "
    "Tarif : 8 €, à partir de 3 ans et jusqu'à 10 ans. "
    "Théâtre municipal, 12 rue des Arts, 76000 Rouen."
)

JUSTE = ExtractedEvent(
    relevant=True,
    title="Le Petit Prince",
    description="Un spectacle de marionnettes pour enfants au théâtre municipal de Rouen.",
    price=8.0,
    age_min=3,
    age_max=10,
    date_start="2026-08-03",
    date_end="2026-08-23",
    weekdays=("mercredi",),
    open_time="14:30",
    setting="INDOOR",
    category="Spectacle",
    venue_name="Théâtre municipal",
    venue_address="12 rue des Arts",
    venue_city="Rouen",
    venue_postal_code="76000",
)


def flags(event: ExtractedEvent, key: str, **kwargs) -> list[str]:
    """Les drapeaux levés sur un aspect. Le raccourci de tous les tests d'après."""
    aspects = {a["key"]: a for a in audit_fiche(event, PAGE, **kwargs)}
    return aspects[key]["flags"]


def test_une_fiche_entierement_ancree_ne_leve_aucun_drapeau():
    """Le test qui garde les instruments honnêtes.

    Un ancrage trop strict crierait à l'invention sur une fiche juste, et la
    console se remplirait de rouge que personne ne regarderait plus — un
    détecteur qui sonne toujours ne détecte rien.
    """
    assert all(not a["flags"] for a in audit_fiche(JUSTE, PAGE, categories=["Spectacle"]))


def test_les_douze_aspects_sont_tous_rendus_meme_vides():
    """Un aspect absent du relevé serait un champ que personne ne jugerait jamais,
    et son taux ne serait pas « inconnu » mais **absent** — donc invisible."""
    keys = [a["key"] for a in audit_fiche(ExtractedEvent(relevant=True), PAGE)]

    assert keys == [
        "verdict", "titre", "description", "tarif", "age", "dates",
        "jours", "horaires", "cadre", "categorie", "lieu", "adresse",
    ]


def test_un_tarif_absent_de_la_page_est_signale():
    assert flags(replace(JUSTE, price=12.0), "tarif") == ["hors_texte"]


def test_un_nombre_nu_ne_suffit_pas_a_ancrer_un_tarif():
    """« 3 » est dans la page — c'est l'âge minimum. Un tarif de 3 € n'y est pas.

    C'est tout le sujet de l'ancrage d'un nombre : sans le voisinage d'une
    monnaie, n'importe quel texte assez long ancre n'importe quel petit entier,
    et l'instrument ne dirait plus rien.
    """
    assert flags(replace(JUSTE, price=3.0), "tarif") == ["hors_texte"]


def test_une_gratuite_inventee_est_signalee():
    """Rien n'oblige un modèle à écrire un nombre pour inventer un tarif : dire
    « c'est gratuit » d'une page qui affiche 8 € est la même faute."""
    assert flags(replace(JUSTE, free=True, price=None), "tarif") == ["hors_texte"]


def test_un_age_minimum_au_dessus_du_maximum_est_incoherent():
    """La cohérence ne demande pas de lire la page : la fiche se contredit seule."""
    assert "incoherent" in flags(replace(JUSTE, age_min=14, age_max=6), "age")


def test_un_age_ecrit_autrement_dans_la_page_reste_ancre():
    """« à partir de 5 » et « 5 ans » sont deux façons de dire la même chose.

    N'en reconnaître qu'une ferait signaler des âges correctement lus, et
    l'instrument coûterait plus de vérifications qu'il n'en épargne. Noter que la
    page n'écrit « ans » que pour le maximum : c'est le cas courant.
    """
    page = "Spectacle pour les enfants à partir de 5 et jusqu'à 12 ans."
    event = ExtractedEvent(relevant=True, age_min=5, age_max=12)

    aspects = {a["key"]: a for a in audit_fiche(event, page)}
    assert aspects["age"]["flags"] == []


def test_une_date_ecrite_en_toutes_lettres_est_ancree():
    """Une page française écrit « 3 août », pas « 2026-08-03 ». Ne chercher que
    la forme ISO ferait déclarer inventée toute date correctement lue."""
    assert flags(JUSTE, "dates") == []


def test_la_regle_du_jusqu_au_n_est_pas_comptee_comme_une_invention():
    """Le prompt impose de mettre *aujourd'hui* en date de début quand la page
    n'annonce qu'une fin. Cette date-là n'est donc pas dans la page, et c'est
    réglementaire : la signaler accuserait le modèle d'avoir suivi sa consigne."""
    page = "Exposition Dinosaures, à l'affiche jusqu'au 23 octobre 2026."
    event = ExtractedEvent(relevant=True, date_start="2026-09-09", date_end="2026-10-23")

    aspects = {a["key"]: a for a in audit_fiche(event, page)}
    assert aspects["dates"]["flags"] == []


def test_des_dates_qui_ne_rencontrent_pas_le_json_ld_sont_signalees():
    """Deux lectures indépendantes de la même page qui se contredisent : l'une
    des deux se trompe, et il faut un humain pour dire laquelle."""
    assert "divergent" in flags(JUSTE, "dates", declared_dates=["2026-12-25T14:30"])


def test_le_json_ld_qui_tombe_dans_la_plage_ne_signale_rien():
    assert flags(JUSTE, "dates", declared_dates=["2026-08-05T14:30"]) == []


def test_une_categorie_hors_du_referentiel_est_signalee():
    """Le prompt impose de choisir dans la liste du site. Un référentiel se
    vérifie sans humain, et c'est le seul aspect dont l'instrument est exact."""
    assert flags(JUSTE, "categorie", categories=["Musée", "Balade"]) == ["hors_liste"]


def test_le_cadre_n_a_aucun_instrument_et_c_est_dit():
    """Intérieur ou extérieur ne s'ancre pas : une page dit « au parc de la
    Villette » et c'est le lecteur qui conclut. Le banc l'annonce plutôt que
    d'imaginer une heuristique qui donnerait l'illusion d'une mesure."""
    aspects = {a["key"]: a for a in audit_fiche(replace(JUSTE, setting="OUTDOOR"), PAGE)}

    assert aspects["cadre"]["instrument"] == "aucun"
    assert aspects["cadre"]["flags"] == []
    assert aspects["cadre"]["value"] == "extérieur"


def test_un_champ_vide_ne_porte_jamais_de_drapeau():
    """Il n'y a rien à ancrer dans le vide. Un drapeau y voudrait dire « la page
    en parle », et ça, aucun instrument ne sait le dire — c'est très exactement
    ce que l'humain apporte, et le taux de couverture qui en dépend."""
    vide = ExtractedEvent(relevant=True)

    assert all(not a["flags"] for a in audit_fiche(vide, PAGE) if not a["filled"])


def test_un_refus_sans_motif_est_incoherent():
    """Le prompt demande d'expliquer pourquoi dans `skip_reason`. Une page
    écartée sans motif ne coûte rien, ne se voit nulle part, et fait disparaître
    une sortie sans laisser de trace."""
    assert flags(ExtractedEvent(relevant=False), "verdict") == ["incoherent"]


def test_la_fiche_part_entiere_meme_les_champs_que_personne_ne_juge():
    """C'est la pièce à conviction : une mesure dont on ne peut plus relire
    l'objet n'est pas vérifiable."""
    payload = fiche_payload(JUSTE)

    assert payload["venuePostalCode"] == "76000"
    assert payload["ageMin"] == 3
    assert payload["weekdays"] == ["mercredi"]
    assert payload["skipReason"] == ""


class FakeProvider:
    """Un fournisseur qui rend la fiche qu'on lui donne, sans appeler personne."""

    def __init__(self, event: ExtractedEvent):
        self.event = event
        self.seen: dict[str, object] = {}
        self.usage = type("U", (), {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})()

    def extract(self, url, content, config, categories, log, *, multiple=False):
        self.seen = {"url": url, "content": content, "multiple": multiple}
        self.usage.input_tokens = 2130
        self.usage.output_tokens = 410
        self.usage.cost_usd = 0.0031
        return [self.event]


class FakeConfig:
    extraction_model = "modele-de-test"


def test_l_extraction_est_rejouee_sur_le_texte_gele_jamais_sur_la_page():
    """L'entrée de cet étage est la sortie du précédent.

    C'est ce qui rend les deux mesures séparables : une fiche sans tarif dirait
    aussi bien « le modèle ne l'a pas vu » que « l'étage 5 l'avait déjà emporté
    avec un `<aside>` ». En partant du texte archivé, l'entrée est acquise.
    """
    provider = FakeProvider(JUSTE)

    out = extract_page(
        "https://theatre.exemple.fr/le-petit-prince",
        PAGE,
        provider=provider,
        config=FakeConfig(),
        log=None,
        categories=["Spectacle"],
    )

    assert provider.seen["content"] == PAGE
    assert provider.seen["multiple"] is False
    assert out["model"] == "modele-de-test"
    assert out["fiche"]["title"] == "Le Petit Prince"
    assert len(out["aspects"]) == 12
    assert out["inputTokens"] == 2130
    assert out["costUsd"] == 0.0031


def test_un_appel_en_echec_remonte_son_motif_et_rien_d_autre():
    class Cassé(FakeProvider):
        def extract(self, *a, **kw):
            raise RuntimeError("quota dépassé")

    out = extract_page(
        "https://exemple.fr/x", PAGE, provider=Cassé(JUSTE), config=FakeConfig(), log=None
    )

    assert "quota dépassé" in out["error"]
    assert "aspects" not in out
