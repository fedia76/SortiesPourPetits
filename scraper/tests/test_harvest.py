"""Téléchargement poli et extraction des liens.

C'est la brique qui remplace `web_fetch` : elle doit trier le bruit sans
jamais écarter un vrai lien d'événement, et refuser ce que `robots.txt`
interdit.
"""

from __future__ import annotations

import pytest

from sortiesbot.harvest import Fetcher, FetchError, links_of, page_text

AGENDA = """
<html><body>
  <nav><a href="/">Accueil</a> <a href="/contact">Contact</a>
       <a href="/jeune-public/">Jeune public</a></nav>
  <article class="event">
    <a href="/jeune-public/vanves/les-caprices-de-l-enfant-roi.html">Les Caprices de l'enfant roi</a>
    <span>jusqu'au 30 août 2026 — Théâtre de Vanves — dès 8 ans</span>
  </article>
  <article class="event">
    <a href="/jeune-public/asnieres-sur-seine/simon-le-saumon.html">Simon le saumon</a>
    <span>jusqu'au 23 oct. 2026 — Théâtre Le Petit Manoir — 10 €</span>
  </article>
  <footer>
    <a href="/mentions-legales">Mentions légales du site</a>
    <a href="/newsletter">Recevoir notre newsletter hebdomadaire</a>
    <a href="https://www.facebook.com/agenda">Suivez-nous sur Facebook</a>
    <a href="mailto:contact@agenda.fr">Nous écrire un message</a>
  </footer>
</body></html>
"""

PAGE = "https://92.agendaculturel.fr/jeune-public/"


def test_les_evenements_sortent_avec_leur_contexte():
    liens = links_of(AGENDA, PAGE)
    assert [l.text for l in liens] == ["Les Caprices de l'enfant roi", "Simon le saumon"]
    # Le contexte porte la date et le lieu : de quoi trier sans ouvrir la page.
    assert "30 août 2026" in liens[0].context
    assert "Théâtre de Vanves" in liens[0].context
    # Les URL relatives sont résolues.
    assert liens[0].url.startswith("https://92.agendaculturel.fr/jeune-public/vanves/")


@pytest.mark.parametrize(
    "raison, html",
    [
        ("texte trop court", '<a href="/spectacle/x-y-z.html">Voir</a>'),
        ("page de service", '<a href="/mentions-legales">Les mentions légales</a>'),
        ("racine du site", '<a href="/">Retour à la page d\'accueil</a>'),
        ("lien sortant", '<a href="https://autre.fr/spectacle/le-grand-cirque">Le grand cirque</a>'),
        ("ancre", '<a href="#programme">Voir tout le programme ici</a>'),
        ("courriel", '<a href="mailto:x@y.fr">Écrire au théâtre municipal</a>'),
    ],
)
def test_bruit_ecarte(raison, html):
    assert links_of(f"<html><body>{html}</body></html>", PAGE) == [], raison


def test_contexte_remonte_jusqu_a_la_carte():
    """Cas réel : le parent immédiat du lien n'enveloppe que le titre, et la
    date est un cran plus haut. S'y arrêter fait perdre ce qui sert à trier."""
    html = """<html><body><article class="card">
        <div class="titre"><a href="/spectacle/le-chaperon.html">Le Petit Chaperon rouge</a></div>
        <div class="infos">du 29 au 30 août 2026 — Théâtre de Vanves — dès 8 ans — 12 €</div>
      </article></body></html>"""
    lien = links_of(html, PAGE)[0]
    assert "29 au 30 août 2026" in lien.context
    assert "Théâtre de Vanves" in lien.context


def test_contexte_ne_deborde_pas_sur_la_liste_entiere():
    """Si la carte n'existe pas, on ne doit pas remonter jusqu'à happer les
    trente autres événements : un contexte faux est pire qu'un contexte court."""
    autres = "".join(
        f'<div><a href="/spectacle/{i}-un-titre-de-spectacle.html">Spectacle numéro {i}</a>'
        f"<span>du 1er au 30 septembre 2026, salle des fêtes</span></div>"
        for i in range(30)
    )
    lien = links_of(f"<html><body><section>{autres}</section></body></html>", PAGE)[0]
    assert "Spectacle numéro 0" in lien.context
    assert "Spectacle numéro 5" not in lien.context


