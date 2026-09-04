# SortiesPourPetits 🎈

Des idées de sorties avec des enfants, proposées par la communauté et validées
par une équipe de modération. Quatre zones ouvertes à ce jour : Île-de-France,
Le Havre, Niort et Nancy.

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
  source de l'événement (facultatif — et, pour une sortie trouvée par la
  recherche automatique, celui de l'organisateur plutôt que de l'agenda qui la
  republiait, voir « Remonter à la source » dans le README du scraper),
  tranche d'âge (facultative), dates de début/fin ou événement permanent
  (facultatives), horaires d'ouverture par jour et cadre
  intérieur/extérieur/les deux (facultatifs), lieu géolocalisé.
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
  navigateur — formule de Haversine en SQL). Les résultats sont **classés par
  pertinence** et non plus par date : la précision de la tranche d'âge d'abord,
  la brièveté de la période ensuite, l'imminence en dernier — voir
  « Classer les résultats » plus bas.
- **Mémoire du scraper** : les pages déjà analysées sont consultables et
  filtrables par verdict. Les oublier les rend à nouveau lisibles — utile pour
  relire un site qui était en panne, sans réexposer ce qui est déjà proposé.
- **Débogage d'une exécution** : depuis la page d'une exécution, une vue qui
  dessine le **graphe des huit étages** du scraper — découverte,
  reconnaissance, dépouillement, sélection, lecture, extraction, attribution,
  publication — avec, sur chaque brique, ce
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
| GET | `/api/scraper/runs/:id/graph` | modérateur | Les huit étages du pipeline, avec ce que chacun a produit |
| GET | `/api/scraper/runs/:id/tree` | modérateur | L'arbre du run : requête → agenda → liens → sorties |
| GET | `/api/scraper/runs/:id/attribution` | modérateur | La mesure de l'étage 7 : où l'attribution trouve, et où elle perd |
| POST | `/api/scraper/events/:id/source` | modérateur | Chercher la source d'une sortie : l'étage 7 rejoué seul |
| GET | `/api/scraper/events/:id/source` | modérateur | L'état de la dernière recherche de source de cette sortie |
| DELETE | `/api/scraper/runs/:id/logs` | modérateur | Oublier le journal détaillé (les compteurs restent) |
| GET | `/api/scraper/memory` | modérateur | Mémoire des pages analysées (`q`, `decision`, `page`) |
| DELETE | `/api/scraper/memory` | modérateur | Oublier des pages (`decision` pour n'en purger qu'un lot) |
| DELETE | `/api/scraper/runs/:id/data` | modérateur | Supprimer ce qu'une exécution a produit : ses sorties et ce qu'elle a mémorisé (le journal reste) |
| GET | `/api/admin/users` | admin | Liste des utilisateurs |
| PATCH | `/api/admin/users/:id/role` | admin | Changer un rôle |

## Classer les résultats

Les résultats étaient rendus par date de début croissante. C'est un ordre
honnête, mais ce n'est pas une réponse à la question posée : un parent qui
cherche pour un enfant de quatre ans veut d'abord ce qui est **fait pour lui**,
et d'abord ce qui **ne repassera pas**.

Trois mesures, dans cet ordre d'importance
([`server/src/lib/relevance.ts`](server/src/lib/relevance.ts)) :

| Mesure | Ce qu'elle vaut | Poids |
|---|---|---|
| **Précision de l'âge** | 1 pour une tranche d'un an, 0 pour « ouvert à tous ». Seule l'étendue compte : « à partir de 4 ans » et « 4 à 16 ans » disent la même chose — la sortie accepte l'enfant sans être pensée pour lui | 6 |
| **Brièveté** | 1 pour une journée, ½ pour une semaine, 0 pour une sortie permanente | 3 |
| **Imminence** | 1 pour ce qui a lieu maintenant, ½ dans quinze jours, comptée depuis le début de la fenêtre demandée | 2 |

Le critère d'âge **se tait** quand aucun âge n'a été demandé : le classement se
joue alors sur la période seule, plutôt que de départager au hasard.

### Pourquoi un score et non trois tris enchaînés

Un tri lexicographique sur la précision de l'âge ferait basculer tout le
classement pour deux ans d'écart de tranche : « 3 à 5 » passerait devant
« 3 à 6 » quelles que soient leurs dates, et une sortie ponctuelle de ce
week-end se retrouverait sous une sortie tout public de l'an prochain.

Les poids disent donc l'ordre d'importance, pas une hiérarchie absolue. Une
sortie tout public d'un seul jour peut passer devant une sortie très ciblée qui
dure deux mois — et c'est voulu : **la seconde sera encore là au prochain
passage, la première non.**

### Où le calcul a lieu

En mémoire, pas en SQL. Le score mêle trois mesures dont deux dépendent de la
requête ; l'écrire en base reviendrait à recopier ces règles dans un langage où
personne n'irait les relire. La recherche relève donc cinq colonnes pour toutes
les sorties qui passent les filtres — pas les fiches — classe, puis ne charge en
entier que la page demandée. Le compte total tombe du même coup, sans seconde
requête. C'est déjà ce que fait le filtre de distance, pour la même raison.

Les ex æquo sont départagés par la date puis par l'identifiant. Sans cet ordre
total, deux pages successives pourraient montrer deux fois la même sortie, ou en
sauter une.

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

### Les pages de zone

Personne ne cherche « sortie enfant » tout court : on cherche « sortie enfant
Nancy ». Chaque zone a donc **sa page** — `/sorties/nancy` — avec son titre, son
texte de présentation et ses sorties, pré-rendue comme le reste. C'est elle
qu'un moteur peut proposer, là où l'accueil ne répond à personne en particulier
et où une fiche isolée ne parle que d'elle-même.

Une zone se définit par des **préfixes de code postal** (`75,77,78,91,92,93,94,95`
pour l'Île-de-France, `766,767` pour le bassin havrais) : une sortie en fait
partie si le code postal de son lieu commence par l'un d'eux. Rien n'est stocké
sur les sorties, redessiner une zone revient à modifier une liste, et c'est le
mécanisme que les recherches automatiques utilisaient déjà. Les zones se gèrent
depuis **Administration → Zones**, sans déploiement.

Les zones sont liées depuis l'accueil et entre elles, et listées en tête du
sitemap : un sitemap signale une page, ce sont les liens qui lui donnent du
poids.

Ce qui reste à faire pour aller plus loin est d'ordre éditorial : des pages par
catégorie à l'intérieur d'une zone (`/sorties/nancy/spectacles`), et une image
de partage par défaut pour l'accueil.

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
