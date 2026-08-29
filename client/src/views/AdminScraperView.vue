<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue';
import { api } from '../lib/api';
import type { ScraperConfig, ScraperRun } from '../types';
import { RUN_STATUS_LABELS } from '../types';

const configs = ref<ScraperConfig[]>([]);
const runs = ref<ScraperRun[]>([]);
const error = ref('');
/**
 * Panne de rafraîchissement, distincte d'une erreur d'action. Le tableau se
 * recharge toutes les dix secondes pendant des minutes : une coupure d'une
 * seconde — réveil de veille, Wi-Fi, redémarrage de l'API — ne doit pas
 * peindre une erreur définitive sur une page qui, elle, refonctionne.
 */
const offline = ref('');
const loading = ref(true);
/** Configuration en cours d'édition ; `0` pour une création. */
const editingId = ref<number | null>(null);
const saving = ref(false);

/** Réglages avancés repliés : la plupart des recherches n'y touchent jamais. */
const showAdvanced = ref(false);

const form = reactive({
  name: '',
  theme: '',
  area: 'Île-de-France',
  period: 'les prochaines semaines',
  horizonDays: 30,
  maxEvents: 20,
  maxSearches: 6,
  maxAgendas: 6,
  maxLinksPerAgenda: 8,
  maxPageChars: 8000,
  maxCostUsd: 1,
  keepOutOfScope: true,
  defaultCategory: 'Non classé',
  postalPrefixes: '75,77,78,91,92,93,94,95',
  blockedDomains: '',
  searchModel: 'claude-haiku-4-5',
  selectModel: 'claude-haiku-4-5',
  extractionModel: 'claude-haiku-4-5',
  searchPrompt: '',
  selectPrompt: '',
  extractionPrompt: '',
});

let timer: ReturnType<typeof setInterval> | undefined;
/** Rafraîchissements ratés d'affilée : on n'alerte qu'à partir du second. */
let misses = 0;

