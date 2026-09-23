<script setup lang="ts">
/**
 * Deux runs de fiches, côte à côte, aspect par aspect.
 *
 * Le tableau des mesures dit **qu'**une brique a reculé ; il ne dit jamais
 * **sur quoi**. « Intérieur ou extérieur : 75 % d'un côté, 6 % de l'autre »
 * est un chiffre qu'on ne peut ni croire ni corriger — il faut lire ce que le
 * second met là où le premier avait bon, et c'est une chose qu'aucun total ne
 * montrera.
 *
 * Cette vue ne mesure rien : elle rapproche deux relevés déjà jugés, et range
 * chaque aspect dans la case que les deux verdicts forment ensemble. Le
 * premier run est la référence, et l'ordre compte : « perdu » veut dire qu'il
 * avait bon et que l'autre non.
 *
 * Le détail ne garde que ce qui diverge. Cent quarante sorties font près de
 * deux mille aspects ; y laisser ceux sur lesquels les deux runs s'accordent
 * noierait les quelques dizaines de lignes qu'on est venu lire. Leur nombre
 * reste au tableau du haut, où il a un sens.
 */
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../lib/api';
import { messageDe } from '../lib/erreurs';
import type { EvalComparaison, EvalRun, EvalBascule } from '../types';
import { EVAL_BASCULE_LABELS } from '../types';

const route = useRoute();
const router = useRouter();

const runs = ref<EvalRun[]>([]);
const idA = ref<number | null>(null);
const idB = ref<number | null>(null);
const vue = ref<EvalComparaison | null>(null);
const loading = ref(false);
const error = ref('');

/**
 * Ce qu'on regarde. « PERDU » par défaut, parce que c'est la question qui
 * amène ici : qu'est-ce que le second casse de ce que le premier réussissait.
 */
const filtre = ref<EvalBascule | 'TOUT'>('PERDU');
const aspect = ref('');
const cherche = ref('');

const FILTRES: (EvalBascule | 'TOUT')[] = ['PERDU', 'GAGNE', 'RATE', 'TOUT'];

/** Seuls les runs d'extraction terminés : eux seuls portent une fiche entière. */
const comparables = computed(() =>
  runs.value.filter((run) => run.stage === 'EXTRACT' && run.status === 'DONE'),
);

async function chargerLesRuns() {
  try {
    runs.value = (await api.get<{ runs: EvalRun[] }>('/api/eval/runs?stage=EXTRACT')).runs;
  } catch (e) {
    error.value = messageDe(e);
  }
}

async function comparer() {
  if (!idA.value || !idB.value || idA.value === idB.value) {
    vue.value = null;
    return;
  }
  loading.value = true;
  error.value = '';
  try {
    vue.value = await api.get<EvalComparaison>(
      `/api/eval/runs/${idA.value}/comparer/${idB.value}`,
    );
    // L'adresse porte le couple comparé : une lecture se partage, et se
    // retrouve après un rechargement.
    router.replace({ query: { a: String(idA.value), b: String(idB.value) } });
  } catch (e) {
    vue.value = null;
    error.value = messageDe(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  await chargerLesRuns();
  const a = Number(route.query.a);
  const b = Number(route.query.b);
  if (a && b) {
    idA.value = a;
    idB.value = b;
    await comparer();
    return;
  }
  // À défaut, les deux plus récents : c'est la comparaison qu'on vient de
  // vouloir faire neuf fois sur dix.
  const [dernier, avant] = comparables.value;
  if (avant) {
    idA.value = avant.id;
    idB.value = dernier.id;
  }
});

watch([idA, idB], comparer);

/** Intervertir : « ce que A casse » et « ce que B casse » sont deux questions. */
function intervertir() {
  const a = idA.value;
  idA.value = idB.value;
  idB.value = a;
}

const lignes = computed(() => {
  if (!vue.value) return [];
  const mot = cherche.value.trim().toLowerCase();
  return vue.value.lignes.filter((ligne) => {
    if (filtre.value !== 'TOUT' && ligne.bascule !== filtre.value) return false;
    if (aspect.value && ligne.key !== aspect.value) return false;
    if (!mot) return true;
    return (
      ligne.label.toLowerCase().includes(mot) ||
      ligne.url.toLowerCase().includes(mot) ||
      ligne.attendu.toLowerCase().includes(mot) ||
      ligne.renduA.toLowerCase().includes(mot) ||
      ligne.renduB.toLowerCase().includes(mot)
    );
  });
});

/** Le nom d'un run, tel qu'on le reconnaît dans une liste. */
function nomDe(run: EvalRun): string {
  const bouts = [`#${run.id}`, run.label, run.model].filter(Boolean);
  return bouts.join(' · ');
}

function courtUrl(url: string): string {
  return url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 60);
}
</script>

