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
import { computed, nextTick, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../lib/api';
import {
  apparierReleve,
  basculer,
  cochees,
  corrections,
  enAttente,
  etatDeCompletude,
  motifsDeRejet,
  pageSuivanteTrouvee,
  phraseDePortee,
  precocher,
  restantes,
  resumeSortie,
  venueDeLEtiquette,
} from '../lib/banc';
import { messageDe } from '../lib/erreurs';
import type {
  EvalAgenda,
  EvalAgendaCandidat,
  EvalHunt,
  EvalHuntPage,
  EvalNature,
  EvalPageNature,
  EvalSortieLabel,
  EvalAudience,
  EvalRunScope,
  EvalSortieFacts,
  EvalSortie,
  EvalCriteres,
  EvalReste,
  EvalSeedCounts,
  EvalVerdict,
  SoucheCorpus,
} from '../types';
import {
  EVAL_AUDIENCE_HINTS,
  EVAL_NATURE_HINTS,
  EVAL_NATURE_LABELS,
  EVAL_AUDIENCE_LABELS,
  EVAL_RELEVANCE_HINTS,
  EVAL_RELEVANCE_LABELS,
  EVAL_CAPTURE_LABELS,
  EVAL_ETAPE_LABELS,
  EVAL_ETAPE_SUITE,
  EVAL_HUNT_STATUS_LABELS,
  EVAL_LABEL_ORIGIN_LABELS,
  EVAL_NATURE_ORIGIN_HINTS,
  EVAL_NATURE_ORIGIN_LABELS,
  EVAL_ORIGIN_HINTS,
  EVAL_ORIGIN_LABELS,
  EVAL_VERDICT_HINTS,
  EVAL_VERDICT_LABELS,
} from '../types';

const VERDICTS: EvalVerdict[] = ['SORTIE', 'PAGINATION', 'SOUS_AGENDA', 'AUTRE'];
const AUDIENCES: EvalAudience[] = ['ENFANTS', 'ADULTES', 'INDETERMINE'];

const agendas = ref<EvalAgenda[]>([]);
const sorties = ref<EvalSortie[]>([]);
/** Le corpus de l'étage 2 : ce qu'une page est, avant qu'on en fasse rien. */
const natures = ref<EvalNature[]>([]);
const newNatureUrl = ref('');
const newNature = ref<EvalPageNature>('AGENDA');
const NATURES: EvalPageNature[] = ['AGENDA', 'SORTIE', 'PROGRAMME', 'AUTRE'];
/**
 * Ce que le corpus de l'étage 2 doit à la brique qu'il mesure.
 *
 * Sa taille ne dit rien : un corpus rempli en validant les précoches d'une
 * chasse grossit sans mesurer autre chose que l'étage 2 contre lui-même. Ce
 * chiffre-ci est le seul qui le dise, et c'est pourquoi il est affiché même
 * quand il est bon.
 */
const souche = ref<SoucheCorpus | null>(null);
/** Les chasses, la plus récente d'abord, avec leurs candidates. */
const chasses = ref<EvalHunt[]>([]);
const nouvelleChasse = ref({
  prompt: '',
  area: 'Île-de-France',
  maxQueries: 6,
  maxPages: 30,
  queries: '',
});
/**
 * Ce qu'on s'apprête à écrire au corpus, candidate par candidate.
 *
 * Absent : on ne retient pas — c'est l'état d'une page que l'étage 2 n'a pas
 * su reconnaître, et elle reste alors en attente plutôt que d'être écartée
 * dans le dos de quelqu'un.
 */
const choix = ref<Record<number, EvalPageNature>>({});
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
/** Ce que chaque étage cherche à savoir. Du serveur, jamais recopié ici. */
const criteres = ref<EvalCriteres | null>(null);
const criteresOuverts = ref(false);
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
    const [a, r, n, c] = await Promise.all([
      api.get<{ agendas: EvalAgenda[] }>('/api/eval/agendas'),
      api.get<{ sorties: EvalSortie[] }>('/api/eval/sorties'),
      api.get<{ natures: EvalNature[]; souche: SoucheCorpus }>('/api/eval/natures'),
      api.get<{ hunts: EvalHunt[] }>('/api/eval/hunts'),
    ]);
    agendas.value = a.agendas;
    sorties.value = r.sorties;
    natures.value = n.natures;
    souche.value = n.souche;
    poserLesChasses(c.hunts);
  } catch (e) {
    error.value = messageDe(e);
  } finally {
    loading.value = false;
  }
  try {
    seed.value = await api.get<EvalSeedCounts>('/api/eval/seed');
    reste.value = await api.get<EvalReste>('/api/eval/reste');
    criteres.value = await api.get<EvalCriteres>('/api/eval/criteres');
  } catch {
    // Les paniers sont un confort : leur échec ne doit pas vider la page.
  }
}

onMounted(load);

