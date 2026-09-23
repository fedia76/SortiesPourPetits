/**
 * Les règles d'entrée du site — mille lignes de schémas, et aucun test.
 *
 * Ce fichier n'essaie pas de les couvrir toutes : il verrouille ce qui décide
 * qu'une requête est refusée proprement plutôt que de tomber plus loin, et les
 * invariants métier qu'on relit rarement — une tranche d'âge inversée, des
 * dates de représentation hors période.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  eventInputSchema,
  searchSchema,
  parseSeedUrls,
  checkScraperMode,
  evalCorpusSchema,
  scraperRunSchema,
  moderationQueueSchema,
} from '../src/lib/validators';

/** Une sortie valide, à laquelle chaque test ne change que ce qui l'intéresse. */
function sortie(champs: Record<string, unknown> = {}) {
  return {
    title: 'Atelier poterie',
    description: 'Un atelier où les enfants façonnent leur premier bol en argile.',
    isFree: true,
    isPermanent: false,
    dateStart: '2026-10-01',
    dateEnd: '2026-10-31',
    categoryId: 1,
    venue: {
      name: 'Maison des arts',
      address: '1 rue des Lilas',
      city: 'Rouen',
      postalCode: '76000',
      lat: 49.44,
      lng: 1.09,
    },
    ...champs,
  };
}

const refus = (champs: Record<string, unknown>) => {
  const lu = eventInputSchema.safeParse(sortie(champs));
  assert.equal(lu.success, false, 'aurait dû être refusé');
  return lu.success ? '' : lu.error.issues[0].message;
};

// ───────────────────────────────────────────────────── les dates au calendrier

test('une sortie ordinaire passe', () => {
  assert.ok(eventInputSchema.safeParse(sortie()).success);
});

test('un mois ou un jour impossible est refusé, pas envoyé à la base', () => {
  // La forme était le seul contrôle : `new Date('2026-13-45')` est invalide,
  // Prisma refuse de l'écrire, et le visiteur recevait 500 pour une faute de
  // frappe.
  assert.match(refus({ dateStart: '2026-13-01' }), /Date invalide/);
  assert.match(refus({ dateEnd: '2026-10-45' }), /Date invalide/);
  assert.match(refus({ dateStart: '2026-00-10' }), /Date invalide/);
});

test('le 31 février est refusé, et non décalé en silence', () => {
  // Pire que l'erreur : JavaScript reporte au 3 mars, et la sortie partait en
  // base avec une date que personne n'avait saisie.
  assert.match(refus({ dateStart: '2026-02-31', dateEnd: '2026-03-15' }), /Date invalide/);
});

test('le 29 février d’une année bissextile passe', () => {
  assert.ok(
    eventInputSchema.safeParse(sortie({ dateStart: '2024-02-29', dateEnd: '2024-03-01' })).success,
  );
  assert.match(refus({ dateStart: '2026-02-29', dateEnd: '2026-03-01' }), /Date invalide/);
});

test('les jours de représentation sont vérifiés comme les autres', () => {
  assert.match(refus({ dates: ['2026-10-05', '2026-10-32'] }), /Date invalide/);
});

test('les bornes de recherche aussi', () => {
  assert.equal(searchSchema.safeParse({ from: '2026-02-30' }).success, false);
  assert.equal(searchSchema.safeParse({ to: '2026-13-01' }).success, false);
  assert.ok(searchSchema.safeParse({ from: '2026-02-28', to: '2026-03-01' }).success);
});

// ─────────────────────────────────────────────────── les invariants d'une fiche

test('une tranche d’âge inversée est refusée', () => {
  assert.match(refus({ ageMin: 10, ageMax: 3 }), /inversée/);
  assert.ok(eventInputSchema.safeParse(sortie({ ageMin: 3, ageMax: 10 })).success);
  // Une seule borne reste valable : « à partir de 3 ans ».
  assert.ok(eventInputSchema.safeParse(sortie({ ageMin: 3 })).success);
});

test('une date de fin qui précède le début est refusée', () => {
  assert.match(refus({ dateStart: '2026-10-31', dateEnd: '2026-10-01' }), /précède/);
});

test('une sortie payante doit dire son prix', () => {
  assert.match(refus({ isFree: false }), /Indiquez un prix/);
  assert.ok(eventInputSchema.safeParse(sortie({ isFree: false, price: 8 })).success);
});

test('le tarif convenu « je ne sais pas » est accepté à l’entrée', () => {
  // C'est la modération qui le refuse à l'approbation, pas le schéma : sinon
  // un import perdrait la sortie au lieu de la proposer à compléter.
  assert.ok(eventInputSchema.safeParse(sortie({ isFree: false, price: -1 })).success);
  assert.match(refus({ isFree: false, price: -2 }), /./);
});

test('une sortie non permanente doit porter ses deux bornes', () => {
  assert.match(refus({ dateStart: null }), /date de début/);
  assert.match(refus({ dateEnd: null }), /date de fin/);
});

test('une sortie permanente n’a ni bornes ni représentations', () => {
  assert.ok(
    eventInputSchema.safeParse(sortie({ isPermanent: true, dateStart: null, dateEnd: null })).success,
  );
  assert.match(
    refus({ isPermanent: true, dateStart: null, dateEnd: null, dates: ['2026-10-05'] }),
    /permanente/,
  );
});

test('une représentation hors période est refusée', () => {
  assert.match(refus({ dates: ['2026-11-05'] }), /sort de la période/);
  assert.ok(eventInputSchema.safeParse(sortie({ dates: ['2026-10-05'] })).success);
});

