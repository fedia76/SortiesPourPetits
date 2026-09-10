/**
 * Les motifs de refus, et l'étage du scraper que chacun met en cause.
 *
 * Un motif de refus n'apprend quelque chose que s'il **désigne un étage**.
 * « mauvaise sortie » ne se corrige nulle part ; « la ville est fausse » se
 * corrige à l'étage 6, et « le lien ne mène pas à cette sortie » à l'étage 7.
 * C'est cette règle, et elle seule, qui a décidé de la liste — pas le désir
 * d'être exhaustif, que le texte libre couvre déjà.
 *
 * Le libellé et l'imputation vivent ici plutôt que dans le client : la page de
 * qualité groupe les refus par étage, et deux tables à tenir en parallèle
 * auraient divergé au premier motif ajouté.
 */

import { RejectionCode } from '@prisma/client';

/** Un étage du pipeline, tel que `sortiesbot/stages/__init__.py` le numérote. */
export interface BlamedStage {
  /** L'identifiant stable côté scraper : `identify`, `extract`, `attribute`… */
  stage: string;
  number: number;
  label: string;
}

const STAGES: Record<string, BlamedStage> = {
  discovery: { stage: 'discovery', number: 1, label: 'Découverte' },
  identify: { stage: 'identify', number: 2, label: 'Reconnaissance' },
  harvest: { stage: 'harvest', number: 3, label: 'Dépouillement' },
  select: { stage: 'select', number: 4, label: 'Sélection' },
  read: { stage: 'read', number: 5, label: 'Lecture' },
  extract: { stage: 'extract', number: 6, label: 'Extraction' },
  attribute: { stage: 'attribute', number: 7, label: 'Attribution' },
  publish: { stage: 'publish', number: 8, label: 'Publication' },
};

export interface RejectionMeaning {
  code: RejectionCode;
  /** Ce que le modérateur lit sur la puce. Court : il clique, il ne lit pas. */
  label: string;
  /** La précision qu'on affiche au survol, quand la puce ne suffit pas. */
  hint: string;
  /**
   * Les étages mis en cause, du plus probable au moins probable. Vide pour
   * `AUTRE` et pour ce qui ne relève d'aucune brique — un doublon n'est la
   * faute de personne, c'est le dédoublonnage qui ne sait pas encore le voir.
   */
  blames: string[];
}

/**
 * L'ordre de cette liste est celui des puces dans la console : les motifs les
 * plus fréquents d'abord, `AUTRE` en dernier. Un modérateur qui refuse vingt
 * fiches ne doit pas chercher sa puce.
 */
export const REJECTION_MEANINGS: RejectionMeaning[] = [
  {
    code: RejectionCode.HORS_SUJET,
    label: 'Ce n’est pas une sortie',
    hint: 'La page n’annonçait pas un événement : article, page d’accueil, liste.',
    blames: ['identify', 'extract'],
  },
  {
    code: RejectionCode.PAS_POUR_ENFANTS,
    label: 'Pas pour les enfants',
    hint: 'C’est bien une sortie, mais elle ne s’adresse pas à ce public.',
    blames: ['extract', 'discovery'],
  },
  {
    code: RejectionCode.DATE_FAUSSE,
    label: 'Dates fausses',
    hint: 'Les dates ou les jours de représentation ne sont pas ceux de la page.',
    blames: ['extract'],
  },
  {
    code: RejectionCode.LIEU_FAUX,
    label: 'Lieu faux',
    hint: 'Le lieu, l’adresse ou la ville ne correspondent pas.',
    blames: ['extract'],
  },
  {
    code: RejectionCode.TARIF_FAUX,
    label: 'Tarif faux',
    hint: 'Le tarif annoncé n’est pas celui de la page.',
    blames: ['extract'],
  },
  {
    code: RejectionCode.DESCRIPTION_INUTILISABLE,
    label: 'Description inutilisable',
    hint: 'Texte tronqué, illisible, ou qui décrit autre chose que la sortie.',
    blames: ['read', 'extract'],
  },
  {
    code: RejectionCode.MAUVAIS_LIEN,
    label: 'Mauvais lien',
    hint: 'Le lien proposé ne mène pas à cette sortie.',
    blames: ['attribute'],
  },
  {
    code: RejectionCode.DOUBLON,
    label: 'Doublon',
    hint: 'La sortie est déjà au catalogue sous une autre adresse.',
    blames: [],
  },
  {
    code: RejectionCode.DEJA_PASSEE,
    label: 'Déjà passée',
    hint: 'La sortie était terminée au moment où elle a été proposée.',
    blames: ['publish'],
  },
  {
    code: RejectionCode.AUTRE,
    label: 'Autre',
    hint: 'Aucun étage en cause, ou plusieurs : le motif écrit fait foi.',
    blames: [],
  },
];

const BY_CODE = new Map(REJECTION_MEANINGS.map((m) => [m.code, m]));

export function meaningOf(code: RejectionCode): RejectionMeaning | undefined {
  return BY_CODE.get(code);
}

/** Le vocabulaire complet, tel que la console le reçoit et l'affiche. */
export function describeRejections() {
  return REJECTION_MEANINGS.map((m) => ({
    ...m,
    blames: m.blames.map((s) => STAGES[s]).filter((s): s is BlamedStage => Boolean(s)),
  }));
}

/**
 * Borne basse de l'intervalle de Wilson à 95 %, pour ordonner des taux dont
 * les effectifs n'ont rien à voir.
 *
 * C'est la précaution qui manque à tout tableau de bord : `3/3` affiche 100 %
 * et `40/50` en affiche 80, si bien qu'un domaine vu trois fois passe devant
 * un domaine éprouvé cinquante. La borne basse remet l'ordre à l'endroit —
 * 0,44 contre 0,67 — parce qu'elle dit ce qu'on sait, pas ce qu'on a vu.
 *
 * Elle ne remplace pas le plancher d'effectif : elle le complète. Un domaine
 * sous le plancher n'est pas mal classé, il n'est pas classé du tout.
 */
export function wilsonLowerBound(successes: number, total: number, z = 1.96): number {
  if (total <= 0) return 0;
  const p = successes / total;
  const z2 = z * z;
  const denominator = 1 + z2 / total;
  const centre = p + z2 / (2 * total);
  const margin = z * Math.sqrt((p * (1 - p) + z2 / (4 * total)) / total);
  return Math.max(0, (centre - margin) / denominator);
}
