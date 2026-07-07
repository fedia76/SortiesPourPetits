<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../lib/api';
import { useAuthStore } from '../stores/auth';
import type { EventItem } from '../types';
import { DAY_NAMES, SETTING_LABELS, STATUS_LABELS } from '../types';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const event = ref<EventItem | null>(null);
const error = ref('');

const canEdit = computed(
  () =>
    event.value &&
    auth.isLoggedIn &&
    (auth.user!.id === event.value.author.id || auth.isModerator),
);

const sortedHours = computed(() =>
  event.value ? [...event.value.openingHours].sort((a, b) => a.dayOfWeek - b.dayOfWeek) : [],
);

const mapsUrl = computed(() => {
  if (!event.value) return '';
  const v = event.value.venue;
  return `https://www.openstreetmap.org/?mlat=${v.lat}&mlon=${v.lng}#map=16/${v.lat}/${v.lng}`;
});

function formatDate(d: string) {
  return new Date(d).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });
}

async function remove() {
  if (!event.value) return;
  if (!confirm('Supprimer définitivement cette sortie ?')) return;
  await api.delete(`/api/events/${event.value.id}`);
  router.push('/mes-sorties');
}

onMounted(async () => {
  try {
    const data = await api.get<{ event: EventItem }>(`/api/events/${route.params.id}`);
    event.value = data.event;
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
});
</script>

<template>
  <div class="container page event-detail">
    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="event">
      <div class="badges" style="margin-bottom: 0.5rem">
        <span v-if="event.status !== 'APPROVED'" :class="`badge status-${event.status}`">
          {{ STATUS_LABELS[event.status] }}
        </span>
      </div>
      <h1>{{ event.title }}</h1>
      <p class="muted">
        Proposée par {{ event.author.displayName }}
        <template v-if="canEdit">
          · <RouterLink :to="`/sorties/${event.id}/modifier`">Modifier</RouterLink>
          · <a href="#" @click.prevent="remove" style="color: var(--danger)">Supprimer</a>
        </template>
      </p>

      <p v-if="event.status === 'REJECTED' && event.rejectionReason" class="error">
        Motif du refus : {{ event.rejectionReason }}
      </p>

      <img v-if="event.photoUrl" :src="event.photoUrl" :alt="event.title" class="hero" />

      <div class="detail-grid">
        <div>
          <h2>Description</h2>
          <p style="white-space: pre-line">{{ event.description }}</p>
        </div>

        <aside class="info-panel card">
          <div>
            <dt>Prix</dt>
            <dd>{{ event.isFree ? 'Gratuit' : `${event.price} €` }}</dd>
          </div>
          <div>
            <dt>Âges</dt>
            <dd>De {{ event.ageMin }} à {{ event.ageMax }} ans</dd>
          </div>
          <div>
            <dt>Dates</dt>
            <dd>Du {{ formatDate(event.dateStart) }} au {{ formatDate(event.dateEnd) }}</dd>
          </div>
          <div>
            <dt>Cadre</dt>
            <dd>{{ SETTING_LABELS[event.setting] }}</dd>
          </div>
          <div>
            <dt>Lieu</dt>
            <dd>
              <strong>{{ event.venue.name }}</strong><br />
              {{ event.venue.address }}<br />
              {{ event.venue.postalCode }} {{ event.venue.city }}<br />
              <a :href="mapsUrl" target="_blank" rel="noopener">Voir sur la carte ↗</a>
            </dd>
          </div>
          <div v-if="sortedHours.length">
            <dt>Horaires d'ouverture</dt>
            <dd>
              <div v-for="(h, i) in sortedHours" :key="i">
                {{ DAY_NAMES[h.dayOfWeek] }} : {{ h.openTime }} – {{ h.closeTime }}
              </div>
            </dd>
          </div>
        </aside>
      </div>
    </template>
  </div>
</template>
