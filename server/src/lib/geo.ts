/**
 * Convention des coordonnées manquantes.
 *
 * Un programme tiers (le scraper) peut proposer une sortie dont l'adresse n'a
 * pas pu être géocodée. Plutôt que de perdre la trouvaille, il la soumet avec
 * des coordonnées à zéro : le point (0, 0) est en plein golfe de Guinée, donc
 * la sortie ne remonte dans aucune recherche par rayon, et son approbation est
 * refusée tant qu'un modérateur n'a pas complété l'adresse.
 */
export function hasCoordinates(venue: { lat: unknown; lng: unknown }): boolean {
  return Number(venue.lat) !== 0 || Number(venue.lng) !== 0;
}
