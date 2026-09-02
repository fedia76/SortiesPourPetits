import { today } from '../lib/dateWindow';
import { escapeHtml, truncate, type RenderedPage } from './html';
import { breadcrumbJsonLd, eventJsonLd, itemListJsonLd, websiteJsonLd } from './jsonld';
import { SITE_NAME, absolute, buildHead, type PageMeta } from './meta';
import {
  SETTING_LABELS,
  ageLabel,
  cardDateLabel,
  dayLabel,
  longDate,
  nextDate,
  priceLabel,
  shortAgeLabel,
} from './labels';
import { findArea, findPublicEvent, listAreas, listPublicEvents, type PublicEvent } from './query';
import type { Area } from '@prisma/client';
import { isPrivatePath } from './routes';

/**
 * Le HTML des pages publiques, écrit à la main.
 *
 * On aurait pu faire tourner Vue côté serveur. Ç'aurait voulu dire un second
 * build, un second point d'entrée, et Vuetify à rendre hors navigateur — pour
 * un résultat que le montage de l'application remplace de toute façon une
 * seconde plus tard. Ce qu'un moteur doit trouver dans le document initial est
 * plus étroit que ce que l'application affiche : le contenu, ses liens, et ses
 * données structurées. C'est exactement ce que ce fichier produit, avec les
 * classes du site pour que le passage de l'un à l'autre ne se voie pas.
 */

/** Même valeur que la vue d'accueil : les deux paginations doivent coïncider. */
const PAGE_SIZE = 12;

const HOME_DESCRIPTION =
  'Des idées de sorties avec des enfants partout en France : spectacles, parcs, ' +
  'musées et ateliers, proposés par des parents et vérifiés par une équipe de modération.';

/** Le numéro de page demandé, ramené à quelque chose de sensé. */
export function pageOf(query: unknown): number {
  const raw = Number(typeof query === 'string' ? query : 1);
  return Number.isInteger(raw) && raw >= 1 ? raw : 1;
}

/** Une vignette de l'accueil, calquée sur `components/EventCard.vue`. */
function eventCard(event: PublicEvent, from: string): string {
  const badges = [
    `<span class="badge price">${escapeHtml(priceLabel(event))}</span>`,
    shortAgeLabel(event) ? `<span class="badge">${escapeHtml(shortAgeLabel(event)!)}</span>` : '',
    event.setting ? `<span class="badge">${escapeHtml(SETTING_LABELS[event.setting])}</span>` : '',
    `<span class="badge">${escapeHtml(event.category.name)}</span>`,
  ].filter(Boolean);

  const photo = event.photoUrl
    ? `<img src="${escapeHtml(event.photoUrl)}" alt="${escapeHtml(event.title)}" class="photo" loading="lazy" />`
    : '<div class="photo placeholder">🎠</div>';

  return `<a href="/sorties/${event.id}" class="event-card card">
        ${photo}
        <div class="body">
          <div class="badges">${badges.join('')}</div>
          <h3>${escapeHtml(event.title)}</h3>
          <div class="muted">${escapeHtml(event.venue.name)} · ${escapeHtml(event.venue.city)}</div>
          <div class="muted">📅 ${escapeHtml(cardDateLabel(event, from))}</div>
        </div>
      </a>`;
}

/**
 * Les liens de pagination.
 *
 * Ce sont eux qui font exister les pages 2 et suivantes pour un robot : sans
 * `<a href>`, une liste paginée par un bouton s'arrête à sa première page, et
 * tout ce qu'elle contenait au-delà reste introuvable.
 */
function pagination(page: number, totalPages: number, path = '/'): string {
  if (totalPages <= 1) return '';
  const href = (n: number) => (n === 1 ? path : `${path}?page=${n}`);
  const previous =
    page > 1 ? `<a class="btn ghost small" href="${href(page - 1)}">← Précédent</a>` : '';
  const next =
    page < totalPages ? `<a class="btn ghost small" href="${href(page + 1)}">Suivant →</a>` : '';
  return `<nav class="pagination">
        ${previous}
        <span class="muted">Page ${page} / ${totalPages}</span>
        ${next}
      </nav>`;
}

async function homePage(
  base: string,
  page: number,
): Promise<{ meta: PageMeta; body: string; status: number }> {
  const from = today();
  const [{ events, total }, areas] = await Promise.all([
    listPublicEvents(page, PAGE_SIZE),
    listAreas(),
  ]);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const list = events.length
    ? `<div class="event-grid">
      ${events.map((e) => eventCard(e, from)).join('\n      ')}
    </div>`
    : '<div class="empty"><p>Aucune sortie à afficher pour le moment. 🧸</p></div>';

  const body = `<div class="container page">
    <div class="hero-banner">
      <h1>Où sort-on avec les enfants ce week-end ?</h1>
      <p>
        Des idées de sorties partout en France, proposées par des parents et
        vérifiées par notre équipe de modération.
      </p>
    </div>
    ${areaLinks(areas)}
    ${list}
    ${pagination(page, totalPages)}
  </div>`;

  const suffix = page > 1 ? ` — page ${page}` : '';
  return {
    // Une page de pagination au-delà de la dernière n'a rien à montrer : elle
    // doit le dire, sinon `?page=900` est une page valide de plus, et un robot
    // en essaiera mille.
    status: page > 1 && events.length === 0 ? 404 : 200,
    meta: {
      title: `Sorties avec les enfants${suffix} — ${SITE_NAME}`,
      description: HOME_DESCRIPTION,
      path: page > 1 ? `/?page=${page}` : '/',
      noindex: page > 1 && events.length === 0,
      jsonLd: [websiteJsonLd(base), itemListJsonLd(base, events, (page - 1) * PAGE_SIZE)],
    },
    body,
  };
}

