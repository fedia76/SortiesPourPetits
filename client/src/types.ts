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
 * Un lieu proposé par un programme d'import dont l'adresse n'a pas pu être
 * géocodée arrive avec des coordonnées à zéro. Le serveur refuse d'approuver
 * une telle sortie : le modérateur doit d'abord compléter l'adresse.
 */
export function hasCoordinates(venue: Pick<Venue, 'lat' | 'lng'>): boolean {
  return venue.lat !== 0 || venue.lng !== 0;
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
