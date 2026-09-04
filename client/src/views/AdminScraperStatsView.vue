<script setup lang="ts">
/**
 * Tableau de bord du scraping.
 *
 * La console dit ce qu'une exécution a fait ; elle ne dit pas d'où vient le
 * catalogue. Deux parts répondent à ça : celle de chaque domaine source — un
 * agenda qui coûte cent pages pour deux sorties n'est pas une bonne source —
 * et celle de chaque catégorie, qui montre ce que les recherches en place
 * laissent de côté.
 */
import { computed, onMounted, ref, watch } from 'vue';
import { api } from '../lib/api';
import type { ScraperConfig, ScraperStats } from '../types';
import { DECISION_LABELS, STATUS_LABELS } from '../types';

const configs = ref<ScraperConfig[]>([]);
const stats = ref<ScraperStats | null>(null);
const loading = ref(true);
const error = ref('');

/** `0` : toutes les recherches confondues. */
const configId = ref(0);
/** `0` : tout l'historique. */
const days = ref(0);

const PERIODS = [
  { value: 0, label: 'Depuis toujours' },
  { value: 7, label: '7 jours' },
  { value: 30, label: '30 jours' },
  { value: 90, label: '90 jours' },
];

async function load() {
  loading.value = true;
  error.value = '';
  const params = new URLSearchParams();
  if (configId.value) params.set('configId', String(configId.value));
  if (days.value) params.set('days', String(days.value));
  try {
    stats.value = await api.get<ScraperStats>(`/api/scraper/stats?${params}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  try {
    const data = await api.get<{ configs: ScraperConfig[] }>('/api/scraper/configs');
    configs.value = data.configs;
  } catch {
    // Le sélecteur de recherche est un confort : son échec ne doit pas
    // emporter les statistiques elles-mêmes.
  }
  await load();
});

watch([configId, days], load);

/** Part en pourcentage, sur un total qui peut être nul. */
function share(value: number, total: number): number {
  return total > 0 ? Math.round((value / total) * 1000) / 10 : 0;
}

const pagesTotal = computed(() =>
  (stats.value?.domains ?? []).reduce((sum, d) => sum + d.pages, 0),
);
const categoryTotal = computed(() =>
  (stats.value?.categories ?? []).reduce((sum, c) => sum + c.events, 0),
);
const decisionTotal = computed(() =>
  (stats.value?.decisions ?? []).reduce((sum, d) => sum + d.count, 0),
);

/** Sorties importées, tous statuts confondus. */
const moderated = computed(() => {
  const s = stats.value?.statuses ?? {};
  return (s.APPROVED ?? 0) + (s.PENDING ?? 0) + (s.REJECTED ?? 0);
});

/**
 * Taux d'approbation : la seule mesure de qualité d'une recherche. Les
 * sorties encore en attente ne comptent pas — elles n'ont pas été jugées.
 */
const approvalRate = computed(() => {
  const s = stats.value?.statuses ?? {};
  const judged = (s.APPROVED ?? 0) + (s.REJECTED ?? 0);
  return judged > 0 ? Math.round(((s.APPROVED ?? 0) / judged) * 100) : null;
});

function decisionLabel(decision: string) {
  return DECISION_LABELS[decision] ?? decision;
}
</script>

<template>
  <div class="container page">
    <h1>Recherche automatique — statistiques</h1>
    <nav class="row" style="gap: 1rem; margin-bottom: 1rem">
      <RouterLink to="/admin/scraper">Recherches et exécutions</RouterLink>
      <RouterLink to="/admin/scraper/agregateurs">Agrégateurs</RouterLink>
      <RouterLink to="/admin/scraper/stats">Statistiques</RouterLink>
      <RouterLink to="/admin/scraper/memoire">Mémoire</RouterLink>
    </nav>

    <p class="muted">
      D'où vient ce que le scraper ramène, et de quoi c'est fait. Une source
      qui coûte beaucoup de pages pour peu de sorties approuvées mérite d'être
      revue ; une catégorie absente dit ce qu'aucune recherche ne couvre.
    </p>

    <div class="row stats-filters">
      <div class="field">
        <label for="st-config">Recherche</label>
        <select id="st-config" v-model.number="configId">
          <option :value="0">Toutes les recherches</option>
          <option v-for="c in configs" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>
      <div class="field">
        <label for="st-days">Période</label>
        <select id="st-days" v-model.number="days">
          <option v-for="p in PERIODS" :key="p.value" :value="p.value">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading" class="muted">Chargement…</p>

    <template v-if="stats">
      <!-- Compteurs -->
      <div class="tiles">
        <div class="card tile">
          <span class="value">{{ stats.totals.runs }}</span>
          <span class="label">exécution(s)</span>
        </div>
        <div class="card tile">
          <span class="value">{{ stats.totals.agendas }}</span>
          <!-- Un agenda paginé compte pour un : ses pages suivantes coûtent des
               téléchargements, elles n'ajoutent pas une source. -->
          <span class="label">
            agendas dépouillés
            <template v-if="stats.totals.nextPages">
              ({{ stats.totals.pages }} pages, dont {{ stats.totals.nextPages }} suivantes)
            </template>
          </span>
        </div>
        <div class="card tile">
          <span class="value">{{ stats.totals.submitted }}</span>
          <span class="label">sorties proposées</span>
        </div>
        <div class="card tile">
          <span class="value">{{ approvalRate === null ? '—' : `${approvalRate} %` }}</span>
          <span class="label">approuvées après modération</span>
        </div>
        <div class="card tile">
          <span class="value">{{ stats.totals.costUsd.toFixed(2) }} $</span>
          <span class="label">
            dépensés<template v-if="stats.totals.submitted">
              · {{ (stats.totals.costUsd / stats.totals.submitted).toFixed(3) }} $ la sortie
            </template>
          </span>
        </div>
        <div class="card tile">
          <span class="value">{{ stats.totals.webSearches }}</span>
          <span class="label">recherches web</span>
        </div>
      </div>

      <!-- Sources -->
      <h2>Part de chaque source</h2>
      <p v-if="!stats.domains.length" class="muted">
        Aucune page traitée sur ce périmètre.
      </p>
      <div v-else class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Domaine</th>
              <th>Pages lues</th>
              <th>Part</th>
              <th>Proposées</th>
              <th>Approuvées</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in stats.domains" :key="d.domain">
              <td>{{ d.domain }}</td>
              <td class="num">{{ d.pages }}</td>
              <td class="bar-cell">
                <span class="bar"><i :style="{ width: `${share(d.pages, pagesTotal)}%` }" /></span>
                <span class="pct">{{ share(d.pages, pagesTotal) }} %</span>
              </td>
              <td class="num">{{ d.submitted }}</td>
              <td class="num">{{ d.approved }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Catégories -->
      <h2>Part de chaque catégorie</h2>
      <p v-if="!stats.categories.length" class="muted">
        Aucune sortie importée sur ce périmètre.
      </p>
      <div v-else class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Catégorie</th>
              <th>Sorties</th>
              <th>Part</th>
              <th>Approuvées</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in stats.categories" :key="c.id">
              <td>{{ c.name }}</td>
              <td class="num">{{ c.events }}</td>
              <td class="bar-cell">
                <span class="bar">
                  <i :style="{ width: `${share(c.events, categoryTotal)}%` }" />
                </span>
                <span class="pct">{{ share(c.events, categoryTotal) }} %</span>
              </td>
              <td class="num">{{ c.approved }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Sort des pages -->
      <h2>Sort des pages traitées</h2>
      <p v-if="!stats.decisions.length" class="muted">Rien à montrer.</p>
      <div v-else class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Décision</th>
              <th>Pages</th>
              <th>Part</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in stats.decisions" :key="d.decision">
              <td>{{ decisionLabel(d.decision) }}</td>
              <td class="num">{{ d.count }}</td>
              <td class="bar-cell">
                <span class="bar">
                  <i :style="{ width: `${share(d.count, decisionTotal)}%` }" />
                </span>
                <span class="pct">{{ share(d.count, decisionTotal) }} %</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Devenir des sorties importées -->
      <h2>Devenir des sorties importées</h2>
      <p v-if="!moderated" class="muted">Aucune sortie importée sur ce périmètre.</p>
      <div v-else class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Statut</th>
              <th>Sorties</th>
              <th>Part</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="statut in (['APPROVED', 'PENDING', 'REJECTED'] as const)" :key="statut">
              <td>{{ STATUS_LABELS[statut] }}</td>
              <td class="num">{{ stats.statuses[statut] ?? 0 }}</td>
              <td class="bar-cell">
                <span class="bar">
                  <i :style="{ width: `${share(stats.statuses[statut] ?? 0, moderated)}%` }" />
                </span>
                <span class="pct">{{ share(stats.statuses[statut] ?? 0, moderated) }} %</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Comparaison des recherches -->
      <h2>Par recherche</h2>
      <p class="muted small">
        Indépendant du filtre ci-dessus : c'est ce tableau qui compare les
        recherches entre elles, sur la période choisie.
      </p>
      <p v-if="!stats.configs.length" class="muted">Aucune exécution sur la période.</p>
      <div v-else class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Recherche</th>
              <th>Exécutions</th>
              <th>Retenues</th>
              <th>Proposées</th>
              <th>Coût</th>
              <th>Coût / sortie</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in stats.configs" :key="c.id">
              <td>
                <button class="linklike" type="button" @click="configId = c.id">
                  {{ c.name }}
                </button>
              </td>
              <td class="num">{{ c.runs }}</td>
              <td class="num">{{ c.retained }}</td>
              <td class="num">{{ c.submitted }}</td>
              <td class="num">{{ c.costUsd.toFixed(2) }} $</td>
              <td class="num">
                {{ c.submitted ? `${(c.costUsd / c.submitted).toFixed(3)} $` : '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.stats-filters {
  gap: 1rem;
  margin-bottom: 1.2rem;
}

/* Deux listes déroulantes n'ont pas à occuper toute la largeur de la page. */
.stats-filters .field {
  flex: 0 1 260px;
}

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.8rem;
  margin-bottom: 1.6rem;
}

.tile {
  padding: 0.9rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.tile .value {
  font-size: 1.5rem;
  font-weight: 700;
}

.tile .label {
  font-size: 0.82rem;
  color: var(--ink-soft);
}

h2 {
  margin-top: 1.6rem;
}

.table-wrap {
  overflow-x: auto;
}

.num {
  text-align: right;
  white-space: nowrap;
}

.bar-cell {
  min-width: 160px;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.bar {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: var(--photo-bg);
  overflow: hidden;
}

.bar i {
  display: block;
  height: 100%;
  background: var(--accent);
}

.pct {
  font-size: 0.8rem;
  color: var(--ink-soft);
  white-space: nowrap;
}

.small {
  font-size: 0.85rem;
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
</style>