/**
 * Les zones, en liens.
 *
 * Une page de zone n'est atteignable que si quelque chose y mène : sans ce
 * bloc, `/sorties/nancy` n'existerait que dans le sitemap, et un sitemap
 * signale une page, il ne lui donne pas de poids. `except` évite qu'une zone
 * pointe vers elle-même.
 */
function areaLinks(areas: Area[], except?: string): string {
  const others = areas.filter((a) => a.slug !== except);
  if (!others.length) return '';
  const links = others
    .map((a) => `<a class="badge" href="/sorties/${escapeHtml(a.slug)}">${escapeHtml(a.name)}</a>`)
    .join('\n        ');
  return `<nav class="areas">
        <h2>Où cherchez-vous ?</h2>
        <div class="badges">
        ${links}
        </div>
      </nav>`;
}

/**
 * La page d'une zone : « Le Havre : où sortir avec les enfants ? »
 *
 * C'est la page qui répond à la requête réellement tapée. Personne ne cherche
 * « sortie enfant » tout court — on cherche « sortie enfant Nancy », et jusqu'ici
 * le site n'avait aucune page à opposer à cette question : l'accueil parlait
 * d'Île-de-France, et une fiche isolée ne parle que d'elle.
 *
 * Le titre place le nom de la zone en tête, et sans préposition : « à Nancy »,
 * « au Havre », « en Île-de-France » ne se déduisent pas d'un nom, et une
 * préposition fausse dans un titre se voit dans les résultats de recherche.
 */
async function areaPage(
  base: string,
  area: Area,
  page: number,
): Promise<{ meta: PageMeta; body: string; status: number }> {
  const from = today();
  const [{ events, total }, areas] = await Promise.all([
    listPublicEvents(page, PAGE_SIZE, area),
    listAreas(),
  ]);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const path = `/sorties/${area.slug}`;

  const list = events.length
    ? `<div class="event-grid">
      ${events.map((e) => eventCard(e, from)).join('\n      ')}
    </div>`
    : `<div class="empty"><p>Aucune sortie n'est programmée dans cette zone pour le moment. 🧸</p>
      <p><a href="/proposer">Proposez la vôtre</a> ou <a href="/">voyez les autres régions</a>.</p></div>`;

  const body = `<div class="container page">
    <div class="hero-banner">
      <h1>${escapeHtml(area.name)} : où sortir avec les enfants ?</h1>
      <p>${escapeHtml(area.intro)}</p>
    </div>
    ${list}
    ${pagination(page, totalPages, path)}
    ${areaLinks(areas, area.slug)}
  </div>`;

  const suffix = page > 1 ? ` — page ${page}` : '';
  return {
    // Une zone vide reste une page valide : elle est annoncée dans le menu, elle
    // se remplira. C'est seulement au-delà de la dernière page qu'il n'y a rien.
    status: page > 1 && events.length === 0 ? 404 : 200,
    meta: {
      title: `${area.name} : sorties avec les enfants${suffix} — ${SITE_NAME}`,
      description: truncate(area.intro),
      path: page > 1 ? `${path}?page=${page}` : path,
      noindex: page > 1 && events.length === 0,
      jsonLd: [
        itemListJsonLd(base, events, (page - 1) * PAGE_SIZE),
        {
          '@context': 'https://schema.org',
          '@type': 'BreadcrumbList',
          itemListElement: [
            { '@type': 'ListItem', position: 1, name: 'Sorties', item: `${base}/` },
            { '@type': 'ListItem', position: 2, name: area.name, item: `${base}${path}` },
          ],
        },
      ],
    },
    body,
  };
}

/** Une ligne du panneau d'information de la fiche. */
function infoRow(label: string, value: string): string {
  return `<div><dt>${escapeHtml(label)}</dt><dd>${value}</dd></div>`;
}

