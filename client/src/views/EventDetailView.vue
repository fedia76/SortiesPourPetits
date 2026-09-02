<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../lib/api';
import { setPageSeo } from '../lib/seo';
import { useAuthStore } from '../stores/auth';
import type { EventItem } from '../types';
import {
  SETTING_LABELS,
  STATUS_LABELS,
  ageLabel,
  dayLabel,
  hasCoordinates,
  hasPrice,
  nextDate,
  priceLabel,
} from '../types';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const event = ref<EventItem | null>(null);
const error = ref('');

const aujourdhui = new Date().toISOString().slice(0, 10);
const prochaine = computed(() => (event.value ? nextDate(event.value) : undefined));

const canEdit = computed(
  () =>
    event.value &&
    auth.isLoggedIn &&
    (auth.user!.id === event.value.author.id || auth.isModerator),
);

/**
 * La fiche est le seul endroit où la sortie se lit en entier : c'est là qu'un
 * modérateur se décide, et il n'avait aucun moyen de trancher sans repasser
 * par la file d'attente.
 */
const canModerate = computed(
  () => !!event.value && auth.isModerator && event.value.status === 'PENDING',
);

/** Ce qu'il reste à compléter avant de pouvoir approuver (voir lib/incomplete.ts). */
const incompleteHint = computed(() => {
  if (!event.value) return '';
  const missing = [
    !hasCoordinates(event.value.venue) ? 'l’adresse du lieu' : '',
    !hasPrice(event.value) ? 'le tarif' : '',
  ].filter(Boolean);
  return missing.length ? `Complétez d’abord ${missing.join(' et ')}.` : '';
});

const moderating = ref(false);
const moderationError = ref('');

async function moderate(action: 'approve' | 'reject') {
  if (!event.value) return;
  let reason: string | undefined;
  if (action === 'reject') {
    reason = prompt('Motif du refus (visible par l’auteur) :') ?? undefined;
    if (reason === undefined) return;
  }
  moderationError.value = '';
  moderating.value = true;
  try {
    await api.post(`/api/moderation/${event.value.id}`, { action, reason });
    // On relit la fiche plutôt que de deviner : le serveur décide du statut,
    // et il peut refuser l'approbation d'une sortie encore incomplète.
    const data = await api.get<{ event: EventItem }>(`/api/events/${event.value.id}`);
    event.value = data.event;
  } catch (e) {
    moderationError.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    moderating.value = false;
  }
}

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

/**
 * Le titre et la description de la fiche, une fois la sortie chargée.
 *
 * Le serveur les a déjà écrits pour la sortie demandée à l'ouverture du site ;
 * ici, on couvre le cas où on arrive sur la fiche par un clic, sans que le
 * document ait été rechargé. Une sortie qui n'est pas encore publique reste
 * hors des moteurs : c'est ce que dit `noindex`, et c'est déjà ce que dit le
 * 404 du serveur.
 */
function applySeo(item: EventItem) {
  const description = item.description.replace(/\s+/g, ' ').trim();
  setPageSeo({
    title: `${item.title} à ${item.venue.city}`,
    description: description.length > 160 ? `${description.slice(0, 159).trimEnd()}…` : description,
    path: `/sorties/${item.id}`,
    noindex: item.status !== 'APPROVED',
  });
}

onMounted(async () => {
  try {
    const data = await api.get<{ event: EventItem }>(`/api/events/${route.params.id}`);
    event.value = data.event;
    applySeo(data.event);
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
    setPageSeo({ title: 'Sortie introuvable', noindex: true });
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

      <!-- Modération sur place : la fiche montre tout, autant y trancher. -->
      <div v-if="canModerate" class="card moderation">
        <p class="muted" style="margin: 0">
          Cette sortie attend votre décision.
          <RouterLink to="/moderation">Voir toute la file</RouterLink>
        </p>
        <p v-if="incompleteHint" class="incomplete">
          {{ incompleteHint }}
          <RouterLink :to="`/sorties/${event.id}/modifier`">Compléter la fiche</RouterLink>
        </p>
        <p v-if="moderationError" class="error">{{ moderationError }}</p>
        <div class="row" style="gap: 0.5rem">
          <button
            class="btn"
            type="button"
            :disabled="moderating || !!incompleteHint"
            :title="incompleteHint"
            @click="moderate('approve')"
          >
            ✓ Approuver
          </button>
          <button
            class="btn ghost"
            type="button"
            :disabled="moderating"
            @click="moderate('reject')"
          >
            ✕ Refuser
          </button>
        </div>
      </div>

      <img v-if="event.photoUrl" :src="event.photoUrl" :alt="event.title" class="hero" />

      <div class="detail-grid">
        <div>
          <h2>Description</h2>
          <p style="white-space: pre-line">{{ event.description }}</p>
        </div>

        <aside class="info-panel card">
          <div>
            <dt>Prix</dt>
            <dd>{{ priceLabel(event) }}</dd>
          </div>
          <div v-if="ageLabel(event)">
            <dt>Âges</dt>
            <dd>{{ ageLabel(event) }}</dd>
          </div>
          <div>
            <dt>Dates</dt>
            <dd v-if="event.isPermanent || !event.dateStart || !event.dateEnd">Toute l'année</dd>
            <dd v-else>Du {{ formatDate(event.dateStart!) }} au {{ formatDate(event.dateEnd!) }}</dd>
          </div>
          <div v-if="event.dates.length">
            <dt>Jours de représentation</dt>
            <dd>
              <p v-if="prochaine" class="next">Prochaine : {{ dayLabel(prochaine) }}</p>
              <p v-else class="next">Toutes les dates sont passées.</p>
              <ul class="days">
                <li v-for="day in event.dates" :key="day" :class="{ passe: day < aujourdhui }">
                  {{ dayLabel(day) }}
                </li>
              </ul>
            </dd>
          </div>
          <div v-if="event.setting">
            <dt>Cadre</dt>
            <dd>{{ SETTING_LABELS[event.setting] }}</dd>
          </div>
          <div>
            <dt>Catégorie</dt>
            <dd>{{ event.category.name }}</dd>
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
          <div v-if="event.openTime && event.closeTime">
            <dt>Horaires d'ouverture</dt>
            <dd>{{ event.openTime }} – {{ event.closeTime }}</dd>
          </div>
          <div v-if="event.sourceUrl">
            <dt>Source</dt>
            <dd><a :href="event.sourceUrl" target="_blank" rel="noopener">Voir l'événement ↗</a></dd>
          </div>
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.moderation {
  padding: 1rem 1.2rem;
  margin-bottom: 1.2rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.moderation .incomplete {
  margin: 0;
  color: var(--danger);
}
</style>
