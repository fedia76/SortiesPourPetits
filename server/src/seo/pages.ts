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
import { findPublicEvent, listPublicEvents, type PublicEvent } from './query';
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
  'Des idées de sorties avec des enfants en Île-de-France : spectacles, parcs, ' +
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
function pagination(page: number, totalPages: number): string {
  if (totalPages <= 1) return '';
  const href = (n: number) => (n === 1 ? '/' : `/?page=${n}`);
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
  const { events, total } = await listPublicEvents(page, PAGE_SIZE);
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
        Des idées de sorties en Île-de-France, proposées par des parents et
        vérifiées par notre équipe de modération.
      </p>
    </div>
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
      title: `Sorties avec les enfants en Île-de-France${suffix} — ${SITE_NAME}`,
      description: HOME_DESCRIPTION,
      path: page > 1 ? `/?page=${page}` : '/',
      noindex: page > 1 && events.length === 0,
      jsonLd: [websiteJsonLd(base), itemListJsonLd(base, events, (page - 1) * PAGE_SIZE)],
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
    <p>Cette sortie n'existe pas, ou elle n'est plus publiée.</p>
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
  } else {
    page = notFoundPage();
    status = 404;
  }

  return { status, head: buildHead(base, page.meta), body: page.body };
}
