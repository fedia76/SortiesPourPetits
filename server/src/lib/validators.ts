import { z } from 'zod';
import { UNKNOWN_PRICE } from './incomplete';

export const registerSchema = z.object({
  email: z.string().email('Email invalide'),
  password: z.string().min(8, 'Le mot de passe doit faire au moins 8 caractères'),
  displayName: z.string().trim().min(2, 'Le nom doit faire au moins 2 caractères').max(50),
});

export const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

const timeRegex = /^([01]\d|2[0-3]):[0-5]\d$/;

export const venueSchema = z.object({
  name: z.string().trim().min(1, 'Nom du lieu requis').max(120),
  address: z.string().trim().min(1, 'Adresse requise').max(255),
  city: z.string().trim().min(1, 'Ville requise').max(120),
  postalCode: z.string().trim().min(4).max(10),
  lat: z.number().min(-90).max(90),
  lng: z.number().min(-180).max(180),
});

export const categorySchema = z.object({
  name: z.string().trim().min(2, 'Nom trop court').max(50, 'Nom trop long'),
});

const dateOnlyRegex = /^\d{4}-\d{2}-\d{2}$/;
const emptyToNull = (v: unknown) => (v === '' ? null : v);

export const eventInputSchema = z
  .object({
    title: z.string().trim().min(3, 'Titre trop court').max(150),
    description: z.string().trim().min(10, 'Description trop courte').max(10_000),
    sourceUrl: z.preprocess(
      emptyToNull,
      z.string().trim().url('URL invalide').max(500).nullable().optional(),
    ),
    isFree: z.boolean(),
    // La borne basse est négative pour laisser passer UNKNOWN_PRICE, le tarif
    // qu'un import n'a pas su déterminer (voir lib/incomplete.ts). La sortie
    // reste alors inapprouvable tant qu'un modérateur ne l'a pas corrigé.
    price: z.number().min(UNKNOWN_PRICE).max(100_000).nullable().optional(),
    ageMin: z.number().int().min(0).max(17).nullable().optional(),
    ageMax: z.number().int().min(0).max(18).nullable().optional(),
    isPermanent: z.boolean().optional().default(false),
    dateStart: z.preprocess(
      emptyToNull,
      z.string().regex(dateOnlyRegex, 'Date invalide (AAAA-MM-JJ)').nullable().optional(),
    ),
    dateEnd: z.preprocess(
      emptyToNull,
      z.string().regex(dateOnlyRegex, 'Date invalide (AAAA-MM-JJ)').nullable().optional(),
    ),
    openTime: z.preprocess(emptyToNull, z.string().regex(timeRegex, 'Heure invalide (HH:MM)').nullable().optional()),
    closeTime: z.preprocess(emptyToNull, z.string().regex(timeRegex, 'Heure invalide (HH:MM)').nullable().optional()),
    setting: z.enum(['INDOOR', 'OUTDOOR', 'BOTH']).nullable().optional(),
    /**
     * Jours où la sortie a effectivement lieu, dans sa période. Une liste vide
     * — le cas courant — veut dire « tous les jours », ce qui était le seul
     * modèle possible avant. Un spectacle du dimanche, lui, énumère ses dates,
     * sinon il ressortirait un jeudi.
     */
    dates: z
      .array(z.string().regex(dateOnlyRegex, 'Date invalide (AAAA-MM-JJ)'))
      .max(400, 'Trop de dates : décrivez plutôt une période continue')
      .optional()
      .default([]),
    categoryId: z.number().int().positive('Catégorie requise'),
    venue: venueSchema,
  })
  .refine((e) => e.ageMin == null || e.ageMax == null || e.ageMin <= e.ageMax, {
    message: "La tranche d'âge est inversée",
  })
  .refine((e) => e.isPermanent || !!e.dateStart, {
    message: 'Indiquez une date de début ou cochez « événement permanent »',
  })
  .refine((e) => e.isPermanent || !!e.dateEnd, {
    message: 'Indiquez une date de fin ou cochez « événement permanent »',
  })
  .refine((e) => !e.dateStart || !e.dateEnd || e.dateStart <= e.dateEnd, {
    message: 'La date de fin précède la date de début',
  })
  .refine((e) => e.isFree || (e.price !== null && e.price !== undefined), {
    message: 'Indiquez un prix ou cochez « gratuit »',
  })
  .refine((e) => !e.openTime || !e.closeTime || e.openTime < e.closeTime, {
    message: "L'heure d'ouverture doit précéder l'heure de fermeture",
  })
  .refine((e) => !e.isPermanent || e.dates.length === 0, {
    message: 'Une sortie permanente n\'a pas de dates de représentation',
  })
  // Des dates hors de la période décriraient une sortie que ni la recherche ni
  // l'affichage ne sauraient présenter de façon cohérente.
  .refine(
    (e) => e.dates.every((d) => (!e.dateStart || d >= e.dateStart) && (!e.dateEnd || d <= e.dateEnd)),
    { message: 'Une date de représentation sort de la période de la sortie' },
  );

