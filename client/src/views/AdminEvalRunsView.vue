<script setup lang="ts">
/**
 * Les évaluations : jouer une brique sur le corpus, et voir si ça monte.
 *
 * C'est la moitié que le banc n'avait pas. Avant, mesurer et étiqueter
 * vivaient dans les mêmes lignes : rejouer un agenda supprimait ses pages,
 * donc en cascade les verdicts humains qu'elles portaient. Mesurer détruisait
 * la mesure, et « est-ce que ça s'améliore ? » restait sans réponse.
 *
 * Ici un run ne touche à rien : il rejoue la brique sur le HTML que le corpus
 * a gelé, range son relevé à côté des précédents, et la mesure se calcule de
 * la confrontation des deux. Un run ancien se re-mesure donc contre un corpus
 * qui a grandi depuis — et c'est voulu : c'est le corpus qui fait autorité,
 * pas la photographie qu'on en avait prise.
 */
import { computed, onMounted, ref } from 'vue';
import { api } from '../lib/api';
import type { EvalRun, EvalScore, EvalStage } from '../types';
import {
  EVAL_RUN_STATUS_LABELS,
  EVAL_STAGE_COST,
  EVAL_STAGE_LABELS,
} from '../types';

const runs = ref<EvalRun[]>([]);
const loading = ref(true);
const error = ref('');
const notice = ref('');
const busy = ref(false);

/** `''` : tous les étages confondus. */
const stage = ref<EvalStage | ''>('');
const newStage = ref<EvalStage>('HARVEST');
const newLabel = ref('');

const STAGES: EvalStage[] = ['HARVEST', 'SELECT', 'READ', 'EXTRACT'];

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const params = stage.value ? `?stage=${stage.value}` : '';
    runs.value = (await api.get<{ runs: EvalRun[] }>(`/api/eval/runs${params}`)).runs;
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function launch() {
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    const body = await api.post<{ run: EvalRun }>('/api/eval/runs', {
      stage: newStage.value,
      label: newLabel.value.trim(),
    });
    notice.value =
      `Run #${body.run.id} en file : ${body.run.items} entrée(s) du corpus. ` +
      'Le worker le prendra à sa prochaine passe.';
    newLabel.value = '';
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    busy.value = false;
  }
}

