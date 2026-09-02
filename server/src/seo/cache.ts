/**
 * Un cache mémoire minuscule, pour ce qui coûte une requête de plus par visite.
 *
 * L'accueil et le sitemap sont recalculés à l'identique pour tous les
 * visiteurs, et le sitemap parcourt toutes les sorties à venir. Les garder
 * quelques minutes évite qu'un passage de robot ne se traduise en autant de
 * requêtes SQL. Les fiches, elles, ne sont pas cachées : une lecture par clé
 * primaire ne vaut pas qu'on s'encombre d'une entrée par sortie.
 */

interface Entry<T> {
  value: T;
  expiresAt: number;
}

const entries = new Map<string, Entry<unknown>>();

/**
 * Au-delà, on repart de zéro. Les clés viennent de l'adresse demandée, donc du
 * dehors : sans plafond, un robot qui parcourt `?page=1` à `?page=100000`
 * ferait grossir la carte autant qu'il le veut. Les entrées utiles se
 * reconstruisent à la requête suivante.
 */
const MAX_ENTRIES = 200;

export async function cached<T>(key: string, ttlMs: number, build: () => Promise<T>): Promise<T> {
  const hit = entries.get(key) as Entry<T> | undefined;
  if (hit && hit.expiresAt > Date.now()) return hit.value;
  const value = await build();
  if (entries.size >= MAX_ENTRIES) entries.clear();
  entries.set(key, { value, expiresAt: Date.now() + ttlMs });
  return value;
}
