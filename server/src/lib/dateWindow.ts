import { Prisma } from '@prisma/client';

/**
 * Une sortie tombe-t-elle dans la fenêtre demandée ?
 *
 * Trois cas, et c'est le deuxième qui a motivé la table `EventDate` : un
 * spectacle joué tous les dimanches de juillet et août ressortait un jeudi,
 * parce que seule sa période était connue.
 *
 * 1. permanente : toujours ;
 * 2. jours de représentation connus : il en faut un dans la fenêtre ;
 * 3. aucun jour enregistré : la période vaut pour tous ses jours, comme avant.
 *
 * Vit ici plutôt que dans la route de recherche parce que le sitemap pose la
 * même question qu'elle : une sortie terminée n'a rien à faire dans ce qu'on
 * soumet à un moteur, et « terminée » se décide d'une seule façon.
 */
export function dateFilter(from: string, to?: string): Prisma.EventWhereInput {
  const day = { gte: new Date(from), ...(to ? { lte: new Date(to) } : {}) };
  const overlapsRange: Prisma.EventWhereInput = {
    AND: [
      { dateEnd: { gte: new Date(from) } },
      ...(to ? [{ dateStart: { lte: new Date(to) } }] : []),
    ],
  };
  return {
    OR: [
      { isPermanent: true },
      { dates: { some: { day } } },
      { AND: [{ dates: { none: {} } }, overlapsRange] },
    ],
  };
}

/** Le jour d'aujourd'hui au format `2026-09-20`, comme l'attend `dateFilter`. */
export function today(): string {
  return new Date().toISOString().slice(0, 10);
}
