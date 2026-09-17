<script setup lang="ts">
/**
 * Le détail d'une mesure : la ligne qui a fait le chiffre.
 *
 * Un taux du banc n'est pas une note, c'est une **conclusion** : elle tombe de
 * la confrontation d'un relevé et d'un corpus, et elle peut surprendre pour
 * trois raisons qui ne se corrigent pas au même endroit —
 *
 *   * la brique a mal fait son travail. C'est le seul cas qu'on veut voir ;
 *   * le corpus est incomplet ou faux, et la mesure accuse un trou plutôt
 *     qu'une brique ;
 *   * la *recherche* du run écarte des liens à raison, et le taux baisse alors
 *     que rien n'a empiré.
 *
 * Aucun total ne les distingue. Chaque ligne porte donc la phrase que la mesure
 * a fabriquée en la rangeant — jamais reconstituée ici : une explication écrite
 * à côté du test finit toujours par décrire un test qui a changé.
 */
import { computed, onMounted, ref } from 'vue';
import { api } from '../lib/api';
import { messageDe } from '../lib/erreurs';
import type {
  EvalAspectDetail,
  EvalAspectTally,
  EvalLinkCase,
  EvalRun,
  EvalRunDetail,
  EvalRunDetailExtract,
  EvalRunDetailPage,
  EvalRunDetailRead,
} from '../types';
import {
  EVAL_FIELD_VERDICT_LABELS,
  EVAL_LINK_CASE_HINTS,
  EVAL_LINK_CASE_LABELS,
  EVAL_RELEVANCE_LABELS,
  EVAL_VERDICT_LABELS,
} from '../types';

const props = defineProps<{ run: EvalRun }>();

const detail = ref<EvalRunDetail | null>(null);
const loading = ref(true);
const error = ref('');
/** La case qu'on regarde. Vide : toutes. */
const filtre = ref<EvalLinkCase | ''>('');
/**
 * Montrer aussi les aspects justes de l'étage 6.
 *
 * Fermé par défaut : douze aspects par sortie, dont onze justes, noient la
 * seule ligne qu'on est venu lire.
 */
const toutMontrer = ref(false);

/**
 * Trier l'encart par aspect le plus raté, plutôt que dans l'ordre des douze.
 *
 * L'ordre canonique est le défaut, et ce n'est pas un détail de présentation :
 * c'est lui qui rend **deux runs comparables ligne à ligne**. Le tri par le
 * pire répond à l'autre question — « sur quoi cette brique-ci échoue-t-elle
 * en particulier ? » —, et les deux valent d'être à un clic l'une de l'autre.
 */
const piresDAbord = ref(false);

onMounted(async () => {
  try {
    const body = await api.get<{ run: EvalRun; detail: EvalRunDetail }>(
      `/api/eval/runs/${props.run.id}`,
    );
    detail.value = body.detail;
  } catch (e) {
    error.value = messageDe(e);
  } finally {
    loading.value = false;
  }
});

const estLien = computed(() => props.run.stage === 'HARVEST' || props.run.stage === 'SELECT');

const pages = computed(() => (estLien.value ? (detail.value as EvalRunDetailPage[]) ?? [] : []));
const lectures = computed(() =>
  props.run.stage === 'READ' ? (detail.value as EvalRunDetailRead[]) ?? [] : [],
);
const extractions = computed(() =>
  props.run.stage === 'EXTRACT' ? (detail.value as EvalRunDetailExtract[]) ?? [] : [],
);

/**
 * Combien de liens dans chaque case, sur tout le run.
 *
 * C'est la première chose à regarder devant un chiffre surprenant : trois
 * « trouvées » et quarante « sans étiquette » donnent 100 % de rappel, et ce
 * 100 % ne dit rien d'autre que la taille du corpus.
 */
const parCas = computed(() => {
  const compte = new Map<EvalLinkCase, number>();
  for (const page of pages.value) {
    for (const lien of page.liens) compte.set(lien.cas, (compte.get(lien.cas) ?? 0) + 1);
  }
  return [...compte.entries()].sort((a, b) => b[1] - a[1]);
});

function liensDe(page: EvalRunDetailPage) {
  return filtre.value ? page.liens.filter((l) => l.cas === filtre.value) : page.liens;
}

/** Les pages qui ont encore quelque chose à montrer sous le filtre courant. */
const pagesVues = computed(() => pages.value.filter((p) => liensDe(p).length > 0));

