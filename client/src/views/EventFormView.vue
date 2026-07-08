<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import AddressPicker from '../components/AddressPicker.vue';
import type { GeoSuggestion } from '../lib/geocode';
import { api } from '../lib/api';
import type { Category, EventInput, EventItem, Setting } from '../types';

const route = useRoute();
const router = useRouter();

const editId = computed(() => (route.name === 'edit-event' ? Number(route.params.id) : null));

const form = reactive({
  title: '',
  description: '',
  isFree: false,
  price: '' as string | number,
  ageMin: 0,
  ageMax: 12,
  dateStart: '',
  dateEnd: '',
  openTime: '10:00',
  closeTime: '18:00',
  setting: 'BOTH' as Setting,
  categoryId: null as number | null,
  venueName: '',
  address: '',
  city: '',
  postalCode: '',
  lat: null as number | null,
  lng: null as number | null,
});

const photo = ref<File | null>(null);
const photoPreview = ref('');
const existingPhotoUrl = ref<string | null>(null);
const error = ref('');
const loading = ref(false);
const categories = ref<Category[]>([]);

function onAddressSelect(s: GeoSuggestion) {
  form.address = s.name || s.label;
  form.city = s.city;
  form.postalCode = s.postcode;
  form.lat = s.lat;
  form.lng = s.lng;
}

function onPhotoChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0] ?? null;
  photo.value = file;
  photoPreview.value = file ? URL.createObjectURL(file) : '';
}

