import { Router } from 'express';
import { pageLegale } from '../lib/legal';

/**
 * Les pages légales, servies en données.
 *
 * Le serveur les rend déjà en HTML dans le document pré-rendu ; cette route
 * existe pour la vue, qui remplace ce document dès que Vue démarre et doit
 * pouvoir réafficher le même texte — au premier chargement sans même un appel
 * réseau, le document portant la réponse (voir `seo/pages.ts`).
 */
export const legalRouter = Router();

legalRouter.get('/:slug', (req, res) => {
  const page = pageLegale(req.params.slug);
  if (!page) {
    res.status(404).json({ error: 'Page inconnue' });
    return;
  }
  res.json({ page });
});
