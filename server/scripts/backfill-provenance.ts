/**
 * Recopie la filiation des exécutions passées sur leurs items.
 *
 *     npm run db:backfill-provenance          # compte, n'écrit rien
 *     npm run db:backfill-provenance -- --apply
 *
 * `ScraperRunItem.agendaUrl` et `.query` ne sont renseignés qu'à la clôture
 * d'un run, par `freezeProvenance` (routes/scraper.ts). Les exécutions
 * antérieures à ce mécanisme portent donc deux colonnes vides — et comme le
 * panier « agendas déjà dépouillés » du banc se lit **sur ces colonnes**, il
 * affiche zéro alors que la production a validé des centaines de sorties.
 *
 * Rejouer les runs pour ça serait absurde : ça repaierait la recherche web et
 * les lectures LLM pour reconstruire une information qui est déjà là. Elle
 * l'est dans `ScraperRunLog`, d'où la clôture la tire — ce script fait donc
 * exactement ce que la clôture aurait fait, après coup, sans rien relire du
 * web.
 *
 * Ce qu'il ne peut pas réparer : un run dont le journal a été purgé (le bouton
 * « oublier le journal » de la console) n'a plus de filiation nulle part. Il
 * est compté et nommé, pour qu'on sache ce qui manque au lieu de le deviner.
 *
 * Idempotent : les mêmes lignes réécrites valent les mêmes valeurs. Les runs
 * déjà pourvus sont sautés, sauf `--force`.
 */
import { PrismaClient } from '@prisma/client';
import { TREE_MAX_ROWS } from '../src/lib/scraperTree';
import { groupProvenance, provenanceOf } from '../src/lib/scraperProvenance';

const prisma = new PrismaClient();

const apply = process.argv.includes('--apply');
const force = process.argv.includes('--force');

interface Bilan {
  runs: number;
  traites: number;
  dejaPourvus: number;
  sansJournal: number;
  sansFiliation: number;
  items: number;
  tronques: number[];
}

async function main(): Promise<void> {
  const runs = await prisma.scraperRun.findMany({
    select: { id: true, startedAt: true },
    orderBy: { id: 'asc' },
  });
  const bilan: Bilan = {
    runs: runs.length,
    traites: 0,
    dejaPourvus: 0,
    sansJournal: 0,
    sansFiliation: 0,
    items: 0,
    tronques: [],
  };

  for (const run of runs) {
    // Un run sans item n'a rien à recevoir ; un run déjà pourvu a été clos
    // après `freezeProvenance` et le rejouer ne changerait rien.
    const [items, pourvus] = await Promise.all([
      prisma.scraperRunItem.count({ where: { runId: run.id } }),
      prisma.scraperRunItem.count({
        where: {
          runId: run.id,
          AND: [{ agendaUrl: { not: null } }, { agendaUrl: { not: '' } }],
        },
      }),
    ]);
    if (items === 0) continue;
    if (pourvus > 0 && !force) {
      bilan.dejaPourvus += 1;
      continue;
    }

    const rows = await prisma.scraperRunLog.findMany({
      where: { runId: run.id },
      select: { seq: true, stage: true, kind: true, level: true, url: true, message: true, data: true },
      orderBy: { seq: 'asc' },
      take: TREE_MAX_ROWS,
    });
    if (rows.length === 0) {
      bilan.sansJournal += 1;
      console.log(`run ${run.id} — journal purgé, filiation irrécupérable (${items} item(s))`);
      continue;
    }
    // Le même plafond qu'à la clôture, et le même effet : au-delà, la queue du
    // journal manque et les dernières pages restent sans origine. On le dit
    // plutôt que de laisser croire le run complet.
    if (rows.length >= TREE_MAX_ROWS) bilan.tronques.push(run.id);

    const groupes = groupProvenance(provenanceOf(rows));
    if (groupes.length === 0) {
      bilan.sansFiliation += 1;
      continue;
    }

    let ecrits = 0;
    for (const groupe of groupes) {
      if (apply) {
        const { count } = await prisma.scraperRunItem.updateMany({
          where: { runId: run.id, url: { in: groupe.urls } },
          data: { agendaUrl: groupe.agendaUrl, query: groupe.query },
        });
        ecrits += count;
      } else {
        // Sans écrire : compter ce que l'`IN` toucherait réellement. Le journal
        // connaît des URL qui ne sont pas des items (liens écartés au tri), et
        // les annoncer gonflerait le bilan d'un tiers.
        ecrits += await prisma.scraperRunItem.count({
          where: { runId: run.id, url: { in: groupe.urls } },
        });
      }
    }
    bilan.traites += 1;
    bilan.items += ecrits;
    console.log(
      `run ${run.id} (${run.startedAt?.toISOString().slice(0, 10) ?? 'sans date'}) — ` +
        `${ecrits}/${items} item(s) ${apply ? 'pourvus' : 'à pourvoir'}, ` +
        `${groupes.length} provenance(s)`,
    );
  }

  console.log(
    `\n${bilan.runs} exécution(s) : ${bilan.traites} ${apply ? 'reprise(s)' : 'reprenable(s)'}, ` +
      `${bilan.items} item(s), ${bilan.dejaPourvus} déjà pourvue(s), ` +
      `${bilan.sansJournal} sans journal, ${bilan.sansFiliation} sans filiation lisible.`,
  );
  if (bilan.tronques.length) {
    console.log(
      `Journal tronqué à ${TREE_MAX_ROWS} lignes sur : ${bilan.tronques.join(', ')} — ` +
        'leurs dernières pages restent sans origine.',
    );
  }
  if (!apply) console.log('Rien n’a été écrit. Relancez avec --apply.');
}

main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
