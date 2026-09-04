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
