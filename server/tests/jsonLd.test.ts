/**
 * Les données structurées d'une fiche, et les champs que Google réclamait.
 *
 * La Search Console signalait quatre absences non critiques sur les `Event` :
 * `organizer`, `offers.validFrom`, `image` et `performer`. Deux se remplissent
 * avec ce que la base sait déjà ; les deux autres ne se remplissent qu'en
 * inventant, et ce test fixe aussi cette limite — pour qu'on ne « corrige »
 * pas un jour l'avertissement en écrivant une contrevérité.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { eventJsonLd } from '../src/seo/jsonld';
import type { PublicEvent } from '../src/seo/query';

const AUJOURDHUI = '2026-09-19';

function sortie(overrides: Partial<PublicEvent> = {}): PublicEvent {
  return {
    id: 12,
    title: 'Atelier modelage',
    description: 'Les mains dans la terre.',
    sourceUrl: null,
    sourceUrlSignal: null,
    isFree: false,
    price: 8,
    photoUrl: '/uploads/12.jpg',
    ageMin: 3,
    ageMax: 6,
    isPermanent: false,
    dateStart: '2026-10-10',
    dateEnd: '2026-10-10',
    dates: [],
    openTime: '14:30',
    closeTime: '16:00',
    setting: 'INDOOR',
    createdAt: new Date('2026-09-01T09:00:00.000Z'),
    authorName: 'Camille',
    category: { id: 1, name: 'Atelier' },
    venue: {
      name: 'Médiathèque des Lilas',
      address: '1 rue des Lilas',
      city: 'Les Lilas',
      postalCode: '93260',
      lat: 48.88,
      lng: 2.42,
    },
    ...overrides,
  };
}

function ld(overrides: Partial<PublicEvent> = {}) {
  return eventJsonLd(sortie(overrides), 'https://exemple.fr/sorties/12', null, AUJOURDHUI);
}

test("l'organisateur annoncé est le lieu", () => {
  assert.deepEqual(ld().organizer, {
    '@type': 'Organization',
    name: 'Médiathèque des Lilas',
  });
});

test("le site de l'organisateur n'est donné que si le lien est bien le sien", () => {
  const sien = ld({ sourceUrl: 'https://mediatheque.fr/atelier', sourceUrlSignal: 'venue_domain' });
  assert.equal((sien.organizer as Record<string, unknown>).url, 'https://mediatheque.fr/atelier');

  // Trouvé par une recherche : ce peut être un agrégateur, donc pas son site.
  const trouve = ld({ sourceUrl: 'https://agregateur.fr/atelier', sourceUrlSignal: 'search' });
  assert.equal((trouve.organizer as Record<string, unknown>).url, undefined);
});

test("l'offre dit depuis quand le tarif vaut : le jour de publication de la fiche", () => {
  const offers = ld().offers as Record<string, unknown>;
  assert.equal(offers.price, 8);
  assert.equal(offers.validFrom, '2026-09-01T09:00:00.000Z');
});

test('une sortie au tarif inconnu ne porte toujours pas d\'offre', () => {
  assert.equal(ld({ isFree: false, price: -1 }).offers, undefined);
});

test("aucun interprète n'est inventé", () => {
  assert.equal(ld().performer, undefined);
});

test("un lieu permanent reste un Place, sans organisateur ni offre", () => {
  const parc = ld({ dateStart: null, dateEnd: null, dates: [], isPermanent: true });
  assert.deepEqual(parc['@type'], ['Place', 'TouristAttraction']);
  assert.equal(parc.organizer, undefined);
  assert.equal(parc.offers, undefined);
});