export const searchSchema = z.object({
  q: z.string().trim().max(200).optional(),
  free: z.enum(['true', 'false']).optional(),
  priceMax: z.coerce.number().min(0).optional(),
  age: z.coerce.number().int().min(0).max(18).optional(),
  from: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  to: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  setting: z.enum(['INDOOR', 'OUTDOOR', 'BOTH']).optional(),
  categoryId: z.coerce.number().int().positive().optional(),
  lat: z.coerce.number().min(-90).max(90).optional(),
  lng: z.coerce.number().min(-180).max(180).optional(),
  radiusKm: z.coerce.number().min(0.1).max(300).optional(),
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(1).max(50).default(12),
});

/**
 * D'où viennent les propositions qu'on veut voir.
 *
 * `origin` distingue l'humain de la machine ; `configId` désigne une recherche
 * précise, ce qui revient le plus souvent à un territoire — une recherche
 * « Seine-Maritime » ne propose que de la Seine-Maritime.
 *
 * Partagé par l'affichage de la file et par son vidage, et ce n'est pas un
 * détail : une file filtrée qu'on vide ne doit emporter que ce qui était
 * affiché.
 */
const moderationFilterShape = {
  configId: z.coerce.number().int().positive().optional(),
  origin: z.enum(['scraper', 'visitors']).optional(),
};

export const moderationQueueSchema = z.object(moderationFilterShape);

export type ModerationFilter = z.infer<typeof moderationQueueSchema>;

/**
 * Vidage de la file de modération.
 *
 * `expected` est le nombre de sorties que le modérateur avait sous les yeux :
 * si la file a bougé entre l'affichage et le clic, on refuse plutôt que de
 * supprimer une proposition que personne n'a lue.
 */
export const moderationPurgeSchema = z.object({
  expected: z.coerce.number().int().min(0).optional(),
  ...moderationFilterShape,
});

export const moderateSchema = z.object({
  action: z.enum(['approve', 'reject']),
  reason: z.string().trim().max(1000).optional(),
});

/** Réglages de la recherche de doublons proposée au modérateur. */
export const similarSchema = z.object({
  radiusKm: z.coerce.number().min(0.1).max(100).default(5),
  minScore: z.coerce.number().min(0).max(100).default(30),
  limit: z.coerce.number().int().min(1).max(20).default(5),
});

export const updateRoleSchema = z.object({
  role: z.enum(['USER', 'MODERATOR', 'ADMIN']),
});

export const createApiKeySchema = z.object({
  name: z.string().trim().min(2, 'Libellé trop court').max(100, 'Libellé trop long'),
  userId: z.number().int().positive('Compte requis'),
});

/** Réglages d'une recherche du scraper, tels que la console les envoie. */
/**
 * Les deux modes de recherche.
 *
 * « recherche » est le mode historique — le modèle cherche sur le web. En
 * « site », les adresses sont données : aucune recherche n'est lancée, et
 * `seedUrls` devient obligatoire (voir `scraperSeedUrls`).
 */
export const SCRAPER_MODES = ['recherche', 'site'] as const;
export type ScraperMode = (typeof SCRAPER_MODES)[number];

/**
 * Les URLs de départ, saisies une par ligne dans la console.
 *
 * Vérifiées ici plutôt que dans le scraper : un run qui part sur une adresse
 * fautive coûte une exécution et n'échoue qu'au bout de plusieurs minutes.
 */
export function parseSeedUrls(raw: string): { urls: string[]; invalid: string | null } {
  const urls = raw
    .split(/[\n,]/)
    .map((line) => line.trim())
    .filter(Boolean);
  const invalid = urls.find((url) => {
    try {
      return !['http:', 'https:'].includes(new URL(url).protocol);
    } catch {
      return true;
    }
  });
  return { urls, invalid: invalid ?? null };
}

export const scraperConfigSchema = z.object({
  name: z.string().trim().min(2, 'Nom trop court').max(60, 'Nom trop long'),
  enabled: z.boolean().optional(),
  mode: z.enum(SCRAPER_MODES).optional(),
  seedUrls: z.string().trim().max(4000).optional(),
  theme: z.string().trim().min(10, 'Décrivez ce que la recherche doit trouver').max(2000),
  area: z.string().trim().min(2).max(120).optional(),
  period: z.string().trim().min(2).max(120).optional(),
  horizonDays: z.number().int().min(1).max(365).optional(),
  maxEvents: z.number().int().min(1).max(100).optional(),
  maxSearches: z.number().int().min(1).max(20).optional(),
  maxAgendas: z.number().int().min(1).max(20).optional(),
  maxLinksPerAgenda: z.number().int().min(1).max(50).optional(),
  maxPageChars: z.number().int().min(1000).max(40_000).optional(),
  maxCostUsd: z.number().min(0.05).max(20).optional(),
  keepOutOfScope: z.boolean().optional(),
  defaultCategory: z.string().trim().min(2).max(50).optional(),
  postalPrefixes: z.string().trim().max(200).optional(),
  blockedDomains: z.string().trim().max(2000).optional(),
  searchModel: z.string().trim().min(3).max(60).optional(),
  selectModel: z.string().trim().min(3).max(60).optional(),
  extractionModel: z.string().trim().min(3).max(60).optional(),
  searchPrompt: z.string().max(20_000).nullable().optional(),
  selectPrompt: z.string().max(20_000).nullable().optional(),
  extractionPrompt: z.string().max(20_000).nullable().optional(),
  extractionMultiPrompt: z.string().max(20_000).nullable().optional(),
});

