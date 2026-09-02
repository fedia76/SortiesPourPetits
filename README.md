# SortiesPourPetits 🎈

Des idées de sorties avec des enfants en Île-de-France, proposées par la
communauté et validées par une équipe de modération.

## Stack

| Couche | Techno |
|---|---|
| Front | Vue 3 + TypeScript + Vite, Pinia, Vue Router |
| Back | Node.js + TypeScript, Express |
| BDD | MySQL 8 (ou MariaDB), accès via Prisma |
| Géocodage | [Photon](https://photon.komoot.io) (OpenStreetMap, gratuit, sans clé ; l'[API Adresse](https://adresse.data.gouv.fr/api-doc/adresse) reste sélectionnable dans `client/src/lib/geocode.ts`) |
| Photos | Upload local, redimensionnement WebP via sharp |
| Scraper | Python 3.10+, BeautifulSoup, API Claude (`web_search`) — voir [`scraper/`](scraper/README.md) |

## Fonctionnalités

- **Comptes** : inscription / connexion (cookie de session httpOnly), trois
  niveaux — `USER` (propose des sorties), `MODERATOR` (approuve ou refuse),
  `ADMIN` (gère les rôles des utilisateurs).
- **Sorties** : titre, description, prix ou gratuit, photo, lien vers la
  source de l'événement (facultatif), tranche d'âge (facultative), dates de
  début/fin ou événement permanent (facultatives), horaires d'ouverture par
  jour et cadre intérieur/extérieur/les deux (facultatifs), lieu géolocalisé.
  Les jours de représentation se prennent au calendrier, plusieurs d'affilée :
  un spectacle qui se joue quinze fois se saisit en quinze clics.
- **Modération** : toute proposition passe en attente ; seules les sorties
  approuvées sont publiques. Une modification par l'auteur repasse en
  modération. Motif de refus visible par l'auteur. Un modérateur tranche
  depuis la file d'attente ou directement depuis la fiche de la sortie —
  c'est là qu'elle se lit en entier. La file se **filtre par origine** —
  propositions des visiteurs, ou d'une recherche automatique précise : comme
  une recherche couvre un territoire, c'est la façon de modérer une région à
  la fois. La file peut aussi être **supprimée** d'un coup, ce qui n'est pas
  la refuser : rien n'est gardé, et c'est ce qu'on veut après un import raté.
  Le filtre s'applique alors aussi à la suppression — une file restreinte ne
  laisse pas partir ce qu'elle masquait.
- **Détection de doublons** : pour chaque sortie de la file, les sorties
  ressemblantes sont cherchées automatiquement et notées sur 100 (même lieu ou
  lieu proche, titre et description, chevauchement des dates, catégorie,
  auteur). Le modérateur voit les raisons du rapprochement et peut refuser en
  pointant la sortie d'origine, motif pré-rempli.
- **Recherche** : texte, gratuit / prix max, âge de l'enfant, période, cadre,
  et **distance** (rayon en km autour d'une adresse ou de la position du
  navigateur — formule de Haversine en SQL).
- **Mémoire du scraper** : les pages déjà analysées sont consultables et
  filtrables par verdict. Les oublier les rend à nouveau lisibles — utile pour
  relire un site qui était en panne, sans réexposer ce qui est déjà proposé.
- **Débogage d'une exécution** : depuis la page d'une exécution, une vue qui
  dessine le **graphe des six étages** du scraper — découverte, dépouillement,
  sélection, lecture, extraction, publication — avec, sur chaque brique, ce
  qu'elle reçoit, ce qu'elle rend, ce qu'elle a produit et combien de temps
  elle a pris. Le journal complet est en dessous : chaque requête lancée,
  chaque lien extrait puis retenu, chaque prompt envoyé, chaque jeton
  consommé. Un journal fait facilement mille lignes, alors on ne le lit pas
  d'un bloc : cliquer une brique ne garde que son étage, cliquer une ligne
  suit une page d'un bout à l'autre du pipeline, et les filtres se composent.
  Une seconde vue, en **arbre**, répond à l'autre question — d'où vient cette
  sortie : quelle requête a remonté quel agenda, quels liens il portait, lesquels
  le modèle a retenus, et ce que chaque page est devenue.
- **Statistiques du scraping** : par recherche ou toutes confondues, la part
  de chaque domaine source — avec ce qu'il a réellement donné, et pas
  seulement ce qu'il a coûté à lire — et la part de chaque catégorie, qui dit
  ce qu'aucune recherche ne couvre.
- **Import automatique** : un [scraper](scraper/README.md) cherche des sorties
  sur le web via l'API Claude et les propose au même titre qu'un visiteur, avec
  une clé d'API. Il sait aussi partir d'une adresse connue — le site d'un
  festival, la saison d'un théâtre — sans lancer la moindre recherche, et tirer
  d'une même page de programme toutes les sorties qu'elle annonce. Ce qu'un
  import n'a pas su déterminer part avec une valeur convenue plutôt que de
  faire perdre la sortie — adresse non géocodée en `(0, 0)`, tarif introuvable
  à `-1` : la modération les signale et refuse l'approbation tant qu'ils ne
  sont pas complétés. Tout ce qu'une exécution a produit — ses sorties et ce
  qu'elle a mémorisé — se supprime d'un bouton depuis sa page.

## Documentation illustrée

Trois pages HTML à ouvrir dans un navigateur, dans [`docs/`](docs/README.md) :
deux **planches** qui résument le scraper étage par étage, l'**anatomie**
détaillée du pipeline et de son coût, et un mode d'emploi pour **fabriquer un
modèle maison** à la place de Haiku. Ce sont des documents d'analyse datés, pas
des spécifications — leur statut est précisé dans l'index.

## Démarrage

Prérequis : Node 20+, MySQL 8 (ou MariaDB) en local.

```bash
# 1. Base de données
mysql -u root -p -e "CREATE DATABASE sortiespourpetits"

# 2. API
cd server
npm install
cp .env.example .env      # puis renseignez DATABASE_URL et JWT_SECRET
npx prisma migrate deploy # crée les tables
npm run db:seed           # comptes + sorties de démonstration (optionnel)
npm run dev               # API sur http://localhost:3000

# 3. Front (autre terminal)
cd client
npm install
npm run dev               # http://localhost:5173 (proxy /api vers :3000)
```

Comptes de démonstration créés par le seed (mot de passe `motdepasse`) :
`admin@example.com`, `modo@example.com`, `parent@example.com`.

## API

| Méthode | Route | Accès | Description |
|---|---|---|---|
| POST | `/api/auth/register` | public | Créer un compte |
| POST | `/api/auth/login` / `/logout` | public | Session |
| GET | `/api/auth/me` | connecté | Profil courant |
| GET | `/api/events` | public | Recherche multi-filtres (`q`, `free`, `priceMax`, `age`, `from`, `to`, `setting`, `lat`+`lng`+`radiusKm`, `page`) |
| GET | `/api/events/:id` | public | Détail (les non-approuvées : auteur/modérateurs) |
| GET | `/api/events/mine` | connecté | Mes propositions |
| POST | `/api/events` | connecté | Proposer (multipart : `data` JSON + `photo`) |
| PUT | `/api/events/:id` | auteur/modérateur | Modifier |
| DELETE | `/api/events/:id` | auteur/modérateur | Supprimer |
| GET | `/api/moderation/pending` | modérateur | File d'attente (`configId`, `origin=scraper\|visitors`) |
| DELETE | `/api/moderation/pending` | modérateur | Vider la file — supprime, ne refuse pas (`expected`, mêmes filtres) |
| GET | `/api/moderation/:id/similar` | modérateur | Doublons potentiels (`radiusKm`, `minScore`, `limit`) |
| POST | `/api/moderation/:id` | modérateur | `{action: "approve"\|"reject", reason?}` |
| GET | `/api/categories` | public | Liste des catégories |
| POST / PATCH / DELETE | `/api/categories[/:id]` | admin | Gérer les catégories |
| GET | `/api/scraper/stats` | modérateur | Statistiques du scraping (`configId`, `days`) |
| GET | `/api/scraper/runs/:id/logs` | modérateur | Journal détaillé d'une exécution (`stage`, `kind`, `level`, `url`, `q`, `after`, `limit`) |
| GET | `/api/scraper/runs/:id/graph` | modérateur | Les six étages du pipeline, avec ce que chacun a produit |
| GET | `/api/scraper/runs/:id/tree` | modérateur | L'arbre du run : requête → agenda → liens → sorties |
| DELETE | `/api/scraper/runs/:id/logs` | modérateur | Oublier le journal détaillé (les compteurs restent) |
| GET | `/api/scraper/memory` | modérateur | Mémoire des pages analysées (`q`, `decision`, `page`) |
| DELETE | `/api/scraper/memory` | modérateur | Oublier des pages (`decision` pour n'en purger qu'un lot) |
| DELETE | `/api/scraper/runs/:id/data` | modérateur | Supprimer ce qu'une exécution a produit : ses sorties et ce qu'elle a mémorisé (le journal reste) |
| GET | `/api/admin/users` | admin | Liste des utilisateurs |
| PATCH | `/api/admin/users/:id/role` | admin | Changer un rôle |

## Référencement

Le site est une application Vue : sans rien de plus, un moteur reçoit un
document vide, le même pour toutes les adresses, et ne trouve les sorties que
s'il exécute le JavaScript — ce que Google fait, tard et sans garantie. Les
fiches, elles, restaient hors d'atteinte : la liste se paginait par un bouton,
donc douze sorties étaient liées et pas une de plus.

L'API sert donc elle-même les pages publiques et les **pré-rend**
(`server/src/seo/`) : le document initial porte déjà le contenu de la page, ses
liens, son titre, sa description et ses données structurées. Vue s'y monte
ensuite et reprend la main. Tout le monde reçoit le même HTML — reconnaître les
robots pour leur en servir un autre n'est ni fiable ni recommandé.

Ce que cela donne, page par page :

| | Accueil (`/`, `/?page=N`) | Fiche (`/sorties/:id`) |
|---|---|---|
| Titre, description | propres à la page | titre de la sortie + sa ville |
| Contenu pré-rendu | les douze vignettes, en liens | la fiche entière |
| Données structurées | `WebSite`, `ItemList` | `Event` daté, ou `Place` si la sortie est permanente, + fil d'Ariane |
| Absente ou non approuvée | — | **404**, et non plus « 200, page vide » |

- **`/sitemap.xml`** liste l'accueil et toutes les sorties approuvées à venir.
  C'est le seul canal de découverte fiable pour un catalogue qui se compte en
  milliers de fiches.
- **`/robots.txt`** ouvre le site et ferme ce qui demande un compte. Hors
  production, il interdit tout : une préproduction indexée coûte des mois.
- **La page est dans l'adresse** (`/?page=2`) : c'est ce qui rend les sorties
  au-delà de la première page atteignables, par un moteur comme par un lien
  partagé.
- Les sorties **passées** sortent du sitemap, mais leur page reste servie.

Deux variables décident, côté serveur : `NODE_ENV=production` (sans elle, rien
n'est indexable) et `PUBLIC_BASE_URL` (l'adresse publique exacte, qui sert à
écrire les liens canoniques et le sitemap). Voir
[`server/.env.example`](server/.env.example).

Ce qui reste à faire pour aller plus loin est d'ordre éditorial : des pages par
ville, par catégorie ou par tranche d'âge — l'API sait déjà filtrer là-dessus,
il leur manque des adresses à elles — et une image de partage par défaut pour
l'accueil.

## Production

```bash
cd server && npm run build && npm start   # API compilée
cd client && npm run build                # fichiers statiques dans client/dist
```

L'API sert le front compilé : elle attend `client/dist` déposé dans un dossier
`client/` à côté d'elle (`CLIENT_DIR` pour une autre disposition). Le reverse
proxy garde les fichiers versionnés de `/assets/*` et lui passe tout le reste —
`/api`, `/uploads`, et les pages, qu'elle pré-rend. Voir
[`deploy/Caddyfile`](deploy/Caddyfile).

Déploiement automatisé sur un VPS via GitHub Actions : voir
[`deploy/README.md`](deploy/README.md) (setup serveur en une fois) et
[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) (build + push
à chaque `git push` sur `main`).
