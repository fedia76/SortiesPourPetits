export type Role = 'USER' | 'MODERATOR' | 'ADMIN';
export type Setting = 'INDOOR' | 'OUTDOOR' | 'BOTH';
export type EventStatus = 'PENDING' | 'APPROVED' | 'REJECTED';

export interface User {
  id: number;
  email: string;
  displayName: string;
  role: Role;
}

export interface Category {
  id: number;
  name: string;
}

export interface Venue {
  id: number;
  name: string;
  address: string;
  city: string;
  postalCode: string;
  lat: number;
  lng: number;
}

/**
 * Champs qu'un programme d'import laisse à compléter par la modération
 * (voir server/src/lib/incomplete.ts) : une adresse qui n'a pas pu être
 * géocodée arrive à (0, 0), un tarif indéterminé arrive négatif. Le serveur
 * refuse d'approuver la sortie tant que ce n'est pas corrigé.
 */
export const UNKNOWN_PRICE = -1;

export function hasCoordinates(venue: Pick<Venue, 'lat' | 'lng'>): boolean {
  return venue.lat !== 0 || venue.lng !== 0;
}

export function hasPrice(event: { isFree: boolean; price: number | null }): boolean {
  return event.isFree || (event.price !== null && event.price >= 0);
}

/** Badge de tarif, y compris pour une sortie importée sans tarif connu. */
export function priceLabel(event: { isFree: boolean; price: number | null }): string {
  if (event.isFree) return 'Gratuit';
  if (!hasPrice(event)) return 'Tarif à compléter';
  return `${event.price} €`;
}

/**
 * Tranche d'âge en clair, y compris quand une seule borne est connue.
 *
 * Les deux bornes sont facultatives et indépendantes : n'afficher la tranche
 * que lorsque les deux sont renseignées faisait disparaître le « à partir de
 * 3 ans » de sorties qui ne se donnent pas d'âge maximum.
 */
export function ageLabel(event: Pick<EventItem, 'ageMin' | 'ageMax'>): string | null {
  const { ageMin, ageMax } = event;
  if (ageMin !== null && ageMax !== null) return `De ${ageMin} à ${ageMax} ans`;
  if (ageMin !== null) return `À partir de ${ageMin} ans`;
  if (ageMax !== null) return `Jusqu'à ${ageMax} ans`;
  return null;
}

/** Même tranche d'âge, en version courte pour un badge de vignette. */
export function shortAgeLabel(event: Pick<EventItem, 'ageMin' | 'ageMax'>): string | null {
  const { ageMin, ageMax } = event;
  if (ageMin !== null && ageMax !== null) return `${ageMin}–${ageMax} ans`;
  if (ageMin !== null) return `dès ${ageMin} ans`;
  if (ageMax !== null) return `jusqu'à ${ageMax} ans`;
  return null;
}

/**
 * Prochain jour où la sortie a lieu, à partir d'aujourd'hui.
 *
 * `null` quand elle n'énumère pas ses jours — le cas courant : sa période
 * suffit alors à la décrire. `undefined` quand elle est passée.
 */
export function nextDate(event: Pick<EventItem, 'dates'>, today = new Date()): string | undefined {
  const iso = today.toISOString().slice(0, 10);
  return event.dates.find((d) => d >= iso);
}

