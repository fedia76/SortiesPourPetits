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
cd /opt/sortiespourpetits/scraper
sudo -u deploy .venv/bin/python -m agentbot --config configs/agent-exemple.yaml --forget
```

Sur le VPS : le Python du venv (celui du worker, qui a les dépendances), et
l'utilisateur `deploy`, pour que `runs/` et `state/` ne deviennent pas la
propriété de root. Les clés (`OPENROUTER_API_KEY`, `SERPER_API_KEY`) sont déjà
dans `scraper/.env`. Une configuration écrite à la main doit être en UTF-8.

| Option | Effet |
|---|---|
| `--pilot` | modèle OpenRouter qui pilote (`z-ai/glm-5.3-flash` par défaut, `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`…) |
| `--effort` | effort de raisonnement du pilote (`low` par défaut, vide pour celui du modèle) |
| `--max-turns`, `--max-pages`, `--max-depth`, `--max-searches` | les plafonds de l'exploration (60 tours, 40 pages, 3 clics, 20 recherches par défaut) |
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
.venv/bin/python -m sortiesbot --config configs/agent-exemple.yaml --forget
.venv/bin/python -m agentbot   --config configs/agent-exemple.yaml --forget
.venv/bin/python -m agentbot   --config configs/agent-exemple.yaml --forget --pilot anthropic/claude-haiku-4.5
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

## Ce que le premier run réel a appris

Le Havre, 0-4 ans, GLM : 24 tours, 0,023 $, 3 sorties retenues dont **une
seule** pour des tout-petits. Quatre corrections en sont sorties :

- **le pilote vérifie l'âge, la période et la zone avant de proposer** — il
  avait retenu deux sorties « dès 6 ans ». Le prompt le lui demande, et
  l'extraction lui montre « âge non précisé » avec le début de la description
  quand la fiche n'a pas d'âge ;
- **`finish` rappelle une fois les pages de sortie jamais extraites** — la
  meilleure piste du run (des lectures du samedi pour les tout-petits) avait
  été ouverte au tour 2 et oubliée ;
- **20 recherches par défaut au lieu de 8** — c'est le quota de recherches, pas
  le budget, qui avait arrêté le run, à 5 % du budget dépensé. Le prompt
  demande aussi des requêtes simples : les guillemets et les `OR` en avaient
  gâché plusieurs ;
- **les liens de menu perdent leur contexte et passent en fin de liste** — un
  contexte partagé par trois liens ou plus est celui d'un menu. Il noyait les
  listes, et faisait passer tous les liens du menu au filtre « jeune public ».

## Ce qui n'est pas vérifié

- **La capacité d'un modèle « flash » à piloter soixante tours.** C'est la
  vraie question du prototype, et seuls des runs y répondront.
- **Le cache chez les hébergeurs de GLM.** L'élagage est conçu pour le
  préserver là où il existe ; rien ne garantit qu'il existe.