function basculer(cas: EvalLinkCase) {
  filtre.value = filtre.value === cas ? '' : cas;
}

/**
 * Oui, non, ou « le corpus n'en dit rien » — et les trois ne se confondent pas.
 *
 * Le mot change avec la question : un texte est entier ou amputé, une image est
 * juste ou fausse. « Faux » partout obligerait à se rappeler de quoi la colonne
 * parle pour savoir ce qui cloche.
 */
function troisEtats(value: boolean | null, oui: string, non: string): string {
  if (value === null) return 'le corpus n’en dit rien';
  return value ? oui : non;
}

function aspectsVus(row: EvalRunDetailExtract): EvalAspectDetail[] {
  return toutMontrer.value ? row.aspects : row.aspects.filter((a) => a.verdict !== 'JUSTE');
}

/**
 * Le décompte par aspect sur tout le run, tel que le serveur l'a calculé.
 *
 * Recalculé nulle part ici : les verdicts viennent de `verdictAspect`, côté
 * serveur, et deux implémentations d'une même règle finissent par diverger
 * sans que rien ne le dise.
 */
const parAspect = computed<EvalAspectTally[]>(() => {
  const score = props.run.score;
  if (!score || score.kind !== 'extract') return [];
  const lignes = [...(score.parAspect ?? [])];
  if (!piresDAbord.value) return lignes;
  // Les aspects que personne n'a étiquetés vont à la fin : ils ne sont pas
  // « les pires », ils ne sont pas jugés du tout.
  return lignes.sort((a, b) => {
    if (a.rate === null) return b.rate === null ? 0 : 1;
    if (b.rate === null) return -1;
    return a.rate - b.rate;
  });
});

/** Un aspect que le corpus n'étiquette nulle part : une dette, pas une faute. */
function sansEtiquette(ligne: EvalAspectTally): boolean {
  return ligne.rate === null;
}

/**
 * Le score de la page, en une ligne.
 *
 * Page par page, parce que c'est page par page que le rappel se calcule — et
 * qu'une seule page ratée sur dix explique souvent tout l'écart d'un run à
 * l'autre.
 */
function scorePage(page: EvalRunDetailPage): string {
  const s = page.score;
  const pct = (v: number | null | undefined) =>
    v === null || v === undefined ? '—' : `${Math.round(v * 100)} %`;
  return (
    `${s.found} trouvée(s) · ${s.missed} manquée(s) · ${s.noise} bruit · ` +
    `rappel ${pct(s.recall)} · précision ${pct(s.precision)}`
  );
}

function court(value: string, max = 90): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}
</script>

