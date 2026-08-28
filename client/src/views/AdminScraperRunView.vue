<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { api } from '../lib/api';
import type { ScraperRun } from '../types';
import { DECISION_LABELS, RUN_STATUS_LABELS } from '../types';

const route = useRoute();
const run = ref<ScraperRun | null>(null);
const error = ref('');
const loading = ref(true);

let timer: ReturnType<typeof setInterval> | undefined;

async function load() {
  try {
    const res = await api.get<{ run: ScraperRun }>(`/api/scraper/runs/${route.params.id}`);
    run.value = res.run;
    // Une exécution terminée ne bouge plus : inutile de continuer à interroger.
    if (res.run.status === 'DONE' || res.run.status === 'FAILED') clearInterval(timer);
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
    clearInterval(timer);
  } finally {
    loading.value = false;
  }
}

const items = computed(() => run.value?.items ?? []);

/** Une ligne par décision, pour lire d'un coup ce que le run a fait. */
const tally = computed(() => {
  const counts = new Map<string, number>();
  for (const item of items.value) counts.set(item.decision, (counts.get(item.decision) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1]);
});

const duration = computed(() => {
  const r = run.value;
  if (!r?.startedAt) return null;
  const end = r.finishedAt ? new Date(r.finishedAt) : new Date();
  const seconds = Math.round((end.getTime() - new Date(r.startedAt).getTime()) / 1000);
  if (seconds < 60) return `${seconds} s`;
  return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, '0')} s`;
});

function label(decision: string) {
  return DECISION_LABELS[decision] ?? decision;
}

/** Les décisions qui ont coûté une lecture de page, par opposition aux écarts. */
function isKept(decision: string) {
  return decision === 'submitted' || decision === 'dry_run';
}

function when(value: string | null) {
  return value ? new Date(value).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'medium' }) : '—';
}

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

onMounted(() => {
  load();
  timer = setInterval(load, 5_000);
});
onUnmounted(() => clearInterval(timer));
</script>

<template>
  <div class="container page">
    <RouterLink to="/admin/scraper" class="back">← Recherche automatique</RouterLink>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading" class="muted">Chargement…</p>

    <template v-if="run">
      <h1>
        {{ run.config?.name ?? 'Exécution' }}
        <span class="badge" :class="`run-${run.status}`">{{ RUN_STATUS_LABELS[run.status] }}</span>
        <span v-if="!run.submit" class="badge">essai</span>
      </h1>
      <p class="muted">
        Mise en file le {{ when(run.queuedAt) }}
        <template v-if="run.requestedBy"> par {{ run.requestedBy.displayName }}</template>
        <template v-if="duration"> · {{ duration }}</template>
      </p>
      <p v-if="run.error" class="error">{{ run.error }}</p>
      <p v-if="!run.submit" class="muted small">
        Exécution d'essai : les sorties trouvées ont été analysées mais rien n'a été proposé
        au site. Elles ne sont pas mémorisées — une exécution réelle les reprendra.
      </p>

      <div class="stats">
        <div class="stat"><b>{{ run.candidates }}</b><span>pages candidates</span></div>
        <div class="stat"><b>{{ run.pages }}</b><span>pages lues</span></div>
        <div class="stat"><b>{{ run.retained }}</b><span>sorties retenues</span></div>
        <div class="stat"><b>{{ run.submitted }}</b><span>proposées</span></div>
        <div class="stat"><b>{{ run.duplicates }}</b><span>doublons</span></div>
        <div class="stat"><b>{{ run.skipped }}</b><span>écartées</span></div>
        <div class="stat"><b>{{ run.errors }}</b><span>erreurs</span></div>
        <div class="stat"><b>{{ run.costUsd.toFixed(3) }} $</b><span>coût</span></div>
      </div>

      <p class="muted small">
        {{ run.inputTokens.toLocaleString('fr-FR') }} jetons en entrée ·
        {{ run.outputTokens.toLocaleString('fr-FR') }} en sortie ·
        {{ run.webSearches }} recherche(s) web
      </p>

      <template v-if="tally.length">
        <h2>Bilan</h2>
        <ul class="tally">
          <li v-for="[decision, count] of tally" :key="decision">
            <span class="badge" :class="{ kept: isKept(decision) }">{{ label(decision) }}</span>
            {{ count }}
          </li>
        </ul>
      </template>

      <h2>Pages analysées</h2>
      <p class="muted small">
        Une page dont le sort est définitif est mémorisée : aucune exécution, quelle que
        soit sa configuration, ne la relira — donc ne la repaiera. Les décisions
        provisoires (déjà connue, doublon, essai, erreur) ne le sont pas.
      </p>
      <p v-if="items.length === 0" class="muted">
        {{ run.status === 'QUEUED' ? "L'exécution n'a pas encore démarré." : 'Aucune page traitée.' }}
      </p>

      <table v-else class="items">
        <thead>
          <tr>
            <th>Page</th>
            <th>Décision</th>
            <th>Détail</th>
            <th>Heure</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>
              <a :href="item.url" target="_blank" rel="noopener noreferrer">
                {{ item.title || host(item.url) }}
              </a>
              <span class="muted small block">{{ host(item.url) }}</span>
            </td>
            <td>
              <span class="badge" :class="{ kept: isKept(item.decision) }">{{ label(item.decision) }}</span>
            </td>
            <td class="muted small">
              <RouterLink v-if="item.eventId" :to="`/sorties/${item.eventId}`">
                Voir la sortie
              </RouterLink>
              <template v-else>{{ item.reason || '—' }}</template>
            </td>
            <td class="muted small">{{ when(item.at) }}</td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>

<style scoped>
.back {
  display: inline-block;
  margin-bottom: 0.8rem;
}

h1 .badge {
  vertical-align: middle;
  margin-left: 0.4rem;
}

.small {
  font-size: 0.85rem;
}

.block {
  display: block;
}

.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.7rem;
  margin: 1rem 0 0.6rem;
}

.stat {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0.6rem 0.9rem;
  min-width: 6.5rem;
}

.stat b {
  display: block;
  font-size: 1.25rem;
}

.stat span {
  font-size: 0.8rem;
  color: var(--ink-soft);
}

.tally {
  list-style: none;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem;
}

.badge.kept {
  background: var(--ok-soft);
  color: var(--ok);
}

.items {
  width: 100%;
  border-collapse: collapse;
  background: var(--card);
  border-radius: 12px;
  overflow: hidden;
}

.items th,
.items td {
  padding: 0.5rem 0.7rem;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--line);
}

.items th {
  font-size: 0.82rem;
  color: var(--ink-soft);
}

.run-QUEUED {
  background: var(--photo-bg);
}

.run-RUNNING {
  background: var(--accent-soft);
  color: var(--accent-dark);
}

.run-DONE {
  background: var(--ok-soft);
  color: var(--ok);
}

.run-FAILED {
  background: var(--danger-soft);
  color: var(--danger);
}
</style>
