<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { api } from '../lib/api';
import type { EventItem, RejectionMeaning, ScraperConfig } from '../types';
import {
  SETTING_LABELS,
  STATUS_LABELS,
  dayLabel,
  hasCoordinates,
  hasPrice,
  priceLabel,
  shortAgeLabel,
} from '../types';

/** Résultat de la recherche de doublons pour une sortie de la file. */
interface DuplicateCheck {
  loading: boolean;
  error: string;
  /** `null` tant que la recherche n'a pas abouti. */
  similar: EventItem[] | null;
  open: boolean;
}

const events = ref<EventItem[]>([]);
const loading = ref(true);
const error = ref('');
const notice = ref('');
/** Doublons potentiels, indexés par identifiant de sortie. */
const duplicates = ref<Record<number, DuplicateCheck>>({});

/**
 * D'où viennent les propositions affichées.
 *
 * `''` pour tout, `visitors` / `scraper` pour l'humain ou la machine, et
 * l'identifiant d'une recherche pour ne voir qu'elle. Une recherche couvre un
 * territoire — « Seine-Maritime » ne propose que de la Seine-Maritime — donc
 * c'est aussi la façon de modérer une région à la fois.
 */
const source = ref<string>('');
const configs = ref<ScraperConfig[]>([]);

/** Ce que le filtre courant ajoute à l'URL de la file. */
const query = computed(() => {
  if (source.value === 'visitors' || source.value === 'scraper') return `origin=${source.value}`;
  return source.value ? `configId=${source.value}` : '';
});

/** Le filtre en toutes lettres, pour les phrases qui doivent le rappeler. */
const sourceLabel = computed(() => {
  if (source.value === 'visitors') return 'proposées par un visiteur';
  if (source.value === 'scraper') return 'issues des recherches automatiques';
  const found = configs.value.find((c) => String(c.id) === source.value);
  return found ? `issues de la recherche « ${found.name} »` : '';
});

/** Au-delà, on considère le doublon probable plutôt que simplement possible. */
const LIKELY_DUPLICATE_SCORE = 60;

/** Plusieurs recherches en parallèle, sans saturer l'API sur une longue file. */
const CONCURRENCY = 3;

async function checkDuplicates(event: EventItem) {
  const state = duplicates.value[event.id];
  if (!state || state.loading) return;
  state.loading = true;
  state.error = '';
  try {
    const data = await api.get<{ similar: EventItem[] }>(`/api/moderation/${event.id}/similar`);
    state.similar = data.similar;
    // Un doublon probable mérite d'être vu sans avoir à déplier.
    state.open = data.similar.some((s) => (s.similarity?.score ?? 0) >= LIKELY_DUPLICATE_SCORE);
  } catch (e) {
    state.error = e instanceof Error ? e.message : 'Erreur';
  } finally {
    state.loading = false;
  }
}

/** Lance la recherche de doublons sur toute la file, quelques-unes à la fois. */
async function checkAllDuplicates(queue: EventItem[]) {
  const remaining = [...queue];
  const workers = Array.from({ length: CONCURRENCY }, async () => {
    for (let next = remaining.shift(); next; next = remaining.shift()) {
      await checkDuplicates(next);
    }
  });
  await Promise.all(workers);
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const url = query.value
      ? `/api/moderation/pending?${query.value}`
      : '/api/moderation/pending';
    const data = await api.get<{ events: EventItem[] }>(url);
    events.value = data.events;
    duplicates.value = Object.fromEntries(
      data.events.map((e) => [e.id, { loading: false, error: '', similar: null, open: false }]),
    );
    void checkAllDuplicates(data.events);
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
}

/**
 * Le refus en cours, s'il y en a un. `code` est ce que le scraper apprendra,
 * `reason` ce que l'auteur lira — les deux sont utiles et ne disent pas la
 * même chose.
 */
const rejecting = ref<{ id: number; code: string; reason: string } | null>(null);

function openRejection(id: number, reason = '') {
  rejecting.value = { id, code: '', reason };
}

/**
 * Confirme le refus. Le motif comptable est **exigé** — c'est un clic, et
 * c'est ce clic qui vaut à lui seul toute la boucle de retour ; sans lui le
 * refus n'apprend rien à personne. « Autre » est toujours disponible pour ce
 * qui n'entre dans aucune case, et le texte libre reste facultatif.
 */
