# Déploiement sur VPS (Ubuntu 24.04)

Mise en place une seule fois du serveur, puis chaque `git push` sur `main`
redéploie automatiquement via `.github/workflows/deploy.yml`.

## 1. Utilisateur dédié

En root sur le VPS :

```bash
adduser --disabled-password --gecos "" deploy
mkdir -p /opt/sortiespourpetits/{server,client,scraper}
chown -R deploy:deploy /opt/sortiespourpetits
```

Autoriser uniquement le redémarrage du service, sans mot de passe, sans accès
root complet :

```bash
echo 'deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart sortiespourpetits-api, /usr/bin/systemctl restart sortiespourpetits-scraper' \
  | tee /etc/sudoers.d/sortiespourpetits-deploy
```

Le compte `deploy` n'a pas de mot de passe : tant qu'aucune clé publique n'est
dans son `authorized_keys`, personne ne peut s'y connecter (ni vous, ni
GitHub Actions). Les fichiers de config (`Caddyfile`, unité systemd, clé SSH
de déploiement) doivent donc tous être envoyés **via `root`**, jamais via
`deploy`. Depuis votre poste local :

```bash
scp deploy/Caddyfile \
    deploy/sortiespourpetits-api.service \
    root@VOTRE_IP_VPS:/tmp/
```

Ces fichiers restent dans `/tmp` sur le VPS jusqu'aux étapes 4 et 6
ci-dessous, qui les copient à leur emplacement final.

Ce `scp` n'est nécessaire qu'ici, pour l'amorçage. Ensuite, chaque
déploiement dépose le contenu à jour du dossier `deploy/` du dépôt dans
`/opt/sortiespourpetits/deploy/` : c'est de là qu'on installe l'unité du
worker à l'étape 9, et c'est de là qu'on reprendra un `Caddyfile` ou une
unité modifiée, sans jamais avoir à les renvoyer à la main.

## 2. Node 24 (LTS)

```bash
curl -fsSL https://deb.nodesource.com/setup_24.x | bash -
apt-get install -y nodejs
```

## 3. MySQL

```bash
apt-get install -y mysql-server
mysql -e "CREATE DATABASE sortiespourpetits;"
mysql -e "CREATE USER 'sortiespourpetits_API'@'localhost' IDENTIFIED BY 'un-mot-de-passe-fort';"
mysql -e "GRANT ALL PRIVILEGES ON sortiespourpetits.* TO 'sortiespourpetits_API'@'localhost';"
```

## 4. Caddy (HTTPS automatique)

```bash
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update && apt-get install -y caddy
```

Copiez le fichier envoyé en `/tmp` à l'étape 1, remplacez `votre-domaine.fr`
par votre vrai domaine, puis rechargez :

```bash
cp /tmp/Caddyfile /etc/caddy/Caddyfile
nano /etc/caddy/Caddyfile   # remplacer votre-domaine.fr
systemctl reload caddy
```

Caddy n'obtiendra un certificat que lorsque le DNS du domaine pointera
réellement vers l'IP du VPS (à faire chez votre registrar — une entrée `A`
vers l'IP du VPS, en `A` et en `AAAA` si IPv6).

Choisissez **une** forme du domaine, avec ou sans `www`, et faites rediriger
l'autre : le bloc commenté en fin de `Caddyfile` est là pour ça. Deux adresses
qui servent le même site, ce sont deux fois les mêmes pages pour un moteur de
recherche, et c'est la première chose que Search Console reproche.

Caddy ne sert plus lui-même les pages : il garde les fichiers du build
(`/assets/*`) et passe tout le reste à l'API, qui les pré-rend. C'est ce qui
donne à chaque sortie son titre, sa description et ses données structurées —
voir la section « Référencement » du [README](../README.md).

## 5. Pare-feu

```bash
ufw allow OpenSSH
ufw allow 80,443/tcp
ufw enable
```

## 6. Service systemd

```bash
cp /tmp/sortiespourpetits-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable sortiespourpetits-api
```

Le service ne démarrera qu'après l'étape 8 (premier déploiement + `.env`).

