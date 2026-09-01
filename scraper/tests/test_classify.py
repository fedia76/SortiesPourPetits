"""Le classifieur en observation : ce qu'il constate, et ce qu'il refuse de dire.

Trois choses se vérifient ici, et la troisième est la plus importante :

* qu'il reconnaît une liste et une fiche quand le site le déclare ;
* qu'une pièce jouée douze fois reste **une** sortie — le piège que
  `harvest.json_ld_dates` documente déjà, un `Event` par représentation ;
* qu'il répond « inconnu » plutôt que de trancher au hasard. C'est ce qui
  autorise l'orchestrateur à garder son filet : dans le doute, agenda.

Le comptage de liens a été un troisième signal, et vingt-sept pages réelles
l'ont enterré : les deux populations se recouvrent complètement (voir l'en-tête
de `classify.py`). Les tests qui l'exerçaient sont devenus des tests
d'abstention — c'est bien le comportement qu'on veut verrouiller, pour que
personne ne le réintroduise sans mesure.
"""

from __future__ import annotations

import json

from sortiesbot.classify import AGENDA, INCONNU, SORTIE, classify, digest
from sortiesbot.harvest import links_of

URL = "https://exemple.fr/page"


def page(body: str, head: str = "") -> str:
    return f"<html><head>{head}</head><body>{body}</body></html>"


def ld(payload: object) -> str:
    return f'<script type="application/ld+json">{json.dumps(payload)}</script>'


def liens(nombre: int, prefixe: str = "spectacle") -> str:
    """Des liens que `links_of` gardera : internes, longs, hors chemins de service."""
    return "".join(
        f'<a href="/{prefixe}/numero-{i}">Un titre de sortie bien assez long {i}</a>'
        for i in range(nombre)
    )


# ------------------------------------------------------- ce que le site déclare


def test_un_seul_evenement_declare_est_une_sortie():
    html = page(ld({"@type": "Event", "name": "Le Petit Prince", "startDate": "2026-09-12"}))
    verdict = classify(html, URL)
    assert (verdict.kind, verdict.signal, verdict.confidence) == (SORTIE, "json-ld", "certain")


def test_un_spectacle_joue_douze_fois_reste_une_sortie():
    """Le piège : un `Event` par représentation. Ce sont des dates, pas des sorties."""
    seances = [
        {"@type": "Event", "name": "Le Petit Prince", "startDate": f"2026-09-{jour:02d}"}
        for jour in range(12, 24)
    ]
    verdict = classify(page(ld(seances)), URL)
    assert verdict.kind == SORTIE
    assert "12 représentation(s)" in verdict.detail


def test_plusieurs_titres_distincts_font_un_agenda():
    spectacles = [
        {"@type": "Event", "name": titre, "startDate": "2026-09-12"}
        for titre in ("Le Petit Prince", "Pierre et le Loup", "Boucle d'or")
    ]
    verdict = classify(page(ld(spectacles)), URL)
    assert (verdict.kind, verdict.confidence) == (AGENDA, "certain")


def test_deux_titres_ne_suffisent_pas_a_faire_un_agenda():
    """Une fiche annonce souvent la séance scolaire à côté de la tout public."""
    seances = [
        {"@type": "Event", "name": "Le Petit Prince", "startDate": "2026-09-12"},
        {"@type": "Event", "name": "Le Petit Prince — séance scolaire", "startDate": "2026-09-13"},
    ]
    # Deux titres : le JSON-LD ne tranche pas, et rien d'autre ne le fera.
    assert classify(page(ld(seances) + liens(2)), URL).kind == INCONNU


def test_une_liste_declaree_est_un_agenda():
    catalogue = {
        "@type": "ItemList",
        "itemListElement": [
            {"@type": "Event", "name": "Le Petit Prince", "startDate": "2026-09-12"},
            {"@type": "Event", "name": "Pierre et le Loup", "startDate": "2026-09-13"},
        ],
    }
    assert classify(page(ld(catalogue)), URL).kind == AGENDA


def test_un_json_ld_illisible_ne_fait_pas_echouer_le_classement():
    html = page('<script type="application/ld+json">{ pas du json</script>' + liens(20))
    assert classify(html, URL).kind == INCONNU


def test_opengraph_event_designe_une_sortie():
    html = page(liens(6), head='<meta property="og:type" content="event">')
    verdict = classify(html, URL)
    assert (verdict.kind, verdict.signal) == (SORTIE, "opengraph")


def test_un_og_type_dans_le_corps_de_page_ne_compte_pas():
    """Seule l'en-tête déclare ; plus bas, c'est du texte qui parle d'`og:type`."""
    corps = "x" * 9000 + '<meta property="og:type" content="event">'
    assert classify(page(corps), URL).kind == INCONNU


# ------------------------------------------------- ce qu'on refuse de deviner


def test_beaucoup_de_liens_ne_font_pas_un_agenda():
    """Enterré par la mesure : `parismomes` rend dix liens sur toutes ses pages.

    Le compte reste relevé — il part au registre — mais il ne décide plus rien.
    """
    verdict = classify(page(liens(30)), URL)
    assert (verdict.kind, verdict.signal) == (INCONNU, "aucun")
    assert "30 liens relevés" in verdict.detail


def test_une_page_qui_ne_mene_nulle_part_nest_pas_pour_autant_une_sortie():
    """`sortiraparis` rend deux cents liens sur une fiche unique. Symétrique."""
    assert classify(page("<h1>Le Petit Prince</h1>" + liens(2)), URL).kind == INCONNU


