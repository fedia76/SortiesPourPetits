<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api } from '../lib/api';
import type { Role } from '../types';

interface KeyAccount {
  id: number;
  displayName: string;
  email: string;
  role: Role;
}

interface ApiKey {
  id: number;
  name: string;
  createdAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
  user: KeyAccount;
}

const ROLE_LABELS: Record<Role, string> = {
  USER: 'Simple',
  MODERATOR: 'Modérateur',
  ADMIN: 'Administrateur',
};

const keys = ref<ApiKey[]>([]);
const accounts = ref<KeyAccount[]>([]);
const error = ref('');

const newName = ref('');
const newUserId = ref<number | ''>('');
const creating = ref(false);

/** Clé en clair, affichée une seule fois juste après création. */
const createdKey = ref('');
const copied = ref(false);

async function load() {
  const [k, u] = await Promise.all([
    api.get<{ keys: ApiKey[] }>('/api/keys'),
    api.get<{ users: KeyAccount[] }>('/api/keys/users'),
  ]);
  keys.value = k.keys;
  accounts.value = u.users;
}

async function create() {
  if (!newName.value.trim() || newUserId.value === '') return;
  error.value = '';
  creating.value = true;
  try {
    const data = await api.post<{ key: string }>('/api/keys', {
      name: newName.value.trim(),
      userId: newUserId.value,
    });
    createdKey.value = data.key;
    copied.value = false;
    newName.value = '';
    newUserId.value = '';
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    creating.value = false;
  }
}

async function copyKey() {
  await navigator.clipboard.writeText(createdKey.value);
  copied.value = true;
}

async function revoke(key: ApiKey) {
  if (
    !confirm(
      `Révoquer la clé « ${key.name} » ?\nLes programmes qui l'utilisent perdront l'accès immédiatement.`,
    )
  )
    return;
  error.value = '';
  try {
    await api.delete(`/api/keys/${key.id}`);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString('fr-FR') : '—';
}

onMounted(load);
</script>

<template>
  <div class="container page">
    <h1>Clés d'API</h1>
    <p class="muted">
      Une clé permet à un programme tiers d'appeler l'API avec le rôle du compte auquel elle est
      rattachée, en l'envoyant dans chaque requête via le header
      <code>Authorization: Bearer &lt;clé&gt;</code>.
    </p>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="createdKey" class="card success key-reveal">
      <p>
        <strong>Clé créée.</strong> Copiez-la maintenant : elle ne pourra plus être réaffichée.
      </p>
      <div class="row" style="gap: 0.5rem; align-items: center">
        <code class="key-value">{{ createdKey }}</code>
        <button class="btn small" type="button" @click="copyKey">
          {{ copied ? 'Copié ✓' : 'Copier' }}
        </button>
        <button class="btn ghost small" type="button" @click="createdKey = ''">Fermer</button>
      </div>
    </div>

    <form class="row" style="gap: 0.5rem; margin: 1rem 0; flex-wrap: wrap" @submit.prevent="create">
      <input
        v-model="newName"
        type="text"
        placeholder="Libellé (ex. script de la mairie)…"
        maxlength="100"
        required
      />
      <select v-model="newUserId" required>
        <option value="" disabled>Compte rattaché…</option>
        <option v-for="a in accounts" :key="a.id" :value="a.id">
          {{ a.displayName }} ({{ a.email }}) — {{ ROLE_LABELS[a.role] }}
        </option>
      </select>
      <button class="btn" type="submit" :disabled="creating">Créer une clé</button>
    </form>

    <div class="table-wrap card">
      <table>
        <thead>
          <tr>
            <th>Libellé</th>
            <th>Compte</th>
            <th>Rôle</th>
            <th>Créée le</th>
            <th>Dernier usage</th>
            <th>Statut</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="keys.length === 0">
            <td colspan="7" class="muted">Aucune clé pour l'instant.</td>
          </tr>
          <tr v-for="k in keys" :key="k.id" :class="{ revoked: k.revokedAt }">
            <td>{{ k.name }}</td>
            <td>{{ k.user.displayName }}</td>
            <td>{{ ROLE_LABELS[k.user.role] }}</td>
            <td>{{ formatDate(k.createdAt) }}</td>
            <td>{{ formatDate(k.lastUsedAt) }}</td>
            <td>
              <span v-if="k.revokedAt" class="badge status-REJECTED">Révoquée</span>
              <span v-else class="badge status-APPROVED">Active</span>
            </td>
            <td>
              <a
                v-if="!k.revokedAt"
                href="#"
                style="color: var(--danger)"
                @click.prevent="revoke(k)"
              >
                Révoquer
              </a>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.key-reveal {
  padding: 1rem;
  margin-bottom: 1rem;
}
.key-value {
  word-break: break-all;
  padding: 0.35rem 0.5rem;
  background: rgba(0, 0, 0, 0.06);
  border-radius: 4px;
}
tr.revoked td {
  opacity: 0.55;
}
</style>
