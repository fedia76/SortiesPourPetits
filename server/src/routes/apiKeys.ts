import { Role } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { generateApiKey, hasRole, requireRole } from '../middleware/auth';
import { createApiKeySchema } from '../lib/validators';

export const apiKeysRouter = Router();

apiKeysRouter.use(requireRole(Role.MODERATOR));

const keySelect = {
  id: true,
  name: true,
  createdAt: true,
  lastUsedAt: true,
  revokedAt: true,
  user: { select: { id: true, displayName: true, email: true, role: true } },
} as const;

apiKeysRouter.get('/', async (_req, res) => {
  const keys = await prisma.apiKey.findMany({
    select: keySelect,
    orderBy: { createdAt: 'desc' },
  });
  res.json({ keys });
});

/** Comptes auxquels l'appelant peut rattacher une clé (rôle ≤ au sien). */
apiKeysRouter.get('/users', async (req, res) => {
  const users = await prisma.user.findMany({
    select: { id: true, displayName: true, email: true, role: true },
    orderBy: { displayName: 'asc' },
  });
  res.json({ users: users.filter((u) => hasRole(req.user, u.role)) });
});

apiKeysRouter.post('/', async (req, res) => {
  const parsed = createApiKeySchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const target = await prisma.user.findUnique({ where: { id: parsed.data.userId } });
  if (!target) {
    res.status(404).json({ error: 'Compte introuvable' });
    return;
  }
  // Anti-escalade : un modérateur ne peut pas se fabriquer une clé aux droits admin.
  if (!hasRole(req.user, target.role)) {
    res.status(403).json({ error: 'Ce compte a un rôle supérieur au vôtre' });
    return;
  }

  const { key, keyHash } = generateApiKey();
  const apiKey = await prisma.apiKey.create({
    data: { name: parsed.data.name, userId: target.id, keyHash },
    select: keySelect,
  });
  // Seule réponse contenant la clé en clair : elle n'est pas récupérable ensuite.
  res.status(201).json({ key, apiKey });
});

/** Révocation (immédiate et définitive) ; la ligne est conservée pour l'historique. */
apiKeysRouter.delete('/:id', async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const apiKey = await prisma.apiKey.findUnique({ where: { id } });
  if (!apiKey) {
    res.status(404).json({ error: 'Clé introuvable' });
    return;
  }
  if (apiKey.revokedAt) {
    res.status(409).json({ error: 'Cette clé est déjà révoquée' });
    return;
  }
  await prisma.apiKey.update({ where: { id }, data: { revokedAt: new Date() } });
  res.json({ ok: true });
});
