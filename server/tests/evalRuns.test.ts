/**
 * La reprise des travaux abandonnés, éprouvée sans base de données.
 *
 * Ce fichier verrouille la seule décision de la reprise : à partir de quand un
 * travail « en cours » est réputé mort. Elle se trompe dans les deux sens, et
 * les deux erreurs ne coûtent pas la même chose — laisser traîner un mort fait
 * perdre une ligne dans une console, tuer un vivant fait perdre une mesure déjà
 * payée. D'où des cas limites écrits ici plutôt que constatés en production.
 *
 * Le second point verrouillé est plus sournois : la règle est écrite **deux
 * fois**, une fois en TypeScript (`abandonne`) et une fois pour la base
 * (`critereAbandon`). Deux formulations d'une seule règle finissent toujours
 * par diverger, et rien ne le dirait — la seconde ne s'exécute qu'en
 * production, contre des lignes que les tests n'ont pas. On les confronte donc
 * sur les mêmes cas.
 *
 * Exécution : `npm test`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ABANDON_APRES_MS,
  abandonne,
  critereAbandon,
  dernierSigneDeVie,
} from '../src/lib/evalRuns';

const MAINTENANT = new Date('2026-09-13T12:00:00.000Z');
const ilYA = (ms: number) => new Date(MAINTENANT.getTime() - ms);
const MINUTE = 60_000;

// ────────────────────────────────────────────────── ce qui vaut signe de vie

test('la réclamation vaut battement tant qu’il n’y en a pas eu', () => {
  // Les runs mis en file avant que la colonne n'existe portent `heartbeatAt`
  // nul. Les traiter comme muets les mettrait tous en échec d'un coup au
  // premier déploiement.
  const claime = { startedAt: ilYA(MINUTE), heartbeatAt: null };
  assert.deepEqual(dernierSigneDeVie(claime), claime.startedAt);
});

test('un battement postérieur remplace la réclamation', () => {
  const battu = { startedAt: ilYA(90 * MINUTE), heartbeatAt: ilYA(MINUTE) };
  assert.deepEqual(dernierSigneDeVie(battu), battu.heartbeatAt);
  // Et c'est tout l'intérêt : ce run tourne depuis une heure et demie, ce qui
  // est parfaitement normal pour un étage 6, et il est vivant.
  assert.equal(abandonne(battu, MAINTENANT), false);
});

// ───────────────────────────────────────────────────────────── le seuil

test('un travail jamais réclamé n’est pas abandonné, il attend', () => {
  // Une file qui n'avance pas est un worker arrêté, pas un travail mort. Les
  // confondre mettrait en échec tout ce qui attend le redémarrage du service —
  // c'est-à-dire exactement ce qu'on veut voir repartir tout seul.
  const enFile = { startedAt: null, heartbeatAt: null };
  assert.equal(abandonne(enFile, MAINTENANT), false);
});

test('sous le seuil, on laisse travailler', () => {
  const lent = { startedAt: ilYA(4 * 60 * MINUTE), heartbeatAt: ilYA(ABANDON_APRES_MS - MINUTE) };
  assert.equal(abandonne(lent, MAINTENANT), false);
});

test('au-delà du seuil, on reprend', () => {
  const mort = { startedAt: ilYA(4 * 60 * MINUTE), heartbeatAt: ilYA(ABANDON_APRES_MS + MINUTE) };
  assert.equal(abandonne(mort, MAINTENANT), true);
});

test('pile sur le seuil, on laisse travailler', () => {
  // Le doute profite au run : le reprendre perdrait une mesure déjà payée.
  const pile = { startedAt: null, heartbeatAt: ilYA(ABANDON_APRES_MS) };
  assert.equal(abandonne(pile, MAINTENANT), false);
});

test('le seuil couvre le pire appel de modèle honnête', () => {
  // L'hypothèse qui rend la reprise sans danger : une entrée ne peut pas
  // légitimement prendre plus longtemps qu'un appel de modèle allé au bout de
  // ses reprises — 300 s de délai d'attente, trois tentatives. Si quelqu'un
  // relève ce plafond côté worker sans toucher à celui-ci, la reprise se
  // mettra à tuer des runs vivants, et ce test est le seul endroit qui le
  // dira.
  const pireEntree = 3 * 300_000;
  assert.ok(
    ABANDON_APRES_MS >= 2 * pireEntree,
    `le seuil (${ABANDON_APRES_MS} ms) doit garder le double de marge sur ${pireEntree} ms`,
  );
});

// ─────────────────────────────────── les deux formulations disent la même chose

/**
 * Évalue le critère destiné à la base contre une ligne, comme le ferait MySQL.
 *
 * Volontairement bête : il applique le critère tel qu'il est écrit, sans
 * reprendre la règle. Si `critereAbandon` change de forme, cette fonction ne
 * compile plus — ce qui est le but.
 */
function selonLaBase(ligne: { startedAt: Date | null; heartbeatAt: Date | null }, quand: Date) {
  const { OR } = critereAbandon(quand);
  const [parBattement, parReclamation] = OR;
  if (ligne.heartbeatAt) return ligne.heartbeatAt < parBattement.heartbeatAt.lt;
  return ligne.heartbeatAt === null && !!ligne.startedAt && ligne.startedAt < parReclamation.startedAt.lt;
}

test('le critère de la base et la fonction tranchent pareil', () => {
  const cas = [
    { startedAt: null, heartbeatAt: null },
    { startedAt: ilYA(MINUTE), heartbeatAt: null },
    { startedAt: ilYA(ABANDON_APRES_MS + MINUTE), heartbeatAt: null },
    { startedAt: ilYA(ABANDON_APRES_MS), heartbeatAt: null },
    { startedAt: ilYA(10 * 60 * MINUTE), heartbeatAt: ilYA(MINUTE) },
    { startedAt: ilYA(MINUTE), heartbeatAt: ilYA(ABANDON_APRES_MS + MINUTE) },
    { startedAt: ilYA(MINUTE), heartbeatAt: ilYA(ABANDON_APRES_MS) },
  ];
  for (const ligne of cas) {
    assert.equal(
      selonLaBase(ligne, MAINTENANT),
      abandonne(ligne, MAINTENANT),
      `désaccord sur ${JSON.stringify(ligne)}`,
    );
  }
});
