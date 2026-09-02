<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import EventCard from '../components/EventCard.vue';
import AddressPicker from '../components/AddressPicker.vue';
import type { GeoSuggestion } from '../lib/geocode';
import { api } from '../lib/api';
import { setPageSeo } from '../lib/seo';
import type { Area, Category, EventItem, Setting } from '../types';

const route = useRoute();
const router = useRouter();

const events = ref<EventItem[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 12;
const loading = ref(false);
const error = ref('');
const categories = ref<Category[]>([]);
const areas = ref<Area[]>([]);

const filters = reactive({
  q: '',
  free: false,
  priceMax: '' as string | number,
  age: '' as string | number,
  from: '',
  to: '',
  setting: '' as '' | Setting,
  categoryId: '' as '' | number,
  address: '',
  lat: null as number | null,
  lng: null as number | null,
  radiusKm: 10,
});

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const geoActive = computed(() => filters.lat !== null && filters.lng !== null);

/**
 * La page courante vit dans l'adresse.
 *
 * Elle ne s'y trouvait pas, et c'est ce qui rendait le catalogue invisible :
 * un robot ouvre l'accueil, y lit douze liens, et n'a aucun moyen d'atteindre
 * les suivants — « page 2 » n'était qu'un bouton. Une page, une adresse : le
 * serveur peut la pré-rendre, le sitemap la désigner, et un lien vers une
 * page de résultats se partage.
 */
function pageFromUrl(): number {
  const raw = Number(route.query.page);
  return Number.isInteger(raw) && raw >= 1 ? raw : 1;
}

/** Change de page en passant par l'adresse ; le `watch` ci-dessous recharge. */
function goToPage(n: number) {
  router.push({ query: { ...route.query, page: n > 1 ? String(n) : undefined } });
}

/**
 * Une recherche relancée repart de la première page — un filtre plus étroit
 * n'a aucune raison de s'ouvrir sur la troisième. Quand l'adresse en désigne
 * une autre, c'est elle qu'on corrige : le `watch` fera la recherche, et la
 * page affichée restera celle que l'adresse annonce.
 */
function applyFilters() {
  if (pageFromUrl() > 1) goToPage(1);
  else search(1);
}

async function search(goTo = 1) {
  page.value = goTo;
  loading.value = true;
  error.value = '';
  const params = new URLSearchParams();
  if (filters.q) params.set('q', filters.q);
  if (filters.free) params.set('free', 'true');
  else if (filters.priceMax !== '') params.set('priceMax', String(filters.priceMax));
  if (filters.age !== '') params.set('age', String(filters.age));
  if (filters.from) params.set('from', filters.from);
  if (filters.to) params.set('to', filters.to);
  if (filters.setting) params.set('setting', filters.setting);
  if (filters.categoryId !== '') params.set('categoryId', String(filters.categoryId));
  if (geoActive.value) {
    params.set('lat', String(filters.lat));
    params.set('lng', String(filters.lng));
    params.set('radiusKm', String(filters.radiusKm));
  }
  params.set('page', String(page.value));
  params.set('pageSize', String(pageSize));

  try {
    const data = await api.get<{ events: EventItem[]; total: number }>(
      `/api/events?${params.toString()}`,
    );
    events.value = data.events;
    total.value = data.total;
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur de chargement';
  } finally {
    loading.value = false;
  }
}

function onAddressSelect(s: GeoSuggestion) {
  filters.lat = s.lat;
  filters.lng = s.lng;
  applyFilters();
}

function clearGeo() {
  filters.lat = null;
  filters.lng = null;
  filters.address = '';
  applyFilters();
}

const geolocating = ref(false);

function useMyPosition() {
  if (!navigator.geolocation) return;
  geolocating.value = true;
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      filters.lat = pos.coords.latitude;
      filters.lng = pos.coords.longitude;
      filters.address = 'Ma position';
      geolocating.value = false;
      applyFilters();
    },
    () => {
      geolocating.value = false;
      error.value = "Impossible d'obtenir votre position";
    },
  );
}

// Un retour arrière, un lien partagé ou un lien suivi depuis la page
// pré-rendue changent l'adresse sans remonter la vue : c'est elle qui commande.
watch(() => route.query.page, () => search(pageFromUrl()));

onMounted(async () => {
  setPageSeo({
    title:
      pageFromUrl() > 1
        ? `Sorties avec les enfants — page ${pageFromUrl()}`
        : 'Sorties avec les enfants',
    description:
      'Des idées de sorties avec des enfants partout en France : spectacles, parcs, ' +
      'musées et ateliers, proposés par des parents et vérifiés par une équipe de modération.',
    path: '/',
  });
  const [{ categories: cats }, { areas: zones }] = await Promise.all([
    api.get<{ categories: Category[] }>('/api/categories'),
    api.get<{ areas: Area[] }>('/api/areas'),
  ]);
  categories.value = cats;
  areas.value = zones;
  search(pageFromUrl());
});
</script>

