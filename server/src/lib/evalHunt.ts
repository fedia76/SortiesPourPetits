/**
 * La chasse : ce qu'une précoche vaut, et comment on le compte.
 *
 * Une chasse lance les recherches de l'étage 1, ouvre ce qu'elles remontent,
 * et marque chaque page avec ce que l'étage 2 en pense. Un humain corrige ce
 * qui est faux et valide le reste — c'est le principe qui vaut déjà pour les
 * liens d'un agenda, « la brique précoche, l'humain corrige », appliqué un
 * étage plus haut.
 *
 * ## Le danger, et il n'est pas théorique
 *
 * Un corpus rempli en acceptant les propositions de la brique mesurerait la
 * brique **contre elle-même**. Le taux monterait à mesure qu'on valide vite,
 * sans qu'aucune page n'ait rien appris à personne, et rien dans un tableau de
 * bord ne distingue ce chiffre-là d'un vrai.
 *
 * C'est le travers que la provenance des champs d'une fiche nommait déjà —
 * `CORRIGE` contre `NON_CONTREDIT` —, et il est ici plus dangereux : il n'y a
 * qu'une seule étiquette à poser, donc un seul clic entre « j'ai vérifié » et
 * « j'ai laissé passer ».
 *
 * Deux règles en découlent, et ce fichier ne contient qu'elles :
 *
 * * une précoche **peut être vide**. Un étage 2 indécis ne propose rien, et la
 *   page attend un humain. Le pipeline, lui, tranche — il traite « inconnu »
 *   en agenda —, mais c'est une décision d'orchestration : la recopier
 *   écrirait au corpus ce que le pipeline *fait* au lieu de ce que la page
 *   *est*, c'est-à-dire exactement ce qu'on cherche à mesurer ;
 * * ce qu'un humain a corrigé se distingue pour toujours de ce qu'il a laissé
 *   passer. Les renseignements sont dans les `CORRIGE`.
 *
 * Du calcul pur, sans base de données : c'est ce qui permet de l'éprouver.
 */
import type { EvalNatureOrigin, EvalPageNature } from '@prisma/client';

/**
 * Ce que `classify.py` rend, traduit dans les natures du corpus.
 *
 * `inconnu` n'y figure pas, et c'est tout le sujet : ce n'est pas une nature,
 * c'est l'absence de réponse. Le pipeline lui donne un comportement — agenda —
 * que le corpus n'a pas à reprendre.
 */
const NATURES: Record<string, EvalPageNature> = {
  agenda: 'AGENDA',
  sortie: 'SORTIE',
  programme: 'PROGRAMME',
};

/** La précoche d'une page, ou `null` quand l'étage 2 n'a pas su trancher. */
export function natureProposee(kind: string): EvalPageNature | null {
  return NATURES[kind.trim().toLowerCase()] ?? null;
}

/**
 * D'où vient l'étiquette qu'un humain vient de poser.
 *
 * Trois cas, et le troisième est celui qui compte :
 *
 * * rien n'était proposé — l'humain a tranché seul : `SAISIE` ;
 * * l'étage 2 proposait autre chose : `CORRIGE`. La plus forte des trois,
 *   parce qu'elle est **indépendante** de ce que la brique pensait ;
 * * l'étage 2 proposait ceci, et on l'a laissé passer : `NON_CONTREDIT`. Elle
 *   vaut — il faut des cas où la brique a raison — mais une mesure calculée
 *   surtout sur celles-là est flatteuse par construction.
 */
export function origineDe(
  proposee: EvalPageNature | null,
  choisie: EvalPageNature,
): EvalNatureOrigin {
  if (proposee === null) return 'SAISIE';
  return proposee === choisie ? 'NON_CONTREDIT' : 'CORRIGE';
}

/** Ce qu'une chasse a donné, et ce qu'elle doit encore à un humain. */
export interface ComptesChasse {
  /** Candidates rapportées, quelle qu'en soit la suite. */
  total: number;
  enAttente: number;
  retenues: number;
  ecartees: number;
  /** Rapportées sans précoche : l'étage 2 n'a pas su. */
  indecises: number;
  /**
   * Injoignables ce jour-là. Elles sont rapportées quand même — l'adresse vaut
   * d'être vue —, et la file de capture les gèlera si on les retient.
   */
  injoignables: number;
}

export function comptesChasse(
  pages: { decision: string; proposed: EvalPageNature | null; error: string }[],
): ComptesChasse {
  return {
    total: pages.length,
    enAttente: pages.filter((p) => p.decision === 'EN_ATTENTE').length,
    retenues: pages.filter((p) => p.decision === 'RETENUE').length,
    ecartees: pages.filter((p) => p.decision === 'ECARTEE').length,
    indecises: pages.filter((p) => p.proposed === null).length,
    injoignables: pages.filter((p) => p.error !== '').length,
  };
}

/**
 * Ce que vaut le corpus de l'étage 2, du point de vue de son indépendance.
 *
 * Le chiffre à regarder n'est pas la taille du corpus mais la part de ce qui
 * ne vient **pas** de la brique : les saisies et les corrections. Si elle
 * s'effondre, le corpus a beau grossir, il ne mesure plus rien — il enregistre
 * ce que l'étage 2 pensait, et le lui ressert.
 */
export interface SoucheCorpus {
  total: number;
  saisies: number;
  corriges: number;
  nonContredits: number;
  /** Part de ce qui ne vient pas de la brique, entre 0 et 1. `null` si vide. */
  independance: number | null;
}

export function soucheCorpus(rows: { origin: EvalNatureOrigin }[]): SoucheCorpus {
  const saisies = rows.filter((r) => r.origin === 'SAISIE').length;
  const corriges = rows.filter((r) => r.origin === 'CORRIGE').length;
  const nonContredits = rows.filter((r) => r.origin === 'NON_CONTREDIT').length;
  return {
    total: rows.length,
    saisies,
    corriges,
    nonContredits,
    independance: rows.length ? (saisies + corriges) / rows.length : null,
  };
}
