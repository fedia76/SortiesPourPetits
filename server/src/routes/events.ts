import { Prisma, Role } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { hasRole, requireAuth } from '../middleware/auth';
import { deletePhoto, photoUpload, savePhoto } from '../lib/upload';
import { eventInputSchema, searchSchema } from '../lib/validators';

export const eventsRouter = Router();

type EventWithRelations = Prisma.EventGetPayload<{
  include: {
    venue: true;
    category: true;
    openingHours: true;
    author: { select: { id: true; displayName: true } };
  };
}>;

const EVENT_INCLUDE = {
  venue: true,
  category: true,
  openingHours: true,
  author: { select: { id: true, displayName: true } },
} as const;

/** Convertit les Decimal Prisma en nombres pour le JSON. */
function serializeEvent(event: EventWithRelations, distanceKm?: number) {
  return {
    ...event,
    price: event.price === null ? null : Number(event.price),
    dateStart: event.dateStart.toISOString().slice(0, 10),
    dateEnd: event.dateEnd.toISOString().slice(0, 10),
    venue: {
      ...event.venue,
      lat: Number(event.venue.lat),
      lng: Number(event.venue.lng),
    },
    distanceKm: distanceKm === undefined ? undefined : Math.round(distanceKm * 10) / 10,
  };
}

/**
 * Recherche publique avec tous les filtres, y compris la distance.
 * Le filtre géographique passe par ST_Distance_Sphere de MySQL sur la
 * table Venue, puis on restreint la requête Prisma aux lieux trouvés.
 */
eventsRouter.get('/', async (req, res) => {
  const parsed = searchSchema.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: 'Paramètres de recherche invalides' });
    return;
  }
  const f = parsed.data;

  const and: Prisma.EventWhereInput[] = [];
  const where: Prisma.EventWhereInput = { status: 'APPROVED', AND: and };

  if (f.q) {
    and.push({ OR: [{ title: { contains: f.q } }, { description: { contains: f.q } }] });
  }
  if (f.free === 'true') {
    where.isFree = true;
  } else if (f.priceMax !== undefined) {
    and.push({ OR: [{ isFree: true }, { price: { lte: f.priceMax } }] });
  }
  if (f.age !== undefined) {
    where.ageMin = { lte: f.age };
    where.ageMax = { gte: f.age };
  }
  // Chevauchement de périodes : l'événement est visible s'il est en cours
  // à un moment de l'intervalle demandé. Par défaut : pas encore terminé.
  const from = f.from ?? new Date().toISOString().slice(0, 10);
  where.dateEnd = { gte: new Date(from) };
  if (f.to) {
    where.dateStart = { lte: new Date(f.to) };
  }
  if (f.setting) {
    // Un lieu « les deux » satisfait une recherche intérieur OU extérieur.
    where.setting = f.setting === 'BOTH' ? 'BOTH' : { in: [f.setting, 'BOTH'] };
  }
  if (f.categoryId !== undefined) {
    where.categoryId = f.categoryId;
  }

  // Filtre distance : liste des lieux dans le rayon + distance de chacun.
  // Formule de Haversine en SQL pur (compatible MySQL et MariaDB).
  let distanceByVenueId: Map<number, number> | undefined;
  if (f.lat !== undefined && f.lng !== undefined && f.radiusKm !== undefined) {
    const rows = await prisma.$queryRaw<{ id: number; distanceKm: number }[]>`
      SELECT id,
        6371 * 2 * ASIN(SQRT(
          POWER(SIN(RADIANS(lat - ${f.lat}) / 2), 2) +
          COS(RADIANS(${f.lat})) * COS(RADIANS(lat)) *
          POWER(SIN(RADIANS(lng - ${f.lng}) / 2), 2)
        )) AS distanceKm
      FROM Venue
      HAVING distanceKm <= ${f.radiusKm}
    `;
    distanceByVenueId = new Map(rows.map((r) => [r.id, Number(r.distanceKm)]));
    if (distanceByVenueId.size === 0) {
      res.json({ events: [], total: 0, page: f.page, pageSize: f.pageSize });
      return;
    }
    where.venueId = { in: [...distanceByVenueId.keys()] };
  }

  const [total, events] = await prisma.$transaction([
    prisma.event.count({ where }),
    prisma.event.findMany({
      where,
      include: EVENT_INCLUDE,
      orderBy: { dateStart: 'asc' },
      skip: (f.page - 1) * f.pageSize,
      take: f.pageSize,
    }),
  ]);

  res.json({
    events: events.map((e) => serializeEvent(e, distanceByVenueId?.get(e.venueId))),
    total,
    page: f.page,
    pageSize: f.pageSize,
  });
});

/** Les événements de l'utilisateur connecté, tous statuts confondus. */
eventsRouter.get('/mine', requireAuth, async (req, res) => {
  const events = await prisma.event.findMany({
    where: { createdById: req.user!.id },
    include: EVENT_INCLUDE,
    orderBy: { createdAt: 'desc' },
  });
  res.json({ events: events.map((e) => serializeEvent(e)) });
});

