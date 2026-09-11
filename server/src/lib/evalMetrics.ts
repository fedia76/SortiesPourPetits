/**
 * La mesure : la confrontation d'un run au corpus.
 *
 * Elle n'est **jamais stockée**, et c'est tout l'intérêt de la séparation. Un
 * verdict enregistré ne vaut que contre le passage qui l'a produit : « le
 * texte était amputé » ne dit rien du texte d'aujourd'hui, et il périmait donc
 * au premier changement de code — ce qui obligeait à ré-étiqueter pour
 * re-mesurer, c'est-à-dire à payer deux fois la chose la plus chère.
 *
 * Ici, le corpus dit ce que la page contient et le run dit ce que la brique a
 * rendu. Le verdict tombe de la comparaison, à la demande, pour n'importe quel
 * run passé ou futur. Les quatre étiquettes d'autrefois n'ont pas disparu :
 * elles sont devenues des conclusions au lieu d'être des données.
 *
 * Tout ce fichier est **pur** : des tableaux entrent, des nombres sortent. Il
 * se teste sans base de données, et c'est la seule partie du banc dont une
 * erreur fausserait silencieusement tous les chiffres.
 */

// ═══════════════════════════════════════════════════ les verdicts dérivés

/** Ce qu'un run a fait d'un champ, face à ce que le corpus déclare. */
export type FieldVerdict = 'JUSTE' | 'FAUX' | 'INVENTE' | 'MANQUE';

/**
 * Compare une valeur rendue à la valeur attendue.
 *
 * La comparaison est **repliée** — sans casse, sans accents, espaces
 * normalisés. Un banc qui compterait « Musée Rodin » et « musee rodin » comme
 * un désaccord mesurerait sa propre sévérité, pas la brique.
 */
