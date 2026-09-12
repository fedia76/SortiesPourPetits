/**
 * Reprend les étiquettes de l'ancien banc d'extraction dans le corpus.
 *
 *     npm run db:backfill-eval
 *
 * L'ancien banc stockait des verdicts — « le tarif rendu est JUSTE » — qui ne
 * veulent rien dire sans la fiche qu'ils jugeaient, et qui périment au premier
 * changement de prompt. Le corpus stocke ce que la page **annonce**, qui vaut
 * pour toujours et contre lequel n'importe quel run se compare tout seul.
 *
 * Un seul verdict est convertible, et c'est logique : `JUSTE` dit que la
 * valeur rendue était celle de la page, donc il la livre. `FAUX`, `INVENTE` et
 * `MANQUE` disaient que la brique s'était trompée sans jamais enregistrer ce
 * qu'il aurait fallu trouver — ils sont perdus comme étiquettes, et c'est
 * précisément le défaut que la séparation corrige.
 *
 * Idempotent : une fiche déjà au corpus n'est pas retouchée. On peut donc le
 * relancer sans risque, et le laisser dans un déploiement.
 */
import { PrismaClient } from '@prisma/client';
import { ASPECTS, type FicheRendue } from '../src/lib/evalMetrics';

const prisma = new PrismaClient();

/** Une ligne de l'ancienne table, telle que la migration 0025 l'a laissée. */
interface LegacyRow {
  sortieId: number;
  createdById: number;
  /** La fiche rendue par la brique, **structurée**. Elle était là depuis le début. */
  fiche: string;
  aspects: string;
  verdicts: string;
  note: string;
  labelledAt: Date;
}

function parse<T>(raw: string, fallback: T): T {
  try {
    const value = JSON.parse(raw) as unknown;
    return value === null || value === undefined ? fallback : (value as T);
  } catch {
    // Un JSON illisible n'est pas une raison d'arrêter la reprise : cette
    // fiche-là n'a pas d'étiquette convertible, les suivantes peut-être.
    return fallback;
  }
}

/**
 * Ce que la page annonce, d'après les seuls aspects jugés justes.
 *
 * On lit la fiche **structurée** de l'ancien run, pas les libellés que
 * `audit_fiche` calculait pour l'affichage : une étiquette porte des faits, et
 * relire de la prose pour en tirer des faits est exactement ce qu'on a arrêté
 * de faire. Les champs se recopient donc tels quels.
 *
 * Le filtre reste le même : seul un aspect jugé `JUSTE` livre une étiquette.
 * `FAUX`, `INVENTE` et `MANQUE` disaient que la brique s'était trompée sans
 * jamais enregistrer ce qu'il aurait fallu trouver — ils restent perdus, et
 * c'est précisément le défaut que la séparation corrige.
 */
export function expectedFrom(ficheRaw: string, verdictsRaw: string): FicheRendue {
  const fiche = parse<Record<string, unknown>>(ficheRaw, {});
  const verdicts = parse<Record<string, string>>(verdictsRaw, {});
  const expected: Record<string, unknown> = {};
  for (const aspect of ASPECTS) {
    if (verdicts[aspect.key] !== 'JUSTE') continue;
    for (const [champ] of aspect.champs) {
      // Un champ absent de l'ancienne fiche reste absent : la clé dirait
      // « quelqu'un a regardé » alors que personne n'a rien enregistré.
      if (champ in fiche) expected[champ] = fiche[champ];
    }
  }
  return expected as FicheRendue;
}

/**
 * La table où l'étiquette atterrit a changé depuis, et ce script visait encore
 * l'ancienne : `EvalFiche` a été fusionnée dans `EvalSortie.expected` par la
 * migration « une sortie, une étiquette », puis supprimée. Le script ne pouvait
 * donc plus que planter — et comme `scripts/` n'était pas typé, rien ne le
 * disait.
 *
 * Il écrit maintenant là où l'étiquette vit, et **seulement** sur une sortie qui
 * n'en a pas : une étiquette saisie depuis vaut mieux qu'une reprise, et on ne
 * l'écrase pas.
 */
async function main(): Promise<void> {
  const legacy = await prisma.$queryRaw<LegacyRow[]>`
    SELECT
      l.sortieId     AS sortieId,
      l.createdById  AS createdById,
      l.fiche        AS fiche,
      l.aspects      AS aspects,
      l.verdicts     AS verdicts,
      l.note         AS note,
      IFNULL(l.validatedAt, l.createdAt) AS labelledAt
    FROM \`_LegacyEvalExtraction\` l
    JOIN \`EvalSortie\` s ON s.id = l.sortieId
    WHERE s.expected = '{}' OR s.expected = '' OR s.expected IS NULL
  `;

  if (legacy.length === 0) {
    console.log('Rien à reprendre : le corpus des sorties est à jour.');
    return;
  }

  let written = 0;
  let empty = 0;
  for (const row of legacy) {
    const expected = expectedFrom(row.fiche, row.verdicts);
    if (Object.keys(expected).length === 0) {
      // Aucun aspect n'avait été jugé juste : il n'y a rien à décrire de cette
      // page. Écrire un objet vide ferait croire à une étiquette.
      empty += 1;
      continue;
    }
    await prisma.evalSortie.update({
      where: { id: row.sortieId },
      data: {
        expected: JSON.stringify(expected),
        // Chaque champ vient d'un aspect qu'un humain avait jugé juste : c'est
        // une saisie, la provenance la plus forte qu'on ait.
        origins: JSON.stringify(
          Object.fromEntries(Object.keys(expected).map((cle) => [cle, 'SAISIE'])),
        ),
        note: row.note ?? '',
        labelledAt: row.labelledAt,
        labelledById: row.createdById,
      },
    });
    written += 1;
  }

  console.log(
    `${written} étiquette(s) reprise(s) au corpus` +
      (empty ? `, ${empty} sans aucun aspect jugé juste — rien à en tirer.` : '.'),
  );
}

main()
  .catch((err) => {
    console.error('Reprise impossible :', err);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
