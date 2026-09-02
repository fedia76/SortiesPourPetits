import { Prisma } from '@prisma/client';

/**
 * Ce qu'une zone recouvre, en termes de requête.
 *
 * Une sortie appartient à une zone si le code postal de son lieu commence par
 * l'un de ses préfixes. « 75 » attrape tout Paris, « 766 » le bassin havrais
 * sans le reste de la Seine-Maritime : la précision se règle en allongeant le
 * préfixe, ce qui évite d'avoir à énumérer des communes.
 */

/** « 75, 77 ,78 » → ['75', '77', '78']. Tolérant, parce que c'est saisi à la main. */
export function parsePrefixes(raw: string): string[] {
  return [...new Set(raw.split(',').map((p) => p.trim()).filter(Boolean))];
}

/**
 * Le filtre Prisma d'une zone.
 *
 * Une zone sans préfixe exploitable ne doit rien renvoyer plutôt que tout : une
 * liste vide se remarque et se corrige, un catalogue entier affiché sous le nom
 * d'une ville ne se remarque pas.
 */
export function areaFilter(postalPrefixes: string): Prisma.EventWhereInput {
  const prefixes = parsePrefixes(postalPrefixes);
  if (!prefixes.length) return { id: -1 };
  return { venue: { OR: prefixes.map((p) => ({ postalCode: { startsWith: p } })) } };
}
