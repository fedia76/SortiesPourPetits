"""Client de l'API SortiesPourPetits.

Le scraper est un « programme tiers » au sens de la clé d'API : il présente
`Authorization: Bearer spp_…` et hérite du rôle du compte rattaché. Toute
sortie créée arrive donc en attente de modération, comme une proposition
humaine.
"""

from __future__ import annotations

import json
from typing import Any

import requests

_TIMEOUT = 30


class ApiError(RuntimeError):
    """Erreur remontée par l'API, avec son message tel quel."""


class SppApi:
    def __init__(self, base_url: str, api_key: str | None = None, session: Any = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session or requests.Session()

    def _headers(self, authenticated: bool) -> dict[str, str]:
        if not authenticated:
            return {}
        if not self.api_key:
            raise ApiError("Aucune clé d'API : renseignez SPP_API_KEY pour soumettre des sorties")
        return {"Authorization": f"Bearer {self.api_key}"}

    def _check(self, response: requests.Response) -> Any:
        if response.status_code >= 400:
            try:
                message = response.json().get("error") or response.text
            except ValueError:
                message = response.text
            raise ApiError(f"HTTP {response.status_code} — {message}")
        return response.json()

    def categories(self) -> dict[str, int]:
        """Catégories existantes, indexées par nom (route publique)."""
        response = self.session.get(f"{self.base_url}/api/categories", timeout=_TIMEOUT)
        body = self._check(response)
        return {c["name"]: c["id"] for c in body.get("categories", [])}

    def create_event(
        self,
        payload: dict[str, Any],
        photo: tuple[str, bytes, str] | None = None,
    ) -> dict[str, Any]:
        """Propose une sortie. Retourne l'événement créé (statut PENDING).

        La route attend le JSON dans un champ `data` — sous forme de chaîne.
        Avec une photo c'est du multipart (multer lit `data` et `photo`) ; sans
        photo on envoie du JSON, car l'API n'a pas d'analyseur pour les
        formulaires urlencodés.
        """
        data = json.dumps(payload, ensure_ascii=False)
        headers = self._headers(authenticated=True)
        url = f"{self.base_url}/api/events"

        if photo is None:
            response = self.session.post(
                url,
                headers={**headers, "Content-Type": "application/json"},
                data=json.dumps({"data": data}).encode("utf-8"),
                timeout=_TIMEOUT,
            )
        else:
            filename, content, mime = photo
            response = self.session.post(
                url,
                headers=headers,
                data={"data": data},
                files={"photo": (filename, content, mime)},
                timeout=_TIMEOUT,
            )
        body = self._check(response)
        return body.get("event", {})
