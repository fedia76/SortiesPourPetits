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

/**
 * Une zone géographique (`model Area`).
 *
 * Le slug est refusé s'il ne tient qu'en chiffres : il partage son espace
 * d'adresses avec les fiches — `/sorties/le-havre` et `/sorties/204` — et une
 * zone nommée « 75 » masquerait la sortie numéro 75.
 */
export const areaSchema = z.object({
  slug: z
    .string()
    .trim()
    .min(2, 'Identifiant trop court')
    .max(60, 'Identifiant trop long')
    .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, 'Minuscules, chiffres et tirets uniquement')
    .refine((v) => !/^\d+$/.test(v), 'Un identifiant tout en chiffres se confondrait avec une sortie'),
  name: z.string().trim().min(2, 'Nom trop court').max(80, 'Nom trop long'),
  postalPrefixes: z
    .string()
    .trim()
    .min(1, 'Indiquez au moins un préfixe de code postal')
    .max(200)
    .regex(/^\d{1,5}(?:\s*,\s*\d{1,5})*$/, 'Préfixes attendus : des nombres séparés par des virgules'),
  intro: z.string().trim().min(1, 'Un texte de présentation est attendu').max(2000),
  position: z.coerce.number().int().min(0).max(999).default(0),
});

const dateOnlyRegex = /^\d{4}-\d{2}-\d{2}$/;
const emptyToNull = (v: unknown) => (v === '' ? null : v);

