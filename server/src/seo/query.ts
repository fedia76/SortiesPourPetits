import { Area, Category } from '@prisma/client';
import { prisma } from '../db';
import { areaFilter } from '../lib/areas';
import { dateFilter, today } from '../lib/dateWindow';
import {
  EVENT_INCLUDE,
  rankedPage,
  serializeEvent,
  type EventWithRelations,
  type SerializedEvent,
} from '../lib/eventSearch';
import { allCategories, areasWithCounts, type AreaWithCount } from '../lib/publicLists';

/**
 * Ce que le pré-rendu lit en base : exactement ce que lit l'API publique.
 *
 * Il lisait moins, et c'était défendable tant qu'il n'écrivait qu'un `<meta>`.
 * Il écrit désormais aussi l'état initial du document — ce que l'API aurait
 * répondu, pour que l'application n'ait pas à le redemander —, et un état
 * amputé de la moitié des champs n'aurait servi à rien. La borne n'a pas
 * changé de nature, elle a changé de place : ce qui part dans le document est
 * ce qu'un visiteur anonyme obtient déjà en appelant `/api/events/:id`.
 */
type EventRow = EventWithRelations;

/** Une sortie approuvée, prête à être écrite en HTML. */
export interface PublicEvent {
  id: number;
  title: string;
  description: string;
  /** Le meilleur lien connu vers la sortie — la page de l'organisateur, au mieux. */
  sourceUrl: string | null;
  /** Ce qui a désigné ce lien : `json_ld`, `venue_domain`, `page_link`, `search`, `manuel`. */
  sourceUrlSignal: string | null;
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
    sourceUrl: row.sourceUrl,
    sourceUrlSignal: row.sourceUrlSignal,
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

/** Une sortie, sous ses deux formes : celle qu'on écrit, celle qu'on transmet. */
export interface PublicEventPage {
  /** Ce dont le HTML et les `<meta>` ont besoin. */
  event: PublicEvent;
  /** Ce que `GET /api/events/:id` aurait répondu, mot pour mot. */
  payload: { event: SerializedEvent };
}

/**
 * La fiche d'une sortie, si et seulement si elle est publique.
 *
 * Le pré-rendu ne s'authentifie pas : il produit un document que n'importe
 * quel cache — le navigateur, un proxy, un moteur — peut garder et resservir à
 * n'importe qui. Une sortie en attente ou refusée n'y a donc pas sa place,
 * même pour son auteur ; c'est l'application qui la lui montrera, une fois
 * démarrée, par un appel authentifié à l'API.
 *
 * C'est aussi ce qui rend l'état initial sûr à transmettre : la réponse de
 * l'API pour une sortie approuvée ne dépend pas de qui la demande.
 */
export async function findPublicEvent(id: number): Promise<PublicEventPage | null> {
  const row = await prisma.event.findFirst({
    where: { id, status: 'APPROVED' },
    include: EVENT_INCLUDE,
  });
  if (!row) return null;
  return { event: toPublic(row), payload: { event: serializeEvent(row) } };
}

/** Les zones ouvertes, dans leur ordre d'affichage. */
export function listAreas(): Promise<Area[]> {
  return prisma.area.findMany({ orderBy: [{ position: 'asc' }, { name: 'asc' }] });
}

/**
 * Les mêmes, avec le compte que l'application affiche dans ses badges.
 *
 * Deux fonctions et non une : le sitemap n'a que faire des comptes, et les
 * calculer lui coûterait une requête par zone pour rien.
 */
export function listAreasPayload(): Promise<AreaWithCount[]> {
  return areasWithCounts();
}

/** Les catégories, telles que `GET /api/categories` les rend. */
export function listCategories(): Promise<Category[]> {
  return allCategories();
}

export function findArea(slug: string): Promise<Area | null> {
  return prisma.area.findUnique({ where: { slug } });
}

/** Une page de liste, sous ses deux formes — comme pour une fiche. */
export interface PublicEventList {
  events: PublicEvent[];
  total: number;
  /** Ce que `GET /api/events?…` aurait répondu, mot pour mot. */
  payload: { events: SerializedEvent[]; total: number; page: number; pageSize: number };
}

/**
 * Une page de sorties, dans le même ordre que ce que l'application affiche.
 * Restreinte à une zone quand on en passe une.
 *
 * Le classement passe par `rankedPage`, celui-là même qu'utilise la route de
 * recherche. Il ne l'utilisait pas : il triait par date de début, quand l'API
 * classait par pertinence depuis `lib/relevance`. Le moteur indexait donc une
 * liste que le visiteur ne voyait jamais — et l'état initial aurait transmis
 * la mauvaise. Une seule façon de classer, un seul endroit où elle vit.
 */
export async function listPublicEvents(
  page: number,
  pageSize: number,
  area?: Area | null,
): Promise<PublicEventList> {
  const from = today();
  const { events, total } = await rankedPage(
    {
      status: 'APPROVED',
      AND: [dateFilter(from), ...(area ? [areaFilter(area.postalPrefixes)] : [])],
    },
    { from, page, pageSize },
  );
  return {
    events: events.map(toPublic),
    total,
    payload: { events: events.map((e) => serializeEvent(e)), total, page, pageSize },
  };
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
    orderBy: { dateStart: 'asc' },
    take: SITEMAP_MAX,
  });
}

/**
 * Quand une page de liste a-t-elle changé pour la dernière fois ?
 *
 * C'est la date de la sortie la plus récemment publiée parmi celles qu'elle
 * affiche. Un moteur s'appuie dessus pour décider s'il vaut la peine de
 * revenir : sans elle, l'accueil et les pages de zone ne disent jamais qu'elles
 * ont bougé, et rien ne les distingue d'une page figée — quand bien même leur
 * contenu change toutes les semaines.
 *
 * On ne met surtout pas la date du jour : une page qui se prétend modifiée en
 * permanence perd sa crédibilité, et le signal cesse d'être lu.
 */
export async function lastPublishedAt(area?: Area | null): Promise<Date | null> {
  const latest = await prisma.event.findFirst({
    where: {
      status: 'APPROVED',
      AND: [dateFilter(today()), ...(area ? [areaFilter(area.postalPrefixes)] : [])],
    },
    select: { createdAt: true },
    orderBy: { createdAt: 'desc' },
  });
  return latest?.createdAt ?? null;
}
