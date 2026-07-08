import { Prisma, Role } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { requireRole } from '../middleware/auth';
import { categorySchema } from '../lib/validators';

export const categoriesRouter = Router();

/** Liste publique : utilisée par le formulaire de sortie et les filtres de recherche. */
categoriesRouter.get('/', async (_req, res) => {
  const categories = await prisma.category.findMany({ orderBy: { name: 'asc' } });
  res.json({ categories });
});

categoriesRouter.post('/', requireRole(Role.ADMIN), async (req, res) => {
  const parsed = categorySchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  try {
    const category = await prisma.category.create({ data: { name: parsed.data.name } });
    res.status(201).json({ category });
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
      res.status(409).json({ error: 'Cette catégorie existe déjà' });
      return;
    }
    throw e;
  }
});

categoriesRouter.patch('/:id', requireRole(Role.ADMIN), async (req, res) => {
  const id = Number(req.params.id);
  const parsed = categorySchema.safeParse(req.body);
  if (!Number.isInteger(id) || !parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const category = await prisma.category.findUnique({ where: { id } });
  if (!category) {
    res.status(404).json({ error: 'Catégorie introuvable' });
    return;
  }
  try {
    const updated = await prisma.category.update({
      where: { id },
      data: { name: parsed.data.name },
    });
    res.json({ category: updated });
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
      res.status(409).json({ error: 'Cette catégorie existe déjà' });
      return;
    }
    throw e;
  }
});

categoriesRouter.delete('/:id', requireRole(Role.ADMIN), async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: 'Identifiant invalide' });
    return;
  }
  const category = await prisma.category.findUnique({
    where: { id },
    include: { _count: { select: { events: true } } },
  });
  if (!category) {
    res.status(404).json({ error: 'Catégorie introuvable' });
    return;
  }
  if (category._count.events > 0) {
    res.status(409).json({ error: 'Cette catégorie est utilisée par des sorties et ne peut pas être supprimée' });
    return;
  }
  await prisma.category.delete({ where: { id } });
  res.json({ ok: true });
});
