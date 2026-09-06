<script setup lang="ts">
/**
 * Le banc d'évaluation : ce que chaque brique du scraper rend vraiment.
 *
 * Un onglet par étage, et un seul rempli — le **dépouillement**. C'est
 * volontaire, et l'ordre a une raison : cet étage est en amont, donc son
 * ratage plafonne tout ce qui suit ; il est déterministe, ce qui ne veut pas
 * dire juste ; et sa panne se déguise en panne de l'étage d'après. Un agenda
 * dont les liens de fiche ont été perdus rend son menu, la sélection n'en
 * retient rien avec un motif parfaitement sensé, et c'est un prompt qu'on ira
 * retoucher pour un bug de sélecteur.
 *
 * ## Le geste que cette page existe pour permettre
 *
 * Ajouter les liens manquants. Tout le reste est de la mise en scène autour
 * de ce bouton-là. Aucun signal gratuit ne peut dire ce que `links_of` a
 * manqué — aucun site ne déclare lesquelles de ses URL sont ses propres
 * fiches — donc il faut un humain, une fois. Ensuite l'étiquette ne périme
 * plus : la page est datée, et la mesure se rejoue sans réseau.
 *
 * ## Pourquoi un arbre, et pas une liste
 *
 * Parce que `links_of` travaille **page par page**. Dire « cet agenda a
 * trente liens » sans dire de quelle page ne permettrait de reprocher un
 * ratage à personne — et masquerait le cas le plus instructif, celui de la
 * page 2 qui ne rend rien alors que la page 1 va bien.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { api } from '../lib/api';
import { EVAL_STATUS_LABELS } from '../types';
import type { EvalAgenda, EvalAgendaPage, EvalAgendaStatus } from '../types';

/**
 * Les huit briques, dans l'ordre du pipeline.
 *
 * Le vocabulaire est celui de `sortiesbot/stages/__init__.py`, et il ne doit
 * pas diverger : la console du scraper dessine déjà son graphe avec, et deux
 * pages qui nomment différemment le même étage se contrediraient.
 */
const BRICKS = [
  { no: 1, name: 'Découverte', who: 'modèle', why: "Son entrée est le web entier, pas une page : elle ne s'évalue qu'en conditions réelles, par comparaison entre gabarits de requêtes." },
  { no: 2, name: 'Reconnaissance', who: 'mixte', why: "Une page, une étiquette humaine. Ce qu'on y mesure n'est pas l'exactitude mais une matrice de coûts : confondre un agenda avec une fiche coûte tous ses liens, l'inverse coûte un appel." },
  { no: 3, name: 'Dépouillement', who: 'python', why: '' },
  { no: 4, name: 'Sélection', who: 'modèle', why: "Le point aveugle : un lien écarté n'est relu par personne. Il faudra un budget d'exploration, ou le vivier commun de plusieurs variantes." },
  { no: 5, name: 'Lecture', who: 'python', why: "Les dates se vérifient gratuitement contre le JSON-LD que le site déclare. Le texte et l'illustration demandent un œil, cinq secondes par page." },
  { no: 6, name: 'Extraction', who: 'modèle', why: "Champ par champ, jamais fiche par fiche. Plus la vérification d'ancrage, qui ne coûte aucune étiquette : toute valeur extraite doit se retrouver dans la page." },
  { no: 7, name: 'Attribution', who: 'mixte', why: "Partiellement mesurée déjà, depuis la page d'une exécution : ce que le moteur rend, ce que le tamis refuse." },
  { no: 8, name: 'Publication', who: 'python', why: "Un contrat d'API. Des tests unitaires suffisent, et il y en a." },
] as const;

const tab = ref(3);

const agendas = ref<EvalAgenda[]>([]);
const loading = ref(true);
const error = ref('');
const notice = ref('');

/** Le formulaire d'ajout. */
const form = ref({ url: '', pages: 1, label: '' });
const adding = ref(false);

/** Agendas et pages dépliés, par identifiant. */
const openAgendas = ref(new Set<number>());
const openPages = ref(new Set<number>());

/** Le formulaire d'ajout d'un lien, ouvert sur une page à la fois. */
const addingTo = ref<number | null>(null);
const newLink = ref({ url: '', text: '' });
const savingLink = ref(false);

/** Identifiants dont une action est en cours, pour ne pas la lancer deux fois. */
const busy = ref(new Set<number>());

let poll: ReturnType<typeof setInterval> | null = null;

/** Vrai tant qu'un agenda attend le worker : c'est ce qui justifie le sondage. */
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

/**
 * Sonde le serveur tant qu'un agenda est en file.
 *
 * Le worker passe toutes les trente secondes à vide : sonder plus vite
 * n'accélérerait rien, sonder moins vite laisserait la page mentir pendant une
 * minute. On s'arrête dès que plus rien n'attend — une page ouverte tout
 * l'après-midi n'a aucune raison de continuer à parler au serveur.
 */
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
 *
 * Deux fonctions plutôt qu'une paramétrée par la ref : dans un template, une
 * ref est déjà déballée — la passer en argument y donnerait le `Set`, pas la
 * référence, et l'affectation se perdrait.
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

