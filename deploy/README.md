# Déploiement sur VPS (Ubuntu 24.04)

Mise en place une seule fois du serveur, puis chaque `git push` sur `main`
redéploie automatiquement via `.github/workflows/deploy.yml`.

## 1. Utilisateur dédié

En root sur le VPS :

```bash
adduser --disabled-password --gecos "" deploy
mkdir -p /opt/sortiespourpetits/{server,client}
chown -R deploy:deploy /opt/sortiespourpetits
```

Autoriser uniquement le redémarrage du service, sans mot de passe, sans accès
root complet :

```bash
echo 'deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart sortiespourpetits-api' \
  | tee /etc/sudoers.d/sortiespourpetits-deploy
```

Le compte `deploy` n'a pas de mot de passe : tant qu'aucune clé publique n'est
dans son `authorized_keys`, personne ne peut s'y connecter (ni vous, ni
GitHub Actions). Les fichiers de config (`Caddyfile`, unité systemd, clé SSH
de déploiement) doivent donc tous être envoyés **via `root`**, jamais via
`deploy`. Depuis votre poste local :

```bash
scp deploy/Caddyfile deploy/sortiespourpetits-api.service root@VOTRE_IP_VPS:/tmp/
```

Ces fichiers restent dans `/tmp` sur le VPS jusqu'aux étapes 4 et 6
ci-dessous, qui les copient à leur emplacement final.

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
nano .env   # DATABASE_URL, JWT_SECRET, NODE_ENV=production, ADMIN_EMAIL, ADMIN_PASSWORD_HASH...
```

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