<template>
  <div class="page">
    <h1>Comparer deux mesures</h1>
    <p class="muted">
      Un taux dit qu’une brique a reculé ; il ne dit pas sur quoi. Ici, les deux
      fiches d’une même page se lisent l’une à côté de l’autre, avec ce que le
      corpus attendait. <strong>Le premier run est la référence</strong> :
      « perdu » veut dire qu’il avait bon et que le second non.
    </p>

    <div class="card choix">
      <div class="row">
        <div class="field grow">
          <label for="cmp-a">Référence</label>
          <select id="cmp-a" v-model.number="idA">
            <option v-for="run in comparables" :key="run.id" :value="run.id">
              {{ nomDe(run) }}
            </option>
          </select>
        </div>
        <button type="button" class="ghost" title="Intervertir" @click="intervertir">⇄</button>
        <div class="field grow">
          <label for="cmp-b">Comparé</label>
          <select id="cmp-b" v-model.number="idB">
            <option v-for="run in comparables" :key="run.id" :value="run.id">
              {{ nomDe(run) }}
            </option>
          </select>
        </div>
      </div>
      <p v-if="comparables.length < 2" class="muted small">
        Il faut deux runs d’extraction terminés pour comparer quoi que ce soit.
      </p>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="muted">Lecture des deux relevés…</p>

    <template v-if="vue">
      <p class="muted small">
        {{ vue.communes }} page(s) lue(s) par les deux runs.
        <template v-if="vue.a.traites !== vue.communes || vue.b.traites !== vue.communes">
          <strong>
            L’un des deux en a traité d’autres ({{ vue.a.traites }} et {{ vue.b.traites }}) :
            elles ne sont pas comparées, et les totaux ci-dessous n’en portent rien.
          </strong>
        </template>
        <template v-if="vue.a.erreurs || vue.b.erreurs">
          {{ vue.a.erreurs }} et {{ vue.b.erreurs }} entrée(s) en erreur — une fiche
          absente compte MANQUÉ sur tous ses aspects, ce qui suffit à expliquer un
          effondrement général.
        </template>
      </p>

      <!-- Ce que les deux runs ont dépensé. Une sortie qui enfle pendant que le
           taux baisse est une explication à elle seule — encore faut-il savoir
           laquelle : un modèle qui réfléchit et un modèle bavard rendent le
           même nombre de jetons, et la correction n'est pas la même. D'où la
           part du raisonnement, à côté du total.

           Les jetons d'entrée, eux, ne se comparent pas d'un modèle à l'autre :
           chacun découpe le texte avec son propre vocabulaire, et le même
           corpus peut rendre 50 % de jetons de plus chez l'un sans qu'une
           ligne ait changé. -->
      <div class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>Modèle</th>
              <th class="num">Jetons d’entrée</th>
              <th class="num">de sortie</th>
              <th class="num">Coût</th>
              <th class="num">En erreur</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(run, i) in [vue.a, vue.b]" :key="run.id">
              <td>{{ i ? 'Comparé' : 'Référence' }} · #{{ run.id }} {{ run.label }}</td>
              <td class="valeur">{{ run.model || '—' }}</td>
              <td class="num">{{ run.inputTokens.toLocaleString('fr-FR') }}</td>
              <td class="num">
                {{ run.outputTokens.toLocaleString('fr-FR') }}
                <!-- Une part, jamais une colonne à additionner : le service
                     les facture dans la sortie. -->
                <span v-if="run.reasoningTokens" class="part">
                  dont {{ run.reasoningTokens.toLocaleString('fr-FR') }} à réfléchir
                </span>
              </td>
              <td class="num">{{ run.costUsd.toFixed(4) }} $</td>
              <td class="num" :class="{ alerte: run.erreurs > 0 }">{{ run.erreurs || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── Où ça bascule, aspect par aspect ─────────────────────────── -->
      <h2>Où ça bascule</h2>
      <p class="muted small">
        Une ligne par aspect du banc. <strong>Perdus</strong> est ce que le second
        casse ; <strong>gagnés</strong> ce qu’il rattrape. Un aspect dont les deux
        colonnes sont hautes n’a pas « un peu baissé » : il a changé de
        comportement.
      </p>
      <div class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Aspect</th>
              <th class="num">Tenus</th>
              <th class="num">Perdus</th>
              <th class="num">Gagnés</th>
              <th class="num">Ratés des deux</th>
              <th class="num">Non jugés</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in vue.aspects" :key="a.key">
              <td>
                <button type="button" class="lien" @click="aspect = a.key; filtre = 'PERDU'">
                  {{ a.libelle }}
                </button>
              </td>
              <td class="num">{{ a.tenu || '—' }}</td>
              <td class="num" :class="{ alerte: a.perdu > 0 }">{{ a.perdu || '—' }}</td>
              <td class="num" :class="{ bon: a.gagne > 0 }">{{ a.gagne || '—' }}</td>
              <td class="num">{{ a.rate || '—' }}</td>
              <td class="num muted">{{ a.nonJuge || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── Ligne à ligne ────────────────────────────────────────────── -->
      <h2>Ligne à ligne</h2>
      <div class="row filtres">
        <div class="field">
          <label for="cmp-filtre">Ce qu’on regarde</label>
          <select id="cmp-filtre" v-model="filtre">
            <option v-for="f in FILTRES" :key="f" :value="f">
              {{ f === 'TOUT' ? 'Toutes les divergences' : EVAL_BASCULE_LABELS[f] }}
            </option>
          </select>
        </div>
        <div class="field">
          <label for="cmp-aspect">Aspect</label>
          <select id="cmp-aspect" v-model="aspect">
            <option value="">Tous</option>
            <option v-for="a in vue.aspects" :key="a.key" :value="a.key">{{ a.libelle }}</option>
          </select>
        </div>
        <div class="field grow">
          <label for="cmp-cherche">Chercher</label>
          <input id="cmp-cherche" v-model="cherche" type="search" placeholder="une page, une valeur…" />
        </div>
      </div>

      <p class="muted small">
        {{ lignes.length }} ligne(s). Les aspects sur lesquels les deux runs disent
        exactement la même chose ne sont pas listés — ils sont
        {{ vue.identiques }}, et comptés plus haut.
      </p>

      <div class="table-wrap card">
        <table class="lignes">
          <thead>
            <tr>
              <th>Page</th>
              <th>Aspect</th>
              <th>Le corpus attend</th>
              <th>Référence</th>
              <th>Comparé</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(ligne, i) in lignes" :key="`${ligne.sortieId}-${ligne.key}-${i}`">
              <td>
                <a :href="ligne.url" target="_blank" rel="noopener">{{ ligne.label || courtUrl(ligne.url) }}</a>
              </td>
              <td>{{ ligne.libelle }}</td>
              <td class="valeur attendu">{{ ligne.attendu || '∅' }}</td>
              <td class="valeur" :class="{ bon: ligne.verdictA === 'JUSTE' }">
                {{ ligne.renduA || '∅' }}
                <span class="verdict">{{ ligne.verdictA ?? '—' }}</span>
              </td>
              <td class="valeur" :class="{ alerte: ligne.verdictB !== 'JUSTE' }">
                {{ ligne.renduB || '∅' }}
                <span class="verdict">{{ ligne.verdictB ?? '—' }}</span>
              </td>
            </tr>
            <tr v-if="!lignes.length">
              <td colspan="5" class="muted">
                Rien sous ce filtre. C’est une réponse : le second ne casse rien de ce
                que le premier réussissait, sur cet aspect.
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.choix {
  padding: 1rem 1.2rem;
}

.filtres {
  align-items: flex-end;
  margin-bottom: 0.4rem;
}

.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

/* Un chiffre qui saute aux yeux, pas une couleur qui décore : ces deux-là
   sont la raison d'être de la page. */
.alerte {
  color: var(--danger, #b3261e);
  font-weight: 600;
}

.bon {
  color: var(--success, #1b6b3a);
}

.valeur {
  max-width: 22rem;
  font-size: 0.9rem;
  word-break: break-word;
}

.attendu {
  font-style: italic;
}

/* La part de raisonnement sous le total de sortie : une précision, pas une
   colonne — l'additionner compterait deux fois ce qui n'a été payé qu'une. */
.part {
  display: block;
  font-size: 0.72rem;
  opacity: 0.65;
}

.verdict {
  display: block;
  font-size: 0.72rem;
  opacity: 0.6;
  letter-spacing: 0.02em;
}

/* Un libellé d'aspect qui filtre la liste du dessous : c'est un bouton, il
   doit se voir comme tel sans devenir un bouton de formulaire. */
.lien {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  color: var(--link, #1a4fa0);
  cursor: pointer;
  text-align: left;
}

.lien:hover {
  text-decoration: underline;
}

.ghost {
  align-self: flex-end;
  margin-bottom: 0.35rem;
}

.lignes td {
  vertical-align: top;
}
</style>
