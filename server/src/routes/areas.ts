import { Prisma, Role } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { requireRole } from '../middleware/auth';
import { areaSchema } from '../lib/validators';
import { areaFilter } from '../lib/areas';
import { dateFilter, today } from '../lib/dateWindow';

export const areasRouter = Router();

/**
 * Liste publique des zones, avec le nombre de sorties visibles dans chacune.
 *
 * Ce compte n'est pas décoratif : il sert à ne pas mettre en avant une zone
 * vide. Une page qui annonce des sorties et n'en montre aucune déçoit le
 * visiteur et, répétée, apprend à Google que le site promet plus qu'il ne tient.
 */
areasRouter.get('/', async (_req, res) => {
  const areas = await prisma.area.findMany({ orderBy: [{ position: 'asc' }, { name: 'asc' }] });
  const upcoming: Prisma.EventWhereInput = { status: 'APPROVED', AND: [dateFilter(today())] };
  const counts = await Promise.all(
    areas.map((area) =>
      prisma.event.count({ where: { AND: [upcoming, areaFilter(area.postalPrefixes)] } }),
    ),
  );
  res.json({
    areas: areas.map((area, i) => ({ ...area, eventCount: counts[i] })),
  });
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
  const id = Number(req.params.id);
  const parsed = areaSchema.safeParse(req.body);
  if (!Number.isInteger(id) || !parsed.success) {
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
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
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
