"""Client de l'API SortiesPourPetits.

Le scraper est un « programme tiers » au sens de la clé d'API : il présente
`Authorization: Bearer spp_…` et hérite du rôle du compte rattaché. Toute
sortie créée arrive donc en attente de modération, comme une proposition
humaine.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_TIMEOUT = 30

#: Reprises sur un échec de **connexion**, et rien d'autre. Le site redémarre
#: en quelques secondes à chaque déploiement (`deploy.yml` relance l'API), et
#: un run en cours perdait une sortie pour ça : la connexion refusée est la
#: seule erreur dont on sait avec certitude que la requête n'est jamais
#: arrivée, donc la seule qu'on puisse rejouer sans risque.
#:
#: Ni lecture ni statut, volontairement : une requête partie a pu être
#: exécutée par le site avant que la réponse se perde, et `POST /api/events`
#: n'est pas idempotent — la rejouer créerait un doublon en modération.
_CONNECT_RETRIES = 3
#: Attente avant chaque reprise : 0,5 s, 1 s, 2 s — le temps d'un redémarrage.
_BACKOFF = 0.5


def retrying_session() -> requests.Session:
    """Une session qui encaisse un redémarrage de l'API sans perdre l'appel."""
    session = requests.Session()
    adapter = HTTPAdapter(
        max_retries=Retry(
            total=_CONNECT_RETRIES,
            connect=_CONNECT_RETRIES,
            read=0,
            status=0,
            redirect=0,
            backoff_factor=_BACKOFF,
            # `None` vaut « toutes les méthodes » : POST compris, puisque
            # seule l'ouverture de la connexion est rejouée.
            allowed_methods=None,
        )
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class ApiError(RuntimeError):
    """Erreur remontée par l'API, ou impossibilité de la joindre."""


@contextmanager
def _as_api_error() -> Iterator[None]:
    """Un site injoignable est une erreur d'API comme une autre : le pipeline
    sait la traiter, alors qu'une exception réseau brute ferait tomber le run."""
    try:
        yield
    except requests.RequestException as err:
        raise ApiError(f"API injoignable : {err.__class__.__name__}") from err


class SppApi:
    def __init__(self, base_url: str, api_key: str | None = None, session: Any = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session or retrying_session()

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

    def _post_json(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        with _as_api_error():
            response = self.session.post(
                f"{self.base_url}{path}",
                headers={**self._headers(authenticated=True), "Content-Type": "application/json"},
                data=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
                timeout=_TIMEOUT,
            )
        return self._check(response)

    # ------------------------------------------------------------- scraper
    # Ces routes sont celles que pilote la console d'administration : le
    # worker y prend son travail, y rend compte, et y consulte la mémoire des
    # pages déjà analysées.

    def next_run(self) -> dict[str, Any] | None:
        """Réclame la prochaine exécution en file, ou None s'il n'y a rien."""
        body = self._post_json("/api/scraper/next")
        return body.get("run")

    def report_items(self, run_id: int, items: list[dict[str, Any]]) -> None:
        """Journalise des pages traitées et alimente la mémoire commune."""
        if not items:
            return
        self._post_json(f"/api/scraper/runs/{run_id}/items", {"items": items})

    def report_logs(self, run_id: int, entries: list[dict[str, Any]]) -> None:
        """Renvoie le journal détaillé du run, par paquets.

        Distinct de `report_items` : celui-ci décide du sort d'une page et
        alimente la mémoire, celui-là ne fait que raconter. Deux routes, pour
        que le journal ne puisse jamais, par un bug, mémoriser quoi que ce soit.
        """
        if not entries:
            return
        self._post_json(f"/api/scraper/runs/{run_id}/logs", {"entries": entries})

    def report_source(
        self,
        run_id: int,
        url: str,
        signal: str,
        detail: str,
        checked: bool,
        found_on: str = "",
    ) -> dict[str, Any]:
        """Rapporte ce qu'une recherche de source a trouvé. Le site décide.

        Le worker ne touche jamais à la fiche : il dit ce qu'il a lu, et le
        site range. `checked` est le seul champ qui autorise le remplacement —
        une URL proposée mais jamais ouverte n'est pas une source.
        """
        payload: dict[str, Any] = {"signal": signal, "detail": detail[:500], "checked": checked}
        if url:
            payload["url"] = url
        if found_on:
            payload["foundOn"] = found_on
        return self._post_json(f"/api/scraper/runs/{run_id}/source", payload)

    def finish_run(self, run_id: int, status: str, **counters: Any) -> None:
        """Clôt l'exécution avec ses compteurs (status : DONE ou FAILED)."""
        self._post_json(f"/api/scraper/runs/{run_id}/finish", {"status": status, **counters})

    def known_urls(self, urls: list[str]) -> set[str]:
        """Parmi ces URLs, celles que le site a déjà vu analyser."""
        if not urls:
            return set()
        known: set[str] = set()
        # La route accepte 500 URLs par appel ; on reste large sous la limite.
        for start in range(0, len(urls), 200):
            body = self._post_json("/api/scraper/seen", {"urls": urls[start : start + 200]})
            known.update(row["url"] for row in body.get("seen", []))
        return known

    def categories(self) -> dict[str, int]:
        """Catégories existantes, indexées par nom (route publique)."""
        with _as_api_error():
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

        with _as_api_error():
            response = self._post(url, headers, data, photo)
        body = self._check(response)
        return body.get("event", {})

    def _post(
        self,
        url: str,
        headers: dict[str, str],
        data: str,
        photo: tuple[str, bytes, str] | None,
    ) -> requests.Response:
        if photo is None:
            return self.session.post(
                url,
                headers={**headers, "Content-Type": "application/json"},
                data=json.dumps({"data": data}).encode("utf-8"),
                timeout=_TIMEOUT,
            )
        filename, content, mime = photo
        return self.session.post(
            url,
            headers=headers,
            data={"data": data},
            files={"photo": (filename, content, mime)},
            timeout=_TIMEOUT,
        )
