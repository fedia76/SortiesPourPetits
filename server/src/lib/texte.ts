/**
 * Mettre en texte une valeur dont on ne sait rien.
 *
 * `String(valeur)` rend « [object Object] » pour n'importe quel objet — une
 * chaîne qui ne distingue aucun objet d'un autre. Écrite dans la colonne d'une
 * correction ou dans une case de tableau comparatif, elle fait disparaître
 * exactement ce qu'on voulait mesurer, et elle le fait en silence. Sur un
 * symbole, `String` lève carrément.
 *
 * Deux endroits en avaient besoin — `eventCorrections` et `evalMetrics` — et
 * tous deux mesurent : c'est la raison d'être de ce fichier minuscule.
 */

/** N'importe quoi → du texte, sans jamais « [object Object] ». */
export function texteDe(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }
  // `JSON.stringify` rend `undefined` pour une fonction ou un symbole : rien à
  // en dire, et c'est plus honnête que d'en écrire le code source.
  return JSON.stringify(value) ?? '';
}
