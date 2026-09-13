# Documentation

Deux natures de documents vivent ici, et les confondre fait croire qu'un chiffre
d'août dit encore quelque chose aujourd'hui.

## La référence du banc, tenue à jour

[`banc-evaluation.md`](banc-evaluation.md) — le banc d'évaluation : les trois
choses qui ne se mélangent pas (corpus, run, mesure), ce que le corpus contient,
comment chacun des étages 2 à 6 se mesure, ce que la modération donne
gratuitement, et **ce qui reste limité**. Il suit le code, comme le [README du
scraper](../scraper/README.md) suit le pipeline.

## Les analyses illustrées, datées

Cinq pages HTML autonomes, à ouvrir dans un navigateur (double-clic sur le
fichier suffit : tout est embarqué, y compris les schémas, qui sont du SVG
écrit à la main). Elles s'affichent en clair ou en sombre selon le thème du
système.

Elles ne remplacent pas les README, qui restent la référence pour **installer
et faire tourner** le projet. Elles répondent à l'autre question : *comment ça
marche, et pourquoi c'est fait comme ça*.

| Document | Ce qu'il explique |
|---|---|
| [`scraper-briques.html`](scraper-briques.html) | **La planche à jour du pipeline**, en six feuilles A4 imprimables : les huit briques, et pour chacune ce qu'elle reçoit et rend, ce qu'elle fait, **ce qu'elle écarte au passage** et ce qui arrive quand elle rate — plus la cardinalité de chaque étage, les garde-fous et ce qu'un run laisse derrière lui. |
| [`scraper-evaluation.html`](scraper-evaluation.html) | **Comment mesurer ces huit briques** : l'unité évaluée et l'origine de l'étiquette pour chacune, pourquoi le rappel n'est aujourd'hui pas observable, les cinq façons d'en sortir, et l'ordre dans lequel s'y prendre. |
| [`scraper-posters.html`](scraper-posters.html) | Deux planches d'une page, à lire d'un coup d'œil. **Le scraper, étage par étage** : les six briques, ce que chacune reçoit et rend, qui travaille et qui paie, les garde-fous et les plafonds. **Du run au modèle maison** : ce que la base de données garde déjà d'exploitable pour entraîner un modèle, ce qu'il faudrait reconstruire, et dans quel ordre s'y prendre. |
| [`scraper-anatomie.html`](scraper-anatomie.html) | Le document long. Le partage Python / modèle et pourquoi aucun appel ne boucle, les six étages en détail, **où part l'argent** poste par poste, les économies à faire avant toute chose, ce qu'un modèle maison voudrait dire concrètement (distillation, cascade), et pourquoi ce n'est probablement pas l'extraction qu'il faudrait viser en premier. |
| [`fabriquer-le-modele.html`](fabriquer-le-modele.html) | Le mode d'emploi, écrit pour quelqu'un qui ne connaît pas l'apprentissage automatique. Ce qu'« entraîner » veut dire, les trois familles de modèles envisageables (classifieur, étiqueteur de spans, générateur *fine-tuné*), lesquelles partent de zéro et lesquelles d'un modèle existant, puis le *fine-tune* étape par étape — et ce qui va mal se passer. |

## Leur statut

`scraper-briques.html` s'imprime : chaque feuille est une page A4 portrait, et
rien ne se coupe en deux — une fiche qui ne tient pas dans la place restante
passe entière à la page suivante. Marges par défaut, graphiques d'arrière-plan
activés, et le thème sombre reste à l'écran.

Ce sont des **documents d'analyse, datés**, pas des spécifications. Les trois
premiers ont été écrits fin août 2026, les deux planches sur les huit briques
en septembre — à partir du code de l'époque et des tarifs alors publiés par
Anthropic. Deux conséquences :

* les **chiffres** — coût d'un run, prix au million de jetons, tarif d'une
  recherche web — vieillissent. Le code, lui, dit toujours la vérité :
  `models.SEARCH_PRICE_USD` et les tables de prix de
  `providers/anthropic_provider.py` ;
* le **verdict** sur le modèle maison est une recommandation, pas une décision
  prise. Rien n'a été implémenté dans ce sens.

Le **nombre d'étages** a bougé depuis : `scraper-posters.html` et
`scraper-anatomie.html` dessinent encore les six briques d'alors. Deux se sont
ajoutées après — la *reconnaissance* (étage 2), qui constate la nature d'une
page sur son HTML, et l'*attribution* (étage 7), qui remonte d'un agrégateur à
la page de l'organisateur. Ce que ces deux documents disent des six autres
reste juste ; pour les huit, c'est `scraper-briques.html` qui fait foi.

`scraper-evaluation.html` a changé de statut depuis, et c'est celui qui a le plus
vieilli. Le banc qu'il recommandait **existe** : la console `/admin/evaluation`
mesure aujourd'hui les étages **3** (dépouillement), **4** (tri), **5** (lecture)
et **6** (extraction) — l'étage **2** a son corpus, mais pas encore de run qui le
rejoue. Ce qu'il dit des trois autres
reste une recommandation, ses **chiffres** restent des ordres de grandeur, et sa
description du banc est dépassée sur un point qui compte : les étiquettes ne sont
plus des verdicts (« le tarif rendu est juste ») mais des faits (« la page annonce
8 € »), ce qui a séparé le corpus des runs. C'est
[`banc-evaluation.md`](banc-evaluation.md) qui fait foi pour le banc.

La description du pipeline, elle, est tenue à jour avec le code : le tableau
des huit étages du [README du scraper](../scraper/README.md) et le vocabulaire
de `sortiesbot/stages/__init__.py` en sont la source, et la console
d'administration dessine son graphe à partir du même vocabulaire — c'est ce
qui garantit qu'elle, au moins, ne peut pas dater.
