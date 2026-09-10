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

const prisma = new PrismaClient();

/** Un aspect tel que `evaluation.audit_fiche` le rend. */
interface Aspect {
  key?: unknown;
  value?: unknown;
}

/** Une ligne de l'ancienne table, telle que la migration 0025 l'a laissée. */
interface LegacyRow {
  readingId: number;
  createdById: number;
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

/** Ce que la page annonce, d'après les seuls aspects jugés justes. */
export function expectedFrom(aspectsRaw: string, verdictsRaw: string): Record<string, string> {
  const aspects = parse<Aspect[]>(aspectsRaw, []);
  const verdicts = parse<Record<string, string>>(verdictsRaw, {});
  const expected: Record<string, string> = {};
  for (const aspect of Array.isArray(aspects) ? aspects : []) {
    const key = typeof aspect?.key === 'string' ? aspect.key : '';
    if (!key || verdicts[key] !== 'JUSTE') continue;
    // Une valeur vide jugée juste est une étiquette de plein droit : « la page
    // n'en dit rien ». C'est elle qui permettra de reconnaître une valeur
    // inventée, et la perdre reviendrait à ne plus pouvoir le faire.
    expected[key] = typeof aspect.value === 'string' ? aspect.value : '';
  }
  return expected;
}

async function main(): Promise<void> {
  const legacy = await prisma.$queryRaw<LegacyRow[]>`
    SELECT
      l.readingId    AS readingId,
      l.createdById  AS createdById,
      l.aspects      AS aspects,
      l.verdicts     AS verdicts,
      l.note         AS note,
      IFNULL(l.validatedAt, l.createdAt) AS labelledAt
    FROM \`_LegacyEvalExtraction\` l
    LEFT JOIN \`EvalFiche\` f ON f.readingId = l.readingId
    WHERE f.id IS NULL
  `;

  if (legacy.length === 0) {
    console.log('Rien à reprendre : le corpus des fiches est à jour.');
    return;
  }

  let written = 0;
  let empty = 0;
  for (const row of legacy) {
    const expected = expectedFrom(row.aspects, row.verdicts);
    if (Object.keys(expected).length === 0) {
      // Aucun aspect n'avait été jugé juste : il n'y a rien à décrire de cette
      // page. Créer une ligne vide ferait croire à une étiquette.
      empty += 1;
      continue;
    }
    await prisma.evalFiche.create({
      data: {
        readingId: row.readingId,
        createdById: row.createdById,
        expected: JSON.stringify(expected),
        note: row.note ?? '',
        labelledAt: row.labelledAt,
      },
    });
    written += 1;
  }

  console.log(
    `${written} fiche(s) reprise(s) au corpus` +
      (empty ? `, ${empty} sans aucun aspect jugé juste — rien à en tirer.` : '.'),
  );
}

main()
  .catch((err) => {
    console.error('Reprise impossible :', err);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
