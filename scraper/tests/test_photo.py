"""Téléchargement de l'illustration.

Les sorties importées arrivaient sans photo. Une fois l'URL trouvée (voir
`test_harvest`), encore faut-il que le fichier passe : c'est ici que se jouent
les types MIME fantaisistes des serveurs, et le fait que le site n'accepte
que cinq formats.
"""

from __future__ import annotations

import pytest

from sortiesbot.photo import PhotoError, download


class FakeResponse:
    def __init__(self, content: bytes, content_type: str | None):
        self.content = content
        self.headers = {} if content_type is None else {"Content-Type": content_type}

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield self.content


class FakeSession:
    def __init__(self, content: bytes, content_type: str | None):
        self.response = FakeResponse(content, content_type)
        self.asked: list[str] = []

    def get(self, url, **kwargs):
        self.asked.append(url)
        return self.response


JPEG = b"\xff\xd8\xff\xe0" + b"des octets"
PNG = b"\x89PNG\r\n\x1a\n" + b"des octets"


def test_le_type_annonce_suffit():
    session = FakeSession(JPEG, "image/jpeg")
    nom, contenu, mime = download("https://cdn.fr/affiche.jpg", session)
    assert (nom, contenu, mime) == ("affiche.jpg", JPEG, "image/jpeg")


def test_image_jpg_est_normalise():
    """Le site n'accepte que `image/jpeg` : renvoyer `image/jpg` ferait
    refuser une photo parfaitement valide."""
    session = FakeSession(JPEG, "image/jpg")
    assert download("https://cdn.fr/affiche.jpg", session)[2] == "image/jpeg"


@pytest.mark.parametrize("annonce", [None, "", "application/octet-stream", "binary/octet-stream"])
def test_un_type_absent_ou_generique_ne_condamne_pas_l_image(annonce):
    """Beaucoup de CDN servent une image sans dire laquelle. Les octets, eux,
    ne mentent pas."""
    session = FakeSession(PNG, annonce)
    assert download("https://cdn.fr/affiche", session)[2] == "image/png"


def test_une_page_html_servie_a_la_place_d_une_image_est_refusee():
    session = FakeSession(b"<html><body>404</body></html>", "text/html")
    with pytest.raises(PhotoError, match="format non support"):
        download("https://cdn.fr/affiche.jpg", session)


def test_photo_vide():
    session = FakeSession(b"", "image/jpeg")
    with pytest.raises(PhotoError, match="vide"):
        download("https://cdn.fr/affiche.jpg", session)


def test_url_non_http():
    with pytest.raises(PhotoError, match="invalide"):
        download("data:image/png;base64,AAAA")


def test_le_nom_de_fichier_suit_le_type_retenu():
    session = FakeSession(PNG, "application/octet-stream")
    assert download("https://cdn.fr/photos/affiche-2026", session)[0] == "affiche-2026.png"
