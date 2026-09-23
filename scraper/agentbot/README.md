# agentbot — le second scraper, un agent

Un prototype, à côté de `sortiesbot` et sans le modifier. Là où le pipeline
enchaîne ses huit étages dans un ordre écrit d'avance (`Run.chain()`), l'agent
laisse un modèle — le **pilote** — choisir à chaque tour l'outil suivant :
chercher, ouvrir, lister des liens, extraire, proposer, conclure.

Rien n'est proposé au site : l'agent ne tourne qu'en essai. Il n'est pas
branché à la console ni au worker ; ce sera à faire si les chiffres le
justifient.

## Lancer

```bash
cd scraper
pip install -e .
# .env : OPENROUTER_API_KEY et SERPER_API_KEY
python -m agentbot --config configs/agent-exemple.yaml --forget
```

| Option | Effet |
|---|---|
| `--pilot` | modèle OpenRouter qui pilote (`z-ai/glm-5.3-flash` par défaut, `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`…) |
| `--effort` | effort de raisonnement du pilote (`low` par défaut, vide pour celui du modèle) |
| `--max-turns`, `--max-pages`, `--max-depth`, `--max-searches` | les plafonds de l'exploration |
| `--limit N` | plafonne le nombre de sorties retenues |
| `--forget` | mémoire vide, pour rejouer |
| `--state` | mémoire des pages vues — **séparée** de celle du pipeline par défaut |

Le run écrit `runs/<horodatage>_<config>-agent.jsonl` (le journal, chaque tour
et chaque outil compris) et `.json` (les sorties retenues, le bilan du pilote,
le nombre d'appels par outil, le coût).

## Comment ça marche

```
tant que le pilote n'a pas conclu, et qu'aucun plafond n'est atteint :
    tour = pilote(historique, outils)     ← un appel facturé, format OpenAI
    pour chaque outil demandé :
        résultat = outil(arguments)       ← une brique de sortiesbot
        historique += résultat (un résumé, jamais la page)
```

| Outil | Brique réutilisée | Coût |
|---|---|---|
| `search` | `SerperClient` | 0,001 $ |
| `open` | étage 2, reconnaissance | gratuit, sauf page indécise |
| `links` | étage 3, dépouillement | gratuit |
| `extract` | étages 5 et 6, lecture et extraction | un appel au modèle d'extraction |
| `propose` | étages 7 et 8, attribution et publication | gratuit, sauf recherche de source |
| `finish` | — | — |

Trois choix qui tiennent le coût, tirés de la première version agentique du
projet (2,35 $ pour six sorties) :

1. **Le pilote ne voit jamais une page.** Il manipule des références (`r3`,
   `p2`, `l14`, `f5`) et des résumés de quelques lignes. L'extraction lit le
   texte dans un appel séparé.
2. **L'historique s'élague par paquets** : tous les huit tours, les résultats
   de plus de quatre tours sont réduits à leur première ligne. Par paquets et
   non à chaque tour, pour ne pas casser le cache des hébergeurs qui en ont un.
3. **Les plafonds sont dans le code.** Un outil qui dépasse refuse et le dit ;
   un pilote ne peut pas ouvrir une adresse qu'aucun outil ne lui a donnée.

## Comparer avec le pipeline

La configuration est celle du pipeline : la même peut être jouée par les deux.

```bash
python -m sortiesbot --config configs/agent-exemple.yaml --forget
python -m agentbot   --config configs/agent-exemple.yaml --forget
python -m agentbot   --config configs/agent-exemple.yaml --forget --pilot anthropic/claude-haiku-4.5
```

Ce qu'il faut regarder, dans les deux JSON :

- **les sorties retenues**, et surtout celles que l'autre n'a *pas* trouvées ;
- **le coût par sortie retenue** (`summary.usage.total_usd` / `summary.retained`) ;
- pour l'agent, **le bilan et les appels par outil** : un pilote qui fait vingt
  recherches et trois extractions ne travaille pas comme un pilote qui creuse
  deux sites.

Un seul run ne prouve rien : un agent ne refait pas deux fois le même parcours.
Trois runs de chaque côté, au minimum. Et toujours deux pilotes : si l'agent
plafonne avec GLM, rien ne dit encore si c'est l'idée qui est en cause ou le
modèle.

## Ce qui n'est pas vérifié

- **La forme d'une réponse à outils d'OpenRouter** n'a pas pu être vérifiée
  contre le service au moment de l'écriture. Le code suit le format OpenAI
  (`tool_calls[].function.arguments`) et renvoie `reasoning_details` d'un tour
  à l'autre. Si le premier run échoue au premier tour, c'est là qu'il faut
  regarder.
- **La capacité d'un modèle « flash » à piloter soixante tours.** C'est la
  vraie question du prototype, et seuls des runs y répondront.
- **Le cache chez les hébergeurs de GLM.** L'élagage est conçu pour le
  préserver là où il existe ; rien ne garantit qu'il existe.
