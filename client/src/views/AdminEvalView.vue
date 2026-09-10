<script setup lang="ts">
/**
 * Le corpus : des entrées gelées, et ce qu'un humain dit qu'elles contiennent.
 *
 * Cette page ne mesure rien, et c'est nouveau. Elle fabrique la seule chose du
 * banc qui coûte cher — l'étiquette — et qui, pour cette raison, ne doit
 * jamais dépendre de ce qu'une brique a rendu : « le tarif rendu est juste »
 * périme au premier changement de prompt, « la page annonce 8 € » vaut pour
 * toujours.
 *
 * La mesure est à côté, sur « Mesures », et elle se calcule de la
 * confrontation des deux.
 *
 * ## La précoche, et pourquoi elle n'est qu'un affichage
 *
 * Étiqueter deux cents liens sur une page vierge serait invivable : la console
 * affiche donc en regard le relevé d'un run, et l'humain n'a plus qu'à
 * confirmer. Mais rien de ce que la brique a dit n'entre au corpus tant que
 * personne n'a cliqué — sans quoi on obtiendrait un rappel de 100 % pour la
 * seule raison que personne n'a regardé, ce qui est très exactement le
 * mensonge que ce banc existe pour éviter.
 */
import { computed, onMounted, ref } from 'vue';
import { api } from '../lib/api';
import type {
  EvalAgenda,
  EvalLinkResult,
  EvalReading,
  EvalSeedCounts,
  EvalVerdict,
} from '../types';
import {
  EVAL_CAPTURE_LABELS,
  EVAL_LABEL_ORIGIN_LABELS,
  EVAL_ORIGIN_HINTS,
  EVAL_ORIGIN_LABELS,
  EVAL_VERDICT_HINTS,
  EVAL_VERDICT_LABELS,
} from '../types';

const VERDICTS: EvalVerdict[] = ['SORTIE', 'PAGINATION', 'SOUS_AGENDA', 'AUTRE'];

const agendas = ref<EvalAgenda[]>([]);
const readings = ref<EvalReading[]>([]);
const seed = ref<EvalSeedCounts | null>(null);
const open = ref<EvalAgenda | null>(null);
const openRunId = ref(0);
const loading = ref(true);
const error = ref('');
const notice = ref('');

const newAgendaUrl = ref('');
const newAgendaPages = ref(1);
const newReadingUrl = ref('');

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const [a, r] = await Promise.all([
      api.get<{ agendas: EvalAgenda[] }>('/api/eval/agendas'),
      api.get<{ readings: EvalReading[] }>('/api/eval/readings'),
    ]);
    agendas.value = a.agendas;
    readings.value = r.readings;
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
  try {
    seed.value = await api.get<EvalSeedCounts>('/api/eval/seed');
  } catch {
    // Les paniers sont un confort : leur échec ne doit pas vider la page.
  }
}

onMounted(load);

function fail(e: unknown) {
  error.value = e instanceof Error ? e.message : 'Erreur';
}

// ── le corpus des agendas ──────────────────────────────────────────────

async function addAgenda() {
  if (!newAgendaUrl.value.trim()) return;
  try {
    await api.post('/api/eval/agendas', {
      url: newAgendaUrl.value.trim(),
      pages: newAgendaPages.value,
    });
    newAgendaUrl.value = '';
    await load();
  } catch (e) {
    fail(e);
  }
}

async function capture(kind: 'agendas' | 'readings', id: number) {
  try {
    await api.post(`/api/eval/${kind}/${id}/capture`);
    notice.value = 'Capture mise en file : le worker la prendra à sa prochaine passe.';
    await load();
  } catch (e) {
    fail(e);
  }
}

async function removeAgenda(agenda: EvalAgenda) {
  if (!confirm(`Retirer « ${agenda.label || agenda.url} » du corpus, avec ses étiquettes ?`)) return;
  try {
    await api.delete(`/api/eval/agendas/${agenda.id}`);
    if (open.value?.id === agenda.id) open.value = null;
    await load();
  } catch (e) {
    fail(e);
  }
}

