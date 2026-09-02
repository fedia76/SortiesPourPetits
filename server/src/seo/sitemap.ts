import { escapeHtml } from './html';

/**
 * Le sitemap : la seule façon fiable, pour un site dont les fiches se
 * comptent en milliers, de les faire toutes connaître.
 *
 * Les liens de l'accueil n'en désignent qu'une page à la fois ; un robot qui
 * suit la pagination y arriverait, mais lentement et sans garantie. Le sitemap
 * les donne d'un coup, avec la date de chacune.
 */
export function sitemapXml(base: string, events: { id: number; createdAt: Date }[]): string {
  const day = (d: Date) => d.toISOString().slice(0, 10);
  const urls = [
    `  <url>
    <loc>${escapeHtml(`${base}/`)}</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>`,
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
