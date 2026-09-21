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

1. il lit le catalogue public et **vérifie le modèle par défaut** — le slug
   sur lequel retombe toute configuration qui n'en nomme pas d'autre. C'est la
   seule chose que ce dépôt affirme d'OpenRouter sans pouvoir la prouver : si
   ce slug a été renommé ou retiré, tous ces runs-là échoueront sur un 404 ;
2. il lance un vrai appel de reconnaissance — le plus petit des quatre — et
   affiche la forme brute reçue : clés de premier niveau, champs d'un choix,
   champs de `usage` ;
3. il refait le même appel **par le fournisseur**, et affiche ce qu'il en
   tire et ce qu'il a facturé.

Il affiche aussi **quel hébergeur a répondu** — son suffixe `:floor` demande
le moins cher d'entre eux, et ce n'est pas le même d'un appel à l'autre — et
**combien de jetons de raisonnement** l'appel a consommés. Ce dernier chiffre
est celui qui règle `MARGE_RAISONNEMENT` : elle a été posée sans mesure, parce
qu'aucun appel n'était encore allé au bout.

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
    EFFORT_RAISONNEMENT,
    ENDPOINT,
    MARGE_RAISONNEMENT,
    MODELE_DEFAUT,
    OpenRouterProvider,
)

CATALOGUE = "https://openrouter.ai/api/v1/models"

#: Un condensé de page minuscule : l'appel doit coûter le moins possible.
CONDENSE = (
    "Théâtre des Petits — Agenda\n"
    "Samedi 3 octobre : Le Petit Chaperon, spectacle dès 3 ans, 8 €\n"
    "Samedi 10 octobre : Contes d'automne, dès 4 ans, 8 €"
)


def verifier_le_defaut(session, modele: str) -> int:
    """Le modèle par défaut existe-t-il au catalogue ?

    C'est la seule chose que ce dépôt affirme d'OpenRouter sans pouvoir la
    prouver : un slug écrit à la main. S'il a été renommé ou retiré, tous les
    runs qui ne nomment pas de modèle échoueront sur un 404, et c'est ici qu'on
    l'apprend plutôt qu'en production.

    Le suffixe de routage (`:floor`, `:nitro`…) est retiré avant de comparer :
    ce n'est pas un modèle, et le catalogue ne le liste pas.
    """
    base = modele.split(":", 1)[0]
    variante = modele[len(base) + 1 :]
    print(f"— le modèle par défaut, contre {CATALOGUE} —")
    try:
        reponse = session.get(CATALOGUE, timeout=30)
        connus = {m.get("id") for m in (reponse.json().get("data") or [])}
    except Exception as err:  # noqa: BLE001 — un outil de vérification, pas du pipeline
        print(f"  catalogue injoignable ({err.__class__.__name__}) : défaut non vérifié")
        return 0

    present = base in connus
    print(f"  {base:<34} {'ok' if present else 'ABSENT DU CATALOGUE'}")
    if variante:
        print(f"  suffixe « :{variante} » — consigne de routage, pas un modèle : non listé")
    if not present:
        print(
            f"\n  MODELE_DEFAUT introuvable. À corriger dans "
            f"providers/openrouter_provider.py — {len(connus)} modèles au catalogue.",
            file=sys.stderr,
        )
    return 0 if present else 1


def main(argv: list[str]) -> int:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY manquante.", file=sys.stderr)
        return 2

    import requests

    session = requests.Session()
    modele = argv[1] if len(argv) > 1 else MODELE_DEFAUT
    faute = verifier_le_defaut(session, modele)
    print(f"\n— un appel de reconnaissance à {modele}, sur {ENDPOINT} —")

    config = Config(name="verif", theme="spectacles enfants", provider="openrouter",
                    classify_model=modele)
    brut = session.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": modele,
            "messages": [{"role": "user", "content": config.render_classify(CONDENSE)}],
            # Comme le fournisseur : le plafond de l'appel, plus la marge de
            # raisonnement. C'est cette marge que le chiffre affiché plus bas
            # permet de régler — elle a été posée sans mesure, faute d'un
            # appel réel qui aille au bout.
            "max_tokens": 300 + MARGE_RAISONNEMENT,
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
            # Comme le fournisseur : le couper est refusé, le régler ne l'est
            # pas. C'est ce chiffre-là — les jetons de raisonnement affichés
            # plus bas — que le réglage vise.
            "reasoning": {"effort": EFFORT_RAISONNEMENT},
        },
        timeout=120,
    )
    print(f"HTTP {brut.status_code}")
    if brut.status_code >= 400:
        print(brut.text[:800], file=sys.stderr)
        return 1

    data = brut.json()
    print(f"Clés de premier niveau : {sorted(data)}")
    # Avec un suffixe `:floor`, c'est l'information qu'on vient chercher : le
    # modèle par défaut demande l'hébergeur le moins cher, et celui-là change
    # d'un appel à l'autre. Savoir lequel a répondu, et si le modèle servi est
    # bien celui demandé, ne se lit nulle part ailleurs.
    print(f"Hébergeur                : {data.get('provider', '(non annoncé)')}")
    print(f"Modèle réellement servi  : {data.get('model', '(non annoncé)')}")
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
    # La consigne « ne raisonne pas » est-elle honorée ? Un chiffre non nul ici
    # veut dire que ce modèle raisonne quoi qu'on lui dise, et qu'il faudra
    # soit en changer, soit payer ce raisonnement à chaque page.
    raisonnement = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    print(
        f"Jetons de raisonnement : {raisonnement!r} "
        f"(effort « {EFFORT_RAISONNEMENT or 'non réglé'} », "
        f"marge prévue : {MARGE_RAISONNEMENT})"
    )
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
