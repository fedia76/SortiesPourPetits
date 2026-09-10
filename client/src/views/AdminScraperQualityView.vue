<script setup lang="ts">
/**
 * Ce que la modération apprend au scraper.
 *
 * La page voisine — « Statistiques » — dit **d'où vient** le catalogue : quel
 * domaine coûte combien de pages, quelle catégorie manque. Celle-ci répond à
 * l'autre question, que rien ne posait : **où le pipeline se trompe-t-il, et
 * de combien ?**
 *
 * Elle ne mesure qu'une chose, et il faut le dire haut pour qu'on ne lui
 * demande pas l'autre : la **précision** — ce qui est parti était-il bon ? Le
 * **rappel** — qu'a-t-on manqué ? — n'a aucune ligne ici, et ne peut pas en
 * avoir : une sortie jamais trouvée ne laisse pas de trace. C'est le travail
 * du banc d'évaluation, et les deux ne se remplacent pas.
 *
 * Rien de ce qui est affiché ici ne coûte un geste à personne. Le motif de
 * refus est une puce que le modérateur clique au lieu de taper une phrase ;
 * les corrections sont le relevé d'un geste qu'il faisait déjà.
 */
import { computed, onMounted, ref, watch } from 'vue';
import { api } from '../lib/api';
import type { ScraperConfig, ScraperQuality } from '../types';
import { ATTRIBUTION_SIGNAL_HINTS, FIELD_LABELS, SOURCE_SIGNAL_LABELS } from '../types';

const configs = ref<ScraperConfig[]>([]);
const data = ref<ScraperQuality | null>(null);
const loading = ref(true);
const error = ref('');

/** `0` : toutes les recherches confondues. */
const configId = ref(0);
/** `0` : tout l'historique. */
const days = ref(0);

const PERIODS = [
  { value: 0, label: 'Depuis toujours' },
  { value: 7, label: '7 jours' },
  { value: 30, label: '30 jours' },
  { value: 90, label: '90 jours' },
];

