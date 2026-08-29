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
export interface ScraperConfig {
  id: number;
  name: string;
  enabled: boolean;
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
  title: string | null;
  decision: string;
  reason: string | null;
  eventId: number | null;
  at: string;
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
