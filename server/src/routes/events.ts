import { EventStatus, Prisma, Role, Setting } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { hasRole, requireAuth } from '../middleware/auth';
import { deletePhoto, photoUpload, savePhoto } from '../lib/upload';
import { hasCoordinates } from '../lib/incomplete';
import { eventInputSchema, searchSchema } from '../lib/validators';
import { diffEvent, type ComparableEvent } from '../lib/eventCorrections';
import { dateFilter } from '../lib/dateWindow';
import { areaFilter } from '../lib/areas';
import { rankEvents } from '../lib/relevance';

export const eventsRouter = Router();

type EventWithRelations = Prisma.EventGetPayload<{
  include: {
    venue: true;
    category: true;
    author: { select: { id: true; displayName: true } };
    dates: { select: { day: true } };
  };
}>;

const EVENT_INCLUDE = {
  venue: true,
  category: true,
  author: { select: { id: true, displayName: true } },
  dates: { select: { day: true }, orderBy: { day: 'asc' } },
} as const satisfies Prisma.EventInclude;

/** `2026-09-20`, sans décalage de fuseau : ces colonnes sont des DATE. */
function isoDay(value: Date): string {
  return value.toISOString().slice(0, 10);
}

/** Convertit les Decimal Prisma en nombres pour le JSON. */
function serializeEvent(event: EventWithRelations, distanceKm?: number) {
  return {
    ...event,
    price: event.price === null ? null : Number(event.price),
    dateStart: event.dateStart ? isoDay(event.dateStart) : null,
    dateEnd: event.dateEnd ? isoDay(event.dateEnd) : null,
    dates: event.dates.map((d) => isoDay(d.day)),
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
/**
 * Lignes `EventDate` à écrire. Dédoublonnées : la contrainte d'unicité
 * ferait échouer la création entière pour un doublon dans le formulaire.
 */
function eventDates(input: { isPermanent: boolean; dates: string[] }) {
  if (input.isPermanent) return [];
  return [...new Set(input.dates)].sort().map((day) => ({ day: new Date(day) }));
}

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
    // Une tranche d'âge non renseignée est considérée comme ouverte à tous.
    and.push({ OR: [{ ageMin: null }, { ageMin: { lte: f.age } }] });
    and.push({ OR: [{ ageMax: null }, { ageMax: { gte: f.age } }] });
  }
  // Chevauchement de périodes : l'événement est visible s'il est en cours
  // à un moment de l'intervalle demandé. Par défaut : pas encore terminé.
  // Un événement permanent (sans date de fin) est toujours considéré en cours.
  const from = f.from ?? new Date().toISOString().slice(0, 10);
  and.push(dateFilter(from, f.to));
  if (f.setting) {
    // Un lieu « les deux » satisfait une recherche intérieur OU extérieur.
    // Un cadre non renseigné satisfait n'importe quelle recherche de cadre.
    const settingMatch: Setting[] = f.setting === 'BOTH' ? ['BOTH'] : [f.setting, 'BOTH'];
    and.push({ OR: [{ setting: null }, { setting: { in: settingMatch } }] });
  }
  // La zone se résout ici plutôt que dans le schéma : c'est une lecture en
  // base, et une zone inconnue doit répondre « aucun résultat » — pas « toutes
  // les sorties de France », ce qui arriverait si on ignorait le filtre.
  if (f.area) {
    const area = await prisma.area.findUnique({ where: { slug: f.area } });
    if (!area) {
      res.json({ events: [], total: 0, page: f.page, pageSize: f.pageSize });
      return;
    }
    and.push(areaFilter(area.postalPrefixes));
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

  // Le classement ne se fait pas en SQL : le score mêle la précision de l'âge,
  // la brièveté de la période et l'imminence, dont deux dépendent de ce qui a
  // été demandé (voir `lib/relevance.ts`). On relève donc de quoi classer —
  // cinq colonnes, pas les fiches — puis on ne charge en entier que la page
  // demandée. Le compte total tombe du même coup, sans seconde requête.
  const matches = await prisma.event.findMany({
    where,
    select: {
      id: true,
      ageMin: true,
      ageMax: true,
      isPermanent: true,
      dateStart: true,
      dateEnd: true,
    },
  });
  const ordered = rankEvents(matches, { age: f.age, from });
  const ids = ordered.slice((f.page - 1) * f.pageSize, f.page * f.pageSize);

  // `findMany` rend ce que la base veut ; l'ordre est celui du classement, et
  // c'est ici qu'on le remet — sans quoi la page s'afficherait par identifiant.
  const rows = ids.length
    ? await prisma.event.findMany({ where: { id: { in: ids } }, include: EVENT_INCLUDE })
    : [];
  const byId = new Map(rows.map((e) => [e.id, e]));
  const events = ids.map((id) => byId.get(id)).filter((e): e is EventWithRelations => !!e);

  res.json({
    events: events.map((e) => serializeEvent(e, distanceByVenueId?.get(e.venueId))),
    total: ordered.length,
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
  if (!existing) return prisma.venue.create({ data: venue });
  // Un lieu créé sans coordonnées (import non géocodé) est complété dès qu'une
  // position arrive : sans ça, le modérateur corrigerait l'adresse sans effet.
  if (!hasCoordinates(existing) && hasCoordinates(venue)) {
    return prisma.venue.update({
      where: { id: existing.id },
      data: { lat: venue.lat, lng: venue.lng, postalCode: venue.postalCode },
    });
  }
  return existing;
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

  // La provenance et le signal ne sont crédibles que d'un programme. Un
  // formulaire ne sait pas d'où il tient son lien : le laisser annoncer
  // « déclaré par la page » ferait passer une saisie pour une trouvaille
  // vérifiée, exactement la confusion que ces champs existent pour éviter.
  const fromProgram = req.viaApiKey === true;

  const event = await prisma.event.create({
    data: {
      title: input.title,
      description: input.description,
      sourceUrl: input.sourceUrl ?? null,
      foundOnUrl: fromProgram ? input.foundOnUrl ?? null : null,
      sourceUrlSignal: fromProgram
        ? input.sourceUrlSignal ?? null
        : input.sourceUrl
          ? 'manuel'
          : null,
      isFree: input.isFree,
      price: input.isFree ? null : input.price,
      photoUrl,
      ageMin: input.ageMin ?? null,
      ageMax: input.ageMax ?? null,
      isPermanent: input.isPermanent,
      dateStart: input.isPermanent ? null : new Date(input.dateStart!),
      dateEnd: input.isPermanent ? null : new Date(input.dateEnd!),
      openTime: input.openTime ?? null,
      closeTime: input.closeTime ?? null,
      setting: input.setting ?? null,
      venueId: venue.id,
      categoryId: input.categoryId,
      createdById: req.user!.id,
      dates: { create: eventDates(input) },
    },
    include: EVENT_INCLUDE,
  });

  res.status(201).json({ event: serializeEvent(event) });
});

eventsRouter.put('/:id', requireAuth, photoUpload.single('photo'), async (req, res) => {
  const id = Number(req.params.id);
  const existing = await prisma.event.findUnique({
    where: { id },
    // Le lieu et les dates servent à mesurer ce que la modération corrige ; un
    // seul item du scraper suffit à savoir que la fiche vient de lui.
    include: {
      venue: true,
      dates: { select: { day: true }, orderBy: { day: 'asc' } },
      scraperItems: { select: { id: true }, take: 1 },
    },
  });
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

  // Changer le lien reprend la main sur ce que le scraper avait déduit : le
  // signal ne décrit plus rien de vrai, et le garder ferait passer une saisie
  // pour une trouvaille vérifiée. Le laisser tel quel si l'URL n'a pas bougé,
  // en revanche, préserve ce qu'on savait d'elle — on peut corriger un titre
  // sans effacer la provenance du lien.
  //
  // `foundOnUrl` ne bouge jamais ici : d'où la sortie *est arrivée* est un
  // fait, pas une préférence, et rien de ce qu'on corrige sur la fiche ne le
  // réécrit.
  const sourceUrl = input.sourceUrl ?? null;
  const sourceUrlSignal =
    sourceUrl === existing.sourceUrl ? existing.sourceUrlSignal : sourceUrl && 'manuel';

  const event = await prisma.event.update({
    where: { id },
    data: {
      title: input.title,
      description: input.description,
      sourceUrl,
      sourceUrlSignal,
      isFree: input.isFree,
      price: input.isFree ? null : input.price,
      photoUrl,
      ageMin: input.ageMin ?? null,
      ageMax: input.ageMax ?? null,
      isPermanent: input.isPermanent,
      dateStart: input.isPermanent ? null : new Date(input.dateStart!),
      dateEnd: input.isPermanent ? null : new Date(input.dateEnd!),
      openTime: input.openTime ?? null,
      closeTime: input.closeTime ?? null,
      setting: input.setting ?? null,
      venueId: venue.id,
      categoryId: input.categoryId,
      // Remplacement en bloc : les dates n'ont pas d'existence propre, elles
      // décrivent la sortie telle qu'elle vient d'être décrite.
      dates: { deleteMany: {}, create: eventDates(input) },
      // Une modification par l'auteur repasse en modération.
      status: isModerator ? existing.status : 'PENDING',
      rejectionReason: isModerator ? existing.rejectionReason : null,
      rejectionCode: isModerator ? existing.rejectionCode : null,
    },
    include: EVENT_INCLUDE,
  });

  await recordCorrections(id, existing, event);

  res.json({ event: serializeEvent(event) });
});

/** `Date` → `YYYY-MM-DD`, ou rien. Les fiches se comparent en clair. */
function day(value: Date | null): string | null {
  return value ? value.toISOString().slice(0, 10) : null;
}

/** Une fiche telle que la base la rend, avec ce qu'il faut pour la comparer. */
type Comparable = {
  title: string;
  description: string;
  sourceUrl: string | null;
  isFree: boolean;
  price: Prisma.Decimal | null;
  ageMin: number | null;
  ageMax: number | null;
  isPermanent: boolean;
  dateStart: Date | null;
  dateEnd: Date | null;
  openTime: string | null;
  closeTime: string | null;
  setting: Setting | null;
  categoryId: number;
  venue: { name: string; address: string; city: string; postalCode: string };
  dates: { day: Date }[];
};

function comparable(event: Comparable): ComparableEvent {
  return {
    title: event.title,
    description: event.description,
    sourceUrl: event.sourceUrl,
    isFree: event.isFree,
    price: event.price === null ? null : Number(event.price),
    ageMin: event.ageMin,
    ageMax: event.ageMax,
    isPermanent: event.isPermanent,
    dateStart: day(event.dateStart),
    dateEnd: day(event.dateEnd),
    openTime: event.openTime,
    closeTime: event.closeTime,
    setting: event.setting,
    categoryId: event.categoryId,
    venueName: event.venue.name,
    venueAddress: event.venue.address,
    venueCity: event.venue.city,
    venuePostalCode: event.venue.postalCode,
    dates: event.dates.map((d) => d.day.toISOString().slice(0, 10)).sort(),
  };
}

/**
 * Enregistre ce que la modération a corrigé sur une fiche du scraper.
 *
 * Trois conditions, et elles sont étroites à dessein :
 *
 * * la fiche vient de la **recherche automatique** — un item la désigne. Une
 *   proposition de visiteur corrigée ne dit rien de l'étage 6 ;
 * * elle était encore **en attente** avant l'édition. Une retouche éditoriale
 *   six mois après approbation est une amélioration du catalogue, pas une
 *   erreur d'extraction, et la compter ici polluerait la mesure exactement
 *   comme le comptage de liens avait pollué le classifieur ;
 * * c'est un **modérateur** qui édite. L'auteur d'une fiche importée est la
 *   clé d'API du scraper : personne d'autre ne passe par là.
 *
 * Rien de tout ceci ne peut faire échouer la requête. Une mesure est un
 * confort ; refuser une correction de fiche parce qu'on n'a pas su la compter
 * serait le plus sûr moyen de faire retirer le dispositif.
 */
async function recordCorrections(
  eventId: number,
  before: Comparable & { status: EventStatus; scraperItems: { id: number }[] },
  after: Comparable,
): Promise<void> {
  if (before.status !== 'PENDING' || before.scraperItems.length === 0) return;
  const corrections = diffEvent(comparable(before), comparable(after));
  if (corrections.length === 0) return;
  try {
    await prisma.eventCorrection.createMany({
      data: corrections.map((c) => ({ ...c, eventId })),
    });
  } catch {
    // Le catalogue passe avant sa mesure : une écriture ratée ici ne doit ni
    // annuler la correction, ni se voir de l'utilisateur.
  }
}

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