Il y a un second service, `sortiespourpetits-scraper` — le worker de la
recherche automatique. Il s'installe à l'étape 9, une fois le premier
déploiement passé : c'est le déploiement qui apporte son unité systemd sur le
VPS. Il est facultatif ; sans lui le site fonctionne, seules les exécutions
lancées depuis la console attendent leur tour indéfiniment.

## 7. Clé SSH pour GitHub Actions

Sur votre poste (pas sur le VPS) :

```bash
ssh-keygen -t ed25519 -f deploy_key -C "github-actions-sortiespourpetits" -N ""
scp deploy_key.pub root@VOTRE_IP_VPS:/tmp/
```

Puis sur le VPS, toujours en `root` (le compte `deploy` n'a pas encore de clé,
donc pas encore de moyen de s'authentifier) :

```bash
mkdir -p /home/deploy/.ssh
cat /tmp/deploy_key.pub >> /home/deploy/.ssh/authorized_keys
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
rm /tmp/deploy_key.pub
```

Le contenu de `deploy_key` (la clé **privée**, générée sur votre poste) va
dans le secret GitHub `VPS_SSH_KEY` (jamais commitée). C'est seulement une
fois cette clé posée que `ssh`/`scp` vers `deploy@...` fonctionnera — gardez
`deploy_key` sur votre poste, vous vous en servez encore à l'étape 8
ci-dessous ; vous pourrez la supprimer localement une fois cette étape
terminée (GitHub Actions utilisera sa propre copie, dans le secret).

Dans les secrets du dépôt GitHub (`Settings > Secrets and variables >
Actions`) :

| Secret | Valeur |
|---|---|
| `VPS_HOST` | IP ou domaine du VPS |
| `VPS_USER` | `deploy` |
| `VPS_SSH_KEY` | clé privée générée ci-dessus |
| `VPS_APP_DIR` | `/opt/sortiespourpetits` |
| `CLAUDE_KEY` | clé de l'API Claude, pour le scraper |
| `SPP_API_KEY` | clé `spp_…` du scraper (facultative : inutile pour un dry-run) |

Les deux dernières alimentent le fichier `scraper/.env` sur le VPS, **régénéré
à chaque déploiement** : il se modifie ici, dans les secrets, jamais à la main
sur le serveur.

## 8. Premier déploiement (manuel)

Connectez-vous en tant que `deploy` avec la clé privée générée à l'étape 7
(c'est sa moitié publique, dans `authorized_keys`, qui vous authentifie —
pas de mot de passe) :

```bash
# depuis votre poste
ssh -i deploy_key deploy@VOTRE_IP_VPS
```

Puis, sur le VPS :

```bash
cd /opt/sortiespourpetits/server
cp .env.example .env
nano .env   # DATABASE_URL, JWT_SECRET, NODE_ENV=production, PUBLIC_BASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD_HASH...
```

Deux variables commandent le référencement, et le site n'est pas indexable
tant qu'elles ne sont pas justes :

- `NODE_ENV=production` — sans elle, `robots.txt` interdit tout le site et
  chaque page part en `noindex`. C'est voulu : une préproduction indexée se
  répare en semaines.
- `PUBLIC_BASE_URL=https://votre-domaine.fr` — l'adresse publique exacte, celle
  que vous déclarerez dans Search Console, sans barre finale. Elle sert à écrire
  les adresses canoniques et le sitemap.

Une fois le site en ligne, `https://votre-domaine.fr/robots.txt` doit annoncer
`Allow: /` et le sitemap ; s'il répond `Disallow: /`, c'est que `NODE_ENV`
n'est pas passé en production.

Une fois cette étape terminée, vous pouvez supprimer `deploy_key` /
`deploy_key.pub` de votre poste local si vous le souhaitez : GitHub Actions
utilise sa propre copie de la clé privée, stockée dans le secret
`VPS_SSH_KEY`.

Puis déclenchez un push sur `main` pour laisser GitHub Actions construire et
livrer le code, ou faites-le une première fois à la main :

```bash
cd /opt/sortiespourpetits/server
npm ci --omit=dev
npm run db:deploy      # migrations
npm run db:seed:prod   # catégories + compte admin
systemctl start sortiespourpetits-api
```

Les déploiements suivants (après un `git push` sur `main`) sont ensuite
automatiques.

## 9. Le scraper

Le [scraper](../scraper/README.md) est déployé en même temps que le reste :
son dossier part en sources dans `/opt/sortiespourpetits/scraper`, son
environnement virtuel est créé et mis à jour, et son `.env` est écrit depuis
les secrets `CLAUDE_KEY` et `SPP_API_KEY`. Ce qui appartient au VPS — le
`.venv`, les journaux de `runs/` et la mémoire locale de `state/` — survit
aux déploiements.

Une seule dépendance système, à installer en root **avant** le premier
déploiement — sans elle, l'étape « Configurer le scraper » échoue :

```bash
apt install -y python3-venv
```

Selon la version de Python du serveur, le paquet peut être versionné
(`python3.14-venv`, `python3.12-venv`…) : le message d'erreur du déploiement
indique lequel installer.

### Les extras du scraper, et pourquoi ils ne s'installent pas à la main

Le worker tourne dans **un venv, et nulle part ailleurs** :
`ExecStart=/opt/sortiespourpetits/scraper/.venv/bin/python -m sortiesbot.worker`.
Ce qu'on installe en root avec `pip install` atterrit dans le Python du
système, que le service ne voit pas — et sur un Ubuntu récent, `pip` refuse
même de le faire (`externally-managed-environment`, PEP 668).

Un extra s'active donc par la **variable de dépôt** `SCRAPER_EXTRAS`
(*Settings → Secrets and variables → Actions → Variables*), que le
déploiement lit :

| Valeur | Ce que le VPS installe |
|---|---|
| *(absente)* | `pip install -e .` — le cas normal |
| `gliner` | `pip install -e ".[gliner]"` — l'étiqueteur de l'étage 6, **et torch, ~2 Go** |
| `classifieur` | `pip install -e ".[classifieur]"` — scikit-learn, ~35 Mo, **sans torch** |
| `gliner,classifieur` | les deux |

Pour un essai ponctuel sans toucher au dépôt, c'est le pip **du venv** qu'il
faut appeler, et sous le compte qui le possède — sans quoi les fichiers
appartiennent à root et le déploiement suivant échoue :

```bash
sudo -u deploy /opt/sortiespourpetits/scraper/.venv/bin/pip install -e \
  '/opt/sortiespourpetits/scraper[gliner]'
```

#### Entraîner le classifieur de catégories

La catégorie d'une sortie n'est écrite nulle part sur la page : aucun site
n'annonce « Catégorie : Spectacles ». Elle ne s'extrait donc pas, elle
s'apprend — sur le corpus étiqueté du banc, par un modèle linéaire qui tient
dans un mégaoctet et ne charge aucun réseau de neurones.

L'entraînement se lance à la main, sur le VPS, et **ne fait pas partie du
déploiement** : il lit le corpus par l'API du site, ce qui suppose une base
peuplée et une clé valide.

```bash
sudo -u deploy /opt/sortiespourpetits/scraper/.venv/bin/python \
  -m tools.classifieur_entrainer --a-blanc   # mesurer sans rien écrire
sudo -u deploy /opt/sortiespourpetits/scraper/.venv/bin/python \
  -m tools.classifieur_entrainer             # puis enregistrer
```

Le modèle est écrit dans `~deploy/.local/share/sortiesbot/categorie.joblib`,
**hors du dépôt** : `/opt/sortiespourpetits` est récrit à chaque mise en ligne,
et un modèle rangé là disparaîtrait sans erreur — juste un champ qui
redeviendrait vide. `SPP_CLASSIFIEUR` dans le `.env` permet de le mettre
ailleurs.

Le script imprime aussi **les traits les plus pesés par classe** : c'est ce
qui répond à « qu'a-t-il appris ? » là où un pourcentage ne répond qu'à
« combien ». Y voir des noms de sites, des menus ou des pieds de page signale
un modèle qui a pris des raccourcis — ils paient sur le corpus et ne valent
rien sur un site inconnu.

`--sans-lieu` retire le nom du lieu des traits : c'est la façon de mesurer ce
qu'il apporte, en comparant deux runs.

Les catégories trop rares sont **mises de côté** : sous cinq exemples, une
classe ne s'apprend pas — le modèle retient la page, pas la catégorie — et ses
pages valent mieux manquées que fausses. Le script dit lesquelles et combien
de pages ça représente ; elles reviennent d'elles-mêmes dès que le corpus en
porte assez. `--minimum N` déplace ce plancher.

Sans modèle entraîné, la brique tourne et laisse la catégorie vide ; le
journal du run porte alors `non_rendus=…,category` et la raison en clair. Il
faut le réentraîner quand le corpus a sensiblement grossi : le script imprime
le nombre d'exemples et les scores hors échantillon, ce qui suffit à voir s'il
progresse.

#### Torch, et les deux pièges de l'extra `gliner`

Ils se ressemblent : tous deux font échouer l'installation en annonçant un
disque plein, alors que `df -h` montre `/` à 25 %.

**La variante CUDA.** `pip install torch` tire par défaut, sur Linux, torch
compilé pour GPU **plus une demi-douzaine de paquets `nvidia-*`** : plusieurs
gigaoctets de noyaux que ce VPS n'exécutera jamais. Le déploiement pose donc
la roue **processeur** d'abord — environ deux cents mégaoctets, aucune
dépendance nvidia — et l'extra trouve ensuite torch déjà satisfait. L'ordre
est le mécanisme.

**`/tmp` est un tmpfs.** pip y déballe ses roues, et ce tmpfs prend deux
gigaoctets sur les quatre de RAM : un déballage de torch y meurt **sans que le
disque bouge d'un pouce**, ce qui explique un message de place manquante que
`df` dément. Le déploiement exporte donc `TMPDIR=/var/tmp`, qui est sur le
disque.

Si une tentative a déjà échoué, il reste des morceaux à balayer avant de
recommencer :

```bash
sudo -u deploy rm -rf ~deploy/.cache/pip
rm -rf /tmp/pip-* /var/tmp/pip-*
```

Et si le message parle de **quota** (`Errno 122`) plutôt que de place, c'est
qu'un quota de système de fichiers est actif — `quota -s -u deploy` le dira,
et là c'est l'hébergeur qu'il faut voir, pas le déploiement.

Pour vérifier ce que le worker voit vraiment, à tout moment :

```bash
/opt/sortiespourpetits/scraper/.venv/bin/python -c 'import gliner, torch; print(gliner.__file__)'
```

### Installer le worker

En marche normale, les recherches se lancent depuis la console
d'administration du site (menu **Recherche auto**, réservé aux modérateurs).
Le worker est ce qui les exécute : il réclame le travail en attente à l'API,
joue la recherche, propose les sorties à la modération et rend compte page par
page dans la console. Sans lui, un clic sur « Lancer » laisse l'exécution
en file, indéfiniment.

Chaque déploiement dépose son unité systemd à jour dans
`/opt/sortiespourpetits/deploy/`. L'installation, elle, demande les droits
root — à faire **une fois**, après un premier déploiement :

```bash
cp /opt/sortiespourpetits/deploy/sortiespourpetits-scraper.service \
   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sortiespourpetits-scraper
```

Il reste à autoriser `deploy` à le redémarrer — sans ça, chaque déploiement
mettra le code à jour mais laissera tourner l'ancienne version. Si la règle de
l'étape 1 date d'avant le worker, elle ne mentionne que l'API : réécrivez-la
avec les deux services.

```bash
grep sortiespourpetits-scraper /etc/sudoers.d/sortiespourpetits-deploy
# rien ? alors :
echo 'deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart sortiespourpetits-api, /usr/bin/systemctl restart sortiespourpetits-scraper' \
  | tee /etc/sudoers.d/sortiespourpetits-deploy
visudo -c
```

C'est tout : les déploiements suivants mettent le code à jour et redémarrent
le worker tout seuls. Si vous modifiez l'unité elle-même dans le dépôt, le
déploiement en dépose la nouvelle version dans `deploy/` mais ne l'installe
pas — refaites le `cp` + `daemon-reload` ci-dessus.

Le worker tourne en `deploy`, comme l'API. Tout ce qu'il écrit — les journaux
de `runs/`, l'environnement virtuel — doit donc lui appartenir. Un essai lancé
en root crée ces dossiers à root, et le service ne peut plus y écrire :

```bash
chown -R deploy:deploy /opt/sortiespourpetits
```

Lancez toujours les essais en ligne de commande **en tant que `deploy`**, pas
en root, pour ne pas reproduire le problème. Un journal fichier impossible à
ouvrir n'arrête pas le run — la console garde la trace de chaque page — mais
autant garder la trace sur disque aussi.

### Surveiller le worker

```bash
systemctl status sortiespourpetits-scraper     # en marche ?
journalctl -u sortiespourpetits-scraper -f     # ce qu'il fait en direct
```

Il lui faut les deux clés (`CLAUDE_KEY` **et** `SPP_API_KEY`) : il refuse de
démarrer sans, et le journal le dit. Une exécution qui reste « En file » dans
la console veut généralement dire que le worker est arrêté ; une exécution
bloquée sur « En cours » se ferme d'elle-même au bout de trente minutes sans
la moindre trace — le bouton « Annuler » ne sert plus qu'à ne pas attendre.

Un arrêt (`systemctl stop`, ou un redémarrage de déploiement) laisse
l'exécution en cours aller au bout : le worker attrape le signal, finit ce
qu'il a commencé et ne prend plus de travail. Au-delà de dix minutes systemd
le tue quand même : l'exécution passe alors « En cours » sans personne
derrière, et le site la ferme d'office une demi-heure plus tard.

Un déploiement pendant une recherche lui coûte en revanche les appels qui
tombent au moment où l'API redémarre — une sortie non soumise, au pire. Le
worker rejoue les connexions refusées, mais pas ce qui était déjà parti.

### Lancer une recherche à la main

Le mode ligne de commande reste disponible, avec un fichier YAML au lieu d'une
configuration du site, et sa propre mémoire locale (`state/seen.sqlite3`) au
lieu de celle de la base :

```bash
cd /opt/sortiespourpetits/scraper
.venv/bin/python -m sortiesbot --config configs/spectacles-weekend.yaml --limit 3
```

Sans `--submit`, rien n'est envoyé au site : le run écrit dans `runs/` le
journal de ce qu'il a consulté et le JSON des sorties retenues. Un dry-run n'a
besoin que de `CLAUDE_KEY`.

## 10. Mesure d'audience (Umami)

De quoi répondre à trois questions : sur quelles pages vont les visiteurs, d'où
ils arrivent, et **sur quels liens ils cliquent**. Sans cookie, donc sans
bandeau de consentement.

Umami tourne en conteneurs, alors que tout le reste du serveur est en systemd,
et ce n'est pas une inconséquence : c'est une application Next.js, et la
**construire** demande plus de mémoire que ce VPS n'en a de libre à côté de
MySQL, de l'API et du worker — le même mur que torch au § 9. L'image publiée
est déjà construite ; on ne compile rien sur le serveur, et une mise à jour se
résume à un `pull`. Le raisonnement complet est en tête de
[`umami/docker-compose.yml`](umami/docker-compose.yml).

La base d'Umami est **PostgreSQL** : le projet a retiré MySQL de ses bases
supportées en version 3. Elle n'a aucun rapport avec le MySQL du site — deux
moteurs, deux données, aucun lien.

### 10.1 Docker

En root :

```bash
curl -fsSL https://get.docker.com | sh
```

Rien à ouvrir dans le pare-feu. Le conteneur publie son port sur
`127.0.0.1:3001` et sur rien d'autre : c'est Caddy, et lui seul, qui donne
accès à ce qui doit l'être. Cette précision vaut d'être comprise — Docker écrit
ses propres règles iptables et **passe devant `ufw`**, si bien qu'un port publié
sans adresse (`3001:3000`) serait joignable depuis l'extérieur malgré le
pare-feu. L'adresse de boucle locale dans le mappage est ce qui l'en empêche.

### 10.2 Les secrets, créés sur le VPS et nulle part ailleurs

```bash
cd /opt/sortiespourpetits/deploy/umami
cp .env.example .env
chmod 600 .env
nano .env   # remplir les trois valeurs avec les `openssl rand` indiqués
```

⚠️ **Ce fichier n'existe que sur le VPS.** Le déploiement dépose le dossier
`deploy/` avec un `rsync --delete`, qui efface tout ce qui ne vient pas du
dépôt : `umami/.env` est explicitement épargné dans
`.github/workflows/deploy.yml`. Si vous déplacez ce fichier ailleurs dans
`deploy/`, l'exclusion ne le suivra pas et la première mise en ligne emportera
vos secrets — la pile ne redémarrera plus.

### 10.3 Démarrer

```bash
cd /opt/sortiespourpetits/deploy/umami
docker compose up -d
docker compose logs -f umami   # « Ready » au bout de quelques dizaines de secondes
```

Aucune table à créer : Umami joue ses propres migrations sur la base vide au
premier démarrage.

### 10.4 Le sous-domaine et Caddy

Une entrée DNS `A` (et `AAAA` si IPv6) pour `stats.votre-domaine.fr` vers l'IP
du VPS, chez votre registrar. Caddy n'obtiendra son certificat qu'une fois le
nom résolu.

Le [`Caddyfile`](Caddyfile) du dépôt porte déjà les trois blocs nécessaires :
le script (`/mesure/mesure.js`), le point de collecte (`/mesure/api/send`) et
le tableau de bord sur son sous-domaine. Reprenez-le et rechargez :

```bash
cp /opt/sortiespourpetits/deploy/Caddyfile /etc/caddy/Caddyfile
nano /etc/caddy/Caddyfile   # remplacer votre-domaine.fr, ici aussi
systemctl reload caddy
```

Deux adresses seulement sortent sur le domaine principal, et elles sont
énumérées une à une. Ce n'est pas de la coquetterie : une règle large aurait
exposé l'API d'administration d'Umami sur l'adresse que tout le monde visite.

Pourquoi faire passer le script par notre domaine au lieu de pointer sur le
conteneur : un script servi par un tiers se fait bloquer par les bloqueurs de
publicité, et le trafic mobile en perd une part qu'on ne retrouve jamais. Servi
depuis `sortiespourpetits.fr`, il est indistinguable du reste du site. Le nom
`mesure.js` participe de la même idée — les listes de filtrage visent des noms
de fichiers connus, et `umami.js` en est un.

### 10.5 Créer le site et le brancher

Ouvrez `https://stats.votre-domaine.fr`. Identifiants par défaut :
`admin` / `umami` — **changez le mot de passe immédiatement**, c'est une
console ouverte sur Internet.

Puis *Settings → Websites → Add website*, avec le domaine du site. Umami donne
alors un identifiant (un UUID). Reportez-le dans `server/.env` :

```bash
nano /opt/sortiespourpetits/server/.env
```

```ini
AUDIENCE_WEBSITE_ID="l-uuid-donné-par-umami"
AUDIENCE_SCRIPT_URL="/mesure/mesure.js"
AUDIENCE_HOST_URL="https://votre-domaine.fr/mesure"
```

```bash
sudo systemctl restart sortiespourpetits-api
```

La balise est écrite par le serveur, dans le `<head>` de chaque page pré-rendue
(`server/src/seo/audience.ts`) — pas dans le build du front. Deux
conséquences voulues : l'identifiant se change sans reconstruire le front, et
**tant que `AUDIENCE_WEBSITE_ID` est vide, aucune balise n'est posée**. C'est
l'état du développement, et c'est ce qui garantit qu'une préproduction ne
compte pas dans les mêmes chiffres.

### 10.6 Vérifier

```bash
curl -sI https://votre-domaine.fr/mesure/mesure.js | head -1   # 200
curl -s  https://votre-domaine.fr/ | grep -o 'data-website-id="[^"]*"'
```

Puis chargez une page du site : la visite doit apparaître en direct dans le
tableau de bord. Si le script répond 200 mais que rien n'arrive, regardez la
console du navigateur — c'est l'appel à `/mesure/api/send` qu'il faut y voir
réussir.

### 10.7 Ne pas se compter soi-même

C'est le premier biais, et de loin : sur un site qui commence, les visites du
modérateur écrasent celles des visiteurs. Depuis la console de **votre**
navigateur, sur le site :

```js
localStorage.setItem('umami.disabled', 1)
```

À refaire par navigateur et par appareil. Filtrer des pages ne servirait à
rien : vous consultez aussi les pages publiques, et ce sont elles qui comptent.
Si votre IP est fixe, `IGNORE_IP` dans le `.env` du conteneur fait le même
travail sans dépendre du navigateur.

Une fois ce drapeau posé, **ce navigateur ne produit plus rien** : le tableau
de bord y restera vide quoi que vous fassiez, et ce n'est pas une panne. C'est
le piège de cette page, parce qu'on éprouve son installation avec le navigateur
qu'on vient de faire taire. Toute vérification ultérieure se fait depuis un
autre navigateur, ou une fenêtre privée d'un autre navigateur — pas une fenêtre
privée du même, qui partage parfois ce stockage.

### 10.8 Quand rien n'apparaît dans le tableau de bord

**À vérifier avant tout le reste, et c'est le cas le plus fréquent :** le
drapeau d'auto-exclusion du § 10.7. Dans la console du navigateur, sur le site :

```js
localStorage.getItem('umami.disabled')
```

S'il rend `"1"`, tout fonctionne — ce navigateur est simplement celui que vous
avez fait taire, et il doit le rester. Une page chargée depuis un autre
navigateur le confirme en quelques secondes ; c'est le test à faire en premier,
avant d'aller chercher une panne qui n'existe pas.

S'il rend `null` et que rien n'arrive quand même, l'onglet Réseau (F12) tranche
en une fois : rechargez et regardez le POST vers `/mesure/api/send`. « Blocked »
désigne une extension du navigateur ; un code `4xx` désigne la configuration —
`400` avec « Website not found » signifie que `AUDIENCE_WEBSITE_ID` ne
correspond à aucun site créé dans Umami.

Ce n'est pas le « Do Not Track » du navigateur : le script ne l'honore que si
on le lui demande par `data-do-not-track`, ce que la balise ne fait pas. Ce
n'est pas non plus le cache : les pages sortent en `max-age=60`
(`server/src/routes/site.ts`), soit une minute.

### 10.9 Quand le script lui-même ne répond pas

Le symptôme le plus déroutant est un `curl` qui **attend** au lieu de répondre
— ni 200, ni 404, rien. Ce n'est pas un pare-feu : c'est une boucle. Trois
causes possibles, à écarter dans cet ordre.

**Le conteneur sert-il seulement le script ?** Depuis le VPS, en court-circuitant
Caddy :

```bash
curl -sI http://127.0.0.1:3001/script.js | head -3
```

- `200` → le conteneur va bien, le problème est dans Caddy (voir plus bas).
- ça attend, puis expire → c'est la boucle décrite juste après.
- `connection refused` → le conteneur n'est pas démarré :
  `docker compose ps` et `docker compose logs umami`.

**La boucle : `TRACKER_SCRIPT_URL`.** Cette variable n'est pas une valeur
d'affichage. Le middleware de l'image réécrit, à l'exécution, toute requête sur
`/script.js` vers l'adresse qu'elle contient. Si cette adresse est celle que
Caddy renvoie au conteneur, la requête tourne en rond jusqu'à l'expiration et
le script n'est jamais servi. **Elle ne doit pas figurer dans le `.env`** — le
renommage en `mesure.js` est le travail de Caddy et ne demande aucune variable.

```bash
grep TRACKER_SCRIPT_URL /opt/sortiespourpetits/deploy/umami/.env   # ne doit rien sortir
```

Si la ligne est là, retirez-la puis :

```bash
cd /opt/sortiespourpetits/deploy/umami
docker compose up -d --force-recreate umami
```

`--force-recreate` n'est pas décoratif : `up -d` seul ne recrée pas un
conteneur dont l'image n'a pas changé, et l'ancienne variable resterait dans
son environnement.

**Caddy sert-il bien la configuration attendue ?** Un `reload` qui échoue
laisse l'ancienne configuration en place, et le site continue de répondre comme
si de rien n'était :

```bash
caddy validate --config /etc/caddy/Caddyfile
systemctl status caddy --no-pager
journalctl -u caddy -n 30 --no-pager
grep -c 'mesure.js' /etc/caddy/Caddyfile   # 1 attendu, 0 = fichier pas à jour
```

Si le fichier n'est pas à jour, c'est qu'il n'a pas été recopié depuis
`/opt/sortiespourpetits/deploy/` après le déploiement — voir § 10.4.

### 10.10 Sauvegarder

Les mesures vivent dans un volume Docker, pas dans MySQL : votre sauvegarde du
site ne les couvre pas.

```bash
docker compose -f /opt/sortiespourpetits/deploy/umami/docker-compose.yml \
  exec -T db pg_dump -U umami umami | gzip > ~/umami-$(date +%F).sql.gz
```

`docker compose down` laisse le volume en place. `docker compose down -v`
l'efface — c'est la commande à ne pas taper.

### 10.11 Mettre à jour

```bash
cd /opt/sortiespourpetits/deploy/umami
docker compose pull && docker compose up -d
```

L'image suit l'étiquette `latest`, comme le compose publié par le projet : un
`pull` peut donc apporter une version majeure. C'est pour ça que la mise à jour
est une commande que l'on tape, jamais un automatisme, et qu'une sauvegarde la
précède. Pour figer une version, remplacez l'étiquette dans le compose.

### 10.12 Ce que ça mesure — et ce que ça ne mesure pas

**Sans rien à coder**, parce que le script s'en charge :

- **les pages vues**, y compris la navigation interne de l'application : le
  script enrobe `history.pushState`, que vue-router appelle à chaque changement
  de page ;
- **les recherches**, parce qu'elles vivent dans la *query string* et donc dans
  l'adresse — la page vue les porte déjà ;
- **d'où viennent les visiteurs** : moteur, réseau social, lien direct.

**Avec deux attributs dans la fiche d'une sortie**
(`client/src/views/EventDetailView.vue`) :

| Événement | Ce qu'il dit |
|---|---|
| `sortie-source` | quelqu'un est parti chez l'organisateur depuis une fiche |
| `sortie-carte` | quelqu'un a ouvert le lieu sur une carte |

`sortie-source` est **la** mesure à regarder. Une page vue ne prouve rien : on
peut ouvrir une fiche et repartir. Partir chez l'organisateur, c'est le site
qui a servi à quelque chose.

**Ce qu'il ne faut pas piloter avec :** le temps passé. Le chiffre existe dans
le tableau de bord, il est trompeur, et il l'est davantage ici : ce site est
une application qui ne recharge jamais la page, et la durée s'y calcule par
différence entre deux événements. **La dernière page d'une visite compte donc
zéro seconde** — quelqu'un qui lit une fiche pendant quatre minutes puis ferme
l'onglet est enregistré à 0 s. Aucun outil ne corrige cela honnêtement. Sur un
faible volume, la moyenne n'est que du bruit.

### 10.13 Consentement

Umami ne pose aucun cookie et ne construit pas d'identifiant durable. C'est ce
qui permet de tenir les quatre critères d'exemption de la CNIL — finalité
limitée à la seule mesure d'audience, pas de recoupement avec d'autres
traitements ni de transmission à des tiers, pas de suivi d'un site à l'autre,
information et opposition possibles — et donc de mesurer **sans bandeau**.

Deux réserves, et elles sont sérieuses :

1. c'est vrai tant qu'on ne branche rien d'autre dessus. Ajouter un outil qui
   pose un cookie, ou croiser ces mesures avec les comptes utilisateurs, fait
   retomber l'ensemble dans le régime du consentement ;
2. l'exemption dispense du bandeau, **pas de l'information**. Le site n'a
   aujourd'hui ni mentions légales ni politique de confidentialité — il en
   faut une, qui dise ce qui est mesuré et comment s'y opposer. Ce n'est pas
   fait ; c'est le prochain chantier.
