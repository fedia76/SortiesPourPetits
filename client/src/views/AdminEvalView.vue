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
  EvalSortieLabel,
  EvalAudience,
  EvalRunScope,
  EvalSortieFacts,
  EvalLink,
  EvalLinkResult,
  EvalSortie,
  EvalReste,
  EvalSeedCounts,
  EvalVerdict,
} from '../types';
import {
  EVAL_AUDIENCE_HINTS,
  EVAL_AUDIENCE_LABELS,
  EVAL_RELEVANCE_HINTS,
  EVAL_RELEVANCE_LABELS,
  EVAL_CAPTURE_LABELS,
  EVAL_LABEL_ORIGIN_LABELS,
  EVAL_ORIGIN_HINTS,
  EVAL_ORIGIN_LABELS,
  EVAL_VERDICT_HINTS,
  EVAL_VERDICT_LABELS,
} from '../types';

const VERDICTS: EvalVerdict[] = ['SORTIE', 'PAGINATION', 'SOUS_AGENDA', 'AUTRE'];
const AUDIENCES: EvalAudience[] = ['ENFANTS', 'ADULTES', 'INDETERMINE'];

const agendas = ref<EvalAgenda[]>([]);
const sorties = ref<EvalSortie[]>([]);
const seed = ref<EvalSeedCounts | null>(null);
/**
 * Ce qui reste à faire à la main, compté.
 *
 * Un run modéré donne la précision gratuitement : parmi ce que le scraper a
 * proposé, ce qu'un humain a validé. Le rappel — ce qu'il a raté — n'est
 * visible nulle part dans ce qu'il a proposé, et se paie en ouvrant les liens
 * qu'il a laissés. L'afficher ne le raccourcit pas ; ça évite de le découvrir
 * au fil de l'eau, ce qui est la façon dont on abandonne un banc.
 */
const reste = ref<EvalReste | null>(null);
const open = ref<EvalAgenda | null>(null);
const openRunId = ref(0);
/**
 * Ce sous quoi le run affiché a joué le tri.
 *
 * Sans elle, « hors recherche » serait une accusation sans procès : le
 * relecteur doit voir la fenêtre et la zone qui font écarter un lien, sinon il
 * corrigera des étiquettes qui n'ont rien de faux.
 */
const openScope = ref<EvalRunScope>({});
const loading = ref(true);
const error = ref('');
const notice = ref('');

