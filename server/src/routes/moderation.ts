import { Role } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { requireRole } from '../middleware/auth';
import { moderateSchema } from '../lib/validators';

export const moderationRouter = Router();

moderationRouter.use(requireRole(Role.MODERATOR));

moderationRouter.get('/pending', async (_req, res) => {
  const events = await prisma.event.findMany({
    where: { status: 'PENDING' },
    include: {
      venue: true,
      author: { select: { id: true, displayName: true, email: true } },
    },
    orderBy: { createdAt: 'asc' },
  });
  res.json({
    events: events.map((e) => ({
      ...e,
      price: e.price === null ? null : Number(e.price),
      dateStart: e.dateStart.toISOString().slice(0, 10),
      dateEnd: e.dateEnd.toISOString().slice(0, 10),
      venue: { ...e.venue, lat: Number(e.venue.lat), lng: Number(e.venue.lng) },
    })),
  });
});

moderationRouter.post('/:id', async (req, res) => {
  const id = Number(req.params.id);
  const parsed = moderateSchema.safeParse(req.body);
  if (!Number.isInteger(id) || !parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const event = await prisma.event.findUnique({ where: { id } });
  if (!event) {
    res.status(404).json({ error: 'Événement introuvable' });
    return;
  }
  if (event.status !== 'PENDING') {
    res.status(409).json({ error: 'Cet événement a déjà été modéré' });
    return;
  }

  const { action, reason } = parsed.data;
  const updated = await prisma.event.update({
    where: { id },
    data: {
      status: action === 'approve' ? 'APPROVED' : 'REJECTED',
      rejectionReason: action === 'reject' ? reason ?? null : null,
      moderatedById: req.user!.id,
    },
  });
  res.json({ ok: true, status: updated.status });
});
