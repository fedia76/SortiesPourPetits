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

export interface LabelledLink {
  url: string;
  verdict: 'SORTIE' | 'PAGINATION' | 'SOUS_AGENDA' | 'AUTRE';
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
 * Le tri, mesuré sur la moisson — comme en production.
 *
 * L'étage 4 ne voit que ce que l'étage 3 lui donne : mesurer sa justesse sur
 * l'ensemble de la page lui reprocherait les liens qu'il n'a jamais vus. Le
 * dénominateur est donc ce qui lui a été soumis, et le rappel perdu en amont
 * se lit sur l'étage 3, où il se corrige.
 */
export function selectScore(labels: LabelledLink[], results: SelectedLink[]): HarvestScore {
  const submitted = results.filter((r) => r.selected !== null);
  // Les étiquettes sont restreintes à ce qui lui a été soumis, et pas
  // seulement les résultats. Sans ce filtre, une sortie que l'étage 3 avait
  // déjà perdue serait comptée « manquée » par l'étage 4, qui ne l'a jamais
  // vue — on lui reprocherait la faute du précédent, et le rappel du tri
  // baisserait chaque fois que le dépouillement s'améliorerait.
  const seen = new Set(submitted.map((r) => r.url));
  return harvestScore(
    labels.filter((l) => seen.has(l.url)),
    submitted.map((r) => ({ url: r.url, harvested: r.selected === true })),
  );
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
