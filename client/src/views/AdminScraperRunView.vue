<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { ApiError, api } from '../lib/api';
import type { ScraperRun } from '../types';
import { DECISION_LABELS, RUN_STATUS_LABELS } from '../types';

const route = useRoute();
const run = ref<ScraperRun | null>(null);
const error = ref('');
/** Compte rendu de la dernière suppression, distinct d'une erreur. */
const notice = ref('');
/** Panne de rafraîchissement — voir AdminScraperView : on continue d'essayer. */
const offline = ref('');
const loading = ref(true);

let timer: ReturnType<typeof setInterval> | undefined;
let misses = 0;

async function load() {
  try {
    const res = await api.get<{ run: ScraperRun }>(`/api/scraper/runs/${route.params.id}`);
    run.value = res.run;
    misses = 0;
    offline.value = '';
    // Une exécution terminée ne bouge plus : inutile de continuer à interroger.
    if (res.run.status === 'DONE' || res.run.status === 'FAILED') clearInterval(timer);
  } catch (e) {
    const message = e instanceof Error ? e.message : 'Erreur';
    // Seule une exécution introuvable est définitive. Une coupure ne doit pas
    // arrêter le suivi d'un run qui, lui, continue sur le serveur.
    if (e instanceof ApiError && e.status === 404) {
      clearInterval(timer);
      error.value = message;
    } else {
      misses += 1;
      if (misses >= 2) offline.value = message;
    }
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

const purging = ref(false);

/** Décisions que le scraper mémorise (voir `store.report(remember=True)`). */
const MEMORISED_DECISIONS = new Set([
  'submitted',
  'irrelevant',
  'invalid',
  'out_of_period',
  'out_of_area',
]);

/**
 * Pages que la purge peut faire oublier.
 *
 * Deux façons de les retrouver, comme côté serveur : la clé de mémorisation,
 * et — pour les exécutions antérieures à ce champ, qui n'en ont pas — la
 * sortie que la page a produite.
 */
const memorised = computed(() => items.value.filter((i) => i.key || i.eventId).length);

/**
 * Une exécution d'avant le suivi des clés a mémorisé des pages qu'on ne sait
 * plus retrouver : celles qui n'ont donné aucune sortie. Le dire plutôt que
 * de laisser croire que la purge est complète.
 */
const partial = computed(() =>
  items.value.some((i) => !i.key && !i.eventId && MEMORISED_DECISIONS.has(i.decision)),
);

/**
 * Supprime tout ce que l'exécution a produit — ses sorties et ce qu'elle a
 * mémorisé — et garde son journal.
 *
 * Les deux vont ensemble : ne supprimer que les sorties laisserait leurs pages
 * mémorisées, donc jamais reproposées, et une recherche mal réglée resterait
 * punie longtemps après sa correction.
 */
async function purge() {
  const r = run.value;
  if (!r) return;
  const sorties = items.value.filter((i) => i.eventId).length;
  const question =
    `Supprimer définitivement les données de cette exécution ?\n\n` +
    `· ${sorties} sortie(s) créée(s), y compris celles déjà publiées sur le site\n` +
    `· ${memorised.value} page(s) oubliée(s) de la mémoire du scraper\n\n` +
    (partial.value
      ? `Cette exécution est antérieure au suivi des clés de mémorisation : les pages ` +
        `qu'elle a écartées sans produire de sortie resteront en mémoire. Pour les ` +
        `oublier, passez par « Recherche auto → Mémoire ».\n\n`
      : '') +
    `Le journal ci-dessous est conservé. Les pages oubliées pourront être relues, ` +
    `donc repayées, par une prochaine exécution.`;
  if (!confirm(question)) return;

  error.value = '';
  purging.value = true;
  try {
    const res = await api.delete<{ events: number; memory: number }>(
      `/api/scraper/runs/${r.id}/data`,
    );
    notice.value =
      `${res.events} sortie(s) supprimée(s) et ${res.memory} page(s) oubliée(s).`;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    purging.value = false;
  }
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
    <p v-if="notice" class="notice">{{ notice }}</p>
    <p v-if="offline" class="error">
      Le site ne répond plus ({{ offline }}). Cette page date de la dernière
      réponse ; l'exécution, elle, tourne sur le serveur. Nouvelle tentative
      dans quelques secondes.
    </p>
    <p v-if="loading && !error" class="muted">Chargement…</p>

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

      <p class="debug-link">
        <RouterLink :to="`/admin/scraper/runs/${run.id}/debug`" class="btn small">
          Journal détaillé et graphe des étages
        </RouterLink>
        <span class="muted small">
          Le déroulé complet, étage par étage : requêtes lancées, liens extraits
          puis retenus, prompts envoyés, jetons consommés. Le tableau ci-dessous
          ne dit que le verdict de chaque page.
        </span>
      </p>

      <div v-if="run.purgedAt" class="purged">
        <b>Données supprimées le {{ when(run.purgedAt) }}.</b>
        Les sorties issues de cette exécution et les pages qu'elle avait mémorisées n'existent
        plus ; les compteurs ci-dessus décrivent ce qu'elle avait fait, pas ce qui reste. Le
        journal, lui, est conservé.
      </div>
      <div v-else-if="run.status === 'DONE' || run.status === 'FAILED'" class="row purge-row">
        <button class="btn small danger" :disabled="purging" @click="purge">
          {{ purging ? 'Suppression…' : 'Supprimer les données de cette exécution' }}
        </button>
        <span class="muted small">
          Ses sorties — publiées comprises — et les {{ memorised }} page(s) qu'elle a
          mémorisées. Le journal reste.
        </span>
      </div>

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
              <RouterLink v-if="item.eventId" :to="`/sorties/${item.eventId}`" class="block">
                Voir la sortie
              </RouterLink>
              <span v-if="item.reason">{{ item.reason }}</span>
              <template v-else-if="!item.eventId">—</template>
            </td>
            <td class="muted small">{{ when(item.at) }}</td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>

<style scoped>
.notice {
  padding: 0.6rem 0.8rem;
  border-radius: 10px;
  background: var(--ok-soft);
  color: var(--ok);
}

.purged {
  padding: 0.7rem 0.9rem;
  margin: 0.8rem 0;
  border-radius: 10px;
  background: var(--photo-bg);
  font-size: 0.9rem;
}

.debug-link {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  flex-wrap: wrap;
  margin: 0.8rem 0;
}

.purge-row {
  align-items: center;
  gap: 0.8rem;
  margin: 0.8rem 0;
  flex-wrap: wrap;
}

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
