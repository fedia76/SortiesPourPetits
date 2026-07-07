import { defineStore } from 'pinia';
import { api, ApiError } from '../lib/api';
import type { User } from '../types';

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as User | null,
    initialized: false,
  }),
  getters: {
    isLoggedIn: (s) => s.user !== null,
    isModerator: (s) => s.user?.role === 'MODERATOR' || s.user?.role === 'ADMIN',
    isAdmin: (s) => s.user?.role === 'ADMIN',
  },
  actions: {
    /** Restaure la session au chargement de l'app (cookie httpOnly). */
    async init() {
      if (this.initialized) return;
      try {
        const { user } = await api.get<{ user: User }>('/api/auth/me');
        this.user = user;
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 401)) console.error(e);
      } finally {
        this.initialized = true;
      }
    },
    async login(email: string, password: string) {
      const { user } = await api.post<{ user: User }>('/api/auth/login', { email, password });
      this.user = user;
    },
    async register(email: string, password: string, displayName: string) {
      const { user } = await api.post<{ user: User }>('/api/auth/register', {
        email,
        password,
        displayName,
      });
      this.user = user;
    },
    async logout() {
      await api.post('/api/auth/logout');
      this.user = null;
    },
  },
});