export const eventInputSchema = z
  .object({
    title: z.string().trim().min(3, 'Titre trop court').max(150),
    description: z.string().trim().min(10, 'Description trop courte').max(10_000),
    /**
     * Le meilleur lien connu pour cette sortie : la page de l'organisateur
     * quand le scraper a su la trouver, la page où elle a été repérée sinon.
     * C'est celui que la fiche affiche — son rôle n'a pas changé depuis que le
     * scraper sait remonter à la source, et c'est ce qui a évité d'apprendre
     * deux champs à tous ses lecteurs.
     */
    sourceUrl: z.preprocess(
      emptyToNull,
      z.string().trim().url('URL invalide').max(500).nullable().optional(),
    ),
    /**
     * La page où la sortie a été repérée, quand ce n'est pas celle qu'on
     * montre — un agrégateur qui republiait l'information d'un musée. C'est de
     * la provenance : elle sert au modérateur et au débogage, jamais au
     * visiteur. Absente d'un formulaire, renseignée par le scraper.
     */
    foundOnUrl: z.preprocess(
      emptyToNull,
      z.string().trim().url('URL invalide').max(500).nullable().optional(),
    ),
    /**
     * Ce qui a désigné `sourceUrl` — un des signaux de l'étage attribution du
     * scraper, ou « manuel ». Le serveur ne vérifie pas la valeur contre une
     * liste : ce champ est un renseignement affiché au modérateur, pas une
     * décision, et figer les noms ici obligerait à redéployer le site pour
     * ajouter un signal au scraper.
     */
    sourceUrlSignal: z.preprocess(
      emptyToNull,
      z.string().trim().max(40).nullable().optional(),
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
  /** Zone géographique, par son identifiant d'adresse : « le-havre ». */
  area: z.string().trim().max(60).optional(),
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
  // Le motif comptable, à côté du texte libre — voir `lib/rejectionCodes.ts`.
  // Facultatif, et il doit le rester : un refus ne peut pas échouer parce
  // qu'aucune case ne convenait, et une console plus ancienne continue de
  // fonctionner sans lui.
  code: z
    .enum([
      'HORS_SUJET',
      'PAS_POUR_ENFANTS',
      'DATE_FAUSSE',
      'LIEU_FAUX',
      'TARIF_FAUX',
      'DESCRIPTION_INUTILISABLE',
      'MAUVAIS_LIEN',
      'DOUBLON',
      'DEJA_PASSEE',
      'AUTRE',
    ])
    .optional(),
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
 * Qui lance les recherches web.
 *
 * « anthropic » passe par l'outil serveur du modèle : les résultats entrent
 * dans son contexte, et ces jetons se facturent. « serper » interroge Google
 * et rend du JSON — un dixième du prix, pas un jeton d'entrée, et un index
 * plus profond sur le local francophone. Le modèle reste derrière dans les
 * deux cas : un moteur trouve des pages, il ne les juge pas.
 */
export const SCRAPER_PROVIDERS = ['anthropic', 'serper'] as const;
export type ScraperProvider = (typeof SCRAPER_PROVIDERS)[number];

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
  maxAgendas: z.number().int().min(1).max(60).optional(),
  // Deux pages suivantes suffisent : chacune coûte un téléchargement, une
  // seconde d'attente polie et des liens de plus au tri, qui est facturé.
  maxNextPages: z.number().int().min(0).max(10).optional(),
  maxLinksPerAgenda: z.number().int().min(1).max(50).optional(),
  maxPageChars: z.number().int().min(1000).max(40_000).optional(),
  maxCostUsd: z.number().min(0.05).max(20).optional(),
  keepOutOfScope: z.boolean().optional(),
  defaultCategory: z.string().trim().min(2).max(50).optional(),
  postalPrefixes: z.string().trim().max(200).optional(),
  // La liste des agrégateurs est commune au site (voir `aggregatorSchema`) :
  // une recherche ne la porte plus, elle décide seulement de les lire ou non.
  blockAggregators: z.boolean().optional(),
  // Le seul appel payant de l'attribution, et donc le seul qu'on puisse
  // couper. Les signaux gratuits, eux, tournent toujours.
  sourceSearch: z.boolean().optional(),
  provider: z.enum(SCRAPER_PROVIDERS).optional(),
  // Seul modèle qu'on puisse vider : sans lui, la reconnaissance s'en tient
  // aux signaux gratuits et laisse la page partir en agenda.
  classifyModel: z.string().trim().max(60).optional(),
  searchModel: z.string().trim().min(3).max(60).optional(),
  selectModel: z.string().trim().min(3).max(60).optional(),
  extractionModel: z.string().trim().min(3).max(60).optional(),
  queries: z.string().max(4000).nullable().optional(),
  queriesPrompt: z.string().max(20_000).nullable().optional(),
  classifyPrompt: z.string().max(20_000).nullable().optional(),
  searchPrompt: z.string().max(20_000).nullable().optional(),
  selectPrompt: z.string().max(20_000).nullable().optional(),
  extractionPrompt: z.string().max(20_000).nullable().optional(),
  extractionMultiPrompt: z.string().max(20_000).nullable().optional(),
});

export const scraperConfigUpdateSchema = scraperConfigSchema.partial();

/**
 * Un agrégateur de la liste commune.
 *
 * Le domaine est normalisé ici et nulle part ailleurs : on colle volontiers
 * une URL entière depuis la barre d'adresse, et « https://www.kidiklik.fr/
 * paris/ » doit devenir « kidiklik.fr » sans que personne ait à le savoir.
 * Sans cette normalisation, deux lignes décriraient le même site et l'une des
 * deux ne servirait jamais — le scraper compare des hôtes, pas des adresses.
 */
export const aggregatorSchema = z.object({
  domain: z
    .string()
    .trim()
    .min(3, 'Domaine trop court')
    .max(190)
    .transform((value) =>
      value
        .toLowerCase()
        .replace(/^[a-z]+:\/\//, '')
        .replace(/^www\./, '')
        .replace(/[/?#].*$/, '')
        .replace(/\.$/, ''),
    )
    .refine((value) => /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(value), 'Domaine invalide'),
  label: z.string().trim().max(80).optional(),
  enabled: z.boolean().optional(),
  note: z.string().trim().max(1000).optional(),
});

export const aggregatorUpdateSchema = aggregatorSchema.partial();

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
/**
 * Un paquet du journal détaillé, envoyé par le worker au fil du run.
 *
 * Volontairement permissif sur `kind` et `stage` : le scraper est la source de
 * vérité de ses propres étiquettes, et un nouveau type d'événement ne doit pas
 * faire échouer un run parce que le serveur ne le connaît pas encore. La
 * console affiche ce qu'elle ne sait pas nommer plutôt que de le perdre.
 */
export const scraperLogsSchema = z.object({
  entries: z
    .array(
      z.object({
        seq: z.number().int().min(0),
        at: z.string().trim().max(40).optional(),
        stage: z.string().trim().max(24).nullable().optional(),
        kind: z.string().trim().min(1).max(40),
        level: z.enum(['info', 'warn', 'error']).optional().default('info'),
        url: z.string().trim().max(500).optional(),
        message: z.string().trim().max(4000).optional(),
        /** Le reste des champs de l'événement. Sérialisé tel quel. */
        data: z.record(z.string(), z.unknown()).optional(),
      }),
    )
    .min(1)
    .max(200),
});

/** Lecture du journal : filtres de la page de débogage. */
export const scraperLogQuerySchema = z.object({
  stage: z.string().trim().max(24).optional(),
  kind: z.string().trim().max(40).optional(),
  level: z.enum(['info', 'warn', 'error']).optional(),
  url: z.string().trim().max(500).optional(),
  /** Filiation : ne garder que ce qui descend de cet agenda, ou de cette page. */
  agenda: z.string().trim().max(500).optional(),
  page: z.string().trim().max(500).optional(),
  q: z.string().trim().max(120).optional(),
  /** Curseur : dernier `seq` déjà reçu. La console charge la suite. */
  after: z.coerce.number().int().min(0).optional(),
  limit: z.coerce.number().int().min(1).max(500).optional().default(200),
});

export const scraperFinishSchema = z.object({
  status: z.enum(['DONE', 'FAILED']),
  error: z.string().trim().max(2000).optional(),
  candidates: z.number().int().min(0).optional(),
  pages: z.number().int().min(0).optional(),
  // Celles des pages qui n'étaient pas la première d'un agenda.
  nextPages: z.number().int().min(0).optional(),
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
 * Ce que le worker rapporte d'une **recherche de source** : l'étage 7 rejoué
 * seul sur une sortie déjà en base.
 *
 * `checked` est le seul champ qui décide. Une URL non vérifiée — proposée par
 * un signal mais jamais ouverte, ou ouverte et parlant d'autre chose — n'est
 * pas une source : elle est journalisée et jetée, exactement comme au fil
 * d'une recherche. Une source fausse est pire qu'une source absente.
 */
export const scraperSourceSchema = z.object({
  url: scraperUrl.optional(),
  /** `json_ld`, `venue_domain`, `page_link`, `search`. Vide si rien trouvé. */
  signal: z.string().trim().max(40).optional(),
  /** Ce qui a désigné puis vérifié la page, en une phrase, pour le journal. */
  detail: z.string().trim().max(500).optional(),
  /**
   * La page d'où l'on est parti — l'agrégateur. Elle descend dans
   * `foundOnUrl` : c'est le worker qui l'a réellement lue, donc c'est lui qui
   * la dit, plutôt que le site qui la recalculerait sur une fiche peut-être
   * modifiée entre-temps.
   */
  foundOn: scraperUrl.optional(),
  checked: z.boolean().optional().default(false),
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

// ───────────────────────────────────────────────────────── banc d'évaluation

/**
 * Combien de pages d'un agenda le banc dépouille, la première comprise.
 *
 * Le plafond est bas et c'est voulu : chaque page est un téléchargement réel
 * chez quelqu'un, et un humain devra ensuite relire ce qu'elle a donné. Une
 * vérité de référence se construit sur quelques pages qu'on regarde vraiment,
 * pas sur cinquante qu'on survole.
 */
export const EVAL_MAX_PAGES = 10;

/** Un agenda ajouté au banc depuis la console. */
export const evalAgendaSchema = z.object({
  url: scraperUrl,
  label: z.string().trim().max(150).optional().default(''),
  pages: z.number().int().min(1).max(EVAL_MAX_PAGES).optional().default(1),
  note: z.string().trim().max(2000).optional().default(''),
});

/** Ce qu'on peut changer d'une entrée du corpus sans la ressaisir. */
export const evalAgendaUpdateSchema = z
  .object({
    label: z.string().trim().max(150),
    pages: z.number().int().min(1).max(EVAL_MAX_PAGES),
    note: z.string().trim().max(2000),
  })
  .partial();

/**
 * Les quatre verdicts, et pourquoi quatre.
 *
 * Trois ne suffisent pas à décrire ce qu'un agenda contient. `SOUS_AGENDA` est
 * le cas que personne ne comptait : « voir aussi les sorties en château », une
 * page à facettes qui porte d'autres sorties sans être la page suivante. Le
 * dépouillement la rend, la sélection l'écarte parce qu'on lui dit d'écarter
 * les catégories, et ce qu'elle porte n'est jamais atteint.
 */
export const EVAL_VERDICTS = ['SORTIE', 'PAGINATION', 'SOUS_AGENDA', 'AUTRE'] as const;

/**
 * Les indices que le contexte d'un lien montre, et qui font dériver la
 * pertinence au lieu de l'étiqueter.
 *
 * Trois états chacun : absent du corps (on ne touche pas), `null` (personne
 * n'a regardé), une valeur — vide comprise, qui veut dire « l'agenda n'affiche
 * rien » et qui est une étiquette de plein droit. Un indice vide ne peut
 * jamais écarter une sortie : il la rend indécidable.
 */
/**
 * L'étiquette qu'un humain pose sur un lien : ce que le lien **est**, et vers
 * quelle sortie il mène.
 *
 * Il ne décrit plus la sortie. La date, le lieu et le public ont brièvement
 * vécu ici, en double de ce que le corpus des sorties disait déjà et sans que
 * rien ne joigne les deux ; ils sont retournés sur la sortie, qui les dit une
 * fois pour les étages 4, 5 et 6.
 */
export const evalVerdictSchema = z
  .object({
    verdict: z.enum(EVAL_VERDICTS),
    note: z.string().trim().max(500),
    /** La sortie vers laquelle ce lien mène. `null` : la détacher. */
    sortieId: z.union([z.number().int().positive(), z.null()]),
  })
  .partial()
  .refine((v) => Object.keys(v).length > 0, { message: 'Rien à changer' });

/**
 * Un lien étiqueté à la main, tel que la console l'envoie.
 *
 * `url` suffit : le texte est un confort d'affichage. Un lien `MANUAL` est le
 * seul moyen de décrire ce qu'aucun `links_of` ne trouvera jamais — une carte
 * rendue en JavaScript, par exemple — et donc de mesurer ce manque.
 */
export const evalLinkSchema = z.object({
  url: scraperUrl,
  text: z.string().trim().max(200).optional().default(''),
  verdict: z.enum(EVAL_VERDICTS).optional().default('SORTIE'),
  note: z.string().trim().max(500).optional().default(''),
  source: z.enum(['PAGE', 'MANUAL']).optional().default('MANUAL'),
});

/**
 * L'étiquette de pagination d'une page : l'adresse de la vraie suite.
 *
 * Trois états, et il en faut trois. `null` : personne n'a regardé. `""` : il
 * n'y a pas de suite, et c'est une étiquette de plein droit. Une URL : la
 * voici. Le verdict d'autrefois (CORRECT / MANQUEE / FAUSSE) n'est plus
 * stocké : il se déduit de la comparaison avec ce qu'un run a trouvé, et vaut
 * donc pour tous les runs au lieu d'un seul.
 */
export const evalNextSchema = z.object({
  expected: z.union([scraperUrl, z.literal(''), z.null()]),
});

/**
 * Étiqueter d'un coup les liens qu'un run a écartés sous un même motif.
 *
 * Soixante-seize écartés se lisent mal un par un, et la plupart sont du bruit
 * évident : quinze liens vers Facebook, douze vers la racine du site. Les
 * expédier d'un clic laisse le temps là où il compte — sous « texte trop
 * court », le motif où se cachent les sorties perdues.
 *
 * L'outil coupe dans les deux sens, et c'est assumé : étiqueter en masse un
 * motif qu'on n'a pas lu fabrique un rappel flatteur. D'où `reason`, qui
 * oblige à viser un groupe plutôt que « tout le reste », et `runId`, qui dit
 * de quel relevé viennent les liens qu'on étiquette.
 */
export const evalBulkVerdictSchema = z.object({
  runId: z.number().int().positive(),
  verdict: z.enum(EVAL_VERDICTS),
  /** Le motif visé. Absent : tous les écartés du relevé. */
  reason: z.string().trim().max(60).optional(),
});

/**
 * Plafond du HTML archivé d'une page, en base64 de gzip.
 *
 * Un million de caractères de base64 font environ 750 ko compressés, soit
 * plusieurs mégaoctets de HTML — bien au-delà de tout agenda réel. Une page
 * plus grosse que ça est pathologique ; le worker la rapporte alors **sans**
 * son HTML plutôt que de faire échouer toute la capture.
 */
export const EVAL_MAX_HTML_B64 = 1_000_000;

/**
 * Ce que le worker rend d'une **capture** : le HTML, et rien d'autre.
 *
 * Ni liens ni page suivante : ceux-là sortent de `links_of` et de
 * `next_page()`, donc d'une brique, donc d'un run. Les faire entrer ici
 * remettrait dans le corpus ce que la séparation vient d'en sortir.
 */
export const evalCaptureSchema = z.object({
  pages: z
    .array(
      z.object({
        pageNo: z.number().int().min(1).max(EVAL_MAX_PAGES),
        url: scraperUrl,
        chars: z.number().int().min(0).optional().default(0),
        html: z.string().max(EVAL_MAX_HTML_B64).optional(),
      }),
    )
    .min(1)
    .max(EVAL_MAX_PAGES),
});

/** Clôture en échec : le worker n'a rien pu capturer. */
export const evalFailSchema = z.object({
  error: z.string().trim().min(1).max(2000),
});

// ─────────────────────────────────────────── corpus de lecture (étage 5)

/** Une page ajoutée au corpus de lecture. Une fiche, pas un agenda. */
export const EVAL_NATURES = ['AGENDA', 'SORTIE', 'PROGRAMME', 'AUTRE'] as const;

/**
 * Une page mise au corpus de l'étage 2, avec ce qu'elle **est**.
 *
 * La nature est obligatoire dès la création : cette table ne contient que des
 * étiquettes, et une ligne sans nature dirait « quelqu'un a regardé sans rien
 * conclure », ce qui n'a pas de sens. Pour dire « je ne sais pas », on
 * n'ajoute pas la page.
 */
export const evalNatureSchema = z.object({
  url: scraperUrl,
  nature: z.enum(EVAL_NATURES),
  label: z.string().trim().max(150).optional().default(''),
  note: z.string().trim().max(2000).optional().default(''),
});

/** Corriger ce qu'on avait dit d'une page. */
export const evalNaturePatchSchema = z
  .object({
    nature: z.enum(EVAL_NATURES),
    label: z.string().trim().max(150),
    note: z.string().trim().max(2000),
  })
  .partial()
  .refine((v) => Object.keys(v).length > 0, { message: 'Rien à changer' });

export const evalSortieSchema = z.object({
  url: scraperUrl,
  label: z.string().trim().max(150).optional().default(''),
  note: z.string().trim().max(2000).optional().default(''),
});

/**
 * Les étiquettes d'une page : ce qu'elle **contient**, et non ce que la brique
 * en a tiré.
 *
 * Chacune a trois états. `null` : personne n'a regardé. Une valeur vide (`""`
 * pour l'image, `[]` pour les dates) : la page n'en porte pas, et c'est une
 * étiquette. Une valeur : la voici. Sans le second état, « pas d'image sur la
 * page » et « pas encore étiqueté » seraient le même silence, et l'on ne
 * pourrait plus reconnaître une image inventée.
 */
export const evalSortieLabelSchema = z
  .object({
    // ── ce que la page porte, pour l'étage 5
    /** L'illustration que la page porte vraiment. */
    image: z.union([scraperUrl, z.literal(''), z.null()]),
    /** Les dates déclarées dans le balisage `schema.org/Event`. */
    declaredDates: z.union([z.array(z.string().trim().max(40)).max(400), z.null()]),
    /**
     * Les fragments que le texte extrait doit contenir — le titre, le tarif,
     * l'adresse. On ne demande pas de retaper le texte attendu : ce serait
     * invivable et personne ne le ferait deux fois. On demande ce qui ne doit
     * pas manquer, ce qui se coche en quelques secondes, et ça suffit à
     * distinguer un texte amputé d'un texte entier — la question de cet étage.
     */
    markers: z.union([z.array(z.string().trim().min(2).max(200)).max(40), z.null()]),

    // ── ce que la sortie est, pour l'étage 4
    /** Premier et dernier jour. `dateEnd` nul sur une date unique. */
    dateStart: z.union([z.string().regex(/^\d{4}-\d{2}-\d{2}$/), z.literal(''), z.null()]),
    dateEnd: z.union([z.string().regex(/^\d{4}-\d{2}-\d{2}$/), z.literal(''), z.null()]),
    /** Cinq chiffres, ou rien. Une ville en toutes lettres ne se compare pas. */
    venuePostalCode: z.union([z.string().regex(/^\d{5}$/), z.literal(''), z.null()]),
    ageMin: z.union([z.number().int().min(0).max(120), z.null()]),
    ageMax: z.union([z.number().int().min(0).max(120), z.null()]),

    /**
     * À qui la sortie s'adresse, quand la page l'annonce en mots. Seule
     * affirmation du banc qu'aucune brique ne rend : elle vit en colonne, pas
     * dans l'étiquette qui décalque la fiche.
     */
    audience: z.union([z.enum(['ENFANTS', 'ADULTES', 'INDETERMINE']), z.null()]),

    note: z.string().trim().max(2000),
  })
  .partial()
  .refine((v) => !v.dateStart || !v.dateEnd || v.dateEnd >= v.dateStart, {
    message: 'La sortie ne peut pas finir avant d’avoir commencé',
    path: ['dateEnd'],
  })
  .refine((v) => v.ageMin == null || v.ageMax == null || v.ageMax >= v.ageMin, {
    message: 'L’âge maximum ne peut pas être inférieur au minimum',
    path: ['ageMax'],
  });

/** Les champs de l'étiquette qui vivent dans le JSON, et non en colonne. */
export const CHAMPS_ETIQUETTE = [
  'image',
  'declaredDates',
  'markers',
  'dateStart',
  'dateEnd',
  'venuePostalCode',
  'ageMin',
  'ageMax',
] as const;

/**
 * Ce que la page annonce, champ par champ : le corpus de l'étage 6.
 *
 * Une clé absente veut dire « personne n'a regardé ce champ » ; une clé
 * présente et vide veut dire « la page n'en dit rien », ce qui est une
 * étiquette et permet de reconnaître une valeur inventée.
 */
export const evalEtiquetteSchema = z.object({
  expected: z.record(z.string().max(40), z.unknown()),
  note: z.string().trim().max(2000).optional().default(''),
});

// ──────────────────────────────────────────────────────────── les runs

export const EVAL_STAGES = ['HARVEST', 'SELECT', 'READ', 'EXTRACT'] as const;

/**
 * Le lancement d'un run.
 *
 * `label` n'est pas du décor : c'est ce qui rend un point de la courbe lisible
 * six mois plus tard — « après le correctif d'encodage » dit quelque chose,
 * « run #47 » non.
 */
export const evalRunSchema = z.object({
  stage: z.enum(EVAL_STAGES),
  label: z.string().trim().max(150).optional().default(''),
});

export const evalRunListSchema = z.object({
  stage: z.enum(EVAL_STAGES).optional(),
  limit: z.coerce.number().int().min(1).max(100).optional().default(30),
});

/** Ce que le worker déclare en prenant un run : de quoi il est le run. */
export const evalRunClaimSchema = z.object({
  codeRef: z.string().trim().max(60).optional().default(''),
  model: z.string().trim().max(120).optional().default(''),
  promptHash: z.string().trim().max(64).optional().default(''),
  settings: z
    .object({
      /** La fenêtre de la recherche jouée, en `YYYY-MM-DD`. */
      dateFrom: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
      dateTo: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
      /** Les départements visés. */
      postalPrefixes: z.array(z.string().max(5)).max(40).optional(),
      /** Le plafond du tri : ce qui rend une page saturée indécidable. */
      maxLinks: z.number().int().min(1).max(200).optional(),
      theme: z.string().max(200).optional(),
    })
    .passthrough()
    .optional()
    .default({}),
});

/** Ce qu'un run de l'étage 3 ou 4 rend sur une page du corpus. */
export const evalLinkResultSchema = z.object({
  pageId: z.number().int().positive(),
  /**
   * Ce que `next_page()` a trouvé. Comparé à `nextExpected` du corpus, c'est
   * la mesure de la pagination — et elle vaut pour tous les runs, là où le
   * verdict figé ne valait que pour celui qui l'avait produit.
   */
  nextUrl: z.union([scraperUrl, z.literal('')]).optional().default(''),
  error: z.string().trim().max(1000).optional(),
  links: z
    .array(
      z.object({
        url: scraperUrl,
        text: z.string().trim().max(200).optional().default(''),
        context: z.string().trim().max(1000).optional().default(''),
        harvested: z.boolean().optional().default(false),
        reason: z.string().trim().max(60).optional().default(''),
        /** Étage 4 seulement. Absent : ce lien n'a pas été soumis au tri. */
        selected: z.boolean().optional(),
        selectReason: z.string().trim().max(500).optional().default(''),
      }),
    )
    .max(600)
    .optional()
    .default([]),
});

/** Ce qu'un run de l'étage 5 rend sur une page du corpus. */
export const evalReadResultSchema = z.object({
  sortieId: z.number().int().positive(),
  readUrl: z.union([scraperUrl, z.literal('')]).optional().default(''),
  swapped: z.boolean().optional().default(false),
  text: z.string().max(200_000).optional().default(''),
  textChars: z.number().int().min(0).optional().default(0),
  dates: z.array(z.string().trim().max(40)).max(400).optional().default([]),
  imageUrl: z.union([scraperUrl, z.literal('')]).optional().default(''),
  heading: z.string().trim().max(200).optional().default(''),
  h1InText: z.boolean().optional().default(false),
  truncated: z.boolean().optional().default(false),
  tooShort: z.boolean().optional().default(false),
  imageLooksLogo: z.boolean().optional().default(false),
  error: z.string().trim().max(1000).optional(),
});

/** Ce qu'un run de l'étage 6 rend sur le texte d'une page du corpus. */
export const evalExtractResultSchema = z.object({
  sortieId: z.number().int().positive(),
  fiche: z.record(z.string(), z.unknown()).optional().default({}),
  aspects: z
    .array(
      z.object({
        key: z.string().max(40),
        label: z.string().max(120).optional().default(''),
        value: z.string().max(2000).optional().default(''),
        filled: z.boolean().optional().default(false),
        instrument: z.string().max(60).optional().default(''),
        flags: z.array(z.string().max(40)).max(20).optional().default([]),
      }),
    )
    .max(60)
    .optional()
    .default([]),
  inputTokens: z.number().int().min(0).optional().default(0),
  outputTokens: z.number().int().min(0).optional().default(0),
  costUsd: z.number().min(0).optional().default(0),
  error: z.string().trim().max(1000).optional(),
});

/** Clôture d'un run : son sort, et ce qu'il a coûté. */
export const evalRunFinishSchema = z.object({
  status: z.enum(['DONE', 'FAILED']),
  error: z.string().trim().max(2000).optional(),
  items: z.number().int().min(0).optional().default(0),
  inputTokens: z.number().int().min(0).optional().default(0),
  outputTokens: z.number().int().min(0).optional().default(0),
  costUsd: z.number().min(0).optional().default(0),
});

/**
 * Peupler le corpus avec ce que le pipeline a déjà fait.
 *
 * Quatre paniers, et l'équilibre entre eux est la question de ce corpus : ne
 * prendre que les réussites mesurerait la brique sur ses propres succès.
 */
export const evalSeedSchema = z.object({
  bucket: z.enum(['approuvees', 'abandonnees', 'illisibles', 'liens', 'fiches']),
  limit: z.coerce.number().int().min(1).max(200).optional().default(25),
});
