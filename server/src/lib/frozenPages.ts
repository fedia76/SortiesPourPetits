/**
 * L'affichage d'une page gelée par le worker (voir `ScraperRunPage`).
 *
 * Une page étrangère servie depuis notre domaine : tout ce qui suit sert à ce
 * qu'elle s'affiche **sans pouvoir rien faire**.
 */

/**
 * `sandbox` sans `allow-scripts` : origine opaque, aucun script, aucun
 * formulaire, aucun accès aux cookies de la console. Les images et les
 * feuilles de style restent permises — c'est ce qui rend la page lisible —,
 * les scripts sont refusés deux fois plutôt qu'une.
 */
export const FROZEN_PAGE_CSP =
  "sandbox; default-src * data: blob: 'unsafe-inline'; script-src 'none'";

/** Ajoute un `<base href>` pour que les chemins relatifs de la page se résolvent chez elle. */
export function withBase(html: string, url: string): string {
  const base = `<base href="${url.replace(/"/g, '&quot;')}">`;
  const head = html.match(/<head[^>]*>/i);
  if (head && head.index !== undefined) {
    const at = head.index + head[0].length;
    return html.slice(0, at) + base + html.slice(at);
  }
  return base + html;
}
