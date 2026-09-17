/**
 * Ce que le serveur a déjà répondu, écrit dans le document.
 *
 * ## Pourquoi ce fichier existe
 *
 * Le serveur pré-rend chaque page publique, puis Vue se monte sur `#app` et
 * **remplace** ce qu'il avait écrit — `createApp` vide le conteneur, il ne
 * s'hydrate pas dessus. La vue repart alors de rien et redemande à l'API ce que
 * le document contenait déjà : entre les deux, la page est vide.
 *
 * Pour un visiteur, c'est un clignotement. Pour le moteur de rendu de Google,
 * c'était fatal : la `robots.txt` lui interdisait `/api/`, l'appel était refusé,
 * et toutes les pages du site rendaient le même encadré d'erreur. Google les a
 * traitées comme ce qu'elles étaient devenues — des doublons —, en a gardé une
 * et a laissé les autres hors de l'index.
 *
 * L'interdiction est levée. Mais la dépendance elle-même est le vrai défaut :
 * une page dont le contenu tient dans le document ne devrait pas avoir besoin
 * du réseau pour s'afficher. Le serveur écrit donc, à côté de ses `<meta>`, les
 * réponses d'API qui correspondent à la page demandée ; ce module les relit.
 *
 * ## Une seule fois
 *
 * Une réponse consommée est retirée. Elle décrit l'instant du rendu, et une
 * navigation ultérieure vers la même adresse doit voir des données fraîches —
 * une sortie a pu être modifiée, une liste changer. L'état initial sert au
 * premier affichage, à rien d'autre.
 */

/** L'identifiant du bloc, connu des deux côtés (`server/src/seo/html.ts`). */
const STATE_ID = 'etat-initial';

/**
 * L'adresse d'une réponse, sous une forme comparable.
 *
 * L'ordre des paramètres ne veut rien dire — `?page=1&pageSize=12` et
 * `?pageSize=12&page=1` sont le même appel —, et faire dépendre la
 * reconnaissance de cet ordre aurait été se condamner à une divergence
 * silencieuse le jour où l'un des deux côtés réordonne sa requête.
 */
function cle(chemin: string): string {
  const url = new URL(chemin, window.location.origin);
  const params = [...url.searchParams.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const query = new URLSearchParams(params).toString();
  return query ? `${url.pathname}?${query}` : url.pathname;
}

let reponses: Map<string, unknown> | null = null;

/**
 * Le bloc, lu et retiré du document.
 *
 * Retiré parce qu'il a fini son office : le garder n'offrirait qu'un JSON
 * dupliqué dans le DOM. Illisible, il est ignoré — un état abîmé doit coûter
 * un aller-retour réseau, pas une page blanche.
 */
function lire(): Map<string, unknown> {
  if (reponses) return reponses;
  reponses = new Map();
  const noeud = document.getElementById(STATE_ID);
  if (!noeud) return reponses;
  try {
    const brut: unknown = JSON.parse(noeud.textContent ?? 'null');
    if (brut && typeof brut === 'object') {
      for (const [chemin, reponse] of Object.entries(brut)) reponses.set(cle(chemin), reponse);
    }
  } catch {
    // Rien à faire : l'application appellera l'API, comme avant ce fichier.
  }
  noeud.remove();
  return reponses;
}

/**
 * La réponse que le serveur a déjà donnée pour cet appel, s'il l'a donnée.
 *
 * `undefined` n'est pas une réponse possible d'une route d'API — elles rendent
 * toutes un objet —, donc il peut dire « rien ici » sans ambiguïté.
 */
export function reponsePreRendue<T>(chemin: string): T | undefined {
  const table = lire();
  const k = cle(chemin);
  if (!table.has(k)) return undefined;
  const reponse = table.get(k) as T;
  table.delete(k);
  return reponse;
}
