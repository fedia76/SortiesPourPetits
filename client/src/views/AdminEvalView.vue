<script setup lang="ts">
/**
 * Le banc d'évaluation : ce que chaque brique du scraper rend vraiment.
 *
 * Un onglet par étage, et un seul rempli — le **dépouillement**. Il est en
 * amont, donc son ratage plafonne tout ce qui suit ; il est déterministe, ce
 * qui ne veut pas dire juste ; et sa panne se déguise en panne de l'étage
 * d'après. Un agenda dont les liens de fiche ont été perdus rend son menu, la
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
import { EVAL_STATUS_LABELS, EVAL_VERDICT_HINTS, EVAL_VERDICT_LABELS } from '../types';
import type {
  EvalAgenda,
  EvalAgendaPage,
  EvalAgendaStatus,
  EvalLink,
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
  { no: 5, name: 'Lecture', why: "Les dates se vérifient gratuitement contre le JSON-LD que le site déclare. Le texte et l'illustration demandent un œil, cinq secondes par page." },
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

function tick() {
  if (waiting.value) load(true);
}

onMounted(async () => {
  await load();
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
  const marked = page.links.filter((l) => l.verdict === 'PAGINATION');
  if (page.nextUrl) {
    return marked.some((l) => l.url === page.nextUrl)
      ? { tone: 'ok', text: `L'étage 3 suit ${page.nextUrl}` }
      : {
          tone: 'bad',
          text: `L'étage 3 suivrait ${page.nextUrl} — qu'aucun lien de la page n'est étiqueté « pagination ». Vérifiez que c'est bien la page suivante.`,
        };
  }
  if (marked.length) {
    return {
      tone: 'bad',
      text: `${marked.length} lien(s) de pagination sur la page, et aucun « rel=next » : l'étage 3 ne saura jamais suivre la suite de cet agenda.`,
    };
  }
  // Sans relecture, on ne sait rien : dire « cette page est la dernière »
  // alors que personne n'a regardé ses liens est exactement l'affirmation
  // gratuite que ce banc existe pour éviter.
  if (page.links.some((l) => !l.reviewed)) {
    return {
      tone: 'todo',
      text: "Aucun « rel=next » sur cette page. S'il y a pourtant une suite, étiquetez ses liens « pagination » : c'est ce qui dira que l'étage 3 l'a ratée.",
    };
  }
  return { tone: 'ok', text: 'Ni « rel=next » ni lien de pagination : cette page est bien la dernière.' };
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
      Un étage est ouvert pour l'instant — le dépouillement.
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

    <section v-if="tab !== 3" class="card waiting">
      <h2>{{ current.no }}. {{ current.name }}</h2>
      <p>{{ current.why }}</p>
      <p class="muted">
        Rien à mesurer ici pour l'instant : le banc s'est ouvert par le dépouillement, et les autres
        étages viendront quand celui-là aura donné ses premiers chiffres.
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
            <dt title="Le site offrait une suite, la brique ne l'a pas vue">
              Pagination ratée
            </dt>
            <dd>{{ agenda.stats.paginationManquee }}</dd>
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
          <template v-if="agenda.stats.reviewed < agenda.stats.links">
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
            :disabled="busy.has(agenda.id) || agenda.stats.reviewed < agenda.stats.links"
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

              <p v-if="pagination(page)" class="pagination" :class="pagination(page)!.tone">
                <strong>Pagination :</strong> {{ pagination(page)!.text }}
              </p>

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

.pagination {
  margin: 0 0 0.7rem;
  font-size: 0.83rem;
  border-left: 3px solid var(--ok);
  background: var(--ok-soft);
  border-radius: 0 8px 8px 0;
  padding: 0.5rem 0.7rem;
  word-break: break-word;
}
.pagination.bad {
  border-color: var(--danger);
  background: var(--danger-soft);
}
/* Ni bon ni mauvais : on ne sait pas encore, et le dire est la seule réponse
   honnête tant que personne n'a relu les liens de la page. */
.pagination.todo {
  border-color: var(--warn);
  background: var(--warn-soft);
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