function eventBody(event: PublicEvent, from: string): string {
  const rows = [
    infoRow('Prix', escapeHtml(priceLabel(event))),
    ageLabel(event) ? infoRow('Âges', escapeHtml(ageLabel(event)!)) : '',
    infoRow(
      'Dates',
      event.isPermanent || !event.dateStart || !event.dateEnd
        ? "Toute l'année"
        : `Du ${escapeHtml(longDate(event.dateStart))} au ${escapeHtml(longDate(event.dateEnd))}`,
    ),
    event.dates.length
      ? infoRow(
          'Jours de représentation',
          `<ul class="days">${event.dates
            .map((d) => `<li${d < from ? ' class="passe"' : ''}>${escapeHtml(dayLabel(d))}</li>`)
            .join('')}</ul>`,
        )
      : '',
    event.setting ? infoRow('Cadre', escapeHtml(SETTING_LABELS[event.setting])) : '',
    infoRow('Catégorie', escapeHtml(event.category.name)),
    infoRow(
      'Lieu',
      `<strong>${escapeHtml(event.venue.name)}</strong><br />` +
        `${escapeHtml(event.venue.address)}<br />` +
        `${escapeHtml(event.venue.postalCode)} ${escapeHtml(event.venue.city)}`,
    ),
    event.openTime && event.closeTime
      ? infoRow(
          "Horaires d'ouverture",
          `${escapeHtml(event.openTime)} – ${escapeHtml(event.closeTime)}`,
        )
      : '',
  ].filter(Boolean);

  const photo = event.photoUrl
    ? `<img src="${escapeHtml(event.photoUrl)}" alt="${escapeHtml(event.title)}" class="hero" />`
    : '';
  const prochaine = nextDate(event, from);

  return `<div class="container page event-detail">
    <h1>${escapeHtml(event.title)}</h1>
    <p class="muted">Proposée par ${escapeHtml(event.authorName)}</p>
    ${photo}
    <div class="detail-grid">
      <div>
        <h2>Description</h2>
        <p style="white-space: pre-line">${escapeHtml(event.description)}</p>
        ${prochaine ? `<p class="next">Prochaine date : ${escapeHtml(dayLabel(prochaine))}</p>` : ''}
      </div>
      <aside class="info-panel card">
        ${rows.join('\n        ')}
      </aside>
    </div>
  </div>`;
}

function eventPage(base: string, event: PublicEvent): { meta: PageMeta; body: string } {
  const from = today();
  const path = `/sorties/${event.id}`;
  const url = `${base}${path}`;
  const image = event.photoUrl ? absolute(base, event.photoUrl) : null;

  // « Titre à Ville » : la ville est ce qu'on ajoute à une recherche de sortie,
  // et elle tient dans ce qu'un résultat affiche.
  const title = truncate(`${event.title} à ${event.venue.city} — ${SITE_NAME}`, 70);

  return {
    meta: {
      title,
      description: truncate(event.description),
      path,
      image,
      ogType: 'article',
      jsonLd: [
        eventJsonLd(event, url, image, from),
        breadcrumbJsonLd(base, event, url),
      ],
    },
    body: eventBody(event, from),
  };
}

/**
 * Ce que reçoit une adresse qui ne mène à rien.
 *
 * Le corps reste celui de l'application — le visiteur qui a le droit de voir
 * une sortie non encore approuvée la verra apparaître dès que Vue aura
 * interrogé l'API avec son cookie. Le code 404, lui, s'adresse aux moteurs :
 * sans lui, toute adresse inventée serait une page valide de plus.
 */
function notFoundPage(): { meta: PageMeta; body: string } {
  return {
    meta: {
      title: `Page introuvable — ${SITE_NAME}`,
      description: "Cette page n'existe pas ou n'est plus disponible.",
      path: '/',
      noindex: true,
    },
    body: `<div class="container page">
    <h1>Page introuvable</h1>
    <p>Cette page n'existe pas, ou elle n'est plus publiée.</p>
    <p><a href="/">Retour aux sorties</a></p>
  </div>`,
  };
}

/** Une page de l'application qui ne s'adresse qu'à ses utilisateurs connectés. */
function privatePage(path: string): { meta: PageMeta; body: string } {
  return {
    meta: {
      title: SITE_NAME,
      description: HOME_DESCRIPTION,
      path,
      noindex: true,
    },
    body: '<div class="container page"></div>',
  };
}

const EVENT_PATH = /^\/sorties\/(\d+)\/?$/;
/** Même espace d'adresses que les fiches, d'où le slug non numérique imposé. */
const AREA_PATH = /^\/sorties\/([a-z0-9][a-z0-9-]*)\/?$/;

/** Le document à servir pour un chemin donné. */
export async function renderPage(
  base: string,
  pathname: string,
  query: Record<string, unknown>,
): Promise<RenderedPage> {
  let status = 200;
  let page: { meta: PageMeta; body: string };

  const eventMatch = EVENT_PATH.exec(pathname);
  if (pathname === '/') {
    const home = await homePage(base, pageOf(query.page));
    page = home;
    status = home.status;
  } else if (isPrivatePath(pathname)) {
    page = privatePage(pathname);
  } else if (eventMatch) {
    const event = await findPublicEvent(Number(eventMatch[1]));
    if (event) {
      page = eventPage(base, event);
    } else {
      page = notFoundPage();
      status = 404;
    }
  } else if (AREA_PATH.test(pathname)) {
    const area = await findArea(AREA_PATH.exec(pathname)![1]);
    if (area) {
      const rendered = await areaPage(base, area, pageOf(query.page));
      page = rendered;
      status = rendered.status;
    } else {
      page = notFoundPage();
      status = 404;
    }
  } else {
    page = notFoundPage();
    status = 404;
  }

  return { status, head: buildHead(base, page.meta), body: page.body };
}