async function forget(run: EvalRun) {
  if (
    !confirm(
      `Oublier le run #${run.id} ? Son relevé disparaît, le corpus et ses ` +
        'étiquettes ne sont pas touchés.',
    )
  ) {
    return;
  }
  try {
    await api.delete(`/api/eval/runs/${run.id}`);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)} %`;
}

/**
 * Le taux qui fait la courbe, quel que soit l'étage.
 *
 * Chaque brique a le sien — rappel pour le dépouillement, textes entiers pour
 * la lecture, champs justes pour l'extraction — et c'est délibéré : un chiffre
 * unique pour quatre questions différentes ne voudrait rien dire. Ils ne se
 * comparent qu'à eux-mêmes, d'un run à l'autre.
 */
function headline(score: EvalScore | undefined): number | null {
  if (!score) return null;
  if (score.kind === 'links') return score.recall;
  return score.rate;
}

/**
 * Ce que le chiffre de tête mesure, dit sans raccourci.
 *
 * « Rappel du tri » était un mensonge court : le tri écarte aussi *à raison* —
 * une sortie hors fenêtre, un concert pour adultes — et compter ces refus
 * comme des oublis faisait baisser le chiffre à mesure que la recherche se
 * précisait. Il ne compte plus que les sorties **pertinentes pour cette
 * recherche**, et seulement sur les pages où le plafond ne lui a pas lié les
 * mains. D'où un nom plus long, mais qui dit ce qu'il compte.
 */
function headlineLabel(stageValue: EvalStage): string {
  if (stageValue === 'HARVEST') return 'rappel';
  if (stageValue === 'SELECT') return 'sorties pertinentes retenues';
  if (stageValue === 'READ') return 'textes entiers';
  return 'champs justes';
}

/** Le détail chiffré, en une ligne lisible. */
function detail(run: EvalRun): string {
  const s = run.score;
  if (!s) return '';
  if (s.kind === 'links') {
    return (
      `${s.found} trouvée(s) · ${s.missed} manquée(s) · ${s.noise} bruit · ` +
      `précision ${pct(s.precision)}` +
      // Du travail bien fait, qui n'apparaissait nulle part : ces refus-là
      // étaient comptés comme des oublis.
      (s.rightlyDropped ? ` · ${s.rightlyDropped} écartée(s) à raison` : '') +
      (s.undecidable ? ` · ${s.undecidable} indécidable(s)` : '') +
      (s.cappedPages
        ? ` · ${s.cappedPages} page(s) au plafond, hors du taux`
        : '') +
      (s.unlabelled ? ` · ${s.unlabelled} lien(s) sans étiquette` : '')
    );
  }
  if (s.kind === 'read') {
    return (
      `${s.textOk}/${s.textJudged} texte(s) entier(s) · ` +
      `${s.imageOk}/${s.imageJudged} image(s) · ${s.datesOk}/${s.datesJudged} date(s) · ` +
      `${s.truncated} tronqué(s) · ${s.tooShort} sous le seuil`
    );
  }
  return (
    `${s.JUSTE} juste(s) · ${s.FAUX} faux · ${s.INVENTE} inventé(s) · ` +
    `${s.MANQUE} manquant(s)` +
    (s.inconnu ? ` · ${s.inconnu} champ(s) sans étiquette` : '')
  );
}

/**
 * Les runs d'un même étage, du plus ancien au plus récent : c'est la courbe.
 *
 * Elle ne vaut que dans un étage : les taux ne mesurent pas la même chose
 * d'une brique à l'autre, et les tracer ensemble ferait une ligne qui ne dit
 * rien.
 */
const series = computed(() => {
  const byStage = new Map<EvalStage, EvalRun[]>();
  for (const run of runs.value) {
    if (run.status !== 'DONE' || headline(run.score) === null) continue;
    const list = byStage.get(run.stage) ?? [];
    list.push(run);
    byStage.set(run.stage, list);
  }
  return [...byStage.entries()].map(([key, list]) => ({
    stage: key,
    runs: [...list].sort((a, b) => a.id - b.id),
  }));
});

/** Ce que le dernier run gagne ou perd sur le précédent. */
function drift(list: EvalRun[]): number | null {
  if (list.length < 2) return null;
  const last = headline(list[list.length - 1].score);
  const before = headline(list[list.length - 2].score);
  return last === null || before === null ? null : last - before;
}

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString('fr-FR') : '—';
}
</script>

<template>
  <div class="container page">
    <h1>Banc d’évaluation — les mesures</h1>
    <nav class="row" style="gap: 1rem; margin-bottom: 1rem">
      <RouterLink to="/admin/evaluation">Corpus et étiquettes</RouterLink>
      <RouterLink to="/admin/evaluation/mesures">Mesures</RouterLink>
    </nav>

    <p class="muted">
      Une mesure rejoue une brique sur le HTML que le corpus a <strong>gelé</strong> :
      un écart entre deux runs ne peut donc venir que du code, jamais du site.
      Rien n’est écrasé — les runs s’empilent, et c’est ce qui permet enfin de
      voir si ça monte.
    </p>

    <!-- ── Lancer ─────────────────────────────────────────────────────── -->
    <div class="card launch">
      <h2>Jouer une mesure</h2>
      <div class="row launch-row">
        <div class="field">
          <label for="ev-stage">Brique</label>
          <select id="ev-stage" v-model="newStage">
            <option v-for="s in STAGES" :key="s" :value="s">{{ EVAL_STAGE_LABELS[s] }}</option>
          </select>
        </div>
        <div class="field grow">
          <label for="ev-label">Étiquette du run</label>
          <input
            id="ev-label"
            v-model="newLabel"
            type="text"
            maxlength="150"
            placeholder="après le correctif d’encodage"
          />
        </div>
        <button class="btn" :disabled="busy" @click="launch()">Mettre en file</button>
      </div>
      <p class="muted small">
        {{ EVAL_STAGE_COST[newStage] }}. L’étiquette n’est pas du décor : c’est
        elle qui rendra ce point de la courbe lisible dans six mois — « run #47 »
        ne dit rien.
      </p>
    </div>

    <p v-if="notice" class="notice">{{ notice }}</p>
    <p v-if="error" class="error">{{ error }}</p>

    <!-- ── La courbe ──────────────────────────────────────────────────── -->
    <h2>Est-ce que ça monte ?</h2>
    <p v-if="!series.length" class="muted">
      Aucune mesure terminée pour l’instant. Le premier run donnera un point ;
      c’est le deuxième qui donnera une réponse.
    </p>
    <div v-for="serie in series" :key="serie.stage" class="card serie">
      <div class="serie-head">
        <h3>{{ EVAL_STAGE_LABELS[serie.stage] }}</h3>
        <span class="muted small">{{ headlineLabel(serie.stage) }}</span>
        <span
          v-if="drift(serie.runs) !== null"
          class="drift"
          :class="{ up: (drift(serie.runs) ?? 0) > 0, down: (drift(serie.runs) ?? 0) < 0 }"
        >
          {{ (drift(serie.runs) ?? 0) > 0 ? '▲' : (drift(serie.runs) ?? 0) < 0 ? '▼' : '=' }}
          {{ Math.abs(Math.round((drift(serie.runs) ?? 0) * 100)) }} pt
        </span>
      </div>
      <!-- Une barre par run, dans l'ordre : la forme la plus honnête pour une
           poignée de points espacés de plusieurs jours. -->
      <ol class="bars">
        <li v-for="run in serie.runs" :key="run.id" :title="`${run.label || 'sans étiquette'} — ${detail(run)}`">
          <span class="bar-col">
            <i :style="{ height: `${Math.round((headline(run.score) ?? 0) * 100)}%` }" />
          </span>
          <span class="bar-val">{{ pct(headline(run.score)) }}</span>
          <span class="bar-tag">{{ run.label || `#${run.id}` }}</span>
        </li>
      </ol>
    </div>

    <!-- ── L'historique ───────────────────────────────────────────────── -->
    <h2>Toutes les mesures</h2>
    <div class="row" style="margin-bottom: 0.8rem">
      <div class="field">
        <label for="ev-filter">Brique</label>
        <select id="ev-filter" v-model="stage" @change="load()">
          <option value="">Toutes</option>
          <option v-for="s in STAGES" :key="s" :value="s">{{ EVAL_STAGE_LABELS[s] }}</option>
        </select>
      </div>
    </div>

    <p v-if="loading" class="muted">Chargement…</p>
    <p v-else-if="!runs.length" class="muted">Aucune mesure.</p>
    <div v-else class="table-wrap card">
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Brique</th>
            <th>Taux</th>
            <th>Détail</th>
            <th>Version</th>
            <th>Coût</th>
            <th>Terminé</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in runs" :key="run.id">
            <td>
              <strong>#{{ run.id }}</strong>
              <div class="muted small">{{ run.label || 'sans étiquette' }}</div>
              <div v-if="run.status !== 'DONE'" class="muted small">
                {{ EVAL_RUN_STATUS_LABELS[run.status] }}
                <span v-if="run.error"> — {{ run.error }}</span>
              </div>
            </td>
            <td>{{ EVAL_STAGE_LABELS[run.stage] }}</td>
            <td class="num">{{ pct(headline(run.score)) }}</td>
            <td class="small">{{ detail(run) }}</td>
            <td class="small">
              <code v-if="run.codeRef">{{ run.codeRef }}</code>
              <span v-else class="muted">version inconnue</span>
              <div v-if="run.model" class="muted">{{ run.model }}</div>
            </td>
            <td class="num">{{ run.costUsd ? `${run.costUsd.toFixed(3)} $` : '—' }}</td>
            <td class="small">{{ when(run.finishedAt) }}</td>
            <td>
              <button class="linklike" @click="forget(run)">Oublier</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card notice-box">
      <p>
        <strong>Un run ne touche jamais au corpus.</strong> Il rejoue la brique
        sur le HTML gelé et range son relevé à côté des précédents. Oublier un
        run efface son relevé, jamais une étiquette.
      </p>
      <p>
        <strong>Les taux ne se comparent qu’à eux-mêmes.</strong> Le rappel du
        dépouillement et la part de champs justes de l’extraction ne mesurent
        pas la même chose : les mettre sur une même courbe ferait une ligne qui
        ne dit rien.
      </p>
      <p>
        <strong>Une mesure ancienne peut bouger.</strong> Elle se recalcule
        contre le corpus d’aujourd’hui, qui a pu grandir depuis. C’est voulu :
        c’est le corpus qui fait autorité, pas la photographie qu’on en avait
        prise — et un run mesuré sur trois étiquettes ne doit pas garder pour
        toujours le taux flatteur que trois étiquettes lui avaient donné.
      </p>
    </div>
  </div>
