<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import EventCard from '../components/EventCard.vue';
import { api } from '../lib/api';
import { setPageSeo } from '../lib/seo';
import type { Area, EventItem } from '../types';

/**
 * Les sorties d'une zone — « Le Havre : où sortir avec les enfants ? »
 *
 * Le serveur pré-rend déjà cette page en entier (server/src/seo/pages.ts) ;
 * ce qui suit la reconstruit à l'identique quand on y arrive par un clic,
 * sans rechargement. Les deux doivent donc dire la même chose, titre compris.
 */
const route = useRoute();
const router = useRouter();

const area = ref<Area | null>(null);
const events = ref<EventItem[]>([]);
const others = ref<Area[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 12;
const loading = ref(true);
const error = ref('');

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const slug = computed(() => String(route.params.slug ?? ''));

function pageFromUrl(): number {
  const raw = Number(route.query.page);
  return Number.isInteger(raw) && raw >= 1 ? raw : 1;
}

function goToPage(n: number) {
  router.push({ query: { ...route.query, page: n > 1 ? String(n) : undefined } });
}

async function load() {
  loading.value = true;
  error.value = '';
  page.value = pageFromUrl();
  try {
    const { areas } = await api.get<{ areas: Area[] }>('/api/areas');
    const found = areas.find((a) => a.slug === slug.value) ?? null;
    area.value = found;
    others.value = areas.filter((a) => a.slug !== slug.value);
    if (!found) {
      error.value = 'Cette zone n’existe pas.';
      setPageSeo({ title: 'Zone introuvable', noindex: true });
      return;
    }
    setPageSeo({
      title:
        page.value > 1
          ? `${found.name} : sorties avec les enfants — page ${page.value}`
          : `${found.name} : sorties avec les enfants`,
      description: found.intro,
      path: `/sorties/${found.slug}`,
    });
    const params = new URLSearchParams({
      area: found.slug,
      page: String(page.value),
      pageSize: String(pageSize),
    });
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

watch(() => [route.params.slug, route.query.page], load, { immediate: true });
</script>

<template>
  <div class="container page">
    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="area">
      <div class="hero-banner">
        <h1>{{ area.name }} : où sortir avec les enfants ?</h1>
        <p>{{ area.intro }}</p>
      </div>

      <div v-if="events.length" class="event-grid">
        <EventCard v-for="e in events" :key="e.id" :event="e" />
      </div>
      <div v-else-if="!loading" class="empty">
        <p>Aucune sortie n'est programmée dans cette zone pour le moment. 🧸</p>
        <p>
          <RouterLink to="/proposer">Proposez la vôtre</RouterLink> ou
          <RouterLink to="/">voyez les autres régions</RouterLink>.
        </p>
      </div>

      <nav v-if="totalPages > 1" class="pagination">
        <button class="btn ghost small" :disabled="page <= 1" @click="goToPage(page - 1)">
          ← Précédent
        </button>
        <span class="muted">Page {{ page }} / {{ totalPages }}</span>
        <button class="btn ghost small" :disabled="page >= totalPages" @click="goToPage(page + 1)">
          Suivant →
        </button>
      </nav>

      <nav v-if="others.length" class="areas">
        <h2>Où cherchez-vous ?</h2>
        <div class="badges">
          <RouterLink
            v-for="a in others"
            :key="a.slug"
            class="badge"
            :to="`/sorties/${a.slug}`"
          >
            {{ a.name }}
          </RouterLink>
        </div>
      </nav>
    </template>
  </div>
</template>
