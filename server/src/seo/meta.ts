import { config } from '../config';
import { escapeHtml, jsonLdScript } from './html';

export const SITE_NAME = 'SortiesPourPetits';

/** Ce qu'une page a besoin de dire d'elle-même dans son `<head>`. */
export interface PageMeta {
  title: string;
  description: string;
  /** Chemin absolu depuis la racine — « /sorties/12 », barre initiale comprise. */
  path: string;
  /** Photo de partage, chemin ou URL déjà absolue. */
  image?: string | null;
  ogType?: 'website' | 'article';
  /** Vrai pour tout ce qu'un moteur n'a aucune raison de garder. */
  noindex?: boolean;
  jsonLd?: unknown[];
}

/**
 * L'adresse publique du site, telle qu'elle doit apparaître dans les liens.
 *
 * `PUBLIC_BASE_URL` fait foi. À défaut on reconstitue depuis la requête, ce
 * qui suppose que le reverse proxy renseigne l'hôte et le protocole — c'est
 * ce que fait Caddy, et ce que `trust proxy` apprend à Express à lire.
 */
export function baseUrl(req: { protocol: string; get(name: string): string | undefined }): string {
  if (config.publicBaseUrl) return config.publicBaseUrl;
  return `${req.protocol}://${req.get('host') ?? 'localhost'}`;
}

/** Rend absolue une adresse interne ; laisse passer celles qui le sont déjà. */
export function absolute(base: string, target: string): string {
  return /^https?:\/\//i.test(target) ? target : `${base}${target}`;
}

/**
 * Le `<head>` complet d'une page.
 *
 * `noindex` s'impose de deux façons : parce que la page ne mérite pas d'être
 * indexée (une file de modération, un formulaire), ou parce que le site entier
 * ne le mérite pas encore — c'est le rôle de `config.indexable`, qui garde une
 * préproduction hors des résultats sans qu'on ait à y penser.
 */
export function buildHead(base: string, meta: PageMeta): string {
  const url = `${base}${meta.path}`;
  const image = meta.image ? absolute(base, meta.image) : null;
  const robots = meta.noindex || !config.indexable ? 'noindex, nofollow' : 'index, follow';
  const tags = [
    `<title>${escapeHtml(meta.title)}</title>`,
    `<meta name="description" content="${escapeHtml(meta.description)}" />`,
    `<meta name="robots" content="${robots}" />`,
    // Pas d'adresse canonique sur une page qu'on demande d'ignorer : ce serait
    // désigner une page de référence pour ce qui n'a pas à en avoir, et une 404
    // qui se déclare équivalente à l'accueil est une invitation à l'indexer.
    meta.noindex ? '' : `<link rel="canonical" href="${escapeHtml(url)}" />`,
    `<meta property="og:site_name" content="${escapeHtml(SITE_NAME)}" />`,
    `<meta property="og:locale" content="fr_FR" />`,
    `<meta property="og:type" content="${meta.ogType ?? 'website'}" />`,
    `<meta property="og:title" content="${escapeHtml(meta.title)}" />`,
    `<meta property="og:description" content="${escapeHtml(meta.description)}" />`,
    `<meta property="og:url" content="${escapeHtml(url)}" />`,
    image ? `<meta property="og:image" content="${escapeHtml(image)}" />` : '',
    `<meta name="twitter:card" content="${image ? 'summary_large_image' : 'summary'}" />`,
    `<meta name="twitter:title" content="${escapeHtml(meta.title)}" />`,
    `<meta name="twitter:description" content="${escapeHtml(meta.description)}" />`,
    image ? `<meta name="twitter:image" content="${escapeHtml(image)}" />` : '',
    ...(meta.jsonLd ?? []).map(jsonLdScript),
  ];
  return tags.filter(Boolean).join('\n    ');
}