</template>

<style scoped>
h2 {
  margin-top: 1.6rem;
}

.launch {
  padding: 1rem 1.2rem;
}

.launch h2 {
  margin-top: 0;
}

.launch-row {
  gap: 1rem;
  align-items: flex-end;
  flex-wrap: wrap;
}

.grow {
  flex: 1;
  min-width: 220px;
}

.grow input {
  width: 100%;
  box-sizing: border-box;
}

.serie {
  padding: 1rem 1.2rem;
  margin-bottom: 1rem;
}

.serie-head {
  display: flex;
  align-items: baseline;
  gap: 0.8rem;
  flex-wrap: wrap;
}

.serie-head h3 {
  margin: 0;
}

.drift {
  font-weight: 700;
}

.drift.up {
  color: #1b7f4d;
}

.drift.down {
  color: #b3261e;
}

.bars {
  display: flex;
  align-items: flex-end;
  gap: 1rem;
  list-style: none;
  margin: 1rem 0 0;
  padding: 0;
  overflow-x: auto;
}

.bars li {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.3rem;
  min-width: 72px;
}

.bar-col {
  display: flex;
  align-items: flex-end;
  width: 32px;
  height: 90px;
  background: var(--photo-bg);
  border-radius: 4px;
  overflow: hidden;
}

.bar-col i {
  display: block;
  width: 100%;
  background: var(--accent);
}

.bar-val {
  font-size: 0.85rem;
  font-weight: 700;
}

.bar-tag {
  font-size: 0.75rem;
  color: var(--ink-soft);
  text-align: center;
  max-width: 90px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-wrap {
  overflow-x: auto;
}

.num {
  text-align: right;
  white-space: nowrap;
}

.small {
  font-size: 0.85rem;
}

.notice-box {
  padding: 1rem 1.2rem;
  margin-top: 1.6rem;
}

.notice-box p {
  margin: 0 0 0.7rem;
}

.notice-box p:last-child {
  margin-bottom: 0;
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
