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
