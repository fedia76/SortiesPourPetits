# Scraper — recherche automatique de sorties

Script Python autonome qui cherche des sorties pour enfants sur le web et les
propose au site comme n'importe quel programme tiers : via `POST /api/events`
avec une clé d'API. Les sorties trouvées arrivent **en attente de modération**,
jamais publiées directement.

La recherche et la lecture des pages sont confiées aux outils serveur
`web_search` et `web_fetch` de l'API Claude : c'est l'infrastructure d'Anthropic
qui va sur le web, le script n'embarque ni navigateur ni analyseur HTML.

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

```
découverte → filtre (domaines bloqués, URLs déjà vues) → extraction
  → géocodage → construction du payload → photo → soumission
```

1. **Découverte** (`claude-opus-5` par défaut) — plusieurs recherches web
   variées, puis lecture des pages d'agenda rencontrées pour en tirer les liens
   d'événements. C'est l'étage qui découvre des sites qu'on n'aurait pas listés.
2. **Filtre** — les domaines bloqués et les URLs déjà traitées lors d'un run
   précédent sont écartées **avant** l'extraction : une page connue ne coûte
   jamais un second jeton. La mémoire est un SQLite dans `state/`.
3. **Extraction** (`claude-haiku-4-5` par défaut) — une page, une sortie
   structurée. Tâche bornée, donc un modèle plus modeste suffit.
4. **Géocodage** — Photon (OpenStreetMap), le même fournisseur que le
   formulaire du site. Une position hors des départements attendus est traitée
   comme un échec : mieux vaut pas de position qu'une position fausse.
5. **Payload** — les règles de `server/src/lib/validators.ts` sont appliquées
   ici. Ce qui peut être réparé l'est (troncatures, âges inversés, horaires
   incohérents) ; ce qui manque part avec une valeur convenue que la modération
   sait reconnaître (voir ci-dessous). Seules les pages inexploitables — sans
   titre, sans description, sans date — sont écartées, motif à l'appui dans le
   journal.
6. **Soumission** — avec la photo trouvée sur la page, le cas échéant. Les
   droits d'usage de l'image ne sont pas vérifiables automatiquement : le
   `sourceUrl` accompagne la sortie et c'est le modérateur qui tranche.

### Champs laissés à la modération

Une information introuvable ne fait pas perdre la sortie : elle est proposée
avec une valeur convenue que le site reconnaît
(`server/src/lib/incomplete.ts`).

| Information | Valeur envoyée | Effet côté site |
|---|---|---|
| Position (géocodage en échec ou hors zone) | `lat = 0`, `lng = 0` | invisible dans les recherches par distance ; bandeau « lieu non géolocalisé » |
| Tarif introuvable sur la page | `price = -1`, `isFree = false` | badge « Tarif à compléter » au lieu du prix ; bandeau « tarif indéterminé » |

Dans les deux cas, **l'approbation est refusée** tant qu'un modérateur n'a pas
corrigé le champ, et le bandeau pointe vers le formulaire d'édition, qui repart
d'un champ vide pour forcer une vraie saisie.

## Configuration

Une configuration = un fichier YAML dans `configs/` (voir
`spectacles-weekend.yaml`, commenté). Seules `name` et `theme` sont
obligatoires. Les prompts eux-mêmes sont des clés de la configuration
(`discovery_prompt`, `extraction_prompt`) : on peut les réécrire entièrement
sans toucher au code — les variables disponibles sont listées en tête de
`sortiesbot/prompts.py`.

Le choix des modèles est par configuration (`discovery_model`,
`extraction_model`), ce qui permet de comparer les coûts d'une recherche à
l'autre.

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

Le journal totalise les jetons consommés par étage et leur prix. **La
facturation des recherches web n'y est pas estimée** — le journal compte les
recherches lancées, c'est le relevé de la console Anthropic qui fait foi.
`max_searches`, `max_fetches` et `max_events` bornent un run.

## Et ensuite

Ce script est la première étape. La suite prévue :

1. tables `ScraperConfig` / `ScraperRun` / `ScraperRunItem` côté site, avec les
   configurations et les journaux consultables depuis la console
   d'administration (le JSONL est déjà écrit dans ce format) ;
2. un worker `systemd` sur le VPS qui prend les runs mis en file par la console
   et porte le cron des configurations ;
3. un fournisseur OpenRouter (`openrouter:web_search` / `openrouter:web_fetch`,
   utilisables par n'importe quel modèle) — l'interface `Provider` est déjà en
   place pour ça ;
4. un second script en liste blanche, alimenté par les domaines dont les
   sorties ont été le plus souvent approuvées.