async function confirmRejection() {
  const pending = rejecting.value;
  if (!pending || !pending.code) return;
  try {
    await api.post(`/api/moderation/${pending.id}`, {
      action: 'reject',
      code: pending.code,
      reason: pending.reason.trim() || undefined,
    });
    events.value = events.value.filter((e) => e.id !== pending.id);
    delete duplicates.value[pending.id];
    rejecting.value = null;
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

async function approve(id: number) {
  try {
    await api.post(`/api/moderation/${id}`, { action: 'approve' });
    events.value = events.value.filter((e) => e.id !== id);
    delete duplicates.value[id];
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

/** Motif pré-rempli du refus, qui tient compte du statut du doublon trouvé. */
function duplicateReason(original: EventItem): string {
  const ref = `« ${original.title} » (${original.venue.name})`;
  if (original.status === 'REJECTED') {
    // Le motif du refus précédent est le meilleur indice : le même défaut
    // s'applique très probablement à cette nouvelle proposition.
    return original.rejectionReason
      ? `Cette sortie fait doublon avec ${ref}, déjà refusée pour le même motif : ${original.rejectionReason}`
      : `Cette sortie fait doublon avec ${ref}, déjà refusée.`;
  }
  if (original.status === 'PENDING') {
    return `Cette sortie fait doublon avec ${ref}, déjà proposée et en attente de modération.`;
  }
  return `Cette sortie fait doublon avec ${ref}, déjà publiée.`;
}

/** Refuse la sortie en pointant le doublon trouvé : motif et puce pré-remplis. */
function rejectAsDuplicate(id: number, original: EventItem) {
  rejecting.value = { id, code: 'DOUBLON', reason: duplicateReason(original) };
}

function periodLabel(e: EventItem) {
  if (e.isPermanent || !e.dateStart || !e.dateEnd) return "toute l'année";
  const periode = `du ${e.dateStart} au ${e.dateEnd}`;
  if (!e.dates.length) return periode;
  return `${periode}, ${e.dates.length} jour(s) de représentation`;
}

/** Ce qu'il reste à compléter avant de pouvoir approuver. */
function incompleteHint(e: EventItem) {
  const missing = [
    !hasCoordinates(e.venue) ? 'l’adresse du lieu' : '',
    !hasPrice(e) ? 'le tarif' : '',
  ].filter(Boolean);
  return missing.length ? `Complétez d’abord ${missing.join(' et ')}` : '';
}

const purging = ref(false);

/**
 * Vide la file — supprime, ne refuse pas.
 *
 * Refuser garde la sortie et son motif, visible par l'auteur. Après un import
 * raté, ce n'est pas ce qu'on veut : vingt pages mal lues qu'il serait absurde
 * de motiver une par une, et qui n'ont rien à laisser derrière elles.
 *
 * La mémoire du scraper, elle, n'est pas touchée : les pages restent connues,
 * donc ne seront pas reproposées. C'est la purge de la mémoire — page
 * « Recherche auto → Mémoire » — qui les rend à nouveau lisibles.
 */
async function purgePending() {
  const combien = events.value.length;
  if (!combien) return;
  const quoi = sourceLabel.value
    ? `les ${combien} sortie(s) en attente ${sourceLabel.value}`
    : `les ${combien} sortie(s) en attente`;
  const question =
    `Supprimer définitivement ${quoi} ?\n\n` +
    'Elles ne seront pas refusées mais effacées : ni motif pour leur auteur, ' +
    'ni trace au catalogue.\n\n' +
    'Les pages dont elles venaient restent en mémoire du scraper, qui ne les ' +
    'reproposera donc pas. Pour qu’il les relise, purgez sa mémoire.\n\n' +
    'Cette action est irréversible.';
  if (!confirm(question)) return;

  error.value = '';
  notice.value = '';
  purging.value = true;
  try {
    // Le nombre part avec la requête : si la file a bougé depuis l'affichage,
    // le serveur refuse plutôt que de supprimer une sortie que personne n'a lue.
    // Le filtre part avec la requête : le serveur ne supprime que ce qui
    // était affiché. Le nombre, lui, reste le garde-fou — si la file a bougé
    // depuis l'affichage, il refuse.
    const suffixe = query.value ? `&${query.value}` : '';
    const res = await api.delete<{ deleted: number }>(
      `/api/moderation/pending?expected=${combien}${suffixe}`,
    );
    notice.value = `${res.deleted} sortie(s) supprimée(s).`;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    purging.value = false;
  }
}

function scoreLevel(score: number) {
  if (score >= LIKELY_DUPLICATE_SCORE) return 'high';
  return score >= 45 ? 'medium' : 'low';
}

/**
 * Les recherches automatiques, pour le filtre. Leur absence n'est pas une
 * erreur à afficher : la file reste modérable sans elles.
 */
async function loadConfigs() {
  try {
    const data = await api.get<{ configs: ScraperConfig[] }>('/api/scraper/configs');
    configs.value = data.configs;
  } catch {
    configs.value = [];
  }
}

/**
 * Les motifs de refus proposés, et l'étage que chacun met en cause.
 *
 * Chargés depuis l'API plutôt que recopiés ici : c'est la même table qui
 * groupe les refus par étage sur la page de qualité, et deux copies auraient
 * divergé au premier motif ajouté.
 */
const codes = ref<RejectionMeaning[]>([]);

/** L'étage que la puce choisie met en cause, en une ligne. */
const blamedLabel = computed(() => {
  const chosen = codes.value.find((c) => c.code === rejecting.value?.code);
  if (!chosen || chosen.blames.length === 0) return '';
  return chosen.blames.map((b) => `${b.number}. ${b.label}`).join(', ');
});

onMounted(() => {
  void loadConfigs();
  void load();
  // Un échec ne doit pas empêcher de modérer : sans la liste, les puces sont
  // absentes et le refus reste possible par le texte libre.
  api
    .get<{ codes: RejectionMeaning[] }>('/api/moderation/codes')
    .then((data) => (codes.value = data.codes))
    .catch(() => undefined);
});
</script>

<template>
  <div class="container page">
    <h1>Modération</h1>
    <div class="queue-head">
      <p class="muted" style="margin: 0">
        {{ events.length }} sortie(s) en attente d'approbation<template v-if="sourceLabel">
          {{ sourceLabel }}</template>.
      </p>
      <label class="filtre">
        <span class="muted small">Origine</span>
        <select v-model="source" @change="load">
          <option value="">Toutes les propositions</option>
          <option value="visitors">Proposées par un visiteur</option>
          <option value="scraper">Toutes les recherches automatiques</option>
          <option v-for="c in configs" :key="c.id" :value="String(c.id)">
            Recherche « {{ c.name }} »
          </option>
        </select>
      </label>
      <button
        v-if="events.length"
        class="btn danger small"
        type="button"
        :disabled="purging"
        title="Efface les propositions sans les refuser : ni motif, ni trace."
        @click="purgePending"
      >
        🗑 Supprimer {{ sourceLabel ? 'ces' : 'les' }} {{ events.length }} sortie(s)
      </button>
    </div>
    <p v-if="events.length" class="muted small">
      Supprimer n'est pas refuser : rien n'est gardé, ni motif pour l'auteur ni
      trace au catalogue. Les pages importées restent connues du scraper, qui ne
      les reproposera pas — pour qu'il les relise, purgez sa
      <RouterLink to="/admin/scraper/memoire">mémoire</RouterLink>.
    </p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <div v-if="!loading && events.length === 0" class="empty">
      <p v-if="sourceLabel">
        Rien à modérer parmi les propositions {{ sourceLabel }}.
        <button class="linklike" type="button" @click="source = ''; load()">
          Voir toute la file
        </button>
      </p>
      <p v-else>🎉 Rien à modérer, tout est à jour !</p>
    </div>

    <div v-for="e in events" :key="e.id" class="card" style="padding: 1.2rem; margin-bottom: 1rem">
      <div class="badges" style="margin-bottom: 0.4rem">
        <span v-if="e.origin" class="badge origin" :title="`Proposée par la recherche automatique « ${e.origin.configName} »`">
          🤖 {{ e.origin.configName }}
        </span>
        <span class="badge price">{{ priceLabel(e) }}</span>
        <span v-if="shortAgeLabel(e)" class="badge">{{ shortAgeLabel(e) }}</span>
        <span v-if="e.setting" class="badge">{{ SETTING_LABELS[e.setting] }}</span>
      </div>
      <!-- Vers la modification, pas vers la fiche : en modération il y a
           presque toujours un détail à corriger, et l'enregistrement ramène
           sur la fiche, d'où l'on approuve. -->
      <h3>
        <RouterLink :to="`/sorties/${e.id}/modifier`">{{ e.title }}</RouterLink>
      </h3>
      <p class="muted">
        {{ e.venue.name }} · {{ e.venue.city }} ·
        {{ periodLabel(e) }}
        · proposé par {{ e.author.displayName }}
      </p>

      <!-- Sortie importée dont l'adresse n'a pas pu être géocodée. -->
      <p v-if="!hasCoordinates(e.venue)" class="incomplete">
        📍 Lieu non géolocalisé — <strong>{{ e.venue.address || 'adresse à préciser' }}</strong
        >. Cette sortie n'apparaîtra dans aucune recherche par distance : complétez l'adresse
        avant de l'approuver.
        <RouterLink :to="`/sorties/${e.id}/modifier`">Compléter l'adresse</RouterLink>
      </p>

      <!-- Sortie importée dont le tarif n'a pas pu être déterminé. -->
      <p v-if="!hasPrice(e)" class="incomplete">
        🏷 Tarif indéterminé — la page source ne l'indiquait pas clairement.
        Renseignez-le (ou cochez « gratuit ») avant d'approuver.
        <RouterLink :to="`/sorties/${e.id}/modifier`">Compléter le tarif</RouterLink>
      </p>
      <!-- Jours de représentation déduits par l'import : à vérifier, c'est ce
           qui décide des jours où la sortie ressortira dans les recherches. -->
      <p v-if="e.dates.length" class="days">
        <span v-for="day in e.dates" :key="day" class="badge">{{ dayLabel(day) }}</span>
      </p>
      <p style="white-space: pre-line">{{ e.description }}</p>
      <img
        v-if="e.photoUrl"
        :src="e.photoUrl"
        :alt="e.title"
        style="max-width: 280px; border-radius: 10px"
      />

      <!-- Doublons potentiels -->
      <div class="dup" :class="{ 'dup-alert': (duplicates[e.id]?.similar?.length ?? 0) > 0 }">
        <p v-if="duplicates[e.id]?.loading" class="muted dup-status">
          Recherche de doublons…
        </p>
        <p v-else-if="duplicates[e.id]?.error" class="muted dup-status">
          Recherche de doublons indisponible ({{ duplicates[e.id].error }}).
          <button class="linklike" @click="checkDuplicates(e)">Réessayer</button>
        </p>
        <p v-else-if="duplicates[e.id]?.similar?.length === 0" class="muted dup-status">
          ✓ Aucune sortie similaire trouvée.
        </p>
        <template v-else-if="duplicates[e.id]?.similar">
          <button class="linklike dup-toggle" @click="duplicates[e.id].open = !duplicates[e.id].open">
            ⚠ {{ duplicates[e.id].similar!.length }} sortie(s) similaire(s) —
            {{ duplicates[e.id].open ? 'masquer' : 'vérifier le doublon' }}
          </button>

          <ul v-if="duplicates[e.id].open" class="dup-list">
            <li v-for="s in duplicates[e.id].similar!" :key="s.id" class="dup-item">
              <div class="dup-head">
                <span class="dup-score" :class="`dup-score-${scoreLevel(s.similarity?.score ?? 0)}`">
                  {{ s.similarity?.score }}/100
                </span>
                <a :href="`/sorties/${s.id}`" target="_blank" rel="noopener">{{ s.title }}</a>
                <span class="badge" :class="`status-${s.status}`">{{ STATUS_LABELS[s.status] }}</span>
              </div>
              <p class="muted dup-meta">
                {{ s.venue.name }} · {{ s.venue.city }} · {{ periodLabel(s) }}
                · proposé par {{ s.author.displayName }}
              </p>
              <!-- Doublon déjà tranché : son motif de refus vaut probablement
                   aussi pour celle-ci. -->
              <p v-if="s.status === 'REJECTED' && s.rejectionReason" class="dup-rejection">
                Motif du refus précédent : {{ s.rejectionReason }}
              </p>
              <div class="badges">
                <span v-for="reason in s.similarity?.reasons ?? []" :key="reason" class="badge">
                  {{ reason }}
                </span>
              </div>
              <button class="linklike dup-action" @click="rejectAsDuplicate(e.id, s)">
                ✕ Refuser comme doublon de cette sortie
              </button>
            </li>
          </ul>
        </template>
      </div>

      <div class="row" style="margin-top: 0.8rem">
        <button
          class="btn"
          :disabled="!hasCoordinates(e.venue) || !hasPrice(e)"
          :title="incompleteHint(e)"
          @click="approve(e.id)"
        >
          ✓ Approuver
        </button>
        <button class="btn danger" @click="openRejection(e.id)">✕ Refuser</button>
      </div>

      <!--
        Le motif du refus. Une puce plutôt qu'une phrase tapée : c'est plus
        rapide pour le modérateur — un clic contre une ligne de texte — et
        c'est la seule forme qui s'additionne, donc la seule qui apprenne
        quelque chose au scraper. Le texte libre reste à côté, facultatif,
        parce que c'est lui que l'auteur de la sortie lira.
      -->
      <div v-if="rejecting?.id === e.id" class="rejection">
        <p class="rejection-title">Pourquoi cette sortie est-elle refusée ?</p>
        <div class="chips">
          <button
            v-for="c in codes"
            :key="c.code"
            type="button"
            class="chip"
            :class="{ on: rejecting.code === c.code }"
            :title="c.hint"
            @click="rejecting.code = c.code"
          >
            {{ c.label }}
          </button>
        </div>
        <p v-if="blamedLabel" class="muted rejection-blame">
          Étage mis en cause : {{ blamedLabel }}
        </p>
        <label class="rejection-label" :for="`reason-${e.id}`">
          Précision pour l’auteur (facultatif)
        </label>
        <textarea
          :id="`reason-${e.id}`"
          v-model="rejecting.reason"
          class="rejection-text"
          rows="2"
        ></textarea>
        <div class="row">
          <button class="btn danger" :disabled="!rejecting.code" @click="confirmRejection()">
            Confirmer le refus
          </button>
          <button class="linklike" type="button" @click="rejecting = null">Annuler</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rejection {
  margin-top: 0.8rem;
  padding: 0.8rem;
  border: 1px solid var(--danger, #b3261e);
  border-radius: 8px;
}
.rejection-title {
  margin: 0 0 0.5rem;
  font-weight: 600;
}
.rejection-blame {
  margin: 0.4rem 0 0;
  font-size: 0.85rem;
}
.rejection-label {
  display: block;
  margin: 0.7rem 0 0.2rem;
  font-size: 0.85rem;
}
.rejection-text {
  width: 100%;
  box-sizing: border-box;
  margin-bottom: 0.6rem;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.chip {
  padding: 0.3rem 0.7rem;
  border: 1px solid currentColor;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 0.85rem;
  cursor: pointer;
}
.chip.on {
  background: var(--danger, #b3261e);
  border-color: var(--danger, #b3261e);
  color: #fff;
}
.queue-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
  margin-bottom: 0.8rem;
}

.notice {
  color: var(--ok);
  font-weight: 600;
}

/* Le filtre s'intercale entre le décompte et le bouton de vidage : c'est
   l'ordre dans lequel on les lit — combien, parmi quoi, et quoi en faire. */
.filtre {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-right: auto;
}

.filtre select {
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--card);
  font: inherit;
}

.badge.origin {
  background: var(--accent-soft);
  color: var(--accent-dark);
}

.small {
  font-size: 0.85rem;
}

.days {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin: 0.4rem 0;
}

.incomplete {
  margin: 0.6rem 0 0;
  padding: 0.6rem 0.8rem;
  border-radius: 12px;
  background: var(--warn-soft);
  color: var(--warn);
  font-size: 0.9rem;
}

.incomplete a {
  color: var(--warn);
  font-weight: 600;
  white-space: nowrap;
}

.dup {
  margin-top: 0.9rem;
  padding: 0.6rem 0.8rem;
  border-radius: 12px;
  background: var(--bg);
  border: 1.3px solid var(--line);
}

.dup-alert {
  background: var(--warn-soft);
  border-color: transparent;
}

.dup-status {
  margin: 0;
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

.dup-toggle {
  font-weight: 600;
  color: var(--warn);
}

.dup-list {
  list-style: none;
  margin: 0.7rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}

.dup-item {
  background: var(--card);
  border: 1.3px solid var(--line);
  border-radius: 12px;
  padding: 0.6rem 0.8rem;
}

.dup-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  font-weight: 600;
}

.dup-score {
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
}

.dup-score-high {
  background: var(--danger-soft);
  color: var(--danger);
}

.dup-score-medium {
  background: var(--warn-soft);
  color: var(--warn);
}

.dup-score-low {
  background: var(--photo-bg);
  color: var(--ink-soft);
}

.dup-meta {
  margin: 0.25rem 0 0.4rem;
}

.dup-rejection {
  margin: 0 0 0.4rem;
  color: var(--danger);
  font-size: 0.88rem;
}

.dup-action {
  margin-top: 0.5rem;
  color: var(--danger);
  font-size: 0.85rem;
}
</style>
