# Scraper — recherche automatique de sorties

Script Python autonome qui cherche des sorties pour enfants sur le web et les
propose au site comme n'importe quel programme tiers : via `POST /api/events`
avec une clé d'API. Les sorties trouvées arrivent **en attente de modération**,
jamais publiées directement.

Seule la recherche passe par l'API Claude (outil serveur `web_search`) : le
téléchargement des pages et l'extraction de leurs liens se font en Python, et
le modèle n'intervient que pour trancher — trier des liens, remplir une fiche.

## Installation

Sur le VPS, rien à faire : le déploiement automatique envoie le dossier, crée
l'environnement virtuel et écrit le `.env` depuis les secrets GitHub (voir
[`deploy/README.md`](../deploy/README.md)). Les instructions ci-dessous sont
pour une installation locale.

```bash
cd scraper
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # + ".[dev]" pour les tests
cp .env.example .env        # puis renseignez les clés
```

`.env` :

| Variable | Rôle |
|---|---|
| `ANTHROPIC_API_KEY` | clé de l'API Claude |
| `SPP_API_URL` | URL du site (défaut `http://localhost:3000`) |
| `SPP_API_KEY` | clé `spp_…` créée depuis la page « Clés d'API » du site |

La clé du site hérite du rôle de son compte : rattachez-la à un compte dont les
propositions doivent passer par la modération.

## Utilisation

Deux façons de lancer une recherche, le même pipeline derrière :

| | Console du site | Ligne de commande |
|---|---|---|
| Configuration | table `ScraperConfig`, éditée dans **Recherche auto** | fichier YAML de `configs/` |
| Déclenchement | bouton « Essai » ou « Lancer et proposer » | `python -m sortiesbot` |
| Mémoire des pages | table `ScrapedUrl`, **commune à toutes les recherches** | SQLite local `state/seen.sqlite3` |
| Journal | consultable dans la console, page par page | fichiers de `runs/` |

La console est le mode normal ; la ligne de commande sert à mettre au point une
configuration ou à rejouer un run.

### Depuis la console (worker)

Le worker tourne en service sur le VPS et attend le travail :

```bash
python -m sortiesbot.worker          # boucle, une passe toutes les 30 s
python -m sortiesbot.worker --once   # traite au plus une exécution, puis sort
```

Il réclame l'exécution en attente (`POST /api/scraper/next`), joue la
recherche avec la configuration que le site lui donne, rend compte page par
page (`/runs/:id/items`) puis clôt l'exécution avec ses compteurs
(`/runs/:id/finish`). Il ne décide de rien : tout se règle dans la console.

Une exécution est close **quoi qu'il arrive**, y compris sur un plantage :
sans clôture elle resterait « En cours » dans la console, et bloquerait toute
nouvelle exécution de la même configuration.

### En ligne de commande

```bash
# Dry-run (défaut) : rien n'est envoyé au site.
python -m sortiesbot --config configs/spectacles-weekend.yaml

# Soumission réelle, une fois le JSON du dry-run relu.
python -m sortiesbot --config configs/spectacles-weekend.yaml --submit
```

**Un run dure plusieurs minutes.** L'étage découverte enchaîne une dizaine de
recherches et de lectures de pages dans un seul appel, côté Anthropic ; il faut
le laisser aller au bout. La console affiche le temps écoulé en tête de chaque
ligne et se remplit au fur et à mesure — résumé du raisonnement, puis chaque
recherche et chaque page ouverte. Si rien n'apparaît pendant plus d'une minute,
c'est anormal ; sinon, c'est que ça travaille.

