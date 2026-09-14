/**
 * Le client HTTP du front — cinquante lignes par lesquelles passe **tout** ce
 * que le site demande au serveur.
 *
 * Ce qu'il décide n'est pas rien : le message qu'une vue affichera, le code
 * qu'elle lira pour savoir s'il faut rediriger vers la connexion, et la façon
 * dont une photo part avec sa fiche. Une erreur ici ne casse pas une page, elle
 * les rend toutes un peu fausses.
 */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { ApiError, api } from './api';

/** Une réponse HTTP telle que `fetch` la rend. */
function reponse(status: number, corps: unknown, illisible = false): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => (illisible ? Promise.reject(new Error('Unexpected token <')) : Promise.resolve(corps)),
  } as Response;
}

let appels: { url: string; init: RequestInit | undefined }[];

beforeEach(() => {
  appels = [];
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url, init });
      return Promise.resolve(reponse(200, { ok: true }));
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Fait répondre le prochain `fetch` comme indiqué. */
function repond(status: number, corps: unknown, illisible = false) {
  vi.mocked(fetch).mockImplementation((url, init) => {
    appels.push({ url: url as string, init });
    return Promise.resolve(reponse(status, corps, illisible));
  });
}

describe('ce qui revient', () => {
  test('un corps JSON est rendu tel quel', async () => {
    repond(200, { events: [{ id: 1 }], total: 1 });
    await expect(api.get('/api/events')).resolves.toEqual({ events: [{ id: 1 }], total: 1 });
  });

  test('le cookie de session part avec chaque requête', async () => {
    await api.get('/api/auth/me');
    expect(appels[0].init?.credentials).toBe('same-origin');
  });
});

describe('ce qui échoue', () => {
  test('le message du serveur est celui qu’on montre', async () => {
    repond(409, { error: 'Cet événement a déjà été modéré' });
    await expect(api.post('/api/moderation/12')).rejects.toThrow('Cet événement a déjà été modéré');
  });

  test('le code de retour voyage avec le message', async () => {
    // Plusieurs vues s'en servent : un 404 est définitif, une coupure non.
    repond(404, { error: 'Événement introuvable' });
    const erreur = await api.get('/api/events/99').catch((e: unknown) => e);
    expect(erreur).toBeInstanceOf(ApiError);
    expect((erreur as ApiError).status).toBe(404);
  });

  test('un échec sans message reste lisible', async () => {
    repond(500, {});
    await expect(api.get('/api/events')).rejects.toThrow('Erreur 500');
  });

  test('une page d’erreur en HTML est pardonnée : le code suffit', async () => {
    // Un relais qui rend sa propre page de panne est un cas normal, et il ne
    // répond pas en JSON.
    repond(502, null, true);
    const erreur = await api.get('/api/events').catch((e: unknown) => e);
    expect((erreur as ApiError).status).toBe(502);
    expect((erreur as ApiError).message).toBe('Erreur 502');
  });

  test('un « error » qui n’est pas du texte ne s’affiche pas tel quel', async () => {
    repond(400, { error: { champ: 'titre' } });
    await expect(api.get('/api/events')).rejects.toThrow('Erreur 400');
  });

  test('une réussite illisible est une erreur, pas une page vide', async () => {
    // Elle rendait un objet vide : ni erreur, ni contenu, et rien à quoi se
    // raccrocher — la vue affichait « aucun résultat » pour une panne.
    repond(200, null, true);
    await expect(api.get('/api/events')).rejects.toThrow('Réponse illisible');
  });
});

describe('ce qui part', () => {
  test('un POST annonce du JSON et porte son corps', async () => {
    await api.post('/api/auth/login', { email: 'a@b.fr', password: 'x' });
    const { init } = appels[0];
    expect(init?.method).toBe('POST');
    expect((init?.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(init?.body).toBe(JSON.stringify({ email: 'a@b.fr', password: 'x' }));
  });

  test('un POST sans données n’envoie pas de corps', async () => {
    // C'est le cas de `/logout` et des boutons de la console : un `undefined`
    // sérialisé enverrait la chaîne « undefined ».
    await api.post('/api/auth/logout');
    expect(appels[0].init?.body).toBeUndefined();
  });

  test('DELETE ne porte rien', async () => {
    await api.delete('/api/scraper/memory');
    expect(appels[0].init?.method).toBe('DELETE');
    expect(appels[0].init?.body).toBeUndefined();
  });

  test('PATCH et PUT annoncent du JSON comme POST', async () => {
    await api.patch('/api/categories/3', { name: 'Musées' });
    await api.put('/api/events/3', { title: 'x' });
    for (const { init } of appels) {
      expect((init?.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    }
  });
});

describe('une fiche avec sa photo', () => {
  test('le JSON part dans « data », la photo dans « photo »', async () => {
    const photo = new File(['x'], 'affiche.jpg', { type: 'image/jpeg' });
    await api.sendForm('/api/events', 'POST', { title: 'Atelier' }, photo);

    const form = appels[0].init?.body as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect(form.get('data')).toBe(JSON.stringify({ title: 'Atelier' }));
    expect(form.get('photo')).toBe(photo);
  });

  test('sans photo, le champ n’existe pas', async () => {
    // `multer` refuserait un champ vide, et une fiche modifiée sans nouvelle
    // photo doit garder la sienne.
    await api.sendForm('/api/events/3', 'PUT', { title: 'Atelier' }, null);
    expect((appels[0].init?.body as FormData).has('photo')).toBe(false);
  });

  test('aucun Content-Type n’est posé : le navigateur doit écrire sa frontière', async () => {
    // L'annoncer à la main casserait l'envoi — le serveur ne saurait plus où
    // les champs se séparent.
    await api.sendForm('/api/events', 'POST', {}, null);
    expect(appels[0].init?.headers).toBeUndefined();
  });
});
