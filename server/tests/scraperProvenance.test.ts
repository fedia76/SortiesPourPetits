/**
 * La filiation d'un run, éprouvée sans base de données.
 *
 * Deux écritures partent de ce calcul, et aucune des deux ne se relit :
 * les colonnes `agendaUrl` / `query` d'un run clos, qu'on n'ouvre que des mois
 * plus tard pour lire un rendement, et l'enrôlement des agendas au corpus du
 * banc, qui déclenche des captures. Une erreur ici ne se voit donc pas — elle
 * se découvre en constatant qu'un tableau est vide, ce qui est exactement
 * l'histoire de ce module.
 *
 * Exécution : `npm test`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { filiationOf, groupProvenance } from '../src/lib/scraperProvenance';
import type { TreeRow } from '../src/lib/scraperTree';

let seq = 0;
function ligne(kind: string, url: string | null, data: Record<string, unknown> = {}, stage = 'harvest'): TreeRow {
  return { seq: ++seq, stage, kind, level: 'info', url, message: null, data: JSON.stringify(data) };
}

/** Un agenda ouvert, lu, et dont on connaît les pages. */
function depouille(agenda: string, pages: string[], query = ''): TreeRow[] {
  return [
    ...(query
      ? [
          ligne('query', null, { query }, 'discover'),
          ligne('search_result', agenda, { query, title: '' }, 'discover'),
        ]
      : []),
    ligne('fetching', agenda),
    ligne('harvested', agenda, { agenda, links: pages.length, page_no: 1 }),
    // Une candidate porte l'agenda d'où elle vient : c'est cette piste-là,
    // et pas l'ordre des lignes, qui fait la filiation.
    ...pages.map((page) => ligne('candidate', page, { agenda, why: '' }, 'select')),
  ];
}

// ───────────────────────────────────────────────────────── d'où vient la page

test('une page tient de l’agenda qui la listait, et de la requête qui l’a remonté', () => {
  const { provenances } = filiationOf(
    depouille('https://agenda.fr/', ['https://a.fr/sortie'], 'sorties enfants'),
  );
  assert.deepEqual(provenances, [
    { url: 'https://a.fr/sortie', agendaUrl: 'https://agenda.fr/', query: 'sorties enfants' },
  ]);
});

test('les pages d’un même agenda se mettent à jour d’un seul IN', () => {
  const { provenances } = filiationOf(
    depouille('https://agenda.fr/', ['https://a.fr/1', 'https://a.fr/2']),
  );
  const groupes = groupProvenance(provenances);
  assert.equal(groupes.length, 1);
  assert.deepEqual(groupes[0].urls, ['https://a.fr/1', 'https://a.fr/2']);
});

test('une page dont on ne sait rien n’est pas écrite', () => {
  // Deux colonnes nulles le disent déjà ; l'écriture serait pure dépense.
  assert.deepEqual(groupProvenance([{ url: 'https://a.fr/1', agendaUrl: '', query: '' }]), []);
});

// ─────────────────────────────────────────── quels agendas le banc enrôle

test('un agenda dépouillé est enrôlé, une seule fois', () => {
  const { agendas } = filiationOf([
    ...depouille('https://agenda.fr/', ['https://a.fr/1']),
    // Sa page 2 : même agenda, la piste le dit. Un agenda paginé reste un.
    ligne('harvested', 'https://agenda.fr/?page=2', {
      agenda: 'https://agenda.fr/',
      links: 4,
      page_no: 2,
    }),
  ]);
  assert.deepEqual(agendas, ['https://agenda.fr/']);
});

test('ce que le run n’a pas lu n’est pas enrôlé', () => {
  // Trois façons de figurer dans l'arbre sans avoir été dépouillé, et aucune
  // ne donne une page dont le gel dirait quoi que ce soit : désigné sans être
  // ouvert, coupé par un plafond, injoignable. Les enrôler remplirait le
  // corpus de pages que personne ne peut étiqueter.
  const { agendas } = filiationOf([
    ligne('agenda_planned', 'https://jamais-ouvert.fr/', { title: 'Désigné' }, 'discover'),
    ligne('fetching', 'https://injoignable.fr/'),
    {
      seq: ++seq,
      stage: 'harvest',
      kind: 'error',
      level: 'error',
      url: 'https://injoignable.fr/',
      message: 'non dépouillé : 503',
      data: JSON.stringify({ agenda: 'https://injoignable.fr/', op: 'agenda' }),
    },
    ...depouille('https://lu.fr/', ['https://a.fr/1']),
  ]);
  assert.deepEqual(agendas, ['https://lu.fr/']);
});

test('un journal illisible ne fait perdre ni la filiation ni les agendas', () => {
  // Une ligne au JSON cassé est muette sur son origine ; les autres valent.
  const { provenances, agendas } = filiationOf([
    { seq: 1, stage: 'harvest', kind: 'harvested', level: 'info', url: null, message: null, data: '{cassé' },
    ...depouille('https://lu.fr/', ['https://a.fr/1']),
  ]);
  assert.deepEqual(agendas, ['https://lu.fr/']);
  assert.equal(provenances.length, 1);
});

test('un journal vide ne rend rien, et surtout pas une entrée vide', () => {
  const { provenances, agendas } = filiationOf([]);
  assert.deepEqual(provenances, []);
  assert.deepEqual(agendas, []);
});
