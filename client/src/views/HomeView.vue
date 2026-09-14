<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import EventCard from '../components/EventCard.vue';
import AddressPicker from '../components/AddressPicker.vue';
import type { GeoSuggestion } from '../lib/geocode';
import { api } from '../lib/api';
import { setPageSeo } from '../lib/seo';
import {
  filtresDepuisQuery,
  filtresVides,
  pageDepuisQuery,
  queryDepuisFiltres,
  requeteApi,
} from '../lib/searchQuery';
import type { Area, Category, EventItem } from '../types';

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

const filters = reactive(filtresVides());

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const geoActive = computed(() => filters.lat !== null && filters.lng !== null);

/**
 * Recopie l'adresse dans les filtres affichés. La règle vit dans
 * `lib/searchQuery`, avec son aller-retour ; ici on ne fait que l'appliquer.
 */
function lireLAdresse() {
  Object.assign(filters, filtresDepuisQuery(route.query));
}

/**
 * Va à cette adresse, et laisse passer les navigations que le routeur refuse.
 *
 * Il en refuse une, et c'est la bonne : demander deux fois la même adresse. Le
 * `watch` ne se déclenche alors pas, et c'est ce qu'on veut — rien n'a changé,
 * il n'y a rien à rechercher.
 */
function naviguer(query: Record<string, string>) {
  router.push({ query }).catch(() => {});
}

/** Change de page en passant par l'adresse ; le `watch` ci-dessous recharge. */
function goToPage(n: number) {
  naviguer(queryDepuisFiltres(filters, n));
}

/**
 * Une recherche relancée repart de la première page — un filtre plus étroit
 * n'a aucune raison de s'ouvrir sur la troisième.
 *
 * Tout passe par l'adresse : c'est le `watch` qui déclenche la recherche, une
 * fois et une seule, quel que soit le geste qui a changé quelque chose.
 */
function applyFilters() {
  naviguer(queryDepuisFiltres(filters, 1));
}

/**
 * Numéro de la recherche en cours.
 *
 * Sans lui, deux recherches lancées coup sur coup — et le champ d'adresse est
 * débouncé, donc c'est le cas courant — s'affichaient dans l'ordre où le
 * réseau les rendait. Une requête large et lente écrasait alors le résultat
 * d'une requête étroite et rapide, et le visiteur voyait des sorties que ses
 * filtres excluaient.
 */
let derniereRecherche = 0;

async function search(goTo = 1) {
  const numero = ++derniereRecherche;
  page.value = goTo;
  loading.value = true;
  error.value = '';

  try {
    const data = await api.get<{ events: EventItem[]; total: number }>(
      `/api/events?${requeteApi(filters, goTo, pageSize)}`,
    );
    // Une recherche plus récente est partie entre-temps : la sienne fait foi.
    if (numero !== derniereRecherche) return;
    events.value = data.events;
    total.value = data.total;
  } catch (e) {
    if (numero !== derniereRecherche) return;
    error.value = e instanceof Error ? e.message : 'Erreur de chargement';
  } finally {
    // Le voyant ne s'éteint qu'avec la dernière recherche : l'éteindre depuis
    // une réponse dépassée montrerait une page prête alors qu'elle attend.
    if (numero === derniereRecherche) loading.value = false;
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
// Un seul observateur, sur l'adresse entière — les filtres y sont désormais,
// et deux observateurs auraient lancé deux recherches pour un seul geste.
watch(
  () => route.query,
  () => {
    lireLAdresse();
    void search(pageDepuisQuery(route.query));
  },
);

onMounted(async () => {
  setPageSeo({
    title:
      pageDepuisQuery(route.query) > 1
        ? `Sorties avec les enfants — page ${pageDepuisQuery(route.query)}`
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
});

// Avant même les catégories : la liste des résultats ne les attend pas, et
// l'adresse porte déjà tout ce qu'il faut pour la demander.
lireLAdresse();
void search(pageDepuisQuery(route.query));
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

    <!-- L'ordre a changé de nature : ce n'est plus la chronologie, c'est une
         réponse à ce qui a été demandé. Le dire évite de croire à un bug quand
         une sortie de la semaine prochaine passe devant une de demain. -->
    <p v-if="events.length" class="muted sorting">
      {{ total }} sortie(s) — les plus
      <template v-if="filters.age !== ''">adaptées à {{ filters.age }} ans d'abord,</template>
      <template v-else>ciblées d'abord,</template>
      puis les plus courtes et les plus proches.
    </p>
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

<style scoped>
/* Une ligne au-dessus des résultats, pas un titre : elle explique l'ordre à
   qui se le demande, sans prendre la place de ce qu'on est venu voir. */
.sorting {
  margin: 0 0 0.6rem;
  font-size: 0.88rem;
}
</style>
