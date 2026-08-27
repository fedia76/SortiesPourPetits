"""Téléchargement de la photo d'illustration trouvée sur la page source.

Les contraintes reproduisent celles de `server/src/lib/upload.ts` : formats
acceptés et taille maximale. Le fichier est rapatrié en flux et abandonné dès
qu'il dépasse la limite, pour ne pas charger un fichier de 200 Mo en mémoire.

Les droits d'usage de l'image ne sont pas vérifiables automatiquement : le
`sourceUrl` accompagne la sortie et c'est le modérateur qui tranche.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import requests

MAX_BYTES = 10 * 1024 * 1024

_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}

_TIMEOUT = 20


class PhotoError(RuntimeError):
    pass


def download(url: str, session: requests.Session | None = None) -> tuple[str, bytes, str]:
    """Retourne `(nom de fichier, contenu, type MIME)` ou lève `PhotoError`."""
    if not url.startswith(("http://", "https://")):
        raise PhotoError("URL de photo invalide")

    session = session or requests.Session()
    try:
        response = session.get(url, timeout=_TIMEOUT, stream=True)
        response.raise_for_status()
        mime = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if mime not in _MIME_EXTENSIONS:
            raise PhotoError(f"format non supporté ({mime or 'inconnu'})")

        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_BYTES:
                raise PhotoError("photo trop lourde (plus de 10 Mo)")
            chunks.append(chunk)
    except requests.RequestException as err:
        raise PhotoError(f"téléchargement impossible : {err}") from err

    content = b"".join(chunks)
    if not content:
        raise PhotoError("photo vide")

    stem = (urlsplit(url).path.rsplit("/", 1)[-1] or "photo").rsplit(".", 1)[0][:40]
    return f"{stem or 'photo'}{_MIME_EXTENSIONS[mime]}", content, mime