/** « dimanche 20 septembre » — un jour de représentation, en clair. */
export function dayLabel(day: string): string {
  return new Date(`${day}T12:00:00`).toLocaleDateString('fr-FR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
}

/** Pourquoi et à quel point une sortie ressemble à celle en cours de modération. */
export interface Similarity {
  /** Note de 0 à 100 : plus c'est haut, plus le doublon est probable. */
  score: number;
  reasons: string[];
  distanceKm?: number;
}

export interface EventItem {
  id: number;
  title: string;
  description: string;
  sourceUrl: string | null;
  isFree: boolean;
  price: number | null;
  photoUrl: string | null;
  ageMin: number | null;
  ageMax: number | null;
  isPermanent: boolean;
  dateStart: string | null;
  dateEnd: string | null;
  /** Jours de représentation. Vide = tous les jours de la période. */
  dates: string[];
  openTime: string | null;
  closeTime: string | null;
  setting: Setting | null;
  status: EventStatus;
  rejectionReason: string | null;
  venue: Venue;
  category: Category;
  author: { id: number; displayName: string; email?: string };
  distanceKm?: number;
  /** Renseigné par la recherche de doublons de la modération. */
  similarity?: Similarity;
}

export interface EventInput {
  title: string;
  description: string;
  sourceUrl: string | null;
  isFree: boolean;
  price: number | null;
  ageMin: number | null;
  ageMax: number | null;
  isPermanent: boolean;
  dateStart: string | null;
  dateEnd: string | null;
  dates: string[];
  openTime: string | null;
  closeTime: string | null;
  setting: Setting | null;
  categoryId: number;
  venue: Omit<Venue, 'id'>;
}

export const SETTING_LABELS: Record<Setting, string> = {
  INDOOR: 'Intérieur',
  OUTDOOR: 'Extérieur',
  BOTH: 'Intérieur & extérieur',
};

export const STATUS_LABELS: Record<EventStatus, string> = {
  PENDING: 'En attente de modération',
  APPROVED: 'Approuvée',
  REJECTED: 'Refusée',
};

export type ScraperRunStatus = 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED';

export const RUN_STATUS_LABELS: Record<ScraperRunStatus, string> = {
  QUEUED: 'En file',
  RUNNING: 'En cours',
  DONE: 'Terminée',
  FAILED: 'En échec',
};

/**
 * Une recherche paramétrée du scraper. Thème, période et zone orientent la
 * recherche ; ils ne filtrent pas le résultat quand `keepOutOfScope` est vrai,
 * parce qu'une page déjà lue est déjà payée.
 */
/**
 * Les deux modes d'une recherche automatique.
 *
 * « recherche » : le modèle cherche sur le web, on dépouille les agendas
 * qu'il remonte. « site » : les adresses sont connues (le site d'un festival,
 * la saison d'un théâtre) et aucune recherche n'est lancée.
 */
export type ScraperMode = 'recherche' | 'site';

export const SCRAPER_MODE_LABELS: Record<ScraperMode, string> = {
  recherche: 'Recherche web',
  site: 'Site précis',
};

export interface ScraperConfig {
  id: number;
  name: string;
  enabled: boolean;
  mode: ScraperMode;
  /** Adresses de départ du mode « site », une par ligne. */
  seedUrls: string;
  theme: string;
  area: string;
  period: string;
  horizonDays: number;
  maxEvents: number;
  maxSearches: number;
  maxAgendas: number;
  maxLinksPerAgenda: number;
  maxPageChars: number;
  maxCostUsd: number;
  keepOutOfScope: boolean;
  defaultCategory: string;
  postalPrefixes: string;
  blockedDomains: string;
  searchModel: string;
  selectModel: string;
  extractionModel: string;
  searchPrompt: string | null;
  selectPrompt: string | null;
  extractionPrompt: string | null;
  extractionMultiPrompt: string | null;
  createdAt: string;
  _count?: { runs: number };
  runs?: Pick<ScraperRun, 'id' | 'status' | 'queuedAt' | 'finishedAt' | 'retained'>[];
}

export interface ScraperRun {
  id: number;
  status: ScraperRunStatus;
  submit: boolean;
  queuedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  /** Date à laquelle les sorties et la mémoire de l'exécution ont été supprimées. */
  purgedAt: string | null;
  error: string | null;
  candidates: number;
  pages: number;
  retained: number;
  submitted: number;
  duplicates: number;
  skipped: number;
  errors: number;
  inputTokens: number;
  outputTokens: number;
  webSearches: number;
  costUsd: number;
  config?: { id: number; name: string };
  requestedBy?: { id: number; displayName: string } | null;
  items?: ScraperRunItem[];
}

export interface ScraperRunItem {
  id: number;
  url: string;
  /** Clé de mémorisation, quand la page a été mémorisée. */
  key: string | null;
  title: string | null;
  decision: string;
  reason: string | null;
  eventId: number | null;
  at: string;
}

/**
 * Une page dont le scraper se souvient (`ScrapedUrl`).
 *
 * L'URL est la clé normalisée — schéma, `www.`, paramètres de suivi et barre
 * finale retirés — pas forcément le lien exact rencontré : deux adresses
 * équivalentes ne doivent pas faire relire deux fois la même page.
 */
export interface ScrapedUrlEntry {
  id: number;
  url: string;
  title: string | null;
  decision: string;
  firstSeen: string;
  lastSeen: string;
  eventId: number | null;
  event?: { id: number; title: string; status: EventStatus } | null;
}

export interface ScraperMemory {
  entries: ScrapedUrlEntry[];
  total: number;
  page: number;
  pageSize: number;
  /** Poids de chaque verdict sur toute la mémoire, filtre courant ignoré. */
  decisions: { decision: string; count: number }[];
}

/** Ce que le scraper a décidé d'une page, en clair. */
export const DECISION_LABELS: Record<string, string> = {
  submitted: 'Proposée au site',
  dry_run: 'Retenue (essai)',
  duplicate: 'Doublon',
  irrelevant: 'Pas une sortie',
  invalid: 'Inexploitable',
  out_of_period: 'Hors période',
  out_of_area: 'Hors zone',
  seen: 'Déjà connue',
  blocked: 'Domaine bloqué',
  error: 'Erreur',
};

/**
 * Tableau de bord du scraping (`GET /api/scraper/stats`).
 *
 * Les parts se calculent côté vue : le serveur renvoie des comptes, ce qui
 * évite d'avoir à s'entendre sur un arrondi.
 */
export interface ScraperStats {
  scope: { configId: number | null; configName: string | null; days: number | null };
  totals: {
    runs: number;
    candidates: number;
    pages: number;
    retained: number;
    submitted: number;
    costUsd: number;
    inputTokens: number;
    outputTokens: number;
    webSearches: number;
  };
  /** Un domaine source, `www.` retiré : les pages qu'il a coûtées et ce qu'il a donné. */
  domains: { domain: string; pages: number; submitted: number; approved: number }[];
  categories: { id: number; name: string; events: number; approved: number }[];
  decisions: { decision: string; count: number }[];
  /** Statuts des sorties importées, indexés par `EventStatus`. */
  statuses: Partial<Record<EventStatus, number>>;
  configs: {
    id: number;
    name: string;
    runs: number;
    pages: number;
    retained: number;
    submitted: number;
    costUsd: number;
  }[];
}
