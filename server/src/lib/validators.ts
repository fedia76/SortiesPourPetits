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

/** Ce qu'on peut changer d'un agenda déjà au banc, sans le ressaisir. */
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

/** La correction d'un humain sur un lien relevé. */
export const evalVerdictSchema = z.object({
  verdict: z.enum(EVAL_VERDICTS),
  note: z.string().trim().max(500).optional(),
});

/**
 * Le verdict de pagination d'une page, tranché par un humain.
 *
 * Il ne se déduit pas des étiquettes des liens : `next_page()` lit aussi le
 * `<link rel="next">` du `<head>`, qui n'est pas un `<a href>` et n'apparaît
 * donc dans aucune ligne. L'URL qu'il en tire était alors invérifiable.
 *
 * `expected` documente la vraie page suivante quand on la connaît — c'est ce
 * qu'il faut pour réparer, savoir que la brique s'est trompée ne disant pas ce
 * qu'elle aurait dû trouver.
 */
export const evalNextSchema = z.object({
  verdict: z.enum(['CORRECT', 'MANQUEE', 'FAUSSE']),
  expected: z.union([scraperUrl, z.literal('')]).optional().default(''),
});

/**
 * Trancher d'un coup tous les liens écartés d'une page, ou d'un seul motif.
 *
 * Soixante-seize écartés se lisent mal un par un, et la plupart sont du bruit
 * évident : quinze liens vers Facebook, douze vers la racine du site. Les
 * expédier d'un clic laisse le temps là où il compte — sous « texte trop
 * court », le motif où se cachent les sorties perdues.
 *
 * L'outil coupe dans les deux sens, et c'est assumé : trancher en masse un
 * motif qu'on n'a pas lu fabrique un rappel flatteur. D'où le champ `reason`,
 * qui oblige à viser un groupe plutôt que « tout le reste ».
 */
export const evalBulkVerdictSchema = z.object({
  verdict: z.enum(EVAL_VERDICTS),
  /** Le motif visé. Absent : tous les écartés de la page. */
  reason: z.string().trim().max(60).optional(),
});

/**
 * Un lien ajouté à la main : ce que le HTML ne portait pas.
 *
 * Le relevé prend déjà tous les `<a href>` de la page ; cette route ne sert
 * plus qu'au cas résiduel mais réel — une carte rendue en JavaScript, qui
 * n'existe dans aucune ancre. Pas de `context` : l'humain donne une URL, pas
 * le texte qui l'entoure, et en fabriquer un ferait croire à l'étage 4 qu'il a
 * reçu quelque chose que le dépouillement ne lui aurait jamais donné.
 */
export const evalLinkSchema = z.object({
  url: scraperUrl,
  text: z.string().trim().max(200).optional().default(''),
  verdict: z.enum(EVAL_VERDICTS).optional().default('SORTIE'),
  note: z.string().trim().max(500).optional().default(''),
});

/**
 * Plafond du HTML archivé d'une page, en base64 de gzip.
 *
 * Un million de caractères de base64 font environ 750 ko compressés, soit
 * plusieurs mégaoctets de HTML — bien au-delà de tout agenda réel. Une page
 * plus grosse que ça est pathologique ; le worker la rapporte alors **sans**
 * son HTML plutôt que de faire échouer tout le compte rendu. La mesure tient,
 * seul le rejeu hors ligne s'en trouve privé pour cette page-là.
 */
export const EVAL_MAX_HTML_B64 = 1_000_000;

/**
 * Ce que le worker rend d'un agenda : une entrée par page réellement
 * demandée, dans l'ordre de la pagination.
 *
 * Une page en erreur est une réponse — elle a été demandée, pas obtenue — et
 * porte donc zéro lien plutôt que de manquer du compte rendu.
 */
