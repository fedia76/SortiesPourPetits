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

const RADIUS_DEFAUT = 10;

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
  radiusKm: RADIUS_DEFAUT,
});

type Filtres = typeof filters;

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const geoActive = computed(() => filters.lat !== null && filters.lng !== null);

/**
 * **Toute** la recherche vit dans l'adresse — la page et les filtres.
 *
 * La page s'y trouvait déjà, et pour une raison qui vaut mot pour mot pour le
 * reste : un robot ouvre l'accueil, y lit douze liens, et n'a aucun moyen
 * d'atteindre les suivants si « page 2 » n'est qu'un bouton. Les filtres, eux,
 * étaient restés dans la mémoire du composant — donc une recherche ne se
 * partageait pas, ne se mettait pas en favori, et le bouton Retour du
 * navigateur la perdait au lieu de la défaire.
 *
 * Contrepartie assumée : le serveur ne pré-rend que la page, pas les filtres
 * (voir `seo/pages.ts`, dont la clé de cache ne retient que `page`). Une
 * adresse filtrée reçoit donc d'abord le catalogue entier, que Vue remplace
 * une seconde plus tard. C'est déjà ce qui arrivait aux paramètres de
 * campagne, et l'adresse canonique reste `/` : un moteur n'a donc pas deux
 * pages à départager.
 */
function pageFromUrl(): number {
  const raw = Number(route.query.page);
  return Number.isInteger(raw) && raw >= 1 ? raw : 1;
}

/** La première valeur d'un paramètre d'adresse, ou une chaîne vide. */
function param(cle: string): string {
  const brut = route.query[cle];
  return typeof brut === 'string' ? brut : '';
}

/** Un nombre lu dans l'adresse, ou `null` si ce n'en est pas un. */
function nombre(cle: string): number | null {
  const texte = param(cle);
  if (!texte) return null;
  const valeur = Number(texte);
  return Number.isFinite(valeur) ? valeur : null;
}

/**
 * Recopie l'adresse dans les filtres affichés.
 *
 * C'est l'adresse qui commande, jamais l'inverse : un retour arrière, un lien
 * partagé ou un lien suivi depuis la page pré-rendue changent l'adresse sans
 * passer par le formulaire, et le formulaire doit alors dire ce que l'adresse
 * dit.
 */
function lireLAdresse() {
  filters.q = param('q');
  filters.free = param('free') === 'true';
  filters.priceMax = param('priceMax');
  filters.age = param('age');
  filters.from = param('from');
  filters.to = param('to');
  filters.setting = (param('setting') || '') as '' | Setting;
  const categorie = nombre('categoryId');
  filters.categoryId = categorie ?? '';
  filters.lat = nombre('lat');
  filters.lng = nombre('lng');
  filters.radiusKm = nombre('radiusKm') ?? RADIUS_DEFAUT;
  filters.address = param('adresse');
}

/**
 * L'adresse qui décrit ces filtres.
 *
 * Ce qui vaut sa valeur par défaut n'y figure pas : une adresse qui énumère
 * douze paramètres vides ne se partage pas, et le `radiusKm` d'une recherche
 * sans position ne veut rien dire.
 */
function ecrireLAdresse(f: Filtres, page: number): Record<string, string> {
  const query: Record<string, string> = {};
  if (f.q) query.q = f.q;
  if (f.free) query.free = 'true';
  else if (f.priceMax !== '') query.priceMax = String(f.priceMax);
  if (f.age !== '') query.age = String(f.age);
  if (f.from) query.from = f.from;
  if (f.to) query.to = f.to;
  if (f.setting) query.setting = f.setting;
  if (f.categoryId !== '') query.categoryId = String(f.categoryId);
  if (f.lat !== null && f.lng !== null) {
    query.lat = String(f.lat);
    query.lng = String(f.lng);
    query.radiusKm = String(f.radiusKm);
    // Ce que le visiteur a tapé, pour que le champ le réaffiche : le couple
    // de coordonnées ne se relit pas.
    if (f.address) query.adresse = f.address;
  }
  if (page > 1) query.page = String(page);
  return query;
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
  naviguer(ecrireLAdresse(filters, n));
}

/**
 * Une recherche relancée repart de la première page — un filtre plus étroit
 * n'a aucune raison de s'ouvrir sur la troisième.
 *
 * Tout passe par l'adresse : c'est le `watch` qui déclenche la recherche, une
 * fois et une seule, quel que soit le geste qui a changé quelque chose.
 */
function applyFilters() {
  naviguer(ecrireLAdresse(filters, 1));
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
    void search(pageFromUrl());
  },
);

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
});

// Avant même les catégories : la liste des résultats ne les attend pas, et
// l'adresse porte déjà tout ce qu'il faut pour la demander.
lireLAdresse();
void search(pageFromUrl());
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
