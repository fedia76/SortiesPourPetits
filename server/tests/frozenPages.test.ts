/**
 * L'affichage d'une page gelée : ses chemins relatifs, et ce qu'elle n'a pas
 * le droit de faire.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { FROZEN_PAGE_CSP, withBase } from '../src/lib/frozenPages';

test('le <base> se place en tête du <head>, pour que les chemins relatifs se résolvent chez le site', () => {
  const html = '<html><head lang="fr"><title>x</title></head><body></body></html>';
  assert.equal(
    withBase(html, 'https://site.fr/agenda/'),
    '<html><head lang="fr"><base href="https://site.fr/agenda/"><title>x</title></head><body></body></html>',
  );
});

test('une page sans <head> reçoit quand même son <base>', () => {
  assert.equal(withBase('<p>x</p>', 'https://site.fr/'), '<base href="https://site.fr/"><p>x</p>');
});

test('une adresse ne peut pas sortir de l’attribut', () => {
  assert.ok(withBase('<p>x</p>', 'https://site.fr/"><script>').startsWith('<base href="https://site.fr/&quot;><script>">'));
});

test('la page rendue ne peut exécuter aucun script', () => {
  assert.match(FROZEN_PAGE_CSP, /^sandbox;/);
  assert.match(FROZEN_PAGE_CSP, /script-src 'none'/);
  assert.doesNotMatch(FROZEN_PAGE_CSP, /allow-scripts/);
});