<template>
  <div class="detail-run">
    <p v-if="loading" class="muted small">Chargement du détail…</p>
    <p v-else-if="error" class="error small">{{ error }}</p>

    <!-- ── Les liens : dépouillement et tri ───────────────────────────── -->
    <template v-else-if="estLien">
      <p class="muted small">
        Chaque lien du relevé, avec <strong>la case où la mesure l’a rangé</strong>
        et la phrase qui le dit. Les cases grisées sont hors de tout
        dénominateur : elles ne font monter ni descendre aucun taux, et ce sont
        elles qu’un total ne laisse jamais deviner.
      </p>
      <div class="cas-chips">
        <button
          v-for="[cas, n] in parCas"
          :key="cas"
          class="chip"
          :class="{ on: filtre === cas, mou: cas === 'SANS_ETIQUETTE' || cas === 'NON_SOUMISE' || cas === 'INDECIDABLE' }"
          :title="EVAL_LINK_CASE_HINTS[cas]"
          @click="basculer(cas)"
        >
          {{ EVAL_LINK_CASE_LABELS[cas] }} · {{ n }}
        </button>
        <button v-if="filtre" class="linklike" @click="filtre = ''">tout remontrer</button>
      </div>

      <div v-for="page in pagesVues" :key="page.pageId" class="page-detail">
        <h4>
          {{ page.label || page.url }}
          <span class="muted small">page {{ page.pageNo }}</span>
          <span v-if="page.plafonnee" class="badge plafond" title="Le tri a retenu exactement son quota : on ne peut pas distinguer un mauvais jugement d’un plafond atteint. Cette page sort du rappel.">
            au plafond — hors du rappel
          </span>
          <a :href="`/api/eval/pages/${page.pageId}/html`" target="_blank" class="muted small">
            HTML gelé
          </a>
        </h4>
        <p class="muted small score-page">{{ scorePage(page) }}</p>
        <p class="muted small pagination-ligne">
          Page suivante — le corpus dit
          <code v-if="page.pagination.attendu">{{ page.pagination.attendu }}</code>
          <em v-else-if="page.pagination.attendu === ''">qu’il n’y en a pas</em>
          <em v-else>rien (non étiquetée)</em>
          ; le relevé a trouvé
          <code v-if="page.pagination.trouve">{{ page.pagination.trouve }}</code>
          <em v-else>rien</em>.
        </p>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Lien</th>
                <th>Le corpus dit</th>
                <th>La brique a fait</th>
                <th>Compté comme, et pourquoi</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="lien in liensDe(page)"
                :key="lien.url"
                :class="{ mou: lien.horsTaux }"
              >
                <td>
                  <div class="link-text">{{ lien.texte || '(sans texte)' }}</div>
                  <a :href="lien.url" target="_blank" class="muted small">{{ court(lien.url) }}</a>
                  <div v-if="lien.contexte" class="muted small ctx">
                    {{ court(lien.contexte, 160) }}
                  </div>
                </td>
                <td class="small">
                  <span v-if="lien.verdict">{{ EVAL_VERDICT_LABELS[lien.verdict] }}</span>
                  <em v-else class="muted">rien — lien non étiqueté</em>
                  <div v-if="lien.relevance" class="muted small">
                    pour cette recherche : {{ EVAL_RELEVANCE_LABELS[lien.relevance] }}
                  </div>
                </td>
                <td class="small">
                  <strong>{{ lien.retenu ? 'retenu' : 'écarté' }}</strong>
                  <!--
                    Ce que la brique dit d'elle-même, à côté de ce que la mesure
                    conclut. C'est le seul moyen de distinguer « le modèle a mal
                    jugé » de « le modèle n'a jamais vu ce lien » — deux fautes
                    qui se corrigent à deux étages différents.
                  -->
                  <div v-if="lien.motif" class="muted small">{{ court(lien.motif, 140) }}</div>
                </td>
                <td class="small">
                  <span class="cas" :class="lien.cas.toLowerCase()">
                    {{ EVAL_LINK_CASE_LABELS[lien.cas] }}
                  </span>
                  <div class="muted small">{{ lien.raison }}</div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <p v-if="!pagesVues.length" class="muted small">
        Rien sous ce filtre.
      </p>
    </template>

    <!-- ── La lecture ─────────────────────────────────────────────────── -->
    <template v-else-if="run.stage === 'READ'">
      <p class="muted small">
        Trois questions par page, et l’attendu en regard du rendu. « Le texte
        n’est pas entier » ne dit pas si la page est tronquée, si elle passe par
        du JavaScript, ou si le fragment attendu était mal choisi — et les trois
        se corrigent ailleurs.
      </p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Page</th>
              <th>Texte</th>
              <th>Illustration</th>
              <th>Dates déclarées</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in lectures" :key="row.sortieId">
              <td>
                <div class="link-text">{{ row.label || row.url }}</div>
                <a :href="row.url" target="_blank" class="muted small">{{ court(row.url) }}</a>
                <div class="muted small">
                  {{ row.textChars }} caractères
                  <span v-if="row.detail.truncated" class="badge">tronqué</span>
                  <span v-if="row.detail.tooShort" class="badge">sous le seuil</span>
                </div>
                <div v-if="row.error" class="error small">{{ row.error }}</div>
              </td>
              <td class="small">
                <span class="cas" :class="row.detail.fragments.verdict === null ? 'indecidable' : row.detail.fragments.verdict ? 'trouvee' : 'manquee'">
                  {{ troisEtats(row.detail.fragments.verdict, 'texte entier', 'texte amputé') }}
                </span>
                <div v-if="row.detail.fragments.manquants.length" class="muted small">
                  absent du texte :
                  <ul class="fragments">
                    <li v-for="f in row.detail.fragments.manquants" :key="f">« {{ f }} »</li>
                  </ul>
                </div>
                <div v-else-if="row.detail.fragments.trouves.length" class="muted small">
                  {{ row.detail.fragments.trouves.length }} fragment(s) retrouvé(s)
                </div>
                <div v-else class="muted small">aucun fragment étiqueté</div>
              </td>
              <td class="small">
                <span class="cas" :class="row.detail.image.verdict === null ? 'indecidable' : row.detail.image.verdict ? 'trouvee' : 'manquee'">
                  {{ troisEtats(row.detail.image.verdict, 'juste', 'fausse') }}
                </span>
                <div v-if="row.detail.image.attendu !== null" class="muted small">
                  corpus : {{ court(row.detail.image.attendu || '(aucune)', 60) }}
                </div>
                <div class="muted small">rendu : {{ court(row.detail.image.rendu || '(aucune)', 60) }}</div>
              </td>
              <td class="small">
                <span class="cas" :class="row.detail.dates.verdict === null ? 'indecidable' : row.detail.dates.verdict ? 'trouvee' : 'manquee'">
                  {{ troisEtats(row.detail.dates.verdict, 'justes', 'fausses') }}
                </span>
                <div v-if="row.detail.dates.attendues" class="muted small">
                  corpus : {{ row.detail.dates.attendues.join(', ') || '(aucune)' }}
                </div>
                <div class="muted small">
                  rendu : {{ row.detail.dates.rendues.join(', ') || '(aucune)' }}
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- ── L'extraction ───────────────────────────────────────────────── -->
    <template v-else>
      <p class="muted small">
        Les aspects que le corpus permet de juger, avec <strong>les deux valeurs
        comparées</strong>. Sans elles, « faux » est une accusation sans pièce
        jointe : on ne sait pas si le modèle s’est trompé, si l’étiquette était
        fautive, ou si les deux disent la même chose autrement — et ce dernier
        cas est une faute de la mesure, qu’aucun total ne révèle.
      </p>
      <!--
        L'encart : le taux d'un run est une moyenne sur douze aspects très
        différents, et il cache lequel lâche. Douze aspects médiocres et onze
        corrects pour un effondré donnent le même chiffre.
      -->
      <div v-if="parAspect.length" class="card aspects-bilan">
        <h4>
          Aspect par aspect
          <button class="linklike" @click="piresDAbord = !piresDAbord">
            {{ piresDAbord ? 'dans l’ordre des douze' : 'les pires d’abord' }}
          </button>
        </h4>
        <table class="aspects-table">
          <thead>
            <tr>
              <th>Aspect</th>
              <th class="num">Justes</th>
              <th class="num">Faux</th>
              <th class="num">Inventés</th>
              <th class="num">Manqués</th>
              <th class="num">Non jugés</th>
              <th class="num">Taux</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ligne in parAspect" :key="ligne.key" :class="{ muet: sansEtiquette(ligne) }">
              <td>{{ ligne.libelle }}</td>
              <td class="num juste">{{ ligne.JUSTE || '—' }}</td>
              <td class="num faux">{{ ligne.FAUX || '—' }}</td>
              <td class="num faux">{{ ligne.INVENTE || '—' }}</td>
              <td class="num faux">{{ ligne.MANQUE || '—' }}</td>
              <td class="num muted">{{ ligne.inconnu || '—' }}</td>
              <td class="num">
                <strong v-if="ligne.rate !== null">{{ Math.round(ligne.rate * 100) }} %</strong>
                <span v-else class="muted">non jugé</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="muted small">
          <strong>Non jugé n’est pas raté.</strong> C’est le corpus qui ne dit rien
          de cet aspect-là : une dette d’étiquetage, pas une faute de la brique.
          Un aspect entièrement non jugé ne compte donc dans aucun taux — le
          sien, ni celui du run.
        </p>
        <p class="muted small">
          <strong>Manqué</strong> : le corpus l’annonce, la brique a rendu vide.
          <strong>Inventé</strong> : la brique l’a rempli, le corpus n’en dit rien.
          <strong>Faux</strong> : les deux parlent, et ne disent pas la même chose.
          Les trois se corrigent autrement, et c’est pourquoi ils ne sont pas
          additionnés.
        </p>
      </div>

      <p class="muted small">
        <button class="linklike" @click="toutMontrer = !toutMontrer">
          {{ toutMontrer ? 'Ne montrer que ce qui cloche' : 'Montrer aussi les aspects justes' }}
        </button>
      </p>
      <div v-for="row in extractions" :key="row.sortieId" class="card fiche-detail">
        <h4>
          {{ row.label || row.url }}
          <a :href="row.url" target="_blank" class="muted small">la page</a>
          <span class="muted small">
            {{ row.tally.JUSTE }} juste(s) · {{ row.tally.FAUX }} faux ·
            {{ row.tally.INVENTE }} inventé(s) · {{ row.tally.MANQUE }} manquant(s) ·
            {{ row.tally.inconnu }} non jugé(s)
          </span>
        </h4>
        <p v-if="row.error" class="error small">{{ row.error }}</p>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Aspect</th>
                <th>Verdict</th>
                <th>Ce que le corpus déclare</th>
                <th>Ce que la brique a rendu</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="aspect in aspectsVus(row)" :key="aspect.key">
                <td class="small">{{ aspect.libelle }}</td>
                <td class="small">
                  <span v-if="aspect.verdict" class="cas" :class="aspect.verdict.toLowerCase()">
                    {{ EVAL_FIELD_VERDICT_LABELS[aspect.verdict] }}
                  </span>
                  <!--
                    Pas un verdict : personne n'a étiqueté cet aspect. Le dire
                    plutôt que de laisser une case vide, qui se lirait « juste ».
                  -->
                  <em v-else class="muted">le corpus n’en dit rien</em>
                </td>
                <td class="small">
                  <code v-if="aspect.attendu">{{ court(aspect.attendu, 120) }}</code>
                  <em v-else class="muted">—</em>
                </td>
                <td class="small">
                  <code>{{ court(aspect.rendu, 120) }}</code>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!aspectsVus(row).length" class="muted small">
          Les douze aspects jugés sont justes.
        </p>
      </div>
      <p v-if="!extractions.length" class="muted small">Ce run n’a rien produit.</p>
    </template>
  </div>
