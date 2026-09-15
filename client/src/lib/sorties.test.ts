/**
 * Ce qu'une sortie dit d'elle-même, et deux règles **recopiées** du serveur.
 *
 * `hasPrice` et `hasCoordinates` existent des deux côtés, faute de paquet
 * partagé entre les deux moitiés du dépôt. Elles avaient déjà divergé : le
 * serveur répondait « tarif connu » pour une sortie payante sans prix — parce
 * que `Number(null)` vaut zéro — là où le client répondait l'inverse. C'est le
 * serveur qui garde l'approbation en modération, donc c'est lui qui avait tort.
 *
 * La table de vérité ci-dessous est **la même** que celle de
 * `server/tests/incomplete.test.ts`, cas pour cas et dans le même ordre. Ce
 * n'est pas un paquet partagé — ça n'en tient pas lieu — mais les deux copies
 * ne peuvent plus diverger sans qu'un des deux fichiers tombe.
 */
import { describe, expect, test } from 'vitest';

import type { ScraperRun } from '../types';
import {
  UNKNOWN_PRICE,
  ageLabel,
  dayLabel,
  hasCoordinates,
  hasPrice,
  nextDate,
  priceLabel,
  runLabel,
  shortAgeLabel,
} from './sorties';

// ──────────────────────────────────────────────────────────────── le tarif

const TARIFS: [string, { isFree: boolean; price: number | null }, boolean][] = [
  ['gratuite', { isFree: true, price: null }, true],
  ['gratuite avec un prix résiduel', { isFree: true, price: 8 }, true],
  ['payante à 8 €', { isFree: false, price: 8 }, true],
  ['payante à 0 €', { isFree: false, price: 0 }, true],
  // Le cas du désaccord : le serveur répondait « connu ».
  ['payante sans prix', { isFree: false, price: null }, false],
  ['tarif que l’import n’a pas su lire', { isFree: false, price: UNKNOWN_PRICE }, false],
];

describe('le tarif est-il connu ?', () => {
  for (const [quoi, event, connu] of TARIFS) {
    test(`une sortie ${quoi} : ${connu ? 'connu' : 'à compléter'}`, () => {
      expect(hasPrice(event)).toBe(connu);
    });
  }

  test('le tarif convenu pour « je ne sais pas » est négatif', () => {
    expect(UNKNOWN_PRICE).toBeLessThan(0);
    expect(hasPrice({ isFree: true, price: UNKNOWN_PRICE })).toBe(true);
  });
});

describe('le badge de tarif', () => {
  test('dit ce qu’il sait, et dit aussi quand il ne sait pas', () => {
    expect(priceLabel({ isFree: true, price: null })).toBe('Gratuit');
    expect(priceLabel({ isFree: false, price: 8 })).toBe('8 €');
    expect(priceLabel({ isFree: false, price: 0 })).toBe('0 €');
    // C'est ce badge qui appelle un modérateur : sans lui, une sortie importée
    // sans tarif ressemblerait à une sortie à -1 €.
    expect(priceLabel({ isFree: false, price: UNKNOWN_PRICE })).toBe('Tarif à compléter');
    expect(priceLabel({ isFree: false, price: null })).toBe('Tarif à compléter');
  });
});

// ────────────────────────────────────────────────────────────── la position

describe('la position est-elle connue ?', () => {
  test('(0, 0) est la convention « non géocodé »', () => {
    expect(hasCoordinates({ lat: 0, lng: 0 })).toBe(false);
    expect(hasCoordinates({ lat: 48.85, lng: 2.35 })).toBe(true);
  });

  test('une seule coordonnée nulle reste une position valable', () => {
    // Le méridien de Greenwich passe en France : Le Havre est à 0,1° est, et
    // un lieu exactement dessus n'est pas une erreur de géocodage.
    expect(hasCoordinates({ lat: 49.49, lng: 0 })).toBe(true);
    expect(hasCoordinates({ lat: 0, lng: 2.35 })).toBe(true);
  });
});

