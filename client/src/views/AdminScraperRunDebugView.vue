<script setup lang="ts">
/**
 * Débogage d'une exécution : le graphe des six étages, et le journal filtrable.
 *
 * Le journal d'un run fait facilement plusieurs milliers de lignes. Le tout
 * afficher serait illisible, et le paginer bêtement ferait perdre le fil. D'où
 * le parti pris : **on part du graphe et on descend**. Cliquer une brique
 * filtre sur son étage, cliquer une ligne filtre sur sa page, et les filtres se
 * composent — chacun est retirable séparément, dans un fil de sélection.
 *
 * Rien n'est chargé d'avance : le journal arrive par tranches, avec un curseur
 * sur `seq` plutôt qu'un décalage, pour que la pagination ne saute ni ne répète
 * de ligne pendant qu'une exécution écrit encore.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ApiError, api } from '../lib/api';
import type { ScraperRun, ScraperRunLog, ScraperStageNode } from '../types';
import { LOG_KIND_LABELS, RUN_STATUS_LABELS } from '../types';

const route = useRoute();
const runId = computed(() => Number(route.params.id));

const run = ref<ScraperRun | null>(null);
const stages = ref<ScraperStageNode[]>([]);
const outside = ref(0);
const logs = ref<ScraperRunLog[]>([]);
const total = ref(0);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref('');

/** Filtres composables. Chacun se retire seul depuis le fil de sélection. */
const filters = ref<{ stage: string; kind: string; level: string; url: string; q: string }>({
  stage: '',
  kind: '',
  level: '',
  url: '',
  q: '',
});

/** Recherche libre : appliquée à la validation, pas à chaque frappe. */
const search = ref('');

const PAGE = 200;

function query(after?: number) {
  const p = new URLSearchParams();
  if (filters.value.stage) p.set('stage', filters.value.stage);
  if (filters.value.kind) p.set('kind', filters.value.kind);
  if (filters.value.level) p.set('level', filters.value.level);
  if (filters.value.url) p.set('url', filters.value.url);
  if (filters.value.q) p.set('q', filters.value.q);
  if (after !== undefined) p.set('after', String(after));
  p.set('limit', String(PAGE));
  return p.toString();
}

async function loadRun() {
  const res = await api.get<{ run: ScraperRun }>(`/api/scraper/runs/${runId.value}`);
  run.value = res.run;
}

async function loadGraph() {
  const res = await api.get<{ stages: ScraperStageNode[]; outside: number }>(
    `/api/scraper/runs/${runId.value}/graph`,
  );
  stages.value = res.stages;
  outside.value = res.outside;
}

async function loadLogs() {
  const res = await api.get<{ logs: ScraperRunLog[]; hasMore: boolean; total: number }>(
    `/api/scraper/runs/${runId.value}/logs?${query()}`,
  );
  logs.value = res.logs;
  hasMore.value = res.hasMore;
  total.value = res.total;
}

async function loadMore() {
  const last = logs.value[logs.value.length - 1];
  if (!last || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const res = await api.get<{ logs: ScraperRunLog[]; hasMore: boolean; total: number }>(
      `/api/scraper/runs/${runId.value}/logs?${query(last.seq)}`,
    );
    logs.value = [...logs.value, ...res.logs];
    hasMore.value = res.hasMore;
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loadingMore.value = false;
  }
}

async function loadAll() {
  try {
    await Promise.all([loadRun(), loadGraph(), loadLogs()]);
    error.value = '';
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      error.value = 'Exécution introuvable';
      clearInterval(timer);
    } else {
      error.value = e instanceof Error ? e.message : 'Erreur';
    }
  } finally {
    loading.value = false;
  }
}

// Un changement de filtre repart du début : le curseur ne veut plus rien dire.
watch(
  filters,
  () => {
    loading.value = true;
    loadLogs()
      .catch((e) => (error.value = e instanceof Error ? e.message : 'Erreur'))
      .finally(() => (loading.value = false));
  },
  { deep: true },
);

let timer: ReturnType<typeof setInterval> | undefined;

