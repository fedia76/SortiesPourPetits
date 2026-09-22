/**
 * Comparer deux runs de fiches : ce que l'un met là où l'autre avait bon.
 *
 * Ces tests portent sur la seule chose que la comparaison décide — le
 * rapprochement de deux verdicts en une **bascule**, et ce qu'elle garde du
 * détail. Les verdicts eux-mêmes viennent de `verdictAspect`, mesuré
 * ailleurs : la comparaison ne recalcule rien, et c'est précisément ce qu'on
 * vérifie ici. Le jour où elle se mettrait à juger de son côté, ses totaux
 * contrediraient ceux de la courbe sans que personne ne sache lequel croire.
 *
 * Exécution : `npm test`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { bascule, comparerExtractions } from '../src/lib/evalMetrics';

/** Une entrée du corpus, réduite à l'aspect qu'on veut éprouver. */
function entree(attendu: unknown, a: unknown, b: unknown, sortieId = 1) {
  return {
    sortieId,
    url: `https://x.fr/${sortieId}`,
    label: `sortie ${sortieId}`,
    attendue: { setting: attendu } as Record<string, unknown>,
    renduA: { setting: a } as Record<string, unknown>,
    renduB: { setting: b } as Record<string, unknown>,
  };
}

function cadre(comparaison: ReturnType<typeof comparerExtractions>) {
  return comparaison.aspects.find((aspect) => aspect.key === 'cadre')!;
}

test('les quatre bascules disent ce qu’elles disent', () => {
  assert.equal(bascule('JUSTE', 'JUSTE'), 'TENU');
  assert.equal(bascule('JUSTE', 'FAUX'), 'PERDU');
  assert.equal(bascule('FAUX', 'JUSTE'), 'GAGNE');
  assert.equal(bascule('FAUX', 'MANQUE'), 'RATE');
});

test('un aspect que le corpus ne juge pas ne bascule pas', () => {
  // La dissymétrie du banc tient ici : personne n'a regardé, et il n'y a rien
  // à conclure — surtout pas que l'un des deux a eu tort.
  assert.equal(bascule(null, 'FAUX'), 'NON_JUGE');
  assert.equal(bascule('JUSTE', null), 'NON_JUGE');
});

test('ce qu’on vient chercher : le premier avait bon, le second met autre chose', () => {
  const vue = comparerExtractions([entree('INDOOR', 'INDOOR', 'OUTDOOR')]);
  const ligne = vue.lignes.find((l) => l.key === 'cadre');
  assert.ok(ligne);
  assert.equal(ligne.bascule, 'PERDU');
  // Les trois valeurs sont là : sans elles, « perdu » est une accusation sans
  // pièce jointe, et on ne peut ni la croire ni la corriger.
  assert.match(ligne.attendu, /INDOOR/);
  assert.match(ligne.renduA, /INDOOR/);
  assert.match(ligne.renduB, /OUTDOOR/);
  assert.equal(cadre(vue).perdu, 1);
});

test('deux runs d’accord ne font pas de ligne, mais restent comptés', () => {
  // Une centaine de sorties font plus d'un millier d'aspects : garder ceux sur
  // lesquels les deux disent la même chose noierait les quelques dizaines de
  // lignes qu'on est venu lire.
  const vue = comparerExtractions([entree('INDOOR', 'INDOOR', 'INDOOR')]);
  assert.equal(vue.lignes.filter((l) => l.key === 'cadre').length, 0);
  assert.equal(cadre(vue).tenu, 1);
  assert.ok(vue.identiques > 0);
});

test('deux runs faux de deux façons différentes font une ligne', () => {
  // Le total dirait « faux des deux côtés » et en resterait là. Or les deux
  // erreurs ne se corrigent pas au même endroit.
  const vue = comparerExtractions([entree('INDOOR', 'OUTDOOR', 'BOTH')]);
  const ligne = vue.lignes.find((l) => l.key === 'cadre');
  assert.ok(ligne);
  assert.equal(ligne.bascule, 'RATE');
  assert.equal(cadre(vue).rate, 1);
});

test('le second peut aussi gagner, et ça se compte à part', () => {
  const vue = comparerExtractions([entree('INDOOR', 'OUTDOOR', 'INDOOR')]);
  assert.equal(cadre(vue).gagne, 1);
  assert.equal(vue.lignes.find((l) => l.key === 'cadre')?.bascule, 'GAGNE');
});

test('un aspect absent de l’étiquette ne compte que comme non jugé', () => {
  const vue = comparerExtractions([
    {
      sortieId: 7,
      url: 'https://x.fr/7',
      label: 'sans cadre étiqueté',
      // `setting` absent : le corpus ne dit rien de cet aspect.
      attendue: { title: 'Atelier' },
      renduA: { title: 'Atelier', setting: 'INDOOR' },
      renduB: { title: 'Atelier', setting: 'OUTDOOR' },
    },
  ]);
  assert.equal(cadre(vue).nonJuge, 1);
  assert.equal(cadre(vue).perdu + cadre(vue).rate + cadre(vue).gagne, 0);
});

test('chaque aspect du banc est représenté, même sans divergence', () => {
  // Une matrice à trous se lirait comme « cet aspect n'existe pas » plutôt que
  // « les deux runs y sont d'accord ».
  const vue = comparerExtractions([entree('INDOOR', 'INDOOR', 'INDOOR')]);
  assert.ok(vue.aspects.length >= 12);
  assert.ok(vue.aspects.every((aspect) => aspect.libelle.length > 0));
});

test('les totaux d’un aspect additionnent toutes les entrées', () => {
  const vue = comparerExtractions([
    entree('INDOOR', 'INDOOR', 'OUTDOOR', 1),
    entree('INDOOR', 'INDOOR', 'INDOOR', 2),
    entree('OUTDOOR', 'INDOOR', 'OUTDOOR', 3),
  ]);
  const c = cadre(vue);
  assert.deepEqual(
    { tenu: c.tenu, perdu: c.perdu, gagne: c.gagne, rate: c.rate },
    { tenu: 1, perdu: 1, gagne: 1, rate: 0 },
  );
});
