/**
 * Lire un identifiant dans une adresse.
 *
 * Ce qui était en jeu : `PUT /api/events/abc` envoyait `NaN` à Prisma, qui
 * refuse, et le visiteur recevait « Erreur interne du serveur » pour une
 * adresse mal tapée — pendant que la trace partait au journal comme si le site
 * était tombé. Deux routes sur trente, parce qu'il y avait trois façons de
 * faire ce contrôle et qu'aucune n'était la bonne par défaut.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { parseId } from '../src/lib/routeParams';

test('un identifiant ordinaire se lit', () => {
  assert.equal(parseId('12'), 12);
  assert.equal(parseId('1'), 1);
  assert.equal(parseId('999999'), 999999);
});

/**
 * Tout ce que `Number` acceptait et qui ne désigne aucune ligne. Aucune de ces
 * formes n'apparaît dans une adresse que le site fabrique : les accepter ne
 * rendait service à personne, et `Number.isInteger` en laissait passer la
 * moitié.
 */
const REFUSES = [
  ['abc', 'des lettres'],
  ['', 'rien du tout'],
  ['   ', 'des espaces'],
  [' 12 ', 'un nombre entouré d’espaces'],
  ['12.5', 'un décimal'],
  ['1e3', 'une notation scientifique'],
  ['0x10', 'un hexadécimal'],
  ['-5', 'un négatif'],
  ['0', 'zéro — aucune ligne ne porte cet identifiant'],
  ['+7', 'un signe explicite'],
  ['Infinity', 'l’infini'],
  ['NaN', 'NaN écrit en toutes lettres'],
  ['12abc', 'un nombre suivi de n’importe quoi'],
  ['9007199254740993', 'au-delà de ce qu’un entier JavaScript représente'],
] as const;

for (const [valeur, quoi] of REFUSES) {
  test(`refusé : ${quoi} (« ${valeur} »)`, () => {
    assert.equal(parseId(valeur), null);
  });
}

test('ce qui n’est même pas une chaîne est refusé sans broncher', () => {
  // `req.params` est typé `string`, mais une route peut se tromper de champ et
  // passer ce que `req.query` a rendu — un tableau, par exemple.
  for (const valeur of [undefined, null, 12, ['12'], { id: 12 }, true]) {
    assert.equal(parseId(valeur), null, String(valeur));
  }
});

test('le retour est un nombre, jamais une chaîne', () => {
  // C'est ce que Prisma attend : un `where: { id: '12' }` échoue à l'exécution.
  assert.equal(typeof parseId('12'), 'number');
});
