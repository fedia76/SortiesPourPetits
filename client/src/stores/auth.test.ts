/**
 * Qui est connecté, et ce que le front en déduit.
 *
 * Ces trois booléens ne **protègent** rien — le serveur relit le rôle en base à
 * chaque requête, et c'est lui la barrière. Mais ils décident de tout ce qui
 * s'affiche : un `isModerator` faux, et un visiteur ordinaire voit des boutons
 * qui échoueront, ou un modérateur ne voit pas la file qu'il doit relire.
 */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

import { ApiError } from '../lib/api';
import { useAuthStore } from './auth';

vi.mock('../lib/api', async () => {
  const reel = await vi.importActual<typeof import('../lib/api')>('../lib/api');
  return { ...reel, api: { get: vi.fn(), post: vi.fn() } };
});

const { api } = await import('../lib/api');

const PARENT = { id: 1, email: 'parent@example.com', displayName: 'Parent', role: 'USER' } as const;
const MODO = { id: 2, email: 'modo@example.com', displayName: 'Modo', role: 'MODERATOR' } as const;
const ADMIN = { id: 3, email: 'admin@example.com', displayName: 'Admin', role: 'ADMIN' } as const;

beforeEach(() => {
  setActivePinia(createPinia());
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ce que le rôle autorise à voir', () => {
  test('un visiteur anonyme ne voit rien de plus', () => {
    const auth = useAuthStore();
    expect(auth.isLoggedIn).toBe(false);
    expect(auth.isModerator).toBe(false);
    expect(auth.isAdmin).toBe(false);
  });

  test('un parent propose, et c’est tout', () => {
    const auth = useAuthStore();
    auth.user = { ...PARENT };
    expect(auth.isLoggedIn).toBe(true);
    expect(auth.isModerator).toBe(false);
    expect(auth.isAdmin).toBe(false);
  });

  test('un modérateur modère, mais n’administre pas', () => {
    const auth = useAuthStore();
    auth.user = { ...MODO };
    expect(auth.isModerator).toBe(true);
    expect(auth.isAdmin).toBe(false);
  });

  test('un administrateur a aussi les droits d’un modérateur', () => {
    // Les rôles sont hiérarchiques côté serveur (`ROLE_LEVEL`) : ils doivent
    // l'être ici aussi, sans quoi un admin perdrait l'accès à la modération.
    const auth = useAuthStore();
    auth.user = { ...ADMIN };
    expect(auth.isModerator).toBe(true);
    expect(auth.isAdmin).toBe(true);
  });
});

describe('la restauration de session au chargement', () => {
  test('un cookie valide rend l’utilisateur', async () => {
    vi.mocked(api.get).mockResolvedValue({ user: MODO });
    const auth = useAuthStore();
    await auth.init();
    expect(auth.user).toEqual(MODO);
    expect(auth.initialized).toBe(true);
  });

  test('pas de cookie : anonyme, et sans bruit dans la console', async () => {
    // Un 401 est la réponse **normale** pour un visiteur : le journaliser
    // remplirait la console de chaque visite.
    const journal = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(api.get).mockRejectedValue(new ApiError(401, 'Authentification requise'));

    const auth = useAuthStore();
    await auth.init();

    expect(auth.user).toBeNull();
    expect(auth.initialized).toBe(true);
    expect(journal).not.toHaveBeenCalled();
  });

  test('une vraie panne se voit, elle', async () => {
    const journal = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(api.get).mockRejectedValue(new ApiError(500, 'Erreur interne'));

    await useAuthStore().init();

    expect(journal).toHaveBeenCalled();
  });

  test('la session ne se restaure qu’une fois', async () => {
    // `init()` est appelé par le garde du routeur, donc à **chaque**
    // navigation : sans ce verrou, chaque clic interrogerait le serveur.
    vi.mocked(api.get).mockResolvedValue({ user: PARENT });
    const auth = useAuthStore();
    await auth.init();
    await auth.init();
    await auth.init();
    expect(vi.mocked(api.get)).toHaveBeenCalledTimes(1);
  });
});

describe('entrer et sortir', () => {
  test('la connexion pose l’utilisateur', async () => {
    vi.mocked(api.post).mockResolvedValue({ user: MODO });
    const auth = useAuthStore();
    await auth.login('modo@example.com', 'motdepasse');
    expect(auth.user).toEqual(MODO);
  });

  test('une connexion refusée ne pose personne', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(401, 'Email ou mot de passe incorrect'));
    const auth = useAuthStore();
    await expect(auth.login('modo@example.com', 'faux')).rejects.toThrow(/incorrect/);
    expect(auth.user).toBeNull();
  });

  test('la déconnexion vide l’utilisateur, une fois le serveur prévenu', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true });
    const auth = useAuthStore();
    auth.user = { ...ADMIN };

    await auth.logout();

    // L'ordre compte : vider avant la réponse laisserait une interface
    // déconnectée devant un cookie encore valide.
    expect(vi.mocked(api.post)).toHaveBeenCalledWith('/api/auth/logout');
    expect(auth.user).toBeNull();
  });

  test('une déconnexion qui échoue garde l’utilisateur en place', async () => {
    // Il l'est encore côté serveur : prétendre le contraire ferait afficher
    // une interface de visiteur à quelqu'un qui peut encore tout faire.
    vi.mocked(api.post).mockRejectedValue(new ApiError(500, 'Erreur interne'));
    const auth = useAuthStore();
    auth.user = { ...ADMIN };

    await expect(auth.logout()).rejects.toThrow();
    expect(auth.user).toEqual(ADMIN);
  });
});