<template>
  <div class="container page">
    <div class="hero-banner">
      <h1>Où sort-on avec les enfants ce week-end ?</h1>
      <p>
        Des idées de sorties partout en France, proposées par des parents et
        vérifiées par notre équipe de modération.
      </p>
    </div>

    <!--
      Les zones, en liens : c'est ce qui les fait exister pour un moteur, et ce
      qui évite à un visiteur de Nancy de filtrer à la main un catalogue national.
    -->
    <nav v-if="areas.length" class="areas">
      <h2>Où cherchez-vous ?</h2>
      <div class="badges">
        <RouterLink v-for="a in areas" :key="a.slug" class="badge" :to="`/sorties/${a.slug}`">
          {{ a.name }}<span v-if="a.eventCount" class="muted"> · {{ a.eventCount }}</span>
        </RouterLink>
      </div>
    </nav>

    <form class="filters card" @submit.prevent="applyFilters()">
      <div class="row">
        <div class="field" style="flex: 2">
          <label for="f-q">Recherche</label>
          <input id="f-q" v-model="filters.q" type="text" placeholder="Parc, musée, spectacle…" />
        </div>
        <div class="field">
          <label for="f-age">Âge de l'enfant</label>
          <input id="f-age" v-model="filters.age" type="number" min="0" max="18" placeholder="ex. 4" />
        </div>
        <div class="field">
          <label for="f-setting">Cadre</label>
          <select id="f-setting" v-model="filters.setting">
            <option value="">Peu importe</option>
            <option value="INDOOR">Intérieur</option>
            <option value="OUTDOOR">Extérieur</option>
            <option value="BOTH">Les deux</option>
          </select>
        </div>
        <div class="field">
          <label for="f-category">Catégorie</label>
          <select id="f-category" v-model="filters.categoryId">
            <option value="">Toutes</option>
            <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>
      </div>

      <div class="row">
        <div class="field">
          <label for="f-from">Du</label>
          <input id="f-from" v-model="filters.from" type="date" />
        </div>
        <div class="field">
          <label for="f-to">Au</label>
          <input id="f-to" v-model="filters.to" type="date" />
        </div>
        <div class="field">
          <label for="f-price">Prix max (€)</label>
          <input
            id="f-price"
            v-model="filters.priceMax"
            type="number"
            min="0"
            placeholder="ex. 15"
            :disabled="filters.free"
          />
        </div>
        <div class="field">
          <label>&nbsp;</label>
          <label class="checkbox">
            <input v-model="filters.free" type="checkbox" />
            Gratuit uniquement
          </label>
        </div>
      </div>

      <div class="row">
        <div class="field" style="flex: 2">
          <label>Autour de…</label>
          <AddressPicker
            v-model="filters.address"
            placeholder="Une adresse, une ville…"
            @select="onAddressSelect"
          />
        </div>
        <div class="field">
          <label for="f-radius">Rayon ({{ filters.radiusKm }} km)</label>
          <input id="f-radius" v-model.number="filters.radiusKm" type="range" min="1" max="100" />
        </div>
        <div class="field">
          <label>&nbsp;</label>
          <div class="row" style="gap: 0.5rem">
            <button type="button" class="btn secondary small" :disabled="geolocating" @click="useMyPosition">
              {{ geolocating ? '…' : '📍 Ma position' }}
            </button>
            <button v-if="geoActive" type="button" class="btn ghost small" @click="clearGeo">✕</button>
          </div>
        </div>
      </div>

      <div>
        <button type="submit" class="btn" :disabled="loading">
          {{ loading ? 'Recherche…' : 'Rechercher' }}
        </button>
      </div>
    </form>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="events.length" class="event-grid">
      <EventCard v-for="e in events" :key="e.id" :event="e" />
    </div>
    <div v-else-if="!loading" class="empty">
      <p>Aucune sortie ne correspond à ces critères. 🧸</p>
      <p>Élargissez le rayon ou retirez un filtre !</p>
    </div>

    <nav v-if="totalPages > 1" class="pagination">
      <button class="btn ghost small" :disabled="page <= 1" @click="goToPage(page - 1)">← Précédent</button>
      <span class="muted">Page {{ page }} / {{ totalPages }}</span>
      <button class="btn ghost small" :disabled="page >= totalPages" @click="goToPage(page + 1)">
        Suivant →
      </button>
    </nav>
  </div>
</template>