</template>

<style scoped>
.detail-run {
  border-top: 1px solid var(--line);
  margin-top: 0.6rem;
  padding-top: 0.8rem;
}

.cas-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
  margin-bottom: 0.8rem;
}

.chip {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0.15rem 0.6rem;
  background: none;
  font: inherit;
  font-size: 0.8rem;
  cursor: pointer;
}

.chip.on {
  border-color: var(--accent);
  background: var(--accent-soft);
}

/* Les cases hors de tout dénominateur : elles ne font monter ni descendre
   aucun taux, et doivent se lire comme telles. */
.chip.mou,
tr.mou {
  color: var(--ink-soft);
}

.page-detail {
  margin-bottom: 1.4rem;
}

.page-detail h4 {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  flex-wrap: wrap;
  margin: 0 0 0.3rem;
}

.score-page,
.pagination-ligne {
  margin: 0 0 0.3rem;
}

.badge {
  font-size: 0.72rem;
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 0.05rem 0.45rem;
  color: var(--ink-soft);
}

.badge.plafond {
  color: var(--warn);
}

.cas {
  font-weight: 700;
  white-space: nowrap;
}

.cas.trouvee,
.cas.juste {
  color: var(--ok);
}

.cas.manquee,
.cas.faux,
.cas.invente,
.cas.manque {
  color: var(--danger);
}

