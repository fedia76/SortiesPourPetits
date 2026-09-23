"""Le second scraper : un agent qui choisit lui-même où chercher.

`sortiesbot` est un **pipeline** : l'ordre des huit étages est écrit dans
`Run.chain()`, et le modèle n'est appelé qu'à des endroits fixes, pour trancher
un point précis. Ce paquet-ci pose la question inverse : et si c'était le
modèle qui décidait de la prochaine étape ?

Ce qui change, et seulement ça :

* **Le pilote.** Un modèle — GLM par défaut, n'importe quel modèle d'OpenRouter
  sachant appeler des outils — reçoit l'objectif du run et une boîte à outils.
  À chaque tour, il choisit un outil ; le code l'exécute et lui rend le
  résultat. Il décide de reformuler une recherche, de creuser un site, de
  descendre de deux clics, de s'arrêter.

Ce qui ne change pas, délibérément :

* **Les outils sont les briques de `sortiesbot`, importées telles quelles.**
  Ouvrir une page, c'est l'étage 2 ; lister ses liens, l'étage 3 ; en tirer
  des fiches, les étages 5 et 6 ; les proposer, les étages 7 et 8. Pas une
  ligne de `sortiesbot` n'a été modifiée pour ça. Deux scrapers qui ne
  différeraient que par leur façon de télécharger ou d'extraire ne se
  compareraient pas : on mesurerait le téléchargement, pas l'idée d'agent.
* **Le modèle ne voit jamais une page.** Il manipule des références (`r3`,
  `p2`, `l14`, `f5`) et des résumés de quelques lignes. Le texte des pages
  reste dans l'état du run, et c'est l'extraction — un appel séparé, dans un
  contexte neuf — qui le lit. C'est la leçon de la première version agentique
  du projet : 2,35 $ pour six sorties, parce que chaque tour refacturait des
  pages entières.
* **Les garde-fous sont dans le code.** Budget, nombre de tours, profondeur,
  pages ouvertes : un outil qui dépasse refuse de s'exécuter et le dit. Un
  pilote ne peut pas non plus ouvrir une adresse qu'aucun outil ne lui a
  rendue — il lui est matériellement impossible d'en inventer une.

Rien n'est proposé au site : l'agent ne tourne qu'en essai, et sa mémoire des
pages vues est séparée de celle du pipeline. Sans cette séparation, il sauterait
tout ce que le pipeline a déjà lu, et la comparaison serait faussée d'office.

Point d'entrée : `python -m agentbot --config configs/agent-exemple.yaml`.
"""
