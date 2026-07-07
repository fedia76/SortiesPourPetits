import { Role } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { requireRole } from '../middleware/auth';
import { updateRoleSchema } from '../lib/validators';

export const adminRouter = Router();

adminRouter.use(requireRole(Role.ADMIN));

adminRouter.get('/users', async (_req, res) => {
  const users = await prisma.user.findMany({
    select: {
      id: true,
      email: true,
      displayName: true,
      role: true,
      createdAt: true,
      _count: { select: { events: true } },
    },
    orderBy: { createdAt: 'desc' },
  });
  res.json({ users });
});

adminRouter.patch('/users/:id/role', async (req, res) => {
  const id = Number(req.params.id);
  const parsed = updateRoleSchema.safeParse(req.body);
  if (!Number.isInteger(id) || !parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  if (id === req.user!.id) {
    res.status(400).json({ error: 'Vous ne pouvez pas changer votre propre rôle' });
    return;
  }
  const user = await prisma.user.findUnique({ where: { id } });
  if (!user) {
    res.status(404).json({ error: 'Utilisateur introuvable' });
    return;
  }
  const updated = await prisma.user.update({
    where: { id },
    data: { role: parsed.data.role },
    select: { id: true, email: true, displayName: true, role: true },
  });
  res.json({ user: updated });
});
