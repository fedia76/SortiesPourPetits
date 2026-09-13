/**
 * Ce qu'un travail du banc en cours donne à voir, et ce qu'on fait de celui
 * qui ne donne plus rien.
 *
 * Deux manques qui n'en font qu'un : la console ne savait afficher d'un run
 * que son statut. Pas son avancement — donc quinze minutes sans rien voir
 * bouger ne disaient rien, et surtout pas s'il fallait s'inquiéter. Pas sa
 * vitalité non plus — donc un worker tué en plein travail laissait la ligne
 * « en cours » jusqu'à ce qu'un humain la close à la main en base.
 *
 * Les deux se répondent : compter ce qui est fait rend le run lisible, et
 * dater le dernier signe de vie rend le run mortel.
 */
import { EvalStage } from '@prisma/client';
import { prisma } from '../db';

/**
 * L'écart au-delà duquel un travail est réputé mort.
 *
 * Ce n'est **pas** une durée maximale de run : un étage 6 sur deux cents
 * sorties dure des heures, et c'est normal. C'est l'écart maximal entre deux
 * battements, et lui se borne — un battement tombe à chaque entrée réclamée.
 *
 * Le pire cas honnête est un appel de modèle qui va au bout de ses reprises :
 * 300 s de délai d'attente, trois tentatives (le SDK en ajoute deux par
 * défaut), soit un quart d'heure sur une seule entrée. Trente minutes laissent
 * donc le double de cette marge. Réduire ce plafond côté worker rendrait ce
 * seuil-ci plus serré, et c'est dans cet ordre-là qu'il faut le faire : tuer
 * un run honnête coûte plus cher que d'en laisser traîner un mort une
 * demi-heure de plus.
 */
export const ABANDON_APRES_MS = 30 * 60 * 1000;

/**
 * Ce qu'on écrit dans `error` en reprenant un travail. Il doit se comprendre
 * seul, six mois plus tard, sans avoir cette page sous les yeux.
 */
export const MOTIF_ABANDON =
  'Repris par le site : le worker n’a plus donné signe de vie pendant plus de ' +
  '30 minutes, et n’a jamais clôturé ce travail. Rien n’a été mesuré au-delà ' +
  'de ce que la console affiche.';

/** Le dernier signe de vie d'un travail, ou rien s'il n'a jamais été réclamé. */
export function dernierSigneDeVie(travail: {
  startedAt: Date | null;
  heartbeatAt: Date | null;
}): Date | null {
  // La réclamation est un signe de vie de plein droit : elle vaut battement
  // pour les runs mis en file avant que cette colonne n'existe, qui la portent
  // nulle.
  return travail.heartbeatAt ?? travail.startedAt;
}

/**
 * Vrai si ce travail n'a plus donné signe de vie depuis trop longtemps.
 *
 * Un travail jamais réclamé n'est **pas** abandonné : il est en file, et une
 * file qui n'avance pas est un worker arrêté, pas un travail mort. Le confondre
 * mettrait en échec tout ce qui attend le redémarrage du service.
 */
export function abandonne(
  travail: { startedAt: Date | null; heartbeatAt: Date | null },
  maintenant: Date = new Date(),
): boolean {
  const dernier = dernierSigneDeVie(travail);
  if (!dernier) return false;
  return maintenant.getTime() - dernier.getTime() > ABANDON_APRES_MS;
}

/**
 * Le même « plus de signe de vie depuis trop longtemps » qu'`abandonne`, dit à
 * la base.
 *
 * Deux formulations d'une seule règle, et c'est un risque assumé : la base ne
 * sait pas exécuter une fonction TypeScript, et ramener toutes les lignes
 * `RUNNING` pour les filtrer en mémoire coûterait plus que ça ne rapporte. Le
 * test les confronte sur les mêmes cas, ce qui est la seule chose qui empêche
 * les deux de diverger.
 *
 * Nul sur `heartbeatAt` veut dire « réclamé avant que la colonne n'existe » :
 * on retombe alors sur la réclamation, qui est le premier battement.
 */
export interface CritereAbandon {
  OR: [{ heartbeatAt: { lt: Date } }, { heartbeatAt: null; startedAt: { lt: Date } }];
}

export function critereAbandon(maintenant: Date): CritereAbandon {
  const limite = new Date(maintenant.getTime() - ABANDON_APRES_MS);
  return {
    OR: [{ heartbeatAt: { lt: limite } }, { heartbeatAt: null, startedAt: { lt: limite } }],
  };
}

/**
 * Clôt en échec les runs et les chasses dont le worker a disparu.
 *
 * Appelée là où quelqu'un regarde — la console qui liste, le worker qui
 * réclame — plutôt que depuis une minuterie : une tâche de fond de plus pour
 * deux tables qu'on consulte dix fois par jour ne se justifie pas, et une
 * reprise qui n'arrive qu'au moment où l'on regarde arrive toujours à temps.
 */
export async function reprendreLesAbandonnes(
  maintenant: Date = new Date(),
): Promise<{ runs: number; hunts: number }> {
  const trop_vieux = critereAbandon(maintenant);
  const [runs, hunts] = await Promise.all([
    prisma.evalRun.updateMany({
      where: { status: 'RUNNING', ...trop_vieux },
      data: { status: 'FAILED', error: MOTIF_ABANDON, finishedAt: maintenant },
    }),
    prisma.evalHunt.updateMany({
      where: { status: 'RUNNING', ...trop_vieux },
      data: { status: 'FAILED', error: MOTIF_ABANDON, endedAt: maintenant },
    }),
  ]);
  return { runs: runs.count, hunts: hunts.count };
}

/**
 * Combien d'entrées du corpus chaque run a déjà traitées.
 *
 * Compté depuis ce que les runs ont **écrit**, jamais depuis un compteur tenu
 * à part : un compteur peut diverger de la table qu'il prétend résumer, et
 * c'est précisément ce qui rendrait l'affichage menteur au moment où on en a
 * besoin.
 *
 * Trois requêtes, quel que soit le nombre de runs — un appel par run ferait
 * grossir la console avec l'historique.
 */
export async function avancements(
  runs: { id: number; stage: EvalStage }[],
): Promise<Map<number, number>> {
  const faits = new Map<number, number>(runs.map((run) => [run.id, 0]));
  const ids = runs.map((run) => run.id);
  if (!ids.length) return faits;

  const liens = runs.filter((r) => r.stage === 'HARVEST' || r.stage === 'SELECT').map((r) => r.id);
  const lectures = runs.filter((r) => r.stage === 'READ').map((r) => r.id);
  const fiches = runs.filter((r) => r.stage === 'EXTRACT').map((r) => r.id);

  const [parPage, parLecture, parFiche] = await Promise.all([
    // Une page donne plusieurs liens : ce qu'on compte est la page, qui est
    // l'entrée du corpus, et non la ligne.
    liens.length
      ? prisma.evalLinkResult.groupBy({
          by: ['runId', 'pageId'],
          where: { runId: { in: liens } },
        })
      : [],
    lectures.length
      ? prisma.evalReadResult.groupBy({
          by: ['runId'],
          _count: { _all: true },
          where: { runId: { in: lectures } },
        })
      : [],
    fiches.length
      ? prisma.evalExtractResult.groupBy({
          by: ['runId'],
          _count: { _all: true },
          where: { runId: { in: fiches } },
        })
      : [],
  ]);

  for (const row of parPage) faits.set(row.runId, (faits.get(row.runId) ?? 0) + 1);
  for (const row of [...parLecture, ...parFiche]) faits.set(row.runId, row._count._all);
  return faits;
}
