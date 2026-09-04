<script setup lang="ts">
/**
 * Les agrégateurs : les grands agendas qui republient.
 *
 * kidiklik, citizenkid, sortiraparis indexent tout et sortent en tête des
 * recherches. Ce sont d'excellents points d'entrée — et jamais la source :
 * un atelier du musée Rodin est une information du musée Rodin. Le scraper
 * les lit, puis remonte à la page de l'organisateur, et c'est celle-là qu'il
 * propose au parent.
 *
 * La liste était un champ libre par recherche, recopié d'une configuration à
 * l'autre. C'était une erreur de niveau : un site republie ou ne republie
 * pas, indépendamment de la recherche qui l'a trouvé. Elle vit donc ici, une
 * fois pour toutes, et chaque recherche ne garde qu'une décision — les lire
 * (le cas normal) ou les refuser.
 */
import { computed, onMounted, reactive, ref } from 'vue';
import { api } from '../lib/api';
import type { Aggregator } from '../types';

const aggregators = ref<Aggregator[]>([]);
/** Combien de recherches existent, et combien refusent de les lire. */
const configs = ref(0);
const blocking = ref(0);
const loading = ref(true);
const error = ref('');
const busy = ref(false);
/** Agrégateur en cours de modification ; `null` pour l'ajout. */
const editingId = ref<number | null>(null);

function blank() {
  return { domain: '', label: '', note: '', enabled: true };
}
const draft = reactive(blank());

const actifs = computed(() => aggregators.value.filter((a) => a.enabled).length);