async function submit() {
  error.value = '';
  if (form.lat === null || form.lng === null) {
    error.value = "Sélectionnez l'adresse du lieu dans les suggestions (pour la géolocalisation).";
    return;
  }
  if (form.categoryId === null) {
    error.value = 'Choisissez une catégorie.';
    return;
  }
  const payload: EventInput = {
    title: form.title,
    description: form.description,
    isFree: form.isFree,
    price: form.isFree || form.price === '' ? null : Number(form.price),
    ageMin: form.ageMin,
    ageMax: form.ageMax,
    dateStart: form.dateStart,
    dateEnd: form.dateEnd,
    openTime: form.openTime,
    closeTime: form.closeTime,
    setting: form.setting,
    categoryId: form.categoryId,
    venue: {
      name: form.venueName,
      address: form.address,
      city: form.city,
      postalCode: form.postalCode,
      lat: form.lat,
      lng: form.lng,
    },
  };

  loading.value = true;
  try {
    const { event } = editId.value
      ? await api.sendForm<{ event: EventItem }>(`/api/events/${editId.value}`, 'PUT', payload, photo.value)
      : await api.sendForm<{ event: EventItem }>('/api/events', 'POST', payload, photo.value);
    router.push(`/sorties/${event.id}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur lors de l’envoi';
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  const { categories: cats } = await api.get<{ categories: Category[] }>('/api/categories');
  categories.value = cats;

  if (!editId.value) return;
  const { event } = await api.get<{ event: EventItem }>(`/api/events/${editId.value}`);
  form.title = event.title;
  form.description = event.description;
  form.isFree = event.isFree;
  form.price = event.price ?? '';
  form.ageMin = event.ageMin;
  form.ageMax = event.ageMax;
  form.dateStart = event.dateStart;
  form.dateEnd = event.dateEnd;
  form.openTime = event.openTime;
  form.closeTime = event.closeTime;
  form.setting = event.setting;
  form.categoryId = event.category.id;
  form.venueName = event.venue.name;
  form.address = event.venue.address;
  form.city = event.venue.city;
  form.postalCode = event.venue.postalCode;
  form.lat = event.venue.lat;
  form.lng = event.venue.lng;
  existingPhotoUrl.value = event.photoUrl;
});
</script>

<template>
  <div class="container page">
    <h1>{{ editId ? 'Modifier la sortie' : 'Proposer une sortie' }}</h1>
    <p class="muted">
      Votre proposition sera vérifiée par un modérateur avant d'être publiée.
    </p>

    <form class="form" @submit.prevent="submit">
      <p v-if="error" class="error">{{ error }}</p>

      <div class="field">
        <label for="title">Titre *</label>
        <input id="title" v-model="form.title" type="text" required minlength="3" maxlength="150" />
      </div>

      <div class="field">
        <label for="desc">Description *</label>
        <textarea id="desc" v-model="form.description" rows="6" required minlength="10" />
      </div>

      <div class="row">
        <div class="field">
          <label>&nbsp;</label>
          <label class="checkbox">
            <input v-model="form.isFree" type="checkbox" />
            Sortie gratuite
          </label>
        </div>
        <div class="field">
          <label for="price">Prix par enfant (€) {{ form.isFree ? '' : '*' }}</label>
          <input
            id="price"
            v-model="form.price"
            type="number"
            min="0"
            step="0.5"
            :disabled="form.isFree"
            :required="!form.isFree"
          />
        </div>
      </div>

      <div class="row">
        <div class="field">
          <label for="age-min">Âge minimum *</label>
          <input id="age-min" v-model.number="form.ageMin" type="number" min="0" max="17" required />
        </div>
        <div class="field">
          <label for="age-max">Âge maximum *</label>
          <input id="age-max" v-model.number="form.ageMax" type="number" min="0" max="18" required />
        </div>
        <div class="field">
          <label for="setting">Cadre *</label>
          <select id="setting" v-model="form.setting" required>
            <option value="INDOOR">Intérieur</option>
            <option value="OUTDOOR">Extérieur</option>
            <option value="BOTH">Les deux</option>
          </select>
        </div>
        <div class="field">
          <label for="category">Catégorie *</label>
          <select id="category" v-model.number="form.categoryId" required>
            <option :value="null" disabled>Choisissez…</option>
            <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>
      </div>

      <div class="row">
        <div class="field">
          <label for="date-start">Date de début *</label>
          <input id="date-start" v-model="form.dateStart" type="date" required />
        </div>
        <div class="field">
          <label for="date-end">Date de fin *</label>
          <input id="date-end" v-model="form.dateEnd" type="date" required />
        </div>
        <div class="field">
          <label for="open-time">Heure d'ouverture *</label>
          <input id="open-time" v-model="form.openTime" type="time" required />
        </div>
        <div class="field">
          <label for="close-time">Heure de fermeture *</label>
          <input id="close-time" v-model="form.closeTime" type="time" required />
        </div>
      </div>
      <span class="hint">Cette plage horaire s'applique tous les jours de l'évènement.</span>

      <h2>Le lieu</h2>

      <div class="field">
        <label for="venue-name">Nom du lieu *</label>
        <input
          id="venue-name"
          v-model="form.venueName"
          type="text"
          required
          placeholder="ex. Parc de Sceaux"
        />
      </div>

      <div class="field">
        <label>Adresse *</label>
        <AddressPicker v-model="form.address" placeholder="Cherchez l'adresse…" @select="onAddressSelect" />
        <span class="hint">
          Choisissez une suggestion pour géolocaliser le lieu (recherche par distance).
        </span>
      </div>

      <div class="row">
        <div class="field">
          <label for="postal">Code postal *</label>
          <input id="postal" v-model="form.postalCode" type="text" required />
        </div>
        <div class="field">
          <label for="city">Ville *</label>
          <input id="city" v-model="form.city" type="text" required />
        </div>
      </div>

      <div class="field">
        <label for="photo">Photo</label>
        <input id="photo" type="file" accept="image/*" @change="onPhotoChange" />
        <img
          v-if="photoPreview || existingPhotoUrl"
          :src="photoPreview || existingPhotoUrl!"
          alt="Aperçu"
          style="max-width: 320px; border-radius: 10px; margin-top: 0.5rem"
        />
      </div>

      <div>
        <button class="btn" type="submit" :disabled="loading">
          {{ loading ? 'Envoi…' : editId ? 'Enregistrer' : 'Proposer la sortie' }}
        </button>
      </div>
    </form>
  </div>
</template>