| Option | Effet |
|---|---|
| `--submit` | propose réellement les sorties (sinon rien n'est envoyé) |
| `--limit N` | plafonne le nombre de sorties du run |
| `--quiet` | pas de sortie console (le journal reste écrit) |
| `--forget` | ignore la mémoire des URLs déjà vues, pour rejouer un run |
| `--runs-dir`, `--state` | emplacements du journal et de la mémoire |

Chaque run écrit deux fichiers dans `runs/` :

- `<horodatage>_<config>.jsonl` — le **journal détaillé** : chaque requête
  lancée, chaque page ouverte, chaque page écartée et pourquoi, chaque
  géocodage, chaque soumission, et la consommation de jetons par étage ;
- `<horodatage>_<config>.json` — les **sorties retenues**, payload prêt pour
  l'API, à relire avant de relancer avec `--submit`.

## Comment ça marche

### Le partage des rôles

Python fait tout ce qui est mécanique — télécharger, parser, extraire des
liens — et ne coûte rien. Le modèle n'intervient qu'aux trois moments où il
faut du jugement, et **aucun de ces appels ne boucle** :

```
1. recherche        modèle + web_search   → pages à ouvrir, classées
                                            « agenda » ou « sortie »
   ├─ sortie  ─────────────────────────────────────────┐
   └─ agenda                                           │
2. téléchargement   Python                → HTML       │           gratuit
3. extraction liens Python (BeautifulSoup)→ (texte, url, contexte)  gratuit
4. sélection        modèle, sans outil    → liens menant à une sortie
                                                       │
5. lecture + fiche  Python puis modèle ◀───────────────┘
                                          → sortie structurée
   puis géocodage, validation, photo, soumission — sans modèle
```

Une recherche ne remonte pas que des agendas : elle tombe régulièrement sur la
page d'une sortie précise. Le modèle classe donc chaque page retenue, et une
sortie trouvée directement court-circuite les étapes 2 à 4. S'il se trompe et
qu'un « agenda » ne donne aucun lien, la page est relue comme une sortie — elle
est déjà téléchargée, la lire coûte 0,004 $, l'ignorer coûte la sortie.

C'est ce découpage qui rend le coût prévisible. La version précédente confiait
toute la procédure à un seul appel agentique : le modèle ouvrait les pages
lui-même, et la boucle serveur d'Anthropic refacturait tout le contexte
accumulé à chacune de ses itérations. Un run mesuré à **2,35 $** pour six
sorties, dont 2,29 $ de jetons d'entrée — un million de jetons pour six
recherches et cinq pages.

### Étape 3, en détail

Une page d'agenda, ce qu'on y cherche, ce sont ses liens. Les faire lire au
modèle coûtait 12 000 jetons par page ; BeautifulSoup les extrait pour rien :

```python
for lien in soup.find_all("a", href=True):
    texte  = lien.get_text(strip=True)          # "Les Caprices de l'enfant roi"
    url    = urljoin(page, lien["href"])
    autour = lien.find_parent(...).get_text()   # "jusqu'au 30 août — Théâtre de Vanves"
```

Le contexte est le gain caché : les agendas affichent la date et le lieu à
côté du titre, donc l'étape 4 tranche souvent **sans ouvrir la page**.

Un premier tri mécanique retire ensuite le bruit évident — liens vides, ancres,
`mailto:`, liens sortants, textes de moins de 15 caractères (« Accueil »,
« Contact »), chemins de service (`/mentions-legales`, `/cgu`, `/newsletter`…),
doublons. Il n'a pas à être parfait : il doit réduire deux cents liens à une
cinquantaine pour que le modèle en juge à moindre coût.

### Étape 4 : le modèle répond par des numéros

Les liens lui sont soumis numérotés, et il renvoie les numéros retenus — jamais
des URL. **Il lui est donc matériellement impossible d'en inventer une**, ce qui
était un vrai problème dans la version précédente. Sa réponse tient en quelques
jetons.

### La mémoire des pages analysées

Une page lue est une page payée : la relire, c'est repayer. Toute page dont le
sort est **définitif** est donc mémorisée, et plus jamais rouverte — par aucune
recherche, la mémoire étant commune à toutes les configurations. C'est ce qui
fait que dix recherches spécialisées se complètent au lieu de se répéter.

Restent journalisées mais **non** mémorisées les décisions provisoires, qui ne
doivent pas empêcher un run ultérieur de traiter la page :

| Décision | Mémorisée ? | Pourquoi |
|---|---|---|
| `submitted` — proposée au site | oui | c'est fait |
| `irrelevant` — pas une sortie | oui | la page ne changera pas de nature |
| `invalid` — inexploitable | oui | idem |
| `out_of_period`, `out_of_area` | oui | écartée sciemment (run strict) |
| `dry_run` — retenue à l'essai | non | sinon le run réel la sauterait |
| `seen`, `duplicate` | non | c'est la décision d'origine qui compte |
| `blocked` — domaine bloqué | non | un réglage, pas un jugement |
| `error` — site ou API injoignable | non | demain ça remarchera peut-être |

La clé de mémorisation est l'URL normalisée (schéma, `www.`, barre finale et
paramètres de suivi retirés) ; le lien exact, lui, reste affiché et cliquable
dans la console.

### Politesse

Puisque le scraper télécharge lui-même, il assume ce qu'Anthropic assumait :
`robots.txt` est lu et respecté, un `User-Agent` identifie le robot et renvoie
vers le site, et une seconde sépare deux requêtes vers le même hôte.

### Champs laissés à la modération

Une information introuvable ne fait pas perdre la sortie : elle est proposée
avec une valeur convenue que le site reconnaît
(`server/src/lib/incomplete.ts`).