async function load() {
  loading.value = true;
  try {
    const data = await api.get<{ aggregators: Aggregator[]; configs: number; blocking: number }>(
      '/api/scraper/aggregators',
    );
    aggregators.value = data.aggregators;
    configs.value = data.configs;
    blocking.value = data.blocking;
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
}

function reset() {
  editingId.value = null;
  Object.assign(draft, blank());
}

function startEdit(a: Aggregator) {
  editingId.value = a.id;
  Object.assign(draft, { domain: a.domain, label: a.label, note: a.note, enabled: a.enabled });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function save() {
  error.value = '';
  busy.value = true;
  try {
    if (editingId.value === null) await api.post('/api/scraper/aggregators', { ...draft });
    else await api.patch(`/api/scraper/aggregators/${editingId.value}`, { ...draft });
    reset();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    busy.value = false;
  }
}

/**
 * Le seul geste qu'on fait souvent : décocher, ou recocher.
 *
 * Il n'ouvre pas le formulaire — on veut voir la liste changer sous les yeux,
 * puisque c'est elle qu'on est venu régler.
 */
async function toggle(a: Aggregator) {
  error.value = '';
  try {
    await api.patch(`/api/scraper/aggregators/${a.id}`, { enabled: !a.enabled });
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

async function remove(a: Aggregator) {
  const question =
    `Retirer « ${a.domain} » de la liste ?\n\n` +
    `Aucune sortie n'est perdue : un agrégateur ne possède rien. Mais les ` +
    `prochaines exécutions cesseront de remonter à l'organisateur depuis ses ` +
    `fiches, et proposeront son adresse. Pour garder la trace, décochez-le ` +
    `plutôt que de le supprimer.`;
  if (!confirm(question)) return;
  error.value = '';
  try {
    await api.delete(`/api/scraper/aggregators/${a.id}`);
    if (editingId.value === a.id) reset();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

onMounted(load);
</script>

<template>
  <div class="container page">
    <h1>Recherche automatique — agrégateurs</h1>
    <nav class="row" style="gap: 1rem; margin-bottom: 1rem">
      <RouterLink to="/admin/scraper">Recherches et exécutions</RouterLink>
      <RouterLink to="/admin/scraper/agregateurs">Agrégateurs</RouterLink>
      <RouterLink to="/admin/scraper/stats">Statistiques</RouterLink>
      <RouterLink to="/admin/scraper/memoire">Mémoire</RouterLink>
    </nav>

    <p class="muted">
      Les grands agendas qui <b>republient</b> — kidiklik, citizenkid, sortiraparis. Ils
      indexent tout et sortent en tête des recherches : on les lit volontiers. Mais un
      atelier du musée Rodin est une information du musée Rodin, alors le scraper remonte
      de leur fiche à la page de l'organisateur, et c'est celle-là qu'il propose au parent.
    </p>
    <p class="muted">
      Cette liste est <b>commune à toutes les recherches</b> : elle ne se règle plus
      recherche par recherche. Une recherche décide seulement de lire ces sites ou de les
      refuser, par la case « ne pas lire les agrégateurs ».
    </p>

    <p v-if="error" class="error">{{ error }}</p>

    <!-- Ajout et modification -->
    <form class="filters card" @submit.prevent="save">
      <h2 style="margin: 0">
        {{ editingId === null ? 'Ajouter un agrégateur' : 'Modifier l’agrégateur' }}
      </h2>
      <div class="row">
        <div class="field" style="flex: 2">
          <label for="g-domain">Domaine</label>
          <input
            id="g-domain"
            v-model="draft.domain"
            type="text"
            required
            maxlength="190"
            placeholder="kidiklik.fr"
          />
          <small class="muted">
            Le domaine seul. Une adresse complète collée depuis le navigateur est ramenée à
            son domaine, et les sous-domaines en relèvent aussi : « paris.kidiklik.fr » est
            couvert par « kidiklik.fr ».
          </small>
        </div>
        <div class="field" style="flex: 2">
          <label for="g-label">Nom</label>
          <input id="g-label" v-model="draft.label" type="text" maxlength="80" placeholder="Kidiklik" />
          <small class="muted">Pour la lecture de cette page. Vide : le domaine suffit.</small>
        </div>
      </div>

      <div class="field">
        <label for="g-note">Note</label>
        <textarea
          id="g-note"
          v-model="draft.note"
          rows="2"
          maxlength="1000"
          placeholder="Ce qu'on a constaté sur ce site."
        ></textarea>
        <small class="muted">
          Utile au prochain qui se demandera pourquoi ce site est là — ou pourquoi il a été
          décoché.
        </small>
      </div>

      <div class="field">
        <label class="checkbox">
          <input v-model="draft.enabled" type="checkbox" />
          Pris en compte par les recherches
        </label>
        <small class="muted">
          Décoché, le site cesse d'être tenu pour un agrégateur : ses pages peuvent alors
          servir de source à une sortie, et une recherche qui bloque les agrégateurs ne le
          bloquera pas.
        </small>
      </div>

      <div class="row" style="gap: 0.5rem">
        <button class="btn" type="submit" :disabled="busy">
          {{ editingId === null ? 'Ajouter' : 'Enregistrer' }}
        </button>
        <button v-if="editingId !== null" class="btn ghost" type="button" @click="reset">
          Annuler
        </button>
      </div>
    </form>

    <p class="muted small">
      {{ actifs }} agrégateur(s) pris en compte sur {{ aggregators.length }}.
      <template v-if="configs">
        <template v-if="blocking">
          {{ blocking }} recherche(s) sur {{ configs }} refusent de les lire.
        </template>
        <template v-else>
          Les {{ configs }} recherche(s) les lisent et remontent ensuite à l'organisateur.
        </template>
      </template>
    </p>

    <p v-if="loading" class="muted">Chargement…</p>
    <p v-else-if="!aggregators.length" class="muted">
      Aucun agrégateur. Le scraper proposera alors l'adresse de la page où il a trouvé la
      sortie, agenda compris — remonter à l'organisateur reste tenté, mais plus rien ne le
      lui impose.
    </p>

    <div v-else class="table-wrap card">
      <table>
        <thead>
          <tr>
            <th>Domaine</th>
            <th>Nom</th>
            <th>Pris en compte</th>
            <th>Note</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in aggregators" :key="a.id" :class="{ off: !a.enabled }">
            <td>
              <a :href="`https://${a.domain}`" target="_blank" rel="noopener noreferrer">
                {{ a.domain }}
              </a>
            </td>
            <td :class="{ muted: !a.label }">{{ a.label || '—' }}</td>
            <td>
              <label class="checkbox">
                <input type="checkbox" :checked="a.enabled" @change="toggle(a)" />
                {{ a.enabled ? 'oui' : 'non' }}
              </label>
            </td>
            <td class="muted small">{{ a.note || '—' }}</td>
            <td>
              <div class="row" style="gap: 0.5rem">
                <button class="btn ghost small" type="button" @click="startEdit(a)">
                  Modifier
                </button>
                <a href="#" style="color: var(--danger)" @click.prevent="remove(a)">Retirer</a>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
/* Une ligne décochée reste lisible, mais ne se lit plus comme une règle en
   vigueur : c'est une trace de décision, pas un site pris en compte. */
tr.off td:not(:last-child) {
  opacity: 0.55;
}
</style>