def test_doublons_fusionnes():
    html = """<a href="/spectacle/le-petit-chaperon.html">Le Petit Chaperon rouge</a>
              <a href="/spectacle/le-petit-chaperon.html">Le Petit Chaperon rouge (réserver)</a>"""
    assert len(links_of(f"<html><body>{html}</body></html>", PAGE)) == 1


def test_texte_de_page_sans_navigation():
    html = """<html><body>
        <nav>Accueil Contact Billetterie</nav>
        <main>Simon le saumon remonte la rivière. Spectacle musical dès 3 ans.</main>
        <footer>Mentions légales</footer>
    </body></html>"""
    texte = page_text(html)
    assert "Simon le saumon remonte la rivière" in texte
    assert "Billetterie" not in texte and "Mentions légales" not in texte


def test_texte_de_page_tronque():
    html = "<html><body><p>" + ("mot " * 5000) + "</p></body></html>"
    assert len(page_text(html, limit=500)) == 500


class FakeResponse:
    def __init__(self, text="", status=200, content_type="text/html"):
        self.text = text
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, size):
        yield self.text.encode("utf-8")


class FakeSession:
    """Session HTTP scriptée : `robots.txt` d'abord, puis les pages."""

    def __init__(self, robots="", pages=None):
        self.robots = robots
        self.pages = pages or {}
        self.headers: dict[str, str] = {}
        self.asked: list[str] = []

    def get(self, url, **_kwargs):
        self.asked.append(url)
        if url.endswith("/robots.txt"):
            return FakeResponse(self.robots)
        if url in self.pages:
            return FakeResponse(self.pages[url])
        return FakeResponse("", status=404)


def test_robots_txt_est_respecte(monkeypatch):
    monkeypatch.setattr("sortiesbot.harvest.CRAWL_DELAY", 0)
    session = FakeSession(robots="User-agent: *\nDisallow: /prive/\n",
                          pages={"https://site.fr/public/x": "<html>ok</html>"})
    fetcher = Fetcher(session=session)

    assert fetcher.get_html("https://site.fr/public/x") == "<html>ok</html>"
    with pytest.raises(FetchError, match="robots.txt"):
        fetcher.get_html("https://site.fr/prive/secret")


def test_robots_txt_absent_vaut_autorisation(monkeypatch):
    monkeypatch.setattr("sortiesbot.harvest.CRAWL_DELAY", 0)
    session = FakeSession(pages={"https://site.fr/a": "<html>ok</html>"})
    session.get_404_robots = True
    fetcher = Fetcher(session=session)
    # Le faux robots.txt renvoie une chaîne vide, donc « tout autorisé ».
    assert fetcher.get_html("https://site.fr/a") == "<html>ok</html>"


def test_on_s_annonce():
    session = FakeSession()
    Fetcher(session=session)
    assert "SortiesPourPetitsBot" in session.headers["User-Agent"]
    assert "sortiespourpetits.fr" in session.headers["User-Agent"]


def test_page_inaccessible(monkeypatch):
    monkeypatch.setattr("sortiesbot.harvest.CRAWL_DELAY", 0)
    fetcher = Fetcher(session=FakeSession())
    with pytest.raises(FetchError, match="inaccessible"):
        fetcher.get_html("https://site.fr/disparue")


def test_geocodeur_bascule_sur_la_ban_quand_photon_refuse(monkeypatch):
    """Un run entier a rendu 20 sorties non géolocalisées sur 20, toutes sur
    des 403 de Photon. La BAN doit prendre le relais — et Photon ne doit pas
    être rejoué vingt fois."""
    import requests

    from sortiesbot import geocode as g

    appels = {"photon": 0, "ban": 0}

    def photon(query):
        appels["photon"] += 1
        raise requests.HTTPError("403 Client Error: Forbidden")

    def ban(query):
        appels["ban"] += 1
        return [{"properties": {"city": "Orsay", "postcode": "91400"},
                 "geometry": {"coordinates": [2.1873, 48.6997]}}]

    monkeypatch.setattr(g, "_photon_available", True)
    monkeypatch.setattr(g, "_photon_search", photon)
    monkeypatch.setattr(g, "_ban_search", ban)

    assert g._search("14bis avenue Saint Laurent, 91400, Orsay")[0]["properties"]["postcode"] == "91400"
    g._search("une autre adresse")
    g._search("une troisième adresse")

    assert appels["photon"] == 1  # une rebuffade suffit, on n'insiste pas
    assert appels["ban"] == 3


