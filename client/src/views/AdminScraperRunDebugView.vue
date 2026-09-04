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
import type {
  ScraperRun,
  ScraperRunLog,
  ScraperStageNode,
  ScraperTree,
  ScraperTreeAgenda,
  ScraperTreePage,
} from '../types';
import { AGENDA_STATUS_LABELS, FATE_LABELS, LOG_KIND_LABELS, RUN_STATUS_LABELS } from '../types';

const route = useRoute();
const runId = computed(() => Number(route.params.id));

const run = ref<ScraperRun | null>(null);
const stages = ref<ScraperStageNode[]>([]);

/**
 * Qui travaille dans une brique, donc qui paie. « mixte » est le cas de la
 * reconnaissance : gratuite tant qu'un signal certain tranche — pagination,
 * JSON-LD, paramètres d'URL — et facturée seulement quand ils se taisent tous.
 */
/**
 * Ce qu'un étage a coûté sur ce run. Un étage gratuit le dit plutôt que
 * d'afficher « 0,0000 $ », qui se lit mal et n'apprend rien.
 */
function money(s: ScraperStageNode): string {
  if (!s.calls) return 'gratuit';
  return `${s.costUsd.toFixed(4).replace('.', ',')} $`;
}

/** Le détail au survol : d'où vient la somme. */
function detail(s: ScraperStageNode): string {
  if (!s.calls) return 'Python seul : aucun appel au modèle.';
  const parts = [`${s.calls} appel(s)`, `${s.tokens.toLocaleString('fr-FR')} jetons`];
  if (s.searches) parts.push(`${s.searches} recherche(s) web`);
  return parts.join(' · ');
}

const ACTORS: Record<string, string> = {
  modele: 'modèle · facturé',
  python: 'python · gratuit',
  mixte: 'mixte · parfois facturé',
};
const outside = ref(0);
const logs = ref<ScraperRunLog[]>([]);
const tree = ref<ScraperTree | null>(null);
/** « arbre » répond à « d'où vient-ce ? », « journal » à « que s'est-il passé ? ». */
const view = ref<'arbre' | 'journal'>('arbre');
const total = ref(0);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref('');