function fail(e: unknown) {
  error.value = messageDe(e);
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

async function capture(kind: 'agendas' | 'sorties' | 'natures', id: number) {
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

/**
 * Les agendas que la recherche auto a dépouillés.
 *
 * Chargés à part et à la demande : c'est une requête d'agrégation sur tout
 * l'historique du scraper, et elle n'a rien à faire dans le chargement d'une
 * page qu'on ouvre dix fois par jour.
 */
const candidats = ref<EvalAgendaCandidat[]>([]);
const candidatsOuverts = ref(false);
const candidatsCharges = ref(false);

async function voirLesCandidats() {
  candidatsOuverts.value = !candidatsOuverts.value;
  if (!candidatsOuverts.value || candidatsCharges.value) return;
  try {
    const body = await api.get<{ candidats: EvalAgendaCandidat[] }>('/api/eval/agendas/candidats');
    candidats.value = body.candidats;
    candidatsCharges.value = true;
  } catch (e) {
    fail(e);
  }
}

async function adopter(candidat: EvalAgendaCandidat, pages: number) {
  try {
    await api.post('/api/eval/agendas', { url: candidat.url, pages });
    notice.value =
      'Agenda ajouté. Il part en file de capture ; une fois gelé, jouez un run ' +
      'de dépouillement — c’est lui qui relèvera ses liens.';
    candidatsCharges.value = false;
    await voirLesCandidats();
    candidatsOuverts.value = true;
    await load();
  } catch (e) {
    fail(e);
  }
}

// ── décrire une sortie sans quitter la ligne du lien ───────────────────
//
// Les faits **ne sont pas recopiés sur le lien** : ce formulaire écrit dans la
// sortie, le même objet que l'onglet d'à côté, par la même route. Une version
// précédente les portait vraiment sur le lien, en double de ce que la sortie
// disait déjà, et les deux divergeaient — c'est ce que « une sortie, une
// étiquette » a supprimé, et ça ne revient pas.
//
// Ce qui revient, c'est le **geste** : l'étage 4 se relit lien par lien, sur
// une page d'agenda, et devoir changer d'onglet pour décrire la sortie qu'on a
// sous les yeux est la raison pour laquelle personne ne le faisait.

const faits = ref<{
  sortieId: number;
  dateStart: string;
  dateEnd: string;
  postalCode: string;
  ageMin: number | null;
  ageMax: number | null;
  audience: EvalAudience | null;
} | null>(null);

function decrire(sortieId: number, sortie: EvalSortieFacts | null | undefined) {
  faits.value = {
    sortieId,
    dateStart: (sortie?.dateStart ?? '').slice(0, 10),
    dateEnd: (sortie?.dateEnd ?? '').slice(0, 10),
    postalCode: sortie?.postalCode ?? '',
    ageMin: sortie?.ageMin ?? null,
    ageMax: sortie?.ageMax ?? null,
    audience: sortie?.audience ?? null,
  };
}

/**
 * Enregistre les seuls champs de l'étage 4.
 *
 * La route fusionne au lieu de réécrire : saisir une date ici n'efface pas
 * l'illustration ni les fragments que la moisson avait remplis pour l'étage 5.
 */
async function enregistrerFaits() {
  const f = faits.value;
  if (!f) return;
  try {
    await api.patch(`/api/eval/sorties/${f.sortieId}`, {
      dateStart: f.dateStart || null,
      dateEnd: f.dateEnd || null,
      venuePostalCode: f.postalCode.trim() || null,
      ageMin: f.ageMin,
      ageMax: f.ageMax,
      audience: f.audience,
    });
    faits.value = null;
    await refreshOpen();
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

const totalJamaisRegardes = computed(() =>
  (reste.value?.jamaisRegardes ?? []).reduce((n, p) => n + p.manquants, 0),
);

/** La portée du run affiché, en une phrase. Vide s'il n'y a rien à dire. */
const scopeText = computed(() => phraseDePortee(openScope.value));

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
    // La sortie créée n'affirme rien : la décrire est le geste qui suit, et il
    // s'enchaîne ici plutôt que de se retrouver, plus tard, dans une liste de
    // dettes qu'on relit sans se rappeler de quelle page il s'agissait.
    const body = await api.post<{ sortie: { id: number } }>(
      `/api/eval/links/${linkId}/sortie`,
      {},
    );
    await refreshOpen();
    decrire(body.sortie.id, null);
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

/**
 * Mettre une page au corpus de l'étage 2, avec ce qu'elle est.
 *
 * La nature est posée dès l'ajout : cette table ne contient que des étiquettes.
 * Pour dire « je ne sais pas », on n'ajoute pas la page — un corpus qui
 * contiendrait des lignes sans réponse ferait croire à un travail fait.
 */
async function addNature() {
  const url = newNatureUrl.value.trim();
  if (!url) return;
  try {
    await api.post('/api/eval/natures', { url, nature: newNature.value });
    newNatureUrl.value = '';
    notice.value = 'Page ajoutée. Elle sera gelée par le worker.';
    await load();
  } catch (e) {
    fail(e);
  }
}

/** Corriger ce qu'on avait dit d'une page. */
async function setNature(id: number, nature: EvalPageNature) {
  try {
    await api.patch(`/api/eval/natures/${id}`, { nature });
    await load();
  } catch (e) {
    fail(e);
  }
}

async function removeNature(page: EvalNature) {
  if (!confirm(`Retirer « ${page.label || page.url} » du corpus de l’étage 2 ?`)) return;
  try {
    await api.delete(`/api/eval/natures/${page.id}`);
    await load();
  } catch (e) {
    fail(e);
  }
}

/**
 * D'où vient une étiquette de lien.
 *
 * La liste comptait une dette sans dire qui l'avait contractée. Or les deux
 * origines ne se relisent pas pareil : ce qu'on a cliqué soi-même, on sait
 * pourquoi ; ce qui vient de la modération a été tranché ailleurs, fiche en
 * main, et n'a jamais été revu ici.
 */
/**
 * Les paniers, et **le chemin exact** qui mène à chacun.
 *
 * Les libellés seuls n'ont jamais suffi à les faire comprendre. Ce qui manquait
 * n'était pas un mot plus juste : c'était de dire d'où vient la ligne — quel
 * run, quelle étape, quelle décision, et de qui.
 */
const PANIERS = [
  {
    cle: 'approuvees' as const,
    // Le geste qui le solde décide de l'onglet où il vit.
    groupe: 'sorties' as const,
    titre: 'Sorties publiées',
    publiee: true,
    ajoute: 'des sorties au corpus',
    chemin: [
      'Un run de <strong>production</strong> a lu une page et en a tiré une fiche.',
      'La fiche est partie en modération.',
      '<strong>Un humain l’a approuvée</strong> : elle est publiée sur le site.',
    ],
    pourquoi:
      'Leur étiquette est du travail humain déjà payé : le bouton suivant la reprend sans rien redemander.',
  },
  {
    cle: 'fiches' as const,
    // Le geste qui le solde décide de l'onglet où il vit.
    groupe: 'sorties' as const,
    titre: 'Étiqueter les sorties publiées',
    publiee: true,
    ajoute: 'l’étiquette de ces sorties',
    chemin: [
      'Une sortie du corpus vient d’une fiche approuvée…',
      '…mais personne n’a encore dit ce qu’elle affirme.',
      'On recopie les champs de la fiche publiée dans son étiquette.',
    ],
    pourquoi:
      'Une copie de champs, pas une interprétation. Les jours de représentation restent en dehors : le site ne les reçoit pas.',
  },
  {
    cle: 'abandonnees' as const,
    // Le geste qui le solde décide de l'onglet où il vit.
    groupe: 'sorties' as const,
    titre: 'Pages abandonnées à la lecture',
    publiee: false,
    ajoute: 'des sorties au corpus',
    chemin: [
      'Un run de <strong>production</strong> a retenu un lien au tri.',
      'L’étage 5 a téléchargé la page et en a extrait le texte.',
      'Le texte faisait <strong>moins de 200 caractères</strong> : la machine a écarté la page, seule.',
      'Aucune fiche n’a été produite. <strong>Aucun humain n’a rien vu.</strong>',
    ],
    pourquoi:
      'Si la page était vraiment vide, parfait. Si elle était pleine et que le texte n’a pas été extrait — JavaScript, encodage —, c’est un ratage que rien d’autre n’attrape.',
  },
  {
    cle: 'illisibles' as const,
    // Le geste qui le solde décide de l'onglet où il vit.
    groupe: 'sorties' as const,
    titre: 'Fiches refusées en modération',
    publiee: false,
    ajoute: 'des sorties au corpus',
    chemin: [
      'L’étage 5 a lu la page : le texte a passé les 200 caractères.',
      'L’étage 6 en a tiré une fiche — un appel au modèle, payé.',
      'La fiche est partie en modération.',
      '<strong>Un humain l’a refusée</strong> pour « description inutilisable ».',
    ],
    pourquoi:
      'Le point aveugle de l’étage 5 : la page n’était pas vide, elle a coûté une extraction, et son texte ne valait rien. Aucun signal automatique ne l’attrape.',
  },
  {
    cle: 'liens' as const,
    // Le geste qui le solde décide de l'onglet où il vit.
    groupe: 'agendas' as const,
    titre: 'Liens d’agenda déjà tranchés',
    publiee: true,
    ajoute: 'l’étiquette du lien, et la sortie décrite au bout',
    chemin: [
      'Une adresse a donné une sortie <strong>approuvée</strong> en modération.',
      'Cette même adresse figure dans le relevé d’un <strong>run du banc</strong> sur une page d’agenda du corpus.',
      'Aucune étiquette n’existe encore pour ce lien sur cette page.',
      'On pose « une sortie » sur le lien : un humain l’a déjà vérifiée, ailleurs.',
      'Et on <strong>crée la sortie au bout</strong>, avec ses faits recopiés de la fiche approuvée — sans quoi l’étage 4 n’aurait rien à quoi comparer.',
    ],
    pourquoi:
      'Reste à zéro tant qu’aucun run du banc n’a été joué sur vos agendas : c’est le run qui relève les liens. N’apporte que des positifs — il ne dira jamais qu’un lien n’est pas une sortie —, donc il raccourcit la relecture sans la remplacer. Les sorties créées partent en file de capture, comme celles du panier « Sorties publiées ».',
  },
];

// ── la chasse : peupler le corpus de l'étage 2 depuis un prompt ────────
//
// Étiqueter est le seul travail coûteux du banc, et ce corpus-ci le payait une
// adresse à la fois. Une chasse lance les recherches, ouvre ce qu'elles
// remontent, et précoche chaque page avec ce que l'étage 2 en pense.
//
// La précoche est un **affichage**, comme partout ailleurs sur cette page :
// rien n'entre au corpus tant que personne n'a cliqué. Et ce qu'on aura
// corrigé est gardé à part de ce qu'on aura laissé passer, sans quoi un corpus
// rempli en trois clics mesurerait l'étage 2 contre lui-même.

/**
 * Range les chasses et repose la précoche sur ce qui attend encore.
 *
 * Une candidate que l'étage 2 n'a pas su reconnaître reste **décochée** : lui
 * donner « agenda », comme le fait le pipeline, écrirait au corpus un repli
 * d'orchestration au lieu de ce que la page est.
 */
function poserLesChasses(rows: EvalHunt[]) {
  chasses.value = rows;
  choix.value = precocher(rows, choix.value);
}

async function lancerChasse() {
  const prompt = nouvelleChasse.value.prompt.trim();
  if (!prompt) return;
  const queries = nouvelleChasse.value.queries
    .split('\n')
    .map((q) => q.trim())
    .filter(Boolean);
  try {
    await api.post('/api/eval/hunts', {
      prompt,
      area: nouvelleChasse.value.area.trim() || 'Île-de-France',
      maxQueries: nouvelleChasse.value.maxQueries,
      maxPages: nouvelleChasse.value.maxPages,
      queries,
    });
    nouvelleChasse.value.prompt = '';
    nouvelleChasse.value.queries = '';
    notice.value =
      'Chasse mise en file : le worker la prendra à sa prochaine passe, ' +
      'après les captures et avant les runs.';
    await load();
  } catch (e) {
    fail(e);
  }
}

async function supprimerChasse(chasse: EvalHunt) {
  const attente = chasse.comptes.enAttente;
  const avertissement = attente ? `\n\n${attente} candidate(s) non triée(s) seront perdues.` : '';
  if (!confirm(`Oublier la chasse « ${chasse.prompt} » ?${avertissement}`)) return;
  try {
    await api.delete(`/api/eval/hunts/${chasse.id}`);
    notice.value = 'Chasse oubliée. Les pages déjà retenues restent au corpus.';
    await load();
  } catch (e) {
    fail(e);
  }
}

/** Cocher une nature, ou la décocher en recliquant dessus. */
function choisir(page: EvalHuntPage, nature: EvalPageNature) {
  choix.value = basculer(choix.value, page.id, nature);
}

function retenue(page: EvalHuntPage): boolean {
  return Boolean(choix.value[page.id]);
}

/**
 * Écrit au corpus les candidates cochées. Les autres **restent en attente**.
 *
 * Valider par paquets ne doit pas trancher à la place de personne : une page
 * décochée parce que l'étage 2 n'a pas su n'est pas une page qu'on a refusée.
 */
async function validerChasse(chasse: EvalHunt) {
  const prises = cochees(chasse, choix.value);
  if (!prises.length) return;
  await envoyer(
    chasse,
    prises.map((p) => ({ pageId: p.id, nature: choix.value[p.id] })),
  );
}

/** Écarte tout ce qui reste : la dette de la chasse tombe à zéro. */
async function ecarterRestantes(chasse: EvalHunt) {
  const restants = restantes(chasse, choix.value);
  if (!restants.length) return;
  if (!confirm(`Écarter ${restants.length} candidate(s) ? Leur HTML gelé sera effacé.`)) return;
  await envoyer(
    chasse,
    restants.map((p) => ({ pageId: p.id, nature: null })),
  );
}

async function ecarterUne(chasse: EvalHunt, page: EvalHuntPage) {
  await envoyer(chasse, [{ pageId: page.id, nature: null }]);
}

async function envoyer(
  chasse: EvalHunt,
  decisions: { pageId: number; nature: EvalPageNature | null }[],
) {
  try {
    const body = await api.post<{ retenues: number; ecartees: number; doublons: string[] }>(
      `/api/eval/hunts/${chasse.id}/decide`,
      { decisions },
    );
    notice.value =
      `${body.retenues} page(s) au corpus, ${body.ecartees} écartée(s)` +
      (body.doublons.length ? `, ${body.doublons.length} déjà au corpus.` : '.');
    await load();
  } catch (e) {
    fail(e);
  }
}

/** Ce que l'étage 2 a dit d'une candidate, en une ligne lisible. */
function precoche(page: EvalHuntPage): string {
  if (page.error) return `injoignable : ${page.error}`;
  if (!page.proposed) return `indécis — ${page.detail || 'rien de déclaré'}`;
  return `${EVAL_NATURE_LABELS[page.proposed]} — ${page.detail}`;
}

/** La part du corpus qui ne vient pas de la brique, en pourcentage. */
const independance = computed(() => {
  const part = souche.value?.independance;
  return part === null || part === undefined ? '—' : `${Math.round(part * 100)} %`;
});

// ── peupler le corpus depuis ce que le pipeline a déjà fait ────────────

async function pour(bucket: 'approuvees' | 'abandonnees' | 'illisibles' | 'liens' | 'fiches') {
  try {
    const body = await api.post<{
      added: number;
      creees?: number;
      decrites?: number;
      rattaches?: number;
    }>(
      '/api/eval/seed',
      { bucket, limit: 25 },
    );
    // Les rattachements sont dits, et pas seulement faits : ce sont des liens
    // qui comptaient *indécidables* et qui vont se mettre à peser dans le
    // rappel de l'étage 4. Un chiffre qui bouge sans qu'on sache pourquoi est
    // ce qui fait douter d'un banc.
    notice.value =
      `${body.added} entrée(s) ajoutée(s) au corpus.` +
      (body.creees
        ? ` ${body.creees} sortie(s) créée(s) et décrite(s) depuis leur fiche approuvée.`
        : '') +
      (body.decrites
        ? ` ${body.decrites} sortie(s) qui n’affirmaient rien viennent d’être décrites.`
        : '') +
      (body.rattaches
        ? ` ${body.rattaches} lien(s) d’agenda viennent d’y être rattachés : ils comptaient` +
          ' indécidables pour l’étage 4, ils comptent maintenant.'
        : '');
    await load();
  } catch (e) {
    fail(e);
  }
}

// ── les trois onglets ──────────────────────────────────────────────────
//
// Un onglet par corpus, et le corpus décide — pas la longueur des sections.
// Les trois n'étiquettent pas la même chose, ne se remplissent pas du même
// geste, et ne se relisent jamais ensemble : les empiler sur une seule page
// obligeait à faire défiler deux cents lignes d'agendas pour atteindre le
// tableau des sorties.

type Onglet = 'pages' | 'agendas' | 'sorties';

const ONGLETS_CONNUS: Onglet[] = ['pages', 'agendas', 'sorties'];

const route = useRoute();
const router = useRouter();

/**
 * L'onglet ouvert, **dans l'adresse**.
 *
 * Pas seulement pour le confort : un rechargement après avoir étiqueté vingt
 * liens ramenait sur le premier onglet, et c'est le genre de détail qui fait
 * qu'on cesse d'utiliser une console.
 */
const onglet = ref<Onglet>(
  ONGLETS_CONNUS.includes(route.query.onglet as Onglet) ? (route.query.onglet as Onglet) : 'pages',
);

function choisirOnglet(cle: Onglet) {
  onglet.value = cle;
  void router.replace({ query: { ...route.query, onglet: cle } });
}

/**
 * Les trois onglets, et **tous les compteurs du corpus**.
 *
 * Ils vivaient au-dessus, dans une grille de cinq tuiles, qui répétait mot pour
 * mot ce que les onglets disent maintenant. Deux fois le même chiffre sur un
 * écran, c'est un de trop — et c'était la moitié du haut de page.
 */
const ONGLETS = computed(() => [
  {
    cle: 'pages' as const,
    titre: 'Étage 2 — ce qu’une page est',
    compte: `${corpusSize.value.natures} page(s)`,
    quoi: 'la chasse, et les natures étiquetées',
  },
  {
    cle: 'agendas' as const,
    titre: 'Étages 3 et 4 — les liens d’un agenda',
    compte:
      `${corpusSize.value.agendas} agenda(s) · ${corpusSize.value.pages} page(s) gelée(s)` +
      ` · ${corpusSize.value.links} lien(s) étiqueté(s)`,
    quoi: 'ce qu’un relevé retient, et ce qu’il laisse',
  },
  {
    cle: 'sorties' as const,
    titre: 'Étages 5 et 6 — ce qu’une page dit',
    compte: `${corpusSize.value.sorties} sortie(s) · ${corpusSize.value.sortieLabels} étiquetée(s)`,
    quoi: 'le texte, l’image, et les champs de la fiche',
  },
]);

/** Les paniers qui se soldent dans un onglet donné. */
function paniersDe(groupe: 'agendas' | 'sorties') {
  return PANIERS.filter((p) => p.groupe === groupe);
}

/**
 * Aller voir la sortie vers laquelle un lien d'agenda mène.
 *
 * Elle vit dans un autre onglet : une ancre `#sortie-12` ne pointait plus sur
 * rien dès que la page s'est découpée. On change d'onglet, puis on va la
 * chercher une fois qu'elle existe — sans quoi le navigateur défilerait vers
 * un élément que Vue n'a pas encore posé.
 */
async function allerALaSortie(sortieId: number) {
  choisirOnglet('sorties');
  await nextTick();
  const cible = document.getElementById(`sortie-${sortieId}`);
  cible?.scrollIntoView({ block: 'center' });
  cible?.classList.add('vise');
  window.setTimeout(() => cible?.classList.remove('vise'), 2000);
}

const corpusSize = computed(() => ({
  natures: natures.value.length,
  agendas: agendas.value.length,
  pages: agendas.value.reduce((n, a) => n + (a.pagesCaptured ?? 0), 0),
  links: agendas.value.reduce((n, a) => n + (a.labels ?? 0), 0),
  sorties: sorties.value.length,
  // Les sorties dont l'étiquette affirme au moins quelque chose. Compter les
  // champs n'aurait pas de sens : ils ne pèsent pas le même travail.
  sortieLabels: sorties.value.filter(
    (r) => r.couverture.tri.faits + r.couverture.lecture.faits + r.couverture.extraction.faits > 0,
  ).length,
}));
</script>

<template>
  <div class="container page">
    <h1>Banc d’évaluation — le corpus</h1>
    <nav class="row" style="gap: 1rem; margin-bottom: 1rem">
      <RouterLink to="/admin/evaluation">Corpus et étiquettes</RouterLink>
      <RouterLink to="/admin/evaluation/mesures">Mesures</RouterLink>
      <RouterLink to="/admin/evaluation/comparer">Comparer</RouterLink>
    </nav>

    <p class="muted">
      Une étiquette dit ce qu’une page <strong>contient</strong>, jamais si une
      brique a eu raison. C’est ce qui la fait vivre des années : « la page
      annonce 8 € » vaut pour toujours, « le tarif rendu est juste » périmait au
      premier changement de prompt. La mesure, elle, est sur
      <RouterLink to="/admin/evaluation/mesures">Mesures</RouterLink>.
    </p>

    <p v-if="notice" class="notice">{{ notice }}</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="muted">Chargement…</p>

    <!-- ── Les trois corpus, un onglet chacun ─────────────────────────── -->
    <!--
      La page tenait tout d'un seul tenant : peupler, les dettes, la chasse,
      les natures, les agendas, les sorties. Ça se lisait tant que le banc
      était petit, et plus du tout une fois qu'il a servi — on cherchait le
      tableau des sorties en faisant défiler deux cents lignes d'agendas.

      Le découpage suit les **trois corpus**, et pas la commodité de
      l'affichage : chacun étiquette une question différente, se remplit d'un
      geste différent, et ne se relit jamais en même temps qu'un autre.

      Les paniers et les dettes se répartissent d'après **le geste qui les
      solde**, et non d'après la liste où ils étaient rangés : « des liens déjà
      tranchés » pose des étiquettes de lien, donc il vit avec les agendas ;
      « la sortie n'affirme rien » se solde en cliquant « Étiqueter » dans le
      tableau des sorties, donc il vit là. Les quatre paniers qui ajoutent des
      sorties, eux, restent ensemble : c'est leur **équilibre** qui est la
      question, et les séparer reviendrait à cacher qu'on n'a repris que les
      réussites.
    -->
    <nav class="onglets" aria-label="Les trois corpus">
      <button
        v-for="o in ONGLETS"
        :key="o.cle"
        class="onglet"
        :class="{ on: onglet === o.cle }"
        :aria-current="onglet === o.cle ? 'page' : undefined"
        @click="choisirOnglet(o.cle)"
      >
        <span class="onglet-titre">{{ o.titre }}</span>
        <span class="onglet-compte">{{ o.compte }}</span>
        <span class="onglet-quoi">{{ o.quoi }}</span>
      </button>
    </nav>

    <!-- ═══ Onglet 1 — l’étage 2 : ce qu’une page est ═══════════════════ -->
    <section v-if="onglet === 'pages'">
      <!-- ── La chasse ──────────────────────────────────────────────────── -->
      <h2>Chasse — peupler l’étage 2 depuis un prompt</h2>
      <p class="muted small">
        Une chasse lance les recherches de l’étage 1, ouvre <strong>toutes</strong>
        les pages qu’elles remontent, et marque chacune avec ce que l’étage 2 en
        pense. Il ne reste qu’à corriger ce qui est faux. Le HTML est gelé au
        passage : la page qu’un run rejouera est exactement celle sur laquelle la
        précoche a été faite, et non celle que le site servira demain.
      </p>
      <p class="muted small">
        Une page que l’étage 2 <strong>ne sait pas reconnaître</strong> arrive
        décochée, et c’est voulu : le pipeline, lui, la traite en agenda, mais
        c’est une décision d’orchestration. L’écrire au corpus y mettrait ce que
        le pipeline <em>fait</em> au lieu de ce que la page <em>est</em> — soit
        exactement ce qu’on cherche à mesurer.
      </p>

      <div class="card chasse-form">
        <label class="chasse-champ">
          <span>Ce qu’on cherche</span>
          <input
            v-model="nouvelleChasse.prompt"
            type="text"
            maxlength="300"
            placeholder="spectacles jeune public en Seine-Saint-Denis à la Toussaint"
          />
        </label>
        <div class="row add">
          <label class="chasse-champ">
            <span>Zone</span>
            <input v-model="nouvelleChasse.area" type="text" maxlength="120" />
          </label>
          <label class="chasse-champ court">
            <span>Requêtes</span>
            <input v-model.number="nouvelleChasse.maxQueries" type="number" min="1" max="10" />
          </label>
          <label class="chasse-champ court">
            <span>Pages au plus</span>
            <input v-model.number="nouvelleChasse.maxPages" type="number" min="1" max="100" />
          </label>
          <button class="btn" @click="lancerChasse()">Lancer la chasse</button>
        </div>
        <details>
          <summary class="muted small">Imposer les requêtes plutôt que les faire formuler</summary>
          <p class="muted small">
            Une par ligne. Les fournir fige la chasse — donc la rend comparable
            d’une semaine sur l’autre — et évite le petit appel qui les formule.
          </p>
          <textarea
            v-model="nouvelleChasse.queries"
            rows="3"
            placeholder="agenda sorties enfants Seine-Saint-Denis octobre"
          ></textarea>
        </details>
      </div>

      <div v-for="chasse in chasses" :key="chasse.id" class="card entry">
        <div class="entry-head">
          <strong>{{ chasse.prompt }}</strong>
          <span class="badge">{{ EVAL_HUNT_STATUS_LABELS[chasse.status] }}</span>
          <span class="muted small">
            {{ chasse.comptes.total }} candidate(s), {{ chasse.comptes.enAttente }} en attente,
            {{ chasse.comptes.retenues }} au corpus
            <template v-if="chasse.comptes.indecises">
              · {{ chasse.comptes.indecises }} que l’étage 2 n’a pas su reconnaître
            </template>
            <template v-if="chasse.overCap">
              · {{ chasse.overCap }} au-delà du plafond, jamais ouverte(s)
            </template>
          </span>
          <span class="spacer"></span>
          <span class="muted small">{{ chasse.costUsd }} $</span>
          <button class="linklike" @click="supprimerChasse(chasse)">Oublier</button>
        </div>
        <p v-if="chasse.error" class="error small">{{ chasse.error }}</p>
        <p v-if="chasse.ranQueries.length" class="muted small">
          Requêtes lancées : {{ chasse.ranQueries.join(' · ') }}
        </p>

        <div v-if="enAttente(chasse).length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Page</th>
                <th>Ce que l’étage 2 en dit</th>
                <th>C’est…</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="page in enAttente(chasse)" :key="page.id" :class="{ off: !retenue(page) }">
                <td>
                  <div class="link-text">{{ page.title || page.url }}</div>
                  <a :href="page.url" target="_blank" class="muted small">{{ page.url }}</a>
                  <div v-if="page.foundUrl" class="muted small">
                    trouvée en <code>{{ page.foundUrl }}</code>, lue en français
                  </div>
                  <div class="muted small">
                    {{ page.links }} lien(s), dont {{ page.dated }} voisinent une date
                    <template v-if="page.archived">
                      ·
                      <a :href="`/api/eval/hunts/pages/${page.id}/html`" target="_blank">HTML gelé</a>
                    </template>
                    <template v-else>· sans archive : elle passera par la file de capture</template>
                  </div>
                </td>
                <td class="small">
                  {{ precoche(page) }}
                  <div class="muted small">
                    <template v-if="page.signal">signal : {{ page.signal }}</template>
                    <template v-if="page.confidence"> ({{ page.confidence }})</template>
                    <template v-if="page.asked"> · tranché par {{ page.asked }}</template>
                  </div>
                </td>
                <td>
                  <div class="chips">
                    <button
                      v-for="n in NATURES"
                      :key="n"
                      class="chip"
                      :class="{ on: choix[page.id] === n }"
                      :title="EVAL_NATURE_HINTS[n]"
                      @click="choisir(page, n)"
                    >
                      {{ EVAL_NATURE_LABELS[n] }}
                    </button>
                  </div>
                </td>
                <td>
                  <button class="linklike" @click="ecarterUne(chasse, page)">Écarter</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="enAttente(chasse).length" class="row add chasse-valide">
          <button class="btn" :disabled="!cochees(chasse, choix).length" @click="validerChasse(chasse)">
            Mettre au corpus les {{ cochees(chasse, choix).length }} cochée(s)
          </button>
          <button class="btn ghost" @click="ecarterRestantes(chasse)">
            Écarter les {{ enAttente(chasse).length - cochees(chasse, choix).length }} restante(s)
          </button>
          <span class="muted small">
            dont <strong>{{ corrections(chasse, choix) }}</strong> correction(s) de ce que l’étage 2
            proposait. C’est le seul chiffre qui dise si cette chasse apprend quelque chose au
            banc : zéro correction, et le corpus recopie la brique qu’il mesure.
          </span>
        </div>
        <p v-else-if="chasse.status === 'DONE'" class="muted small">
          Plus rien à trier. {{ chasse.comptes.retenues }} page(s) sont entrées au corpus.
        </p>
      </div>

      <!-- ── Ce qu'une page est ─────────────────────────────────────────── -->
      <h2>Pages — étage 2 : ce qu’une page est</h2>
      <p class="muted small">
        La découverte rend des adresses sans rien en dire. L’étage 2 décide où
        chacune va — <strong>en lisant la page</strong>, d’où le HTML gelé. Et
        l’erreur n’y est pas symétrique : prendre une sortie pour un agenda coûte
        un appel de tri et se rattrape tout seul ; prendre un agenda pour une
        sortie coûte <strong>tous ses liens</strong>, sans rattrapage.
      </p>
      <p class="muted small">
        Mettez-y aussi des <strong>contre-exemples</strong> — une page d’accueil,
        un article, une billetterie. Sans eux, on ne mesurerait que les cas où
        l’étage 2 a déjà raison.
      </p>
      <div class="row add">
        <input v-model="newNatureUrl" type="url" placeholder="https://exemple.fr/une-page" />
        <select v-model="newNature" :title="EVAL_NATURE_HINTS[newNature]">
          <option v-for="n in NATURES" :key="n" :value="n">{{ EVAL_NATURE_LABELS[n] }}</option>
        </select>
        <button class="btn" @click="addNature()">Ajouter au corpus</button>
      </div>

      <p v-if="souche && souche.total" class="muted small">
        <strong>{{ independance }}</strong> de ce corpus ne vient pas de l’étage 2 :
        {{ souche.saisies }} saisie(s) et {{ souche.corriges }} correction(s), contre
        {{ souche.nonContredits }} précoche(s) laissée(s) passer. C’est le chiffre à
        regarder avant la taille : une mesure calculée surtout sur des étiquettes
        non contredites vérifie que l’étage 2 fait ce qu’il fait, et elle sera
        flatteuse par construction.
      </p>

      <div v-if="natures.length" class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Page</th>
              <th>Capture</th>
              <th>C’est…</th>
              <th>Étiquette</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="page in natures" :key="page.id">
              <td>
                <div class="link-text">{{ page.label || page.url }}</div>
                <a :href="page.url" target="_blank" class="muted small">{{ page.url }}</a>
              </td>
              <td class="small">
                {{ EVAL_CAPTURE_LABELS[page.capture] }}
                <button
                  v-if="page.capture !== 'CAPTURED'"
                  class="linklike"
                  @click="capture('natures', page.id)"
                >
                  geler
                </button>
                <a
                  v-else-if="page.archived"
                  :href="`/api/eval/natures/${page.id}/html`"
                  target="_blank"
                >
                  HTML
                </a>
                <div v-if="page.captureError" class="error small">{{ page.captureError }}</div>
              </td>
              <td>
                <div class="chips">
                  <button
                    v-for="n in NATURES"
                    :key="n"
                    class="chip"
                    :class="{ on: page.nature === n }"
                    :title="EVAL_NATURE_HINTS[n]"
                    @click="setNature(page.id, n)"
                  >
                    {{ EVAL_NATURE_LABELS[n] }}
                  </button>
                </div>
              </td>
              <td class="small">
                <span
                  class="provenance"
                  :class="page.origin === 'NON_CONTREDIT' ? 'banc' : 'publiee'"
                  :title="EVAL_NATURE_ORIGIN_HINTS[page.origin]"
                >
                  {{ EVAL_NATURE_ORIGIN_LABELS[page.origin] }}
                </span>
                <div v-if="page.proposed && page.proposed !== page.nature" class="muted small">
                  l’étage 2 disait « {{ EVAL_NATURE_LABELS[page.proposed] }} »
                </div>
              </td>
              <td>
                <button class="linklike" @click="removeNature(page)">Retirer</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="muted small">
        Rien encore. Ajoutez quelques pages de chaque sorte — y compris des
        contre-exemples.
      </p>

    </section>

    <!-- ═══ Onglet 2 — les étages 3 et 4 : les liens d’un agenda ════════ -->
    <section v-else-if="onglet === 'agendas'">
      <!-- ── Peupler : le seul panier qui pose des étiquettes de lien ───── -->
      <h2>Peupler depuis ce que le pipeline a déjà fait</h2>
      <p class="muted small">
        Ce panier-ci n’ajoute <strong>aucune sortie</strong> : il pose des
        étiquettes de lien sur les agendas du corpus, à partir d’adresses qu’un
        humain a déjà tranchées ailleurs, en modération. Les paniers qui
        ajoutent des sorties sont dans l’onglet
        <button class="linklike" @click="choisirOnglet('sorties')">
          Étages 5 et 6
        </button>.
      </p>
      <div v-if="seed" class="paniers">
        <div v-for="panier in paniersDe('agendas')" :key="panier.cle" class="panier">
          <button
            class="btn ghost"
            :disabled="!seed[panier.cle]"
            @click="pour(panier.cle)"
          >
            {{ panier.titre }} ({{ seed[panier.cle] }})
          </button>
          <div class="panier-quoi">
            <span class="provenance" :class="panier.publiee ? 'publiee' : 'banc'">
              {{ panier.publiee ? 'sortie publiée' : 'jamais publiée' }}
            </span>
            <strong class="small">ajoute : {{ panier.ajoute }}</strong>
          </div>
          <!--
            Les étapes exactes qui mènent à ce panier. Trois fois de suite ces
            libellés n'ont pas suffi : ce qui manquait n'était pas un mot plus
            juste, c'était le chemin.
          -->
          <ol class="panier-chemin">
            <li v-for="(etape, i) in panier.chemin" :key="i" v-html="etape"></li>
          </ol>
          <p class="muted small panier-pourquoi">{{ panier.pourquoi }}</p>
        </div>
      </div>
      <!-- ── Ce qui reste à la main, côté liens ─────────────────────────── -->
      <h2>Ce qui reste à la main</h2>
      <p class="muted small">
        La modération paie la <strong>précision</strong> : parmi ce que le
        scraper a proposé, ce qu’un humain a validé. Elle ne paiera jamais le
        <strong>rappel</strong> — ce qu’il a raté n’apparaît pas dans ce qu’il a
        proposé. Ces deux listes-ci se soldent <strong>dans cet onglet</strong> :
        en ouvrant un agenda, et en cliquant.
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
        <!--
          Deux dettes, et elles ne se soldent pas du même geste — c'est aussi ce
          qui décide de leur onglet. Celle-ci se solde ici, en ouvrant un
          agenda ; la troisième — « la sortie existe mais n'affirme rien » — se
          solde dans le tableau des sorties, et vit donc là-bas. Les mêler sous
          un seul compte obligeait à ouvrir chaque ligne pour savoir laquelle on
          avait sous les yeux.
        -->
        <div class="reste-ligne">
          <strong>{{ reste.aCreer.length }}</strong>
          lien(s) « une sortie » dont la sortie <strong>n’existe pas</strong> au corpus
          <p class="muted small">
            Quelqu’un a dit que ce lien mène à une sortie, mais rien ne la
            représente au banc : il n’y a aucun objet à décrire. Le geste est de
            <strong>la créer</strong>.
          </p>
          <ul v-if="reste.aCreer.length" class="reste-detail">
            <li v-for="lien in reste.aCreer.slice(0, 5)" :key="lien.id">
              <a :href="lien.url" target="_blank">{{ lien.text || lien.url }}</a>
              <span class="muted small">— {{ venueDeLEtiquette(lien.origin) }}</span>
            </li>
          </ul>
        </div>
      </div>
      <!-- ── Les agendas ────────────────────────────────────────────────── -->
      <h2>Agendas — étages 3 et 4</h2>
      <!--
        Coller une adresse marche, et c'est la mauvaise façon de commencer : un
        agenda choisi au hasard n'a aucun recouvrement avec ce que la modération
        a déjà tranché, donc rien à reprendre, donc tout à étiqueter à la main —
        et en attendant, l'étage 4 mesure zéro. Le panier ci-dessous part de ce
        que la production a réellement dépouillé.
      -->
      <p class="muted small">
        <button class="linklike" @click="voirLesCandidats()">
          {{ candidatsOuverts ? 'Masquer' : 'Choisir un agenda que la recherche auto a dépouillé' }}
        </button>
        — ceux-là ont, par construction, des liens qu’un modérateur a déjà jugés.
      </p>

      <div v-if="candidatsOuverts" class="card candidats">
        <p class="muted small">
          Le rendement compte ce que cet agenda a rendu <strong>alors</strong> ;
          la page qu’on gèlera est celle d’<strong>aujourd’hui</strong>. Les
          sorties expirent et les agendas tournent : d’où la colonne « 3 mois »,
          la seule qui ait une chance d’être encore sur la page. Le vrai
          recouvrement ne se connaît qu’après la capture et un run de
          dépouillement.
        </p>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Agenda</th>
                <th class="num" title="Pages distinctes que la production a tirées de cet agenda.">
                  Pages
                </th>
                <th class="num" title="Pages approuvées par un modérateur : autant d’étiquettes de lien déjà payées.">
                  Approuvées
                </th>
                <th class="num" title="Approuvées ces trois derniers mois.">3 mois</th>
                <th class="num" title="Pages refusées en modération : elles ne donnent aucune étiquette, mais elles disent que l’agenda produit du bruit.">
                  Refusées
                </th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in candidats" :key="c.url" :class="{ off: c.dejaAuCorpus }">
                <td>
                  <a :href="c.url" target="_blank" class="link-text">{{ c.url }}</a>
                  <div v-if="c.query" class="muted small">remonté par « {{ c.query }} »</div>
                </td>
                <td class="num">{{ c.pages }}</td>
                <td class="num">{{ c.approuvees }}</td>
                <td class="num"><strong>{{ c.recentes }}</strong></td>
                <td class="num">{{ c.refusees }}</td>
                <td>
                  <span v-if="c.dejaAuCorpus" class="muted small">déjà au corpus</span>
                  <button v-else class="linklike" @click="adopter(c, newAgendaPages)">
                    Ajouter ({{ newAgendaPages }} page(s))
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="candidatsCharges && !candidats.length" class="muted small">
          Aucun agenda dépouillé n’a encore donné de sortie approuvée. La
          filiation n’est journalisée que depuis qu’elle est recopiée à la
          clôture des runs : les exécutions antérieures n’en portent pas. Elle
          se rattrape sans rien relire du web — leur journal la contient encore
          tant qu’il n’a pas été purgé : <code>npm run db:backfill-provenance</code>
          sur le serveur, puis <code>-- --apply</code>.
        </p>
      </div>

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
            {{ agenda.pagesCaptured }} page(s) gelée(s) ·
            {{ agenda.labels }} / {{ agenda.releves }} lien(s) étiqueté(s)
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
        <!--
          D'où vient cette entrée. Les agendas enrôlés par la clôture d'un run
          arrivent seuls, en nombre, et sans ça rien ne les distinguait de ceux
          qu'on a choisis : une liste qui grandit toute seule sans dire pourquoi
          est exactement ce qui fait douter d'un corpus.
        -->
        <p v-if="agenda.note" class="muted small">{{ agenda.note }}</p>
        <!--
          Où en est cet agenda, et ce qu'il attend. La chaîne — geler, jouer un
          run de dépouillement, étiqueter — est une dépendance réelle que rien
          n'écrivait : la sauter ne produit aucune erreur, seulement un zéro
          plus loin, qu'on attribue à la brique.
        -->
        <p class="etape" :class="agenda.etape.toLowerCase()">
          <strong>{{ EVAL_ETAPE_LABELS[agenda.etape] }}</strong>
          <span class="muted small">{{ EVAL_ETAPE_SUITE[agenda.etape] }}</span>
        </p>

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
                <code v-if="pageSuivanteTrouvee(page)">{{ pageSuivanteTrouvee(page) }}</code>
                <em v-else>rien</em>
              </span>
              <button class="linklike" @click="labelNext(page.id, pageSuivanteTrouvee(page))">
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
            <div v-if="motifsDeRejet(page).length" class="row reasons">
              <span class="muted small">Écartés par le relevé :</span>
              <span v-for="[reason, count] in motifsDeRejet(page)" :key="reason" class="reason">
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
                <tr v-for="row in apparierReleve(page)" :key="row.result?.url ?? row.label?.url">
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
                        La date, le lieu et l'âge se saisissent ici, et ils
                        n'appartiennent toujours pas au lien : ce formulaire
                        écrit dans la **sortie**, le même objet que l'onglet d'à
                        côté, par la même route. Une version précédente les
                        portait vraiment sur le lien, en double de ce que le
                        corpus disait déjà, et les deux divergeaient — c'est ce
                        que « une sortie, une étiquette » a supprimé, et ça ne
                        revient pas.
                        Ce qui revient, c'est le geste : l'étage 4 se relit lien
                        par lien, et devoir changer d'onglet pour décrire la
                        sortie qu'on a sous les yeux est la raison pour laquelle
                        personne ne le faisait.
                      -->
                      <div v-else class="hints">
                        <button class="linklike" @click="decrire(row.label.sortieId!, row.label.sortie)">
                          décrire
                        </button>
                        <button class="linklike" @click="allerALaSortie(row.label.sortieId!)">
                          voir la sortie
                        </button>
                        <span class="muted small">{{ resumeSortie(row.label.sortie) }}</span>
                      </div>

                      <!-- Le formulaire de l'étage 4, et rien d'autre : trois
                           faits, ceux que le tri regarde. -->
                      <div v-if="faits && faits.sortieId === row.label.sortieId" class="faits-ligne-inline">
                        <div class="row faits-ligne">
                          <label class="hint">
                            <span class="muted small">du</span>
                            <input v-model="faits.dateStart" type="date" />
                          </label>
                          <label class="hint">
                            <span class="muted small">au</span>
                            <input
                              v-model="faits.dateEnd"
                              type="date"
                              title="Vide sur une date unique."
                            />
                          </label>
                          <label class="hint">
                            <span class="muted small">à</span>
                            <input
                              v-model="faits.postalCode"
                              type="text"
                              inputmode="numeric"
                              size="6"
                              placeholder="75012"
                              title="Cinq chiffres. Une ville en toutes lettres ne se compare à aucun département."
                            />
                          </label>
                          <label class="hint">
                            <span class="muted small">de</span>
                            <input v-model.number="faits.ageMin" type="number" min="0" max="120" size="3" />
                            <span class="muted small">à</span>
                            <input v-model.number="faits.ageMax" type="number" min="0" max="120" size="3" />
                            <span class="muted small">ans</span>
                          </label>
                        </div>
                        <div class="chips">
                          <button
                            v-for="a in AUDIENCES"
                            :key="a"
                            class="chip tiny"
                            :class="{ on: faits.audience === a }"
                            :title="EVAL_AUDIENCE_HINTS[a]"
                            @click="faits.audience = faits.audience === a ? null : a"
                          >
                            {{ EVAL_AUDIENCE_LABELS[a] }}
                          </button>
                        </div>
                        <div class="row">
                          <button class="btn" @click="enregistrerFaits()">Enregistrer</button>
                          <button class="linklike" @click="faits = null">Annuler</button>
                          <span class="muted small">
                            Écrit dans la sortie. L’illustration et les fragments de
                            l’étage 5 ne sont pas touchés.
                          </span>
                        </div>
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

    </section>

    <!-- ═══ Onglet 3 — les étages 5 et 6 : ce qu’une page dit ═══════════ -->
    <section v-else>
      <!-- ── Peupler ────────────────────────────────────────────────────── -->
      <h2>Peupler depuis ce que le pipeline a déjà fait</h2>
      <p class="muted small">
        Chaque panier reprend ce que votre pipeline a déjà fait, et chacun dit
        d’où il vient. L’équilibre entre eux est la question : ne prendre que les
        réussites mesurerait la brique sur ses propres succès — on lirait 96 % de
        textes corrects, et ça ne voudrait rien dire.
      </p>
      <div v-if="seed" class="paniers">
        <div v-for="panier in paniersDe('sorties')" :key="panier.cle" class="panier">
          <button
            class="btn ghost"
            :disabled="!seed[panier.cle]"
            @click="pour(panier.cle)"
          >
            {{ panier.titre }} ({{ seed[panier.cle] }})
          </button>
          <div class="panier-quoi">
            <span class="provenance" :class="panier.publiee ? 'publiee' : 'banc'">
              {{ panier.publiee ? 'sortie publiée' : 'jamais publiée' }}
            </span>
            <strong class="small">ajoute : {{ panier.ajoute }}</strong>
          </div>
          <!--
            Les étapes exactes qui mènent à ce panier. Trois fois de suite ces
            libellés n'ont pas suffi : ce qui manquait n'était pas un mot plus
            juste, c'était le chemin.
          -->
          <ol class="panier-chemin">
            <li v-for="(etape, i) in panier.chemin" :key="i" v-html="etape"></li>
          </ol>
          <p class="muted small panier-pourquoi">{{ panier.pourquoi }}</p>
        </div>

        <div class="panier">
          <button
            class="btn ghost danger"
            :disabled="!corpusSize.sorties"
            @click="viderSorties()"
          >
            Vider les sorties
          </button>
          <p class="muted small panier-pourquoi">
            Remet le corpus des sorties à zéro. Tout ce qui vient du site se
            remoissonne avec les boutons ci-dessus ; ce qui a été saisi à la main,
            non — le compte rendu le dit avant.
          </p>
        </div>
      </div>
      <!-- ── Ce qui reste à la main, côté sorties ───────────────────────── -->
      <h2>Ce qui reste à la main</h2>
      <p class="muted small">
        Une sortie au corpus dont l’étiquette est vide ne dit rien : l’étage 4
        n’a rien à quoi la comparer, et elle compte <em>indécidable</em> — ni
        pour, ni contre. C’est la dette qui se solde ici, en étiquetant.
      </p>
      <div v-if="reste" class="card reste">
        <div class="reste-ligne">
          <strong>{{ reste.aDecrire.length }}</strong>
          lien(s) dont la sortie <strong>existe mais n’affirme rien</strong>
          <p class="muted small">
            L’objet est au corpus, son étiquette est vide : ni date, ni code
            postal, ni âge, ni public. L’étage 4 n’a rien à quoi la comparer, elle
            compte <em>indécidable</em> — ni pour ni contre le modèle. Le geste est
            de <strong>la décrire</strong>, ou de laisser le bouton
            « Étiqueter les sorties publiées » le faire quand elle vient du site.
          </p>
          <ul v-if="reste.aDecrire.length" class="reste-detail">
            <li v-for="lien in reste.aDecrire.slice(0, 5)" :key="lien.id">
              <a :href="lien.url" target="_blank">{{ lien.text || lien.url }}</a>
              <span class="muted small">— {{ venueDeLEtiquette(lien.origin) }}</span>
            </li>
          </ul>
        </div>
      </div>
      <!-- ── Les pages de lecture ───────────────────────────────────────── -->
      <h2>Pages — étages 5 et 6</h2>
      <div class="row add">
        <input v-model="newSortieUrl" type="url" placeholder="https://exemple.fr/spectacle" />
        <button class="btn" @click="addSortie()">Ajouter au corpus</button>
      </div>

      <!--
        Ce que chaque compteur compte, en clair. La liste vient du serveur : deux
        compteurs écrits à la main ont menti, dont un qui annonçait « 6/6 » sur
        six champs choisis arbitrairement quand l'étage en juge douze.
      -->
      <p v-if="criteres" class="muted small">
        <button class="linklike" @click="criteresOuverts = !criteresOuverts">
          {{ criteresOuverts ? 'Masquer' : 'Que comptent les colonnes Étage 4, 5 et 6 ?' }}
        </button>
      </p>
      <div v-if="criteres && criteresOuverts" class="card criteres">
        <div v-for="etage in criteres.etages" :key="etage.etage" class="criteres-bloc">
          <h4>
            Étage {{ etage.etage }} — {{ etage.nom }}
            <span class="muted small">{{ etage.criteres.length }} critère(s)</span>
          </h4>
          <ol>
            <li v-for="critere in etage.criteres" :key="critere.libelle">
              {{ critere.libelle }}
              <span class="muted small">
                — {{ critere.champs.join(' ou ') }}
              </span>
            </li>
          </ol>
        </div>
        <p class="muted small">
          Un critère est compté dès qu’<strong>un</strong> de ses champs figure
          dans l’étiquette — même vide, puisque « la page n’en dit rien » est une
          étiquette de plein droit. Plusieurs champs pour un critère veut dire
          qu’un seul suffit à y répondre : l’un ou l’autre, jamais deux fois.
        </p>
      </div>

      <div class="table-wrap card">
        <table>
          <thead>
            <tr>
              <th>Page</th>
              <th>Provenance</th>
              <th>Capture</th>
              <th class="num" title="Ce que le tri juge : la date, le lieu, le public.">
                Étage 4<br /><span class="muted small">tri</span>
              </th>
              <th class="num" title="Ce que la lecture juge : l’illustration, les dates déclarées, les fragments du texte.">
                Étage 5<br /><span class="muted small">lecture</span>
              </th>
              <th class="num" title="Ce que l’extraction juge : les douze aspects de la fiche.">
                Étage 6<br /><span class="muted small">extraction</span>
              </th>
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
              <!--
                Une colonne par étage : les trois ne mesurent pas la même chose,
                et les aligner sur une seule ligne faisait lire « 6/6 » comme une
                complétude alors que c'était un dénominateur inventé.
              -->
              <td class="num" :class="etatDeCompletude(sortie.couverture.tri)">
                {{ sortie.couverture.tri.faits }}/{{ sortie.couverture.tri.total }}
              </td>
              <td class="num" :class="etatDeCompletude(sortie.couverture.lecture)">
                {{ sortie.couverture.lecture.faits }}/{{ sortie.couverture.lecture.total }}
              </td>
              <td class="num" :class="etatDeCompletude(sortie.couverture.extraction)">
                {{ sortie.couverture.extraction.faits }}/{{ sortie.couverture.extraction.total }}
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
    </section>
  </div>
</template>

<style scoped>

/* ── Les onglets ──────────────────────────────────────────────────────
   Larges et bavards, à dessein : ce sont trois corpus différents, et le
   libellé doit dire lequel avant qu'on clique. */
.onglets {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.6rem;
  margin: 1.4rem 0 0.4rem;
}

.onglet {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  text-align: left;
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--photo-bg);
  border-radius: 8px;
  background: none;
  font: inherit;
  cursor: pointer;
}

.onglet.on {
  border-color: var(--accent);
  box-shadow: inset 0 -3px 0 var(--accent);
}

.onglet-titre {
  font-weight: 700;
}

.onglet-compte {
  font-size: 0.85rem;
}

.onglet-quoi {
  font-size: 0.78rem;
  color: var(--ink-soft);
}

/* La sortie qu'on vient d'atteindre depuis l'onglet des agendas : sans ce
   repère, on arrive au milieu d'un tableau sans savoir sur quelle ligne. */
.vise > td {
  background: var(--photo-bg);
}
h2 {
  margin-top: 1.8rem;
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

.etape {
  margin: 0.4rem 0 0;
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  flex-wrap: wrap;
  font-size: 0.85rem;
  border-left: 3px solid var(--line);
  padding-left: 0.6rem;
}

.etape.a_geler,
.etape.sans_releve {
  border-left-color: var(--warn);
}

.etape.a_etiqueter,
.etape.en_cours {
  border-left-color: var(--accent);
}

.etape.complet {
  border-left-color: var(--ok);
}

.faits-ligne-inline {
  border-left: 3px solid var(--accent);
  padding: 0.4rem 0 0.2rem 0.6rem;
  margin-top: 0.4rem;
}

.candidats {
  padding: 0.8rem 1rem;
  margin-bottom: 1rem;
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

td.num.complete {
  color: var(--ok, #1a7f37);
  font-weight: 600;
}

td.num.vide {
  color: var(--ink-soft, #999);
}

.paniers {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 0.9rem;
  margin-bottom: 1rem;
}

.panier {
  padding: 0.8rem 0.9rem;
  border: 1px solid var(--border, #e5e5e5);
  border-radius: 8px;
}

.panier .btn {
  width: 100%;
  margin-bottom: 0.5rem;
}

.panier-quoi {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.4rem;
}

.panier-chemin {
  margin: 0 0 0.4rem;
  padding-left: 1.1rem;
  font-size: 0.8rem;
  line-height: 1.45;
}

.panier-pourquoi {
  margin: 0;
}

.criteres {
  padding: 0.9rem 1.1rem;
  margin-bottom: 1rem;
}

.criteres-bloc + .criteres-bloc {
  margin-top: 0.9rem;
}

.criteres h4 {
  margin: 0 0 0.3rem;
  font-size: 0.9rem;
}

.criteres ol {
  margin: 0;
  padding-left: 1.3rem;
  font-size: 0.85rem;
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

.chasse-form {
  padding: 0.9rem 1.1rem;
  margin-bottom: 1rem;
}

.chasse-champ {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.82rem;
  color: var(--ink-soft);
  flex: 1;
  min-width: 180px;
}

.chasse-champ.court {
  flex: 0 0 7rem;
  min-width: 7rem;
}

.chasse-form textarea {
  width: 100%;
  margin-top: 0.3rem;
}

.chasse-valide {
  align-items: center;
  margin-top: 0.8rem;
}

/* Une candidate décochée reste lisible : elle n'est pas refusée, elle attend. */
tr.off {
  opacity: 0.55;
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
