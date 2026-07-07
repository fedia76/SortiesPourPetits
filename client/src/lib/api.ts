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
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, body.error ?? `Erreur ${res.status}`);
  }
  return body as T;
}

export const api = {
  get<T>(path: string): Promise<T> {
    return request<T>(path);
  },
  post<T>(path: string, data?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: data === undefined ? undefined : JSON.stringify(data),
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
