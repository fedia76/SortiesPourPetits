/**
 * La chasse, éprouvée sans base de données.
 *
 * Ce fichier ne vérifie pas des cas limites : il verrouille les deux règles qui
 * décident si le corpus de l'étage 2 vaut quelque chose, et dont aucune ne se
 * voit à l'œil nu dans un tableau de bord.
 *
 *   * une précoche vide **reste vide**. Traduire « inconnu » en « agenda »
 *     ferait entrer au corpus le repli du pipeline au lieu de ce que la page
 *     est — et la mesure de l'étage 2 vérifierait alors que l'étage 2 fait ce
 *     qu'il fait ;
 *   * une étiquette qui reprend la précoche **se distingue** d'une étiquette
 *     qui la corrige. Sans cette distinction, un corpus rempli en cliquant
 *     « tout valider » mesurerait la brique contre elle-même, et son taux
 *     monterait tout seul.
 *
 * Exécution : `npm test`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { comptesChasse, natureProposee, origineDe, soucheCorpus } from '../src/lib/evalHunt';

// ─────────────────────────────────────────────────── ce que la brique propose

test('les trois natures de classify deviennent celles du corpus', () => {
  assert.equal(natureProposee('agenda'), 'AGENDA');
  assert.equal(natureProposee('sortie'), 'SORTIE');
  assert.equal(natureProposee('programme'), 'PROGRAMME');
});

test('« inconnu » ne propose rien — et surtout pas « agenda »', () => {
  // Le pipeline traite « inconnu » en agenda, et il a raison de le faire :
  // l'erreur n'y est pas symétrique. Mais c'est une décision d'orchestration,
  // et la recopier ici écrirait au corpus ce que le pipeline fait au lieu de
  // ce que la page est.
  assert.equal(natureProposee('inconnu'), null);
  assert.equal(natureProposee(''), null);
  assert.equal(natureProposee('  '), null);
});

test('une réponse inattendue ne propose rien non plus', () => {
  assert.equal(natureProposee('billetterie'), null);
});

// ──────────────────────────────────────────────── d'où vient chaque étiquette

test('sans précoche, l’humain a tranché seul', () => {
  assert.equal(origineDe(null, 'AGENDA'), 'SAISIE');
});

test('une précoche laissée passer ne contredit rien', () => {
  assert.equal(origineDe('AGENDA', 'AGENDA'), 'NON_CONTREDIT');
});

test('une précoche corrigée est l’étiquette la plus forte', () => {
  // Indépendante de ce que la brique pensait : c'est la seule des trois dont
  // un taux calculé dessus mesure autre chose que le modèle lui-même.
  assert.equal(origineDe('AGENDA', 'SORTIE'), 'CORRIGE');
  assert.equal(origineDe('SORTIE', 'AUTRE'), 'CORRIGE');
});

// ─────────────────────────────────────────────── ce qu'une chasse doit encore

test('une chasse compte ce qu’elle doit encore à un humain', () => {
  const comptes = comptesChasse([
    { decision: 'EN_ATTENTE', proposed: 'AGENDA', error: '' },
    { decision: 'EN_ATTENTE', proposed: null, error: '' },
    { decision: 'RETENUE', proposed: 'SORTIE', error: '' },
    { decision: 'ECARTEE', proposed: 'SORTIE', error: 'HTTP 403' },
  ]);
  assert.deepEqual(comptes, {
    total: 4,
    enAttente: 2,
    retenues: 1,
    ecartees: 1,
    indecises: 1,
    injoignables: 1,
  });
});

// ───────────────────────────────────── ce que le corpus doit à la brique

test('un corpus rempli en validant tout n’est plus indépendant', () => {
  // Dix pages, toutes acceptées telles quelles : le corpus a grossi, et il ne
  // mesure plus rien. C'est précisément ce que ce chiffre existe pour dire.
  const souche = soucheCorpus(Array.from({ length: 10 }, () => ({ origin: 'NON_CONTREDIT' as const })));
  assert.equal(souche.independance, 0);
  assert.equal(souche.nonContredits, 10);
});

test('les saisies et les corrections font l’indépendance', () => {
  const souche = soucheCorpus([
    { origin: 'SAISIE' },
    { origin: 'CORRIGE' },
    { origin: 'NON_CONTREDIT' },
    { origin: 'NON_CONTREDIT' },
  ]);
  assert.equal(souche.saisies, 1);
  assert.equal(souche.corriges, 1);
  assert.equal(souche.independance, 0.5);
});

test('un corpus vide n’a pas d’indépendance à annoncer', () => {
  // Zéro sur zéro vaut zéro en JavaScript, et un zéro affiché se lirait comme
  // « ce corpus ne vaut rien » alors qu'il n'y a rien à en dire.
  assert.equal(soucheCorpus([]).independance, null);
});
