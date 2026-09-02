<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { api } from '../lib/api';
import type { Area } from '../types';

/**
 * Les zones géographiques du site.
 *
 * Chacune porte une page publique — `/sorties/le-havre` — avec son titre, son
 * texte et ses sorties. C'est cette page qu'un moteur de recherche peut
 * proposer à quelqu'un qui cherche « sortie enfant Le Havre » ; le texte de
 * présentation n'est donc pas décoratif, c'est lui qui distingue la page d'une
 * simple liste filtrée.
 */
const areas = ref<Area[]>([]);
const error = ref('');
const busy = ref(false);
const editingId = ref<number | null>(null);

/** Un brouillon de zone, partagé par la création et la modification. */
function blank() {
  return { slug: '', name: '', postalPrefixes: '', intro: '', position: 0 };
}
const draft = reactive(blank());

async function load() {
  const data = await api.get<{ areas: Area[] }>('/api/areas');
  areas.value = data.areas;
}

function reset() {
  editingId.value = null;
  Object.assign(draft, blank());
}

function startEdit(area: Area) {
  editingId.value = area.id;
  Object.assign(draft, {
    slug: area.slug,
    name: area.name,
    postalPrefixes: area.postalPrefixes,
    intro: area.intro,
    position: area.position,
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function save() {
  error.value = '';
  busy.value = true;
  try {
    if (editingId.value === null) await api.post('/api/areas', { ...draft });
    else await api.patch(`/api/areas/${editingId.value}`, { ...draft });
    reset();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    busy.value = false;
  }
}

async function remove(area: Area) {
  if (
    !confirm(
      `Supprimer la zone « ${area.name} » ?\n\n` +
        'Aucune sortie ne sera perdue — une zone ne fait que décrire des codes ' +
        'postaux. Mais son adresse publique disparaîtra, et si elle était ' +
        'référencée, elle deviendra une page en erreur.',
    )
  )
    return;
  error.value = '';
  try {
    await api.delete(`/api/areas/${area.id}`);
    if (editingId.value === area.id) reset();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

onMounted(load);
</script>

<template>
  <div class="container page">
    <h1>Administration — zones</h1>
    <nav class="row" style="gap: 1rem; margin-bottom: 1rem">
      <RouterLink to="/admin">Utilisateurs</RouterLink>
      <RouterLink to="/admin/categories">Catégories</RouterLink>
      <RouterLink to="/admin/zones">Zones</RouterLink>
    </nav>

    <p v-if="error" class="error">{{ error }}</p>

    <form class="filters card" @submit.prevent="save">
      <h2 style="margin: 0">{{ editingId === null ? 'Nouvelle zone' : 'Modifier la zone' }}</h2>
      <div class="row">
        <div class="field" style="flex: 2">
          <label for="z-name">Nom affiché</label>
          <input id="z-name" v-model="draft.name" type="text" maxlength="80" required
                 placeholder="Le Havre" />
        </div>
        <div class="field" style="flex: 2">
          <label for="z-slug">Identifiant d'adresse</label>
          <input id="z-slug" v-model="draft.slug" type="text" maxlength="60" required
                 placeholder="le-havre" />
          <small class="muted">La page sera /sorties/{{ draft.slug || 'le-havre' }}</small>
        </div>
        <div class="field">
          <label for="z-position">Ordre</label>
          <input id="z-position" v-model.number="draft.position" type="number" min="0" max="999" />
        </div>
      </div>

      <div class="field">
        <label for="z-prefixes">Préfixes de code postal</label>
        <input id="z-prefixes" v-model="draft.postalPrefixes" type="text" maxlength="200" required
               placeholder="766,767,762,764" />
        <small class="muted">
          Séparés par des virgules. Une sortie appartient à la zone si le code postal de son lieu
          commence par l'un d'eux — « 75 » prend tout Paris, « 766 » le seul bassin havrais.
        </small>
      </div>

      <div class="field">
        <label for="z-intro">Texte de présentation</label>
        <textarea id="z-intro" v-model="draft.intro" rows="4" maxlength="2000" required
                  placeholder="Ce que la zone offre aux familles, en quelques phrases."></textarea>
        <small class="muted">
          Affiché en tête de page et repris comme description dans les résultats de recherche.
          Écrivez-le pour un parent de la région, pas pour un moteur : c'est ce qui donne à la page
          une raison d'exister.
        </small>
      </div>

      <div class="row" style="gap: 0.5rem">
        <button class="btn" type="submit" :disabled="busy">
          {{ editingId === null ? 'Créer la zone' : 'Enregistrer' }}
        </button>
        <button v-if="editingId !== null" class="btn ghost" type="button" @click="reset">
          Annuler
        </button>
      </div>
    </form>

    <div class="table-wrap card">
      <table>
        <thead>
          <tr>
            <th>Zone</th>
            <th>Adresse</th>
            <th>Codes postaux</th>
            <th>Sorties à venir</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in areas" :key="a.id">
            <td>{{ a.name }}</td>
            <td><RouterLink :to="`/sorties/${a.slug}`">/sorties/{{ a.slug }}</RouterLink></td>
            <td class="muted">{{ a.postalPrefixes }}</td>
            <td :class="{ muted: !a.eventCount }">{{ a.eventCount ?? '—' }}</td>
            <td>
              <div class="row" style="gap: 0.5rem">
                <button class="btn ghost small" type="button" @click="startEdit(a)">Modifier</button>
                <a href="#" style="color: var(--danger)" @click.prevent="remove(a)">Supprimer</a>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
