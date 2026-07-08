<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api } from '../lib/api';
import { useAuthStore } from '../stores/auth';
import type { Role } from '../types';

interface AdminUser {
  id: number;
  email: string;
  displayName: string;
  role: Role;
  createdAt: string;
  _count: { events: number };
}

const auth = useAuthStore();
const users = ref<AdminUser[]>([]);
const error = ref('');

const ROLE_LABELS: Record<Role, string> = {
  USER: 'Simple',
  MODERATOR: 'Modérateur',
  ADMIN: 'Administrateur',
};

async function load() {
  const data = await api.get<{ users: AdminUser[] }>('/api/admin/users');
  users.value = data.users;
}

async function changeRole(user: AdminUser, event: Event) {
  const role = (event.target as HTMLSelectElement).value as Role;
  error.value = '';
  try {
    await api.patch(`/api/admin/users/${user.id}/role`, { role });
    user.role = role;
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
    (event.target as HTMLSelectElement).value = user.role;
  }
}

onMounted(load);
</script>

<template>
  <div class="container page">
    <h1>Administration — utilisateurs</h1>
    <nav class="row" style="gap: 1rem; margin-bottom: 1rem">
      <RouterLink to="/admin">Utilisateurs</RouterLink>
      <RouterLink to="/admin/categories">Catégories</RouterLink>
    </nav>
    <p v-if="error" class="error">{{ error }}</p>

    <div class="table-wrap card">
      <table>
        <thead>
          <tr>
            <th>Nom</th>
            <th>Email</th>
            <th>Sorties</th>
            <th>Inscrit le</th>
            <th>Rôle</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.displayName }}</td>
            <td>{{ u.email }}</td>
            <td>{{ u._count.events }}</td>
            <td>{{ new Date(u.createdAt).toLocaleDateString('fr-FR') }}</td>
            <td>
              <span v-if="u.id === auth.user!.id" class="badge">{{ ROLE_LABELS[u.role] }} (vous)</span>
              <select v-else :value="u.role" @change="changeRole(u, $event)">
                <option value="USER">Simple</option>
                <option value="MODERATOR">Modérateur</option>
                <option value="ADMIN">Administrateur</option>
              </select>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