function mark(id: number, on: boolean) {
  const next = new Set(busy.value);
  if (on) next.add(id);
  else next.delete(id);
  busy.value = next;
}

async function act<T>(id: number, run: () => Promise<T>): Promise<T | null> {
  error.value = '';
  notice.value = '';
  mark(id, true);
  try {
    return await run();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
    return null;
  } finally {
    mark(id, false);
  }
}

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
    notice.value = "Agenda mis en file : le worker le dépouillera à son prochain passage.";
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    adding.value = false;
  }
}

async function analyze(agenda: EvalAgenda) {
  if (
    agenda.stats.manual > 0 &&
    !confirm(
      `Relancer l'analyse effacera les ${agenda.stats.manual} lien(s) ajouté(s) à la main.\n\n` +
        "Ils disaient « le dépouillement a manqué ceci sur cette page telle qu'elle était » : " +
        'la page va être retéléchargée, elle a pu changer, et les garder les rattacherait à ' +
        "un HTML qu'ils n'ont jamais décrit.",
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
    });
    replace(data.agenda);
    // Le formulaire reste ouvert : les liens manquants vont rarement seuls, et
    // refermer après chacun ferait recliquer pour rien.
    newLink.value = { url: '', text: '' };
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    savingLink.value = false;
  }
}

async function removeLink(agendaId: number, linkId: number) {
  const data = await act(agendaId, () =>
    api.delete<{ agenda: EvalAgenda }>(`/api/eval/links/${linkId}`),
  );
  if (data) replace(data.agenda);
}

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

