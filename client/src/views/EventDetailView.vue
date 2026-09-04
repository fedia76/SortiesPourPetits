<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../lib/api';
import { setPageSeo } from '../lib/seo';
import { useAuthStore } from '../stores/auth';
import type { EventItem, ScraperRun } from '../types';
import {
  SETTING_LABELS,
  SOURCE_SIGNAL_LABELS,
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

/** `musee-rodin.fr` plutôt qu'une URL de deux cents caractères. */
function hostLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

/**
 * D'où vient la proposition, quand ce n'est pas la page qu'on affiche.
 *
 * Réservée aux modérateurs, et c'est le point de tout ce dispositif : le
 * visiteur veut le musée, pas l'agrégateur qui l'a republié. Le modérateur,
 * lui, a besoin des deux — il vérifie que le scraper a remonté la bonne
 * source, et le signal lui dit quelle confiance y accorder.
 */
const provenance = computed(() => {
  const e = event.value;
  if (!e || !auth.isModerator || !e.foundOnUrl || e.foundOnUrl === e.sourceUrl) return null;
  return { url: e.foundOnUrl, host: hostLabel(e.foundOnUrl) };
});

/** Ce qui a désigné le lien affiché. Vide pour les sorties d'avant l'attribution. */
const sourceSignal = computed(() => {
  const signal = event.value?.sourceUrlSignal;
  if (!signal || !auth.isModerator) return '';
  return SOURCE_SIGNAL_LABELS[signal] ?? signal;
});

// ------------------------------------------- chercher la source à la demande

/**
 * L'étage 7 du scraper, rejoué sur cette fiche seule.
 *
 * Le scraper ne remonte de l'agrégateur à l'organisateur qu'au fil d'une
 * recherche : une sortie déjà publiée dont le lien pointe sur kidiklik y
 * restait pour toujours, et le modérateur qui le voyait n'avait qu'à chercher
 * à la main. Ce bouton met la question en file ; le worker la prend à son
 * prochain passage, et la fiche se met à jour toute seule.
 */
const hunt = ref<ScraperRun | null>(null);
const hunting = ref(false);
const huntError = ref('');
let huntTimer: ReturnType<typeof setInterval> | undefined;

/** Une recherche de source est en file ou en cours : on attend, on la suit. */
const huntRunning = computed(
  () => hunt.value?.status === 'QUEUED' || hunt.value?.status === 'RUNNING',
);

/** Le bouton n'a de sens que sur une fiche qui porte un lien à remonter. */
const canHunt = computed(() => !!event.value?.sourceUrl && auth.isModerator);

async function loadHunt() {
  if (!event.value || !auth.isModerator) return;
  const data = await api.get<{ run: ScraperRun | null }>(
    `/api/scraper/events/${event.value.id}/source`,
  );
  hunt.value = data.run;
  if (huntRunning.value) watchHunt();
  else stopWatchingHunt();
}

/**
 * Suit l'exécution jusqu'à sa fin. Le worker passe toutes les trente
 * secondes : on interroge plus souvent que ça, mais pas au point de marteler
 * l'API pour une réponse qui met une minute à venir.
 */
function watchHunt() {
  if (huntTimer) return;
  huntTimer = setInterval(async () => {
    if (!event.value) return;
    try {
      const data = await api.get<{ run: ScraperRun | null }>(
        `/api/scraper/events/${event.value.id}/source`,
      );
      hunt.value = data.run;
      if (!huntRunning.value) {
        stopWatchingHunt();
        // La fiche a peut-être changé de lien : c'est le site qui l'a écrit,
        // on le relit plutôt que de le deviner.
        const fresh = await api.get<{ event: EventItem }>(`/api/events/${event.value.id}`);
        event.value = fresh.event;
      }
    } catch (e) {
      stopWatchingHunt();
      huntError.value = e instanceof Error ? e.message : 'Erreur';
    }
  }, 5_000);
}

function stopWatchingHunt() {
  clearInterval(huntTimer);
  huntTimer = undefined;
}

async function huntSource() {
  if (!event.value) return;
  huntError.value = '';
  hunting.value = true;
  try {
    const data = await api.post<{ run: ScraperRun }>(
      `/api/scraper/events/${event.value.id}/source`,
    );
    hunt.value = data.run;
    watchHunt();
  } catch (e) {
    huntError.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    hunting.value = false;
  }
}

onUnmounted(stopWatchingHunt);

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
    // Une recherche de source lancée puis quittée doit se retrouver au retour :
    // elle dure une minute, et la page se ferme plus vite que ça.
    if (canHunt.value) await loadHunt();
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
            <dd>
              <a :href="event.sourceUrl" target="_blank" rel="noopener">
                {{ hostLabel(event.sourceUrl) }} ↗
              </a>
              <span v-if="sourceSignal" class="signal">{{ sourceSignal }}</span>

              <!-- L'étage 7 du scraper, rejoué sur cette fiche seule. Réservé
                   au modérateur : c'est lui qui voit qu'un lien pointe sur un
                   agrégateur, et lui seul peut en changer. -->
              <template v-if="canHunt">
                <button
                  class="btn small ghost hunt"
                  :disabled="hunting || huntRunning"
                  @click="huntSource"
                >
                  {{ huntRunning ? 'Recherche en cours…' : 'Chercher la source' }}
                </button>
                <span v-if="huntError" class="hunt-note error">{{ huntError }}</span>
                <span v-else-if="huntRunning" class="hunt-note">
                  En file d'attente : le worker la prendra dans la minute, la
                  fiche se mettra à jour toute seule.
                </span>
                <span v-else-if="hunt?.status === 'FAILED'" class="hunt-note">
                  Dernière recherche en échec{{ hunt.error ? ` : ${hunt.error}` : '' }}.
                  <RouterLink :to="`/admin/scraper/runs/${hunt.id}/debug`">
                    Voir le journal
                  </RouterLink>
                </span>
                <span v-else-if="hunt" class="hunt-note">
                  Dernière recherche terminée.
                  <RouterLink :to="`/admin/scraper/runs/${hunt.id}/debug`">
                    Voir ce qu'elle a essayé
                  </RouterLink>
                </span>
              </template>
            </dd>
          </div>
          <!-- Provenance : la page que la recherche automatique a réellement
               lue, quand ce n'est pas celle qu'on montre. Un modérateur juge
               d'un coup d'œil si le lien remonté est le bon. -->
          <div v-if="provenance">
            <dt>Repérée sur</dt>
            <dd>
              <a :href="provenance.url" target="_blank" rel="noopener">
                {{ provenance.host }} ↗
              </a>
            </dd>
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

/* Le signal ne se lit qu'après le lien : c'est une nuance de confiance, pas
   une information de premier plan. */
.signal {
  display: block;
  font-size: 0.85em;
  opacity: 0.75;
}

/* Chercher la source est un outil de modération, pas une action de la fiche :
   il se range sous le lien, discret, à la taille de ce qu'il vaut. */
.hunt {
  display: inline-block;
  margin-top: 0.4rem;
}

.hunt-note {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.82em;
  opacity: 0.8;
}

.hunt-note.error {
  opacity: 1;
  color: var(--danger);
}
</style>
