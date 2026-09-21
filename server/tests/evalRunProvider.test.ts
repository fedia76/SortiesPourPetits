/**
 * Le choix du fournisseur d'un run de banc, et les deux gardes qui l'entourent.
 *
 * Ce choix descend de la console jusqu'au worker Python par une seule colonne,
 * `EvalRun.settings`, où il voyage à côté de la recherche. Ce fichier verrouille
 * ce que le schéma accepte, et surtout ce qu'il **refuse** — parce que la
 * mauvaise combinaison ne se voit pas au lancement : elle occupe le worker,
 * puis échoue à la première page, un quart d'heure plus tard.
 *
 * Exécution : `npm test`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { evalRunSchema } from '../src/lib/validators';

const RECHERCHE = {
  dateFrom: '2026-07-01',
  dateTo: '2026-07-31',
  postalPrefixes: ['54'],
  maxLinks: 8,
  theme: 'sorties enfants',
};

test('un run d’extraction peut nommer l’étiqueteur local', () => {
  const parsed = evalRunSchema.safeParse({
    stage: 'EXTRACT',
    label: 'GLiNER, premier essai',
    extraction: { provider: 'gliner' },
  });
  assert.ok(parsed.success);
  assert.equal(parsed.data.extraction?.provider, 'gliner');
  // Point de contrôle laissé vide : c'est celui du scraper qui vaudra.
  assert.equal(parsed.data.extraction?.model, '');
});

test('le point de contrôle se choisit', () => {
  const parsed = evalRunSchema.safeParse({
    stage: 'EXTRACT',
    extraction: { provider: 'gliner', model: 'fastino/gliner2-multi-v1' },
  });
  assert.ok(parsed.success);
  assert.equal(parsed.data.extraction?.model, 'fastino/gliner2-multi-v1');
});

test('l’étiqueteur est refusé au tri, et au lancement', () => {
  // Un étiqueteur ne sait pas choisir des numéros de ligne dans une liste. Le
  // laisser passer occuperait le worker pour échouer à la première page.
  const parsed = evalRunSchema.safeParse({
    stage: 'SELECT',
    recherche: RECHERCHE,
    extraction: { provider: 'gliner' },
  });
  assert.ok(!parsed.success);
  assert.match(parsed.error.issues[0].message, /run d’extraction/);
});

test('l’étiqueteur est refusé aux deux étages de Python pur', () => {
  for (const stage of ['HARVEST', 'READ'] as const) {
    const parsed = evalRunSchema.safeParse({ stage, extraction: { provider: 'gliner' } });
    assert.ok(!parsed.success, `${stage} aurait dû être refusé`);
  }
});

test('aucun fournisseur ne se déclare aux étages de Python pur', () => {
  // Ils n'appellent personne : un run qui en nomme un se déclarerait joué par
  // quelqu'un qui n'a rien fait, et la ligne resterait fausse en base.
  for (const stage of ['HARVEST', 'READ'] as const) {
    for (const provider of ['anthropic', 'openrouter'] as const) {
      const parsed = evalRunSchema.safeParse({ stage, extraction: { provider } });
      assert.ok(!parsed.success, `${stage} + ${provider} aurait dû être refusé`);
    }
  }
});

test('le routeur est permis aux deux étages qui appellent quelqu’un', () => {
  // Il sait remplir une fiche **et** choisir des numéros de ligne : c'est là
  // toute la différence avec l'étiqueteur, et tout l'intérêt de la mesure.
  const extrait = evalRunSchema.safeParse({
    stage: 'EXTRACT',
    extraction: { provider: 'openrouter', model: 'google/gemini-2.5-flash' },
  });
  assert.ok(extrait.success);
  assert.equal(extrait.data.extraction?.model, 'google/gemini-2.5-flash');

  const trie = evalRunSchema.safeParse({
    stage: 'SELECT',
    recherche: RECHERCHE,
    extraction: { provider: 'openrouter', model: 'mistralai/mistral-small' },
  });
  assert.ok(trie.success);
});

test('la forme du slug n’est pas vérifiée ici, et c’est délibéré', () => {
  // La table qui traduit « claude-haiku-4-5 » en slug vit en Python. En tenir
  // une copie ici garantirait qu'elles divergent : c'est le worker qui refuse,
  // en réclamant le run et avant d'en traiter la moindre entrée.
  const parsed = evalRunSchema.safeParse({
    stage: 'EXTRACT',
    extraction: { provider: 'openrouter', model: 'claude-haiku-4-5' },
  });
  assert.ok(parsed.success);
});

test('le modèle reste permis partout — c’est le fournisseur de production', () => {
  const parsed = evalRunSchema.safeParse({
    stage: 'SELECT',
    recherche: RECHERCHE,
    extraction: { provider: 'anthropic' },
  });
  assert.ok(parsed.success);
});

test('un fournisseur inconnu est refusé', () => {
  const parsed = evalRunSchema.safeParse({
    stage: 'EXTRACT',
    extraction: { provider: 'glinerr' },
  });
  assert.ok(!parsed.success);
});

test('un run sans fournisseur reste valide : c’est le cas de tous les anciens', () => {
  const parsed = evalRunSchema.safeParse({ stage: 'EXTRACT' });
  assert.ok(parsed.success);
  assert.equal(parsed.data.extraction, undefined);
});

test('les deux réglages voyagent ensemble sans s’effacer', () => {
  // La forme exacte qui part en base, et que le worker relira : la recherche à
  // plat, le fournisseur sous sa clé. C'est ce que la route sérialise.
  const settings = JSON.stringify({ ...RECHERCHE, extraction: { provider: 'gliner', model: '' } });
  const { extraction, ...recherche } = JSON.parse(settings) as Record<string, unknown>;
  assert.deepEqual(extraction, { provider: 'gliner', model: '' });
  assert.equal((recherche as { theme: string }).theme, 'sorties enfants');
  // Et la clé `extraction` ne doit pas polluer la recherche que le worker lit.
  assert.ok(!('extraction' in recherche));
});