// ─────────────────────────────────────────────────────────── la tranche d'âge

describe('la tranche d’âge', () => {
  test('les deux bornes', () => {
    expect(ageLabel({ ageMin: 3, ageMax: 6 })).toBe('De 3 à 6 ans');
    expect(shortAgeLabel({ ageMin: 3, ageMax: 6 })).toBe('3–6 ans');
  });

  test('une seule borne se dit quand même', () => {
    // N'afficher la tranche que lorsque les deux bornes existaient faisait
    // disparaître le « à partir de 3 ans » de la moitié des sorties.
    expect(ageLabel({ ageMin: 3, ageMax: null })).toBe('À partir de 3 ans');
    expect(ageLabel({ ageMin: null, ageMax: 6 })).toBe("Jusqu'à 6 ans");
    expect(shortAgeLabel({ ageMin: 3, ageMax: null })).toBe('dès 3 ans');
    expect(shortAgeLabel({ ageMin: null, ageMax: 6 })).toBe("jusqu'à 6 ans");
  });

  test('aucune borne ne dit rien plutôt que « de 0 à 18 ans »', () => {
    expect(ageLabel({ ageMin: null, ageMax: null })).toBeNull();
    expect(shortAgeLabel({ ageMin: null, ageMax: null })).toBeNull();
  });

  test('zéro est un âge, pas une absence', () => {
    // `0` est faux en JavaScript : un test sur la valeur au lieu de `null`
    // aurait fait disparaître « dès 0 an », qui est le cas des bébés lecteurs.
    expect(ageLabel({ ageMin: 0, ageMax: 3 })).toBe('De 0 à 3 ans');
    expect(shortAgeLabel({ ageMin: 0, ageMax: null })).toBe('dès 0 ans');
  });
});

// ──────────────────────────────────────────────── la prochaine représentation

describe('la prochaine date', () => {
  const aujourdhui = new Date('2026-10-15T09:00:00Z');

  test('le prochain jour à venir, pas le premier de la liste', () => {
    const dates = ['2026-10-01', '2026-10-20', '2026-11-05'];
    expect(nextDate({ dates }, aujourdhui)).toBe('2026-10-20');
  });

  test('aujourd’hui compte encore', () => {
    expect(nextDate({ dates: ['2026-10-15'] }, aujourdhui)).toBe('2026-10-15');
  });

  test('rien quand tout est passé, rien quand il n’y a pas de dates', () => {
    expect(nextDate({ dates: ['2026-09-01'] }, aujourdhui)).toBeUndefined();
    expect(nextDate({ dates: [] }, aujourdhui)).toBeUndefined();
  });
});

test('un jour se lit en toutes lettres, en français', () => {
  // Midi et non minuit dans `dayLabel` : à minuit UTC, un navigateur à l'ouest
  // de Greenwich afficherait la veille.
  expect(dayLabel('2026-10-20')).toBe('mardi 20 octobre');
});

// ─────────────────────────────────────────────────── le nom d'une exécution

describe('le nom d’une exécution', () => {
  const run = (champs: Partial<ScraperRun>) => ({ ...champs }) as ScraperRun;

  test('sa configuration, quand elle en a une', () => {
    expect(runLabel(run({ config: { id: 1, name: 'Seine-Maritime' } }))).toBe('Seine-Maritime');
  });

  test('la sortie qu’elle porte, pour une recherche de source', () => {
    // Une recherche de source n'a pas de configuration : sans ce cas, la ligne
    // s'affichait sans titre dans la console.
    expect(runLabel(run({ event: { id: 12, title: 'Le Petit Prince' } }))).toBe(
      'Source de « Le Petit Prince »',
    );
  });

  test('et un nom de repli plutôt qu’une ligne vide', () => {
    expect(runLabel(run({}))).toBe('Exécution');
  });
});
