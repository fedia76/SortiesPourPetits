<script setup lang="ts">
/**
 * La mémoire des pages déjà analysées.
 *
 * C'est elle qui empêche de relire — donc de repayer — une page connue, et
 * qui évite de reproposer une sortie déjà refusée. Elle est commune à toutes
 * les recherches, ce qui la rend difficile à deviner : une page qu'aucune
 * recherche ne ramène plus y est peut-être retenue par le verdict d'un autre
 * run. D'où cette page, et le bouton qui permet d'oublier.
 */
import { computed, onMounted, ref, watch } from 'vue';
import { api } from '../lib/api';
import type { ScrapedUrlEntry, ScraperMemory } from '../types';
import { DECISION_LABELS, STATUS_LABELS } from '../types';

const memory = ref<ScraperMemory | null>(null);
const loading = ref(true);
const error = ref('');
const notice = ref('');

const q = ref('');
/** Verdict affiché ; vide = tous. */
const decision = ref('');
const page = ref(1);
const purging = ref(false);

const PAGE_SIZE = 50;

async function load() {
  loading.value = true;
  error.value = '';
  const params = new URLSearchParams({ page: String(page.value), pageSize: String(PAGE_SIZE) });
  if (q.value.trim()) params.set('q', q.value.trim());
  if (decision.value) params.set('decision', decision.value);
  try {
    memory.value = await api.get<ScraperMemory>(`/api/scraper/memory?${params}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
}

onMounted(load);
// Un changement de filtre repart de la première page : rester à la page 7
// d'un filtre qui n'a qu'une page afficherait un tableau vide.
watch([q, decision], () => {
  page.value = 1;
  load();
});
watch(page, load);

const total = computed(() => memory.value?.total ?? 0);
const pages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)));
/** Poids de la mémoire entière, filtre courant ignoré. */
const memorized = computed(() =>
  (memory.value?.decisions ?? []).reduce((sum, d) => sum + d.count, 0),
);
const decisionCount = computed(
  () => memory.value?.decisions.find((d) => d.decision === decision.value)?.count ?? 0,
);

function decisionLabel(value: string) {
  return DECISION_LABELS[value] ?? value;
}

function when(value: string) {
  return new Date(value).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
}

/** Ce que le site retiendra du titre d'une page sans titre relevé. */
function entryTitle(entry: ScrapedUrlEntry) {
  return entry.title || entry.event?.title || '—';
}

/**
 * Oublie un lot de pages. Toute la mémoire, ou le seul verdict affiché —
 * c'est presque toujours ce second cas qu'on veut : oublier les erreurs de
 * lecture d'un site alors en panne sans réexposer ce qui est déjà proposé.
 */
async function purge(scope: 'all' | 'decision') {
  const cible = scope === 'decision' ? decision.value : '';
  const combien = scope === 'decision' ? decisionCount.value : memorized.value;
  const quoi =
    scope === 'decision'
      ? `les ${combien} page(s) « ${decisionLabel(cible)} »`
      : `toute la mémoire (${combien} page(s))`;
  const consequence =
    scope === 'decision' && cible !== 'submitted'
      ? 'Elles seront relues — et repayées — au prochain run.'
      : 'Elles seront relues, repayées, et les sorties déjà proposées pourront ' +
        'l’être une seconde fois.';
  if (!confirm(`Oublier ${quoi} ?\n\n${consequence}\n\nCette action est irréversible.`)) return;

  error.value = '';
  notice.value = '';
  purging.value = true;
  try {
    const res = await api.delete<{ deleted: number }>(
      `/api/scraper/memory${cible ? `?decision=${encodeURIComponent(cible)}` : ''}`,
    );
    notice.value = `${res.deleted} page(s) oubliée(s).`;
    page.value = 1;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    purging.value = false;
  }
}
</script>

<template>
  <div class="container page">
    <h1>Recherche automatique — mémoire</h1>
    <nav class="row" style="gap: 1rem; margin-bottom: 1rem">
      <RouterLink to="/admin/scraper">Recherches et exécutions</RouterLink>
      <RouterLink to="/admin/scraper/agregateurs">Agrégateurs</RouterLink>
      <RouterLink to="/admin/scraper/stats">Statistiques</RouterLink>
      <RouterLink to="/admin/scraper/memoire">Mémoire</RouterLink>
    </nav>

    <p class="muted">
      Les pages dont le scraper se souvient, toutes recherches confondues. Une
      page mémorisée n'est plus jamais rouverte : c'est ce qui évite de la
      repayer et de reproposer une sortie déjà refusée. L'adresse affichée est
      la clé normalisée — sans <code>www.</code>, sans paramètres de suivi —
      et non le lien exact rencontré.
    </p>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <!-- Filtres -->
    <div class="row memory-filters">
      <div class="field">
        <label for="m-q">Chercher</label>
        <input id="m-q" v-model.lazy="q" type="search" placeholder="une adresse, un titre…" />
      </div>
      <div class="field">
        <label for="m-decision">Verdict</label>
        <select id="m-decision" v-model="decision">
          <option value="">Tous ({{ memorized }})</option>
          <option v-for="d in memory?.decisions ?? []" :key="d.decision" :value="d.decision">
            {{ decisionLabel(d.decision) }} ({{ d.count }})
          </option>
        </select>
      </div>
    </div>

    <!-- Purge -->
    <div class="card purge">
      <p class="muted" style="margin: 0">
        Oublier des pages les rend à nouveau lisibles par le scraper : elles
        seront relues, donc repayées, et celles qui avaient déjà donné une
        sortie pourront la proposer une seconde fois.
      </p>
      <div class="row" style="gap: 0.5rem">
        <button
          v-if="decision"
          class="btn danger small"
          type="button"
          :disabled="purging || !decisionCount"
          @click="purge('decision')"
        >
          Oublier les {{ decisionCount }} page(s) « {{ decisionLabel(decision) }} »
        </button>
        <button
          class="btn small"
          :class="decision ? 'ghost' : 'danger'"
          type="button"
          :disabled="purging || !memorized"
          @click="purge('all')"
        >
          Purger toute la mémoire ({{ memorized }})
        </button>
      </div>
    </div>

    <p class="muted small">
      {{ total }} page(s) sur ce filtre · page {{ page }} / {{ pages }}
    </p>
    <p v-if="loading" class="muted">Chargement…</p>
    <p v-else-if="!memory?.entries.length" class="muted">Aucune page mémorisée ici.</p>

    <div v-else class="table-wrap card">
      <table>
        <thead>
          <tr>
            <th>Page</th>
            <th>Verdict</th>
            <th>Sortie</th>
            <th>Première fois</th>
            <th>Dernière fois</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in memory.entries" :key="e.id">
            <td class="page-cell">
              <a :href="e.url" target="_blank" rel="noopener">{{ entryTitle(e) }}</a>
              <span class="url">{{ e.url }}</span>
            </td>
            <td><span class="badge">{{ decisionLabel(e.decision) }}</span></td>
            <td>
              <template v-if="e.event">
                <RouterLink :to="`/sorties/${e.event.id}`">{{ e.event.title }}</RouterLink>
                <span class="badge" :class="`status-${e.event.status}`">
                  {{ STATUS_LABELS[e.event.status] }}
                </span>
              </template>
              <span v-else class="muted">—</span>
            </td>
            <td class="muted small">{{ when(e.firstSeen) }}</td>
            <td class="muted small">{{ when(e.lastSeen) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="pages > 1" class="row pager">
      <button class="btn ghost small" :disabled="page <= 1" @click="page -= 1">← Précédent</button>
      <span class="muted small">Page {{ page }} / {{ pages }}</span>
      <button class="btn ghost small" :disabled="page >= pages" @click="page += 1">
        Suivant →
      </button>
    </div>
  </div>
</template>

<style scoped>
.memory-filters {
  gap: 1rem;
  margin-bottom: 1rem;
}

.memory-filters .field {
  flex: 0 1 260px;
}

.purge {
  padding: 0.9rem 1.1rem;
  margin-bottom: 1.2rem;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}

.notice {
  color: var(--ok);
  font-weight: 600;
}

.table-wrap {
  overflow-x: auto;
}

.page-cell {
  max-width: 420px;
}

.page-cell .url {
  display: block;
  font-size: 0.78rem;
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}

.small {
  font-size: 0.85rem;
}

.pager {
  gap: 0.8rem;
  align-items: center;
  margin-top: 0.9rem;
}
</style>