/** Filtres composables. Chacun se retire seul depuis le fil de sélection. */
const filters = ref({
  stage: '',
  kind: '',
  level: '',
  url: '',
  agenda: '',
  page: '',
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
  if (filters.value.agenda) p.set('agenda', filters.value.agenda);
  if (filters.value.page) p.set('page', filters.value.page);
  if (filters.value.q) p.set('q', filters.value.q);
  if (after !== undefined) p.set('after', String(after));
  p.set('limit', String(PAGE));
  return p.toString();
}

async function loadRun() {
  const res = await api.get<{ run: ScraperRun }>(`/api/scraper/runs/${runId.value}`);
  run.value = res.run;
}

async function loadTree() {
  tree.value = await api.get<ScraperTree>(`/api/scraper/runs/${runId.value}/tree`);
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
    await Promise.all([loadRun(), loadGraph(), loadTree(), loadLogs()]);
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

/**
 * Bascule vers le journal, filtré sur une branche de l'arbre.
 *
 * C'est la jonction entre les deux vues : on repère une anomalie dans
 * l'arbre, on ouvre le journal exactement là où elle est, sans avoir à
 * reconstruire le filtre à la main.
 */
function inspect(part: { agenda?: string; page?: string; kind?: string }) {
  reset();
  if (part.agenda) filters.value.agenda = part.agenda;
  if (part.page) filters.value.page = part.page;
  if (part.kind) filters.value.kind = part.kind;
  view.value = 'journal';
}

/** Les liens d'un agenda, chargés seulement quand on les demande. */
const branchLinks = ref<Record<string, ScraperRunLog[]>>({});
const branchLoading = ref('');

async function toggleLinks(agenda: ScraperTreeAgenda, kind: 'link' | 'link_kept') {
  const key = `${kind}:${agenda.url}`;
  if (branchLinks.value[key]) {
    const next = { ...branchLinks.value };
    delete next[key];
    branchLinks.value = next;
    return;
  }
  branchLoading.value = key;
  try {
    const p = new URLSearchParams({ kind, agenda: agenda.url, limit: '500' });
    const res = await api.get<{ logs: ScraperRunLog[] }>(
      `/api/scraper/runs/${runId.value}/logs?${p}`,
    );
    branchLinks.value = { ...branchLinks.value, [key]: res.logs };
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    branchLoading.value = '';
  }
}

/** Nœuds d'arbre repliés. Tout est ouvert par défaut : on vient pour voir. */
const collapsed = ref<Set<string>>(new Set());
function fold(key: string) {
  const next = new Set(collapsed.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  collapsed.value = next;
}

/**
 * Ce qu'un étage a produit sur **tout** le run.
 *
 * La brique affichait le dernier passage : « 65 lien(s) extrait(s) » était le
 * compte du sixième agenda, pas celui des six. Les compteurs sont donc
 * additionnés côté serveur, et chaque étage choisit ici ce qu'il en montre.
 */
const STAGE_TOTALS: Record<string, (t: Record<string, number>) => string> = {
  discovery: (t) =>
    [
      t.agendas ? `${t.agendas} agenda(s) à ouvrir` : '',
      t.direct ? `${t.direct} sortie(s) directe(s)` : '',
      t.over_cap ? `${t.over_cap} au-delà du plafond` : '',
    ]
      .filter(Boolean)
      .join(' · '),
  harvest: (t) =>
    [
      `${t.links ?? 0} lien(s) extrait(s) au total`,
      // Les pages suivantes se lisent ici, et nulle part ailleurs : sans
      // elles, un agenda paginé passait pour trois agendas.
      t.pages ? `${t.pages} page(s) téléchargée(s)` : '',
      t.next_pages ? `dont ${t.next_pages} page(s) suivante(s)` : '',
    ]
      .filter(Boolean)
      .join(' · '),
  select: (t) => `${t.kept ?? 0} lien(s) retenu(s) sur ${t.among ?? 0}`,
  read: (t) => `${(t.chars ?? 0).toLocaleString('fr-FR')} caractères lus au total`,
  extract: (t) => `${t.fiches ?? 0} fiche(s) extraite(s)`,
  publish: (t) =>
    [
      t.submitted ? `${t.submitted} proposée(s)` : '',
      t.retained ? `${t.retained} retenue(s)` : '',
    ]
      .filter(Boolean)
      .join(' · ') || 'aucune sortie publiée',
};

function stageTotal(stage: string): string {
  const t = tree.value?.totals?.[stage];
  if (!t) return '';
  return STAGE_TOTALS[stage]?.(t) ?? '';
}

/** Ponctue un motif venu du scraper : deux phrases doivent se séparer. */
function sentence(text: string) {
  const t = text.trim();
  return !t || /[.!?]$/.test(t) ? t : `${t}.`;
}

/** Vert = exploité, gris = écarté sciemment, rouge = raté. */
function fateClass(fate: string) {
  if (fate === 'agenda' || fate === 'direct' || fate === 'depouille') return 'ok';
  if (fate === 'echec') return 'ko';
  return 'off';
}

function outcomeClass(page: ScraperTreePage) {
  if (page.decision === 'submitted') return 'ok';
  if (page.decision === 'skip') return 'off';
  if (page.errors) return 'ko';
  return '';
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
  filters.value = { stage: '', kind: '', level: '', url: '', agenda: '', page: '', q: '' };
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
  if (f.url) out.push({ key: 'url', label: `Page : ${short(f.url)}` });
  if (f.agenda) out.push({ key: 'agenda', label: `Venant de : ${short(f.agenda)}` });
  if (f.page) out.push({ key: 'page', label: `Piste : ${short(f.page)}` });
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

/** Le numéro de l'étage, ou null s'il ne figure pas dans le graphe. */
function stageNumber(stage: string | null) {
  return stages.value.find((s) => s.stage === stage)?.number ?? null;
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

/** Hôte + chemin abrégé : deux pages d'un même site doivent se distinguer. */
function short(url: string, max = 34) {
  const label = host(url) + pathOf(url);
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

/** Le chemin d'une URL, sans son hôte : le titre est déjà à côté. */
function pathOf(url: string) {
  try {
    const u = new URL(url);
    return (u.pathname + u.search).replace(/\/$/, '') || '/';
  } catch {
    return '';
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
      // Une page suivante dit deux choses : ce qu'elle a apporté, et le cumul
      // de l'agenda. La première seule laisserait croire à un second agenda.
      return d.new === undefined
        ? `${s('links')} lien(s) sur ${s('chars')} caractères`
        : `page ${s('page_no')} : ${s('new')} lien(s) de plus, ${s('links')} en tout`;
    case 'next_page':
      return (
        `page ${s('page_no')} du même agenda — ${s('links')} lien(s) jusqu'ici, ` +
        `plafond ${s('budget')}`
      );
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
const BOX_H = 114;
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
          :viewBox="`0 0 ${graphWidth} 190`"
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
                paid: s.actor !== 'python',
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
                {{ ACTORS[s.actor] ?? 'python · gratuit' }}
              </text>
              <text :x="boxX(i) + 14" y="70" class="n-count">{{ s.events }}</text>
              <text :x="boxX(i) + 14 + String(s.events).length * 9 + 6" y="70" class="n-unit">
                événement(s)
              </text>
              <text :x="boxX(i) + 14" y="88" class="n-unit">
                {{ s.passes }} passage(s) · {{ s.seconds }} s
              </text>
              <text :x="boxX(i) + 14" y="106" class="n-cost" :class="{ free: !s.calls }">
                {{ money(s) }}
                <title>{{ detail(s) }}</title>
              </text>
              <text v-if="s.errors" :x="boxX(i) + BOX_W - 14" y="26" class="n-err" text-anchor="end">
                {{ s.errors }} ⚠
              </text>
            </g>
            <text v-if="s.takes" :x="boxX(i)" y="142" class="io">
              ↳ reçoit : {{ clip(s.takes) }}
              <title>{{ s.takes }}</title>
            </text>
            <text v-if="s.gives" :x="boxX(i)" y="160" class="io">
              ↳ rend : {{ clip(s.gives) }}
              <title>{{ s.gives }}</title>
            </text>
            <text v-if="stageTotal(s.stage)" :x="boxX(i)" y="180" class="io done">
              {{ clip(stageTotal(s.stage), 30) }}
              <title>{{ stageTotal(s.stage) }} — cumul des {{ s.passes }} passage(s)</title>
            </text>
          </g>
        </svg>
      </div>
      <p v-else-if="!loading && !total" class="muted">
        Cette exécution n'a pas de journal détaillé. Seules les exécutions lancées
        après la mise en place de cette page en produisent un.
      </p>
      <p v-else-if="!loading" class="muted">
        Le journal de cette exécution ne porte pas le graphe de ses étages : elle
        est antérieure à cette page. Les événements ci-dessous restent lisibles,
        mais leur détail — ce qui entre et sort de chaque brique — n'a pas été
        enregistré. La prochaine exécution l'aura.
      </p>

      <!-- -------------------------------------------------------- onglets -->
      <div class="tabs" role="tablist">
        <button
          class="tab" :class="{ on: view === 'arbre' }" role="tab"
          :aria-selected="view === 'arbre'" @click="view = 'arbre'"
        >
          Arbre — d'où vient chaque sortie
        </button>
        <button
          class="tab" :class="{ on: view === 'journal' }" role="tab"
          :aria-selected="view === 'journal'" @click="view = 'journal'"
        >
          Journal — {{ total.toLocaleString('fr-FR') }} événements
        </button>
      </div>

      <!-- ---------------------------------------------------------- arbre -->
      <template v-if="view === 'arbre'">
        <p v-if="!tree" class="muted">Chargement…</p>
        <template v-else>
          <p v-if="tree.truncated" class="error">
            Journal trop long : l'arbre ne montre que son début. Le journal reste complet.
          </p>

          <!-- 1. les recherches, et ce que chacune a remonté -->
          <template v-if="tree.searches.length">
            <h2>Recherches lancées</h2>
            <ul class="tree">
              <li v-for="s of tree.searches" :key="s.query">
                <div class="node q">
                  <button class="fold" @click="fold(`q:${s.query}`)">
                    {{ collapsed.has(`q:${s.query}`) ? '▸' : '▾' }}
                  </button>
                  <span class="ico" aria-hidden="true">🔎</span>
                  <b>{{ s.query }}</b>
                  <span class="muted small">{{ s.results.length }} résultat(s)</span>
                </div>
                <ul v-if="!collapsed.has(`q:${s.query}`)" class="tree sub">
                  <li v-for="r of s.results" :key="r.url" class="leaf">
                    <span class="dot" :class="fateClass(r.fate)" aria-hidden="true"></span>
                    <a :href="r.url" target="_blank" rel="noopener noreferrer">
                      {{ r.title || host(r.url) }}
                    </a>
                    <span class="muted small">{{ host(r.url) }}</span>
                    <span class="fate" :class="fateClass(r.fate)">{{ FATE_LABELS[r.fate] }}</span>
                  </li>
                </ul>
              </li>
            </ul>
          </template>

          <!-- 2. les agendas, leurs liens et les sorties qu'ils ont données -->
          <h2>Agendas dépouillés</h2>
          <p v-if="!tree.agendas.length" class="muted">Aucun agenda dépouillé.</p>
          <ul class="tree">
            <li v-for="a of tree.agendas" :key="a.url">
              <div class="node ag" :class="{ ko: a.errors > 0 }">
                <button class="fold" @click="fold(`a:${a.url}`)">
                  {{ collapsed.has(`a:${a.url}`) ? '▸' : '▾' }}
                </button>
                <span class="ico" aria-hidden="true">📋</span>
                <a :href="a.url" target="_blank" rel="noopener noreferrer"><b>{{ host(a.url) }}</b></a>
                <span class="muted small path">{{ pathOf(a.url) }}</span>
                <span class="fate" :class="fateClass(a.status)">
                  {{ AGENDA_STATUS_LABELS[a.status] ?? a.status }}
                </span>
                <span v-if="a.errors" class="badge err">{{ a.errors }} erreur(s)</span>
              </div>

              <template v-if="!collapsed.has(`a:${a.url}`)">
                <p class="from">
                  <template v-if="a.fromQuery">
                    remonté par la recherche <b>« {{ a.fromQuery }} »</b>
                  </template>
                  <template v-else>origine inconnue (page de départ, ou requête non journalisée)</template>
                </p>

                <!-- Pourquoi un site remonté par la recherche n'a rien donné. -->
                <p v-if="a.status !== 'depouille'" class="why-not">
                  <b>Jamais dépouillé.</b> {{ sentence(a.statusReason) || 'Motif non journalisé.' }}
                  <template v-if="a.status === 'plafond'">
                    Le plafond se règle par <code>maxAgendas</code>, dans la configuration.
                  </template>
                </p>

                <ul v-if="a.status === 'depouille'" class="tree sub">
                  <li>
                    <div class="node small-node">
                      <button class="fold" @click="toggleLinks(a, 'link')">
                        {{ branchLinks[`link:${a.url}`] ? '▾' : '▸' }}
                      </button>
                      <span>
                        {{ a.links }} lien(s) extrait(s)
                        <span v-if="a.fetched > 1" class="muted small">
                          sur {{ a.fetched }} pages — pagination suivie, un seul agenda
                        </span>
                      </span>
                      <button class="btn tiny ghost" @click="inspect({ agenda: a.url, kind: 'link' })">
                        au journal
                      </button>
                      <span v-if="branchLoading === `link:${a.url}`" class="muted small">chargement…</span>
                    </div>
                    <ul v-if="branchLinks[`link:${a.url}`]" class="tree sub scroller">
                      <li v-for="l of branchLinks[`link:${a.url}`]" :key="l.id" class="leaf">
                        <span class="idx">{{ (l.data as any)?.index }}</span>
                        <a :href="l.url ?? '#'" target="_blank" rel="noopener noreferrer">
                          {{ (l.data as any)?.text || l.url }}
                        </a>
                        <span class="muted small ctx">{{ (l.data as any)?.context }}</span>
                      </li>
                    </ul>
                  </li>

                  <li>
                    <div class="node small-node">
                      <button class="fold" @click="toggleLinks(a, 'link_kept')">
                        {{ branchLinks[`link_kept:${a.url}`] ? '▾' : '▸' }}
                      </button>
                      <span><b>{{ a.kept }}</b> lien(s) retenu(s) par le modèle</span>
                      <button class="btn tiny ghost" @click="inspect({ agenda: a.url, kind: 'link_kept' })">
                        au journal
                      </button>
                    </div>
                    <p v-if="a.droppedReason" class="dropped">
                      Ce que le modèle dit avoir écarté : « {{ a.droppedReason }} »
                    </p>
                    <ul v-if="branchLinks[`link_kept:${a.url}`]" class="tree sub">
                      <li v-for="l of branchLinks[`link_kept:${a.url}`]" :key="l.id" class="leaf">
                        <a :href="l.url ?? '#'" target="_blank" rel="noopener noreferrer">
                          {{ (l.data as any)?.text || l.url }}
                        </a>
                        <span v-if="(l.data as any)?.why" class="muted small ctx">
                          — {{ (l.data as any).why }}
                        </span>
                      </li>
                    </ul>
                  </li>

                  <li>
                    <div class="node small-node">
                      <span class="fold-spacer" aria-hidden="true"></span>
                      <span><b>{{ a.pages.length }}</b> page(s) lue(s) et leur verdict</span>
                    </div>
                    <ul class="tree sub">
                      <li v-for="p of a.pages" :key="p.url" class="leaf page">
                        <span class="dot" :class="outcomeClass(p)" aria-hidden="true"></span>
                        <a :href="p.url" target="_blank" rel="noopener noreferrer">
                          {{ p.title || host(p.url) }}
                        </a>
                        <span class="muted small">{{ p.outcome }}</span>
                        <RouterLink v-if="p.eventId" :to="`/sorties/${p.eventId}`" class="small">
                          voir la sortie
                        </RouterLink>
                        <button class="btn tiny ghost" @click="inspect({ page: p.url })">
                          sa piste
                        </button>
                      </li>
                    </ul>
                  </li>
                </ul>
              </template>
            </li>
          </ul>

          <!-- 3. ce qui n'est venu d'aucun agenda -->
          <template v-if="tree.direct.length">
            <h2>Trouvées sans agenda</h2>
            <p class="muted small">
              Une recherche remonte parfois la page d'une sortie précise : elle
              saute les étages 2 et 3. En mode « site », ce sont les adresses de départ.
            </p>
            <ul class="tree">
              <li v-for="p of tree.direct" :key="p.url" class="leaf page">
                <span class="dot" :class="outcomeClass(p)" aria-hidden="true"></span>
                <a :href="p.url" target="_blank" rel="noopener noreferrer">
                  {{ p.title || host(p.url) }}
                </a>
                <span class="muted small">{{ p.outcome }}</span>
                <button class="btn tiny ghost" @click="inspect({ page: p.url })">sa piste</button>
              </li>
            </ul>
          </template>
        </template>
      </template>

      <!-- ------------------------------------------------------- filtres -->
      <template v-else>
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
            <span v-if="log.stage" class="badge stage" :title="stageLabel(log.stage)">
              {{ stageNumber(log.stage) ?? '·' }}
            </span>
            <span v-else class="badge stage out" title="Hors étage">—</span>
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

.n-cost {
  font-size: 12px;
  font-weight: 600;
  fill: var(--warn);
}
.n-cost.free {
  font-weight: 400;
  opacity: 0.55;
  fill: currentColor;
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

/* ----------------------------------------------------------------- arbre */

.tabs {
  display: flex;
  gap: 0.4rem;
  margin: 1.2rem 0 1rem;
  border-bottom: 2px solid var(--line);
}

.tab {
  border: none;
  background: none;
  font: inherit;
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--ink-soft);
  padding: 0.45rem 0.9rem;
  cursor: pointer;
  border-bottom: 3px solid transparent;
  margin-bottom: -2px;
}

.tab.on {
  color: var(--accent-dark);
  border-bottom-color: var(--accent-dark);
}

ul.tree {
  list-style: none;
  margin: 0.3rem 0;
  padding: 0;
}

ul.tree.sub {
  margin-left: 1.1rem;
  padding-left: 0.9rem;
  border-left: 2px solid var(--line);
}

/* Une liste de deux cents liens ne doit pas noyer le reste de l'arbre. */
ul.tree.scroller {
  max-height: 20rem;
  overflow-y: auto;
}

.node {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0.35rem 0.5rem;
  border-radius: 9px;
}

.node.q,
.node.ag {
  background: var(--card);
  border: 1px solid var(--line);
  margin-top: 0.4rem;
}

.node.ag.ko {
  border-color: var(--danger);
}

.node.small-node {
  font-size: 0.9rem;
  padding: 0.25rem 0.3rem;
}

.fold,
.fold-spacer {
  border: none;
  background: none;
  cursor: pointer;
  font: inherit;
  color: var(--ink-soft);
  padding: 0;
  width: 1rem;
  flex: none;
  text-align: left;
}

.fold-spacer {
  cursor: default;
}

.node .path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 22rem;
}

.from {
  margin: 0.2rem 0 0.3rem 1.6rem;
  font-size: 0.85rem;
  color: var(--ink-soft);
}

li.leaf {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0.18rem 0.2rem;
  font-size: 0.88rem;
}

li.leaf .idx {
  font-variant-numeric: tabular-nums;
  color: var(--ink-soft);
  font-size: 0.75rem;
  min-width: 1.8rem;
}

li.leaf .ctx {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 26rem;
}

/* La pastille dit le verdict d'un coup d'œil, sans lire la phrase. */
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--line);
  flex: none;
}

.dot.ok {
  background: var(--ok);
}

.dot.off {
  background: var(--ink-soft);
}

.dot.ko {
  background: var(--danger);
}

.fate {
  font-size: 0.76rem;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--photo-bg);
  color: var(--ink-soft);
  white-space: nowrap;
}

.fate.ok {
  background: var(--ok-soft);
  color: var(--ok);
}

.fate.ko {
  background: var(--danger-soft);
  color: var(--danger);
}

/* Le pourquoi d'un agenda jamais ouvert : c'est ce qu'on venait chercher. */
.why-not {
  margin: 0.2rem 0 0.5rem 1.6rem;
  padding: 0.5rem 0.8rem;
  border-left: 3px solid var(--warn);
  background: var(--warn-soft);
  border-radius: 0 8px 8px 0;
  font-size: 0.86rem;
}

.dropped {
  margin: 0.1rem 0 0.4rem 2.6rem;
  font-size: 0.83rem;
  color: var(--ink-soft);
  font-style: italic;
}

.badge.err {
  background: var(--danger-soft);
  color: var(--danger);
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