onMounted(() => {
  loadAll();
  // Une exécution en cours écrit encore : on la suit. Une exécution terminée
  // ne bouge plus, et l'intervalle s'arrête de lui-même au premier passage.
  timer = setInterval(() => {
    const status = run.value?.status;
    if (status === 'DONE' || status === 'FAILED') {
      clearInterval(timer);
      return;
    }
    loadAll();
  }, 5_000);
});
onUnmounted(() => clearInterval(timer));

// ------------------------------------------------------------------ filtres

function pickStage(stage: string) {
  filters.value.stage = filters.value.stage === stage ? '' : stage;
}

function follow(url: string) {
  // Suivre une page, c'est vouloir son parcours complet : on relâche l'étage,
  // sinon on ne verrait qu'un sixième de ce qu'on cherche.
  filters.value.url = url;
  filters.value.stage = '';
}

function applySearch() {
  filters.value.q = search.value.trim();
}

function clearFilter(key: keyof typeof filters.value) {
  filters.value[key] = '';
  if (key === 'q') search.value = '';
}

function reset() {
  search.value = '';
  filters.value = { stage: '', kind: '', level: '', url: '', q: '' };
}

/**
 * Oublie le journal détaillé de cette exécution.
 *
 * Il est verbeux par construction — chaque lien soumis au tri y figure — et
 * cent exécutions gardées font une table inutilement lourde. Les compteurs de
 * l'exécution et le sort de chaque page, eux, ne bougent pas.
 */
const purging = ref(false);
async function purgeLogs() {
  const question =
    `Oublier les ${total.value} ligne(s) de journal de cette exécution ?\n\n` +
    `Ses compteurs et le sort de chaque page sont conservés — c'est le détail ` +
    `du déroulé qui disparaît, et il ne se reconstitue pas.`;
  if (!confirm(question)) return;
  purging.value = true;
  try {
    await api.delete<{ deleted: number }>(`/api/scraper/runs/${runId.value}/logs`);
    logs.value = [];
    total.value = 0;
    hasMore.value = false;
    stages.value = [];
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    purging.value = false;
  }
}

const active = computed(() => {
  const out: { key: keyof typeof filters.value; label: string }[] = [];
  const f = filters.value;
  if (f.stage) out.push({ key: 'stage', label: `Étage : ${stageLabel(f.stage)}` });
  if (f.kind) out.push({ key: 'kind', label: `Type : ${kindLabel(f.kind)}` });
  if (f.level) out.push({ key: 'level', label: `Gravité : ${f.level}` });
  if (f.url) out.push({ key: 'url', label: `Page : ${host(f.url)}` });
  if (f.q) out.push({ key: 'q', label: `Texte : « ${f.q} »` });
  return out;
});

/** Les types présents dans ce qui est chargé : le filtre ne propose rien de vide. */
const kinds = computed(() => {
  const seen = new Map<string, number>();
  for (const l of logs.value) seen.set(l.kind, (seen.get(l.kind) ?? 0) + 1);
  return [...seen].sort((a, b) => b[1] - a[1]);
});

// ------------------------------------------------------------------ affichage

function stageLabel(stage: string | null) {
  if (!stage) return 'Hors étage';
  const node = stages.value.find((s) => s.stage === stage);
  return node ? `${node.number}. ${node.label}` : stage;
}

function stageNumber(stage: string | null) {
  return stages.value.find((s) => s.stage === stage)?.number ?? 0;
}

function kindLabel(kind: string) {
  return LOG_KIND_LABELS[kind] ?? kind;
}

function host(url: string) {
  try {
    return new URL(url).host.replace(/^www\./, '');
  } catch {
    return url;
  }
}

function time(iso: string) {
  return new Date(iso).toLocaleTimeString('fr-FR');
}

