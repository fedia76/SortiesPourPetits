/**
 * Champs qu'un import laisse à compléter par la modération.
 *
 * Un programme tiers (le scraper) trouve rarement toutes les informations
 * d'une sortie. Plutôt que de perdre la trouvaille, il la propose avec une
 * valeur convenue à la place de ce qui manque, et le serveur refuse de
 * l'approuver tant qu'un modérateur ne l'a pas corrigée :
 *
 *   - position inconnue → coordonnées (0, 0), en plein golfe de Guinée, donc
 *     hors de portée de toute recherche par rayon ;
 *   - tarif inconnu → prix négatif, impossible à confondre avec la gratuité.
 */

/** Valeur convenue pour « le tarif n'a pas pu être déterminé ». */
export const UNKNOWN_PRICE = -1;

export function hasCoordinates(venue: { lat: unknown; lng: unknown }): boolean {
  return Number(venue.lat) !== 0 || Number(venue.lng) !== 0;
}

export function hasPrice(event: { isFree: boolean; price: unknown }): boolean {
  return event.isFree || Number(event.price) >= 0;
}
