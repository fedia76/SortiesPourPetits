import { reponsePreRendue } from './etatInitial';

/**
 * Ce que l'API a répondu quand ce n'est pas ce qu'on attendait.
 *
 * Le `status` compte autant que le message : c'est lui qui distingue « vous
 * n'êtes pas connecté » de « cette sortie n'existe pas », et plusieurs vues
 * s'en servent pour décider quoi afficher.
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: 'same-origin', ...init });

  // Un corps illisible n'est pardonné que sur une réponse **en échec** : un
  // relais qui rend sa propre page d'erreur en HTML est un cas normal, et le
  // code de retour suffit alors à dire quoi que ce soit d'utile.
  //
  // Sur une réponse réussie, en revanche, un corps illisible est une anomalie.
  // Le rendre comme un objet vide en faisait une page silencieusement vide —
  // ni erreur, ni contenu, et rien à quoi se raccrocher.
  const body: unknown = await res.json().catch(() => (res.ok ? ILLISIBLE : {}));

  if (!res.ok) {
    const message = (body as { error?: unknown }).error;
    throw new ApiError(res.status, typeof message === 'string' ? message : `Erreur ${res.status}`);
  }
  if (body === ILLISIBLE) {
    throw new ApiError(res.status, 'Réponse illisible du serveur');
  }
  return body as T;
}

/** Marqueur interne : le corps n'a pas pu être lu. Jamais rendu à l'appelant. */
const ILLISIBLE = Symbol('corps illisible');

export const api = {
  /**
   * Une lecture — et, au premier affichage, souvent pas un appel du tout.
   *
   * Le document porte les réponses qui correspondent à la page demandée (voir
   * `lib/etatInitial.ts`) : quand l'une d'elles répond à cet appel, elle est
   * rendue telle quelle et le réseau n'est pas sollicité. C'est réservé au
   * `get` : lui seul relit ce que le serveur venait d'écrire.
   */
  get<T>(path: string): Promise<T> {
    const prerendu = reponsePreRendue<T>(path);
    if (prerendu !== undefined) return Promise.resolve(prerendu);
    return request<T>(path);
  },
  post<T>(path: string, data?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
  },
  put<T>(path: string, data: unknown): Promise<T> {
    return request<T>(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  patch<T>(path: string, data: unknown): Promise<T> {
    return request<T>(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: 'DELETE' });
  },
  /** POST/PUT multipart : le JSON part dans le champ "data", la photo dans "photo". */
  sendForm<T>(path: string, method: 'POST' | 'PUT', data: unknown, photo?: File | null): Promise<T> {
    const form = new FormData();
    form.append('data', JSON.stringify(data));
    if (photo) form.append('photo', photo);
    return request<T>(path, { method, body: form });
  },
};
