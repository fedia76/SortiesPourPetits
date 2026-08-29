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
  c'est là qu'elle se lit en entier. La file entière peut aussi être
  **supprimée** d'un coup, ce qui n'est pas la refuser : rien n'est gardé, et
  c'est ce qu'on veut après un import raté.
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
- **Statistiques du scraping** : par recherche ou toutes confondues, la part
  de chaque domaine source — avec ce qu'il a réellement donné, et pas
  seulement ce qu'il a coûté à lire — et la part de chaque catégorie, qui dit
  ce qu'aucune recherche ne couvre.
- **Import automatique** : un [scraper](scraper/README.md) cherche des sorties
  sur le web via l'API Claude et les propose au même titre qu'un visiteur, avec
  une clé d'API. Ce qu'un import n'a pas su déterminer part avec une valeur
  convenue plutôt que de faire perdre la sortie — adresse non géocodée en
  `(0, 0)`, tarif introuvable à `-1` : la modération les signale et refuse
  l'approbation tant qu'ils ne sont pas complétés.

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
| GET | `/api/moderation/pending` | modérateur | File d'attente |
| DELETE | `/api/moderation/pending` | modérateur | Vider la file — supprime, ne refuse pas (`expected`) |
| GET | `/api/moderation/:id/similar` | modérateur | Doublons potentiels (`radiusKm`, `minScore`, `limit`) |
| POST | `/api/moderation/:id` | modérateur | `{action: "approve"\|"reject", reason?}` |
| GET | `/api/categories` | public | Liste des catégories |
| POST / PATCH / DELETE | `/api/categories[/:id]` | admin | Gérer les catégories |
| GET | `/api/scraper/stats` | modérateur | Statistiques du scraping (`configId`, `days`) |
| GET | `/api/scraper/memory` | modérateur | Mémoire des pages analysées (`q`, `decision`, `page`) |
| DELETE | `/api/scraper/memory` | modérateur | Oublier des pages (`decision` pour n'en purger qu'un lot) |
| GET | `/api/admin/users` | admin | Liste des utilisateurs |
| PATCH | `/api/admin/users/:id/role` | admin | Changer un rôle |

## Production

```bash
cd server && npm run build && npm start   # API compilée
cd client && npm run build                # fichiers statiques dans client/dist
```

Servez `client/dist` derrière un reverse proxy (nginx, Caddy…) qui route
`/api` et `/uploads` vers l'API Node.

Déploiement automatisé sur un VPS via GitHub Actions : voir
[`deploy/README.md`](deploy/README.md) (setup serveur en une fois) et
[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) (build + push
à chaque `git push` sur `main`).
