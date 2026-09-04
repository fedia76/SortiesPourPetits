import { Prisma, Role } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { requireRole } from '../middleware/auth';
import { deletePhoto } from '../lib/upload';
import {
  moderateSchema,
  moderationPurgeSchema,
  moderationQueueSchema,
  similarSchema,
  type ModerationFilter,
} from '../lib/validators';
import { hasCoordinates, hasPrice } from '../lib/incomplete';
import { rankSimilar, significantWords, type SimilarityScore } from '../lib/similarity';

export const moderationRouter = Router();

moderationRouter.use(requireRole(Role.MODERATOR));

const MODERATION_INCLUDE = {
  venue: true,
  category: true,
  author: { select: { id: true, displayName: true, email: true } },
  // Le modérateur doit voir les jours de représentation : c'est ce que le
  // scraper a déduit d'une page, et c'est là qu'on le corrige.
  dates: { select: { day: true }, orderBy: { day: 'asc' } },
  // D'où vient la proposition. Une seule ligne suffit : les suivantes
  // désigneraient la même page revue par une autre exécution.
  scraperItems: {
    select: { run: { select: { configId: true, config: { select: { name: true } } } } },
    orderBy: { id: 'asc' },
    take: 1,
  },
} as const satisfies Prisma.EventInclude;

type ModeratedEvent = Prisma.EventGetPayload<{ include: typeof MODERATION_INCLUDE }>;

/** Convertit les Decimal Prisma et les dates en valeurs JSON. */
function serializeEvent(event: ModeratedEvent, similarity?: SimilarityScore) {
  const { scraperItems, ...rest } = event;
  const from = scraperItems[0]?.run;
  // Une recherche de source ne propose aucune sortie — elle rejoue l'étage 7
  // sur une fiche existante — donc elle n'a jamais d'item, et la recherche
  // rattachée à un item porte toujours sa configuration. Le second test est
  // là pour le type, pas pour un cas connu.
  const origin =
    from?.config && from.configId !== null
      ? { configId: from.configId, configName: from.config.name }
      : null;
  return {
    ...rest,
    // `null` pour une sortie proposée par un visiteur : c'est ce que la
    // console affiche, et ce sur quoi le filtre « visiteurs » s'appuie.
    origin,
    price: event.price === null ? null : Number(event.price),
    dateStart: event.dateStart ? event.dateStart.toISOString().slice(0, 10) : null,
    dateEnd: event.dateEnd ? event.dateEnd.toISOString().slice(0, 10) : null,
    dates: event.dates.map((d) => d.day.toISOString().slice(0, 10)),
    venue: { ...event.venue, lat: Number(event.venue.lat), lng: Number(event.venue.lng) },
    similarity,
  };
}

/**
 * La file, éventuellement restreinte à une origine.
 *
 * Une recherche automatique couvre un territoire — « Seine-Maritime » ne
 * propose que de la Seine-Maritime — donc filtrer par recherche revient à
 * modérer une région à la fois, ce qui demande un tout autre regard que de
 * relire vingt propositions venues de partout.
 */
function pendingWhere(filter: ModerationFilter): Prisma.EventWhereInput {
  const where: Prisma.EventWhereInput = { status: 'PENDING' };
  if (filter.configId) {
    where.scraperItems = { some: { run: { configId: filter.configId } } };
  } else if (filter.origin === 'scraper') {
    where.scraperItems = { some: {} };
  } else if (filter.origin === 'visitors') {
    where.scraperItems = { none: {} };
  }
  return where;
}

moderationRouter.get('/pending', async (req, res) => {
  const parsed = moderationQueueSchema.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const events = await prisma.event.findMany({
    where: pendingWhere(parsed.data),
    include: MODERATION_INCLUDE,
    orderBy: { createdAt: 'asc' },
  });
  res.json({ events: events.map((e) => serializeEvent(e)) });
});

/**
 * Vide la file d'attente — supprime, ne refuse pas.
 *
 * Refuser garde la sortie et son motif, que son auteur peut lire. Supprimer
 * ne garde rien : c'est ce qu'on veut après un import raté, vingt pages mal
 * lues qu'il serait absurde de motiver une par une.
 *
 * La mémoire du scraper n'est pas touchée — `ScrapedUrl.eventId` passe à NULL
 * (`onDelete: SetNull`) mais la ligne reste, donc la page n'est pas
 * reproposée. C'est `DELETE /api/scraper/memory` qui la rend à nouveau
 * lisible, et les deux gestes sont bien distincts.
 *
 * Irréversible, d'où le garde-fou : la file doit être celle qu'on avait sous
 * les yeux — au nombre près, et au filtre près. Vider une file restreinte à
 * une recherche ne supprime que les propositions de cette recherche.
 */
moderationRouter.delete('/pending', async (req, res) => {
  const parsed = moderationPurgeSchema.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const { expected, ...filter } = parsed.data;
  // Le même filtre que l'affichage : une file restreinte à une recherche ne
  // doit pas emporter les propositions qu'elle masquait.
  const pending = await prisma.event.findMany({
    where: pendingWhere(filter),
    select: { id: true, photoUrl: true },
  });

  if (expected !== undefined && expected !== pending.length) {
    res.status(409).json({
      error:
        `La file a changé depuis son affichage : elle compte maintenant ` +
        `${pending.length} sortie(s) au lieu de ${expected}. Rechargez la page.`,
    });
    return;
  }
  if (pending.length === 0) {
    res.json({ ok: true, deleted: 0 });
    return;
  }

  await prisma.event.deleteMany({ where: { id: { in: pending.map((e) => e.id) } } });
  // Les photos ne partent qu'une fois les lignes supprimées : un fichier
  // orphelin se repère, une fiche sans sa photo ne se répare pas.
  for (const event of pending) {
    if (event.photoUrl) await deletePhoto(event.photoUrl);
  }
  res.json({ ok: true, deleted: pending.length });
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
