<script setup lang="ts">
/**
 * Le banc d'évaluation : ce que chaque brique du scraper rend vraiment.
 *
 * Un onglet par étage, deux remplis — le **dépouillement** et la **lecture**.
 * Ce sont les deux étages gratuits en amont des appels payants : leur ratage
 * plafonne tout ce qui suit, ils sont déterministes — ce qui ne veut pas dire
 * justes — et leurs pannes se déguisent en pannes des étages d'après. Un agenda dont les liens de fiche ont été perdus rend son menu, la
 * sélection n'en retient rien avec un motif parfaitement sensé, et c'est un
 * prompt qu'on ira retoucher pour un bug de sélecteur.
 *
 * ## Le principe : la brique précoche, l'humain corrige
 *
 * Le banc relève **tous** les liens de la page. Pour chacun, ce que le vrai
 * `links_of` en a fait devient une proposition — retenu, donc probablement une
 * sortie ; écarté, donc probablement du bruit. Il ne reste qu'à corriger ce qui
 * est faux, et ce sont ces corrections-là qui sont la mesure.
 *
 * C'est ce qui donne les **deux** erreurs. Ne montrer que la moisson
 * obligeait à retrouver les manqués soi-même, en rouvrant la vraie page — lent,
 * et incomplet par construction. Et surtout ça ne disait rien du contraire :
 * un lien retenu qui ne mène nulle part coûte un appel payant à l'étage 4, et
 * cette erreur-là restait invisible.
 *
 * ## Le filtre est un outil de travail, pas un ornement
 *
 * Une page d'agenda aligne trois cents liens. On commence par **les retenus** —
 * une vingtaine, qu'on confirme ou corrige vite — puis on passe aux écartés,
 * rangés par motif : les sorties perdues se concentrent sous « texte trop
 * court » et « hors domaine », jamais sous « mentions légales ».
 */
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { api } from '../lib/api';
import {
  EVAL_READ_ASPECTS,
  EVAL_STATUS_LABELS,
  EVAL_VERDICT_HINTS,
  EVAL_VERDICT_LABELS,
} from '../types';
import type {
  EvalAgenda,
  EvalAgendaPage,
  EvalAgendaStatus,
  EvalLink,
  EvalNextVerdict,
  EvalReading,
  EvalReadingStats,
  EvalVerdict,
} from '../types';

/**
 * Les huit briques, dans l'ordre du pipeline.
 *
 * Le vocabulaire est celui de `sortiesbot/stages/__init__.py`, et il ne doit
 * pas diverger : la console du scraper dessine déjà son graphe avec, et deux
 * pages qui nomment différemment le même étage se contrediraient.
 */
const BRICKS = [
  { no: 1, name: 'Découverte', why: "Son entrée est le web entier, pas une page : elle ne s'évalue qu'en conditions réelles, par comparaison entre gabarits de requêtes." },
  { no: 2, name: 'Reconnaissance', why: "Une page, une étiquette humaine. Ce qu'on y mesure n'est pas l'exactitude mais une matrice de coûts : confondre un agenda avec une fiche coûte tous ses liens, l'inverse coûte un appel." },
  { no: 3, name: 'Dépouillement', why: '' },
  { no: 4, name: 'Sélection', why: "Le point aveugle : un lien écarté n'est relu par personne. Il faudra un budget d'exploration, ou le vivier commun de plusieurs variantes." },
  { no: 5, name: 'Lecture', why: '' },
  { no: 6, name: 'Extraction', why: "Champ par champ, jamais fiche par fiche. Plus la vérification d'ancrage, qui ne coûte aucune étiquette : toute valeur extraite doit se retrouver dans la page." },
  { no: 7, name: 'Attribution', why: "Partiellement mesurée déjà, depuis la page d'une exécution : ce que le moteur rend, ce que le tamis refuse." },
  { no: 8, name: 'Publication', why: "Un contrat d'API. Des tests unitaires suffisent, et il y en a." },
] as const;

const VERDICTS: EvalVerdict[] = ['SORTIE', 'PAGINATION', 'SOUS_AGENDA', 'AUTRE'];

/** Les quatre vues d'une page. « Retenus » d'abord : c'est par là qu'on commence. */
const FILTERS = [
  { key: 'kept', label: 'Retenus' },
  { key: 'dropped', label: 'Écartés' },
  { key: 'todo', label: 'À revoir' },
  { key: 'diff', label: 'Désaccords' },
  { key: 'all', label: 'Tous' },
] as const;
type FilterKey = (typeof FILTERS)[number]['key'];

const tab = ref(3);

const agendas = ref<EvalAgenda[]>([]);
const loading = ref(true);
const error = ref('');
const notice = ref('');

const form = ref({ url: '', pages: 1, label: '' });
const adding = ref(false);

const openAgendas = ref(new Set<number>());
const openPages = ref(new Set<number>());

/** Le filtre courant, commun à toutes les pages : on travaille page par page. */
const filter = ref<FilterKey>('kept');
/** Motif de rejet affiché ; vide = tous. Ne s'applique qu'aux écartés. */
const reason = ref('');

const addingTo = ref<number | null>(null);
const newLink = ref({ url: '', text: '' });
const savingLink = ref(false);

/** Liens dont le verdict est en cours d'envoi, pour ne pas cliquer deux fois. */
const saving = ref(new Set<number>());
const busy = ref(new Set<number>());

// ─────────────────────────────────────────── étage 5 : le banc de lecture

const readings = ref<EvalReading[]>([]);
const readStats = ref<EvalReadingStats | null>(null);
const readForm = ref({ url: '', label: '' });
const addingRead = ref(false);
const openReadings = ref(new Set<number>());

let poll: ReturnType<typeof setInterval> | null = null;

const waiting = computed(() =>
  agendas.value.some((a) => a.status === 'QUEUED' || a.status === 'RUNNING'),
);

