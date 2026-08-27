import { Prisma, Role } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { requireRole } from '../middleware/auth';
import { moderateSchema, similarSchema } from '../lib/validators';
import { hasCoordinates, hasPrice } from '../lib/incomplete';
import { rankSimilar, significantWords, type SimilarityScore } from '../lib/similarity';

export const moderationRouter = Router();

moderationRouter.use(requireRole(Role.MODERATOR));

const MODERATION_INCLUDE = {
  venue: true,
  category: true,
  author: { select: { id: true, displayName: true, email: true } },
} as const;

type ModeratedEvent = Prisma.EventGetPayload<{ include: typeof MODERATION_INCLUDE }>;

/** Convertit les Decimal Prisma et les dates en valeurs JSON. */
function serializeEvent(event: ModeratedEvent, similarity?: SimilarityScore) {
  return {
    ...event,
    price: event.price === null ? null : Number(event.price),
    dateStart: event.dateStart ? event.dateStart.toISOString().slice(0, 10) : null,
    dateEnd: event.dateEnd ? event.dateEnd.toISOString().slice(0, 10) : null,
    venue: { ...event.venue, lat: Number(event.venue.lat), lng: Number(event.venue.lng) },
    similarity,
  };
}

moderationRouter.get('/pending', async (_req, res) => {
  const events = await prisma.event.findMany({
    where: { status: 'PENDING' },
    include: MODERATION_INCLUDE,
    orderBy: { createdAt: 'asc' },
  });
  res.json({ events: events.map((e) => serializeEvent(e)) });
});

/** Nombre de mots du titre utilisés pour élargir la recherche hors du rayon. */
const TITLE_PROBE_WORDS = 4;
/** Garde-fou : au-delà, on ne compare pas tout, on prend les plus récents. */
const MAX_CANDIDATES = 300;

/**
 * Sorties ressemblant à celle-ci, pour repérer un doublon avant de trancher.
 *
 * Le vivier est volontairement large — tout ce qui est au même endroit (ou à
 * moins de `radiusKm`), plus tout ce qui partage un mot marquant du titre —
 * puis chaque candidat est noté et seuls les plus proches sont renvoyés.
 * Les sorties refusées sont ignorées : un doublon d'une sortie déjà refusée
 * n'apprend rien au modérateur.
 */
moderationRouter.get('/:id/similar', async (req, res) => {
  const id = Number(req.params.id);
  const parsed = similarSchema.safeParse(req.query);
  if (!Number.isInteger(id) || !parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const { radiusKm, minScore, limit } = parsed.data;

  const event = await prisma.event.findUnique({ where: { id }, include: MODERATION_INCLUDE });
  if (!event) {
    res.status(404).json({ error: 'Événement introuvable' });
    return;
  }

  // Lieux dans le rayon et distance de chacun (Haversine en SQL pur, comme la
  // recherche publique : compatible MySQL et MariaDB, et l'index [lat, lng]
  // n'aide pas ici mais la table Venue reste petite).
  const lat = Number(event.venue.lat);
  const lng = Number(event.venue.lng);
  const nearbyVenues = await prisma.$queryRaw<{ id: number; distanceKm: number }[]>`
    SELECT id,
      6371 * 2 * ASIN(SQRT(
        POWER(SIN(RADIANS(lat - ${lat}) / 2), 2) +
        COS(RADIANS(${lat})) * COS(RADIANS(lat)) *
        POWER(SIN(RADIANS(lng - ${lng}) / 2), 2)
      )) AS distanceKm
    FROM Venue
    HAVING distanceKm <= ${radiusKm}
  `;
  const distanceByVenueId = new Map(nearbyVenues.map((v) => [v.id, Number(v.distanceKm)]));

  // Un doublon posté à un lieu mal géocodé sort du rayon : on rattrape ces cas
  // par les mots marquants du titre. Les plus longs sont les plus distinctifs.
  const probeWords = significantWords(event.title)
    .sort((a, b) => b.length - a.length)
    .slice(0, TITLE_PROBE_WORDS);

  const matchers: Prisma.EventWhereInput[] = [{ venueId: { in: [...distanceByVenueId.keys()] } }];
  for (const word of probeWords) {
    matchers.push({ title: { contains: word } });
  }

  const candidates = await prisma.event.findMany({
    where: {
      id: { not: event.id },
      status: { in: ['APPROVED', 'PENDING'] },
      OR: matchers,
    },
    include: MODERATION_INCLUDE,
    orderBy: { createdAt: 'desc' },
    take: MAX_CANDIDATES,
  });

  const ranked = rankSimilar(event, candidates, distanceByVenueId, { radiusKm, minScore, limit });

  res.json({
    event: serializeEvent(event),
    similar: ranked.map((r) => serializeEvent(r.event, r.similarity)),
  });
});

moderationRouter.post('/:id', async (req, res) => {
  const id = Number(req.params.id);
  const parsed = moderateSchema.safeParse(req.body);
  if (!Number.isInteger(id) || !parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const event = await prisma.event.findUnique({ where: { id }, include: { venue: true } });
  if (!event) {
    res.status(404).json({ error: 'Événement introuvable' });
    return;
  }
  if (event.status !== 'PENDING') {
    res.status(409).json({ error: 'Cet événement a déjà été modéré' });
    return;
  }

  const { action, reason } = parsed.data;
  // Rien de public tant qu'un champ laissé à compléter par un import n'a pas
  // été corrigé (voir lib/incomplete.ts).
  if (action === 'approve' && !hasCoordinates(event.venue)) {
    res.status(409).json({
      error: "Le lieu n'est pas géolocalisé : complétez l'adresse avant d'approuver cette sortie",
    });
    return;
  }
  if (action === 'approve' && !hasPrice(event)) {
    res.status(409).json({
      error: "Le tarif n'a pas pu être déterminé : renseignez-le avant d'approuver cette sortie",
    });
    return;
  }
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
