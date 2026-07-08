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

export interface OpeningHour {
  dayOfWeek: number; // 0 = lundi … 6 = dimanche
  openTime: string;
  closeTime: string;
}

export interface EventItem {
  id: number;
  title: string;
  description: string;
  isFree: boolean;
  price: number | null;
  photoUrl: string | null;
  ageMin: number;
  ageMax: number;
  dateStart: string;
  dateEnd: string;
  setting: Setting;
  status: EventStatus;
  rejectionReason: string | null;
  venue: Venue;
  category: Category;
  openingHours: OpeningHour[];
  author: { id: number; displayName: string; email?: string };
  distanceKm?: number;
}

export interface EventInput {
  title: string;
  description: string;
  isFree: boolean;
  price: number | null;
  ageMin: number;
  ageMax: number;
  dateStart: string;
  dateEnd: string;
  setting: Setting;
  categoryId: number;
  venue: Omit<Venue, 'id'>;
  openingHours: OpeningHour[];
}

export const DAY_NAMES = [
  'Lundi',
  'Mardi',
  'Mercredi',
  'Jeudi',
  'Vendredi',
  'Samedi',
  'Dimanche',
] as const;

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
