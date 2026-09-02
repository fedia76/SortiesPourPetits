/**
 * Les chemins que l'application sert mais qu'un moteur n'a rien à indexer :
 * ce qui demande un compte, et ce qui n'est qu'un formulaire.
 *
 * Une seule liste, lue à deux endroits — le `noindex` des pages et le
 * `robots.txt` — parce qu'un des deux qui oublie une entrée, c'est une file de
 * modération dans les résultats de recherche.
 */
export const PRIVATE_PREFIXES = [
  '/admin',
  '/moderation',
  '/proposer',
  '/mes-sorties',
  '/cles-api',
  '/connexion',
  '/inscription',
];

/** Une fiche en cours d'édition : même chemin qu'une fiche publique, en plus long. */
export const EDIT_SUFFIX = '/modifier';

export function isPrivatePath(pathname: string): boolean {
  if (pathname.endsWith(EDIT_SUFFIX)) return true;
  return PRIVATE_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}