async function openAgenda(agenda: EvalAgenda) {
  if (open.value?.id === agenda.id) {
    open.value = null;
    return;
  }
  try {
    const body = await api.get<{ agenda: EvalAgenda; runId: number }>(
      `/api/eval/agendas/${agenda.id}`,
    );
    open.value = body.agenda;
    openRunId.value = body.runId;
  } catch (e) {
    fail(e);
  }
}

/** Les liens du relevé affiché, avec l'étiquette qu'ils portent déjà. */
function rows(page: EvalAgenda['agendaPages'][number]) {
  const labelled = new Map(page.links.map((l) => [l.url, l]));
  const seenUrls = new Set<string>();
  const out: { result: EvalLinkResult | null; label: (typeof page.links)[number] | null }[] = [];
  for (const result of page.results ?? []) {
    // La ligne technique de la pagination n'est pas un lien.
    if (result.position < 0) continue;
    seenUrls.add(result.url);
    out.push({ result, label: labelled.get(result.url) ?? null });
  }
  // Les étiquettes que le relevé ne porte pas : un lien ajouté à la main, ou
  // une sortie que la brique ne trouve plus. Les cacher reviendrait à effacer
  // la mesure la plus intéressante.
  for (const label of page.links) {
    if (!seenUrls.has(label.url)) out.push({ result: null, label });
  }
  return out;
}

/** Ce que le relevé affiché a trouvé comme page suivante. */
function foundNext(page: EvalAgenda['agendaPages'][number]): string {
  return (page.results ?? []).find((r) => r.position < 0)?.selectReason ?? '';
}

async function labelLink(pageId: number, url: string, text: string, verdict: EvalVerdict) {
  try {
    await api.put(`/api/eval/pages/${pageId}/links`, { url, text, verdict, source: 'PAGE' });
    await refreshOpen();
  } catch (e) {
    fail(e);
  }
}

async function unlabel(id: number) {
  try {
    await api.delete(`/api/eval/links/${id}`);
    await refreshOpen();
  } catch (e) {
    fail(e);
  }
}

/** Demande l'adresse de la vraie page suivante, et l'étiquette. */
function askNext(pageId: number) {
  const answer = window.prompt('Adresse de la vraie page suivante :');
  if (answer === null) return;
  void labelNext(pageId, answer.trim());
}

async function labelNext(pageId: number, expected: string | null) {
  try {
    await api.patch(`/api/eval/pages/${pageId}/next`, { expected });
    await refreshOpen();
  } catch (e) {
    fail(e);
  }
}

/**
 * Étiqueter d'un coup tous les liens qu'un relevé a écartés sous un motif.
 *
 * L'outil coupe dans les deux sens, et c'est assumé : expédier un motif qu'on
 * n'a pas lu fabrique un rappel flatteur. D'où l'obligation de viser un motif
 * précis plutôt que « tout le reste ».
 */
async function bulk(pageId: number, reason: string, verdict: EvalVerdict) {
  if (!openRunId.value) return;
  if (!confirm(`Étiqueter « ${EVAL_VERDICT_LABELS[verdict]} » tous les liens écartés sous « ${reason} » ?`))
    return;
  try {
    const body = await api.post<{ labelled: number }>(`/api/eval/pages/${pageId}/bulk`, {
      runId: openRunId.value,
      verdict,
      reason,
    });
    notice.value = `${body.labelled} étiquette(s) posée(s).`;
    await refreshOpen();
  } catch (e) {
    fail(e);
  }
}

