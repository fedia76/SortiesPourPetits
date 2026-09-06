import { escapeHtml } from './html';

/**
 * Le sitemap : la seule façon fiable, pour un site dont les fiches se
 * comptent en milliers, de les faire toutes connaître.
 *
 * Les liens de l'accueil n'en désignent qu'une page à la fois ; un robot qui
 * suit la pagination y arriverait, mais lentement et sans garantie. Le sitemap
 * les donne d'un coup, avec la date de chacune.
 */
/** Une page de liste — l'accueil, une zone — et la date de sa dernière nouveauté. */
export interface SitemapListPage {
  path: string;
  lastmod: Date | null;
}

export function sitemapXml(
  base: string,
  events: { id: number; createdAt: Date }[],
  home: Date | null = null,
  areas: SitemapListPage[] = [],
): string {
  const day = (d: Date) => d.toISOString().slice(0, 10);
  /**
   * `lastmod` dit à un moteur qu'il vaut la peine de repasser. Il manquait sur
   * l'accueil et les zones — les deux pages dont le contenu bouge le plus, et
   * les seules qu'on souhaite voir réexplorées après un changement de titre.
   */
  const lastmod = (d: Date | null) => (d ? `\n    <lastmod>${day(d)}</lastmod>` : '');
  const urls = [
    `  <url>
    <loc>${escapeHtml(`${base}/`)}</loc>${lastmod(home)}
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>`,
    // Les zones passent avant les fiches : ce sont elles qu'on veut voir
    // classées, et une fiche de spectacle disparaît quand le spectacle est joué.
    ...areas.map(
      (a) => `  <url>
    <loc>${escapeHtml(`${base}${a.path}`)}</loc>${lastmod(a.lastmod)}
    <changefreq>daily</changefreq>
    <priority>0.9</priority>
  </url>`,
    ),
    ...events.map(
      (e) => `  <url>
    <loc>${escapeHtml(`${base}/sorties/${e.id}`)}</loc>
    <lastmod>${day(e.createdAt)}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>`,
    ),
  ];
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.join('\n')}
</urlset>
`;
}
