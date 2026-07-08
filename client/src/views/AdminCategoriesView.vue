<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api } from '../lib/api';
import type { Category } from '../types';

const categories = ref<Category[]>([]);
const error = ref('');
const newName = ref('');
const creating = ref(false);
const editingId = ref<number | null>(null);
const editingName = ref('');

async function load() {
  const data = await api.get<{ categories: Category[] }>('/api/categories');
  categories.value = data.categories;
}

async function create() {
  if (!newName.value.trim()) return;
  error.value = '';
  creating.value = true;
  try {
    await api.post('/api/admin/categories', { name: newName.value.trim() });
    newName.value = '';
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    creating.value = false;
  }
}

function startEdit(category: Category) {
  editingId.value = category.id;
  editingName.value = category.name;
}

function cancelEdit() {
  editingId.value = null;
  editingName.value = '';
}

async function rename(category: Category) {
  if (!editingName.value.trim()) return;
  error.value = '';
  try {
    await api.patch(`/api/admin/categories/${category.id}`, { name: editingName.value.trim() });
    cancelEdit();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

async function remove(category: Category) {
  if (!confirm(`Supprimer la catégorie « ${category.name} » ?`)) return;
  error.value = '';
  try {
    await api.delete(`/api/admin/categories/${category.id}`);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

onMounted(load);
</script>

<template>
  <div class="container page">
    <h1>Administration — catégories</h1>
    <nav class="row" style="gap: 1rem; margin-bottom: 1rem">
      <RouterLink to="/admin">Utilisateurs</RouterLink>
      <RouterLink to="/admin/categories">Catégories</RouterLink>
    </nav>

    <p v-if="error" class="error">{{ error }}</p>

    <form class="row" style="gap: 0.5rem; margin-bottom: 1rem" @submit.prevent="create">
      <input
        v-model="newName"
        type="text"
        placeholder="Nouvelle catégorie…"
        maxlength="50"
        required
      />
      <button class="btn" type="submit" :disabled="creating">Ajouter</button>
    </form>

    <div class="table-wrap card">
      <table>
        <thead>
          <tr>
            <th>Nom</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in categories" :key="c.id">
            <td>
              <input v-if="editingId === c.id" v-model="editingName" type="text" maxlength="50" />
              <template v-else>{{ c.name }}</template>
            </td>
            <td>
              <div class="row" style="gap: 0.5rem">
                <template v-if="editingId === c.id">
                  <button class="btn small" type="button" @click="rename(c)">Enregistrer</button>
                  <button class="btn ghost small" type="button" @click="cancelEdit">Annuler</button>
                </template>
                <template v-else>
                  <button class="btn ghost small" type="button" @click="startEdit(c)">Renommer</button>
                  <a href="#" style="color: var(--danger)" @click.prevent="remove(c)">Supprimer</a>
                </template>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