/** La ligne lisible d'un événement — ce qu'on lit sans déplier. */
function summary(log: ScraperRunLog): string {
  const d = (log.data ?? {}) as Record<string, unknown>;
  const s = (k: string) => (d[k] === undefined || d[k] === null ? '' : String(d[k]));
  switch (log.kind) {
    case 'stage_start':
      return `reçoit : ${s('takes')}`;
    case 'stage_end':
      return `${s('produced')} — ${s('seconds')} s`;
    case 'query':
      return s('query');
    case 'search_result':
    case 'fetching':
    case 'seed':
      return s('url') || s('title');
    case 'harvested':
      return `${s('links')} lien(s) sur ${s('chars')} caractères`;
    case 'link':
      return `[${s('index')}] ${s('text')}`;
    case 'link_kept':
      return s('text');
    case 'selected':
      return `${s('kept')} retenu(s) sur ${s('among')}`;
    case 'page':
      return `${s('chars')} caractères · ${s('json_ld')} date(s) JSON-LD · image ${d.image ? 'oui' : 'non'}`;
    case 'prompt':
      return `${s('op')} · ${s('chars')} caractères`;
    case 'usage':
      return `${s('op')} [${s('model')}] ${s('input_tokens')} → ${s('output_tokens')} jetons · ${s('total_usd')} $`;
    case 'extract':
      return `${s('title')} — ${s('venue')}`;
    case 'geocode':
      return d.located ? `${s('query')} → ${s('lat')}, ${s('lng')}` : `échec : ${s('reason')}`;
    case 'schedule':
      return `${s('count')} date(s) [${s('source')}] — ${s('title')}`;
    case 'photo':
      return `${s('status')}`;
    case 'skip':
      return s('reason');
    case 'submit':
      return `#${s('event_id')} ${s('title')}`;
    case 'dry_run':
    case 'candidate':
    case 'direct':
      return s('title') || s('url');
    case 'incomplete':
      return `${s('field')} — ${s('title')}`;
    case 'programme':
      return `${s('found')} sortie(s) relevée(s)`;
    case 'error':
      return `${s('op')} : ${log.message ?? ''}`;
    case 'run_start':
      return s('mode');
    case 'run_end':
      return 'exécution terminée';
    default:
      return log.message ?? '';
  }
}

/** Champs déjà lus dans le résumé : inutile de les répéter dans le détail. */
const SUMMARISED = new Set(['takes', 'gives', 'number', 'label', 'actor', 'stages']);

function details(log: ScraperRunLog) {
  const d = log.data ?? {};
  const rest = Object.entries(d).filter(([k]) => !SUMMARISED.has(k));
  return rest.length ? rest : null;
}

