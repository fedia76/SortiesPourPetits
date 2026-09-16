/**
 * Ce qu'une sortie **dit d'elle-même**, mis en mots pour l'écran.
 *
 * Ces fonctions vivaient dans `types.ts`, qui avait fini par en compter huit,
 * plus quelques constantes, sur seize cents lignes. Un fichier nommé `types`
 * qui porte du calcul n'est plus un fichier de types : c'est l'endroit où l'on
 * pose ce qu'on ne sait pas où mettre, et il grossit indéfiniment parce que
 * tout le monde l'importe déjà.
 *
 * Deux règles ici sont **recopiées du serveur** (`server/src/lib/incomplete.ts`)
 * faute de paquet partagé entre les deux moitiés du dépôt. Elles avaient déjà
 * divergé : le serveur répondait « tarif connu » pour une sortie payante sans
 * prix, là où le client affichait « Tarif à compléter ». Le serveur garde
 * l'approbation en modération, donc c'est lui qui avait tort. `types.test.ts`
 * et `server/tests/incomplete.test.ts` tiennent désormais la **même** table de
 * vérité, cas pour cas — les deux copies ne peuvent plus diverger sans qu'un
 * des deux fichiers tombe.
 */
import type { EventItem, ScraperRun, Venue } from '../types';

/**
 * Les conventions d'un import incomplet : une adresse qui n'a pas pu être
 * géocodée arrive à (0, 0), un tarif indéterminé arrive négatif. Le serveur
 * refuse d'approuver la sortie tant que ce n'est pas corrigé.
 */
export const UNKNOWN_PRICE = -1;

export function hasCoordinates(venue: Pick<Venue, 'lat' | 'lng'>): boolean {
  return venue.lat !== 0 || venue.lng !== 0;
}

export function hasPrice(event: { isFree: boolean; price: number | null }): boolean {
  if (event.isFree) return true;
  if (event.price === null || event.price === undefined) return false;
  return event.price >= 0;
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
/**
 * `musee-rodin.fr` plutôt qu'une URL de deux cents caractères.
 *
 * Partagée plutôt que recopiée : la fiche et la modération montrent les mêmes
 * deux liens, et deux abréviations différentes de la même adresse feraient
 * douter qu'il s'agit de la même page — exactement ce que ces deux champs
 * existent pour lever.
 */
export function hostLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    // Une adresse que le navigateur ne sait pas lire est montrée telle quelle :
    // c'est encore le plus utile pour qui doit la corriger.
    return url;
  }
}

export function dayLabel(day: string): string {
  return new Date(`${day}T12:00:00`).toLocaleDateString('fr-FR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
}

/** Ce qu'une exécution a joué, dit en une ligne : c'est son nom dans la console. */
export function runLabel(run: ScraperRun): string {
  if (run.config) return run.config.name;
  if (run.event) return `Source de « ${run.event.title} »`;
  return 'Exécution';
}
