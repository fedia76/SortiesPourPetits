import path from 'path';
import dotenv from 'dotenv';

dotenv.config();

export const config = {
  port: Number(process.env.PORT ?? 3000),
  jwtSecret: process.env.JWT_SECRET ?? 'dev-secret-change-me',
  uploadsDir: process.env.UPLOADS_DIR ?? path.join(__dirname, '..', 'uploads'),
  // Durée de vie du cookie de session (7 jours)
  sessionMaxAgeMs: 7 * 24 * 60 * 60 * 1000,

  /**
   * Adresse publique du site, sans barre finale — « https://exemple.fr ».
   *
   * Les URL canoniques, le sitemap et les balises Open Graph doivent être
   * absolues : un moteur ne sait pas quoi faire de « /sorties/12 ». Quand la
   * variable est absente, on la déduit de la requête (Caddy renseigne
   * X-Forwarded-Proto, d'où le `trust proxy` ci-dessus) : le site reste
   * correct, mais un domaine figé vaut mieux qu'un domaine deviné.
   */
  publicBaseUrl: (process.env.PUBLIC_BASE_URL ?? '').replace(/\/+$/, ''),

  /**
   * Le front **compilé**, que l'API sert elle-même : c'est elle qui pré-rend
   * les pages publiques, donc c'est elle qui tient le `index.html` du build.
   *
   * Deux dispositions, d'où le test sur `__dirname`. Compilée, l'API tourne
   * depuis `server/dist/` et le déploiement dépose le build dans `client/`, à
   * côté. En sources (`npm run dev`), le même chemin désignerait `client/` tel
   * qu'il est dans le dépôt — donc son code et ses `node_modules`, qu'il n'est
   * pas question de servir : c'est `client/dist` qu'on vise, et rien d'autre.
   */
  clientDir:
    process.env.CLIENT_DIR ??
    (path.basename(__dirname) === 'dist'
      ? path.join(__dirname, '..', '..', 'client')
      : path.join(__dirname, '..', '..', 'client', 'dist')),

  /**
   * La mesure d'audience, et de quoi la débrancher en ne renseignant rien.
   *
   * Les trois valeurs sont publiques — elles finissent dans le HTML de chaque
   * page, c'est leur rôle. Elles sont ici, et non dans le build du front,
   * pour que le développement et une éventuelle préproduction ne comptent pas
   * dans les mêmes chiffres que le site : sans `AUDIENCE_WEBSITE_ID`, aucune
   * balise n'est posée et rien n'est mesuré.
   *
   * `AUDIENCE_SCRIPT_URL` est servie par Caddy depuis notre propre domaine
   * (voir `deploy/Caddyfile`), et pas depuis le conteneur : un script tiers se
   * fait bloquer, et ce qui est bloqué ne se compte pas.
   */
  audience: {
    scriptUrl: process.env.AUDIENCE_SCRIPT_URL ?? '',
    websiteId: process.env.AUDIENCE_WEBSITE_ID ?? '',
    hostUrl: (process.env.AUDIENCE_HOST_URL ?? '').replace(/\/+$/, ''),
  },

  /**
   * Autorise-t-on les moteurs à indexer ?
   *
   * Non par défaut : une préproduction ou un poste de développement joignable
   * depuis l'extérieur ne doit pas se retrouver dans les résultats, et c'est
   * le genre d'accident qu'on met des mois à défaire.
   */
  indexable: process.env.NODE_ENV === 'production',
};