.cas.bruit {
  color: var(--warn);
}

.cas.ecartee_a_raison {
  color: var(--ok);
}

.cas.indecidable,
.cas.sans_etiquette,
.cas.non_soumise {
  color: var(--ink-soft);
}

.aspects-bilan {
  margin-bottom: 1rem;
}

.aspects-bilan h4 {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  margin: 0 0 0.6rem;
}

.aspects-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

.aspects-table th,
.aspects-table td {
  padding: 0.25rem 0.5rem;
  border-bottom: 1px solid var(--border, #eee);
  text-align: left;
}

.aspects-table .num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

/* Les mêmes couleurs que les verdicts des lignes, qui ne valaient jusqu'ici
   que sous `.cas`. Le vert et le rouge ne portent aucune information que le
   chiffre ne porte pas : ils font gagner le coup d'œil, pas la lecture. */
.aspects-table .juste {
  color: var(--ok);
}

.aspects-table .faux {
  color: var(--danger);
}

/* Un aspect que personne n'a étiqueté s'efface : il ne dit rien de la brique,
   et le laisser au même poids ferait chercher une faute là où il n'y a qu'un
   corpus muet. */
.aspects-table tr.muet td {
  opacity: 0.55;
}

.fiche-detail {
  padding: 0.8rem 1rem;
  margin-bottom: 0.8rem;
}

.fiche-detail h4 {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  flex-wrap: wrap;
  margin: 0 0 0.4rem;
}

.fragments {
  margin: 0.2rem 0 0;
  padding-left: 1.1rem;
}

.link-text {
  font-weight: 600;
}

.ctx {
  max-width: 46ch;
}

.table-wrap {
  overflow-x: auto;
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
</style>
