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
