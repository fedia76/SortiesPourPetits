/**
 * Détection de doublons pour la modération.
 *
 * Un doublon typique, c'est le même évènement re-proposé par quelqu'un d'autre :
 * même lieu, mêmes dates, un titre écrit un peu différemment. On note donc
 * chaque candidat sur 100 en combinant ces signaux, et on rend les raisons du
 * score pour que le modérateur juge lui-même — l'outil ne décide rien.
 */

/** Poids de chaque signal. Le total des maximums fait 100. */
const WEIGHTS = {
  sameVenue: 35,
  nearbyVenue: 30,
  title: 30,
  description: 10,
  dateOverlap: 15,
  sameCategory: 5,
  sameAuthor: 5,
};

/** Au-delà, comparer plus de texte ne change plus le score de façon utile. */
const DESCRIPTION_COMPARE_LENGTH = 2000;

/**
 * Deux sorties qui ne peuvent pas avoir lieu en même temps sont rarement des
 * doublons : sans ce coup de frein, un lieu qui programme beaucoup noierait le
 * vrai doublon sous ses autres évènements, tous crédités du même lieu.
 */
const NO_OVERLAP_DAMPING = 0.6;

/** Minuscules, sans accents ni ponctuation : « Fête de l'Été » → « fete de l ete ». */
export function normalize(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

/** Mots trop courants pour distinguer deux sorties. */
const STOP_WORDS = new Set([
  'a', 'au', 'aux', 'avec', 'ce', 'ces', 'dans', 'de', 'des', 'du', 'en', 'et',
  'la', 'le', 'les', 'lors', 'pour', 'par', 'sur', 'un', 'une', 'sans',
]);

/** Mots significatifs d'un texte, dédoublonnés. */
export function significantWords(text: string): string[] {
  const words = normalize(text)
    .split(' ')
    .filter((w) => w.length >= 3 && !STOP_WORDS.has(w));
  return [...new Set(words)];
}

/** Multiensemble des bigrammes de caractères. */
function bigrams(text: string): Map<string, number> {
  const counts = new Map<string, number>();
  for (let i = 0; i < text.length - 1; i += 1) {
    const pair = text.slice(i, i + 2);
    counts.set(pair, (counts.get(pair) ?? 0) + 1);
  }
  return counts;
}

/**
 * Coefficient de Sørensen–Dice sur les bigrammes de caractères, entre 0 et 1.
 * Tolère les fautes de frappe et l'ordre des mots, contrairement à une égalité
 * stricte : « Ferme pédagogique de Gally » et « La ferme de Gally » ≈ 0,7.
 */
export function similarityRatio(a: string, b: string): number {
  const left = normalize(a);
  const right = normalize(b);
  if (!left || !right) return 0;
  if (left === right) return 1;
  if (left.length < 2 || right.length < 2) return 0;

  const leftGrams = bigrams(left);
  const rightGrams = bigrams(right);
  let shared = 0;
  let leftTotal = 0;
  for (const [gram, count] of leftGrams) {
    leftTotal += count;
    shared += Math.min(count, rightGrams.get(gram) ?? 0);
  }
  const rightTotal = [...rightGrams.values()].reduce((sum, n) => sum + n, 0);
  return (2 * shared) / (leftTotal + rightTotal);
}

export interface DatedEvent {
  isPermanent: boolean;
  dateStart: Date | null;
  dateEnd: Date | null;
}

/**
 * Deux évènements peuvent-ils avoir lieu en même temps ?
 * Un évènement permanent est considéré comme toujours en cours, et une borne
 * manquante comme ouverte — mêmes conventions que la recherche publique.
 */
export function periodsOverlap(a: DatedEvent, b: DatedEvent): boolean {
  if (a.isPermanent || b.isPermanent) return true;
  const aStart = a.dateStart?.getTime() ?? -Infinity;
  const aEnd = a.dateEnd?.getTime() ?? Infinity;
  const bStart = b.dateStart?.getTime() ?? -Infinity;
  const bEnd = b.dateEnd?.getTime() ?? Infinity;
  return aStart <= bEnd && bStart <= aEnd;
}

export interface ComparableEvent extends DatedEvent {
  title: string;
  description: string;
  venueId: number;
  categoryId: number;
  createdById: number;
}

export interface SimilarityScore {
  /** Note de 0 à 100 : plus c'est haut, plus le doublon est probable. */
  score: number;
  /** Ce qui a rapproché les deux sorties, à afficher au modérateur. */
  reasons: string[];
  /** Distance entre les deux lieux, absente si les lieux sont les mêmes. */
  distanceKm?: number;
}

function percent(ratio: number): string {
  return `${Math.round(ratio * 100)} %`;
}

function formatKm(km: number): string {
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1).replace('.', ',')} km`;
}

/**
 * Compare une sortie en cours de modération à une sortie déjà en base.
 * `distanceKm` vaut `undefined` si la distance n'a pas été calculée (lieux
 * identiques, ou lieu hors du rayon de recherche).
 */
export function scoreSimilarity(
  candidate: ComparableEvent,
  other: ComparableEvent,
  distanceKm?: number,
  radiusKm = 5,
): SimilarityScore {
  const reasons: string[] = [];
  let score = 0;

  if (candidate.venueId === other.venueId) {
    score += WEIGHTS.sameVenue;
    reasons.push('Même lieu');
  } else if (distanceKm !== undefined && radiusKm > 0) {
    const proximity = Math.max(0, 1 - distanceKm / radiusKm);
    if (proximity > 0) {
      score += WEIGHTS.nearbyVenue * proximity;
      reasons.push(`Lieu à ${formatKm(distanceKm)}`);
    }
  }

  const titleRatio = similarityRatio(candidate.title, other.title);
  score += WEIGHTS.title * titleRatio;
  if (titleRatio >= 0.5) {
    reasons.push(`Titre proche à ${percent(titleRatio)}`);
  }

  const descriptionRatio = similarityRatio(
    candidate.description.slice(0, DESCRIPTION_COMPARE_LENGTH),
    other.description.slice(0, DESCRIPTION_COMPARE_LENGTH),
  );
  score += WEIGHTS.description * descriptionRatio;
  if (descriptionRatio >= 0.7) {
    reasons.push(`Description proche à ${percent(descriptionRatio)}`);
  }

  if (candidate.categoryId === other.categoryId) {
    score += WEIGHTS.sameCategory;
    reasons.push('Même catégorie');
  }

  if (candidate.createdById === other.createdById) {
    score += WEIGHTS.sameAuthor;
    reasons.push('Même auteur');
  }

  // Les dates arbitrent en dernier, sur le total : elles font pencher la
  // balance dans les deux sens plutôt que d'ajouter un simple bonus.
  if (periodsOverlap(candidate, other)) {
    score += WEIGHTS.dateOverlap;
    reasons.push('Périodes qui se chevauchent');
  } else {
    score *= NO_OVERLAP_DAMPING;
    reasons.push('Périodes différentes');
  }

  return {
    score: Math.round(Math.min(100, score)),
    reasons,
    distanceKm: candidate.venueId === other.venueId ? undefined : distanceKm,
  };
}

export interface RankOptions {
  /** Rayon ayant servi à calculer les distances, pour noter la proximité. */
  radiusKm: number;
  /** Score minimal pour être proposé au modérateur. */
  minScore: number;
  /** Nombre maximal de sorties renvoyées. */
  limit: number;
}

/**
 * Note tous les candidats face à la sortie examinée et garde les plus proches,
 * du plus ressemblant au moins ressemblant.
 */
export function rankSimilar<T extends ComparableEvent>(
  event: ComparableEvent,
  candidates: T[],
  distanceByVenueId: Map<number, number>,
  { radiusKm, minScore, limit }: RankOptions,
): { event: T; similarity: SimilarityScore }[] {
  return candidates
    .map((candidate) => ({
      event: candidate,
      similarity: scoreSimilarity(
        event,
        candidate,
        distanceByVenueId.get(candidate.venueId),
        radiusKm,
      ),
    }))
    .filter(({ similarity }) => similarity.score >= minScore)
    .sort((a, b) => b.similarity.score - a.similarity.score)
    .slice(0, limit);
}
