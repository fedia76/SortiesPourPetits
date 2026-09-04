/**
 * Le classement d'une recherche de sorties : ce qui remonte, et pourquoi.
 *
 * Les résultats étaient rendus par date de début croissante. C'est un ordre
 * honnête, mais ce n'est pas une réponse à la question qu'on pose : un parent
 * qui cherche pour un enfant de quatre ans veut d'abord ce qui est **fait pour
 * lui**, et d'abord ce qui **ne repassera pas**.
 *
 * Trois mesures, dans cet ordre d'importance, et un score qui les mêle :
 *
 * 1. **la précision de l'âge** — « 3 à 5 ans » est fait pour un enfant de
 *    quatre ans, « 0 à 12 ans » l'accepte. La recherche gardait déjà les deux ;
 *    elle sait maintenant lequel des deux répond ;
 * 2. **la brièveté de la période** — une journée, un week-end, contre deux
 *    mois d'affiche. Le second sera encore là dans trois semaines ;
 * 3. **l'imminence** — à cadrage égal, ce qui a lieu bientôt d'abord.
 *
 * ## Pourquoi un score et non trois tris enchaînés
 *
 * Un tri lexicographique sur la précision de l'âge ferait basculer tout le
 * classement pour deux ans d'écart de tranche : « 3 à 5 » passerait devant
 * « 3 à 6 » quelles que soient leurs dates, et une sortie ponctuelle de ce
 * week-end se retrouverait sous une sortie tout-public de l'an prochain.
 *
 * Les poids disent donc l'ordre d'importance, pas une hiérarchie absolue. Une
 * sortie tout public d'un seul jour peut passer devant une sortie très ciblée
 * qui dure deux mois — et c'est voulu : la seconde sera encore là au prochain
 * passage, la première non.
 */

/** Ce qu'il faut d'une sortie pour la classer. Rien de plus n'est lu. */
export interface Rankable {
  id: number;
  ageMin: number | null;
  ageMax: number | null;
  isPermanent: boolean;
  dateStart: Date | null;
  dateEnd: Date | null;
}

/** Ce que la recherche demandait, et depuis quand elle regarde. */
export interface RankContext {
  /** L'âge de l'enfant, s'il a été précisé. Sans lui, ce critère se tait. */
  age?: number;
  /** Le premier jour de la fenêtre — aujourd'hui par défaut. `2026-09-20`. */
  from: string;
}

/**
 * L'âge le plus élevé qu'une fiche puisse annoncer (`ageMax` va jusqu'à 18).
 * Sert d'étendue de référence : une tranche non renseignée s'ouvre à tous,
 * donc elle est la moins précise qui soit, pas la plus.
 */
const AGE_SPAN_MAX = 18;

/**
 * Les poids. Leur rapport est tout ce qui compte : l'âge pèse deux fois la
 * brièveté, qui pèse une fois et demie l'imminence.
 */
const WEIGHT_AGE = 6;
const WEIGHT_BREVITY = 3;
const WEIGHT_SOON = 2;

/**
 * Demi-vie de la brièveté, en jours. Une sortie d'une semaine vaut la moitié
 * d'une sortie d'un jour ; un mois, le cinquième.
 */
const BREVITY_HALF_LIFE = 7;

/**
 * Demi-vie de l'imminence, en jours. Deux semaines : au-delà, l'écart entre
 * « dans trois mois » et « dans quatre » ne veut plus dire grand-chose pour
 * qui cherche une sortie.
 */
const SOON_HALF_LIFE = 14;

const DAY_MS = 24 * 60 * 60 * 1000;

/** Le jour `2026-09-20` en instant, sans décalage : ces colonnes sont des DATE. */
function dayValue(iso: string): number {
  return Date.parse(`${iso}T00:00:00.000Z`);
}

/** Écart en jours entiers, jamais négatif. */
function daysBetween(from: number, to: number): number {
  return Math.max(0, Math.round((to - from) / DAY_MS));
}