export function fold(text: string): string {
  return (text ?? '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

/**
 * Le verdict d'un champ. `null` quand le corpus ne dit rien de ce champ —
 * personne ne l'a étiqueté, donc il n'y a rien à conclure, et surtout pas que
 * la brique a eu tort.
 *
 * Noter la dissymétrie entre les deux vides : une valeur **attendue** vide est
 * une étiquette de plein droit (« la page n'en dit rien »), alors qu'une clé
 * absente est un silence. C'est ce qui permet de reconnaître une valeur
 * inventée, et c'est pourquoi les deux ne se confondent jamais.
 */
export function verdictOf(expected: string | undefined, produced: string): FieldVerdict | null {
  if (expected === undefined) return null;
  const wanted = fold(expected);
  const got = fold(produced);
  if (!wanted && !got) return 'JUSTE';
  if (!wanted) return 'INVENTE';
  if (!got) return 'MANQUE';
  return wanted === got ? 'JUSTE' : 'FAUX';
}

/** Le compte des quatre verdicts, plus ce que le corpus n'a pas étiqueté. */
export interface VerdictTally {
  JUSTE: number;
  FAUX: number;
  INVENTE: number;
  MANQUE: number;
  /** Champs rendus dont le corpus ne dit rien : un trou, pas une erreur. */
  inconnu: number;
}

export function emptyTally(): VerdictTally {
  return { JUSTE: 0, FAUX: 0, INVENTE: 0, MANQUE: 0, inconnu: 0 };
}

/** Part des champs étiquetés que la brique a rendus justes. `null` si aucun. */
export function accuracy(tally: VerdictTally): number | null {
  const judged = tally.JUSTE + tally.FAUX + tally.INVENTE + tally.MANQUE;
  return judged > 0 ? tally.JUSTE / judged : null;
}

// ═════════════════════════════════════════════ étage 3 — le dépouillement

/**
 * Pour qui est la sortie, d'après ce que le contexte du lien montre.
 *
 * `INDETERMINE` est une étiquette de plein droit, pas un silence : le contexte
 * d'un lien ne dit presque jamais le public, et prétendre le savoir fabriquerait
 * de faux reproches. Le silence, lui, est l'absence de la colonne — `null`.
 */
export type Audience = 'ENFANTS' | 'ADULTES' | 'INDETERMINE';

/**
 * Ce qu'un humain dit d'un lien d'agenda.
 *
 * `verdict` dit **ce que le lien est** : c'est stable, ça ne dépend d'aucune
 * recherche. Les trois indices disent **ce que la sortie est**, tels que le
 * contexte du lien les montre — sa date, son lieu, son public.
 *
 * La distinction est le cœur de ce qui suit. « Pertinente » n'est pas une
 * propriété du lien : le même atelier est pertinent pour « musées
 * Île-de-France » et hors sujet pour « spectacles Seine-Maritime ». En faire
 * une étiquette la rendrait fausse au premier changement de configuration —
 * exactement la péremption que la séparation corpus / run a supprimée
 * ailleurs. On étiquette donc des faits, et la pertinence se **dérive**.
 */
export interface LabelledLink {
  url: string;
  verdict: 'SORTIE' | 'PAGINATION' | 'SOUS_AGENDA' | 'AUTRE';
  /** `YYYY-MM-DD` si l'agenda l'affiche, `''` s'il n'affiche rien, `null` si personne n'a regardé. */
  dateHint?: string | null;
  /** Ville ou code postal si l'agenda l'affiche. Mêmes trois états. */
  placeHint?: string | null;
  audience?: Audience | null;
}

export interface HarvestedLink {
  url: string;
  harvested: boolean;
}

/**
 * Ce que le dépouillement a trouvé, et ce qu'il a manqué.
 *
 * Deux erreurs, et elles ne se corrigent pas au même endroit : un lien de
 * sortie qu'on n'a pas retenu est une sortie **perdue** — le ratage cher, et
 * silencieux ; un lien retenu qui n'en est pas est du bruit qu'on paiera au
 * tri de l'étage 4. Les confondre en un seul taux les rendrait tous deux
 * invisibles.
 */
export interface HarvestScore {
  /** Liens de sortie que le corpus déclare, et que la brique a retenus. */
  found: number;
  /** Liens de sortie que le corpus déclare, et que la brique a manqués. */
  missed: number;
  /** Liens retenus que le corpus dit n'être pas des sorties. */
  noise: number;
  /** Liens retenus dont le corpus ne dit rien : le corpus est incomplet. */
  unlabelled: number;
  /** Trouvés sur l'ensemble des sorties étiquetées. `null` s'il n'y en a pas. */
  recall: number | null;
  /**
   * Trouvés sur l'ensemble des liens retenus **et étiquetés**. Les liens sans
   * étiquette sont exclus du dénominateur plutôt que comptés comme du bruit :
   * les compter accuserait la brique d'un trou du corpus.
   */
  precision: number | null;
}

export function harvestScore(labels: LabelledLink[], results: HarvestedLink[]): HarvestScore {
  const labelByUrl = new Map(labels.map((l) => [l.url, l.verdict]));
  const harvestedUrls = new Set(results.filter((r) => r.harvested).map((r) => r.url));

  let found = 0;
  let missed = 0;
  for (const label of labels) {
    if (label.verdict !== 'SORTIE') continue;
    if (harvestedUrls.has(label.url)) found += 1;
    else missed += 1;
  }

  let noise = 0;
  let unlabelled = 0;
  for (const url of harvestedUrls) {
    const verdict = labelByUrl.get(url);
    if (verdict === undefined) unlabelled += 1;
    else if (verdict !== 'SORTIE') noise += 1;
  }

  const sorties = found + missed;
  const judgedKept = found + noise;
  return {
    found,
    missed,
    noise,
    unlabelled,
    recall: sorties > 0 ? found / sorties : null,
    precision: judgedKept > 0 ? found / judgedKept : null,
  };
}

// ══════════════════════════════════════════════════ étage 4 — la sélection

export interface SelectedLink {
  url: string;
  /** `null` quand le run n'a pas soumis ce lien au tri. */
  selected: boolean | null;
}

/**
 * Ce que la recherche d'un run demandait, tel que le run l'a enregistré.
 *
 * C'est ce qui permet de dériver la pertinence sans l'avoir étiquetée. Un
 * champ absent veut dire « la recherche ne filtrait pas là-dessus », et la
 * dimension correspondante ne peut alors écarter personne.
 */
export interface RunScope {
  /** Fenêtre de la recherche, en `YYYY-MM-DD`. */
  dateFrom?: string;
  dateTo?: string;
  /** Préfixes de code postal visés — « 75 », « 76 »… */
  postalPrefixes?: string[];
  /** Nombre maximal de liens que le tri avait le droit de retenir. */
  maxLinks?: number;
}

/** Ce qu'un lien vaut pour une recherche donnée. */
export type Relevance = 'PERTINENTE' | 'HORS_RECHERCHE' | 'INDECIDABLE';

/**
 * La pertinence d'un lien pour **cette** recherche, dérivée de ses indices.
 *
 * Le principe : on n'écarte que sur ce que le corpus **affirme**. Un indice
 * vide — l'agenda n'affichait pas la date — ne peut pas rendre une sortie hors
 * recherche, il la rend indécidable, et l'indécidable ne compte dans aucun
 * dénominateur. C'est la même règle que le prompt de l'étage 4 applique
 * lui-même : « dans le doute sur une date ou un lieu que le contexte n'indique
 * pas, retiens le lien ». La mesure ne peut pas être plus sévère que la
 * consigne.
 */
export function relevanceOf(label: LabelledLink, scope: RunScope): Relevance {
  if (label.verdict !== 'SORTIE') return 'HORS_RECHERCHE';

  // Un public déclaré adulte suffit à écarter, et c'est le seul des trois
  // indices qui tranche à lui seul : il ne dépend pas des réglages du run.
  if (label.audience === 'ADULTES') return 'HORS_RECHERCHE';

  let decidable = false;

  if (label.dateHint) {
    const day = label.dateHint.slice(0, 10);
    if (scope.dateFrom && day < scope.dateFrom) return 'HORS_RECHERCHE';
    if (scope.dateTo && day > scope.dateTo) return 'HORS_RECHERCHE';
    if (scope.dateFrom || scope.dateTo) decidable = true;
  }

  if (label.placeHint && scope.postalPrefixes?.length) {
    const digits = label.placeHint.replace(/\D/g, '');
    // Une ville en toutes lettres n'a pas de chiffres : on ne sait pas la
    // situer, donc on ne l'écarte pas. Mieux vaut un indécidable qu'un
    // reproche inventé.
    if (digits) {
      if (!scope.postalPrefixes.some((p) => digits.startsWith(p))) return 'HORS_RECHERCHE';
      decidable = true;
    }
  }

  if (label.audience === 'ENFANTS') decidable = true;

  // Rien d'affirmé, rien à conclure : le corpus ne permet pas de dire si ce
  // lien avait sa place dans cette recherche.
  return decidable ? 'PERTINENTE' : 'INDECIDABLE';
}

/**
 * Le tri, mesuré sur ce qu'on lui a soumis — et sur ce qu'on lui a demandé.
 *
 * C'est ici que la mesure précédente était **fausse**, et pas seulement
 * incomplète. L'étage 4 ne fait pas un métier mais trois : reconnaître une
 * sortie, écarter ce qui sort de la recherche, et n'en garder qu'un nombre
 * borné. Compter comme « manquée » toute sortie qu'il n'a pas retenue lui
 * reprochait donc deux comportements corrects — un concert pour adultes
 * écarté à raison, une sortie de l'an prochain hors fenêtre — et faisait
 * baisser son rappel à mesure que la recherche se précisait.
 *
 * Chaque lien tombe désormais dans une case, et une seule :
 *
 * * **trouvée** — pertinente, et retenue. Ce qu'on veut ;
 * * **manquée** — pertinente, et écartée. La vraie faute ;
 * * **bruit** — hors recherche, et retenue. L'autre faute, qui coûte une
 *   lecture payée pour rien ;
 * * **écartée à raison** — hors recherche, et écartée. Le travail bien fait,
 *   qui n'apparaissait nulle part ;
 * * **indécidable** — le corpus ne permet pas de trancher. Hors de tout
 *   dénominateur, et affiché pour qu'on sache ce qu'on ignore.
 */
export interface SelectScore extends HarvestScore {
  /** Hors recherche, et écartée : le filtre a fait son travail. */
  rightlyDropped: number;
  /** Le corpus ne permet pas de dire si ce lien avait sa place. */
  undecidable: number;
  /**
   * Pages dont le tri a retenu exactement son plafond.
   *
   * Sur celles-là, une sortie pertinente écartée peut l'avoir été par le
   * plafond et non par un mauvais jugement — les deux sont indiscernables du
   * relevé. Elles sortent donc du rappel, et leur nombre est affiché : un
   * rappel calculé dessus mesurerait `max_links`, pas le modèle.
   */
  cappedPages: number;
}

export function selectScore(
  labels: LabelledLink[],
  results: SelectedLink[],
  scope: RunScope = {},
): SelectScore {
  const submitted = results.filter((r) => r.selected !== null);
  // Les étiquettes sont restreintes à ce qui lui a été soumis. Sans ce filtre,
  // une sortie que l'étage 3 avait déjà perdue serait comptée « manquée » par
  // l'étage 4, qui ne l'a jamais vue — on lui reprocherait la faute du
  // précédent, et son rappel baisserait chaque fois que le dépouillement
  // s'améliorerait.
  const seen = new Set(submitted.map((r) => r.url));
  const keptUrls = new Set(submitted.filter((r) => r.selected === true).map((r) => r.url));

  // Le plafond : quand le tri a retenu exactement son quota, on ne peut pas
  // distinguer « écarté à tort » de « tronqué ». La page ne compte alors pas
  // dans le rappel.
  const capped = scope.maxLinks !== undefined && keptUrls.size >= scope.maxLinks;

  let found = 0;
  let missed = 0;
  let noise = 0;
  let rightlyDropped = 0;
  let undecidable = 0;

  for (const label of labels) {
    if (!seen.has(label.url)) continue;
    const kept = keptUrls.has(label.url);
    switch (relevanceOf(label, scope)) {
      case 'PERTINENTE':
        if (kept) found += 1;
        else missed += 1;
        break;
      case 'HORS_RECHERCHE':
        if (kept) noise += 1;
        else rightlyDropped += 1;
        break;
      default:
        undecidable += 1;
    }
  }

  const unlabelled = [...keptUrls].filter(
    (url) => !labels.some((l) => l.url === url),
  ).length;

  const pertinentes = found + missed;
  const judgedKept = found + noise;
  return {
    found,
    missed,
    noise,
    rightlyDropped,
    undecidable,
    unlabelled,
    cappedPages: capped ? 1 : 0,
    // Sur une page plafonnée, le rappel mesurerait le plafond : on ne le rend
    // pas plutôt que de rendre un chiffre qui n'accuse personne de juste.
    recall: capped || pertinentes === 0 ? null : found / pertinentes,
    precision: judgedKept > 0 ? found / judgedKept : null,
  };
}

/**
 * Les scores d'un run, rassemblés depuis ceux de ses pages.
 *
 * Le rappel ne se calcule **pas** sur la somme des pages : les pages saturées
 * en sortent. Les additionner d'abord ferait rentrer le plafond dans le
 * dénominateur par la porte de derrière — une page où le tri a pris ses huit
 * liens et en a laissé douze compterait douze manquées, alors qu'il n'avait
 * plus le droit d'en prendre un seul. D'où deux comptes : celui qu'on affiche,
 * qui dit ce qui s'est passé, et celui du rappel, qui ne retient que les pages
 * où le modèle a eu les mains libres.
 *
 * La précision, elle, se calcule bien sur tout : ce que le tri a retenu, il
 * l'a retenu de son plein gré, plafond ou pas.
 */
export function sumSelect(pages: SelectScore[]): SelectScore {
  const total: SelectScore = {
    found: 0,
    missed: 0,
    noise: 0,
    unlabelled: 0,
    rightlyDropped: 0,
    undecidable: 0,
    cappedPages: 0,
    recall: null,
    precision: null,
  };
  let recallFound = 0;
  let recallMissed = 0;
  for (const page of pages) {
    total.found += page.found;
    total.missed += page.missed;
    total.noise += page.noise;
    total.unlabelled += page.unlabelled;
    total.rightlyDropped += page.rightlyDropped;
    total.undecidable += page.undecidable;
    total.cappedPages += page.cappedPages;
    if (page.cappedPages === 0) {
      recallFound += page.found;
      recallMissed += page.missed;
    }
  }
  const pertinentes = recallFound + recallMissed;
  const kept = total.found + total.noise;
  total.recall = pertinentes > 0 ? recallFound / pertinentes : null;
  total.precision = kept > 0 ? total.found / kept : null;
  return total;
}

/** Le même repli pour le dépouillement, qui n'a pas de plafond à écarter. */
export function sumHarvest(pages: HarvestScore[]): HarvestScore {
  const total: HarvestScore = {
    found: 0,
    missed: 0,
    noise: 0,
    unlabelled: 0,
    recall: null,
    precision: null,
  };
  for (const page of pages) {
    total.found += page.found;
    total.missed += page.missed;
    total.noise += page.noise;
    total.unlabelled += page.unlabelled;
  }
  const pertinentes = total.found + total.missed;
  const kept = total.found + total.noise;
  total.recall = pertinentes > 0 ? total.found / pertinentes : null;
  total.precision = kept > 0 ? total.found / kept : null;
  return total;
}

// ═══════════════════════════════════════════════════ étage 5 — la lecture

export interface ReadLabels {
  /** `null` : personne n'a regardé. `''` : la page n'en porte pas. */
  expectedImage: string | null;
  /** JSON d'un tableau de dates. `null` : personne n'a regardé. */
  expectedDates: string | null;
  /** JSON d'un tableau de fragments que le texte doit contenir. */
  expectedMarkers: string | null;
}

export interface ReadOutput {
  text: string;
  imageUrl: string;
  /** JSON d'un tableau de dates. */
  dates: string;
  truncated: boolean;
  tooShort: boolean;
}

/** Les trois questions de l'étage 5, chacune tranchée par comparaison. */
export interface ReadScore {
  /** Fragments attendus retrouvés dans le texte, et ceux qui manquent. */
  markersFound: number;
  markersMissing: number;
  /** `null` si le corpus ne dit rien des fragments. */
  textOk: boolean | null;
  /** Le texte est au plafond : la fin de la page n'atteindra pas le modèle. */
  truncated: boolean;
  /** Sous le seuil de l'étage 5 : la page serait abandonnée sans être lue. */
  tooShort: boolean;
  imageOk: boolean | null;
  datesOk: boolean | null;
}

function parseList(raw: string | null): string[] | null {
  if (raw === null) return null;
  try {
    const value = JSON.parse(raw) as unknown;
    return Array.isArray(value) ? value.map((v) => String(v)) : null;
  } catch {
    return null;
  }
}

export function readScore(labels: ReadLabels, out: ReadOutput): ReadScore {
  const haystack = fold(out.text);
  const markers = parseList(labels.expectedMarkers);

  let markersFound = 0;
  let markersMissing = 0;
  for (const marker of markers ?? []) {
    if (haystack.includes(fold(marker))) markersFound += 1;
    else markersMissing += 1;
  }

  const wantedDates = parseList(labels.expectedDates);
  const gotDates = parseList(out.dates) ?? [];
  const datesOk =
    wantedDates === null
      ? null
      : wantedDates.length === gotDates.length &&
        [...wantedDates].sort().every((d, i) => d === [...gotDates].sort()[i]);

  return {
    markersFound,
    markersMissing,
    // Un texte sans fragment attendu n'est pas jugé : le corpus ne dit rien.
    textOk: markers === null || markers.length === 0 ? null : markersMissing === 0,
    truncated: out.truncated,
    tooShort: out.tooShort,
    imageOk:
      labels.expectedImage === null ? null : fold(labels.expectedImage) === fold(out.imageUrl),
    datesOk,
  };
}

// ════════════════════════════════════════════════ étage 6 — l'extraction

export interface Aspect {
  key: string;
  value: string;
}

/**
 * La fiche rendue, champ par champ, face à ce que la page annonce.
 *
 * C'est ici que le changement de nature des étiquettes paie : le corpus dit
 * « la page annonce 8 € », et n'importe quel run — d'hier, d'aujourd'hui, avec
 * un autre modèle ou un autre prompt — se compare à lui sans qu'un humain
 * n'ait à rouvrir quoi que ce soit.
 */
export function extractScore(
  expected: Record<string, string>,
  aspects: Aspect[],
): { tally: VerdictTally; byField: Record<string, FieldVerdict | null> } {
  const tally = emptyTally();
  const byField: Record<string, FieldVerdict | null> = {};
  for (const aspect of aspects) {
    const verdict = verdictOf(expected[aspect.key], aspect.value ?? '');
    byField[aspect.key] = verdict;
    if (verdict === null) tally.inconnu += 1;
    else tally[verdict] += 1;
  }
  return { tally, byField };
}
