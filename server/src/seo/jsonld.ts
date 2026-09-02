import { hasCoordinates, hasPrice } from '../lib/incomplete';
import { SITE_NAME } from './meta';
import type { PublicEvent } from './query';

/**
 * Les données structurées schema.org.
 *
 * C'est ce qui distingue, pour un moteur, une page qui parle d'un spectacle
 * d'une page qui *est* un spectacle : la date, le lieu, le tarif et l'âge y
 * sont nommés au lieu d'être noyés dans du texte. Sans elles, un annuaire de
 * sorties reste une suite de pages ordinaires.
 *
 * Deux formes, parce qu'il y a deux natures de sorties. Un spectacle a une
 * date : c'est un `Event`, et `startDate` y est obligatoire. Un parc ou un
 * musée n'en a pas : ce serait un `Event` sans date, donc invalide, alors
 * qu'un `Place` le décrit exactement.
 */

const CONTEXT = 'https://schema.org';

/** Une adresse postale, telle que Google la lit. */
function postalAddress(venue: PublicEvent['venue']) {
  return {
    '@type': 'PostalAddress',
    streetAddress: venue.address,
    postalCode: venue.postalCode,
    addressLocality: venue.city,
    addressCountry: 'FR',
  };
}

/**
 * Les coordonnées, sauf quand elles valent (0, 0) : c'est la valeur convenue
 * pour « adresse non géocodée » (voir `lib/incomplete.ts`), et annoncer le
 * golfe de Guinée est pire que ne rien annoncer.
 */
function geo(venue: PublicEvent['venue']) {
  if (!hasCoordinates(venue)) return undefined;
  return { '@type': 'GeoCoordinates', latitude: venue.lat, longitude: venue.lng };
}

function place(event: PublicEvent) {
  return {
    '@type': 'Place',
    name: event.venue.name,
    address: postalAddress(event.venue),
    geo: geo(event.venue),
  };
}

/**
 * L'offre tarifaire — omise quand le tarif reste à compléter (prix négatif,
 * même convention) : annoncer « -1 € » vaudrait un signalement.
 */
function offers(event: PublicEvent, url: string) {
  if (!hasPrice(event)) return undefined;
  return {
    '@type': 'Offer',
    url,
    price: event.isFree ? 0 : event.price,
    priceCurrency: 'EUR',
    availability: 'https://schema.org/InStock',
  };
}

/** « 3-6 », « 3- », « 0-10 » — la façon dont schema.org écrit une tranche. */
function typicalAgeRange(event: PublicEvent): string | undefined {
  const { ageMin, ageMax } = event;
  if (ageMin !== null && ageMax !== null) return `${ageMin}-${ageMax}`;
  if (ageMin !== null) return `${ageMin}-`;
  if (ageMax !== null) return `0-${ageMax}`;
  return undefined;
}

/** `2026-09-20` + `14:30` → `2026-09-20T14:30`, que schema.org accepte tel quel. */
function withTime(day: string, time: string | null): string {
  return time ? `${day}T${time}` : day;
}

/**
 * Quand la sortie a-t-elle lieu ?
 *
 * Une sortie qui énumère ses jours en a souvent quinze, et schema.org veut une
 * seule date de début. C'est la prochaine séance à venir qui est la bonne
 * réponse : c'est celle qu'un visiteur cherche, et c'est elle que la fiche met
 * en avant. Quand tout est passé, on donne la dernière — la page décrit alors
 * un événement terminé, ce qui est la vérité.
 */
function occurrence(event: PublicEvent, from: string): { start: string; end: string } | null {
  if (event.dates.length) {
    const day = event.dates.find((d) => d >= from) ?? event.dates[event.dates.length - 1];
    return { start: withTime(day, event.openTime), end: withTime(day, event.closeTime) };
  }
  if (!event.dateStart) return null;
  return {
    start: withTime(event.dateStart, event.openTime),
    end: withTime(event.dateEnd ?? event.dateStart, event.closeTime),
  };
}

/** Retire les clés sans valeur : un `undefined` sérialisé en JSON-LD est du bruit. */
function compact<T extends Record<string, unknown>>(value: T): T {
  return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined)) as T;
}

/**
 * La sortie, décrite pour les moteurs. `image` et `url` doivent être absolues,
 * l'appelant s'en charge.
 */
export function eventJsonLd(
  event: PublicEvent,
  url: string,
  image: string | null,
  from: string,
): Record<string, unknown> {
  const shared = {
    '@context': CONTEXT,
    name: event.title,
    description: event.description,
    url,
    image: image ?? undefined,
    isAccessibleForFree: event.isFree,
    typicalAgeRange: typicalAgeRange(event),
  };
  const when = occurrence(event, from);

  // Sans date, la sortie est un lieu qu'on visite quand on veut : un parc, un
  // musée, une ferme pédagogique.
  if (!when) {
    return compact({
      ...shared,
      '@type': ['Place', 'TouristAttraction'],
      address: postalAddress(event.venue),
      geo: geo(event.venue),
      // Les horaires du modèle valent pour tous les jours d'ouverture.
      openingHours:
        event.openTime && event.closeTime
          ? `Mo-Su ${event.openTime}-${event.closeTime}`
          : undefined,
    });
  }

  return compact({
    ...shared,
    '@type': 'Event',
    startDate: when.start,
    endDate: when.end,
    eventStatus: 'https://schema.org/EventScheduled',
    eventAttendanceMode: 'https://schema.org/OfflineEventAttendanceMode',
    location: place(event),
    offers: offers(event, url),
  });
}

/** Le fil d'Ariane d'une fiche : l'accueil, puis elle. */
export function breadcrumbJsonLd(base: string, event: PublicEvent, url: string) {
  return {
    '@context': CONTEXT,
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Sorties', item: `${base}/` },
      { '@type': 'ListItem', position: 2, name: event.title, item: url },
    ],
  };
}

/** Le site lui-même, pour que son nom accompagne ses résultats. */
export function websiteJsonLd(base: string) {
  return {
    '@context': CONTEXT,
    '@type': 'WebSite',
    name: SITE_NAME,
    url: `${base}/`,
    inLanguage: 'fr-FR',
  };
}

/**
 * La liste de l'accueil. Elle ne répète pas les fiches — elle les désigne :
 * c'est leur page qui les décrit, et dupliquer les descriptions ici brouillerait
 * la piste au lieu de l'éclairer.
 */
export function itemListJsonLd(base: string, events: PublicEvent[], offset: number) {
  return {
    '@context': CONTEXT,
    '@type': 'ItemList',
    itemListElement: events.map((event, i) => ({
      '@type': 'ListItem',
      position: offset + i + 1,
      url: `${base}/sorties/${event.id}`,
      name: event.title,
    })),
  };
}