/** Les motifs de rejet du relevé affiché, avec leur compte. */
function reasons(page: EvalAgenda['agendaPages'][number]) {
  const counts = new Map<string, number>();
  for (const result of page.results ?? []) {
    if (result.position < 0 || result.harvested || !result.dropReason) continue;
    counts.set(result.dropReason, (counts.get(result.dropReason) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

async function refreshOpen() {
  if (!open.value) return;
  const id = open.value.id;
  const body = await api.get<{ agenda: EvalAgenda; runId: number }>(`/api/eval/agendas/${id}`);
  open.value = body.agenda;
  openRunId.value = body.runId;
  await load();
}

// ── le corpus de lecture ───────────────────────────────────────────────

async function addReading() {
  if (!newReadingUrl.value.trim()) return;
  try {
    await api.post('/api/eval/readings', { url: newReadingUrl.value.trim() });
    newReadingUrl.value = '';
    await load();
  } catch (e) {
    fail(e);
  }
}

async function removeReading(reading: EvalReading) {
  if (!confirm(`Retirer « ${reading.label || reading.url} » du corpus, avec ses étiquettes ?`)) return;
  try {
    await api.delete(`/api/eval/readings/${reading.id}`);
    await load();
  } catch (e) {
    fail(e);
  }
}

/** Les trois étiquettes d'une page, saisies en clair. */
const editing = ref<EvalReading | null>(null);
const editImage = ref('');
const editDates = ref('');
const editMarkers = ref('');

function edit(reading: EvalReading) {
  editing.value = reading;
  editImage.value = reading.expectedImage ?? '';
  editDates.value = (JSON.parse(reading.expectedDates ?? '[]') as string[]).join('\n');
  editMarkers.value = (JSON.parse(reading.expectedMarkers ?? '[]') as string[]).join('\n');
}

function lines(value: string): string[] {
  return value
    .split('\n')
    .map((v) => v.trim())
    .filter(Boolean);
}

async function saveLabels(clear = false) {
  const reading = editing.value;
  if (!reading) return;
  try {
    await api.patch(`/api/eval/readings/${reading.id}`, {
      expectedImage: clear ? null : editImage.value.trim(),
      expectedDates: clear ? null : lines(editDates.value),
      expectedMarkers: clear ? null : lines(editMarkers.value),
    });
    editing.value = null;
    await load();
  } catch (e) {
    fail(e);
  }
}

/** Combien d'étiquettes une page porte : trois au plus, celles de l'étage 5. */
function labelled(reading: EvalReading): number {
  return [reading.expectedImage, reading.expectedDates, reading.expectedMarkers].filter(
    (v) => v !== null,
  ).length;
}

// ── peupler le corpus depuis ce que le pipeline a déjà fait ────────────

async function pour(bucket: 'approuvees' | 'abandonnees' | 'illisibles' | 'liens') {
  try {
    const body = await api.post<{ added: number }>('/api/eval/seed', { bucket, limit: 25 });
    notice.value = `${body.added} entrée(s) ajoutée(s) au corpus.`;
    await load();
  } catch (e) {
    fail(e);
  }
}

const corpusSize = computed(() => ({
  agendas: agendas.value.length,
  pages: agendas.value.reduce((n, a) => n + (a.pagesCaptured ?? 0), 0),
  links: agendas.value.reduce((n, a) => n + (a.labels ?? 0), 0),
  readings: readings.value.length,
  readingLabels: readings.value.reduce((n, r) => n + labelled(r), 0),
}));
</script>

<template>
  <div class="container page">
    <h1>Banc d’évaluation — le corpus</h1>
    <nav class="row" style="gap: 1rem; margin-bottom: 1rem">
      <RouterLink to="/admin/evaluation">Corpus et étiquettes</RouterLink>
      <RouterLink to="/admin/evaluation/mesures">Mesures</RouterLink>
    </nav>

    <p class="muted">
      Une étiquette dit ce qu’une page <strong>contient</strong>, jamais si une
      brique a eu raison. C’est ce qui la fait vivre des années : « la page
      annonce 8 € » vaut pour toujours, « le tarif rendu est juste » périmait au
      premier changement de prompt. La mesure, elle, est sur
      <RouterLink to="/admin/evaluation/mesures">Mesures</RouterLink>.
    </p>

    <div class="tiles">
      <div class="card tile">
        <span class="value">{{ corpusSize.pages }}</span>
        <span class="label">page(s) d’agenda gelée(s)</span>
      </div>
      <div class="card tile">
        <span class="value">{{ corpusSize.links }}</span>
        <span class="label">lien(s) étiqueté(s)</span>
      </div>
      <div class="card tile">
        <span class="value">{{ corpusSize.readings }}</span>
        <span class="label">page(s) au corpus de lecture</span>
      </div>
      <div class="card tile">
        <span class="value">{{ corpusSize.readingLabels }}</span>
        <span class="label">étiquette(s) de lecture</span>
      </div>
    </div>

    <p v-if="notice" class="notice">{{ notice }}</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="muted">Chargement…</p>

    <!-- ── Peupler ────────────────────────────────────────────────────── -->
    <h2>Peupler depuis ce que le pipeline a déjà fait</h2>
    <p class="muted small">
      Quatre paniers, et l’équilibre entre eux est la question : ne prendre que
      les réussites mesurerait la brique sur ses propres succès — on lirait 96 %
      de textes corrects, et ça ne voudrait rien dire.
    </p>
    <div v-if="seed" class="row buckets">
      <button class="btn ghost" :disabled="!seed.approuvees" @click="pour('approuvees')">
        Sorties approuvées ({{ seed.approuvees }})
      </button>
      <button class="btn ghost" :disabled="!seed.abandonnees" @click="pour('abandonnees')">
        Pages abandonnées ({{ seed.abandonnees }})
      </button>
      <button class="btn ghost" :disabled="!seed.illisibles" @click="pour('illisibles')">
        Descriptions refusées ({{ seed.illisibles }})
      </button>
      <button class="btn ghost" :disabled="!seed.liens" @click="pour('liens')">
        Étiquettes venues de la modération ({{ seed.liens }})
      </button>
    </div>
    <p v-if="seed" class="muted small">
      Le dernier panier n’apporte que des <strong>positifs</strong> : une page
      devenue une sortie approuvée est une sortie, un modérateur l’a vérifiée
      fiche en main. Il ne dira jamais qu’un lien n’en est pas une — il
      raccourcit la relecture, il ne la remplace pas.
    </p>

    <!-- ── Les agendas ────────────────────────────────────────────────── -->
    <h2>Agendas — étages 3 et 4</h2>
    <div class="row add">
      <input v-model="newAgendaUrl" type="url" placeholder="https://exemple.fr/agenda" />
      <input v-model.number="newAgendaPages" type="number" min="1" max="10" title="Pages à geler" />
      <button class="btn" @click="addAgenda()">Ajouter au corpus</button>
    </div>

    <div v-for="agenda in agendas" :key="agenda.id" class="card entry">
      <div class="entry-head">
        <button class="linklike strong" @click="openAgenda(agenda)">
          {{ agenda.label || agenda.url }}
        </button>
        <span class="badge">{{ EVAL_CAPTURE_LABELS[agenda.capture] }}</span>
        <span class="muted small">
          {{ agenda.pagesCaptured }} page(s) gelée(s) · {{ agenda.labels }} étiquette(s)
        </span>
        <span class="spacer" />
        <button
          v-if="agenda.capture !== 'CAPTURED'"
          class="linklike"
          @click="capture('agendas', agenda.id)"
        >
          Geler
        </button>
        <button class="linklike" @click="removeAgenda(agenda)">Retirer</button>
      </div>
      <p v-if="agenda.captureError" class="error small">{{ agenda.captureError }}</p>

      <!-- Le détail : les étiquettes, et un relevé en regard -->
      <div v-if="open?.id === agenda.id" class="detail">
        <p v-if="!openRunId" class="muted small">
          Aucune mesure jouée : les liens de cette page ne sont pas encore
          connus. Lancez-en une depuis
          <RouterLink to="/admin/evaluation/mesures">Mesures</RouterLink>, ou
          étiquetez à la main ce que vous savez déjà.
        </p>
        <p v-else class="muted small">
          Relevé affiché : run #{{ openRunId }}. Il <strong>propose</strong>, il
          n’écrit rien : une ligne n’entre au corpus que si vous cliquez.
        </p>

        <div v-for="page in open.agendaPages" :key="page.id" class="page-block">
          <h4>
            Page {{ page.pageNo }}
            <span class="muted small">{{ page.chars }} caractères</span>
            <a v-if="page.archived" :href="`/api/eval/pages/${page.id}/html`" target="_blank">
              voir le HTML gelé
            </a>
          </h4>

          <!-- La pagination -->
          <div class="next">
            <span class="muted small">Page suivante réelle :</span>
            <code v-if="page.nextExpected">{{ page.nextExpected }}</code>
            <em v-else-if="page.nextExpected === ''" class="muted">il n’y en a pas</em>
            <em v-else class="muted">non étiquetée</em>
            <span v-if="openRunId" class="muted small">
              — le relevé a trouvé
              <code v-if="foundNext(page)">{{ foundNext(page) }}</code>
              <em v-else>rien</em>
            </span>
            <button class="linklike" @click="labelNext(page.id, foundNext(page))">
              c’est juste
            </button>
            <button class="linklike" @click="labelNext(page.id, '')">il n’y a pas de suite</button>
            <button
              class="linklike"
              @click="askNext(page.id)"
            >
              c’est celle-ci…
            </button>
          </div>

          <!-- Les motifs de rejet, expédiables en groupe -->
          <div v-if="reasons(page).length" class="row reasons">
            <span class="muted small">Écartés par le relevé :</span>
            <span v-for="[reason, count] in reasons(page)" :key="reason" class="reason">
              {{ reason }} ({{ count }})
              <button class="linklike" @click="bulk(page.id, reason, 'AUTRE')">
                tout « autre chose »
              </button>
            </span>
          </div>

          <table class="links">
            <thead>
              <tr>
                <th>Lien</th>
                <th>Relevé</th>
                <th>Étiquette</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows(page)" :key="row.result?.url ?? row.label?.url">
                <td>
                  <div class="link-text">{{ row.result?.text || row.label?.text || '(sans texte)' }}</div>
                  <a :href="row.result?.url ?? row.label?.url" target="_blank" class="muted small">
                    {{ row.result?.url ?? row.label?.url }}
                  </a>
                  <div v-if="row.result?.context" class="muted small ctx">{{ row.result.context }}</div>
                </td>
                <td class="small">
                  <template v-if="row.result">
                    <span v-if="row.result.harvested">retenu</span>
                    <span v-else class="muted">écarté — {{ row.result.dropReason }}</span>
                    <div v-if="row.result.selected !== null" class="muted">
                      tri : {{ row.result.selected ? 'retenu' : 'écarté' }}
                    </div>
                  </template>
                  <em v-else class="muted">absent du relevé</em>
                </td>
                <td>
                  <div class="chips">
                    <button
                      v-for="v in VERDICTS"
                      :key="v"
                      class="chip"
                      :class="{ on: row.label?.verdict === v }"
                      :title="EVAL_VERDICT_HINTS[v]"
                      @click="labelLink(page.id, row.result?.url ?? row.label!.url, row.result?.text ?? row.label?.text ?? '', v)"
                    >
                      {{ EVAL_VERDICT_LABELS[v] }}
                    </button>
                    <button v-if="row.label" class="linklike" @click="unlabel(row.label.id)">
                      retirer
                    </button>
                  </div>
                  <div v-if="row.label" class="muted small">
                    {{ EVAL_LABEL_ORIGIN_LABELS[row.label.origin] }}
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ── Les pages de lecture ───────────────────────────────────────── -->
    <h2>Pages — étages 5 et 6</h2>
    <div class="row add">
      <input v-model="newReadingUrl" type="url" placeholder="https://exemple.fr/spectacle" />
      <button class="btn" @click="addReading()">Ajouter au corpus</button>
    </div>

    <div class="table-wrap card">
      <table>
        <thead>
          <tr>
            <th>Page</th>
            <th>Origine</th>
            <th>Capture</th>
            <th>Étiquettes</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="reading in readings" :key="reading.id">
            <td>
              <div class="link-text">{{ reading.label || reading.url }}</div>
              <a :href="reading.url" target="_blank" class="muted small">{{ reading.url }}</a>
            </td>
            <td :title="EVAL_ORIGIN_HINTS[reading.origin]" class="small">
              {{ EVAL_ORIGIN_LABELS[reading.origin] }}
            </td>
            <td class="small">
              {{ EVAL_CAPTURE_LABELS[reading.capture] }}
              <button
                v-if="reading.capture !== 'CAPTURED'"
                class="linklike"
                @click="capture('readings', reading.id)"
              >
                geler
              </button>
              <a v-else-if="reading.archived" :href="`/api/eval/readings/${reading.id}/html`" target="_blank">
                HTML
              </a>
            </td>
            <td class="num">
              {{ labelled(reading) }}/3
              <span v-if="reading.fiche" class="muted small"> · fiche</span>
            </td>
            <td>
              <div class="row actions">
                <button class="linklike" @click="edit(reading)">Étiqueter</button>
                <button class="linklike" @click="removeReading(reading)">Retirer</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- L'étiquetage d'une page -->
    <div v-if="editing" class="card editor">
      <h3>{{ editing.label || editing.url }}</h3>
      <p class="muted small">
        Ce que la page contient. Un champ vide veut dire « la page n’en porte
        pas », et c’est une étiquette de plein droit : c’est elle qui permettra
        de reconnaître une valeur inventée. Pour dire « je n’ai pas regardé »,
        utilisez « Effacer les étiquettes ».
      </p>
      <label for="ed-img">Illustration de la page</label>
      <input id="ed-img" v-model="editImage" type="url" placeholder="https://… (vide : aucune)" />

      <label for="ed-dates">Dates annoncées — une par ligne</label>
      <textarea id="ed-dates" v-model="editDates" rows="3" placeholder="2027-03-04"></textarea>

      <label for="ed-mark">Fragments que le texte doit contenir — un par ligne</label>
      <textarea
        id="ed-mark"
        v-model="editMarkers"
        rows="4"
        placeholder="Atelier modelage&#10;8 €&#10;77 rue de Varenne"
      ></textarea>
      <p class="muted small">
        On ne demande pas de retaper le texte attendu : ce serait invivable et
        personne ne le ferait deux fois. Quelques fragments suffisent à
        distinguer un texte amputé d’un texte entier, qui est la question de cet
        étage.
      </p>

      <div class="row">
        <button class="btn" @click="saveLabels()">Enregistrer</button>
        <button class="linklike" @click="saveLabels(true)">Effacer les étiquettes</button>
        <button class="linklike" @click="editing = null">Annuler</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
h2 {
  margin-top: 1.8rem;
}

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.8rem;
  margin-bottom: 1.4rem;
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

.add {
  gap: 0.6rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}

.add input[type='url'] {
  flex: 1;
  min-width: 240px;
}

.add input[type='number'] {
  width: 5rem;
}

.buckets {
  gap: 0.6rem;
  flex-wrap: wrap;
  margin-bottom: 0.6rem;
}

.entry {
  padding: 0.9rem 1.1rem;
  margin-bottom: 0.8rem;
}

.entry-head {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  flex-wrap: wrap;
}

.spacer {
  flex: 1;
}

.badge {
  font-size: 0.75rem;
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 0.1rem 0.5rem;
  color: var(--ink-soft);
}

.detail {
  margin-top: 1rem;
  border-top: 1px solid var(--photo-bg);
  padding-top: 0.8rem;
}

.page-block {
  margin-bottom: 1.4rem;
}

.page-block h4 {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  margin: 0 0 0.5rem;
}

.next,
.reasons {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-bottom: 0.6rem;
  font-size: 0.85rem;
}

.reason {
  border: 1px solid var(--photo-bg);
  border-radius: 6px;
  padding: 0.1rem 0.5rem;
}

.links {
  width: 100%;
  font-size: 0.9rem;
}

.link-text {
  font-weight: 600;
}

.ctx {
  max-width: 40ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  align-items: center;
}

.chip {
  padding: 0.15rem 0.5rem;
  border: 1px solid currentColor;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 0.78rem;
  cursor: pointer;
}

.chip.on {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.editor {
  padding: 1rem 1.2rem;
  margin-top: 1rem;
}

.editor label {
  display: block;
  margin: 0.8rem 0 0.2rem;
  font-size: 0.85rem;
  font-weight: 600;
}

.editor input,
.editor textarea {
  width: 100%;
  box-sizing: border-box;
}

.actions {
  gap: 0.7rem;
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

.linklike {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  color: var(--accent-dark);
  cursor: pointer;
  text-decoration: underline;
}

.linklike.strong {
  font-weight: 700;
}

.btn.ghost {
  background: transparent;
  color: var(--accent-dark);
  border: 1px solid currentColor;
}
</style>