/**
 * Une décroissance douce, de 1 à 0, qui vaut ½ à sa demi-vie.
 *
 * Préférée à un palier : deux sorties qui se ressemblent doivent se classer
 * l'une près de l'autre, sans qu'un jour d'écart les sépare d'un cran.
 */
function decay(days: number, halfLife: number): number {
  return halfLife / (halfLife + Math.max(0, days));
}

/**
 * À quel point la tranche d'âge vise **cet** enfant. De 0 à 1.
 *
 * Seule l'étendue compte, pas le centrage : « à partir de 4 ans » et
 * « 4 à 16 ans » disent la même chose — la sortie accepte l'enfant sans être
 * pensée pour lui. Une tranche absente vaut « ouvert à tous », donc zéro : le
 * filtre l'a gardée, le classement ne la met pas en avant.
 */
export function agePrecision(event: Rankable): number {
  const low = event.ageMin ?? 0;
  const high = event.ageMax ?? AGE_SPAN_MAX;
  const span = Math.min(AGE_SPAN_MAX, Math.max(0, high - low));
  return 1 - span / AGE_SPAN_MAX;
}

/**
 * À quel point la sortie est **rare**. De 0 à 1.
 *
 * C'est la durée de l'affiche qui est lue, pas le nombre de représentations :
 * un spectacle joué tous les dimanches de juillet et d'août reste une offre
 * qui dure deux mois, et c'est cette disponibilité-là qu'on compare. Une
 * sortie permanente est le cas limite : elle ne finit jamais.
 */
export function brevity(event: Rankable): number {
  if (event.isPermanent || !event.dateStart || !event.dateEnd) return 0;
  const days = daysBetween(event.dateStart.getTime(), event.dateEnd.getTime()) + 1;
  return decay(days - 1, BREVITY_HALF_LIFE);
}

/**
 * À quel point c'est pour bientôt. De 0 à 1.
 *
 * Comptée depuis le début de la fenêtre demandée, pas depuis aujourd'hui :
 * une recherche pour les vacances de février ne doit pas ranger février par
 * ordre d'éloignement de septembre. Une sortie déjà commencée, ou permanente,
 * a lieu maintenant.
 */
export function imminence(event: Rankable, from: string): number {
  if (event.isPermanent || !event.dateStart) return 1;
  return decay(daysBetween(dayValue(from), event.dateStart.getTime()), SOON_HALF_LIFE);
}

/** Le score d'une sortie pour cette recherche. Plus il est haut, plus haut elle sort. */
export function relevance(event: Rankable, ctx: RankContext): number {
  // Sans âge demandé, ce critère ne dit rien : il se tait au lieu de départager
  // au hasard, et le classement se joue sur la période.
  const age = ctx.age === undefined ? 0 : WEIGHT_AGE * agePrecision(event);
  return age + WEIGHT_BREVITY * brevity(event) + WEIGHT_SOON * imminence(event, ctx.from);
}

/**
 * Les sorties, classées. Rend les identifiants dans l'ordre d'affichage.
 *
 * Le classement se fait ici et non en SQL : le score mêle trois mesures dont
 * deux dépendent de la requête, et l'écrire en base reviendrait à recopier ces
 * règles dans un langage où personne n'irait les relire. Le volume s'y prête —
 * une recherche porte sur les sorties à venir d'une zone, pas sur un catalogue.
 *
 * Les ex æquo sont départagés par la date puis par l'identifiant : sans cet
 * ordre total, deux pages successives pourraient montrer deux fois la même
 * sortie, ou en sauter une.
 */
export function rankEvents(events: Rankable[], ctx: RankContext): number[] {
  return events
    .map((event) => ({
      id: event.id,
      score: relevance(event, ctx),
      at: event.dateStart ? event.dateStart.getTime() : Number.POSITIVE_INFINITY,
    }))
    .sort((a, b) => b.score - a.score || a.at - b.at || a.id - b.id)
    .map((row) => row.id);
}
