/**
 * Ce qu'un modérateur a changé sur une fiche importée, champ par champ.
 *
 * Le taux d'approbation dit qu'une fiche était mauvaise. Il ne dit pas **en
 * quoi**, et c'est pourtant la seule chose qui permette de réparer quelque
 * chose : savoir que 40 % des fiches voient leur ville corrigée et aucune leur
 * titre désigne l'étage 6 et le champ à reprendre, là où un taux global
 * n'aurait jamais désigné personne.
 *
 * Le geste existe déjà — le modérateur corrige avant d'approuver. On se
 * contente de l'enregistrer, ce qui est la raison pour laquelle cette mesure
 * ne coûte rien à personne et ne périmera pas.
 *
 * Ce module est **pur** : il compare deux états et rend une liste. Ce qu'on en
 * fait, et les conditions étroites dans lesquelles on le fait, sont l'affaire
 * de l'appelant (voir `routes/events.ts`).
 */

/** Une fiche réduite aux champs que le scraper remplit et qu'on peut corriger. */
export interface ComparableEvent {
  title: string;
  description: string;
  sourceUrl: string | null;
  isFree: boolean;
  /** En euros. `null` pour une sortie gratuite. */
  price: number | null;
  ageMin: number | null;
  ageMax: number | null;
  isPermanent: boolean;
  /** `YYYY-MM-DD`, ou `null` pour une sortie permanente. */
  dateStart: string | null;
  dateEnd: string | null;
  openTime: string | null;
  closeTime: string | null;
  setting: string | null;
  categoryId: number;
  venueName: string;
  venueAddress: string;
  venueCity: string;
  venuePostalCode: string;
  /** Les jours de représentation, triés. Vide = toute la période. */
  dates: string[];
}

export interface Correction {
  field: string;
  before: string | null;
  after: string | null;
}

/** Tronqué au format de la colonne : on mesure une fréquence, pas un contenu. */
const MAX = 500;

function show(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (Array.isArray(value)) return value.length ? value.join(' ').slice(0, MAX) : null;
  const text = String(value).trim();
  return text ? text.slice(0, MAX) : null;
}

/**
 * Les champs comparés, dans l'ordre où la fiche les présente. La liste est
 * explicite plutôt que dérivée des clés de l'objet : un champ ajouté à la
 * fiche ne doit pas se mettre à compter dans la mesure sans qu'on l'ait voulu,
 * sous peine de faire bouger une série qu'on suit depuis des mois.
 */
const FIELDS: (keyof ComparableEvent)[] = [
  'title',
  'description',
  'sourceUrl',
  'isFree',
  'price',
  'ageMin',
  'ageMax',
  'isPermanent',
  'dateStart',
  'dateEnd',
  'openTime',
  'closeTime',
  'setting',
  'categoryId',
  'venueName',
  'venueAddress',
  'venueCity',
  'venuePostalCode',
  'dates',
];

/**
 * La description est le seul champ qu'on ne compare pas au caractère près.
 *
 * Un modérateur qui reprend une coquille ou coupe une phrase promotionnelle ne
 * dit pas que l'extraction s'est trompée ; s'il la réécrit, si. Le seuil est
 * grossier et il est assumé — mieux vaut rater quelques réécritures que
 * compter chaque virgule comme une erreur de l'étage 6, ce qui saturerait la
 * mesure et la rendrait muette.
 */
const DESCRIPTION_MIN_DELTA = 0.25;

function rewritten(before: string, after: string): boolean {
  const a = before.trim();
  const b = after.trim();
  if (a === b) return false;
  const longest = Math.max(a.length, b.length);
  if (longest === 0) return false;
  return Math.abs(a.length - b.length) / longest >= DESCRIPTION_MIN_DELTA;
}

/**
 * Ce qui a changé entre la fiche proposée et la fiche telle qu'elle est
 * enregistrée. Liste vide si rien n'a bougé — le cas le plus fréquent, et
 * celui qui compte le plus : une fiche approuvée sans retouche est la seule
 * preuve que l'étage 6 avait tout bon.
 */
export function diffEvent(before: ComparableEvent, after: ComparableEvent): Correction[] {
  const corrections: Correction[] = [];
  for (const field of FIELDS) {
    const from = before[field];
    const to = after[field];

    if (field === 'description') {
      if (rewritten(String(from ?? ''), String(to ?? ''))) {
        corrections.push({ field, before: show(from), after: show(to) });
      }
      continue;
    }
    if (field === 'dates') {
      const a = (from as string[]) ?? [];
      const b = (to as string[]) ?? [];
      if (a.length !== b.length || a.some((day, i) => day !== b[i])) {
        corrections.push({ field, before: show(a), after: show(b) });
      }
      continue;
    }
    if (from !== to) {
      corrections.push({ field, before: show(from), after: show(to) });
    }
  }
  return corrections;
}