test('une heure de fermeture avant l’ouverture est refusée', () => {
  assert.match(refus({ openTime: '18:00', closeTime: '10:00' }), /précéder/);
  assert.match(refus({ openTime: '25:00' }), /Heure invalide/);
  assert.ok(eventInputSchema.safeParse(sortie({ openTime: '10:00', closeTime: '18:00' })).success);
});

test('un lien qui n’est pas une URL est refusé', () => {
  assert.match(refus({ sourceUrl: 'pas-une-url' }), /URL invalide/);
  assert.ok(eventInputSchema.safeParse(sortie({ sourceUrl: 'https://exemple.fr/x' })).success);
  // La chaîne vide vaut « pas de lien », pas « lien invalide » : c'est ce que
  // rend un champ de formulaire qu'on n'a pas rempli.
  assert.ok(eventInputSchema.safeParse(sortie({ sourceUrl: '' })).success);
});

test('une position hors du globe est refusée', () => {
  assert.match(refus({ venue: { ...sortie().venue, lat: 95 } }), /./);
  assert.match(refus({ venue: { ...sortie().venue, lng: -200 } }), /./);
  // (0, 0) reste accepté : c'est la convention « adresse à compléter ».
  assert.ok(
    eventInputSchema.safeParse(sortie({ venue: { ...sortie().venue, lat: 0, lng: 0 } })).success,
  );
});

// ───────────────────────────────────────────── la configuration d'une recherche

test('les URL de départ se lisent par lignes ou par virgules', () => {
  const { urls, invalid } = parseSeedUrls('https://a.fr/x\n  https://b.fr/y , https://c.fr/z  ');
  assert.deepEqual(urls, ['https://a.fr/x', 'https://b.fr/y', 'https://c.fr/z']);
  assert.equal(invalid, null);
});

test('une URL de départ fautive est nommée', () => {
  assert.equal(parseSeedUrls('https://a.fr\nftp://b.fr').invalid, 'ftp://b.fr');
  assert.equal(parseSeedUrls('pas une url').invalid, 'pas une url');
  assert.equal(parseSeedUrls('').invalid, null);
});

test('le mode « site » réclame au moins une adresse', () => {
  assert.match(checkScraperMode({ mode: 'site', seedUrls: '' }) ?? '', /au moins une adresse/);
  assert.equal(checkScraperMode({ mode: 'site', seedUrls: 'https://a.fr' }), null);
  // En mode « recherche », aucune adresse n'est attendue…
  assert.equal(checkScraperMode({ mode: 'recherche', seedUrls: '' }), null);
  // …mais celles qui sont là doivent tenir debout.
  assert.match(checkScraperMode({ mode: 'recherche', seedUrls: 'n’importe quoi' }) ?? '', /invalide/);
});

// ───────────────────────────── le corpus servi au worker pour l'entraînement

test('le corpus étiqueté se pagine par curseur, avec des bornes', () => {
  const vide = evalCorpusSchema.parse({});
  assert.equal(vide.after, 0);
  assert.equal(vide.limit, 10);

  // Cent soixante pages gelées font des dizaines de mégaoctets : une tranche
  // trop large ferait tomber la requête sur un VPS à quatre gigaoctets.
  assert.equal(evalCorpusSchema.safeParse({ limit: 500 }).success, false);
  assert.equal(evalCorpusSchema.safeParse({ limit: 0 }).success, false);
  assert.equal(evalCorpusSchema.safeParse({ after: -1 }).success, false);
});

test('le curseur accepte une chaîne, comme tout ce qui vient du réseau', () => {
  const parsed = evalCorpusSchema.parse({ after: '42', limit: '5' });
  assert.equal(parsed.after, 42);
  assert.equal(parsed.limit, 5);
});


// ───────────────────────────────────────────── les deux scrapers

test('une exécution sans scraper précisé est une exécution du pipeline', () => {
  const run = scraperRunSchema.parse({ submit: true });
  assert.equal(run.engine, 'pipeline');
  assert.equal(run.pilot, undefined);
});

test('l\'agent accepte un pilote au format d\'OpenRouter, ou aucun', () => {
  assert.equal(scraperRunSchema.parse({ engine: 'agent', pilot: 'z-ai/glm-5.3-flash' }).pilot, 'z-ai/glm-5.3-flash');
  assert.equal(scraperRunSchema.parse({ engine: 'agent', pilot: 'z-ai/glm-5.3-flash:floor' }).pilot, 'z-ai/glm-5.3-flash:floor');
  assert.equal(scraperRunSchema.parse({ engine: 'agent', pilot: '' }).pilot, '');
  assert.equal(scraperRunSchema.safeParse({ engine: 'agent', pilot: 'glm-flash' }).success, false);
});

test('un pilote sur une exécution du pipeline est refusé', () => {
  assert.equal(scraperRunSchema.safeParse({ pilot: 'z-ai/glm-5.3-flash' }).success, false);
});

test('un scraper inconnu est refusé', () => {
  assert.equal(scraperRunSchema.safeParse({ engine: 'autre' }).success, false);
});

test('la file de modération se filtre par scraper', () => {
  assert.equal(moderationQueueSchema.parse({ origin: 'agent' }).origin, 'agent');
  assert.equal(moderationQueueSchema.parse({ origin: 'pipeline', configId: '3' }).configId, 3);
  assert.equal(moderationQueueSchema.safeParse({ origin: 'robot' }).success, false);
});