| Information | Valeur envoyée | Effet côté site |
|---|---|---|
| Position (géocodage en échec ou hors zone) | `lat = 0`, `lng = 0` | invisible dans les recherches par distance ; bandeau « lieu non géolocalisé » |
| Tarif introuvable sur la page | `price = -1`, `isFree = false` | badge « Tarif à compléter » au lieu du prix ; bandeau « tarif indéterminé » |

Dans les deux cas, **l'approbation est refusée** tant qu'un modérateur n'a pas
corrigé le champ, et le bandeau pointe vers le formulaire d'édition.

## La configuration oriente, elle ne filtre pas

Thème, période et zone servent aux deux premières étapes : formuler les
recherches, trier les liens. C'est là qu'ils font gagner du temps et de
l'argent, en évitant d'ouvrir des pages sans intérêt.

Passé l'extraction, ils ne servent plus à rien — parce que la page est
**déjà lue et déjà payée**. L'écarter parce qu'elle déborde de la fenêtre,
c'est payer pour ne rien garder, alors que le site sait filtrer par date et
par distance, et qu'un modérateur relit chaque proposition.

Une recherche « spectacles de ce week-end » qui croise un atelier de musée
programmé dans trois mois le rapporte donc quand même. Plusieurs
configurations spécialisées (musée, spectacle, fête foraine…) se complètent
ainsi : chacune ratisse son thème et ramasse au passage ce que les autres
auraient manqué. `keep_out_of_scope: false` rétablit la rigueur d'une fenêtre
stricte si une configuration en a besoin.

Le géocodeur suit la même logique : il vérifie que la position trouvée est en
France — une homonymie, il y a un Montreuil au Québec — mais plus qu'elle est
dans les départements visés.

## Configuration

Une configuration = un fichier YAML dans `configs/` (voir
`spectacles-weekend.yaml`, commenté). Seules `name` et `theme` sont
obligatoires. Les prompts eux-mêmes sont des clés de la configuration
(`search_prompt`, `select_prompt`, `extraction_prompt`) : on peut les réécrire
sans toucher au code — les variables disponibles sont listées en tête de
`sortiesbot/prompts.py`.

Le choix des modèles est par configuration (`search_model`, `select_model`,
`extraction_model`), ce qui permet de comparer les coûts d'une recherche à
l'autre.

**Pourquoi Haiku partout.** Haiku 4.5 échoue dès qu'on lui demande de dérouler
une procédure en plusieurs temps — essayé trois fois : il cherche puis conclut
sans rien ouvrir, ou répond de mémoire sans chercher. Il est en revanche
parfaitement à l'aise sur une tâche bornée. Le pipeline actuel n'en contient
que : chercher, trier une liste, remplir un formulaire. C'est le découpage qui
permet le modèle bon marché, pas l'inverse.

Le seul outil serveur encore utilisé est `web_search_20250305`, la variante de
base : le filtrage dynamique des variantes récentes servait à alléger les pages
que le modèle lisait, et il ne lit plus de pages.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest
```

Aucun test n'appelle le réseau : le fournisseur Claude est branché sur un
serveur HTTP local qui enregistre les requêtes, ce qui verrouille la forme de
ce qui est envoyé (outils serveur, format structuré, reprise après
`pause_turn`) sans dépenser de jetons.

## Coût d'un run

Trois postes seulement, tous bornés :

| Poste | Prix |
|---|---|
| Recherches web | 0,01 $ pièce (`max_searches`, 6 par défaut) |
| Téléchargement et dépouillement des agendas | **0 $** — c'est du Python |
| Sélection des liens | ~0,005 $ par agenda |
| Lecture d'une sortie | ~0,006 $ par sortie |

Soit de l'ordre de **0,20 $ pour un run complet de vingt sorties**. Aucun appel
n'ayant d'outil hormis la recherche, il n'y a plus de boucle serveur, donc plus
de contexte refacturé — c'est un changement de mécanisme, pas un réglage.

`max_cost_usd` (1 $ par défaut) arrête le run avant un appel payant s'il est
dépassé ; ce qui a déjà été trouvé est conservé dans le JSON. Le journal
totalise jetons, recherches et coût, par étape.

Pour mémoire, les mesures des versions précédentes : 3,24 $ avec Opus 5 et des
pages de 30 000 jetons, 2,35 $ avec Sonnet 5 — dans les deux cas, la boucle
serveur refacturant le contexte accumulé à chaque itération.

## Et ensuite

1. un déclenchement périodique des configurations (le worker sait déjà exécuter
   ce qu'on lui met en file ; il manque qui l'y met, et quand) ;
2. un fournisseur OpenRouter — l'interface `Provider` (trois méthodes) est déjà
   en place pour ça, et seule la recherche y demande un outil ;
3. un second script en liste blanche, alimenté par les domaines dont les
   sorties ont été le plus souvent approuvées.