async function load() {
  try {
    const [c, r] = await Promise.all([
      api.get<{ configs: ScraperConfig[] }>('/api/scraper/configs'),
      api.get<{ runs: ScraperRun[] }>('/api/scraper/runs'),
    ]);
    configs.value = c.configs;
    runs.value = r.runs;
    misses = 0;
    offline.value = '';
  } catch (e) {
    misses += 1;
    if (misses >= 2) offline.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
}

function reset() {
  Object.assign(form, {
    name: '',
    theme: '',
    area: 'Île-de-France',
    period: 'les prochaines semaines',
    horizonDays: 30,
    maxEvents: 20,
    maxSearches: 6,
    maxAgendas: 6,
    maxLinksPerAgenda: 8,
    maxPageChars: 8000,
    maxCostUsd: 1,
    keepOutOfScope: true,
    defaultCategory: 'Non classé',
    postalPrefixes: '75,77,78,91,92,93,94,95',
    blockedDomains: '',
    searchModel: 'claude-haiku-4-5',
    selectModel: 'claude-haiku-4-5',
    extractionModel: 'claude-haiku-4-5',
    searchPrompt: '',
    selectPrompt: '',
    extractionPrompt: '',
  });
}

function startCreate() {
  reset();
  editingId.value = 0;
  showAdvanced.value = false;
}

function startEdit(config: ScraperConfig) {
  // Champ par champ : la configuration renvoyée par l'API porte aussi son id,
  // sa date et ses compteurs, qui n'ont rien à faire dans le formulaire.
  for (const key of Object.keys(form) as (keyof typeof form)[]) {
    const value = config[key as keyof ScraperConfig];
    if (value !== undefined) (form as Record<string, unknown>)[key] = value ?? '';
  }
  editingId.value = config.id;
  showAdvanced.value = false;
}

function cancel() {
  editingId.value = null;
}

async function save() {
  error.value = '';
  saving.value = true;
  // Un prompt laissé vide veut dire « garde celui du scraper », pas « aucun ».
  const payload = {
    ...form,
    searchPrompt: form.searchPrompt.trim() || null,
    selectPrompt: form.selectPrompt.trim() || null,
    extractionPrompt: form.extractionPrompt.trim() || null,
  };
  try {
    if (editingId.value === 0) {
      await api.post('/api/scraper/configs', payload);
    } else {
      await api.patch(`/api/scraper/configs/${editingId.value}`, payload);
    }
    editingId.value = null;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    saving.value = false;
  }
}

async function toggle(config: ScraperConfig) {
  error.value = '';
  try {
    await api.patch(`/api/scraper/configs/${config.id}`, { enabled: !config.enabled });
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

async function remove(config: ScraperConfig) {
  if (!confirm(`Supprimer la recherche « ${config.name} » et son historique ?`)) return;
  error.value = '';
  try {
    await api.delete(`/api/scraper/configs/${config.id}`);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

async function launch(config: ScraperConfig, submit: boolean) {
  const question = submit
    ? `Lancer « ${config.name} » et proposer les sorties trouvées à la modération ?`
    : `Lancer « ${config.name} » en essai ? Rien ne sera proposé au site.`;
  if (!confirm(question)) return;
  error.value = '';
  try {
    await api.post(`/api/scraper/configs/${config.id}/run`, { submit });
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

async function cancelRun(run: ScraperRun) {
  if (!confirm('Annuler cette exécution ?')) return;
  try {
    await api.post(`/api/scraper/runs/${run.id}/cancel`);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

function when(value: string | null) {
  return value ? new Date(value).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '—';
}

onMounted(() => {
  load();
  // Une exécution passe par la file : sans rafraîchissement, la console
  // resterait figée sur « En file » jusqu'à ce qu'on recharge la page.
  timer = setInterval(load, 10_000);
});
onUnmounted(() => clearInterval(timer));
</script>

<template>
  <div class="container page">
    <h1>Recherche automatique</h1>
    <nav class="row" style="gap: 1rem; margin-bottom: 1rem">
      <RouterLink to="/admin/scraper">Recherches et exécutions</RouterLink>
      <RouterLink to="/admin/scraper/stats">Statistiques</RouterLink>
    </nav>
    <p class="muted">
      Chaque recherche est un angle d'attaque : elle ratisse son thème et ramasse au passage
      ce que les autres manquent. Le thème, la période et la zone orientent la recherche —
      ils ne filtrent pas le résultat, parce qu'une page déjà lue est déjà payée.
    </p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="offline" class="error">
      Le site ne répond plus ({{ offline }}). Le tableau ci-dessous date de la
      dernière réponse ; la recherche en cours, elle, tourne sur le serveur et
      n'est pas affectée. Nouvelle tentative dans quelques secondes.
    </p>

    <!-- Formulaire -->
    <div v-if="editingId !== null" class="card form-card">
      <h2>{{ editingId === 0 ? 'Nouvelle recherche' : 'Modifier la recherche' }}</h2>
      <form class="form" @submit.prevent="save">
        <div class="field">
          <label for="s-name">Nom *</label>
          <input id="s-name" v-model="form.name" type="text" required maxlength="60" />
          <span class="hint">Par exemple « spectacles du week-end » ou « musées et ateliers ».</span>
        </div>

        <div class="field">
          <label for="s-theme">Ce qu'on cherche *</label>
          <textarea id="s-theme" v-model="form.theme" rows="3" required minlength="10" />
          <span class="hint">
            En une phrase, comme à un humain : « des spectacles, théâtres et contes pour
            enfants de 0 à 12 ans ».
          </span>
        </div>

        <div class="row">
          <div class="field">
            <label for="s-area">Zone</label>
            <input id="s-area" v-model="form.area" type="text" maxlength="120" />
          </div>
          <div class="field">
            <label for="s-period">Période (en toutes lettres)</label>
            <input id="s-period" v-model="form.period" type="text" maxlength="120" />
          </div>
          <div class="field">
            <label for="s-horizon">Horizon (jours)</label>
            <input id="s-horizon" v-model.number="form.horizonDays" type="number" min="1" max="365" />
          </div>
        </div>

        <div class="row">
          <div class="field">
            <label for="s-max">Sorties max par exécution</label>
            <input id="s-max" v-model.number="form.maxEvents" type="number" min="1" max="100" />
          </div>
          <div class="field">
            <label for="s-cost">Plafond de coût ($)</label>
            <input id="s-cost" v-model.number="form.maxCostUsd" type="number" min="0.05" max="20" step="0.05" />
            <span class="hint">L'exécution s'arrête avant de dépasser.</span>
          </div>
        </div>

        <div class="field">
          <label class="checkbox">
            <input v-model="form.keepOutOfScope" type="checkbox" />
            Garder les sorties hors période ou hors zone
          </label>
          <span class="hint">
            Recommandé. Leur page a déjà été lue et payée ; le site sait filtrer par date
            et par distance, et vous relisez tout en modération.
          </span>
        </div>

        <button type="button" class="linklike" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Masquer' : 'Afficher' }} les réglages avancés
        </button>

        <template v-if="showAdvanced">
          <div class="row">
            <div class="field">
              <label for="s-searches">Recherches web</label>
              <input id="s-searches" v-model.number="form.maxSearches" type="number" min="1" max="20" />
              <span class="hint">0,01 $ pièce.</span>
            </div>
            <div class="field">
              <label for="s-agendas">Agendas ouverts</label>
              <input id="s-agendas" v-model.number="form.maxAgendas" type="number" min="1" max="20" />
              <span class="hint">Gratuit : téléchargés en Python.</span>
            </div>
            <div class="field">
              <label for="s-links">Liens retenus par agenda</label>
              <input id="s-links" v-model.number="form.maxLinksPerAgenda" type="number" min="1" max="50" />
            </div>
            <div class="field">
              <label for="s-chars">Caractères lus par page</label>
              <input id="s-chars" v-model.number="form.maxPageChars" type="number" min="1000" max="40000" step="1000" />
            </div>
          </div>

          <div class="row">
            <div class="field">
              <label for="s-cat">Catégorie par défaut</label>
              <input id="s-cat" v-model="form.defaultCategory" type="text" maxlength="50" />
            </div>
            <div class="field">
              <label for="s-postal">Départements visés</label>
              <input id="s-postal" v-model="form.postalPrefixes" type="text" maxlength="200" />
              <span class="hint">Préfixes de codes postaux, séparés par des virgules.</span>
            </div>
          </div>

          <div class="field">
            <label for="s-blocked">Domaines bloqués</label>
            <input id="s-blocked" v-model="form.blockedDomains" type="text" maxlength="2000" />
            <span class="hint">Séparés par des virgules. Laissez vide pour la liste par défaut.</span>
          </div>

          <div class="row">
            <div class="field">
              <label for="s-m1">Modèle — recherche</label>
              <input id="s-m1" v-model="form.searchModel" type="text" maxlength="60" />
            </div>
            <div class="field">
              <label for="s-m2">Modèle — tri des liens</label>
              <input id="s-m2" v-model="form.selectModel" type="text" maxlength="60" />
            </div>
            <div class="field">
              <label for="s-m3">Modèle — lecture des pages</label>
              <input id="s-m3" v-model="form.extractionModel" type="text" maxlength="60" />
            </div>
          </div>

          <div class="field">
            <label for="s-p1">Prompt — recherche</label>
            <textarea id="s-p1" v-model="form.searchPrompt" rows="4" />
            <span class="hint">Vide : le scraper utilise le sien.</span>
          </div>
          <div class="field">
            <label for="s-p2">Prompt — tri des liens</label>
            <textarea id="s-p2" v-model="form.selectPrompt" rows="4" />
          </div>
          <div class="field">
            <label for="s-p3">Prompt — lecture d'une page</label>
            <textarea id="s-p3" v-model="form.extractionPrompt" rows="4" />
          </div>
        </template>

        <div class="row" style="margin-top: 0.8rem">
          <button class="btn" type="submit" :disabled="saving">
            {{ saving ? 'Enregistrement…' : 'Enregistrer' }}
          </button>
          <button class="btn ghost" type="button" @click="cancel">Annuler</button>
        </div>
      </form>
    </div>

    <button v-else class="btn" @click="startCreate">+ Nouvelle recherche</button>

    <!-- Configurations -->
    <h2 style="margin-top: 1.6rem">Recherches</h2>
    <p v-if="!loading && configs.length === 0" class="muted">
      Aucune recherche pour l'instant.
    </p>

    <div v-for="c in configs" :key="c.id" class="card config">
      <div class="config-head">
        <h3>
          {{ c.name }}
          <span v-if="!c.enabled" class="badge">désactivée</span>
        </h3>
        <span class="muted">{{ c._count?.runs ?? 0 }} exécution(s)</span>
      </div>
      <p class="theme">{{ c.theme }}</p>
      <p class="muted small">
        {{ c.area }} · {{ c.period }} ({{ c.horizonDays }} j) · {{ c.maxEvents }} sorties max ·
        plafond {{ c.maxCostUsd }} $
        <template v-if="c.runs?.length">
          · dernière : {{ RUN_STATUS_LABELS[c.runs[0].status] }} le {{ when(c.runs[0].queuedAt) }}
        </template>
      </p>
      <div class="row">
        <button class="btn small" @click="launch(c, false)">▶ Essai</button>
        <button class="btn small" @click="launch(c, true)">▶ Lancer et proposer</button>
        <button class="btn small ghost" @click="startEdit(c)">Modifier</button>
        <button class="btn small ghost" @click="toggle(c)">
          {{ c.enabled ? 'Désactiver' : 'Activer' }}
        </button>
        <button class="btn small danger" @click="remove(c)">Supprimer</button>
      </div>
    </div>

    <!-- Exécutions -->
    <h2 style="margin-top: 1.6rem">Dernières exécutions</h2>
    <p v-if="!loading && runs.length === 0" class="muted">Aucune exécution.</p>

    <table v-else-if="runs.length" class="runs">
      <thead>
        <tr>
          <th>Recherche</th>
          <th>État</th>
          <th>Mise en file</th>
          <th>Trouvées</th>
          <th>Proposées</th>
          <th>Coût</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in runs" :key="r.id">
          <td>
            <RouterLink :to="`/admin/scraper/runs/${r.id}`">{{ r.config?.name }}</RouterLink>
            <span v-if="!r.submit" class="badge">essai</span>
          </td>
          <td>
            <span class="badge" :class="`run-${r.status}`">{{ RUN_STATUS_LABELS[r.status] }}</span>
          </td>
          <td class="muted small">{{ when(r.queuedAt) }}</td>
          <td>{{ r.retained }} / {{ r.candidates }}</td>
          <td>{{ r.submitted }}</td>
          <td>{{ r.costUsd.toFixed(3) }} $</td>
          <td>
            <button
              v-if="r.status === 'QUEUED' || r.status === 'RUNNING'"
              class="linklike"
              @click="cancelRun(r)"
            >
              Annuler
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.form-card {
  padding: 1.2rem;
  margin-bottom: 1.2rem;
}

.config {
  padding: 1rem 1.2rem;
  margin-bottom: 0.9rem;
}

.config-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
}

.config-head h3 {
  margin: 0;
}

.theme {
  margin: 0.3rem 0;
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

.runs {
  width: 100%;
  border-collapse: collapse;
  background: var(--card);
  border-radius: 12px;
  overflow: hidden;
}

.runs th,
.runs td {
  padding: 0.5rem 0.7rem;
  text-align: left;
  border-bottom: 1px solid var(--line);
}

.runs th {
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
