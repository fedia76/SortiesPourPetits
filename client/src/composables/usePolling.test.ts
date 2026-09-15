/**
 * Le sondage, et la seule chose qu'il ajoute aux quatre `setInterval` qu'il
 * remplace : se taire quand personne ne regarde.
 *
 * Un onglet oublié sur la console du scraper frappait l'API toutes les cinq
 * secondes jusqu'au lendemain. C'est invisible à la relecture, invisible à
 * l'usage, et ça ne se voit que dans les journaux du serveur — donc c'est très
 * exactement ce qu'un test doit tenir.
 */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { createApp } from 'vue';

import { usePolling, type Polling } from './usePolling';

/** Un composant minimal, juste pour que `onMounted` ait un endroit où vivre. */
function monter<T>(setup: () => T): { valeur: T; demonter: () => void } {
  let valeur!: T;
  const app = createApp({
    setup() {
      valeur = setup();
      return () => null;
    },
  });
  app.mount(document.createElement('div'));
  return { valeur, demonter: () => app.unmount() };
}

/** L'onglet passe au premier plan ou en arrière-plan, et le navigateur le dit. */
function visibilite(cache: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => cache });
  document.dispatchEvent(new Event('visibilitychange'));
}

beforeEach(() => {
  vi.useFakeTimers();
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
});

afterEach(() => {
  vi.useRealTimers();
});

test('bat à l’intervalle demandé', () => {
  const battements = vi.fn();
  const { demonter } = monter(() => usePolling(battements, 1_000));

  // Rien à l'installation : la vue vient de charger ce qu'elle affiche.
  expect(battements).toHaveBeenCalledTimes(0);
  vi.advanceTimersByTime(3_000);
  expect(battements).toHaveBeenCalledTimes(3);
  demonter();
});

test('s’arrête au démontage', () => {
  const battements = vi.fn();
  const { demonter } = monter(() => usePolling(battements, 1_000));
  vi.advanceTimersByTime(1_000);
  demonter();
  vi.advanceTimersByTime(10_000);
  expect(battements).toHaveBeenCalledTimes(1);
});

describe('quand personne ne regarde', () => {
  test('un onglet en arrière-plan ne demande rien', () => {
    const battements = vi.fn();
    const { demonter } = monter(() => usePolling(battements, 1_000));
    vi.advanceTimersByTime(2_000);
    expect(battements).toHaveBeenCalledTimes(2);

    visibilite(true);
    vi.advanceTimersByTime(60_000);
    expect(battements).toHaveBeenCalledTimes(2);
    demonter();
  });

  test('le retour au premier plan rafraîchit tout de suite', () => {
    // Attendre le prochain battement laisserait la page mentir jusque-là.
    const battements = vi.fn();
    const { demonter } = monter(() => usePolling(battements, 10_000));
    visibilite(true);
    vi.advanceTimersByTime(30_000);
    expect(battements).toHaveBeenCalledTimes(0);

    visibilite(false);
    expect(battements).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(10_000);
    expect(battements).toHaveBeenCalledTimes(2);
    demonter();
  });

  test('un onglet déjà caché à l’ouverture ne part pas non plus', () => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    const battements = vi.fn();
    const { demonter } = monter(() => usePolling(battements, 1_000));
    vi.advanceTimersByTime(5_000);
    expect(battements).toHaveBeenCalledTimes(0);
    demonter();
  });

  test('l’écouteur part avec la vue', () => {
    const battements = vi.fn();
    const { demonter } = monter(() => usePolling(battements, 1_000));
    demonter();
    // Une vue démontée ne doit pas se réveiller parce qu'un onglet a changé.
    visibilite(true);
    visibilite(false);
    vi.advanceTimersByTime(5_000);
    expect(battements).toHaveBeenCalledTimes(0);
  });
});

describe('arrêter et reprendre', () => {
  test('stop() arrête définitivement — une exécution terminée ne bouge plus', () => {
    const battements = vi.fn();
    let suivi!: Polling;
    const { demonter } = monter(() => (suivi = usePolling(battements, 1_000)));

    vi.advanceTimersByTime(2_000);
    suivi.stop();
    vi.advanceTimersByTime(60_000);
    expect(battements).toHaveBeenCalledTimes(2);
    demonter();
  });

  test('un onglet qui revient ne ressuscite pas un sondage arrêté', () => {
    const battements = vi.fn();
    let suivi!: Polling;
    const { demonter } = monter(() => (suivi = usePolling(battements, 1_000)));
    suivi.stop();

    visibilite(true);
    visibilite(false);
    vi.advanceTimersByTime(10_000);
    expect(battements).toHaveBeenCalledTimes(0);
    demonter();
  });

  test('start() reprend, et stop() avant le montage tient', () => {
    // C'est ce que fait la fiche d'une sortie : le sondage n'a rien à suivre
    // tant qu'aucune recherche de source n'est lancée.
    const battements = vi.fn();
    let suivi!: Polling;
    const { demonter } = monter(() => {
      suivi = usePolling(battements, 1_000);
      suivi.stop();
      return suivi;
    });

    vi.advanceTimersByTime(10_000);
    expect(battements).toHaveBeenCalledTimes(0);

    suivi.start();
    vi.advanceTimersByTime(2_000);
    expect(battements).toHaveBeenCalledTimes(2);
    demonter();
  });

  test('start() deux fois de suite n’arme pas deux minuteurs', () => {
    const battements = vi.fn();
    let suivi!: Polling;
    const { demonter } = monter(() => (suivi = usePolling(battements, 1_000)));

    suivi.start();
    suivi.start();
    vi.advanceTimersByTime(3_000);
    expect(battements).toHaveBeenCalledTimes(3);
    demonter();
  });
});

test('un battement qui échoue n’arrête pas le suivant, et se dit', async () => {
  // Les vues gèrent leurs erreurs elles-mêmes ; ce qui leur échappe ne doit
  // pas finir en rejet non traité, où plus rien ne nomme la vue en cause.
  const journal = vi.spyOn(console, 'error').mockImplementation(() => {});
  const battements = vi.fn().mockRejectedValue(new Error('réseau coupé'));
  const { demonter } = monter(() => usePolling(battements, 1_000));

  vi.advanceTimersByTime(3_000);
  await vi.advanceTimersByTimeAsync(0);

  expect(battements).toHaveBeenCalledTimes(3);
  expect(journal).toHaveBeenCalledTimes(3);
  expect(journal.mock.calls[0][0]).toContain('sondage');
  journal.mockRestore();
  demonter();
});
