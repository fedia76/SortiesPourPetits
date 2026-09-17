import { Prisma, Role } from '@prisma/client';
import { safeRouter } from '../lib/asyncRoutes';
import { prisma } from '../db';
import { requireRole } from '../middleware/auth';
import { areaSchema } from '../lib/validators';
import { areasWithCounts } from '../lib/publicLists';
import { parseId } from '../lib/routeParams';

export const areasRouter = safeRouter();

/**
 * Liste publique des zones. Le pré-rendu écrit la même chose dans l'état
 * initial du document, d'où la brique partagée (`lib/publicLists`).
 */
areasRouter.get('/', async (_req, res) => {
  res.json({ areas: await areasWithCounts() });
});

areasRouter.post('/', requireRole(Role.ADMIN), async (req, res) => {
  const parsed = areaSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  try {
    const area = await prisma.area.create({ data: parsed.data });
    res.status(201).json({ area });
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
      res.status(409).json({ error: 'Une zone porte déjà ce nom ou cet identifiant' });
      return;
    }
    throw e;
  }
});

areasRouter.patch('/:id', requireRole(Role.ADMIN), async (req, res) => {
  const id = parseId(req.params.id);
  const parsed = areaSchema.safeParse(req.body);
  if (id === null || !parsed.success) {
    res.status(400).json({ error: parsed.success ? 'Requête invalide' : parsed.error.issues[0].message });
    return;
  }
  const existing = await prisma.area.findUnique({ where: { id } });
  if (!existing) {
    res.status(404).json({ error: 'Zone introuvable' });
    return;
  }
  try {
    const area = await prisma.area.update({ where: { id }, data: parsed.data });
    res.json({ area });
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
      res.status(409).json({ error: 'Une zone porte déjà ce nom ou cet identifiant' });
      return;
    }
    throw e;
  }
});

/**
 * Supprimer une zone ne touche à aucune sortie — rien ne lui appartient, elle
 * ne fait que décrire un ensemble de codes postaux. En revanche son adresse
 * disparaît, et une adresse indexée qui s'évanouit se paie en erreurs dans la
 * Search Console : mieux vaut redessiner une zone que la supprimer.
 */
areasRouter.delete('/:id', requireRole(Role.ADMIN), async (req, res) => {
  const id = parseId(req.params.id);
  if (id === null) {
    res.status(400).json({ error: 'Identifiant invalide' });
    return;
  }
  const area = await prisma.area.findUnique({ where: { id } });
  if (!area) {
    res.status(404).json({ error: 'Zone introuvable' });
    return;
  }
  await prisma.area.delete({ where: { id } });
  res.json({ ok: true });
});
