<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api } from '../lib/api';
import type { EventItem } from '../types';
import {
  SETTING_LABELS,
  STATUS_LABELS,
  dayLabel,
  hasCoordinates,
  hasPrice,
  priceLabel,
} from '../types';

/** Résultat de la recherche de doublons pour une sortie de la file. */
interface DuplicateCheck {
  loading: boolean;
  error: string;
  /** `null` tant que la recherche n'a pas abouti. */
  similar: EventItem[] | null;
  open: boolean;
}

const events = ref<EventItem[]>([]);
const loading = ref(true);
const error = ref('');
/** Doublons potentiels, indexés par identifiant de sortie. */
const duplicates = ref<Record<number, DuplicateCheck>>({});

/** Au-delà, on considère le doublon probable plutôt que simplement possible. */
const LIKELY_DUPLICATE_SCORE = 60;

/** Plusieurs recherches en parallèle, sans saturer l'API sur une longue file. */
const CONCURRENCY = 3;

async function checkDuplicates(event: EventItem) {
  const state = duplicates.value[event.id];
  if (!state || state.loading) return;
  state.loading = true;
  state.error = '';
  try {
    const data = await api.get<{ similar: EventItem[] }>(`/api/moderation/${event.id}/similar`);
    state.similar = data.similar;
    // Un doublon probable mérite d'être vu sans avoir à déplier.
    state.open = data.similar.some((s) => (s.similarity?.score ?? 0) >= LIKELY_DUPLICATE_SCORE);
  } catch (e) {
    state.error = e instanceof Error ? e.message : 'Erreur';
  } finally {
    state.loading = false;
  }
}

/** Lance la recherche de doublons sur toute la file, quelques-unes à la fois. */
async function checkAllDuplicates(queue: EventItem[]) {
  const remaining = [...queue];
  const workers = Array.from({ length: CONCURRENCY }, async () => {
    for (let next = remaining.shift(); next; next = remaining.shift()) {
      await checkDuplicates(next);
    }
  });
  await Promise.all(workers);
}

