/**
 * Les deux liens d'une fiche, éprouvés sans base de données.
 *
 * Ce fichier tient la règle qui empêche une correction de modérateur de
 * détruire un fait : la page que la recherche a lue. Elle ne se voit nulle
 * part quand elle échoue — la fiche reste correcte, le lien affiché est même
 * meilleur qu'avant — et c'est précisément pourquoi elle se teste.
 *
 * Exécution : `npm test`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { liensApresCorrection, type LiensExistants } from '../src/lib/eventSource';

const AGENDA = 'https://agenda.fr/sortie-du-musee';
const MUSEE = 'https://musee.fr/expo';

/** Le cas courant : l'attribution a échoué, la page lue tient lieu de lien. */
const sansSourceTrouvee: LiensExistants = {
  sourceUrl: AGENDA,
  foundOnUrl: null,
  sourceUrlSignal: null,
  fromScraper: true,
};

test('corriger le lien fait descendre la page lue en provenance', () => {
  // Le geste du modérateur : il trouve le musée et le colle par-dessus
  // l'agenda. L'agenda ne doit pas disparaître pour autant.
  assert.deepEqual(liensApresCorrection(sansSourceTrouvee, MUSEE), {
    sourceUrl: MUSEE,
    foundOnUrl: AGENDA,
    sourceUrlSignal: 'manuel',
  });
});

test('une provenance déjà connue n’est pas réécrite', () => {
  // L'attribution avait trouvé le musée, le modérateur corrige vers une autre
  // page du musée. D'où la sortie est arrivée n'a pas changé pour autant.
  const attribue: LiensExistants = {
    sourceUrl: MUSEE,
    foundOnUrl: AGENDA,
    sourceUrlSignal: 'json_ld',
    fromScraper: true,
  };
  const ecrits = liensApresCorrection(attribue, 'https://musee.fr/expo/horaires');
  assert.equal(ecrits.foundOnUrl, AGENDA);
  assert.equal(ecrits.sourceUrlSignal, 'manuel');
});

test('une proposition de visiteur n’a pas de page lue', () => {
  // Personne n'a « trouvé » cette adresse : elle a été tapée. La faire
  // descendre en provenance inventerait un fait.
  const visiteur: LiensExistants = {
    sourceUrl: 'https://tapee-a-la-main.fr/',
    foundOnUrl: null,
    sourceUrlSignal: 'manuel',
    fromScraper: false,
  };
  assert.equal(liensApresCorrection(visiteur, MUSEE).foundOnUrl, null);
});

test('deux liens égaux ne se répètent pas', () => {
  // Le modérateur recolle l'agenda en provenance : le champ n'apprend plus
  // rien, il repart vide. C'est l'invariant du champ depuis le premier jour.
  const attribue: LiensExistants = {
    sourceUrl: MUSEE,
    foundOnUrl: AGENDA,
    sourceUrlSignal: 'json_ld',
    fromScraper: true,
  };
  assert.equal(liensApresCorrection(attribue, AGENDA).foundOnUrl, null);
});

test('ne pas toucher au lien préserve ce qu’on savait de lui', () => {
  // Corriger un titre ne doit pas transformer une trouvaille vérifiée en
  // saisie manuelle : le signal ne bouge que si l'URL bouge.
  const attribue: LiensExistants = {
    sourceUrl: MUSEE,
    foundOnUrl: AGENDA,
    sourceUrlSignal: 'json_ld',
    fromScraper: true,
  };
  assert.deepEqual(liensApresCorrection(attribue, MUSEE), {
    sourceUrl: MUSEE,
    foundOnUrl: AGENDA,
    sourceUrlSignal: 'json_ld',
  });
});

test('vider le lien n’invente pas un signal', () => {
  // `''` n'est pas une saisie : un champ vidé n'a été désigné par personne.
  const ecrits = liensApresCorrection(sansSourceTrouvee, null);
  assert.equal(ecrits.sourceUrl, null);
  assert.equal(ecrits.sourceUrlSignal, null);
  // La page lue reste : c'est tout ce qu'on sait encore de cette sortie.
  assert.equal(ecrits.foundOnUrl, AGENDA);
});