export const evalHarvestSchema = z.object({
  pages: z
    .array(
      z.object({
        pageNo: z.number().int().min(1).max(EVAL_MAX_PAGES),
        url: scraperUrl,
        chars: z.number().int().min(0).optional().default(0),
        error: z.string().trim().max(1000).optional(),
        /**
         * Ce que `next_page()` a trouvé sur cette page — donc ce que l'étage 3
         * saurait suivre. Vide quand la page ne déclare pas de suite, ce qui
         * est une réponse : comparé aux liens étiquetés « pagination », c'est
         * ce qui dit qu'un site se pagine d'une façon que le pipeline ignore.
         */
        nextUrl: z.union([scraperUrl, z.literal('')]).optional().default(''),
        /**
         * Le HTML servi, gzippé puis encodé en base64 par le worker.
         *
         * Il voyage compressé et sera écrit tel quel : c'est ce qui fait du
         * banc un corpus gelé. Absent pour une page injoignable, ou trop
         * lourde pour être archivée.
         */
        html: z.string().max(EVAL_MAX_HTML_B64).optional(),
        /**
         * **Tous** les liens de la page, pas seulement la moisson : c'est ce
         * qui permet de mesurer les deux erreurs. Le plafond est large parce
         * qu'une page à méga-menu aligne trois cents liens avant d'arriver à
         * son listing.
         */
        links: z
          .array(
            z.object({
              url: scraperUrl,
              text: z.string().trim().max(200).optional().default(''),
              context: z.string().trim().max(1000).optional().default(''),
              /** Le verdict du vrai `links_of` : la précoche. */
              harvested: z.boolean().optional().default(false),
              /** Pourquoi il a été écarté. Un libellé, pas une décision. */
              reason: z.string().trim().max(60).optional().default(''),
            }),
          )
          .max(600)
          .optional()
          .default([]),
      }),
    )
    .min(1)
    .max(EVAL_MAX_PAGES),
});

/** Clôture en échec : le worker n'a rien pu tirer de cet agenda. */
export const evalFailSchema = z.object({
  error: z.string().trim().min(1).max(2000),
});

// ─────────────────────────────────────────── banc de lecture (étage 5)

/** Une page ajoutée au banc de lecture. Une fiche, pas un agenda. */
export const evalReadingSchema = z.object({
  url: scraperUrl,
  label: z.string().trim().max(150).optional().default(''),
  note: z.string().trim().max(2000).optional().default(''),
});

export const EVAL_TEXT_VERDICTS = ['CORRECT', 'AMPUTE', 'TRONQUE', 'HORS_SUJET'] as const;
export const EVAL_IMAGE_VERDICTS = ['CORRECTE', 'LOGO', 'MAUVAISE', 'MANQUANTE'] as const;
export const EVAL_DATES_VERDICTS = ['CORRECTES', 'INCOMPLETES', 'FAUSSES', 'MANQUANTES'] as const;

/**
 * Ce qu'un humain dit d'une lecture. Les trois aspects sont indépendants : on
 * peut trancher le texte sans avoir encore regardé l'illustration, et la page
 * n'est jugée que lorsque les trois le sont.
 */
export const evalReadingVerdictSchema = z
  .object({
    textVerdict: z.enum(EVAL_TEXT_VERDICTS),
    imageVerdict: z.enum(EVAL_IMAGE_VERDICTS),
    datesVerdict: z.enum(EVAL_DATES_VERDICTS),
    note: z.string().trim().max(2000),
  })
  .partial()
  .refine((v) => Object.keys(v).length > 0, { message: 'Aucun verdict à enregistrer' });

/**
 * Ce que le worker rend d'une page lue.
 *
 * Le texte voyage en clair — il fait au plus quelques milliers de caractères et
 * c'est la pièce à conviction : sans lui, juger « le texte porte-t-il bien la
 * sortie ? » demanderait de rouvrir la page, donc de comparer à un HTML qui a
 * pu changer entre-temps.
 */
export const evalReadSchema = z.object({
  url: scraperUrl,
  error: z.string().trim().max(1000).optional(),
  swapped: z.boolean().optional().default(false),
  text: z.string().max(20_000).optional().default(''),
  textChars: z.number().int().min(0).optional().default(0),
  chars: z.number().int().min(0).optional().default(0),
  heading: z.string().trim().max(200).optional().default(''),
  dates: z.array(z.string().trim().max(40)).max(400).optional().default([]),
  imageUrl: z.union([scraperUrl, z.literal('')]).optional().default(''),
  h1InText: z.boolean().optional().default(false),
  truncated: z.boolean().optional().default(false),
  tooShort: z.boolean().optional().default(false),
  imageLooksLogo: z.boolean().optional().default(false),
  html: z.string().max(EVAL_MAX_HTML_B64).optional(),
});

// ────────────────────────────────────── banc d'extraction (étage 6)

/**
 * Les quatre verdicts d'un champ extrait, et pourquoi quatre.
 *
 * Le croisement avec « le modèle a-t-il rempli ce champ ? » donne les trois
 * taux qui comptent : l'exactitude de ce qu'il ose, sa couverture de ce que la
 * page offre, et son taux d'**invention**.
 *
 * `INVENTE` mérite sa propre valeur plutôt que d'être rangé sous `FAUX` : c'est
 * la faute propre à un modèle, celle qu'aucun code déterministe ne commet, et
 * c'est très exactement celle que l'ancrage sait pré-signaler sans coûter la
 * moindre étiquette. Les mélanger cacherait le seul chiffre qui dit si le
 * prompt tient le modèle.
 */
export const EVAL_FIELD_VERDICTS = ['JUSTE', 'FAUX', 'INVENTE', 'MANQUE'] as const;

