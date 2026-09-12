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
export type Verdict = 'SORTIE' | 'PAGINATION' | 'SOUS_AGENDA' | 'AUTRE';

export interface LabelledLink {
  url: string;
  /** Ce que le lien **est**. La question de l'étage 3, et rien d'autre. */
  verdict: Verdict;
  /**
   * La sortie vers laquelle il mène, quand quelqu'un l'a décrite.
   *
   * Un lien ne décrit pas une sortie, il y mène : ce qu'elle est appartient à
   * la sortie, qui le dit une fois pour les étages 4, 5 et 6. Nul sur un lien
   * `SORTIE` veut dire que personne ne l'a encore décrite.
   */
  sortie?: SortieFacts | null;
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
 * Ce qu'une sortie **est**, dit une fois pour les étages 4, 5 et 6.
 *
 * Des faits, pas leur mise en forme : une date se compare à une fenêtre, un
 * code postal à des préfixes. La prose de `EvalFiche` — « dès 3 ans », « du 20
 * au 22 septembre » — sert à l'étage 6, qui compare des chaînes à des chaînes.
 *
 * `null` partout : personne n'a regardé.
 */
export interface SortieFacts {
  /** `YYYY-MM-DD`. `dateEnd` nul sur une date unique. */
  dateStart?: string | null;
  dateEnd?: string | null;
  postalCode?: string | null;
  ageMin?: number | null;
  ageMax?: number | null;
  audience?: Audience | null;
}

/**
 * L'âge d'où se déduit le public, quand personne ne l'a dit explicitement.
 *
 * Un seuil est une convention, pas une vérité — il est ici pour que la moisson
 * depuis la modération serve à quelque chose : `Event` porte `ageMin`/`ageMax`
 * mais aucune colonne « public ». Sans cette déduction, l'essentiel du corpus
 * arriverait sans public déclaré et le critère ne jouerait jamais.
 */
const MAJORITE = 18;

export function audienceOf(sortie: SortieFacts): Audience | null {
  if (sortie.audience) return sortie.audience;
  if (sortie.ageMin != null && sortie.ageMin >= MAJORITE) return 'ADULTES';
  if (sortie.ageMax != null && sortie.ageMax < MAJORITE) return 'ENFANTS';
  return null;
}

/**
 * La pertinence d'un lien pour **cette** recherche, dérivée de la sortie vers
 * laquelle il mène.
 *
 * ## Ce qu'on mesure, et ce qu'on ne mesure pas
 *
 * On juge **si l'objectif est atteint**, pas si l'étage avait les moyens de
 * l'atteindre. L'étage 4 ne voit que le contexte du lien et sa consigne lui
 * dit de retenir dans le doute : un lien au contexte muet qu'il a gardé, et
 * qui s'avère être un concert pour adultes, compte donc comme du **bruit**.
 * Il n'est pas fautif — et la lecture a quand même été payée pour rien.
 *
 * Ce n'est pas une sévérité gratuite. Un banc qui absout l'étage 4 parce que
 * l'agenda était avare ne dit plus rien de ce qu'il faut corriger ; celui-ci
 * dit « l'objectif n'est pas atteint », et la correction — donner à l'étage 4
 * davantage que le contexte — se décide ensuite, au vu du chiffre.
 *
 * ## Le seul silence qui compte
 *
 * `INDECIDABLE` ne veut plus dire « le contexte n'affichait rien ». Il veut
 * dire : **personne n'a décrit cette sortie**. Il n'y a alors rien à quoi
 * comparer, donc rien à conclure — ni pour, ni contre. C'est une dette de
 * corpus, pas un jugement, et elle se solde en étiquetant.
 */
export function relevanceOf(
  label: { verdict: Verdict; sortie?: SortieFacts | null },
  scope: RunScope,
): Relevance {
  if (label.verdict !== 'SORTIE') return 'HORS_RECHERCHE';

  const sortie = label.sortie;
  if (!sortie) return 'INDECIDABLE';

  if (audienceOf(sortie) === 'ADULTES') return 'HORS_RECHERCHE';

  let decidable = false;

  // Une sortie occupe une plage, pas un point : celle du 15 septembre au
  // 15 décembre est dans une fenêtre qui s'arrête au 11 octobre. La comparer
  // par son seul premier jour l'écarterait à tort dès que la fenêtre
  // commencerait après son ouverture.
  if (sortie.dateStart) {
    const debut = sortie.dateStart.slice(0, 10);
    const fin = (sortie.dateEnd ?? sortie.dateStart).slice(0, 10);
    if (scope.dateTo && debut > scope.dateTo) return 'HORS_RECHERCHE';
    if (scope.dateFrom && fin < scope.dateFrom) return 'HORS_RECHERCHE';
    if (scope.dateFrom || scope.dateTo) decidable = true;
  }

  if (sortie.postalCode && scope.postalPrefixes?.length) {
    const chiffres = sortie.postalCode.replace(/\D/g, '');
    if (chiffres) {
      if (!scope.postalPrefixes.some((p) => chiffres.startsWith(p))) return 'HORS_RECHERCHE';
      decidable = true;
    }
  }

  if (audienceOf(sortie) === 'ENFANTS') decidable = true;

  // La sortie est décrite, mais rien de ce qu'elle affirme ne rencontre les
  // réglages de ce run : il n'y a pas de quoi trancher.
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

/**
 * Ce que l'étiquette dit de la **page**, pour l'étage 5.
 *
 * Trois clés du même JSON que le reste — une sortie n'a qu'une étiquette. Une
 * clé absente veut dire « personne n'a regardé » ; une valeur vide (`""` pour
 * l'image, `[]` pour les dates) veut dire « la page n'en porte pas », ce qui
 * est une étiquette de plein droit. Sans le second état, une image inventée
 * serait indiscernable d'un champ jamais relu.
 */
export interface ReadLabels {
  /** L'illustration que la page porte vraiment. */
  image?: string | null;
  /** Les dates que la page déclare dans son balisage `schema.org/Event`. */
  declaredDates?: string[] | null;
  /** Quelques fragments que le texte extrait doit contenir. */
  markers?: string[] | null;
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
  const markers = labels.markers ?? null;

  let markersFound = 0;
  let markersMissing = 0;
  for (const marker of markers ?? []) {
    if (haystack.includes(fold(marker))) markersFound += 1;
    else markersMissing += 1;
  }

  const wantedDates = labels.declaredDates ?? null;
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
    imageOk: labels.image == null ? null : fold(labels.image) === fold(out.imageUrl),
    datesOk,
  };
}

// ════════════════════════════════════════════════ étage 6 — l'extraction

/**
 * La fiche que l'étage 6 rend, telle que `evaluation.fiche_payload` l'envoie :
 * les champs du modèle, en camelCase, **structurés**.
 *
 * ## Pourquoi on compare ça, et pas la prose
 *
 * Chaque champ est structuré aux deux bouts de la chaîne : le modèle rend
 * `{"ageMin": 3, "ageMax": null}`, et la sortie publiée porte les colonnes
 * `ageMin` / `ageMax`. Entre les deux, `audit_fiche` met en forme « dès 3 ans »
 * — pour l'affichage humain, ce qui est son métier.
 *
 * La mesure comparait cette **mise en forme**. Ça marchait, tant que les deux
 * côtés l'écrivaient pareil ; ça obligeait surtout à réécrire en TypeScript un
 * format défini en Python, pour traverser un aplatissement dont personne
 * n'avait besoin. Un point-virgule changé dans `audit_fiche` et tous les
 * tarifs comptaient « faux ».
 *
 * On compare donc les faits. La mise en forme redevient ce qu'elle est : de
 * l'affichage, et rien d'autre.
 */
export interface FicheRendue {
  relevant?: boolean;
  several?: boolean;
  skipReason?: string;
  title?: string;
  description?: string;
  free?: boolean;
  price?: number | null;
  ageMin?: number | null;
  ageMax?: number | null;
  permanent?: boolean;
  dateStart?: string;
  dateEnd?: string;
  weekdays?: string[];
  dates?: string[];
  openTime?: string;
  closeTime?: string;
  setting?: string;
  category?: string;
  venueName?: string;
  venueAddress?: string;
  venueCity?: string;
  venuePostalCode?: string;
}

/** Comment se compare un champ. Le repli ne vaut que pour de la prose. */
type Genre = 'texte' | 'nombre' | 'booleen' | 'jour' | 'liste';

/**
 * Les aspects d'une fiche, et les champs que chacun recouvre.
 *
 * Le regroupement n'est pas cosmétique : `free` et `price` disent **un seul
 * fait**, et les juger séparément compterait deux fois la même erreur. C'est
 * la raison d'être de cette table, et la seule ; elle décrit le même découpage
 * que `evaluation.audit_fiche`, mais en termes de champs plutôt que de chaînes.
 */
export const ASPECTS: { key: string; champs: [keyof FicheRendue, Genre][] }[] = [
  { key: 'verdict', champs: [['relevant', 'booleen'], ['several', 'booleen']] },
  { key: 'titre', champs: [['title', 'texte']] },
  { key: 'description', champs: [['description', 'texte']] },
  { key: 'tarif', champs: [['free', 'booleen'], ['price', 'nombre']] },
  { key: 'age', champs: [['ageMin', 'nombre'], ['ageMax', 'nombre']] },
  {
    key: 'dates',
    champs: [['permanent', 'booleen'], ['dateStart', 'jour'], ['dateEnd', 'jour']],
  },
  { key: 'jours', champs: [['weekdays', 'liste'], ['dates', 'liste']] },
  { key: 'horaires', champs: [['openTime', 'texte'], ['closeTime', 'texte']] },
  { key: 'cadre', champs: [['setting', 'texte']] },
  { key: 'categorie', champs: [['category', 'texte']] },
  { key: 'lieu', champs: [['venueName', 'texte']] },
  {
    key: 'adresse',
    champs: [
      ['venueAddress', 'texte'],
      ['venuePostalCode', 'texte'],
      ['venueCity', 'texte'],
    ],
  },
];

/** Une valeur qui ne dit rien : `null`, vide, ou une liste vide. */
function muet(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim() === '';
  if (Array.isArray(value)) return value.length === 0;
  // `false` et `0` **disent** quelque chose : gratuit, et zéro an.
  return false;
}

/** Deux valeurs d'un même champ se valent-elles. */
function pareil(a: unknown, b: unknown, genre: Genre): boolean {
  if (muet(a) && muet(b)) return true;
  if (muet(a) || muet(b)) return false;
  switch (genre) {
    case 'nombre':
      return Number(a) === Number(b);
    case 'booleen':
      return Boolean(a) === Boolean(b);
    case 'jour':
      // Une date se compare à son jour : le corpus dit « 2026-09-20 », la
      // brique peut rendre un instant.
      return String(a).slice(0, 10) === String(b).slice(0, 10);
    case 'liste': {
      const gauche = [...(a as string[])].map(fold).sort();
      const droite = [...(b as string[])].map(fold).sort();
      return gauche.length === droite.length && gauche.every((v, i) => v === droite[i]);
    }
    default:
      return fold(String(a)) === fold(String(b));
  }
}

/**
 * Le verdict d'un aspect, par comparaison champ à champ.
 *
 * Les quatre verdicts gardent exactement le sens qu'ils avaient :
 *
 *   attendu renseigné, rendu identique   → JUSTE
 *   attendu renseigné, rendu différent   → FAUX
 *   attendu vide,      rendu renseigné   → INVENTE
 *   attendu renseigné, rendu vide        → MANQUE
 *
 * `null` quand **aucun** champ de l'aspect n'est présent dans l'étiquette :
 * personne n'a regardé, et il n'y a rien à conclure. La dissymétrie entre une
 * clé absente et une valeur vide reste le cœur de l'affaire — sans elle, « la
 * page n'annonce pas de tarif » et « personne n'a vérifié le tarif » seraient
 * le même silence, et une valeur inventée deviendrait invisible.
 */
export function verdictAspect(
  aspect: { key: string; champs: [keyof FicheRendue, Genre][] },
  attendue: FicheRendue,
  rendue: FicheRendue,
): FieldVerdict | null {
  // Seuls les champs que l'étiquette **porte** sont jugés. Un champ absent
  // n'est pas un vide : personne ne l'a regardé, et le comparer reprocherait à
  // la brique d'avoir rendu quelque chose sur quoi le corpus se tait.
  //
  // C'est le cas des jours de représentation : l'étiquette reprise d'une
  // sortie publiée porte `dates` mais jamais `weekdays`, que le site ne reçoit
  // pas. Sans ce filtre, chaque sortie à récurrence compterait « faux ».
  const juges = aspect.champs.filter(([champ]) => champ in attendue);
  if (juges.length === 0) return null;

  const attenduRempli = juges.some(([champ]) => !muet(attendue[champ]));
  const renduRempli = juges.some(([champ]) => !muet(rendue[champ]));

  if (!attenduRempli && !renduRempli) return 'JUSTE';
  if (!attenduRempli) return 'INVENTE';
  if (!renduRempli) return 'MANQUE';

  const accord = juges.every(([champ, genre]) => pareil(attendue[champ], rendue[champ], genre));
  return accord ? 'JUSTE' : 'FAUX';
}

/**
 * La fiche rendue, champ par champ, face à ce que la page annonce.
 *
 * C'est ici que le changement de nature des étiquettes paie : le corpus dit
 * « la page annonce 8 € » sous la forme `{"free": false, "price": 8}`, et
 * n'importe quel run — d'hier, d'aujourd'hui, avec un autre modèle ou un autre
 * prompt — se compare à lui sans qu'un humain n'ait à rouvrir quoi que ce soit,
 * et sans qu'aucune mise en forme n'ait à concorder entre deux langages.
 */
/**
 * Ce qu'une étiquette couvre, étage par étage.
 *
 * Les compteurs se dérivent **du code de mesure**, et pas d'une liste écrite à
 * la main. Deux compteurs successifs ont menti pour l'avoir été : l'un ne
 * connaissait que les trois étiquettes de lecture et affichait « 0/3 » sur une
 * sortie parfaitement décrite pour le tri ; l'autre annonçait « 6/6 » sur six
 * champs que j'avais choisis arbitrairement, alors que l'étage 6 en juge douze.
 *
 * Ici, chaque dénominateur est celui de la mesure : ajouter un aspect à
 * `ASPECTS` ou un critère à `relevanceOf` déplace le compteur tout seul.
 */
export interface Couverture {
  /** Étage 4 — la date, le lieu, le public. Ce que `relevanceOf` sait lire. */
  tri: { faits: number; total: number };
  /** Étage 5 — l'image, les dates déclarées, les fragments. Ce que lit `readScore`. */
  lecture: { faits: number; total: number };
  /** Étage 6 — les aspects de la fiche qu'au moins un champ renseigne. */
  extraction: { faits: number; total: number };
}

/**
 * Les trois questions de l'étage 4, et ce qui permet d'y répondre.
 *
 * Des **critères**, pas des champs : le public se lit dans `audience` ou se
 * déduit de l'âge, et compter les deux ferait deux fois la même chose.
 */
const CRITERES_TRI: ((e: FicheRendue, audience: Audience | null) => boolean)[] = [
  (e) => 'dateStart' in e,
  (e) => 'venuePostalCode' in e,
  (e, audience) => audience !== null || 'ageMin' in e || 'ageMax' in e,
];

/** Ce que `readScore` lit, et rien d'autre. */
const CRITERES_LECTURE: (keyof ReadLabels)[] = ['image', 'declaredDates', 'markers'];

export function couverture(attendue: FicheRendue, audience: Audience | null): Couverture {
  const etiquette = attendue as Record<string, unknown>;
  return {
    tri: {
      faits: CRITERES_TRI.filter((critere) => critere(attendue, audience)).length,
      total: CRITERES_TRI.length,
    },
    lecture: {
      faits: CRITERES_LECTURE.filter((cle) => cle in etiquette).length,
      total: CRITERES_LECTURE.length,
    },
    // Un aspect est couvert dès qu'un de ses champs est étiqueté : c'est très
    // exactement le test que `verdictAspect` fait pour décider s'il rend un
    // verdict ou « personne n'a regardé ».
    extraction: {
      faits: ASPECTS.filter((a) => a.champs.some(([champ]) => champ in etiquette)).length,
      total: ASPECTS.length,
    },
  };
}

export function extractScore(
  attendue: FicheRendue,
  rendue: FicheRendue,
): { tally: VerdictTally; byField: Record<string, FieldVerdict | null> } {
  const tally = emptyTally();
  const byField: Record<string, FieldVerdict | null> = {};
  for (const aspect of ASPECTS) {
    const verdict = verdictAspect(aspect, attendue, rendue);
    byField[aspect.key] = verdict;
    if (verdict === null) tally.inconnu += 1;
    else tally[verdict] += 1;
  }
  return { tally, byField };
}