async function load(quiet = false) {
  if (!quiet) loading.value = true;
  try {
    const data = await api.get<{ agendas: EvalAgenda[] }>('/api/eval/agendas');
    agendas.value = data.agendas;
    if (!quiet) error.value = '';
  } catch (e) {
    if (!quiet) error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
}

async function loadReadings(quiet = false) {
  try {
    const data = await api.get<{ readings: EvalReading[]; stats: EvalReadingStats }>(
      '/api/eval/readings',
    );
    readings.value = data.readings;
    readStats.value = data.stats;
  } catch (e) {
    if (!quiet) error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

function tick() {
  if (waiting.value) load(true);
  if (readings.value.some((r) => r.status === 'QUEUED' || r.status === 'RUNNING')) {
    loadReadings(true);
  }
}

onMounted(async () => {
  await Promise.all([load(), loadReadings()]);
  poll = setInterval(tick, 5000);
});
onUnmounted(() => {
  if (poll) clearInterval(poll);
});

function replace(agenda: EvalAgenda) {
  const index = agendas.value.findIndex((a) => a.id === agenda.id);
  if (index === -1) agendas.value.unshift(agenda);
  else agendas.value[index] = agenda;
}

/**
 * Déplie ou replie. Un `Set` neuf à chaque fois : Vue ne suit pas les mutations
 * d'un `Set` derrière un `ref`, et muter celui en place n'afficherait rien.
 */
function flip(current: Set<number>, id: number): Set<number> {
  const next = new Set(current);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

function toggleAgenda(id: number) {
  openAgendas.value = flip(openAgendas.value, id);
}

function togglePage(id: number) {
  openPages.value = flip(openPages.value, id);
}

function mark(set: typeof busy, id: number, on: boolean) {
  const next = new Set(set.value);
  if (on) next.add(id);
  else next.delete(id);
  set.value = next;
}

async function act<T>(id: number, run: () => Promise<T>): Promise<T | null> {
  error.value = '';
  notice.value = '';
  mark(busy, id, true);
  try {
    return await run();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
    return null;
  } finally {
    mark(busy, id, false);
  }
}

// ───────────────────────────────────────────────────────────── la mesure

/**
 * Le désaccord entre la brique et l'humain — l'erreur, dans un sens ou l'autre.
 *
 * C'est la seule chose que cette console cherche à faire voir : un lien retenu
 * qui n'est pas une sortie a coûté un appel payant pour rien, un lien écarté
 * qui en est une est une sortie que personne n'aurait jamais vue.
 */
function disagrees(link: EvalLink): boolean {
  return link.harvested !== (link.verdict === 'SORTIE');
}

/** Corrige le verdict d'un lien. C'est le geste que toute la page entoure. */
async function setVerdict(link: EvalLink, verdict: EvalVerdict) {
  if (link.verdict === verdict) return;
  error.value = '';
  mark(saving, link.id, true);
  const before = link.verdict;
  // Optimiste : le bouton répond tout de suite, sinon corriger deux cents
  // liens serait insupportable. On revient en arrière si le serveur refuse.
  link.verdict = verdict;
  try {
    const data = await api.patch<{ agenda: EvalAgenda }>(`/api/eval/links/${link.id}`, {
      verdict,
    });
    replace(data.agenda);
  } catch (e) {
    link.verdict = before;
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    mark(saving, link.id, false);
  }
}

// ─────────────────────────────────────────────────────────── les agendas

async function addAgenda() {
  error.value = '';
  notice.value = '';
  adding.value = true;
  try {
    const data = await api.post<{ agenda: EvalAgenda }>('/api/eval/agendas', {
      url: form.value.url.trim(),
      pages: form.value.pages,
      label: form.value.label.trim(),
    });
    replace(data.agenda);
    openAgendas.value = new Set([...openAgendas.value, data.agenda.id]);
    form.value = { url: '', pages: form.value.pages, label: '' };
    notice.value = 'Agenda mis en file : le worker le relèvera à son prochain passage.';
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    adding.value = false;
  }
}

async function analyze(agenda: EvalAgenda) {
  if (
    agenda.stats.reviewed > 0 &&
    !confirm(
      `Relancer l'analyse effacera les ${agenda.stats.reviewed} verdict(s) que vous avez donné(s).\n\n` +
        "Ils décrivaient la page telle qu'elle était : elle va être retéléchargée, " +
        "elle a pu changer, et les garder les rattacherait à un HTML qu'ils n'ont jamais décrit.",
    )
  ) {
    return;
  }
  const data = await act(agenda.id, () =>
    api.post<{ agenda: EvalAgenda }>(`/api/eval/agendas/${agenda.id}/analyze`),
  );
  if (data) replace(data.agenda);
}

async function validate(agenda: EvalAgenda) {
  const data = await act(agenda.id, () =>
    api.post<{ agenda: EvalAgenda }>(`/api/eval/agendas/${agenda.id}/validate`),
  );
  if (data) {
    replace(data.agenda);
    notice.value = 'Vérité de référence enregistrée : cet agenda compte désormais dans la mesure.';
  }
}

async function remove(agenda: EvalAgenda) {
  if (!confirm(`Supprimer « ${title(agenda)} » et tout ce qui a été relevé dessus ?`)) return;
  const done = await act(agenda.id, () => api.delete(`/api/eval/agendas/${agenda.id}`));
  if (done) agendas.value = agendas.value.filter((a) => a.id !== agenda.id);
}

function openAdd(page: EvalAgendaPage) {
  addingTo.value = addingTo.value === page.id ? null : page.id;
  newLink.value = { url: '', text: '' };
}

async function addLink(page: EvalAgendaPage) {
  error.value = '';
  savingLink.value = true;
  try {
    const data = await api.post<{ agenda: EvalAgenda }>(`/api/eval/pages/${page.id}/links`, {
      url: newLink.value.url.trim(),
      text: newLink.value.text.trim(),
      verdict: 'SORTIE',
    });
    replace(data.agenda);
    newLink.value = { url: '', text: '' };
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    savingLink.value = false;
  }
}

/**
 * Donne le même verdict à tous les écartés d'un motif. Un raccourci, et une
 * lame à double tranchant.
 *
 * Soixante-seize écartés se lisent mal un par un, et la plupart sont du bruit
 * évident. Mais trancher en masse un motif qu'on n'a pas lu fabrique un rappel
 * flatteur — d'où la confirmation qui nomme le motif et le compte, et le fait
 * que ça ne touche jamais les liens retenus.
 */
async function bulk(page: EvalAgendaPage, agendaId: number, verdict: EvalVerdict) {
  const cible = reason.value
    ? `les ${reasons(page).find((r) => r.key === reason.value)?.count ?? 0} lien(s) « ${reason.value} »`
    : `les ${counts(page).dropped} lien(s) écarté(s) de cette page`;
  if (
    !confirm(
      `Marquer « ${EVAL_VERDICT_LABELS[verdict]} » ${cible} ?\n\n` +
        "Rien ne sera touché parmi les liens retenus. Ne le faites que sur un motif " +
        "dont vous avez lu assez de lignes pour savoir ce qu'il contient : trancher " +
        'en masse ce qu\'on n\'a pas lu fabrique un rappel flatteur.',
    )
  ) {
    return;
  }
  const data = await act(agendaId, () =>
    api.post<{ agenda: EvalAgenda; count: number }>(`/api/eval/pages/${page.id}/verdict`, {
      verdict,
      reason: reason.value || undefined,
    }),
  );
  if (data) {
    replace(data.agenda);
    notice.value = `${data.count} lien(s) marqué(s) « ${EVAL_VERDICT_LABELS[verdict]} ».`;
  }
}

async function removeLink(agendaId: number, linkId: number) {
  const data = await act(agendaId, () =>
    api.delete<{ agenda: EvalAgenda }>(`/api/eval/links/${linkId}`),
  );
  if (data) replace(data.agenda);
}

// ──────────────────────────────────────────────────────────── affichage

function title(agenda: EvalAgenda) {
  return agenda.label || agenda.url;
}

function statusLabel(status: EvalAgendaStatus) {
  return EVAL_STATUS_LABELS[status];
}

function percent(value: number | null) {
  return value === null ? '—' : `${Math.round(value * 100)} %`;
}

function when(value: string | null) {
  if (!value) return '';
  return new Date(value).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
}

function counts(page: EvalAgendaPage) {
  const kept = page.links.filter((l) => l.harvested).length;
  return {
    kept,
    dropped: page.links.length - kept,
    todo: page.links.filter((l) => !l.reviewed).length,
    diff: page.links.filter(disagrees).length,
  };
}

/** Le compte du filtre `key` sur cette page — pour la pastille du bouton. */
function tally(page: EvalAgendaPage, key: FilterKey): number {
  if (key === 'all') return page.links.length;
  return counts(page)[key];
}

/** Les motifs de rejet présents sur cette page, du plus fréquent au moins. */
function reasons(page: EvalAgendaPage): { key: string; count: number }[] {
  const tally = new Map<string, number>();
  for (const link of page.links) {
    if (link.harvested || !link.dropReason) continue;
    tally.set(link.dropReason, (tally.get(link.dropReason) ?? 0) + 1);
  }
  return [...tally.entries()]
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count);
}

function visible(page: EvalAgendaPage): EvalLink[] {
  let links = page.links;
  if (filter.value === 'kept') links = links.filter((l) => l.harvested);
  else if (filter.value === 'dropped') links = links.filter((l) => !l.harvested);
  else if (filter.value === 'todo') links = links.filter((l) => !l.reviewed);
  else if (filter.value === 'diff') links = links.filter(disagrees);
  if (reason.value && filter.value === 'dropped') {
    links = links.filter((l) => l.dropReason === reason.value);
  }
  return links;
}

function pageSummary(page: EvalAgendaPage) {
  if (page.error) return page.error;
  const { kept } = counts(page);
  return `${page.links.length} lien(s) relevé(s), ${kept} retenu(s) par la brique`;
}

/**
 * La vérification de la pagination, page par page.
 *
 * Trois cas, et le troisième est celui que le banc existe pour attraper : le
 * site offre visiblement une suite, et `next_page()` ne la voit pas — parce
 * qu'elle n'est pas déclarée en `rel="next"`. Cette page-là ne sera jamais
 * suivie, et rien ailleurs ne le signale.
 */
function pagination(page: EvalAgendaPage): { tone: 'ok' | 'bad' | 'todo'; text: string } | null {
  if (page.error) return null;
  // Le constat, factuel : ce que `next_page()` a trouvé. Ce n'est pas un
  // jugement — c'est l'humain qui tranche, juste en dessous.
  const trouve = page.nextUrl
    ? `L'étage 3 suivrait ${page.nextUrl}`
    : "L'étage 3 n'a trouvé aucun « rel=next » sur cette page";
  if (!page.nextVerdict) return { tone: 'todo', text: trouve };
  if (page.nextVerdict === 'CORRECT') {
    return {
      tone: 'ok',
      text: page.nextUrl ? `${trouve} — et c'est bien la suite.` : `${trouve}, et il n'y en a pas.`,
    };
  }
  const attendu = page.nextExpected ? ` La vraie suite est ${page.nextExpected}.` : '';
  return {
    tone: 'bad',
    text:
      page.nextVerdict === 'MANQUEE'
        ? `${trouve} — alors qu'il y a bien une suite.${attendu} Ratage de pagination.`
        : `${trouve} — qui n'est pas la suite.${attendu} Il court après une fausse page.`,
  };
}

/**
 * Les réponses proposées, qui dépendent de ce que la brique a trouvé.
 *
 * Sans `rel="next"`, « fausse » n'a pas de sens : on ne court après rien.
 */
function nextChoices(page: EvalAgendaPage): { key: EvalNextVerdict; label: string }[] {
  const juste = page.nextUrl ? "C'est bien la suite" : "Il n'y a pas de suite";
  const choix: { key: EvalNextVerdict; label: string }[] = [
    { key: 'CORRECT', label: juste },
    { key: 'MANQUEE', label: 'Il a raté la suite' },
  ];
  if (page.nextUrl) choix.push({ key: 'FAUSSE', label: "Ce n'est pas la suite" });
  return choix;
}

/** La page dont on saisit l'adresse de la vraie suite, et ce qui est tapé. */
const expectingFor = ref<number | null>(null);
const expected = ref('');

/**
 * Enregistre le verdict de pagination d'une page.
 *
 * `CORRECT` se pose d'un clic. Les deux autres ouvrent un champ facultatif :
 * savoir que la brique s'est trompée ne dit pas ce qu'elle aurait dû trouver, et
 * c'est cette adresse-là qui permettra de réparer `next_page()`.
 */
async function setNext(page: EvalAgendaPage, agendaId: number, verdict: EvalNextVerdict) {
  if (verdict !== 'CORRECT' && expectingFor.value !== page.id) {
    expectingFor.value = page.id;
    expected.value = page.nextExpected;
    // Premier clic : on ouvre le champ. Le second, sur le même bouton,
    // enregistre — avec ou sans adresse, elle reste facultative.
    if (page.nextVerdict !== verdict) return;
  }
  const data = await act(agendaId, () =>
    api.patch<{ agenda: EvalAgenda }>(`/api/eval/pages/${page.id}/next`, {
      verdict,
      expected: verdict === 'CORRECT' ? '' : expected.value.trim(),
    }),
  );
  if (data) {
    replace(data.agenda);
    expectingFor.value = null;
    expected.value = '';
  }
}

/** Ce que la moisson a manqué en pages, dit en une phrase. */
function pagesVerdict(agenda: EvalAgenda): string {
  const { pagesAsked, pagesRead, stop } = agenda.stats;
  const manque = `${pagesAsked} page(s) demandée(s), ${pagesRead} lue(s).`;
  if (stop === 'sans_suite') {
    return `${manque} L'étage 3 n'a trouvé aucun « rel=next » sur la dernière — s'il y a bien une suite, c'est un ratage de la pagination, et parcourir les pages fait partie de son travail.`;
  }
  if (stop === 'injoignable') {
    return `${manque} La page suivante a refusé la lecture : ce n'est pas la brique qu'il faut accuser.`;
  }
  if (stop === 'boucle') {
    return `${manque} Le « rel=next » de la dernière renvoyait vers une page déjà lue : cet agenda boucle.`;
  }
  return '';
}

function replaceReading(reading: EvalReading) {
  const index = readings.value.findIndex((r) => r.id === reading.id);
  if (index === -1) readings.value.unshift(reading);
  else readings.value[index] = reading;
  // Les taux se recalculent au serveur, sur l'ensemble du banc : les recopier
  // ici en aurait fait une seconde vérité, qui aurait fini par diverger.
  loadReadings(true);
}

function toggleReading(id: number) {
  openReadings.value = flip(openReadings.value, id);
}

async function addReading() {
  error.value = '';
  notice.value = '';
  addingRead.value = true;
  try {
    const data = await api.post<{ reading: EvalReading }>('/api/eval/readings', {
      url: readForm.value.url.trim(),
      label: readForm.value.label.trim(),
    });
    replaceReading(data.reading);
    openReadings.value = new Set([...openReadings.value, data.reading.id]);
    readForm.value = { url: '', label: '' };
    notice.value = 'Page mise en file : le worker la lira à son prochain passage.';
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    addingRead.value = false;
  }
}

/** Trancher un aspect. C'est le geste que cet onglet existe pour permettre. */
async function setAspect(reading: EvalReading, key: string, value: string) {
  const data = await act(reading.id, () =>
    api.patch<{ reading: EvalReading }>(`/api/eval/readings/${reading.id}`, { [key]: value }),
  );
  if (data) replaceReading(data.reading);
}

async function analyzeReading(reading: EvalReading) {
  if (
    reading.judged &&
    !confirm(
      "Relancer la lecture effacera les trois verdicts.\n\nIls décrivaient la page telle " +
        "qu'elle était : elle va être retéléchargée, et elle a pu changer.",
    )
  ) {
    return;
  }
  const data = await act(reading.id, () =>
    api.post<{ reading: EvalReading }>(`/api/eval/readings/${reading.id}/analyze`),
  );
  if (data) replaceReading(data.reading);
}

async function validateReading(reading: EvalReading) {
  const data = await act(reading.id, () =>
    api.post<{ reading: EvalReading }>(`/api/eval/readings/${reading.id}/validate`),
  );
  if (data) {
    replaceReading(data.reading);
    notice.value = 'Vérité de référence enregistrée : cette page compte dans la mesure.';
  }
}

async function removeReading(reading: EvalReading) {
  if (!confirm(`Supprimer « ${reading.label || reading.url} » et ce qui en a été relevé ?`)) return;
  const done = await act(reading.id, () => api.delete(`/api/eval/readings/${reading.id}`));
  if (done) readings.value = readings.value.filter((r) => r.id !== reading.id);
}

/**
 * Les signaux gratuits d'une page, en clair.
 *
 * Ils ne décident de rien — la brique a déjà rendu ce qu'elle rend, et c'est ce
 * rendu qu'on mesure. Ils disent seulement **où regarder**, et le premier est
 * de loin le plus utile : un titre absent du texte extrait veut presque
 * toujours dire qu'un `<header>` a été décapé, et avec lui les dates.
 */
function readFlags(r: EvalReading): { tone: 'bad' | 'warn'; text: string }[] {
  const flags: { tone: 'bad' | 'warn'; text: string }[] = [];
  if (r.tooShort) {
    flags.push({
      tone: 'bad',
      text: `Sous le seuil des 200 caractères : le pipeline aurait abandonné cette page avant le moindre appel payant.`,
    });
  }
  if (r.heading && !r.h1InText) {
    flags.push({
      tone: 'bad',
      text: `Le titre de la page — « ${r.heading} » — ne se retrouve pas dans le texte extrait. Un bloc a été décapé, et souvent les dates avec.`,
    });
  }
  if (r.truncated) {
    flags.push({
      tone: 'warn',
      text: 'Texte coupé au plafond : la fin de la page n’atteindra jamais le modèle.',
    });
  }
  if (r.imageLooksLogo) {
    flags.push({ tone: 'warn', text: "L'adresse de l'illustration ressemble à celle d'un logo." });
  }
  if (!r.imageUrl && !r.error) {
    flags.push({ tone: 'warn', text: 'Aucune illustration retenue.' });
  }
  if (!r.dates.length && !r.error) {
    flags.push({ tone: 'warn', text: 'Aucune date JSON-LD relevée.' });
  }
  if (r.swapped) {
    flags.push({ tone: 'warn', text: `Échange de langue : la page lue est ${r.readUrl}` });
  }
  return flags;
}

const current = computed(() => BRICKS.find((b) => b.no === tab.value)!);
</script>

<template>
  <div class="container page">
    <nav class="row admin-nav">
      <RouterLink to="/admin">Utilisateurs</RouterLink>
      <RouterLink to="/admin/categories">Catégories</RouterLink>
      <RouterLink to="/admin/zones">Zones</RouterLink>
      <RouterLink to="/admin/evaluation">Banc d'évaluation</RouterLink>
    </nav>
    <h1>Banc d'évaluation</h1>
    <p class="muted lede">
      Mesurer ce que chaque brique rend vraiment, plutôt que d'espérer qu'elle rende ce qu'il faut.
      Deux étages sont ouverts — le <strong>dépouillement</strong>, qui décide quels liens partent au
      tri, et la <strong>lecture</strong>, qui décide ce que le modèle verra de la page.
    </p>

    <nav class="tabs" aria-label="Les huit briques du scraper">
      <button
        v-for="brick in BRICKS"
        :key="brick.no"
        type="button"
        class="tab"
        :class="{ active: tab === brick.no, ready: brick.no === 3 }"
        :aria-current="tab === brick.no ? 'page' : undefined"
        @click="tab = brick.no"
      >
        <span class="no">{{ brick.no }}</span>
        <span class="name">{{ brick.name }}</span>
      </button>
    </nav>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="success">{{ notice }}</p>

    <!-- ─────────────────────────────────────────── 5. la lecture -->
    <section v-if="tab === 5" class="brick3">
      <div class="card intro">
        <h2>5. Lecture — ce que la brique tire d'une fiche</h2>
        <p>
          L'étage 5 lit <strong>trois fois</strong> un même HTML : le texte qui part au modèle, les
          dates que le site déclare en JSON-LD, et l'illustration. Et il en tire une décision — sous
          deux cents caractères, la page est <strong>abandonnée</strong> avant le moindre appel
          payant.
        </p>
        <p>
          Trois verdicts plutôt qu'un, parce que les trois se ratent séparément et ne se réparent
          pas au même endroit : un texte amputé accuse la liste des balises décapées
          (<code>nav header footer aside form</code>), un texte tronqué accuse le plafond de
          caractères, une illustration qui est le logo du site accuse le tamis des images.
        </p>
        <p class="rule">
          <strong>Le signal à regarder en premier :</strong> quand le titre de la page ne se
          retrouve pas dans le texte extrait, c'est qu'un bloc a été décapé — presque toujours un
          <code>&lt;header&gt;</code>, et les dates et l'adresse sont parties avec. Le texte reste
          non vide, rien ne proteste, et c'est l'extraction qu'on ira accuser de rendre une fiche
          sans date.
        </p>
      </div>

      <form class="card form add" @submit.prevent="addReading">
        <div class="row">
          <div class="field grow">
            <label for="read-url">Adresse d'une fiche</label>
            <input
              id="read-url"
              v-model="readForm.url"
              type="url"
              required
              placeholder="https://exemple.fr/agenda/le-spectacle"
            />
          </div>
          <div class="field">
            <label for="read-label">Nom (facultatif)</label>
            <input id="read-label" v-model="readForm.label" type="text" maxlength="150" />
          </div>
          <div class="field submit">
            <button class="btn" type="submit" :disabled="addingRead || !readForm.url.trim()">
              {{ addingRead ? 'Envoi…' : 'Lire' }}
            </button>
          </div>
        </div>
        <p class="hint pages-why">
          Une <strong>fiche</strong>, pas un agenda : ce ne sont pas les mêmes pages, donc pas le
          même corpus. Prenez-les dans les liens que l'étage 3 a retenus — ce sont exactement celles
          que le pipeline lirait.
        </p>
      </form>

      <dl v-if="readStats && readStats.pages" class="stats card readstats">
        <div>
          <dt>Pages</dt>
          <dd>{{ readStats.pages }}</dd>
        </div>
        <div :class="{ warn: readStats.judged < readStats.pages }">
          <dt title="Les trois aspects tranchés">Jugées</dt>
          <dd>{{ readStats.judged }} / {{ readStats.pages }}</dd>
        </div>
        <div class="rate">
          <dt>Texte juste</dt>
          <dd>{{ percent(readStats.textOk) }}</dd>
        </div>
        <div class="rate">
          <dt>Illustration juste</dt>
          <dd>{{ percent(readStats.imageOk) }}</dd>
        </div>
        <div class="rate">
          <dt>Dates justes</dt>
          <dd>{{ percent(readStats.datesOk) }}</dd>
        </div>
        <div :class="{ flag: readStats.ampute > 0 }">
          <dt title="Le décapage a emporté une partie de la page">Amputés</dt>
          <dd>{{ readStats.ampute }}</dd>
        </div>
        <div :class="{ flag: readStats.tronque > 0 }">
          <dt title="Le plafond de caractères a coupé la fin">Tronqués</dt>
          <dd>{{ readStats.tronque }}</dd>
        </div>
        <div :class="{ flag: readStats.abandonnees > 0 }">
          <dt title="Sous le seuil : le pipeline les aurait abandonnées">Abandonnées</dt>
          <dd>{{ readStats.abandonnees }}</dd>
        </div>
      </dl>

      <p v-if="!readings.length" class="muted empty">
        Aucune fiche au banc. Une trentaine suffit à savoir si l'étage 5 lit ce qu'il devrait lire.
      </p>

      <article v-for="r in readings" :key="r.id" class="card agenda">
        <header class="agenda-head">
          <button
            type="button"
            class="disclose"
            :aria-expanded="openReadings.has(r.id)"
            @click="toggleReading(r.id)"
          >
            <span class="caret" :class="{ open: openReadings.has(r.id) }" aria-hidden="true"
              >▸</span
            >
            <span class="agenda-title">{{ r.label || r.url }}</span>
          </button>
          <span class="pill" :class="r.status.toLowerCase()">{{ statusLabel(r.status) }}</span>
        </header>

        <p class="agenda-url">
          <a :href="r.url" target="_blank" rel="noopener noreferrer">{{ r.url }}</a>
          <a
            v-if="r.archived"
            class="frozen"
            :href="`/api/eval/readings/${r.id}/html`"
            target="_blank"
            rel="noopener noreferrer"
            >voir le HTML gelé</a
          >
        </p>

        <p v-if="r.error" class="error slim">{{ r.error }}</p>

        <ul v-if="readFlags(r).length" class="flags">
          <li v-for="(f, i) in readFlags(r)" :key="i" :class="f.tone">{{ f.text }}</li>
        </ul>

        <div v-if="openReadings.has(r.id) && !r.error" class="tree">
          <div class="read-grid">
            <section class="read-col">
              <h4>Le texte — {{ r.textChars }} caractères</h4>
              <pre class="extract">{{ r.text || '(vide)' }}</pre>
            </section>
            <section class="read-col">
              <h4>Les dates JSON-LD</h4>
              <ul v-if="r.dates.length" class="dates">
                <li v-for="(d, i) in r.dates" :key="i">{{ d }}</li>
              </ul>
              <p v-else class="muted">Aucune.</p>

              <h4>L'illustration</h4>
              <template v-if="r.imageUrl">
                <a :href="r.imageUrl" target="_blank" rel="noopener noreferrer" class="imgurl">{{
                  r.imageUrl
                }}</a>
                <img :src="r.imageUrl" alt="" class="shot" loading="lazy" />
              </template>
              <p v-else class="muted">Aucune.</p>
            </section>
          </div>

          <div v-for="aspect in EVAL_READ_ASPECTS" :key="aspect.key" class="aspect">
            <span class="aspect-title">{{ aspect.title }}</span>
            <span class="seg">
              <button
                v-for="c in aspect.choices"
                :key="c.key"
                type="button"
                class="segb"
                :class="{ on: r[aspect.key] === c.key }"
                :aria-pressed="r[aspect.key] === c.key"
                :title="c.hint"
                :disabled="busy.has(r.id)"
                @click="setAspect(r, aspect.key, c.key)"
              >
                {{ c.label }}
              </button>
            </span>
            <span v-if="!r[aspect.key]" class="pre">à juger</span>
          </div>
        </div>

        <div class="actions">
          <button
            class="btn small secondary"
            type="button"
            :disabled="busy.has(r.id) || r.status === 'RUNNING'"
            @click="analyzeReading(r)"
          >
            {{ r.status === 'FAILED' ? 'Réessayer' : 'Relire' }}
          </button>
          <button
            v-if="r.status === 'ANALYZED'"
            class="btn small"
            type="button"
            :disabled="busy.has(r.id) || !r.judged"
            :title="r.judged ? 'Figer la vérité de référence' : 'Les trois aspects doivent être tranchés'"
            @click="validateReading(r)"
          >
            Valider la lecture
          </button>
          <span v-if="r.validatedAt" class="muted small-note">
            Validé le {{ when(r.validatedAt) }} · {{ r.author.displayName }}
          </span>
          <button
            class="btn small danger"
            type="button"
            :disabled="busy.has(r.id)"
            @click="removeReading(r)"
          >
            Supprimer
          </button>
        </div>
      </article>
    </section>

    <section v-else-if="tab !== 3" class="card waiting">
      <h2>{{ current.no }}. {{ current.name }}</h2>
      <p>{{ current.why }}</p>
      <p class="muted">
        Rien à mesurer ici pour l'instant : le banc s'est ouvert par le dépouillement et la lecture —
        les deux étages gratuits, en amont, dont les pannes se déguisent en pannes des étages
        payants. Les autres viendront quand ceux-là auront donné leurs premiers chiffres.
      </p>
    </section>

    <section v-else class="brick3">
      <div class="card intro">
        <h2>3. Dépouillement — la brique précoche, vous corrigez</h2>
        <p>
          Le banc relève <strong>tous</strong> les liens de la page, puis appelle le vrai
          <code>links_of</code> : ce qu'il retient est précoché « sortie », le reste « autre ». Il
          ne reste qu'à corriger ce qui est faux, et ce sont ces corrections qui sont la mesure.
        </p>
        <p>
          C'est ce qui donne les <strong>deux</strong> erreurs. Un lien retenu qui ne mène nulle
          part a coûté un appel payant à l'étage 4 ; un lien écarté qui était une sortie est une
          sortie que personne n'aurait jamais vue — et celle-là ne coûte rien, donc ne se voit
          nulle part.
        </p>
        <dl class="verdicts">
          <div v-for="v in VERDICTS" :key="v" :class="`v-${v.toLowerCase()}`">
            <dt>{{ EVAL_VERDICT_LABELS[v] }}</dt>
            <dd>{{ EVAL_VERDICT_HINTS[v] }}</dd>
          </div>
        </dl>
      </div>

      <form class="card form add" @submit.prevent="addAgenda">
        <div class="row">
          <div class="field grow">
            <label for="eval-url">Adresse de l'agenda</label>
            <input
              id="eval-url"
              v-model="form.url"
              type="url"
              required
              placeholder="https://exemple.fr/agenda/"
            />
          </div>
          <div class="field narrow">
            <label for="eval-pages">Pages</label>
            <input id="eval-pages" v-model.number="form.pages" type="number" min="1" max="10" />
            <span class="hint">1re comprise</span>
          </div>
          <div class="field">
            <label for="eval-label">Nom (facultatif)</label>
            <input id="eval-label" v-model="form.label" type="text" maxlength="150" />
          </div>
          <div class="field submit">
            <button class="btn" type="submit" :disabled="adding || !form.url.trim()">
              {{ adding ? 'Envoi…' : 'Analyser' }}
            </button>
          </div>
        </div>
        <p class="hint pages-why">
          Un nombre fixe, et non la règle de l'étage 3 qui suit sa pagination tant qu'il manque de
          liens : ce qu'on mesure ici est <code>links_of</code> sur une page donnée. Ce que la
          pagination donnerait est mesuré à part, page par page.
        </p>
      </form>

      <p v-if="loading" class="muted">Chargement…</p>
      <p v-else-if="!agendas.length" class="muted empty">
        Aucun agenda au banc. Ajoutez-en un ci-dessus — une dizaine suffit à savoir si le
        dépouillement voit ce qu'il devrait voir.
      </p>

      <article v-for="agenda in agendas" :key="agenda.id" class="card agenda">
        <header class="agenda-head">
          <button
            type="button"
            class="disclose"
            :aria-expanded="openAgendas.has(agenda.id)"
            @click="toggleAgenda(agenda.id)"
          >
            <span class="caret" :class="{ open: openAgendas.has(agenda.id) }" aria-hidden="true"
              >▸</span
            >
            <span class="agenda-title">{{ title(agenda) }}</span>
          </button>
          <span class="pill" :class="agenda.status.toLowerCase()">
            {{ statusLabel(agenda.status) }}
          </span>
        </header>

        <p class="agenda-url">
          <a :href="agenda.url" target="_blank" rel="noopener noreferrer">{{ agenda.url }}</a>
          <span class="muted"> · {{ agenda.pages }} page(s) demandée(s)</span>
        </p>

        <p v-if="agenda.error" class="error slim">{{ agenda.error }}</p>
        <p v-if="pagesVerdict(agenda)" class="pages-short">{{ pagesVerdict(agenda) }}</p>

        <dl class="stats">
          <div>
            <dt>Relevés</dt>
            <dd>{{ agenda.stats.links }}</dd>
          </div>
          <div>
            <dt>Retenus</dt>
            <dd>{{ agenda.stats.kept }}</dd>
          </div>
          <div>
            <dt>Sorties</dt>
            <dd>{{ agenda.stats.sorties }}</dd>
          </div>
          <div :class="{ flag: agenda.stats.keptWrong > 0 }">
            <dt title="Ils ont coûté un appel à l'étage 4 pour rien">Retenus à tort</dt>
            <dd>{{ agenda.stats.keptWrong }}</dd>
          </div>
          <div :class="{ flag: agenda.stats.missed > 0 }">
            <dt title="Personne ne les aurait jamais vues">Sorties perdues</dt>
            <dd>{{ agenda.stats.missed }}</dd>
          </div>
          <div :class="{ warn: agenda.stats.sousAgendas > 0 }">
            <dt title="Le pipeline n'en fait rien aujourd'hui">Sous-agendas</dt>
            <dd>{{ agenda.stats.sousAgendas }}</dd>
          </div>
          <div :class="{ flag: agenda.stats.pagesRead < agenda.stats.pagesAsked }">
            <dt title="Parcourir les pages fait partie du travail de la brique">Pages lues</dt>
            <dd>{{ agenda.stats.pagesRead }} / {{ agenda.stats.pagesAsked }}</dd>
          </div>
          <div :class="{ flag: agenda.stats.paginationManquee > 0 }">
            <dt title="Le site offrait une suite, la brique ne l'a pas vue">Suites ratées</dt>
            <dd>{{ agenda.stats.paginationManquee }}</dd>
          </div>
          <div :class="{ flag: agenda.stats.paginationFausse > 0 }">
            <dt title="La brique a couru après une page qui n'était pas la suite">
              Fausses suites
            </dt>
            <dd>{{ agenda.stats.paginationFausse }}</dd>
          </div>
          <div :class="{ warn: agenda.stats.reviewed < agenda.stats.links }">
            <dt title="Tranchés par un humain, pas par la précoche">Revus</dt>
            <dd>{{ agenda.stats.reviewed }} / {{ agenda.stats.links }}</dd>
          </div>
          <div class="rate">
            <dt title="De ce que la brique donne à l'étage 4, la part qui est une sortie">
              Précision
            </dt>
            <dd>{{ percent(agenda.stats.precision) }}</dd>
          </div>
          <div class="rate">
            <dt title="La part qui mène quelque part de réel : sortie, pagination ou sous-agenda">
              dont utiles
            </dt>
            <dd>{{ percent(agenda.stats.precisionUseful) }}</dd>
          </div>
          <div class="rate">
            <dt>Rappel</dt>
            <dd>{{ percent(agenda.stats.recall) }}</dd>
          </div>
        </dl>
        <p v-if="agenda.stats.precision === null && agenda.status === 'ANALYZED'" class="hint">
          <template v-if="agenda.stats.pagesJugees < agenda.stats.pagesRead">
            <strong
              >{{ agenda.stats.pagesRead - agenda.stats.pagesJugees }} page(s) attendent leur
              verdict de pagination.</strong
            >
            Suivre les pages fait partie du travail de l'étage 3 : dites, pour chacune, si ce qu'il
            a trouvé — ou n'a pas trouvé — est juste.
          </template>
          <template v-else-if="agenda.stats.reviewed < agenda.stats.links">
            <strong
              >{{ agenda.stats.links - agenda.stats.reviewed }} lien(s) portent encore la précoche
              de la brique.</strong
            >
            Tant qu'ils n'ont pas été tranchés, le rappel ne pourrait dire que « personne n'a
            regardé le reste » — c'est ce qui le ferait afficher 100 % à tort. Le filtre « À
            revoir » les liste ; l'action de groupe permet d'en expédier un motif entier.
          </template>
          <template v-else>
            Tout est relu. « Valider l'extraction » fige la vérité de référence et débloque les
            taux.
          </template>
        </p>

        <div class="actions">
          <button
            class="btn small secondary"
            type="button"
            :disabled="busy.has(agenda.id) || agenda.status === 'RUNNING'"
            @click="analyze(agenda)"
          >
            {{ agenda.status === 'FAILED' ? 'Réessayer' : 'Relancer l’analyse' }}
          </button>
          <button
            v-if="agenda.status === 'ANALYZED'"
            class="btn small"
            type="button"
            :disabled="
              busy.has(agenda.id) ||
              agenda.stats.reviewed < agenda.stats.links ||
              agenda.stats.pagesJugees < agenda.stats.pagesRead
            "
            :title="
              agenda.stats.reviewed < agenda.stats.links
                ? `${agenda.stats.links - agenda.stats.reviewed} lien(s) portent encore la précoche`
                : 'Figer la vérité de référence'
            "
            @click="validate(agenda)"
          >
            Valider l’extraction
          </button>
          <span v-if="agenda.validatedAt" class="muted small-note">
            Validé le {{ when(agenda.validatedAt) }} · {{ agenda.author.displayName }}
          </span>
          <button
            class="btn small danger"
            type="button"
            :disabled="busy.has(agenda.id)"
            @click="remove(agenda)"
          >
            Supprimer
          </button>
        </div>

        <div v-if="openAgendas.has(agenda.id)" class="tree">
          <p v-if="!agenda.agendaPages.length" class="muted">
            Rien de relevé pour l'instant.
            <span v-if="agenda.status === 'QUEUED'"
              >Le worker passe toutes les trente secondes.</span
            >
          </p>

          <section v-for="page in agenda.agendaPages" :key="page.id" class="page-node">
            <button
              type="button"
              class="disclose page-head"
              :aria-expanded="openPages.has(page.id)"
              @click="togglePage(page.id)"
            >
              <span class="caret" :class="{ open: openPages.has(page.id) }" aria-hidden="true"
                >▸</span
              >
              <span class="page-no">Page {{ page.pageNo }}</span>
              <span class="page-sum" :class="{ bad: !!page.error }">{{ pageSummary(page) }}</span>
              <span v-if="counts(page).diff" class="diff-badge"
                >{{ counts(page).diff }} désaccord(s)</span
              >
              <span class="archive" :class="{ off: !page.archived }">
                {{ page.archived ? 'archivée' : 'non archivée' }}
              </span>
            </button>

            <div v-if="openPages.has(page.id)" class="page-body">
              <p class="page-url">
                <a :href="page.url" target="_blank" rel="noopener noreferrer">{{ page.url }}</a>
                <a
                  v-if="page.archived"
                  class="frozen"
                  :href="`/api/eval/pages/${page.id}/html`"
                  target="_blank"
                  rel="noopener noreferrer"
                  >voir le HTML gelé</a
                >
              </p>

              <div v-if="pagination(page)" class="pagcheck" :class="pagination(page)!.tone">
                <p class="pag-text"><strong>Pagination :</strong> {{ pagination(page)!.text }}</p>
                <div class="pag-choices">
                  <button
                    v-for="c in nextChoices(page)"
                    :key="c.key"
                    type="button"
                    class="pagb"
                    :class="{ on: page.nextVerdict === c.key }"
                    :disabled="busy.has(agenda.id)"
                    @click="setNext(page, agenda.id, c.key)"
                  >
                    {{ c.label }}
                  </button>
                </div>
                <div v-if="expectingFor === page.id" class="pag-expected">
                  <label :for="`exp-${page.id}`">
                    Adresse de la vraie page suivante — facultatif, mais c'est ce qui permettra de
                    réparer&nbsp;:
                  </label>
                  <div class="row">
                    <input
                      :id="`exp-${page.id}`"
                      v-model="expected"
                      type="url"
                      placeholder="https://exemple.fr/sorties/page/2/"
                    />
                    <button type="button" class="btn small" @click="expectingFor = null">
                      Fermer
                    </button>
                  </div>
                  <p class="hint">
                    Recliquez sur le bouton pour enregistrer. L'adresse est gardée telle quelle :
                    savoir que la brique s'est trompée ne dit pas ce qu'elle aurait dû trouver.
                  </p>
                </div>
              </div>

              <div v-if="page.links.length" class="filters-bar">
                <button
                  v-for="f in FILTERS"
                  :key="f.key"
                  type="button"
                  class="fbtn"
                  :class="{ on: filter === f.key }"
                  @click="filter = f.key"
                >
                  {{ f.label }}
                  <span class="n">{{ tally(page, f.key) }}</span>
                </button>
                <template v-if="filter === 'dropped' && reasons(page).length">
                  <span class="sep" aria-hidden="true">·</span>
                  <button
                    type="button"
                    class="rbtn"
                    :class="{ on: !reason }"
                    @click="reason = ''"
                  >
                    Tous motifs
                  </button>
                  <button
                    v-for="r in reasons(page)"
                    :key="r.key"
                    type="button"
                    class="rbtn"
                    :class="{ on: reason === r.key }"
                    @click="reason = r.key"
                  >
                    {{ r.key }} <span class="n">{{ r.count }}</span>
                  </button>
                  <button
                    type="button"
                    class="bulk"
                    :disabled="busy.has(agenda.id)"
                    :title="
                      reason
                        ? `Marquer « autre » tous les liens du motif « ${reason} »`
                        : 'Marquer « autre » tous les écartés de cette page'
                    "
                    @click="bulk(page, agenda.id, 'AUTRE')"
                  >
                    Tout marquer « autre »
                  </button>
                </template>
              </div>

              <ul v-if="visible(page).length" class="links">
                <li
                  v-for="link in visible(page)"
                  :key="link.id"
                  :class="{
                    diff: disagrees(link),
                    manual: link.source === 'MANUAL',
                    todo: !link.reviewed,
                  }"
                >
                  <span class="tag" :class="link.harvested ? 'kept' : 'dropped'">
                    {{
                      link.source === 'MANUAL'
                        ? 'ajouté'
                        : link.harvested
                          ? 'retenu'
                          : link.dropReason || 'écarté'
                    }}
                  </span>
                  <span class="link-body">
                    <a :href="link.url" target="_blank" rel="noopener noreferrer">{{ link.url }}</a>
                    <span v-if="link.text" class="link-text">{{ link.text }}</span>
                    <span v-if="link.context" class="link-context">{{ link.context }}</span>
                  </span>
                  <span
                    v-if="!link.reviewed"
                    class="pre"
                    title="Encore la proposition de la brique : personne ne l'a tranché"
                    >précoché</span
                  >
                  <span class="seg" :class="{ busy: saving.has(link.id) }">
                    <button
                      v-for="v in VERDICTS"
                      :key="v"
                      type="button"
                      class="segb"
                      :class="[`v-${v.toLowerCase()}`, { on: link.verdict === v }]"
                      :aria-pressed="link.verdict === v"
                      :title="EVAL_VERDICT_HINTS[v]"
                      @click="setVerdict(link, v)"
                    >
                      {{ EVAL_VERDICT_LABELS[v] }}
                    </button>
                  </span>
                  <button
                    v-if="link.source === 'MANUAL'"
                    class="btn small ghost"
                    type="button"
                    title="Retirer cet ajout"
                    @click="removeLink(agenda.id, link.id)"
                  >
                    Retirer
                  </button>
                </li>
              </ul>
              <p v-else class="muted none">
                Rien sous ce filtre.
                <template v-if="filter === 'kept' && !page.error">
                  La brique n'a retenu aucun lien de cette page — si elle en montre pourtant, c'est
                  exactement ce que le banc cherche à attraper : passez aux écartés.
                </template>
              </p>

              <button class="btn small secondary add-link" type="button" @click="openAdd(page)">
                {{ addingTo === page.id ? 'Fermer' : 'Ajouter un lien absent du HTML' }}
              </button>

              <form v-if="addingTo === page.id" class="form inline" @submit.prevent="addLink(page)">
                <div class="row">
                  <div class="field grow">
                    <label :for="`link-url-${page.id}`">Adresse du lien</label>
                    <input
                      :id="`link-url-${page.id}`"
                      v-model="newLink.url"
                      type="url"
                      required
                      placeholder="https://exemple.fr/agenda/le-spectacle"
                    />
                  </div>
                  <div class="field">
                    <label :for="`link-text-${page.id}`">Intitulé (facultatif)</label>
                    <input
                      :id="`link-text-${page.id}`"
                      v-model="newLink.text"
                      type="text"
                      maxlength="200"
                    />
                  </div>
                  <div class="field submit">
                    <button class="btn small" type="submit" :disabled="savingLink">
                      {{ savingLink ? 'Ajout…' : 'Ajouter' }}
                    </button>
                  </div>
                </div>
                <p class="hint">
                  Réservé à ce que le HTML ne porte pas — une carte rendue en JavaScript, par
                  exemple. Tout le reste est déjà relevé : donnez-lui plutôt son verdict.
                </p>
              </form>
            </div>
          </section>
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.admin-nav {
  gap: 1rem;
  margin-bottom: 1rem;
}
.lede {
  max-width: 62ch;
  margin-top: -0.4rem;
}

/* ---- les huit onglets ---- */
.tabs {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  margin: 1.2rem 0 1rem;
  border-bottom: 2px solid var(--line);
  padding-bottom: 0.6rem;
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  background: none;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0.35rem 0.85rem 0.35rem 0.4rem;
  font: inherit;
  font-size: 0.88rem;
  color: var(--ink-soft);
  cursor: pointer;
}
.tab:hover {
  border-color: var(--accent);
  color: var(--ink);
}
.tab .no {
  display: grid;
  place-items: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 50%;
  background: var(--line);
  color: var(--ink-soft);
  font-size: 0.75rem;
  font-weight: 700;
}
/* Le seul étage réellement mesuré se distingue même quand il n'est pas ouvert. */
.tab.ready {
  color: var(--ink);
}
.tab.ready .no {
  background: var(--ok-soft);
  color: var(--ok);
}
.tab.active {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent-dark);
  font-weight: 600;
}
.tab.active .no {
  background: var(--accent);
  color: #fff;
}

.waiting h2,
.intro h2 {
  margin-top: 0;
  font-size: 1.1rem;
}
.waiting p:last-child {
  margin-bottom: 0;
}
.intro p {
  max-width: 76ch;
}

/* ---- la légende des quatre verdicts ---- */
.verdicts {
  display: grid;
  gap: 0.5rem;
  grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
  margin: 1rem 0 0;
}
.verdicts > div {
  border-left: 3px solid var(--a, var(--line));
  padding: 0.35rem 0 0.35rem 0.7rem;
}
.verdicts dt {
  font-weight: 700;
  color: var(--a, var(--ink));
  font-size: 0.88rem;
}
.verdicts dd {
  margin: 0.1rem 0 0;
  font-size: 0.82rem;
  color: var(--ink-soft);
  line-height: 1.4;
}
.v-sortie {
  --a: var(--ok);
}
.v-pagination {
  --a: var(--accent-dark);
}
.v-sous_agenda {
  --a: var(--warn);
}
.v-autre {
  --a: var(--ink-soft);
}

/* ---- ajout d'un agenda ---- */
.add {
  margin-top: 1rem;
  max-width: none;
}
.add .row {
  display: grid;
  grid-template-columns: 1fr 7.5rem 14rem auto;
  align-items: end;
  gap: 0.9rem;
}
@media (max-width: 860px) {
  .add .row {
    grid-template-columns: 1fr 7.5rem;
  }
  .add .field.grow,
  .add .field.submit {
    grid-column: 1 / -1;
  }
}
.field.submit .btn {
  width: 100%;
}
.pages-why {
  margin: 0.7rem 0 0;
  max-width: 76ch;
}
.empty {
  margin-top: 1.4rem;
}

/* ---- un agenda ---- */
.agenda {
  margin-top: 1rem;
}
.agenda-head {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  justify-content: space-between;
}
.disclose {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  color: var(--ink);
  cursor: pointer;
  text-align: left;
}
.caret {
  display: inline-block;
  color: var(--ink-soft);
  transition: transform 0.15s ease;
}
.caret.open {
  transform: rotate(90deg);
}
@media (prefers-reduced-motion: reduce) {
  .caret {
    transition: none;
  }
}
.agenda-title {
  font-weight: 700;
  font-size: 1.02rem;
}
.agenda-url {
  margin: 0.35rem 0 0.7rem;
  font-size: 0.85rem;
  word-break: break-all;
}

.pill {
  flex: none;
  border-radius: 999px;
  padding: 0.15rem 0.65rem;
  font-size: 0.76rem;
  font-weight: 600;
  background: var(--line);
  color: var(--ink-soft);
}
.pill.queued,
.pill.running {
  background: var(--warn-soft);
  color: var(--warn);
}
.pill.analyzed {
  background: var(--accent-soft);
  color: var(--accent-dark);
}
.pill.validated {
  background: var(--ok-soft);
  color: var(--ok);
}
.pill.failed {
  background: var(--danger-soft);
  color: var(--danger);
}

.stats {
  display: flex;
  gap: 1.4rem;
  margin: 0 0 0.6rem;
  flex-wrap: wrap;
}
.stats div {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}
.stats dt {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ink-soft);
  white-space: nowrap;
}
.stats dd {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
/* Les deux erreurs sont le chiffre du banc : elles se voient, ou la page ne
   sert à rien. */
.stats .flag dd,
.stats .flag dt {
  color: var(--danger);
}
.stats .warn dd,
.stats .warn dt {
  color: var(--warn);
}
.stats .rate dd {
  color: var(--accent-dark);
}

.actions {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  flex-wrap: wrap;
  margin-top: 0.4rem;
}
.small-note {
  font-size: 0.8rem;
}
.error.slim {
  margin: 0.4rem 0;
  font-size: 0.86rem;
}

/* ---- l'arbre ---- */
.tree {
  margin-top: 1rem;
  border-top: 1px solid var(--line);
  padding-top: 0.8rem;
}
.page-node {
  border-left: 2px solid var(--line);
  padding-left: 0.9rem;
  margin-bottom: 0.5rem;
}
.page-head {
  width: 100%;
  gap: 0.7rem;
  padding: 0.3rem 0;
  flex-wrap: wrap;
}
.page-no {
  font-weight: 700;
  font-size: 0.9rem;
}
.page-sum {
  font-size: 0.85rem;
  color: var(--ink-soft);
}
.page-sum.bad {
  color: var(--danger);
}
.diff-badge {
  font-size: 0.72rem;
  font-weight: 700;
  border-radius: 5px;
  padding: 0.1rem 0.45rem;
  background: var(--danger-soft);
  color: var(--danger);
}
.archive {
  font-size: 0.72rem;
  font-weight: 600;
  border-radius: 5px;
  padding: 0.1rem 0.4rem;
  background: var(--ok-soft);
  color: var(--ok);
}
.archive.off {
  background: var(--warn-soft);
  color: var(--warn);
}
.page-body {
  padding: 0.3rem 0 0.8rem;
}
.page-url {
  margin: 0 0 0.5rem;
  font-size: 0.8rem;
  word-break: break-all;
}
.frozen {
  margin-left: 0.7rem;
  white-space: nowrap;
}

.pagcheck {
  margin: 0 0 0.7rem;
  font-size: 0.83rem;
  border-left: 3px solid var(--ok);
  background: var(--ok-soft);
  border-radius: 0 8px 8px 0;
  padding: 0.5rem 0.7rem;
  word-break: break-word;
}
.pagcheck.bad {
  border-color: var(--danger);
  background: var(--danger-soft);
}
/* Ni bon ni mauvais : on ne sait pas encore, et le dire est la seule réponse
   honnête tant que personne n'a relu les liens de la page. */
.pagcheck.todo {
  border-color: var(--warn);
  background: var(--warn-soft);
}
.pag-text {
  margin: 0;
}
.pag-choices {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
  margin-top: 0.5rem;
}
.pagb {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0.2rem 0.7rem;
  font: inherit;
  font-size: 0.78rem;
  color: var(--ink-soft);
  cursor: pointer;
}
.pagb:hover:not(:disabled) {
  border-color: var(--ink-soft);
  color: var(--ink);
}
.pagb.on {
  background: var(--ink);
  border-color: var(--ink);
  color: var(--card);
  font-weight: 600;
}
.pag-expected {
  margin-top: 0.6rem;
  border-top: 1px dashed var(--line);
  padding-top: 0.5rem;
}
.pag-expected label {
  display: block;
  font-size: 0.8rem;
  font-weight: 600;
  margin-bottom: 0.3rem;
}
.pag-expected .row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}
.pag-expected input {
  flex: 1;
  min-width: 0;
}
.pag-expected .hint {
  margin: 0.4rem 0 0;
}
/* ---- onglet 5 : la lecture ---- */
.readstats {
  margin-top: 1rem;
  padding: 1rem 1.2rem;
}
.flags {
  list-style: none;
  margin: 0.5rem 0 0.7rem;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.flags li {
  font-size: 0.84rem;
  line-height: 1.45;
  border-left: 3px solid var(--warn);
  background: var(--warn-soft);
  border-radius: 0 8px 8px 0;
  padding: 0.4rem 0.7rem;
}
/* Les deux qui font perdre la page se distinguent des trois qui la dégradent. */
.flags li.bad {
  border-color: var(--danger);
  background: var(--danger-soft);
}
.read-grid {
  display: grid;
  gap: 1.2rem;
  grid-template-columns: 1.4fr 1fr;
  margin-bottom: 1rem;
}
@media (max-width: 900px) {
  .read-grid {
    grid-template-columns: 1fr;
  }
}
.read-col h4 {
  margin: 0 0 0.4rem;
  font-size: 0.86rem;
  font-weight: 700;
  color: var(--ink);
}
.read-col h4 + * + h4 {
  margin-top: 1rem;
}
.extract {
  margin: 0;
  max-height: 22rem;
  overflow: auto;
  background: var(--bg);
  border-radius: 8px;
  padding: 0.7rem 0.8rem;
  font-size: 0.82rem;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
.dates {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}
.dates li {
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
  background: var(--bg);
  border-radius: 5px;
  padding: 0.15rem 0.45rem;
}
.imgurl {
  display: block;
  font-size: 0.78rem;
  word-break: break-all;
  margin-bottom: 0.4rem;
}
.shot {
  max-width: 100%;
  max-height: 12rem;
  border-radius: 8px;
  background: var(--photo-bg);
}
.aspect {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  flex-wrap: wrap;
  padding: 0.5rem 0;
  border-top: 1px solid var(--line);
}
.aspect-title {
  font-weight: 700;
  font-size: 0.88rem;
  min-width: 9rem;
}
.pages-short {
  margin: 0.4rem 0 0.7rem;
  font-size: 0.86rem;
  line-height: 1.5;
  border-left: 3px solid var(--danger);
  background: var(--danger-soft);
  border-radius: 0 8px 8px 0;
  padding: 0.55rem 0.8rem;
}

/* ---- filtres ---- */
.filters-bar {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
  margin-bottom: 0.6rem;
}
.fbtn,
.rbtn {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0.22rem 0.6rem;
  font: inherit;
  font-size: 0.78rem;
  color: var(--ink-soft);
  cursor: pointer;
}
.fbtn.on {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent-dark);
  font-weight: 600;
}
.rbtn.on {
  background: var(--ink);
  border-color: var(--ink);
  color: var(--card);
}
.fbtn .n,
.rbtn .n {
  font-variant-numeric: tabular-nums;
  opacity: 0.7;
  margin-left: 0.2rem;
}
.sep {
  color: var(--line);
  margin: 0 0.2rem;
}
/* Le raccourci qui rend soixante-seize écartés tenables. Discret : c'est une
   commodité, pas le geste que cette page existe pour permettre. */
.bulk {
  margin-left: auto;
  background: none;
  border: 1px dashed var(--line);
  border-radius: 999px;
  padding: 0.22rem 0.7rem;
  font: inherit;
  font-size: 0.78rem;
  color: var(--ink-soft);
  cursor: pointer;
}
.bulk:hover:not(:disabled) {
  border-style: solid;
  border-color: var(--ink-soft);
  color: var(--ink);
}
.bulk:disabled {
  opacity: 0.5;
  cursor: default;
}

/* ---- les liens ---- */
.links {
  list-style: none;
  margin: 0 0 0.7rem;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.links li {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  padding: 0.4rem 0.6rem;
  border-radius: 8px;
  background: var(--bg);
  font-size: 0.84rem;
}
/* Le désaccord entre la brique et l'humain : c'est la seule chose que cette
   liste cherche à faire voir. */
.links li.diff {
  background: var(--danger-soft);
}
.links li.manual {
  background: var(--accent-soft);
}
/* Un lien qui porte encore la précoche : rien n'est tranché tant que la barre
   n'a pas disparu. Discret — c'est l'état par défaut de toute la page au
   premier chargement. */
.links li.todo {
  border-left: 3px solid var(--warn);
  padding-left: calc(0.6rem - 3px);
}
.pre {
  flex: none;
  align-self: center;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--warn);
  background: var(--warn-soft);
  border-radius: 5px;
  padding: 0.12rem 0.4rem;
}
.tag {
  flex: none;
  min-width: 7.5rem;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 700;
  border-radius: 5px;
  padding: 0.15rem 0.4rem;
  text-align: center;
  background: var(--card);
  color: var(--ink-soft);
}
.tag.kept {
  color: var(--ok);
}
.link-body {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  min-width: 0;
  flex: 1;
}
.link-body a {
  word-break: break-all;
}
.link-text {
  font-weight: 600;
}
.link-context {
  color: var(--ink-soft);
  font-size: 0.78rem;
}

/* ---- les quatre boutons de verdict ---- */
.seg {
  display: flex;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: var(--card);
}
.seg.busy {
  opacity: 0.55;
}
.segb {
  background: none;
  border: 0;
  border-right: 1px solid var(--line);
  padding: 0.25rem 0.55rem;
  font: inherit;
  font-size: 0.75rem;
  color: var(--ink-soft);
  cursor: pointer;
  white-space: nowrap;
}
.segb:last-child {
  border-right: 0;
}
.segb:hover {
  background: var(--bg);
  color: var(--ink);
}
.segb.on {
  background: var(--a, var(--ink));
  color: #fff;
  font-weight: 700;
}
.none {
  margin: 0.4rem 0 0.8rem;
}
.add-link {
  margin-bottom: 0.5rem;
}
.form.inline {
  background: var(--bg);
  border-radius: 10px;
  padding: 0.8rem;
  max-width: none;
}
.form.inline .row {
  display: grid;
  grid-template-columns: 1fr 14rem auto;
  align-items: end;
  gap: 0.7rem;
}
@media (max-width: 720px) {
  .form.inline .row {
    grid-template-columns: 1fr;
  }
}
.form.inline .hint {
  margin: 0.6rem 0 0;
  max-width: 70ch;
}
</style>