/** Ce que la page a rendu, dit en une ligne dans l'en-tête du dépliant. */
function pageSummary(page: EvalAgendaPage) {
  if (page.error) return page.error;
  const harvested = page.links.filter((l) => l.source === 'HARVEST').length;
  const manual = page.links.length - harvested;
  const found = `${harvested} lien(s) dépouillé(s)`;
  return manual ? `${found}, ${manual} ajouté(s) à la main` : found;
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

    <!-- ─────────────────────────────────── les sept briques en attente -->
    <section v-if="tab !== 3" class="card waiting">
      <h2>{{ current.no }}. {{ current.name }}</h2>
      <p>{{ current.why }}</p>
      <p class="muted">
        Rien à mesurer ici pour l'instant : le banc s'est ouvert par le dépouillement, et les autres
        étages viendront quand celui-là aura donné ses premiers chiffres.
      </p>
    </section>

    <!-- ─────────────────────────────────────────── 3. le dépouillement -->
    <section v-else class="brick3">
      <div class="card intro">
        <h2>3. Dépouillement — ce que <code>links_of</code> tire d'une page</h2>
        <p>
          On donne un agenda réel et le nombre de pages à ouvrir. Le worker les télécharge et
          appelle le <strong>vrai</strong> <code>links_of</code> — une extraction réécrite ici
          donnerait la vérité d'une réécriture, c'est-à-dire aucune vérité.
        </p>
        <p>
          Puis vient le seul geste qui compte :
          <strong>ajouter les liens qu'il a manqués</strong>. Aucun signal gratuit ne peut le dire à
          votre place, parce qu'aucun site ne déclare lesquelles de ses URL sont ses propres fiches.
          Une fois validée, l'étiquette ne périme plus jamais — le HTML de la page est gardé, et la
          mesure se rejoue sans réseau.
        </p>
        <p class="rule">
          <strong>Ce qu'est un lien manqué :</strong> un lien de la page qui mène à la fiche d'une
          sortie, et que le dépouillement n'a pas rendu. Rien d'autre — pas un lien de navigation,
          pas une catégorie, pas une pagination : ceux-là, l'étage 3 a raison de les écarter, c'est
          même son travail. La question à laquelle vous répondez est
          <em>« l'étage 4 aurait-il dû voir ce lien ? »</em>
        </p>
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
          liens : ce qu'on mesure ici est <code>links_of</code> sur une page donnée, pas la décision
          d'en ouvrir une de plus.
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

        <dl class="stats">
          <div>
            <dt>Dépouillés</dt>
            <dd>{{ agenda.stats.harvested }}</dd>
          </div>
          <div :class="{ flag: agenda.stats.manual > 0 }">
            <dt>Manqués</dt>
            <dd>{{ agenda.stats.manual }}</dd>
          </div>
          <div>
            <dt>Total</dt>
            <dd>{{ agenda.stats.total }}</dd>
          </div>
          <div class="recall">
            <dt>Rappel</dt>
            <dd>{{ percent(agenda.stats.recall) }}</dd>
          </div>
        </dl>
        <p v-if="agenda.stats.recall === null && agenda.status === 'ANALYZED'" class="hint">
          Le rappel n'apparaît qu'une fois l'agenda validé : avant, il dirait 100 % et ne
          signifierait que « personne n'a encore regardé ».
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
            :disabled="busy.has(agenda.id)"
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

        <!-- L'arbre : une branche par page réellement téléchargée. -->
        <div v-if="openAgendas.has(agenda.id)" class="tree">
          <p v-if="!agenda.agendaPages.length" class="muted">
            Rien de dépouillé pour l'instant.
            <span v-if="agenda.status === 'QUEUED'">Le worker passe toutes les trente secondes.</span>
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
              <span v-if="page.chars" class="muted chars">{{ page.chars }} caractères</span>
              <span class="archive" :class="{ off: !page.archived }">
                {{ page.archived ? 'page archivée' : 'non archivée' }}
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
              <p v-if="!page.archived && !page.error" class="hint">
                Le HTML de cette page n'a pas pu être gardé : la mesure ci-dessous reste juste,
                mais elle ne pourra pas être rejouée hors ligne après une modification de
                <code>links_of</code>.
              </p>

              <ul v-if="page.links.length" class="links">
                <li v-for="link in page.links" :key="link.id" :class="link.source.toLowerCase()">
                  <span class="tag">{{ link.source === 'MANUAL' ? 'manqué' : 'dépouillé' }}</span>
                  <span class="link-body">
                    <a :href="link.url" target="_blank" rel="noopener noreferrer">{{ link.url }}</a>
                    <span v-if="link.text" class="link-text">{{ link.text }}</span>
                    <span v-if="link.context" class="link-context">{{ link.context }}</span>
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
              <p v-else class="muted">
                Aucun lien sur cette page.
                <template v-if="!page.error">
                  Si la page en montre pourtant, c'est exactement ce que le banc cherche à
                  attraper : ajoutez-les.
                </template>
              </p>

              <button class="btn small secondary add-link" type="button" @click="openAdd(page)">
                {{ addingTo === page.id ? 'Fermer' : 'Ajouter un lien manqué' }}
              </button>

              <form v-if="addingTo === page.id" class="form inline" @submit.prevent="addLink(page)">
                <div class="row">
                  <div class="field grow">
                    <label :for="`link-url-${page.id}`">Adresse du lien manqué</label>
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
                  N'ajoutez qu'un lien qui mène à <strong>la fiche d'une sortie</strong> : un lien
                  de navigation ou de pagination, l'étage 3 a raison de l'écarter.
                </p>
                <p class="hint">
                  Pas de contexte à saisir : le dépouillement, lui, rend le texte qui entoure le
                  lien. En inventer un ferait croire à l'étage 4 qu'il a reçu quelque chose qu'il
                  n'aurait jamais reçu.
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
/* Le seul étage réellement mesuré se distingue même quand il n'est pas ouvert :
   sept onglets identiques laisseraient chercher lequel donne quelque chose. */
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
.intro p:last-child {
  margin-bottom: 0;
}

/* ---- ajout d'un agenda ---- */
.add {
  margin-top: 1rem;
  /* `.form` est plafonné à 640 px pour les formulaires du site, où une ligne
     trop longue se lit mal. Ici on aligne quatre champs et un arbre de liens :
     c'est la largeur de la console qu'il faut. */
  max-width: none;
}
/* Une grille plutôt qu'un flex : les quatre champs n'ont pas la même largeur
   naturelle, et laisser le flex arbitrer les faisait passer à la ligne dans un
   ordre qui ne voulait rien dire. */
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
  gap: 1.6rem;
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
}
.stats dd {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
/* Les liens manqués sont le chiffre du banc : ils se voient, ou la page ne
   sert à rien. */
.stats .flag dd {
  color: var(--danger);
}
.stats .recall dd {
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
.chars {
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
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
.frozen {
  margin-left: 0.7rem;
  font-size: 0.78rem;
  white-space: nowrap;
}
.rule {
  border-left: 3px solid var(--accent);
  background: var(--accent-soft);
  border-radius: 0 8px 8px 0;
  padding: 0.7rem 0.9rem;
}
.page-body {
  padding: 0.3rem 0 0.8rem;
}
.page-url {
  margin: 0 0 0.6rem;
  font-size: 0.8rem;
  word-break: break-all;
}

.links {
  list-style: none;
  margin: 0 0 0.7rem;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.links li {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  padding: 0.4rem 0.6rem;
  border-radius: 8px;
  background: var(--bg);
  font-size: 0.85rem;
}
.links li.manual {
  background: var(--danger-soft);
}
.tag {
  flex: none;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 700;
  border-radius: 5px;
  padding: 0.12rem 0.4rem;
  background: var(--card);
  color: var(--ink-soft);
}
.links li.manual .tag {
  color: var(--danger);
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
  font-size: 0.8rem;
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