function pretty(value: unknown) {
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

const open = ref<Set<number>>(new Set());
function toggle(id: number) {
  const next = new Set(open.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  open.value = next;
}

// --------------------------------------------------------------- le graphe

/** Géométrie du graphe : six briques en ligne, reliées par des flèches. */
const BOX_W = 178;
const GAP = 26;
const BOX_H = 96;
const graphWidth = computed(() => stages.value.length * BOX_W + (stages.value.length - 1) * GAP);
function boxX(index: number) {
  return index * (BOX_W + GAP);
}

/**
 * Tronque un libellé à la largeur d'une brique.
 *
 * SVG ne sait pas retourner à la ligne, et un texte qui dépasse s'écrit
 * par-dessus la brique suivante. Le texte complet reste lisible dans le
 * journal, et en info-bulle sur la brique.
 */
// 22 caractères : la brique fait 178 px, et le préfixe « ↳ rend : » en
// consomme déjà neuf. Le texte entier reste en info-bulle.
function clip(text: string, max = 22) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
</script>

<template>
  <div class="container page debug">
    <RouterLink :to="`/admin/scraper/runs/${runId}`" class="back">← Détail de l'exécution</RouterLink>

    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="run">
      <h1>
        Débogage — {{ run.config?.name ?? 'Exécution' }}
        <span class="badge" :class="`run-${run.status}`">{{ RUN_STATUS_LABELS[run.status] }}</span>
      </h1>
      <p class="muted small">
        {{ total.toLocaleString('fr-FR') }} événement(s) journalisé(s).
        Le graphe se lit de gauche à droite ; cliquez une brique pour ne garder
        qu'elle, une ligne pour suivre une page d'un bout à l'autre.
      </p>

      <!-- ------------------------------------------------------ le graphe -->
      <div v-if="stages.length" class="graph-wrap">
        <svg
          class="graph"
          :viewBox="`0 0 ${graphWidth} 168`"
          role="img"
          aria-label="Les six étages du pipeline, avec le nombre d'événements et la durée de chacun."
        >
          <defs>
            <marker
              id="dbg-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill="currentColor" />
            </marker>
          </defs>

          <g v-for="(s, i) in stages" :key="s.stage">
            <line
              v-if="i > 0"
              :x1="boxX(i) - GAP + 4"
              :y1="52"
              :x2="boxX(i) - 6"
              :y2="52"
              class="edge"
              marker-end="url(#dbg-arrow)"
            />
            <g
              class="node"
              :class="{
                paid: s.actor === 'modele',
                on: filters.stage === s.stage,
                failed: s.errors > 0,
              }"
              role="button"
              tabindex="0"
              :aria-pressed="filters.stage === s.stage"
              @click="pickStage(s.stage)"
              @keydown.enter.prevent="pickStage(s.stage)"
              @keydown.space.prevent="pickStage(s.stage)"
            >
              <rect :x="boxX(i)" y="4" :width="BOX_W" :height="BOX_H" rx="10" />
              <text :x="boxX(i) + 14" y="26" class="n-num">{{ s.number }}</text>
              <text :x="boxX(i) + 34" y="26" class="n-label">{{ s.label }}</text>
              <text :x="boxX(i) + 14" y="46" class="n-actor">
                {{ s.actor === 'modele' ? 'modèle · facturé' : 'python · gratuit' }}
              </text>
              <text :x="boxX(i) + 14" y="70" class="n-count">{{ s.events }}</text>
              <text :x="boxX(i) + 14 + String(s.events).length * 9 + 6" y="70" class="n-unit">
                événement(s)
              </text>
              <text :x="boxX(i) + 14" y="88" class="n-unit">
                {{ s.passes }} passage(s) · {{ s.seconds }} s
              </text>
              <text v-if="s.errors" :x="boxX(i) + BOX_W - 14" y="26" class="n-err" text-anchor="end">
                {{ s.errors }} ⚠
              </text>
            </g>
            <text :x="boxX(i)" y="122" class="io">
              ↳ reçoit : {{ clip(s.takes) }}
              <title>{{ s.takes }}</title>
            </text>
            <text :x="boxX(i)" y="140" class="io">
              ↳ rend : {{ clip(s.gives) }}
              <title>{{ s.gives }}</title>
            </text>
            <text v-if="s.produced.length" :x="boxX(i)" y="160" class="io done">
              {{ clip(s.produced[s.produced.length - 1], 30) }}
              <title>{{ s.produced.join(" · ") }}</title>
            </text>
          </g>
        </svg>
      </div>
      <p v-else-if="!loading" class="muted">
        Cette exécution n'a pas de journal détaillé. Seules les exécutions lancées
        après la mise en place de cette page en produisent un.
      </p>

      <!-- ------------------------------------------------------- filtres -->
      <div class="logfilters">
        <select v-model="filters.kind" aria-label="Type d'événement">
          <option value="">Tous les types</option>
          <option v-for="[k, n] of kinds" :key="k" :value="k">{{ kindLabel(k) }} ({{ n }})</option>
        </select>
        <select v-model="filters.level" aria-label="Gravité">
          <option value="">Toutes gravités</option>
          <option value="info">Information</option>
          <option value="warn">Avertissement</option>
          <option value="error">Erreur</option>
        </select>
        <form class="searchbox" @submit.prevent="applySearch">
          <input
            v-model="search"
            type="search"
            placeholder="Chercher dans le journal…"
            aria-label="Chercher dans le journal"
          />
          <button class="btn small" type="submit">Chercher</button>
        </form>
      </div>

      <div v-if="active.length" class="chips">
        <span class="muted small">Sélection :</span>
        <button v-for="f of active" :key="f.key" class="chip" @click="clearFilter(f.key)">
          {{ f.label }} <span aria-hidden="true">×</span>
          <span class="sr-only">retirer ce filtre</span>
        </button>
        <button class="btn small ghost" @click="reset">Tout effacer</button>
      </div>

      <!-- ------------------------------------------------------- journal -->
      <p v-if="loading" class="muted">Chargement…</p>
      <p v-else-if="!logs.length" class="muted">
        Aucun événement ne correspond à cette sélection.
      </p>

      <ol v-else class="journal">
        <li
          v-for="log of logs"
          :key="log.id"
          class="entry"
          :class="[`lvl-${log.level}`, { open: open.has(log.id) }]"
        >
          <div class="head" role="button" tabindex="0" @click="toggle(log.id)" @keydown.enter="toggle(log.id)">
            <span class="seq">{{ log.seq }}</span>
            <span class="hour">{{ time(log.at) }}</span>
            <span v-if="log.stage" class="badge stage" :data-n="stageNumber(log.stage)">
              {{ stageNumber(log.stage) }}
            </span>
            <span v-else class="badge stage out">—</span>
            <span class="kind">{{ kindLabel(log.kind) }}</span>
            <span class="sum">{{ summary(log) }}</span>
          </div>
          <div class="tail">
            <a v-if="log.url" :href="log.url" target="_blank" rel="noopener noreferrer" class="small">
              {{ host(log.url) }}
            </a>
            <button v-if="log.url" class="btn tiny ghost" @click="follow(log.url!)">
              Suivre cette page
            </button>
          </div>
          <dl v-if="open.has(log.id) && details(log)" class="detail">
            <template v-for="[k, v] of details(log)!" :key="k">
              <dt>{{ k }}</dt>
              <dd>
                <pre>{{ pretty(v) }}</pre>
              </dd>
            </template>
          </dl>
        </li>
      </ol>

      <div v-if="hasMore" class="more">
        <button class="btn small" :disabled="loadingMore" @click="loadMore">
          {{ loadingMore ? 'Chargement…' : `Charger ${PAGE} événements de plus` }}
        </button>
        <span class="muted small">{{ logs.length }} affiché(s) sur {{ total }}</span>
      </div>

      <p
        v-if="total && (run.status === 'DONE' || run.status === 'FAILED')"
        class="more"
      >
        <button class="btn small ghost" :disabled="purging" @click="purgeLogs">
          {{ purging ? 'Suppression…' : 'Oublier ce journal détaillé' }}
        </button>
        <span class="muted small">
          Un journal garde chaque lien soumis au tri : comptez un millier de
          lignes par exécution. Les compteurs et le sort de chaque page restent.
        </span>
      </p>
    </template>
  </div>
</template>

<style scoped>
/* La console de débogage déborde volontairement du gabarit du site :
   six briques de front ne tiennent pas dans 1080 px. */
.debug {
  max-width: 1360px;
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

/* ---------------------------------------------------------------- graphe */

.graph-wrap {
  overflow-x: auto;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 0.9rem;
  margin: 1rem 0;
}

.graph {
  display: block;
  min-width: 1120px;
  width: 100%;
  height: auto;
  color: var(--ink-soft);
}

.edge {
  stroke: var(--ink-soft);
  stroke-width: 1.6;
}

.node rect {
  fill: var(--bg);
  stroke: var(--line);
  stroke-width: 1.6;
  transition: fill 0.15s;
}

.node {
  cursor: pointer;
}

.node:hover rect,
.node:focus-visible rect {
  fill: var(--accent-soft);
}

.node.paid rect {
  stroke: var(--brand);
}

.node.on rect {
  fill: var(--accent-soft);
  stroke: var(--accent-dark);
  stroke-width: 2.4;
}

.node.failed rect {
  stroke: var(--danger);
}

.n-num {
  font: 700 15px var(--font-display, sans-serif);
  fill: var(--ink);
}

.n-label {
  font:
    600 14px system-ui,
    sans-serif;
  fill: var(--ink);
}

.n-actor {
  font-size: 10.5px;
  fill: var(--ink-soft);
  letter-spacing: 0.03em;
}

.node.paid .n-actor {
  fill: var(--brand-dark);
}

.n-count {
  font: 700 15px system-ui, sans-serif;
  fill: var(--ink);
}

.n-unit {
  font-size: 11px;
  fill: var(--ink-soft);
}

.n-err {
  font: 700 11px system-ui, sans-serif;
  fill: var(--danger);
}

.io {
  font-size: 10.5px;
  fill: var(--ink-soft);
}

.io.done {
  fill: var(--ok);
}

/* --------------------------------------------------------------- filtres */

.logfilters {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  gap: 0.6rem;
  align-items: center;
  margin: 1rem 0 0.6rem;
  padding: 0;
}

/* La feuille globale impose `width: 100%` à tous les champs : sans ces
   largeurs explicites, chaque filtre prend une ligne entière. */
.logfilters select,
.searchbox input {
  width: auto;
  padding: 0.35rem 0.6rem;
  border: 1.5px solid var(--line);
  border-radius: 9px;
  background: var(--card);
  color: inherit;
  font: inherit;
  font-size: 0.88rem;
  line-height: 1.4;
}

.logfilters select {
  flex: 0 0 auto;
  width: auto;
  max-width: 16rem;
}

.searchbox {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex: 0 1 24rem;
}

.searchbox input {
  flex: 1 1 auto;
  min-width: 8rem;
}

.searchbox .btn {
  flex: 0 0 auto;
  white-space: nowrap;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
  margin-bottom: 0.8rem;
}

.chip {
  border: 1px solid var(--accent-dark);
  background: var(--accent-soft);
  color: var(--accent-dark);
  border-radius: 999px;
  padding: 0.18rem 0.7rem;
  font-size: 0.82rem;
  cursor: pointer;
}

.chip:hover {
  background: var(--card);
}

.btn.ghost {
  background: none;
  border: 1px solid var(--line);
  color: var(--ink-soft);
}

.btn.tiny {
  padding: 0.15rem 0.5rem;
  font-size: 0.75rem;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

/* --------------------------------------------------------------- journal */

.journal {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--card);
}

.entry {
  border-bottom: 1px solid var(--line);
  padding: 0.35rem 0.7rem;
}

.entry:last-child {
  border-bottom: none;
}

.entry.lvl-error {
  background: var(--danger-soft);
}

.entry.lvl-warn {
  background: var(--warn-soft);
}

.head {
  display: flex;
  gap: 0.55rem;
  align-items: baseline;
  cursor: pointer;
  font-size: 0.86rem;
}

.seq {
  font-variant-numeric: tabular-nums;
  color: var(--ink-soft);
  font-size: 0.75rem;
  min-width: 2.6rem;
}

.hour {
  font-variant-numeric: tabular-nums;
  color: var(--ink-soft);
  font-size: 0.75rem;
}

.badge.stage {
  min-width: 1.4rem;
  text-align: center;
  padding: 0 0.35rem;
  font-variant-numeric: tabular-nums;
}

.badge.stage.out {
  opacity: 0.6;
}

.kind {
  font-weight: 600;
  white-space: nowrap;
}

.sum {
  color: var(--ink-soft);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tail {
  display: flex;
  gap: 0.6rem;
  align-items: center;
  padding-left: 3.2rem;
}

.detail {
  margin: 0.4rem 0 0.5rem 3.2rem;
  display: grid;
  grid-template-columns: minmax(6rem, max-content) 1fr;
  gap: 0.2rem 0.8rem;
  font-size: 0.82rem;
}

.detail dt {
  color: var(--ink-soft);
  font-family: ui-monospace, monospace;
}

.detail dd {
  margin: 0;
  min-width: 0;
}

.detail pre {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: ui-monospace, monospace;
  font-size: 0.78rem;
  max-height: 16rem;
  overflow: auto;
}

.more {
  display: flex;
  gap: 0.8rem;
  align-items: center;
  margin: 0.8rem 0;
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
