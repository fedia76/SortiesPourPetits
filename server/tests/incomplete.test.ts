/**
 * Les deux conventions d'un import incomplet, et les deux tables qui en
 * dérivaient chacune de leur côté.
 *
 * Un programme d'import qui n'a pas tout trouvé propose quand même la sortie,
 * avec une valeur convenue à la place de ce qui manque : (0, 0) pour une
 * position inconnue, un tarif négatif pour un prix introuvable. Le serveur
 * refuse alors l'approbation, et le client affiche « à compléter ».
 *
 * Deux lectures de la même règle, dans deux fichiers, et elles ne disaient pas
 * la même chose : `Number(null)` vaut **zéro**, donc le serveur répondait
 * « tarif connu » pour une sortie payante sans prix, là où le client répondait
 * l'inverse. Le schéma d'entrée interdit aujourd'hui de créer une telle fiche,
 * si bien que le désaccord ne se voyait sur aucune sortie vivante — il se
 * serait vu sur la première ligne écrite autrement, par une reprise de données
 * ou une migration, et c'est le serveur qui garde l'approbation.
 *
 * Ce fichier fixe la table de vérité que les deux copies doivent suivre.
 * L'autre est dans `client/src/types.ts`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { RejectionCode } from '@prisma/client';

import { UNKNOWN_PRICE, hasCoordinates, hasPrice } from '../src/lib/incomplete';
import { moderateSchema } from '../src/lib/validators';
import { REJECTION_MEANINGS } from '../src/lib/rejectionCodes';

// ────────────────────────────────────────────────────────────────── le tarif

const TARIFS: { cas: string; event: { isFree: boolean; price: unknown }; connu: boolean }[] = [
  { cas: 'gratuite', event: { isFree: true, price: null }, connu: true },
  { cas: 'gratuite avec un prix résiduel', event: { isFree: true, price: 8 }, connu: true },
  { cas: 'payante à 8 €', event: { isFree: false, price: 8 }, connu: true },
  { cas: 'payante à 0 €', event: { isFree: false, price: 0 }, connu: true },
  // Le cas du désaccord : le serveur répondait « connu ».
  { cas: 'payante sans prix', event: { isFree: false, price: null }, connu: false },
  { cas: 'payante, prix absent', event: { isFree: false, price: undefined }, connu: false },
  { cas: 'tarif que l’import n’a pas su lire', event: { isFree: false, price: UNKNOWN_PRICE }, connu: false },
];

for (const { cas, event, connu } of TARIFS) {
  test(`tarif — une sortie ${cas} : ${connu ? 'connu' : 'à compléter'}`, () => {
    assert.equal(hasPrice(event), connu);
  });
}

test('le tarif convenu pour « je ne sais pas » est négatif, donc jamais confondu avec la gratuité', () => {
  assert.ok(UNKNOWN_PRICE < 0);
  assert.equal(hasPrice({ isFree: false, price: UNKNOWN_PRICE }), false);
  assert.equal(hasPrice({ isFree: true, price: UNKNOWN_PRICE }), true);
});

test('un Decimal de Prisma se lit comme un nombre', () => {
  // La colonne est un DECIMAL : `event.price` arrive en objet, pas en nombre.
  const decimal = { toString: () => '12.50', valueOf: () => '12.50' };
  assert.equal(hasPrice({ isFree: false, price: decimal }), true);
});

// ─────────────────────────────────────────────────────────────── la position

test('position — (0, 0) est la convention « non géocodé »', () => {
  assert.equal(hasCoordinates({ lat: 0, lng: 0 }), false);
  assert.equal(hasCoordinates({ lat: 48.85, lng: 2.35 }), true);
  // Une seule coordonnée nulle est une position valable : le méridien de
  // Greenwich passe en France, et l'équateur n'est pas la question.
  assert.equal(hasCoordinates({ lat: 49.49, lng: 0 }), true);
  assert.equal(hasCoordinates({ lat: 0, lng: 2.35 }), true);
});

test('position — les Decimal de Prisma se lisent aussi', () => {
  const zero = { valueOf: () => '0' };
  assert.equal(hasCoordinates({ lat: zero, lng: zero }), false);
});

// ──────────────────────────────────── les motifs de refus, une seule liste

test('le schéma de modération accepte tous les motifs de la base', () => {
  // Cette liste était recopiée à la main dans `validators.ts`. Un onzième
  // motif passait la migration, s'affichait dans la console, et se faisait
  // refuser en 400 par une enum oubliée.
  for (const code of Object.values(RejectionCode)) {
    const lu = moderateSchema.safeParse({ action: 'reject', code });
    assert.ok(lu.success, `le motif ${code} doit être accepté`);
  }
});

test('et rien d’autre', () => {
  assert.equal(moderateSchema.safeParse({ action: 'reject', code: 'PAS_UN_MOTIF' }).success, false);
});

test('le motif reste facultatif : un refus ne peut pas échouer faute de case', () => {
  assert.ok(moderateSchema.safeParse({ action: 'reject', reason: 'Hors sujet' }).success);
  assert.ok(moderateSchema.safeParse({ action: 'approve' }).success);
});

test('la table des significations couvre exactement l’enum de la base', () => {
  assert.deepEqual(
    REJECTION_MEANINGS.map((m) => m.code).sort(),
    Object.values(RejectionCode).sort(),
  );
});