/**
 * Trancher un aspect d'une fiche, ou plusieurs d'un coup.
 *
 * La clé est celle que `evaluation.audit_fiche` a donnée à l'aspect. Le serveur
 * ne tient pas la liste : elle est définie côté Python, elle bougera avec le
 * schéma d'extraction, et l'écrire ici en ferait une seconde vérité qui
 * finirait par diverger. Il vérifie seulement que la clé existe dans les
 * aspects de **cette** fiche — ce qui est la seule vérification qui ait un sens.
 */
export const evalFieldVerdictSchema = z.object({
  verdicts: z
    .record(z.string().trim().min(1).max(40), z.enum(EVAL_FIELD_VERDICTS))
    .refine((v) => Object.keys(v).length > 0, { message: 'Aucun verdict à enregistrer' }),
  note: z.string().trim().max(2000).optional(),
});

/** Le modèle à interroger, quand on ne veut pas celui du scraper par défaut. */
export const evalExtractionSchema = z.object({
  readingId: z.number().int().positive(),
  model: z.string().trim().max(120).optional().default(''),
});

/**
 * Mettre en file **toutes** les fiches lisibles du banc de lecture.
 *
 * Pas de `readingId` : c'est le serveur qui tient la liste des pages
 * extractibles, et lui seul. Laisser la console énumérer les identifiants
 * ferait de sa copie une seconde vérité — elle en tient déjà une pour peupler
 * son menu, et deux listes finissent toujours par diverger.
 */
export const evalExtractionAllSchema = z.object({
  model: z.string().trim().max(120).optional().default(''),
});

/**
 * Ce que le worker rend d'une extraction : la fiche, ses aspects, et le prix.
 *
 * Les aspects arrivent tels que le Python les a calculés — libellé compris. Le
 * serveur ne les recompose pas : l'ancrage, la cohérence et l'accord sont des
 * instruments de `evaluation.audit_fiche`, et les réimplémenter en Node
 * donnerait la vérité d'une réimplémentation, c'est-à-dire aucune.
 */
export const evalExtractSchema = z.object({
  error: z.string().trim().max(2000).optional(),
  model: z.string().trim().max(120).optional().default(''),
  fiche: z.record(z.string(), z.unknown()).optional().default({}),
  aspects: z
    .array(
      z.object({
        key: z.string().trim().min(1).max(40),
        label: z.string().trim().max(80),
        value: z.string().max(4000).optional().default(''),
        filled: z.boolean().optional().default(false),
        /** Ce qui l'a examiné : « ancrage », « cohérence », « aucun »… */
        instrument: z.string().trim().max(60).optional().default(''),
        /** Les défauts relevés. Des libellés, pas des verdicts. */
        flags: z.array(z.string().trim().max(30)).max(8).optional().default([]),
        /**
         * Le verdict que la fiche approuvée **propose** pour ce champ, quand il
         * y en a une. Vide quand elle ne peut pas trancher — la description,
         * qui est une reformulation, ou un champ vide des deux côtés mais
         * ancré dans la page.
         *
         * Proposé, jamais écrit : il n'entre dans `verdicts` que si un humain
         * clique. Un verdict qui s'inscrirait tout seul redeviendrait
         * indiscernable de « personne n'a regardé ».
         */
        proposed: z.enum(EVAL_FIELD_VERDICTS).or(z.literal('')).optional().default(''),
        /** Pourquoi cette proposition, en clair. */
        because: z.string().trim().max(200).optional().default(''),
      }),
    )
    .max(40)
    .optional()
    .default([]),
  /** Une fiche approuvée a servi de référence. */
  hasReference: z.boolean().optional().default(false),
  /**
   * Le titre approuvé ne se retrouve plus dans le texte : ce n'est plus la même
   * page, et toutes les propositions ont été retirées.
   */
  pageMoved: z.boolean().optional().default(false),
  inputTokens: z.number().int().min(0).optional().default(0),
  outputTokens: z.number().int().min(0).optional().default(0),
  costUsd: z.number().min(0).optional().default(0),
});

/**
 * Peupler le banc de lecture depuis ce que le pipeline a déjà fait.
 *
 * Deux paniers, et l'équilibre entre eux est **la** question de ce banc :
 * `approuvees` sont les pages où l'étage 5 a réussi, `abandonnees` celles qu'il
 * a écartées sans que personne ne vérifie jamais s'il avait raison. Ne prendre
 * que les premières mesurerait la brique sur ses propres succès.
 */
export const evalSeedSchema = z.object({
  bucket: z.enum(['approuvees', 'abandonnees']),
  limit: z.number().int().min(1).max(100).optional().default(25),
});
