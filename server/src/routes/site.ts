import express, { Router } from 'express';
import path from 'path';
import { config } from '../config';
import { cached } from '../seo/cache';
import { renderDocument } from '../seo/html';
import { baseUrl } from '../seo/meta';
import { pageOf, renderPage } from '../seo/pages';
import { listAreas, listSitemapEvents } from '../seo/query';
import { EDIT_SUFFIX, PRIVATE_PREFIXES } from '../seo/routes';
import { sitemapXml } from '../seo/sitemap';

/**
 * Le site lui-même, servi par l'API.
 *
 * Jusqu'ici le serveur web renvoyait `index.html` pour toute adresse inconnue
 * et l'application se débrouillait. Cela suffit à un visiteur — pas à un
 * moteur : toutes les adresses partageaient un titre, aucune ne portait son
 * contenu, et une adresse inventée répondait « 200, tout va bien ». Faire
 * passer les documents par l'API permet de leur donner ce qui leur manquait :
 * leur contenu, leurs métadonnées, et le bon code de retour.
 *
 * Le reverse proxy garde les fichiers versionnés du build (`/assets/*`) : ils
 * n'ont aucune raison de traverser Node. Le repli ci-dessous existe pour les
 * autres déploiements et pour le développement.
 */
export const siteRouter = Router();

/** Combien de temps l'accueil et le sitemap restent bons à resservir. */
const HOME_TTL_MS = 60_000;
const SITEMAP_TTL_MS = 10 * 60_000;

// Deux adresses pour la même page, c'est un doublon de plus à expliquer à
// Google. Autant n'en garder qu'une.
siteRouter.get('/index.html', (_req, res) => res.redirect(301, '/'));

/**
 * Ce que les robots ont le droit de parcourir.
 *
 * Hors production, tout est interdit : une préproduction indexée est un
 * accident coûteux à réparer, et le silence est ici la bonne valeur par défaut.
 */
siteRouter.get('/robots.txt', (req, res) => {
  const base = baseUrl(req);
  const body = config.indexable
    ? [
        'User-agent: *',
        'Allow: /',
        ...PRIVATE_PREFIXES.map((p) => `Disallow: ${p}`),
        `Disallow: /*${EDIT_SUFFIX}`,
        'Disallow: /api/',
        '',
        `Sitemap: ${base}/sitemap.xml`,
        '',
      ].join('\n')
    : ['User-agent: *', 'Disallow: /', ''].join('\n');
  res.type('text/plain; charset=utf-8').send(body);
});

siteRouter.get('/sitemap.xml', async (req, res, next) => {
  try {
    const base = baseUrl(req);
    const xml = await cached(`sitemap:${base}`, SITEMAP_TTL_MS, async () => {
      const [events, areas] = await Promise.all([listSitemapEvents(), listAreas()]);
      return sitemapXml(base, events, areas.map((a) => a.slug));
    });
    res.type('application/xml; charset=utf-8').send(xml);
  } catch (err) {
    next(err);
  }
});

// Les fichiers du build. `index: false` : la racine est une page à pré-rendre,
// pas un fichier à servir.
siteRouter.use(
  '/assets',
  express.static(path.join(config.clientDir, 'assets'), { maxAge: '1y', immutable: true }),
);
siteRouter.use(express.static(config.clientDir, { index: false, maxAge: '1h' }));

/** `/favicon.svg` manquant doit rester une erreur, pas devenir une page HTML. */
const LOOKS_LIKE_A_FILE = /\/[^/]+\.[a-z0-9]{1,8}$/i;

/** Ce qui n'est pas une page : une route d'API inconnue doit répondre en API. */
function isApiPath(pathname: string): boolean {
  return ['/api', '/uploads'].some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

siteRouter.use(async (req, res, next) => {
  if (req.method !== 'GET' && req.method !== 'HEAD') return next();
  if (isApiPath(req.path) || LOOKS_LIKE_A_FILE.test(req.path)) return next();

  try {
    const base = baseUrl(req);
    // La clé ne retient que ce que l'accueil lit vraiment de l'adresse : deux
    // visiteurs arrivant avec des paramètres de campagne différents doivent se
    // partager la même page, pas s'en fabriquer chacun une.
    const key = `home:${base}:${pageOf(req.query.page)}`;
    const page =
      req.path === '/'
        ? await cached(key, HOME_TTL_MS, () => renderPage(base, req.path, req.query))
        : await renderPage(base, req.path, req.query);

    const html = renderDocument(page);
    if (html === null) return next();

    res
      .status(page.status)
      .type('text/html; charset=utf-8')
      .set('Cache-Control', page.status === 200 ? 'public, max-age=60' : 'no-store')
      .send(html);
  } catch (err) {
    next(err);
  }
});