export const scraperConfigUpdateSchema = scraperConfigSchema.partial();

/**
 * Ce qui lie le mode au reste de la configuration, vérifié sur la ligne
 * complète — création, ou modification fusionnée avec l'existant. Une
 * modification partielle ne porte pas forcément les deux champs : changer le
 * mode seul ne doit pas échapper au contrôle des URLs, ni l'inverse.
 *
 * Retourne le message d'erreur, ou `null` si la configuration tient debout.
 */
export function checkScraperMode(config: { mode: string; seedUrls: string }): string | null {
  const { urls, invalid } = parseSeedUrls(config.seedUrls ?? '');
  if (invalid) return `URL de départ invalide : « ${invalid} »`;
  if (config.mode === 'site' && urls.length === 0) {
    return 'Le mode « site » réclame au moins une adresse de départ';
  }
  return null;
}

/** Mise en file d'une exécution depuis la console. */
export const scraperRunSchema = z.object({
  submit: z.boolean().optional().default(false),
});

const scraperUrl = z.string().trim().url('URL invalide').max(500);

/** Compte rendu d'une page traitée, envoyé par le worker au fil de l'eau. */
export const scraperItemsSchema = z.object({
  items: z
    .array(
      z.object({
        url: scraperUrl,
        /**
         * Clé de mémorisation : l'URL débarrassée de ce qui ne change pas la
         * page (schéma, www, paramètres de suivi, barre finale). Le scraper
         * l'envoie pour que deux liens vers la même page n'y comptent qu'une
         * fois, alors que `url` reste le lien exact, cliquable dans la console.
         */
        key: scraperUrl.optional(),
        title: z.string().trim().max(190).optional(),
        decision: z.string().trim().min(2).max(40),
        reason: z.string().trim().max(1000).optional(),
        eventId: z.number().int().positive().nullable().optional(),
        /** Faux pour une décision provisoire, qui ne doit pas être mémorisée. */
        remember: z.boolean().optional().default(true),
      }),
    )
    .min(1)
    .max(200),
});

/** Clôture d'une exécution : compteurs finaux. */
export const scraperFinishSchema = z.object({
  status: z.enum(['DONE', 'FAILED']),
  error: z.string().trim().max(2000).optional(),
  candidates: z.number().int().min(0).optional(),
  pages: z.number().int().min(0).optional(),
  retained: z.number().int().min(0).optional(),
  submitted: z.number().int().min(0).optional(),
  duplicates: z.number().int().min(0).optional(),
  skipped: z.number().int().min(0).optional(),
  errors: z.number().int().min(0).optional(),
  inputTokens: z.number().int().min(0).optional(),
  outputTokens: z.number().int().min(0).optional(),
  webSearches: z.number().int().min(0).optional(),
  costUsd: z.number().min(0).optional(),
});

/**
 * Périmètre demandé au tableau de bord du scraping.
 *
 * `configId` absent veut dire « toutes les recherches confondues » : c'est la
 * vue qui dit d'où vient réellement le catalogue, toutes configurations
 * mélangées.
 */
export const scraperStatsSchema = z.object({
  configId: z.coerce.number().int().positive().optional(),
  /** Fenêtre d'observation, en jours. Absent : tout l'historique. */
  days: z.coerce.number().int().min(1).max(3650).optional(),
});

/** Consultation de la mémoire des pages, depuis la console. */
export const scraperMemorySchema = z.object({
  q: z.string().trim().max(200).optional(),
  decision: z.string().trim().min(2).max(40).optional(),
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(1).max(200).default(50),
});

/**
 * Purge de la mémoire.
 *
 * `decision` restreint la purge à un seul verdict — oublier les erreurs de
 * lecture sans oublier ce qui a déjà été proposé au site. Sans elle, tout
 * part, et le prochain run relira (donc repaiera) chaque page connue.
 */
export const scraperMemoryPurgeSchema = z.object({
  decision: z.string().trim().min(2).max(40).optional(),
});

/** Interrogation de la mémoire des pages déjà analysées. */
export const scraperSeenSchema = z.object({
  urls: z.array(scraperUrl).min(1).max(500),
});
