"""Confronte le fournisseur Serper au vrai service, et montre ce qu'il rend.

Les tests de `test_provider_serper.py` simulent les réponses à la forme
documentée de l'API. Ils verrouillent ce que le code **fait** de cette forme ;
ils ne prouvent pas qu'elle soit la bonne — personne, dans ce dépôt, ne l'a
vérifiée contre le service.

Ce script est là pour ça. Il n'a rien à faire dans la suite de tests : il
appelle le réseau, il consomme des crédits, et il demande une clé. On le lance
à la main, ou par le workflow `verifier.yml` qui, lui, a la clé.

    SERPER_API_KEY=… python -m tools.serper_shape "spectacle enfant Paris"

Il affiche la forme brute reçue — clés de premier niveau, champs d'un résultat
organique — puis ce que le fournisseur en tire. Si les deux ne concordent pas,
c'est ici que ça se voit, et le code des tests est à corriger d'après ce que
la sortie montre.
"""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sortiesbot.config import Config  # noqa: E402
from sortiesbot.journal import RunLog  # noqa: E402
from sortiesbot.providers.serper_client import ENDPOINT  # noqa: E402
from sortiesbot.providers.serper_provider import SerperProvider  # noqa: E402


def main(argv: list[str]) -> int:
    key = os.environ.get("SERPER_API_KEY")
    if not key:
        print("SERPER_API_KEY manquante.", file=sys.stderr)
        return 2

    query = argv[1] if len(argv) > 1 else "spectacle jeune public Paris septembre"
    print(f"Requête : {query}\nAdresse : {ENDPOINT}\n")

    import requests

    brut = requests.post(
        ENDPOINT,
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        data=json.dumps({"q": query, "gl": "fr", "hl": "fr", "num": 10}),
        timeout=30,
    )
    print(f"HTTP {brut.status_code}")
    if brut.status_code >= 400:
        print(brut.text[:500], file=sys.stderr)
        return 1

    data = brut.json()
    print(f"Clés de premier niveau : {sorted(data)}")
    organic = data.get("organic") or []
    print(f"Résultats organiques   : {len(organic)}")
    if organic:
        print(f"Champs d'un résultat   : {sorted(organic[0])}")
        for item in organic[:3]:
            print(f"  · {item.get('title', '?')[:60]}\n    {item.get('link')}")

    # Puis le même appel, mais par le fournisseur : c'est lui qu'on vérifie.
    print("\n— ce que le fournisseur en tire —")
    provider = SerperProvider(_SansModele(), api_key=key)
    log = RunLog(path=None, verbose=False, stream=io.StringIO())
    pages = provider.search([query], Config(name="verif", theme="x", provider="serper"), log)
    for page in pages[:3]:
        print(f"  · {page.title[:60]}\n    {page.url}")
    print(f"\n{len(pages)} page(s) retenue(s) · {provider.usage.search_cost_usd:.4f} $")

    if not pages:
        print("\nAucune page : la forme de la réponse a changé, ou la requête est vide.",
              file=sys.stderr)
        return 1
    return 0


class _SansModele:
    """Le fournisseur exige un modèle derrière lui ; on ne l'appelle pas ici."""

    from sortiesbot.models import Usage as _Usage

    name = "aucun"
    usage = _Usage()

    def __getattr__(self, nom):
        raise AssertionError(f"ce script ne doit appeler que la recherche, pas {nom}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
