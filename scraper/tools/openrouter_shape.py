"""Confronte le fournisseur OpenRouter au vrai service, et montre ce qu'il rend.

Les tests de `test_provider_openrouter.py` simulent les réponses à la forme
**documentée** de l'API. Ils verrouillent ce que le code en fait ; ils ne
prouvent pas qu'elle soit la bonne — personne, dans ce dépôt, ne l'a vérifiée
contre le service, à la différence de Serper.

Ce script est là pour ça. Il n'a rien à faire dans la suite de tests : il
appelle le réseau, il consomme quelques centièmes de centime, et il demande
une clé. On le lance à la main, ou par le workflow `verifier.yml` qui, lui, a
la clé.

    OPENROUTER_API_KEY=… python -m tools.openrouter_shape
    OPENROUTER_API_KEY=… python -m tools.openrouter_shape google/gemini-2.5-flash

Il fait trois choses, dans cet ordre :

1. il lit le catalogue public et **vérifie la table d'équivalences** — les
   noms du pipeline (« claude-haiku-4-5 ») traduits en slugs OpenRouter. Cette
   table a été écrite d'après leur convention de nommage, pas d'après leur
   catalogue : c'est ici qu'on l'apprend si elle a vieilli ;
2. il lance un vrai appel de reconnaissance — le plus petit des quatre — et
   affiche la forme brute reçue : clés de premier niveau, champs d'un choix,
   champs de `usage` ;
3. il refait le même appel **par le fournisseur**, et affiche ce qu'il en
   tire et ce qu'il a facturé.

Si les deux ne concordent pas, c'est ici que ça se voit, et le code des tests
est à corriger d'après ce que la sortie montre.
"""

from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sortiesbot.config import Config
from sortiesbot.journal import RunLog
from sortiesbot.providers.openrouter_provider import (
    ENDPOINT,
    EQUIVALENCES,
    OpenRouterProvider,
)

CATALOGUE = "https://openrouter.ai/api/v1/models"

#: Un condensé de page minuscule : l'appel doit coûter le moins possible.
CONDENSE = (
    "Théâtre des Petits — Agenda\n"
    "Samedi 3 octobre : Le Petit Chaperon, spectacle dès 3 ans, 8 €\n"
    "Samedi 10 octobre : Contes d'automne, dès 4 ans, 8 €"
)


def verifier_la_table(session) -> int:
    """Chaque équivalence existe-t-elle encore au catalogue ?"""
    print(f"— la table d'équivalences, contre {CATALOGUE} —")
    try:
        reponse = session.get(CATALOGUE, timeout=30)
        connus = {m.get("id") for m in (reponse.json().get("data") or [])}
    except Exception as err:  # noqa: BLE001 — un outil de vérification, pas du pipeline
        print(f"  catalogue injoignable ({err.__class__.__name__}) : table non vérifiée")
        return 0

    manquants = [slug for slug in EQUIVALENCES.values() if slug not in connus]
    for nom, slug in EQUIVALENCES.items():
        etat = "absent du catalogue" if slug in manquants else "ok"
        print(f"  {nom:<20} → {slug:<34} {etat}")
    if manquants:
        print(f"\n  {len(manquants)} équivalence(s) à corriger dans EQUIVALENCES.", file=sys.stderr)
    return 1 if manquants else 0


def main(argv: list[str]) -> int:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY manquante.", file=sys.stderr)
        return 2

    import requests

    session = requests.Session()
    faute = verifier_la_table(session)

    modele = argv[1] if len(argv) > 1 else EQUIVALENCES["claude-haiku-4-5"]
    print(f"\n— un appel de reconnaissance à {modele}, sur {ENDPOINT} —")

    config = Config(name="verif", theme="spectacles enfants", provider="openrouter",
                    classify_model=modele)
    brut = session.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": modele,
            "messages": [{"role": "user", "content": config.render_classify(CONDENSE)}],
            "max_tokens": 300,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "nature",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "nature": {"type": "string"},
                            "pourquoi": {"type": "string"},
                        },
                        "required": ["nature", "pourquoi"],
                        "additionalProperties": False,
                    },
                },
            },
            "provider": {"require_parameters": True},
            "usage": {"include": True},
        },
        timeout=120,
    )
    print(f"HTTP {brut.status_code}")
    if brut.status_code >= 400:
        print(brut.text[:800], file=sys.stderr)
        return 1

    data = brut.json()
    print(f"Clés de premier niveau : {sorted(data)}")
    choices = data.get("choices") or []
    if choices:
        print(f"Champs d'un choix      : {sorted(choices[0])}")
        print(f"Champs d'un message    : {sorted(choices[0].get('message') or {})}")
        print(f"Motif d'arrêt          : {choices[0].get('finish_reason')}")
        contenu = (choices[0].get("message") or {}).get("content")
        print(f"Contenu                : {str(contenu)[:200]}")
    usage = data.get("usage") or {}
    print(f"Champs de « usage »    : {sorted(usage)}")
    print(f"Coût annoncé           : {usage.get('cost')!r}")
    if "cost" not in usage:
        print(
            "\n  `usage.cost` absent : le fournisseur facturerait à l'estime, et le "
            "plafond du run tomberait trop tôt.",
            file=sys.stderr,
        )
        faute = 1

    print("\n— ce que le fournisseur en tire —")
    provider = OpenRouterProvider(api_key=key)
    log = RunLog(path=None, verbose=False, stream=io.StringIO())
    nature, pourquoi = provider.classify(CONDENSE, config, log)
    print(f"  nature  : {nature}")
    print(f"  motif   : {pourquoi}")
    print(
        f"  facture : {provider.usage.cost_usd:.6f} $ "
        f"({provider.usage.input_tokens} jetons d'entrée, "
        f"{provider.usage.output_tokens} de sortie)"
    )

    if nature != "agenda":
        print(
            f"\n  Cette page est un agenda ; le modèle a répondu « {nature} ». "
            "Ce n'est pas la forme de l'API qui est en cause, mais le modèle "
            "choisi ou le prompt.",
            file=sys.stderr,
        )
    return faute


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