const newAgendaUrl = ref('');
const newAgendaPages = ref(1);
const newSortieUrl = ref('');

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const [a, r] = await Promise.all([
      api.get<{ agendas: EvalAgenda[] }>('/api/eval/agendas'),
      api.get<{ sorties: EvalSortie[] }>('/api/eval/sorties'),
    ]);
    agendas.value = a.agendas;
    sorties.value = r.sorties;
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
  try {
    seed.value = await api.get<EvalSeedCounts>('/api/eval/seed');
    reste.value = await api.get<EvalReste>('/api/eval/reste');
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

async function capture(kind: 'agendas' | 'sorties', id: number) {
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
    const body = await api.get<{ agenda: EvalAgenda; runId: number; scope: EvalRunScope }>(
      `/api/eval/agendas/${agenda.id}`,
    );
    open.value = body.agenda;
    openRunId.value = body.runId;
    openScope.value = body.scope ?? {};
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

const totalJamaisRegardes = computed(() =>
  (reste.value?.jamaisRegardes ?? []).reduce((n, p) => n + p.manquants, 0),
);

/** La portée du run affiché, en une phrase. Vide s'il n'y a rien à dire. */
const scopeText = computed(() => {
  const s = openScope.value;
  const bouts: string[] = [];
  if (s.dateFrom && s.dateTo) bouts.push(`du ${s.dateFrom} au ${s.dateTo}`);
  if (s.postalPrefixes?.length) bouts.push(`départements ${s.postalPrefixes.join(', ')}`);
  if (s.maxLinks) bouts.push(`au plus ${s.maxLinks} liens par page`);
  return bouts.join(' · ');
});

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

/**
 * Créer au corpus la sortie vers laquelle un lien mène, et l'y attacher.
 *
 * Tant qu'elle n'existe pas, l'étage 4 n'a rien à quoi se comparer et le lien
 * compte *indécidable* — ni pour, ni contre. C'est le geste qui solde cette
 * dette, et c'est le seul travail que la modération ne paie pas d'avance.
 */
async function creerSortie(linkId: number) {
  try {
    await api.post(`/api/eval/links/${linkId}/sortie`, {});
    await refreshOpen();
  } catch (e) {
    fail(e);
  }
}

/**
 * Ce que la sortie affirme, en une ligne.
 *
 * De la lecture seule, délibérément : la saisie est dans le groupe des
 * sorties, parce que c'est là que la donnée vit. Afficher sans permettre de
 * modifier est la seule façon de montrer la frontière au lieu de l'expliquer.
 */
function resume(sortie: EvalSortieFacts | null | undefined): string {
  if (!sortie) return '';
  const bouts: string[] = [];
  if (sortie.dateStart) {
    bouts.push(sortie.dateEnd && sortie.dateEnd !== sortie.dateStart
      ? `du ${sortie.dateStart} au ${sortie.dateEnd}`
      : `le ${sortie.dateStart}`);
  }
  if (sortie.postalCode) bouts.push(sortie.postalCode);
  if (sortie.ageMin != null && sortie.ageMax != null) bouts.push(`${sortie.ageMin} à ${sortie.ageMax} ans`);
  else if (sortie.ageMin != null) bouts.push(`dès ${sortie.ageMin} ans`);
  else if (sortie.ageMax != null) bouts.push(`jusqu’à ${sortie.ageMax} ans`);
  if (sortie.audience) bouts.push(EVAL_AUDIENCE_LABELS[sortie.audience]);
  return bouts.length ? `— ${bouts.join(' · ')}` : '— rien d’affirmé';
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
  const body = await api.get<{ agenda: EvalAgenda; runId: number; scope: EvalRunScope }>(
    `/api/eval/agendas/${id}`,
  );
  open.value = body.agenda;
  openRunId.value = body.runId;
  openScope.value = body.scope ?? {};
  await load();
}

// ── le corpus de lecture ───────────────────────────────────────────────

async function addSortie() {
  if (!newSortieUrl.value.trim()) return;
  try {
    await api.post('/api/eval/sorties', { url: newSortieUrl.value.trim() });
    newSortieUrl.value = '';
    await load();
  } catch (e) {
    fail(e);
  }
}

async function removeSortie(sortie: EvalSortie) {
  if (!confirm(`Retirer « ${sortie.label || sortie.url} » du corpus, avec ses étiquettes ?`)) return;
  try {
    await api.delete(`/api/eval/sorties/${sortie.id}`);
    await load();
  } catch (e) {
    fail(e);
  }
}

/** Les trois étiquettes d'une page, saisies en clair. */
const editing = ref<EvalSortie | null>(null);
const editImage = ref('');
const editDates = ref('');
const editMarkers = ref('');
/**
 * Ce que l'étage 4 juge. Saisi **ici**, sur la sortie, et nulle part ailleurs :
 * c'est la sortie qui a une date et un lieu, pas le lien d'agenda qui y mène.
 * Plusieurs agendas peuvent annoncer la même sortie.
 */
const editDateStart = ref('');
const editDateEnd = ref('');
const editPostalCode = ref('');
const editAgeMin = ref<number | null>(null);
const editAgeMax = ref<number | null>(null);
const editAudience = ref<EvalAudience | null>(null);

/**
 * L'étiquette d'une sortie, relue pour le formulaire.
 *
 * Une sortie n'a qu'une étiquette, en JSON. Chaque étage y lit son
 * sous-ensemble : la console fait saisir celui des étages 4 et 5, le reste
 * vient de la moisson.
 */
function edit(sortie: EvalSortie) {
  editing.value = sortie;
  const e = JSON.parse(sortie.expected || '{}') as Partial<EvalSortieLabel>;
  editImage.value = e.image ?? '';
  editDates.value = (e.declaredDates ?? []).join('\n');
  editMarkers.value = (e.markers ?? []).join('\n');
  editDateStart.value = (e.dateStart ?? '').slice(0, 10);
  editDateEnd.value = (e.dateEnd ?? '').slice(0, 10);
  editPostalCode.value = e.venuePostalCode ?? '';
  editAgeMin.value = e.ageMin ?? null;
  editAgeMax.value = e.ageMax ?? null;
  editAudience.value = sortie.audience;
}

function lines(value: string): string[] {
  return value
    .split('\n')
    .map((v) => v.trim())
    .filter(Boolean);
}

async function saveLabels(clear = false) {
  const sortie = editing.value;
  if (!sortie) return;
  try {
    await api.patch(`/api/eval/sorties/${sortie.id}`, {
      image: clear ? null : editImage.value.trim(),
      declaredDates: clear ? null : lines(editDates.value),
      markers: clear ? null : lines(editMarkers.value),
      dateStart: clear ? null : editDateStart.value || null,
      dateEnd: clear ? null : editDateEnd.value || null,
      venuePostalCode: clear ? null : editPostalCode.value.trim() || null,
      ageMin: clear ? null : editAgeMin.value,
      ageMax: clear ? null : editAgeMax.value,
      audience: clear ? null : editAudience.value,
    });
    editing.value = null;
    await load();
  } catch (e) {
    fail(e);
  }
}

/** Combien d'étiquettes une page porte : trois au plus, celles de l'étage 5. */
/**
 * Ce que l'étiquette d'une sortie affirme, étage par étage.
 *
 * L'ancien compteur ne connaissait que les trois étiquettes de lecture et
 * affichait donc « 0/3 » sur une sortie parfaitement décrite pour le tri. Il
 * dit maintenant ce que chaque étage y trouve — et il n'y a plus qu'une
 * étiquette derrière, pas deux objets à recouper.
 */
function etiquette(sortie: EvalSortie) {
  const e = JSON.parse(sortie.expected || '{}') as Record<string, unknown>;
  const dit = (cle: string) => cle in e;
  return {
    // L'étage 4 ne regarde que la date, le lieu et le public.
    tri: [dit('dateStart'), dit('venuePostalCode'), sortie.audience !== null].filter(Boolean).length,
    lecture: [dit('image'), dit('declaredDates'), dit('markers')].filter(Boolean).length,
    // L'étage 6 regarde la fiche entière. On compte ce qui la remplit, sans
    // les clés que les deux étages précédents se sont déjà comptées.
    extraction: ['title', 'description', 'free', 'ageMin', 'category', 'venueName'].filter(dit)
      .length,
  };
}

/**
 * Vider le corpus des sorties.
 *
 * Ce qui vient du site se remoissonne d'un clic ; ce qu'un humain a saisi à la
 * main, non. On le compte et on le dit **avant** de demander confirmation :
 * une confirmation qui n'annonce pas ce qu'elle détruit n'en est pas une.
 */
async function viderSorties() {
  const saisies = sorties.value.filter((r) => !r.published && r.labelledAt).length;
  const avertissement = saisies
    ? `\n\n${saisies} sortie(s) étiquetée(s) à la main seront perdues : elles ne viennent pas du site et ne se remoissonnent pas.`
    : '';
  if (!confirm(`Vider les ${sorties.value.length} sortie(s) du corpus ?${avertissement}`)) return;
  try {
    const body = await api.delete<{ removed: number; handLabelled: number }>('/api/eval/sorties');
    notice.value =
      `${body.removed} sortie(s) retirée(s)` +
      (body.handLabelled ? `, dont ${body.handLabelled} étiquetée(s) à la main.` : '.');
    await load();
  } catch (e) {
    fail(e);
  }
}

// ── peupler le corpus depuis ce que le pipeline a déjà fait ────────────

async function pour(bucket: 'approuvees' | 'abandonnees' | 'illisibles' | 'liens' | 'fiches') {
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
  sorties: sorties.value.length,
  // Les sorties dont l'étiquette affirme au moins quelque chose. Compter les
  // champs n'aurait pas de sens : ils ne pèsent pas le même travail.
  sortieLabels: sorties.value.filter((r) => {
    const e = etiquette(r);
    return e.tri + e.lecture + e.extraction > 0;
  }).length,
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
        <span class="value">{{ corpusSize.sorties }}</span>
        <span class="label">sortie(s) au corpus</span>
      </div>
      <div class="card tile">
        <span class="value">{{ corpusSize.sortieLabels }}</span>
        <span class="label">sortie(s) étiquetée(s)</span>
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
        Sorties publiées ({{ seed.approuvees }})
      </button>
      <button class="btn ghost" :disabled="!seed.fiches" @click="pour('fiches')">
        Étiqueter les sorties publiées ({{ seed.fiches }})
      </button>
      <button class="btn ghost" :disabled="!seed.abandonnees" @click="pour('abandonnees')">
        Pages abandonnées ({{ seed.abandonnees }})
      </button>
      <button class="btn ghost" :disabled="!seed.illisibles" @click="pour('illisibles')">
        Descriptions refusées ({{ seed.illisibles }})
      </button>
      <button class="btn ghost" :disabled="!seed.liens" @click="pour('liens')">
        Liens d’agenda déjà tranchés ({{ seed.liens }})
      </button>
      <button class="btn ghost danger" :disabled="!corpusSize.sorties" @click="viderSorties()">
        Vider les sorties
      </button>
    </div>
    <p class="muted small">
      Les deux premiers viennent de <strong>sorties publiées</strong> sur le
      site : un modérateur les a approuvées, leur étiquette est donc du travail
      humain déjà payé. Les deux suivants sont des pages que le pipeline a
      rencontrées mais <strong>jamais publiées</strong> — abandonnées à la
      lecture, ou dont la fiche a été refusée : elles n’ont aucune étiquette
      d’avance, et c’est pour ça qu’elles comptent. Un corpus qui ne
      contiendrait que des réussites mesurerait la brique sur ses propres
      succès.
    </p>
    <p v-if="seed" class="muted small">
      <strong>« Étiqueter les sorties publiées »</strong> remplit ce qu’une
      sortie <em>est</em>, champ par champ, depuis ce qu’un modérateur a validé.
      Les <em>jours de représentation</em> restent en dehors : le site ne les
      reçoit pas, et les reconstituer donnerait une étiquette amputée qui
      compterait « faux » à chaque sortie récurrente.
    </p>
    <p v-if="seed" class="muted small">
      <strong>« Liens d’agenda déjà tranchés »</strong> n’apporte que des
      <strong>positifs</strong> : une page devenue une sortie approuvée est une
      sortie, un modérateur l’a vérifiée. Il ne dira jamais qu’un lien n’en est
      pas une — il raccourcit la relecture, il ne la remplace pas.
    </p>
    <p class="muted small">
      <strong>« Vider les sorties »</strong> remet le corpus des sorties à zéro.
      Tout ce qui vient du site se remoissonne avec les boutons ci-dessus ; ce
      qui a été saisi à la main, non — le compte rendu le dit avant.
    </p>

    <!-- ── Ce qui reste à faire à la main ─────────────────────────────── -->
    <h2>Ce qui reste à la main</h2>
    <p class="muted small">
      La modération paie la <strong>précision</strong> : parmi ce que le
      scraper a proposé, ce qu’un humain a validé. Elle ne paiera jamais le
      <strong>rappel</strong> — ce qu’il a raté n’apparaît pas dans ce qu’il a
      proposé. Ces deux listes sont ce qu’il coûte.
    </p>
    <div v-if="reste" class="card reste">
      <div class="reste-ligne">
        <strong>{{ totalJamaisRegardes }}</strong>
        lien(s) relevés que personne n’a tranchés
        <span class="muted small">
          — tant qu’ils sont là, le rappel de l’étage 3 est une illusion : on ne
          peut pas savoir si une sortie s’y cache.
        </span>
        <ul v-if="reste.jamaisRegardes.length" class="reste-detail">
          <li v-for="page in reste.jamaisRegardes.slice(0, 5)" :key="page.pageId">
            {{ page.manquants }} sur « {{ page.label || page.url }} »
          </li>
        </ul>
      </div>
      <div class="reste-ligne">
        <strong>{{ reste.sansSortie.length }}</strong>
        sortie(s) reconnues dont rien n’est affirmé
        <span class="muted small">
          — l’étage 4 n’a rien à quoi les comparer : elles comptent
          <em>indécidables</em>, ni pour ni contre.
        </span>
        <ul v-if="reste.sansSortie.length" class="reste-detail">
          <li v-for="lien in reste.sansSortie.slice(0, 5)" :key="lien.id">
            <a :href="lien.url" target="_blank">{{ lien.text || lien.url }}</a>
            <span class="muted small">
              {{ lien.sortieId ? '— à décrire' : '— à créer' }}
            </span>
          </li>
        </ul>
      </div>
    </div>

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
          <template v-if="scopeText">
            <br />
            Recherche de ce run : {{ scopeText }}. C’est elle, et elle seule,
            qui rend un lien « hors recherche » — les étiquettes, elles, ne
            changent pas d’un run à l’autre.
          </template>
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
                  <!--
                    Un lien « une sortie » mène quelque part. Tant que personne
                    n'a dit ce qu'il y a au bout, l'étage 4 n'a rien à quoi se
                    comparer : on propose de la décrire plutôt que d'afficher
                    des champs qui n'appartiendraient à rien.
                  -->
                  <template v-if="row.label?.verdict === 'SORTIE'">
                    <div v-if="!row.label.sortie" class="hints">
                      <span class="muted small">Sortie non décrite —</span>
                      <button class="linklike" @click="creerSortie(row.label.id)">
                        la décrire
                      </button>
                    </div>

                    <!--
                      La date, le lieu et l'âge **ne se saisissent pas ici**.
                      Ils décrivent la sortie, pas le lien, et une seule sortie
                      peut être annoncée par plusieurs agendas. Les offrir sur
                      cette ligne laissait croire qu'ils lui appartenaient — ce
                      qu'ils faisaient d'ailleurs, dans une version précédente,
                      en double de ce que le corpus des sorties disait déjà.
                      On y renvoie plutôt qu'on ne les recopie.
                    -->
                    <div v-else class="hints">
                      <a :href="`#sortie-${row.label.sortieId}`" class="linklike">
                        voir la sortie
                      </a>
                      <span class="muted small">{{ resume(row.label.sortie) }}</span>
                    </div>

                    <!--
                      Ce que la sortie donne pour le run affiché. Ce n'est pas
                      une étiquette de plus : c'est ce que le serveur en déduit,
                      et il change avec la recherche qu'on regarde.
                    -->
                    <span
                      v-if="row.label.relevance"
                      class="relevance"
                      :class="row.label.relevance.toLowerCase()"
                      :title="EVAL_RELEVANCE_HINTS[row.label.relevance]"
                    >
                      → {{ EVAL_RELEVANCE_LABELS[row.label.relevance] }}
                    </span>
                  </template>
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
      <input v-model="newSortieUrl" type="url" placeholder="https://exemple.fr/spectacle" />
      <button class="btn" @click="addSortie()">Ajouter au corpus</button>
    </div>

    <div class="table-wrap card">
      <table>
        <thead>
          <tr>
            <th>Page</th>
            <th>Provenance</th>
            <th>Capture</th>
            <th>Étiquettes</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="sortie in sorties" :id="`sortie-${sortie.id}`" :key="sortie.id">
            <td>
              <div class="link-text">{{ sortie.label || sortie.url }}</div>
              <a :href="sortie.url" target="_blank" class="muted small">{{ sortie.url }}</a>
            </td>
            <td class="small">
              <!--
                D'abord d'où elle vient, parce que c'est ce qui dit si son
                étiquette est du travail déjà payé ou du travail à faire.
              -->
              <span
                class="provenance"
                :class="sortie.published ? 'publiee' : 'banc'"
                :title="
                  sortie.published
                    ? 'Publiée sur le site : un modérateur l’a approuvée, son étiquette se moissonne.'
                    : 'Propre au banc : jamais publiée, tout ce qu’elle affirme est à saisir.'
                "
              >
                {{ sortie.published ? 'sortie publiée' : 'banc de test' }}
              </span>
              <div :title="EVAL_ORIGIN_HINTS[sortie.origin]" class="muted small">
                {{ EVAL_ORIGIN_LABELS[sortie.origin] }}
              </div>
            </td>
            <td class="small">
              {{ EVAL_CAPTURE_LABELS[sortie.capture] }}
              <button
                v-if="sortie.capture !== 'CAPTURED'"
                class="linklike"
                @click="capture('sorties', sortie.id)"
              >
                geler
              </button>
              <a v-else-if="sortie.archived" :href="`/api/eval/sorties/${sortie.id}/html`" target="_blank">
                HTML
              </a>
            </td>
            <td class="num small">
              <span :title="'Ce que l’étage 4 juge : la date, le lieu, le public.'">
                tri {{ etiquette(sortie).tri }}/3
              </span>
              ·
              <span :title="'Ce que l’étage 5 juge : l’illustration, les dates déclarées, les fragments du texte.'">
                lecture {{ etiquette(sortie).lecture }}/3
              </span>
              ·
              <span :title="'Ce que l’étage 6 juge : la fiche entière.'">
                fiche {{ etiquette(sortie).extraction }}/6
              </span>
            </td>
            <td>
              <div class="row actions">
                <button class="linklike" @click="edit(sortie)">Étiqueter</button>
                <button class="linklike" @click="removeSortie(sortie)">Retirer</button>
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
      <fieldset class="faits">
        <legend>Ce que l’étage 4 juge — la date, le lieu, l’âge</legend>
        <p class="muted small">
          Trois champs, et ils suffisent : c’est tout ce que le tri regarde.
          Ils se lisent souvent dans la ligne de l’agenda, sans ouvrir la page.
        </p>
        <div class="row faits-ligne">
          <label class="hint">
            <span class="muted small">du</span>
            <input v-model="editDateStart" type="date" />
          </label>
          <label class="hint">
            <span class="muted small">au</span>
            <input v-model="editDateEnd" type="date" title="Vide sur une date unique." />
          </label>
          <label class="hint">
            <span class="muted small">à</span>
            <input
              v-model="editPostalCode"
              type="text"
              inputmode="numeric"
              size="6"
              placeholder="75012"
              title="Cinq chiffres. Une ville en toutes lettres ne se compare à aucun département."
            />
          </label>
          <label class="hint">
            <span class="muted small">de</span>
            <input v-model.number="editAgeMin" type="number" min="0" max="120" size="3" />
            <span class="muted small">à</span>
            <input v-model.number="editAgeMax" type="number" min="0" max="120" size="3" />
            <span class="muted small">ans</span>
          </label>
        </div>
        <div class="chips">
          <button
            v-for="a in AUDIENCES"
            :key="a"
            class="chip tiny"
            :class="{ on: editAudience === a }"
            :title="EVAL_AUDIENCE_HINTS[a]"
            @click="editAudience = editAudience === a ? null : a"
          >
            {{ EVAL_AUDIENCE_LABELS[a] }}
          </button>
        </div>
      </fieldset>

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

.faits {
  border: 1px solid var(--border, #ddd);
  border-radius: 6px;
  padding: 0.6rem 0.9rem 0.9rem;
  margin-bottom: 1rem;
}

.faits legend {
  font-size: 0.85rem;
  font-weight: 600;
  padding: 0 0.4rem;
}

.faits-ligne {
  gap: 0.8rem;
  flex-wrap: wrap;
  margin-bottom: 0.5rem;
}

.provenance {
  display: inline-block;
  padding: 0.05rem 0.45rem;
  border-radius: 999px;
  font-size: 0.74rem;
  white-space: nowrap;
}

.provenance.publiee {
  background: var(--accent, #2563eb);
  color: #fff;
}

.provenance.banc {
  border: 1px solid var(--border, #ccc);
  color: var(--ink-soft, #666);
}

.btn.ghost.danger {
  color: var(--danger, #b42318);
  border-color: currentColor;
}

.reste {
  padding: 0.8rem 1rem;
}

.reste-ligne + .reste-ligne {
  margin-top: 0.8rem;
  padding-top: 0.8rem;
  border-top: 1px solid var(--border, #eee);
}

.reste-detail {
  margin: 0.3rem 0 0;
  padding-left: 1.2rem;
  font-size: 0.82rem;
}

.relevance {
  font-size: 0.74rem;
  white-space: nowrap;
  opacity: 0.85;
}

.relevance.pertinente {
  color: var(--ok, #1a7f37);
}

.relevance.hors_recherche {
  color: var(--muted, #666);
}

.relevance.indecidable {
  color: var(--warn, #9a6700);
}

.chip.tiny {
  font-size: 0.72rem;
  padding: 0.1rem 0.4rem;
}

/* Les indices sont en retrait du verdict : ils le qualifient, ils ne le
   concurrencent pas. */
.hints {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin: 0.35rem 0 0.2rem 0.6rem;
  padding-left: 0.6rem;
  border-left: 2px solid var(--border, #ddd);
}

.hint {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.hints input {
  font: inherit;
  font-size: 0.78rem;
  padding: 0.1rem 0.3rem;
}

.hints input[type='text'] {
  width: 9rem;
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
