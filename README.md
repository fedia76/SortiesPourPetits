# SortiesPourPetits 🎈

Des idées de sorties avec des enfants en Île-de-France, proposées par la
communauté et validées par une équipe de modération.

## Stack

| Couche | Techno |
|---|---|
| Front | Vue 3 + TypeScript + Vite, Pinia, Vue Router |
| Back | Node.js + TypeScript, Express |
| BDD | MySQL 8 (ou MariaDB), accès via Prisma |
| Géocodage | [API Adresse](https://adresse.data.gouv.fr/api-doc/adresse) (gratuite, sans clé) |
| Photos | Upload local, redimensionnement WebP via sharp |

## Fonctionnalités

- **Comptes** : inscription / connexion (cookie de session httpOnly), trois
  niveaux — `USER` (propose des sorties), `MODERATOR` (approuve ou refuse),
  `ADMIN` (gère les rôles des utilisateurs).
- **Sorties** : titre, description, prix ou gratuit, photo, tranche d'âge,
  dates de début/fin, horaires d'ouverture par jour, intérieur/extérieur/les
  deux, lieu géolocalisé.
- **Modération** : toute proposition passe en attente ; seules les sorties
  approuvées sont publiques. Une modification par l'auteur repasse en
  modération. Motif de refus visible par l'auteur.
- **Recherche** : texte, gratuit / prix max, âge de l'enfant, période, cadre,
  et **distance** (rayon en km autour d'une adresse ou de la position du
  navigateur — formule de Haversine en SQL).

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
| POST | `/api/moderation/:id` | modérateur | `{action: "approve"\|"reject", reason?}` |
| GET | `/api/admin/users` | admin | Liste des utilisateurs |
| PATCH | `/api/admin/users/:id/role` | admin | Changer un rôle |

## Production

```bash
cd server && npm run build && npm start   # API compilée
cd client && npm run build                # fichiers statiques dans client/dist
```

Servez `client/dist` derrière un reverse proxy (nginx, Caddy…) qui route
`/api` et `/uploads` vers l'API Node.