async function load() {
  loading.value = true;
  try {
    const data = await api.get<{ events: EventItem[] }>('/api/moderation/pending');
    events.value = data.events;
    duplicates.value = Object.fromEntries(
      data.events.map((e) => [e.id, { loading: false, error: '', similar: null, open: false }]),
    );
    void checkAllDuplicates(data.events);
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
}

async function moderate(id: number, action: 'approve' | 'reject') {
  let reason: string | undefined;
  if (action === 'reject') {
    reason = prompt('Motif du refus (visible par l’auteur) :') ?? undefined;
    if (reason === undefined) return;
  }
  try {
    await api.post(`/api/moderation/${id}`, { action, reason });
    events.value = events.value.filter((e) => e.id !== id);
    delete duplicates.value[id];
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

/** Refuse la sortie en pointant le doublon trouvé, motif pré-rempli. */
async function rejectAsDuplicate(id: number, original: EventItem) {
  const reason = prompt(
    'Motif du refus (visible par l’auteur) :',
    `Cette sortie fait doublon avec « ${original.title} » (${original.venue.name}), déjà publiée.`,
  );
  if (reason === null) return;
  try {
    await api.post(`/api/moderation/${id}`, { action: 'reject', reason });
    events.value = events.value.filter((e) => e.id !== id);
    delete duplicates.value[id];
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

function periodLabel(e: EventItem) {
  if (e.isPermanent || !e.dateStart || !e.dateEnd) return "toute l'année";
  const periode = `du ${e.dateStart} au ${e.dateEnd}`;
  if (!e.dates.length) return periode;
  return `${periode}, ${e.dates.length} jour(s) de représentation`;
}

/** Ce qu'il reste à compléter avant de pouvoir approuver. */
function incompleteHint(e: EventItem) {
  const missing = [
    !hasCoordinates(e.venue) ? 'l’adresse du lieu' : '',
    !hasPrice(e) ? 'le tarif' : '',
  ].filter(Boolean);
  return missing.length ? `Complétez d’abord ${missing.join(' et ')}` : '';
}

function scoreLevel(score: number) {
  if (score >= LIKELY_DUPLICATE_SCORE) return 'high';
  return score >= 45 ? 'medium' : 'low';
}

onMounted(load);
</script>

<template>
  <div class="container page">
    <h1>Modération</h1>
    <p class="muted">{{ events.length }} sortie(s) en attente d'approbation.</p>
    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="!loading && events.length === 0" class="empty">
      <p>🎉 Rien à modérer, tout est à jour !</p>
    </div>

    <div v-for="e in events" :key="e.id" class="card" style="padding: 1.2rem; margin-bottom: 1rem">
      <div class="badges" style="margin-bottom: 0.4rem">
        <span class="badge price">{{ priceLabel(e) }}</span>
        <span v-if="e.ageMin !== null && e.ageMax !== null" class="badge">{{ e.ageMin }}–{{ e.ageMax }} ans</span>
        <span v-if="e.setting" class="badge">{{ SETTING_LABELS[e.setting] }}</span>
      </div>
      <h3>
        <RouterLink :to="`/sorties/${e.id}`">{{ e.title }}</RouterLink>
      </h3>
      <p class="muted">
        {{ e.venue.name }} · {{ e.venue.city }} ·
        {{ periodLabel(e) }}
        · proposé par {{ e.author.displayName }}
      </p>

      <!-- Sortie importée dont l'adresse n'a pas pu être géocodée. -->
      <p v-if="!hasCoordinates(e.venue)" class="incomplete">
        📍 Lieu non géolocalisé — <strong>{{ e.venue.address || 'adresse à préciser' }}</strong
        >. Cette sortie n'apparaîtra dans aucune recherche par distance : complétez l'adresse
        avant de l'approuver.
        <RouterLink :to="`/sorties/${e.id}/modifier`">Compléter l'adresse</RouterLink>
      </p>

      <!-- Sortie importée dont le tarif n'a pas pu être déterminé. -->
      <p v-if="!hasPrice(e)" class="incomplete">
        🏷 Tarif indéterminé — la page source ne l'indiquait pas clairement.
        Renseignez-le (ou cochez « gratuit ») avant d'approuver.
        <RouterLink :to="`/sorties/${e.id}/modifier`">Compléter le tarif</RouterLink>
      </p>
      <!-- Jours de représentation déduits par l'import : à vérifier, c'est ce
           qui décide des jours où la sortie ressortira dans les recherches. -->
      <p v-if="e.dates.length" class="days">
        <span v-for="day in e.dates" :key="day" class="badge">{{ dayLabel(day) }}</span>
      </p>
      <p style="white-space: pre-line">{{ e.description }}</p>
      <img
        v-if="e.photoUrl"
        :src="e.photoUrl"
        :alt="e.title"
        style="max-width: 280px; border-radius: 10px"
      />

      <!-- Doublons potentiels -->
      <div class="dup" :class="{ 'dup-alert': (duplicates[e.id]?.similar?.length ?? 0) > 0 }">
        <p v-if="duplicates[e.id]?.loading" class="muted dup-status">
          Recherche de doublons…
        </p>
        <p v-else-if="duplicates[e.id]?.error" class="muted dup-status">
          Recherche de doublons indisponible ({{ duplicates[e.id].error }}).
          <button class="linklike" @click="checkDuplicates(e)">Réessayer</button>
        </p>
        <p v-else-if="duplicates[e.id]?.similar?.length === 0" class="muted dup-status">
          ✓ Aucune sortie similaire trouvée.
        </p>
        <template v-else-if="duplicates[e.id]?.similar">
          <button class="linklike dup-toggle" @click="duplicates[e.id].open = !duplicates[e.id].open">
            ⚠ {{ duplicates[e.id].similar!.length }} sortie(s) similaire(s) —
            {{ duplicates[e.id].open ? 'masquer' : 'vérifier le doublon' }}
          </button>

          <ul v-if="duplicates[e.id].open" class="dup-list">
            <li v-for="s in duplicates[e.id].similar!" :key="s.id" class="dup-item">
              <div class="dup-head">
                <span class="dup-score" :class="`dup-score-${scoreLevel(s.similarity?.score ?? 0)}`">
                  {{ s.similarity?.score }}/100
                </span>
                <a :href="`/sorties/${s.id}`" target="_blank" rel="noopener">{{ s.title }}</a>
                <span class="badge" :class="`status-${s.status}`">{{ STATUS_LABELS[s.status] }}</span>
              </div>
              <p class="muted dup-meta">
                {{ s.venue.name }} · {{ s.venue.city }} · {{ periodLabel(s) }}
                · proposé par {{ s.author.displayName }}
              </p>
              <div class="badges">
                <span v-for="reason in s.similarity?.reasons ?? []" :key="reason" class="badge">
                  {{ reason }}
                </span>
              </div>
              <button class="linklike dup-action" @click="rejectAsDuplicate(e.id, s)">
                ✕ Refuser comme doublon de cette sortie
              </button>
            </li>
          </ul>
        </template>
      </div>

      <div class="row" style="margin-top: 0.8rem">
        <button
          class="btn"
          :disabled="!hasCoordinates(e.venue) || !hasPrice(e)"
          :title="incompleteHint(e)"
          @click="moderate(e.id, 'approve')"
        >
          ✓ Approuver
        </button>
        <button class="btn danger" @click="moderate(e.id, 'reject')">✕ Refuser</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.days {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin: 0.4rem 0;
}

.incomplete {
  margin: 0.6rem 0 0;
  padding: 0.6rem 0.8rem;
  border-radius: 12px;
  background: var(--warn-soft);
  color: var(--warn);
  font-size: 0.9rem;
}

.incomplete a {
  color: var(--warn);
  font-weight: 600;
  white-space: nowrap;
}

.dup {
  margin-top: 0.9rem;
  padding: 0.6rem 0.8rem;
  border-radius: 12px;
  background: var(--bg);
  border: 1.3px solid var(--line);
}

.dup-alert {
  background: var(--warn-soft);
  border-color: transparent;
}

.dup-status {
  margin: 0;
}

.linklike {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  color: var(--accent-dark);
  cursor: pointer;
  text-decoration: underline;
}

.dup-toggle {
  font-weight: 600;
  color: var(--warn);
}

.dup-list {
  list-style: none;
  margin: 0.7rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}

.dup-item {
  background: var(--card);
  border: 1.3px solid var(--line);
  border-radius: 12px;
  padding: 0.6rem 0.8rem;
}

.dup-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  font-weight: 600;
}

.dup-score {
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
}

.dup-score-high {
  background: var(--danger-soft);
  color: var(--danger);
}

.dup-score-medium {
  background: var(--warn-soft);
  color: var(--warn);
}

.dup-score-low {
  background: var(--photo-bg);
  color: var(--ink-soft);
}

.dup-meta {
  margin: 0.25rem 0 0.4rem;
}

.dup-action {
  margin-top: 0.5rem;
  color: var(--danger);
  font-size: 0.85rem;
}
</style>