eventsRouter.get('/:id', async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: 'Identifiant invalide' });
    return;
  }
  const event = await prisma.event.findUnique({ where: { id }, include: EVENT_INCLUDE });
  if (!event) {
    res.status(404).json({ error: 'Événement introuvable' });
    return;
  }
  // Un événement non approuvé n'est visible que par son auteur et les modérateurs.
  const canSeeUnapproved =
    req.user && (req.user.id === event.createdById || hasRole(req.user, Role.MODERATOR));
  if (event.status !== 'APPROVED' && !canSeeUnapproved) {
    res.status(404).json({ error: 'Événement introuvable' });
    return;
  }
  res.json({ event: serializeEvent(event) });
});

function parseEventBody(raw: unknown) {
  if (typeof raw !== 'string') return null;
  try {
    return eventInputSchema.safeParse(JSON.parse(raw));
  } catch {
    return null;
  }
}

/** Trouve ou crée le lieu (réutilisé si même nom + adresse). */
async function upsertVenue(venue: {
  name: string;
  address: string;
  city: string;
  postalCode: string;
  lat: number;
  lng: number;
}) {
  const existing = await prisma.venue.findFirst({
    where: { name: venue.name, address: venue.address, city: venue.city },
  });
  return existing ?? prisma.venue.create({ data: venue });
}

eventsRouter.post('/', requireAuth, photoUpload.single('photo'), async (req, res) => {
  const parsed = parseEventBody(req.body.data);
  if (!parsed) {
    res.status(400).json({ error: 'Corps de requête invalide' });
    return;
  }
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const input = parsed.data;
  const venue = await upsertVenue(input.venue);
  const photoUrl = req.file ? await savePhoto(req.file.buffer) : null;

  const event = await prisma.event.create({
    data: {
      title: input.title,
      description: input.description,
      isFree: input.isFree,
      price: input.isFree ? null : input.price,
      photoUrl,
      ageMin: input.ageMin,
      ageMax: input.ageMax,
      dateStart: new Date(input.dateStart),
      dateEnd: new Date(input.dateEnd),
      setting: input.setting,
      venueId: venue.id,
      categoryId: input.categoryId,
      createdById: req.user!.id,
      openingHours: { create: input.openingHours },
    },
    include: EVENT_INCLUDE,
  });

  res.status(201).json({ event: serializeEvent(event) });
});

eventsRouter.put('/:id', requireAuth, photoUpload.single('photo'), async (req, res) => {
  const id = Number(req.params.id);
  const existing = await prisma.event.findUnique({ where: { id } });
  if (!existing) {
    res.status(404).json({ error: 'Événement introuvable' });
    return;
  }
  const isModerator = hasRole(req.user, Role.MODERATOR);
  if (existing.createdById !== req.user!.id && !isModerator) {
    res.status(403).json({ error: 'Vous ne pouvez modifier que vos propres événements' });
    return;
  }

  const parsed = parseEventBody(req.body.data);
  if (!parsed) {
    res.status(400).json({ error: 'Corps de requête invalide' });
    return;
  }
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const input = parsed.data;
  const venue = await upsertVenue(input.venue);

  let photoUrl = existing.photoUrl;
  if (req.file) {
    if (existing.photoUrl) await deletePhoto(existing.photoUrl);
    photoUrl = await savePhoto(req.file.buffer);
  }

  const event = await prisma.event.update({
    where: { id },
    data: {
      title: input.title,
      description: input.description,
      isFree: input.isFree,
      price: input.isFree ? null : input.price,
      photoUrl,
      ageMin: input.ageMin,
      ageMax: input.ageMax,
      dateStart: new Date(input.dateStart),
      dateEnd: new Date(input.dateEnd),
      setting: input.setting,
      venueId: venue.id,
      categoryId: input.categoryId,
      // Une modification par l'auteur repasse en modération.
      status: isModerator ? existing.status : 'PENDING',
      rejectionReason: isModerator ? existing.rejectionReason : null,
      openingHours: { deleteMany: {}, create: input.openingHours },
    },
    include: EVENT_INCLUDE,
  });

  res.json({ event: serializeEvent(event) });
});

eventsRouter.delete('/:id', requireAuth, async (req, res) => {
  const id = Number(req.params.id);
  const existing = await prisma.event.findUnique({ where: { id } });
  if (!existing) {
    res.status(404).json({ error: 'Événement introuvable' });
    return;
  }
  if (existing.createdById !== req.user!.id && !hasRole(req.user, Role.MODERATOR)) {
    res.status(403).json({ error: 'Vous ne pouvez supprimer que vos propres événements' });
    return;
  }
  await prisma.event.delete({ where: { id } });
  if (existing.photoUrl) await deletePhoto(existing.photoUrl);
  res.json({ ok: true });
});
