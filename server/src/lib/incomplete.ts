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

/**
 * Le tarif de cette sortie est-il connu ?
 *
 * Le test sur l'absence est explicite, et il ne l'était pas : `Number(null)`
 * vaut **zéro**, donc `Number(event.price) >= 0` répondait « oui, le tarif est
 * connu » pour une sortie payante sans prix. Le client, lui
 * (`client/src/types.ts`), écartait ce cas — les deux copies de la même règle
 * ne disaient donc pas la même chose, et c'est le serveur qui garde
 * l'approbation en modération.
 *
 * Le schéma d'entrée interdit aujourd'hui de créer une telle fiche, si bien
 * que le désaccord ne se voyait sur aucune sortie vivante. Il se serait vu sur
 * la première ligne écrite autrement — une reprise de données, une migration.
 *
 * ⚠️ Cette fonction est **recopiée** dans `client/src/types.ts`, faute de
 * paquet partagé entre les deux moitiés du dépôt. Les deux doivent changer
 * ensemble ; `tests/incomplete.test.ts` fixe la table de vérité commune.
 */
export function hasPrice(event: { isFree: boolean; price: unknown }): boolean {
  if (event.isFree) return true;
  if (event.price === null || event.price === undefined) return false;
  return Number(event.price) >= 0;
}
