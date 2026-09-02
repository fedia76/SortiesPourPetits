import { Prisma } from '@prisma/client';
import { prisma } from '../db';
import { dateFilter, today } from '../lib/dateWindow';

/**
 * Ce que le pré-rendu lit en base.
 *
 * Volontairement plus étroit que `EVENT_INCLUDE` de la route de recherche :
 * une page publique n'a pas à connaître le modérateur d'une sortie, et l'auteur
 * ne lui sert qu'à écrire « proposée par ». Ce qui n'est pas lu ne peut pas
 * fuiter dans un `<meta>`.
 */
const PUBLIC_INCLUDE = {
  venue: true,
  category: { select: { id: true, name: true } },
  author: { select: { displayName: true } },
  dates: { select: { day: true }, orderBy: { day: 'asc' } },
} as const satisfies Prisma.EventInclude;

type EventRow = Prisma.EventGetPayload<{ include: typeof PUBLIC_INCLUDE }>;

/** Une sortie approuvée, prête à être écrite en HTML. */
export interface PublicEvent {
  id: number;
  title: string;
  description: string;
  isFree: boolean;
  price: number | null;
  photoUrl: string | null;
  ageMin: number | null;
  ageMax: number | null;
  isPermanent: boolean;
  dateStart: string | null;
  dateEnd: string | null;
  dates: string[];
  openTime: string | null;
  closeTime: string | null;
  setting: 'INDOOR' | 'OUTDOOR' | 'BOTH' | null;
  createdAt: Date;
  authorName: string;
  category: { id: number; name: string };
  venue: {
    name: string;
    address: string;
    city: string;
    postalCode: string;
    lat: number;
    lng: number;
  };
}

/** `2026-09-20`, sans décalage de fuseau : ces colonnes sont des DATE. */
function isoDay(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function toPublic(row: EventRow): PublicEvent {
  return {
    id: row.id,
    title: row.title,
    description: row.description,
    isFree: row.isFree,
    price: row.price === null ? null : Number(row.price),
    photoUrl: row.photoUrl,
    ageMin: row.ageMin,
    ageMax: row.ageMax,
    isPermanent: row.isPermanent,
    dateStart: row.dateStart ? isoDay(row.dateStart) : null,
    dateEnd: row.dateEnd ? isoDay(row.dateEnd) : null,
    dates: row.dates.map((d) => isoDay(d.day)),
    openTime: row.openTime,
    closeTime: row.closeTime,
    setting: row.setting,
    createdAt: row.createdAt,
    authorName: row.author.displayName,
    category: row.category,
    venue: {
      name: row.venue.name,
      address: row.venue.address,
      city: row.venue.city,
      postalCode: row.venue.postalCode,
      lat: Number(row.venue.lat),
      lng: Number(row.venue.lng),
    },
  };
}

/**
 * La fiche d'une sortie, si et seulement si elle est publique.
 *
 * Le pré-rendu ne s'authentifie pas : il produit un document que n'importe
 * quel cache — le navigateur, un proxy, un moteur — peut garder et resservir à
 * n'importe qui. Une sortie en attente ou refusée n'y a donc pas sa place,
 * même pour son auteur ; c'est l'application qui la lui montrera, une fois
 * démarrée, par un appel authentifié à l'API.
 */
export async function findPublicEvent(id: number): Promise<PublicEvent | null> {
  const row = await prisma.event.findFirst({
    where: { id, status: 'APPROVED' },
    include: PUBLIC_INCLUDE,
  });
  return row && toPublic(row);
}

/**
 * Le même ordre que `GET /api/events` — les sorties les plus proches d'abord.
 *
 * Ce n'est pas un détail de présentation : le HTML pré-rendu et ce que Vue
 * affichera ensuite doivent montrer les mêmes sorties dans le même ordre. Deux
 * listes différentes, c'est un moteur qui indexe autre chose que ce que le
 * visiteur verra.
 */
const PUBLIC_ORDER = { dateStart: 'asc' } as const;

/** Une page de l'accueil, dans le même ordre que ce que l'application affiche. */
export async function listPublicEvents(
  page: number,
  pageSize: number,
): Promise<{ events: PublicEvent[]; total: number }> {
  const where: Prisma.EventWhereInput = { status: 'APPROVED', AND: [dateFilter(today())] };
  const [rows, total] = await Promise.all([
    prisma.event.findMany({
      where,
      include: PUBLIC_INCLUDE,
      orderBy: PUBLIC_ORDER,
      skip: (page - 1) * pageSize,
      take: pageSize,
    }),
    prisma.event.count({ where }),
  ]);
  return { events: rows.map(toPublic), total };
}

/**
 * Un sitemap ne peut pas dépasser 50 000 adresses ; passé ce seuil il faut le
 * découper et publier un index. On s'arrête avant, plutôt que de livrer un
 * fichier que Google refusera en bloc — le jour où le plafond est atteint,
 * c'est le découpage qu'il faudra écrire.
 */
const SITEMAP_MAX = 50_000;

/**
 * Les sorties à soumettre aux moteurs : celles qui sont approuvées et qui
 * n'ont pas encore eu lieu. Une sortie passée reste consultable, mais la
 * proposer à l'indexation revient à demander qu'on la propose à des visiteurs.
 */
export function listSitemapEvents(): Promise<{ id: number; createdAt: Date }[]> {
  return prisma.event.findMany({
    where: { status: 'APPROVED', AND: [dateFilter(today())] },
    select: { id: true, createdAt: true },
    orderBy: PUBLIC_ORDER,
    take: SITEMAP_MAX,
  });
}