def test_les_liens_deja_comptes_ne_sont_pas_recomptes():
    """Le dépouillement a déjà la liste : lui refaire lire le HTML serait bête."""
    verdict = classify(page("<p>rien</p>"), URL, links=40)
    assert "40 liens relevés" in verdict.detail


# --------------------------------------------------------------- la confrontation


def test_l_accord_avec_la_decouverte_se_lit_en_trois_etats():
    catalogue = [
        {"@type": "Event", "name": titre, "startDate": "2026-09-12"}
        for titre in ("Le Petit Prince", "Pierre et le Loup", "Boucle d'or")
    ]
    verdict = classify(page(ld(catalogue)), URL)
    assert verdict.agrees_with("agenda") is True
    assert verdict.agrees_with("sortie") is False
    # Rien d'annoncé : il n'y a rien à comparer, ce n'est pas un désaccord.
    assert verdict.agrees_with("") is None


def test_un_verdict_inconnu_ne_contredit_personne():
    verdict = classify(page(liens(6)), URL)
    assert verdict.kind == INCONNU
    assert verdict.agrees_with("agenda") is None


# ═══════════════════════════════════════════════════ ce que l'URL seule dit


def test_une_page_paginee_est_une_liste():
    """Pas une heuristique de gabarit : la sémantique d'un paramètre."""
    verdict = classify(page(liens(1)), "https://x.fr/agenda?page=2")
    assert (verdict.kind, verdict.signal, verdict.confidence) == (AGENDA, "url", "certain")


def test_un_chemin_pagine_aussi():
    assert classify(page(""), "https://x.fr/sorties/page/3").kind == AGENDA


def test_une_recherche_ou_un_filtre_aussi():
    for query in ("search=cirque", "filter[]=jeune-public", "tag=famille", "s=noel"):
        assert classify(page(""), f"https://x.fr/a?{query}").kind == AGENDA, query


def test_un_parametre_de_suivi_ne_dit_rien():
    """`utm_source` n'est pas une pagination : une fiche partagée en porte."""
    assert classify(page(""), "https://x.fr/spectacle?utm_source=newsletter").kind == INCONNU


def test_le_chemin_seul_ne_decide_jamais():
    """Deux domaines sur sept servent agendas et fiches sous le même segment.

    `/agenda/`, `/sorties/`, `/que-faire/` reviendraient à apprendre le gabarit
    de chaque site — et à ne rien savoir de celui qu'on n'a jamais vu.
    """
    for url in ("https://x.fr/agenda/le-petit-prince", "https://x.fr/que-faire/ce-week-end"):
        assert classify(page(""), url).kind == INCONNU, url


# ══════════════════════════════════════════════════════════════ le condensé


def agenda_html() -> str:
    cartes = "".join(
        f'<article><a href="/e/{i}">Un spectacle jeune public numéro {i}</a>'
        f"<p>Samedi {i + 1} septembre 2026 — Théâtre de la Ville</p></article>"
        for i in range(12)
    )
    return f"<html><head><title>Que faire ce week-end</title></head><body>" \
           f"<h1>Que faire en famille</h1><p>Notre sélection du mois.</p>{cartes}</body></html>"


def test_le_condense_compte_les_liens_qui_voisinent_une_date():
    """Le trait le plus prometteur : un agenda mène à des choses datées."""
    url = "https://x.fr/agenda/"
    card = digest(agenda_html(), url, links_of(agenda_html(), url))
    assert card.links == 12 and card.dated == 12
    assert card.heading == "Que faire en famille"
    assert card.title == "Que faire ce week-end"


def test_une_fiche_ne_voisine_aucune_date():
    html = page(
        '<h1>Le Petit Prince</h1><p>Un spectacle tendre.</p>'
        '<a href="/autre-spectacle">Vous aimerez aussi : Pierre et le Loup</a>'
    )
    card = digest(html, "https://x.fr/le-petit-prince")
    assert (card.links, card.dated) == (1, 0)


def test_le_condense_ne_traine_ni_le_titre_ni_le_bandeau_de_cookies():
    """Trois cents caractères : quarante de « nous utilisons des cookies » sont
    quarante de perdus, et le titre répété n'apprend rien de plus."""
    html = (
        "<html><head><title>Mon Théâtre</title></head><body>"
        '<div class="cookie-banner">Nous utilisons des cookies. J\'accepte</div>'
        "<h1>Le Petit Prince</h1><p>Un spectacle tendre et musical.</p></body></html>"
    )
    card = digest(html, "https://x.fr/a")
    assert card.opening.startswith("Le Petit Prince")
    assert "cookies" not in card.opening
    assert card.title == "Mon Théâtre"


def test_le_condense_est_borne_quelle_que_soit_la_page():
    """Sa raison d'être : un coût plafonné, que la page fasse 2 Ko ou 2 Mo.

    Le plafond se calcule — URL, titre, h1, trois cents caractères d'amorce et
    vingt textes de liens de quatre-vingts — et c'est lui qui garantit que
    l'appel restera à quelques centaines de jetons.
    """
    html = agenda_html() + "<p>" + "du remplissage. " * 5000 + "</p>"
    card = digest(html, "https://x.fr/agenda/", links_of(html, "https://x.fr/agenda/"))
    assert len(card.as_prompt()) < 2600
    assert "dont 12 voisinent une date" in card.as_prompt()
