import { hasPrice } from '../lib/incomplete';
import type { PublicEvent } from './query';

/**
 * Les mêmes libellés que `client/src/types.ts`, en français et au même mot
 * près.
 *
 * C'est une duplication, et elle est voulue : le HTML pré-rendu est aussitôt
 * remplacé par celui de Vue, et les deux doivent dire la même chose — un
 * moteur qui lit « Gratuit » là où le visiteur lira « Prix libre » indexe autre
 * chose que ce qu'on montre. Toucher à l'un des deux fichiers demande donc de
 * toucher à l'autre.
 */

export const SETTING_LABELS: Record<string, string> = {
  INDOOR: 'Intérieur',
  OUTDOOR: 'Extérieur',
  BOTH: 'Intérieur & extérieur',
};

export function priceLabel(event: PublicEvent): string {
  if (event.isFree) return 'Gratuit';
  if (!hasPrice(event)) return 'Tarif à compléter';
  return `${event.price} €`;
}

export function ageLabel(event: PublicEvent): string | null {
  const { ageMin, ageMax } = event;
  if (ageMin !== null && ageMax !== null) return `De ${ageMin} à ${ageMax} ans`;
  if (ageMin !== null) return `À partir de ${ageMin} ans`;
  if (ageMax !== null) return `Jusqu'à ${ageMax} ans`;
  return null;
}

export function shortAgeLabel(event: PublicEvent): string | null {
  const { ageMin, ageMax } = event;
  if (ageMin !== null && ageMax !== null) return `${ageMin}–${ageMax} ans`;
  if (ageMin !== null) return `dès ${ageMin} ans`;
  if (ageMax !== null) return `jusqu'à ${ageMax} ans`;
  return null;
}

/** Prochain jour où la sortie a lieu ; `undefined` si tout est passé. */
export function nextDate(event: PublicEvent, from: string): string | undefined {
  return event.dates.find((d) => d >= from);
}

/** « dimanche 20 septembre » */
export function dayLabel(day: string): string {
  return new Date(`${day}T12:00:00Z`).toLocaleDateString('fr-FR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    timeZone: 'UTC',
  });
}

/** « 20 septembre 2026 » */
export function longDate(day: string): string {
  return new Date(`${day}T12:00:00Z`).toLocaleDateString('fr-FR', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

/** Ce que la vignette d'une sortie affiche en guise de date. */
export function cardDateLabel(event: PublicEvent, from: string): string {
  if (event.isPermanent || !event.dateStart || !event.dateEnd) return 'Toute l’année';
  const short = (d: string) =>
    new Date(`${d}T12:00:00Z`).toLocaleDateString('fr-FR', {
      day: 'numeric',
      month: 'short',
      timeZone: 'UTC',
    });
  const prochaine = nextDate(event, from);
  if (prochaine) {
    return new Date(`${prochaine}T12:00:00Z`).toLocaleDateString('fr-FR', {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      timeZone: 'UTC',
    });
  }
  return event.dateStart === event.dateEnd
    ? short(event.dateStart)
    : `${short(event.dateStart)} → ${short(event.dateEnd)}`;
}
