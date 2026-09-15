/**
 * Qui a le droit d'ouvrir quelle page — et, tout aussi important, ce que voit
 * quelqu'un qui n'y a pas droit.
 *
 * Ce garde ne protège rien : le serveur relit le rôle en base à chaque requête,
 * et c'est lui la barrière. Il évite d'ouvrir un écran qui répondrait 403 à sa
 * première requête. Mais s'il se trompe dans l'autre sens, un modérateur ne
 * peut plus atteindre sa file d'attente — et ça, personne ne le rattrape.
 *
 * Le tableau des routes est parcouru tel quel : une route ajoutée sans
 * `requiresAuth` se verra ici, plutôt qu'à la première visite d'un anonyme.
 */
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import type { RouteLocationNormalized, RouteRecordRaw } from 'vue-router';

vi.mock('../lib/api', async () => {
  const reel = await vi.importActual<typeof import('../lib/api')>('../lib/api');
  return { ...reel, api: { get: vi.fn(), post: vi.fn() } };
});

const { api } = await import('../lib/api');
const { gardeDAcces, default: router } = await import('./index');
const { useAuthStore } = await import('../stores/auth');

type Role = 'USER' | 'MODERATOR' | 'ADMIN';

/** Une destination réduite à ce que le garde en lit. */
function vers(path: string, meta: Record<string, boolean> = {}): RouteLocationNormalized {
  return { fullPath: path, path, meta } as unknown as RouteLocationNormalized;
}

/** Installe une session, ou aucune. */
function connecte(role: Role | null) {
  setActivePinia(createPinia());
  const auth = useAuthStore();
  auth.initialized = true;
  auth.user = role ? { id: 1, email: 'x@y.fr', displayName: 'X', role } : null;
  return auth;
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  setActivePinia(createPinia());
});

describe('ce qui demande un compte', () => {
  test('un anonyme part se connecter, et on retient où il allait', async () => {
    connecte(null);
    const sortie = await gardeDAcces(vers('/proposer?ville=rouen', { requiresAuth: true }));
    expect(sortie).toEqual({ name: 'login', query: { redirect: '/proposer?ville=rouen' } });
  });

  test('un utilisateur connecté passe', async () => {
    connecte('USER');
    expect(await gardeDAcces(vers('/proposer', { requiresAuth: true }))).toBeUndefined();
  });
});

describe('ce qui demande la modération', () => {
  test('un parent est renvoyé à l’accueil', async () => {
    connecte('USER');
    const sortie = await gardeDAcces(vers('/moderation', { requiresAuth: true, requiresModerator: true }));
    expect(sortie).toEqual({ name: 'home' });
  });

  test('un modérateur passe', async () => {
    connecte('MODERATOR');
    const cible = vers('/moderation', { requiresAuth: true, requiresModerator: true });
    expect(await gardeDAcces(cible)).toBeUndefined();
  });

  test('un administrateur passe aussi — les rôles sont hiérarchiques', async () => {
    connecte('ADMIN');
    const cible = vers('/moderation', { requiresAuth: true, requiresModerator: true });
    expect(await gardeDAcces(cible)).toBeUndefined();
  });
});

describe('ce qui demande l’administration', () => {
  test('un modérateur n’entre pas au banc d’évaluation', async () => {
    // Le banc fabrique la vérité de référence : une vérité que plusieurs mains
    // modifient sans se concerter n'en est plus une.
    connecte('MODERATOR');
    const cible = vers('/admin/evaluation', { requiresAuth: true, requiresAdmin: true });
    expect(await gardeDAcces(cible)).toEqual({ name: 'home' });
  });

  test('un administrateur entre', async () => {
    connecte('ADMIN');
    const cible = vers('/admin/evaluation', { requiresAuth: true, requiresAdmin: true });
    expect(await gardeDAcces(cible)).toBeUndefined();
  });
});

test('une page publique s’ouvre sans rien demander', async () => {
  connecte(null);
  expect(await gardeDAcces(vers('/'))).toBeUndefined();
  expect(await gardeDAcces(vers('/sorties/12'))).toBeUndefined();
  expect(await gardeDAcces(vers('/sorties/le-havre'))).toBeUndefined();
});

test('la session se restaure avant de trancher', async () => {
  // Sans cette attente, la première navigation d'un rechargement jugerait un
  // utilisateur encore anonyme et renverrait un modérateur à l'accueil.
  setActivePinia(createPinia());
  vi.mocked(api.get).mockResolvedValue({
    user: { id: 2, email: 'modo@x.fr', displayName: 'Modo', role: 'MODERATOR' },
  });

  const cible = vers('/moderation', { requiresAuth: true, requiresModerator: true });
  expect(await gardeDAcces(cible)).toBeUndefined();
  expect(vi.mocked(api.get)).toHaveBeenCalledWith('/api/auth/me');
});

// ────────────────────────────────────────── le tableau des routes, tel quel

/** Toutes les routes déclarées, à plat. */
const ROUTES = router.getRoutes();

describe('ce que le tableau des routes déclare', () => {
  test('tout ce qui est sous /admin réclame un compte', () => {
    // Une route ajoutée sans `requiresAuth` s'ouvrirait à un anonyme jusqu'à
    // son premier appel d'API — c'est-à-dire jusqu'à un écran vide et un 401
    // dans la console.
    for (const route of ROUTES.filter((r) => r.path.startsWith('/admin'))) {
      expect(route.meta.requiresAuth, route.path).toBe(true);
      expect(
        route.meta.requiresModerator === true || route.meta.requiresAdmin === true,
        route.path,
      ).toBe(true);
    }
  });

  test('tout ce qui demande un rôle demande aussi un compte', () => {
    for (const route of ROUTES) {
      if (route.meta.requiresModerator || route.meta.requiresAdmin) {
        expect(route.meta.requiresAuth, route.path).toBe(true);
      }
    }
  });

  test('tout ce qui demande un compte est en noindex', () => {
    // Un formulaire ou une file d'attente n'a rien à faire dans les résultats
    // d'un moteur, et le serveur le dit déjà de son côté (`seo/routes.ts`).
    for (const route of ROUTES) {
      if (route.meta.requiresAuth) expect(route.meta.noindex, route.path).toBe(true);
    }
  });

  test('les pages publiques, elles, sont indexables', () => {
    for (const chemin of ['/', '/sorties/:id(\\d+)']) {
      const route = ROUTES.find((r) => r.path === chemin);
      expect(route, chemin).toBeDefined();
      expect(route?.meta.noindex).toBeUndefined();
    }
  });

  test('une fiche se distingue d’une zone par ses chiffres, et passe avant', () => {
    // « /sorties/204 » est une sortie, « /sorties/le-havre » une zone. L'ordre
    // de déclaration tranche, et le serveur applique la même règle.
    const chemins = (router.options.routes as RouteRecordRaw[]).map((r) => r.path);
    expect(chemins.indexOf('/sorties/:id(\\d+)')).toBeLessThan(
      chemins.indexOf('/sorties/:slug([a-z0-9][a-z0-9-]*)'),
    );
  });

  test('une adresse inconnue tombe sur une vraie page 404', () => {
    // Elle affichait l'accueil, par redirection : le visiteur n'y comprenait
    // rien, et le serveur, lui, répond bien 404 sur cette adresse.
    const perdue = router.resolve('/cette-page-n-existe-pas');
    expect(perdue.name).toBe('not-found');
  });
});