async function load() {
  loading.value = true;
  error.value = '';
  const params = new URLSearchParams();
  if (configId.value) params.set('configId', String(configId.value));
  if (days.value) params.set('days', String(days.value));
  try {
    data.value = await api.get<ScraperQuality>(`/api/scraper/quality?${params}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  try {
    const body = await api.get<{ configs: ScraperConfig[] }>('/api/scraper/configs');
    configs.value = body.configs;
  } catch {
    // Le sélecteur est un confort : son échec ne doit pas emporter la mesure.
  }
  await load();
});

watch([configId, days], load);

/** Part en pourcentage, sur un total qui peut être nul. */
function share(value: number, total: number): number {
  return total > 0 ? Math.round((value / total) * 1000) / 10 : 0;
}

function percent(rate: number | null): string {
  return rate === null ? '—' : `${Math.round(rate * 100)} %`;
}

/** Sorties effectivement jugées : les « en attente » ne comptent nulle part. */
const judged = computed(() => {
  const j = data.value?.judged;
  return j ? j.approved + j.rejected : 0;
});

const approvalRate = computed(() =>
  judged.value > 0 ? (data.value?.judged.approved ?? 0) / judged.value : null,
);

/** Fiches du scraper qu'un modérateur a relues : retouchées ou non. */
const reviewed = computed(() => {
  const c = data.value?.corrections;
  return c ? c.untouched + c.touched : 0;
});

const meaningOf = computed(() => new Map((data.value?.codes ?? []).map((c) => [c.code, c])));

/** Les refus, du plus fréquent au moins fréquent, avec leur libellé. */
const rejections = computed(() =>
  [...(data.value?.rejections ?? [])]
    .map((r) => {
      const meaning = r.code ? meaningOf.value.get(r.code) : undefined;
      return {
        code: r.code ?? '',
        // Un refus antérieur au motif comptable n'est pas caché : un tableau
        // qui tait ce qu'il ignore laisse croire que la mesure est complète.
        label: meaning?.label ?? (r.code ? r.code : 'Sans motif enregistré'),
        blame: meaning?.blames[0] ?? null,
        events: r.events,
      };
    })
    .sort((a, b) => b.events - a.events),
);

/**
 * Les refus imputés à chaque étage.
 *
 * Un motif qui met en cause plusieurs briques est compté sur la **première**,
 * la plus probable, et sur elle seule : réparti sur toutes, un même refus
 * gonflerait le total et l'on croirait le pipeline plus fautif qu'il n'est.
 * Ce qui n'accuse personne — un doublon, un « autre » — n'apparaît pas.
 */
const byStage = computed(() => {
  const buckets = new Map<string, { number: number; label: string; events: number }>();
  for (const row of rejections.value) {
    if (!row.blame) continue;
    const bucket = buckets.get(row.blame.stage) ?? {
      number: row.blame.number,
      label: row.blame.label,
      events: 0,
    };
    bucket.events += row.events;
    buckets.set(row.blame.stage, bucket);
  }
  return [...buckets.values()].sort((a, b) => a.number - b.number);
});

const stageTotal = computed(() => byStage.value.reduce((sum, s) => sum + s.events, 0));
const rejectionTotal = computed(() => rejections.value.reduce((sum, r) => sum + r.events, 0));

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

function signalLabel(signal: string): string {
  return signal ? SOURCE_SIGNAL_LABELS[signal] ?? signal : 'aucun (la page lue faisait foi)';
}
</script>

<template>
  <div class="container page">
    <h1>Recherche automatique — ce que la modération apprend</h1>
    <nav class="row" style="gap: 1rem; margin-bottom: 1rem">
      <RouterLink to="/admin/scraper">Recherches et exécutions</RouterLink>
      <RouterLink to="/admin/scraper/agregateurs">Agrégateurs</RouterLink>
      <RouterLink to="/admin/scraper/stats">Statistiques</RouterLink>
      <RouterLink to="/admin/scraper/qualite">Qualité</RouterLink>
      <RouterLink to="/admin/scraper/memoire">Mémoire</RouterLink>
    </nav>

    <p class="muted">
      La page « Statistiques » dit d'où vient le catalogue. Celle-ci dit
      <strong>où le pipeline se trompe</strong>, à partir de ce que la
      modération fait déjà : un motif de refus cliqué, et les champs qu'un
      relecteur corrige avant d'approuver.
    </p>

    <div class="row stats-filters">
      <div class="field">
        <label for="ql-config">Recherche</label>
        <select id="ql-config" v-model.number="configId">
          <option :value="0">Toutes les recherches</option>
          <option v-for="c in configs" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>
      <div class="field">
        <label for="ql-days">Période</label>
        <select id="ql-days" v-model.number="days">
          <option v-for="p in PERIODS" :key="p.value" :value="p.value">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading" class="muted">Chargement…</p>

    <template v-if="data">
      <div class="tiles">
        <div class="card tile">
          <span class="value">{{ data.corrections.untouched }}</span>
          <!-- La seule preuve positive dont on dispose sur l'étage 6 : une
               fiche prise telle quelle, sans qu'un humain ait rien eu à
               reprendre. -->
          <span class="label">approuvées sans retouche</span>
        </div>
        <div class="card tile">
          <span class="value">{{ data.corrections.touched }}</span>
          <span class="label">approuvées après correction</span>
        </div>
        <div class="card tile">
          <span class="value">{{ data.judged.rejected }}</span>
          <span class="label">refusées</span>
        </div>
        <div class="card tile">
          <span class="value">{{ percent(approvalRate) }}</span>
          <span class="label">
            approuvées sur {{ judged }} jugée(s)
          </span>
        </div>
        <div class="card tile">
          <span class="value">{{ data.judged.pending }}</span>
          <span class="label">en attente — comptées nulle part</span>
        </div>
      </div>

      <!-- ── Les corrections ─────────────────────────────────────────── -->
      <h2>Ce que la modération corrige, champ par champ</h2>
      <p class="muted small">
        La mesure la moins chère du projet, et la seule qui désigne un champ
        plutôt qu'une fiche : un taux d'approbation dit qu'une fiche était
        mauvaise, ce tableau dit que c'était la ville. La part se lit sur les
        {{ reviewed }} fiche(s) relue(s) sur la période.
      </p>
      <p v-if="!data.corrections.fields.length" class="muted">
        Aucune correction enregistrée. Soit rien n'a été retouché, soit aucune
        fiche du scraper n'est passée en modération depuis la mise en place de
        cette mesure — elle ne rattrape pas le passé.
      </p>
      <div v-else class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Champ</th>
              <th>Fiches corrigées</th>
              <th>Part des fiches relues</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="f in data.corrections.fields" :key="f.field">
              <td>{{ fieldLabel(f.field) }}</td>
              <td class="num">{{ f.events }}</td>
              <td class="bar-cell">
                <span class="bar"><i :style="{ width: `${share(f.events, reviewed)}%` }" /></span>
                <span class="pct">{{ share(f.events, reviewed) }} %</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── Les motifs de refus ─────────────────────────────────────── -->
      <h2>Pourquoi les sorties sont refusées</h2>
      <p class="muted small">
        Un motif n'apprend quelque chose que s'il désigne un étage : c'est la
        règle qui a décidé de la liste des puces, et la colonne de droite en
        est la conséquence.
      </p>
      <p v-if="!rejections.length" class="muted">Aucun refus sur ce périmètre.</p>
      <div v-else class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Motif</th>
              <th>Sorties</th>
              <th>Part des refus</th>
              <th>Étage mis en cause</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rejections" :key="r.code || 'sans-motif'">
              <td>{{ r.label }}</td>
              <td class="num">{{ r.events }}</td>
              <td class="bar-cell">
                <span class="bar">
                  <i :style="{ width: `${share(r.events, rejectionTotal)}%` }" />
                </span>
                <span class="pct">{{ share(r.events, rejectionTotal) }} %</span>
              </td>
              <td>
                <span v-if="r.blame">{{ r.blame.number }}. {{ r.blame.label }}</span>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── Par étage ───────────────────────────────────────────────── -->
      <h2>Les refus, rangés par brique</h2>
      <p class="muted small">
        Un motif qui met plusieurs briques en cause est compté sur la première,
        la plus probable, et sur elle seule : réparti sur toutes, un même refus
        gonflerait le total et ferait paraître le pipeline plus fautif qu'il ne
        l'est. Ce qui n'accuse personne — un doublon, un « autre » — n'est pas
        dans ce tableau.
      </p>
      <p v-if="!byStage.length" class="muted">Aucun refus imputé à une brique.</p>
      <div v-else class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Brique</th>
              <th>Refus</th>
              <th>Part des refus imputés</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in byStage" :key="s.number">
              <td>{{ s.number }}. {{ s.label }}</td>
              <td class="num">{{ s.events }}</td>
              <td class="bar-cell">
                <span class="bar">
                  <i :style="{ width: `${share(s.events, stageTotal)}%` }" />
                </span>
                <span class="pct">{{ share(s.events, stageTotal) }} %</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── L'attribution ───────────────────────────────────────────── -->
      <h2>Les signaux de l'attribution</h2>
      <p class="muted small">
        L'étage 7 propose un lien et dit sur quoi il s'est fondé. Voici ce que
        la modération a fait des fiches qu'il a servies, signal par signal. La
        ligne « saisi à la main » est la plus instructive de toutes : c'est un
        lien qu'un humain a dû reprendre.
      </p>
      <p v-if="!data.signals.length" class="muted">Aucune sortie jugée sur ce périmètre.</p>
      <div v-else class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Signal</th>
              <th>Jugées</th>
              <th>Approuvées</th>
              <th>Taux</th>
              <th>Ce qu'on en sait</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in data.signals" :key="s.signal || 'aucun'">
              <td :title="ATTRIBUTION_SIGNAL_HINTS[s.signal] ?? ''">
                {{ signalLabel(s.signal) }}
                <span v-if="!s.enough" class="muted small"> · non classé</span>
              </td>
              <td class="num">{{ s.judged }}</td>
              <td class="num">{{ s.approved }}</td>
              <td class="num">{{ percent(s.rate) }}</td>
              <td class="bar-cell">
                <span class="bar"><i :style="{ width: `${Math.round(s.lower * 100)}%` }" /></span>
                <span class="pct">≥ {{ Math.round(s.lower * 100) }} %</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── Les requêtes ────────────────────────────────────────────── -->
      <h2>Rendement d'une requête web</h2>
      <p class="muted small">
        Ce que 0,01 $ de recherche rapporte vraiment. La filiation vient du
        journal du run, recopiée sur chaque page à la clôture : les exécutions
        antérieures à cette recopie n'ont pas de requête, et n'apparaissent pas
        ici.
      </p>
      <p v-if="!data.queries.length" class="muted">
        Aucune requête rattachée. Normal si aucune exécution en mode « recherche »
        ne s'est terminée depuis la mise en place de la recopie — et normal pour
        toujours en mode « site », qui ne lance aucune recherche.
      </p>
      <div v-else class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Requête</th>
              <th>Pages lues</th>
              <th>Proposées</th>
              <th>Jugées</th>
              <th>Approuvées</th>
              <th>Taux</th>
              <th>Ce qu'on en sait</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="q in data.queries" :key="q.query">
              <td>
                {{ q.query }}
                <span v-if="!q.enough" class="muted small"> · non classé</span>
              </td>
              <td class="num">{{ q.pages }}</td>
              <td class="num">{{ q.submitted }}</td>
              <td class="num">{{ q.judged }}</td>
              <td class="num">{{ q.approved }}</td>
              <td class="num">{{ percent(q.rate) }}</td>
              <td class="bar-cell">
                <span class="bar"><i :style="{ width: `${Math.round(q.lower * 100)}%` }" /></span>
                <span class="pct">≥ {{ Math.round(q.lower * 100) }} %</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── Les domaines ────────────────────────────────────────────── -->
      <h2>Qualité par domaine</h2>
      <p class="muted small">
        La page « Statistiques » donne le volume de chaque source ; ici c'est sa
        qualité, et le classement se fait sur ce qu'on sait du taux, pas sur ce
        qu'on en a vu.
      </p>
      <p v-if="!data.domains.length" class="muted">Aucune sortie proposée sur ce périmètre.</p>
      <div v-else class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Domaine</th>
              <th>Pages lues</th>
              <th>Proposées</th>
              <th>Jugées</th>
              <th>Approuvées</th>
              <th>Taux</th>
              <th>Ce qu'on en sait</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in data.domains" :key="d.domain">
              <td>
                {{ d.domain }}
                <span v-if="!d.enough" class="muted small"> · non classé</span>
              </td>
              <td class="num">{{ d.pages }}</td>
              <td class="num">{{ d.submitted }}</td>
              <td class="num">{{ d.judged }}</td>
              <td class="num">{{ d.approved }}</td>
              <td class="num">{{ percent(d.rate) }}</td>
              <td class="bar-cell">
                <span class="bar"><i :style="{ width: `${Math.round(d.lower * 100)}%` }" /></span>
                <span class="pct">≥ {{ Math.round(d.lower * 100) }} %</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── Comment lire tout ça ────────────────────────────────────── -->
      <h2>Comment lire ces tableaux</h2>
      <div class="card notice">
        <p>
          <strong>« Ce qu'on en sait » n'est pas le taux.</strong> C'est la
          borne basse de son intervalle de confiance à 95 %, et c'est elle qui
          ordonne les tableaux. Un domaine approuvé 3 fois sur 3 affiche 100 %
          et ne vaut pourtant pas un domaine approuvé 40 fois sur 50 : le
          premier est à 44 %, le second à 67 %. La colonne dit ce qu'on sait,
          la colonne « Taux » ce qu'on a vu.
        </p>
        <p>
          <strong>« Non classé »</strong> marque les lignes de moins de
          {{ data.rankingFloor }} sorties jugées. Elles sont affichées, jamais
          classées : on ne les cache pas, on dit qu'on ne sait pas encore.
        </p>
        <p>
          <strong>Cette page mesure la précision, pas le rappel.</strong> Elle
          dit si ce qui est parti était bon. Elle ne dit rien de ce que le
          pipeline n'a jamais trouvé — une sortie manquée ne laisse aucune
          trace, et aucun tableau bâti sur la modération ne pourra le dire.
          C'est le travail du <RouterLink to="/admin/evaluation">banc
          d'évaluation</RouterLink>, et les deux sont complémentaires.
        </p>
        <p>
          <strong>Ces chiffres décrivent aussi vos propres décisions.</strong>
          Un domaine bloqué ne propose plus rien, donc n'a plus de score, donc
          reste bloqué. Avant de retirer une source ou une requête sur la foi
          de ce tableau, gardez-lui de quoi se démentir.
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.stats-filters {
  gap: 1rem;
  align-items: flex-end;
  margin-bottom: 1.2rem;
}

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.8rem;
  margin-bottom: 1.6rem;
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

h2 {
  margin-top: 1.6rem;
}

.table-wrap {
  overflow-x: auto;
}

.num {
  text-align: right;
  white-space: nowrap;
}

.bar-cell {
  min-width: 160px;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.bar {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: var(--photo-bg);
  overflow: hidden;
}

.bar i {
  display: block;
  height: 100%;
  background: var(--accent);
}

.pct {
  font-size: 0.8rem;
  color: var(--ink-soft);
  white-space: nowrap;
}

.small {
  font-size: 0.85rem;
}

.notice {
  padding: 1rem 1.2rem;
}

.notice p {
  margin: 0 0 0.7rem;
}

.notice p:last-child {
  margin-bottom: 0;
}
</style>