# ------------------------------------------------------------------ la photo
#
# Le modèle ne reçoit que le texte de la page : il ne pouvait pas connaître
# l'URL d'une image, et les sorties importées arrivaient toutes sans photo.
# C'est donc le HTML qu'on interroge.

from sortiesbot.harvest import main_image

FICHE = """
<html><head>
  <meta property="og:image" content="/media/spectacle-2026.jpg">
</head><body>
  <img src="/static/logo.png" alt="Logo du théâtre">
  <img src="/media/salle.jpg" alt="La salle">
</body></html>
"""


def test_l_image_de_partage_gagne_et_devient_absolue():
    assert main_image(FICHE, PAGE) == "https://92.agendaculturel.fr/media/spectacle-2026.jpg"


def test_a_defaut_le_json_ld_de_l_evenement():
    html = """
    <html><head><script type="application/ld+json">
      {"@type": "TheaterEvent", "startDate": "2026-08-30",
       "image": {"@type": "ImageObject", "url": "https://cdn.fr/affiche.webp"}}
    </script></head><body></body></html>
    """
    assert main_image(html, PAGE) == "https://cdn.fr/affiche.webp"


def test_a_defaut_une_image_du_corps_mais_jamais_l_habillage():
    html = """
    <html><body>
      <img src="/img/logo-site.png" alt="Logo">
      <img src="/img/icon-partage.png" width="24" height="24">
      <img src="/img/affiche-du-spectacle.jpg" alt="Affiche">
    </body></html>
    """
    assert main_image(html, PAGE).endswith("/img/affiche-du-spectacle.jpg")


def test_le_lazy_loading_cache_la_vraie_url():
    html = '<html><body><img src="" data-src="/img/photo.jpg" alt="Le spectacle"></body></html>'
    assert main_image(html, PAGE).endswith("/img/photo.jpg")


def test_ni_svg_ni_data_uri():
    html = """
    <html><head><meta property="og:image" content="data:image/png;base64,AAAA"></head>
    <body><img src="/img/pictogramme.svg" alt="Un pictogramme"></body></html>
    """
    assert main_image(html, PAGE) == ""


def test_une_page_sans_image_ne_ment_pas():
    assert main_image("<html><body><p>Rien à voir</p></body></html>", PAGE) == ""


def test_une_page_nest_telechargee_quune_fois_par_run():
    """Le pipeline lit la même page deux fois — reconnaissance puis lecture.

    C'est la bande passante du site, et une seconde d'attente polie, pour un
    contenu identique. Le cache meurt avec le run : la semaine suivante, la
    page sera bien retéléchargée.
    """
    from sortiesbot.harvest import Fetcher

    appels: list[str] = []

    class SessionSimulee:
        headers: dict = {}

        def get(self, url, timeout=None, stream=False):
            appels.append(url)
            return _Reponse("<html><body><p>une page</p></body></html>")

    fetcher = Fetcher(session=SessionSimulee())
    fetcher._robots["https://exemple.fr"] = None  # pas de robots.txt à lire

    premier = fetcher.get_html("https://exemple.fr/page")
    second = fetcher.get_html("https://exemple.fr/page")

    assert premier == second
    assert appels == ["https://exemple.fr/page"], "un seul aller-retour réseau"


class _Reponse:
    """Le minimum de ce que `get_html` attend d'une réponse HTTP."""

    def __init__(self, texte: str):
        self._texte = texte
        self.headers = {"Content-Type": "text/html"}
        self.encoding = "utf-8"

    def raise_for_status(self):
        return None

    def iter_content(self, taille):
        yield self._texte.encode("utf-8")
