import { Prisma } from '@prisma/client';
import { prisma } from '../db';
import { rankEvents } from './relevance';

/**
 * La lecture d'une sortie et son classement, en un seul endroit.
 *
 * Ces trois briques vivaient dans `routes/events.ts`, et c'était tenable tant
 * que l'API était seule à s'en servir. Le pré-rendu SEO lit désormais les mêmes
 * sorties pour écrire le même document *et* l'état initial que l'application
 * reprendra : trois copies de « ce qu'est une sortie publique » auraient dérivé
 * l'une de l'autre, et c'est déjà arrivé — le pré-rendu triait par date de
 * début quand l'API classait par pertinence, de sorte que le moteur indexait un
 * ordre que le visiteur ne voyait jamais.
 */

/**
 * Ce qu'il faut charger avec une sortie pour la rendre.
 *
 * `scraperItems` est là pour une seule question : la fiche vient-elle d'une
 * recherche automatique ? Un item suffit à y répondre, d'où le `take: 1`.
 */
export const EVENT_INCLUDE = {
  venue: true,
  category: true,
  author: { select: { id: true, displayName: true } },
  dates: { select: { day: true }, orderBy: { day: 'asc' } },
  scraperItems: { select: { id: true }, take: 1 },
} as const satisfies Prisma.EventInclude;

export type EventWithRelations = Prisma.EventGetPayload<{ include: typeof EVENT_INCLUDE }>;

/** `2026-09-20`, sans décalage de fuseau : ces colonnes sont des DATE. */
function isoDay(value: Date): string {
  return value.toISOString().slice(0, 10);
}

/**
 * Une sortie, telle que l'API la rend — et telle que le pré-rendu l'écrit dans
 * l'état initial. Les deux doivent coïncider au champ près : l'application ne
 * sait pas d'où vient ce qu'elle affiche, et ne doit pas avoir à le savoir.
 */
export function serializeEvent(event: EventWithRelations, distanceKm?: number) {
  const { scraperItems, ...rest } = event;
  return {
    ...rest,
    /**
     * La fiche vient d'une recherche automatique. Ce qui en dépend : `foundOnUrl`
     * et `sourceUrl` sont alors deux **faits** — la page lue et le meilleur lien
     * connu —, là où une proposition de visiteur n'a qu'une adresse saisie.
     */
    fromScraper: scraperItems.length > 0,
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

export type SerializedEvent = ReturnType<typeof serializeEvent>;

/** Ce qui décide du classement, en plus du filtre déjà construit. */
export interface RankedPageOptions {
  /** L'âge demandé, quand il l'a été : il pèse dans le score. */
  age?: number;
  /** Le premier jour de la fenêtre — `2026-09-20`. */
  from: string;
  page: number;
  pageSize: number;
}

/**
 * Une page de sorties, classée par pertinence.
 *
 * Le classement ne se fait pas en SQL : le score mêle la précision de l'âge, la
 * brièveté de la période et l'imminence, dont deux dépendent de ce qui a été
 * demandé (voir `lib/relevance.ts`). On relève donc de quoi classer — six
 * colonnes, pas les fiches — puis on ne charge en entier que la page demandée.
 * Le compte total tombe du même coup, sans seconde requête.
 */
export async function rankedPage(
  where: Prisma.EventWhereInput,
  { age, from, page, pageSize }: RankedPageOptions,
): Promise<{ events: EventWithRelations[]; total: number }> {
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
  const ordered = rankEvents(matches, { age, from });
  const ids = ordered.slice((page - 1) * pageSize, page * pageSize);

  // `findMany` rend ce que la base veut ; l'ordre est celui du classement, et
  // c'est ici qu'on le remet — sans quoi la page s'afficherait par identifiant.
  const rows = ids.length
    ? await prisma.event.findMany({ where: { id: { in: ids } }, include: EVENT_INCLUDE })
    : [];
  const byId = new Map(rows.map((e) => [e.id, e]));
  return {
    events: ids.map((id) => byId.get(id)).filter((e): e is EventWithRelations => !!e),
    total: ordered.length,
  };
}
