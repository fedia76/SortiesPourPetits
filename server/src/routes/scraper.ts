import { Prisma, Role } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { deletePhoto } from '../lib/upload';
import { TREE_MAX_ROWS, buildTree } from '../lib/scraperTree';
import { requireRole } from '../middleware/auth';
import {
  checkScraperMode,
  scraperConfigSchema,
  scraperConfigUpdateSchema,
  scraperFinishSchema,
  scraperItemsSchema,
  scraperLogQuerySchema,
  scraperLogsSchema,
  scraperMemoryPurgeSchema,
  scraperMemorySchema,
  scraperRunSchema,
  scraperSeenSchema,
  scraperStatsSchema,
} from '../lib/validators';

export const scraperRouter = Router();

// Toute la console du scraper est réservée aux modérateurs — c'est aussi le
// rôle que porte la clé d'API du worker.
scraperRouter.use(requireRole(Role.MODERATOR));

/** Convertit les Decimal Prisma en nombres pour le JSON. */
function serializeConfig<T extends { maxCostUsd: Prisma.Decimal }>(config: T) {
  return { ...config, maxCostUsd: Number(config.maxCostUsd) };
}

function serializeRun<T extends { costUsd: Prisma.Decimal }>(run: T) {
  return { ...run, costUsd: Number(run.costUsd) };
}

// ------------------------------------------------------------ configurations

scraperRouter.get('/configs', async (_req, res) => {
  const configs = await prisma.scraperConfig.findMany({
    orderBy: { name: 'asc' },
    include: {
      _count: { select: { runs: true } },
      runs: {
        orderBy: { queuedAt: 'desc' },
        take: 1,
        select: { id: true, status: true, queuedAt: true, finishedAt: true, retained: true },
      },
    },
  });
  res.json({ configs: configs.map(serializeConfig) });
});

scraperRouter.post('/configs', async (req, res) => {
  const parsed = scraperConfigSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const invalide = checkScraperMode({
    mode: parsed.data.mode ?? 'recherche',
    seedUrls: parsed.data.seedUrls ?? '',
  });
  if (invalide) {
    res.status(400).json({ error: invalide });
    return;
  }
  try {
    const config = await prisma.scraperConfig.create({ data: parsed.data });
    res.status(201).json({ config: serializeConfig(config) });
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
      res.status(409).json({ error: 'Une configuration porte déjà ce nom' });
      return;
    }
    throw e;
  }
});

scraperRouter.patch('/configs/:id', async (req, res) => {
  const id = Number(req.params.id);
  const parsed = scraperConfigUpdateSchema.safeParse(req.body);
  if (!Number.isInteger(id) || !parsed.success) {
    res.status(400).json({ error: parsed.success ? 'Requête invalide' : parsed.error.issues[0].message });
    return;
  }
  // Le mode et les URLs se tiennent l'un l'autre, et une modification
  // partielle ne porte pas forcément les deux : on juge la ligne telle
  // qu'elle sera, pas seulement ce que la requête change.
  const actuelle = await prisma.scraperConfig.findUnique({ where: { id } });
  if (!actuelle) {
    res.status(404).json({ error: 'Configuration introuvable' });
    return;
  }
  const invalide = checkScraperMode({
    mode: parsed.data.mode ?? actuelle.mode,
    seedUrls: parsed.data.seedUrls ?? actuelle.seedUrls,
  });
  if (invalide) {
    res.status(400).json({ error: invalide });
    return;
  }
  try {
    const config = await prisma.scraperConfig.update({ where: { id }, data: parsed.data });
    res.json({ config: serializeConfig(config) });
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2025') {
      res.status(404).json({ error: 'Configuration introuvable' });
      return;
    }
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
      res.status(409).json({ error: 'Une configuration porte déjà ce nom' });
      return;
    }
    throw e;
  }
});

scraperRouter.delete('/configs/:id', async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  try {
    // Les runs et leurs lignes suivent (onDelete: Cascade) ; la mémoire des
    // pages, elle, est commune à toutes les configurations et survit.
    await prisma.scraperConfig.delete({ where: { id } });
    res.json({ ok: true });
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2025') {
      res.status(404).json({ error: 'Configuration introuvable' });
      return;
    }
    throw e;
  }
});

// ------------------------------------------------------------------- runs

/** Met une exécution en file. Le worker la prendra à son prochain passage. */
scraperRouter.post('/configs/:id/run', async (req, res) => {
  const configId = Number(req.params.id);
  const parsed = scraperRunSchema.safeParse(req.body ?? {});
  if (!Number.isInteger(configId) || !parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const config = await prisma.scraperConfig.findUnique({ where: { id: configId } });
  if (!config) {
    res.status(404).json({ error: 'Configuration introuvable' });
    return;
  }
  // Une exécution déjà en attente ou en cours suffit : en empiler d'autres ne
  // ferait que payer plusieurs fois la même recherche.
  const pending = await prisma.scraperRun.findFirst({
    where: { configId, status: { in: ['QUEUED', 'RUNNING'] } },
  });
  if (pending) {
    res.status(409).json({ error: 'Une exécution est déjà en attente pour cette configuration' });
    return;
  }
  const run = await prisma.scraperRun.create({
    data: { configId, submit: parsed.data.submit, requestedById: req.user!.id },
  });
  res.status(201).json({ run: serializeRun(run) });
});

scraperRouter.get('/runs', async (_req, res) => {
  const runs = await prisma.scraperRun.findMany({
    orderBy: { queuedAt: 'desc' },
    take: 50,
    include: {
      config: { select: { id: true, name: true } },
      requestedBy: { select: { id: true, displayName: true } },
    },
  });
  res.json({ runs: runs.map(serializeRun) });
});

scraperRouter.get('/runs/:id', async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const run = await prisma.scraperRun.findUnique({
    where: { id },
    include: {
      config: { select: { id: true, name: true } },
      requestedBy: { select: { id: true, displayName: true } },
      items: { orderBy: { at: 'asc' }, take: 500 },
    },
  });
  if (!run) {
    res.status(404).json({ error: 'Exécution introuvable' });
    return;
  }
  res.json({ run: serializeRun(run) });
});

/** Annule une exécution restée en file (worker arrêté, essai abandonné). */
scraperRouter.post('/runs/:id/cancel', async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const run = await prisma.scraperRun.findUnique({ where: { id } });
  if (!run) {
    res.status(404).json({ error: 'Exécution introuvable' });
    return;
  }
  if (run.status === 'DONE' || run.status === 'FAILED') {
    res.status(409).json({ error: 'Cette exécution est déjà terminée' });
    return;
  }
  const updated = await prisma.scraperRun.update({
    where: { id },
    data: { status: 'FAILED', error: 'Annulée depuis la console', finishedAt: new Date() },
  });
  res.json({ run: serializeRun(updated) });
});

// --------------------------------------------------------------- mémoire

/**
 * La mémoire des pages déjà analysées, telle quelle.
 *
 * C'est elle qui empêche de relire — donc de repayer — une page connue, et
 * qui évite de reproposer une sortie déjà refusée. Elle est commune à toutes
 * les configurations, d'où l'intérêt de pouvoir la regarder : une page qu'on
 * croit oubliée y est peut-être retenue par un verdict d'un autre run.
 */
scraperRouter.get('/memory', async (req, res) => {
  const parsed = scraperMemorySchema.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const { q, decision, page, pageSize } = parsed.data;
  const where: Prisma.ScrapedUrlWhereInput = {
    ...(decision ? { decision } : {}),
    ...(q ? { OR: [{ url: { contains: q } }, { title: { contains: q } }] } : {}),
  };

  const [total, entries, byDecision] = await Promise.all([
    prisma.scrapedUrl.count({ where }),
    prisma.scrapedUrl.findMany({
      where,
      orderBy: { lastSeen: 'desc' },
      skip: (page - 1) * pageSize,
      take: pageSize,
      include: { event: { select: { id: true, title: true, status: true } } },
    }),
    // Les verdicts et leur poids, sur toute la mémoire et non sur le filtre
    // courant : c'est ce qui permet de purger le bon lot plutôt que tout.
    prisma.scrapedUrl.groupBy({
      by: ['decision'],
      _count: { _all: true },
      orderBy: { _count: { decision: 'desc' } },
    }),
  ]);

  res.json({
    entries,
    total,
    page,
    pageSize,
    decisions: byDecision.map((d) => ({ decision: d.decision, count: d._count._all })),
  });
});

/**
 * Oublie des pages.
 *
 * Sans `decision`, toute la mémoire part : le prochain run relira chaque page
 * connue, la repaiera, et reproposera ce qui avait déjà été proposé. Avec,
 * on n'oublie qu'un verdict — les erreurs de lecture d'un site alors en
 * panne, par exemple, sans toucher à ce qui est déjà au catalogue.
 */
scraperRouter.delete('/memory', async (req, res) => {
  const parsed = scraperMemoryPurgeSchema.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const { decision } = parsed.data;
  const { count } = await prisma.scrapedUrl.deleteMany({
    where: decision ? { decision } : {},
  });
  res.json({ ok: true, deleted: count });
});

// ------------------------------------------------------------ statistiques

/** Les compteurs bruts de MySQL arrivent en BigInt : le JSON n'en veut pas. */
function count(value: unknown): number {
  return Number(value ?? 0);
}

/**
 * Tableau de bord du scraping.
 *
 * Deux questions, et une seule table pour y répondre — `ScraperRunItem`, qui
 * garde l'URL de chaque page traitée et la sortie qui en est née :
 *
 * - **d'où vient ce qu'on ramène** : la part de chaque domaine source, avec
 *   ce qu'il a réellement donné (proposé, puis approuvé) et pas seulement ce
 *   qu'il a coûté à lire — un agenda qui fournit cent pages pour deux sorties
 *   n'est pas une bonne source ;
 * - **de quoi le catalogue est fait** : la part de chaque catégorie, qui dit
 *   ce que les recherches en place laissent de côté.
 *
 * `configId` restreint à une recherche ; sans lui, tout est confondu. Le
 * domaine est tiré de l'URL en SQL (`SUBSTRING_INDEX`) : le faire en JS
 * obligerait à rapatrier toutes les lignes du journal.
 */
scraperRouter.get('/stats', async (req, res) => {
  const parsed = scraperStatsSchema.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const { configId, days } = parsed.data;

  let config = null;
  if (configId !== undefined) {
    config = await prisma.scraperConfig.findUnique({
      where: { id: configId },
      select: { id: true, name: true },
    });
    if (!config) {
      res.status(404).json({ error: 'Configuration introuvable' });
      return;
    }
  }

  const since = days === undefined ? null : new Date(Date.now() - days * 86_400_000);
  const runWhere: Prisma.ScraperRunWhereInput = {
    ...(configId === undefined ? {} : { configId }),
    ...(since === null ? {} : { queuedAt: { gte: since } }),
  };
  // Les mêmes bornes, en SQL, pour les deux agrégats qui passent par du brut.
  const scope = Prisma.sql`
    ${configId === undefined ? Prisma.empty : Prisma.sql`AND r.configId = ${configId}`}
    ${since === null ? Prisma.empty : Prisma.sql`AND r.queuedAt >= ${since}`}
  `;

  const [runs, byDecision, domains, categories, statuses, perConfig] = await Promise.all([
    prisma.scraperRun.aggregate({
      where: runWhere,
      _count: { _all: true },
      _sum: {
        candidates: true,
        pages: true,
        retained: true,
        submitted: true,
        costUsd: true,
        inputTokens: true,
        outputTokens: true,
        webSearches: true,
      },
    }),

    prisma.scraperRunItem.groupBy({
      by: ['decision'],
      where: { run: runWhere },
      _count: { _all: true },
      orderBy: { _count: { decision: 'desc' } },
    }),

    // `www.` retiré et casse uniformisée : sans ça, le même site compte deux
    // fois et sa part est fausse.
    prisma.$queryRaw<
      { domain: string; pages: bigint; submitted: bigint; approved: bigint }[]
    >`
      SELECT
        LOWER(TRIM(LEADING 'www.' FROM
          SUBSTRING_INDEX(SUBSTRING_INDEX(SUBSTRING_INDEX(i.url, '://', -1), '/', 1), ':', 1)
        )) AS domain,
        COUNT(*) AS pages,
        COUNT(DISTINCT i.eventId) AS submitted,
        COUNT(DISTINCT CASE WHEN e.status = 'APPROVED' THEN e.id END) AS approved
      FROM ScraperRunItem i
      JOIN ScraperRun r ON r.id = i.runId
      LEFT JOIN Event e ON e.id = i.eventId
      WHERE 1 = 1 ${scope}
      GROUP BY domain
      ORDER BY pages DESC
      LIMIT 100
    `,

    // Une sortie peut être journalisée par plusieurs lignes (deux runs qui
    // retombent dessus) : elle ne doit compter qu'une fois dans sa catégorie.
    prisma.$queryRaw<
      { id: number; name: string; events: bigint; approved: bigint }[]
    >`
      SELECT
        c.id AS id,
        c.name AS name,
        COUNT(DISTINCT e.id) AS events,
        COUNT(DISTINCT CASE WHEN e.status = 'APPROVED' THEN e.id END) AS approved
      FROM ScraperRunItem i
      JOIN ScraperRun r ON r.id = i.runId
      JOIN Event e ON e.id = i.eventId
      JOIN Category c ON c.id = e.categoryId
      WHERE 1 = 1 ${scope}
      GROUP BY c.id, c.name
      ORDER BY events DESC
    `,

    // Ce que la modération a fait des sorties importées : le taux
    // d'approbation est la mesure de qualité d'une recherche.
    prisma.$queryRaw<{ status: string; events: bigint }[]>`
      SELECT e.status AS status, COUNT(DISTINCT e.id) AS events
      FROM ScraperRunItem i
      JOIN ScraperRun r ON r.id = i.runId
      JOIN Event e ON e.id = i.eventId
      WHERE 1 = 1 ${scope}
      GROUP BY e.status
    `,

    // Le tableau par recherche ne dépend pas du périmètre choisi : c'est lui
    // qui sert à comparer les configurations entre elles.
    prisma.scraperRun.groupBy({
      by: ['configId'],
      where: since === null ? {} : { queuedAt: { gte: since } },
      _count: { _all: true },
      _sum: { retained: true, submitted: true, pages: true, costUsd: true },
    }),
  ]);

  const names = new Map(
    (await prisma.scraperConfig.findMany({ select: { id: true, name: true } })).map((c) => [
      c.id,
      c.name,
    ]),
  );

  res.json({
    scope: { configId: config?.id ?? null, configName: config?.name ?? null, days: days ?? null },
    totals: {
      runs: runs._count._all,
      candidates: runs._sum.candidates ?? 0,
      pages: runs._sum.pages ?? 0,
      retained: runs._sum.retained ?? 0,
      submitted: runs._sum.submitted ?? 0,
      costUsd: Number(runs._sum.costUsd ?? 0),
      inputTokens: runs._sum.inputTokens ?? 0,
      outputTokens: runs._sum.outputTokens ?? 0,
      webSearches: runs._sum.webSearches ?? 0,
    },
    domains: domains.map((d) => ({
      domain: d.domain,
      pages: count(d.pages),
      submitted: count(d.submitted),
      approved: count(d.approved),
    })),
    categories: categories.map((c) => ({
      id: c.id,
      name: c.name,
      events: count(c.events),
      approved: count(c.approved),
    })),
    decisions: byDecision.map((d) => ({ decision: d.decision, count: d._count._all })),
    statuses: Object.fromEntries(statuses.map((s) => [s.status, count(s.events)])),
    configs: perConfig
      .map((c) => ({
        id: c.configId,
        name: names.get(c.configId) ?? `Recherche #${c.configId}`,
        runs: c._count._all,
        pages: c._sum.pages ?? 0,
        retained: c._sum.retained ?? 0,
        submitted: c._sum.submitted ?? 0,
        costUsd: Number(c._sum.costUsd ?? 0),
      }))
      .sort((a, b) => b.submitted - a.submitted),
  });
});

// ------------------------------------------------------------------ worker

/**
 * Le worker réclame le travail en attente. La prise est atomique : le passage
 * en RUNNING est conditionné au statut QUEUED, donc deux workers ne peuvent
 * pas se disputer la même exécution.
 */
scraperRouter.post('/next', async (_req, res) => {
  const queued = await prisma.scraperRun.findFirst({
    where: { status: 'QUEUED' },
    orderBy: { queuedAt: 'asc' },
    include: { config: true },
  });
  if (!queued) {
    res.json({ run: null });
    return;
  }
  const claimed = await prisma.scraperRun.updateMany({
    where: { id: queued.id, status: 'QUEUED' },
    data: { status: 'RUNNING', startedAt: new Date() },
  });
  if (claimed.count === 0) {
    // Un autre worker est passé devant : il repassera.
    res.json({ run: null });
    return;
  }
  res.json({
    run: { ...serializeRun(queued), status: 'RUNNING', config: serializeConfig(queued.config) },
  });
});

/** Journalise les pages traitées et alimente la mémoire commune. */
scraperRouter.post('/runs/:id/items', async (req, res) => {
  const runId = Number(req.params.id);
  const parsed = scraperItemsSchema.safeParse(req.body);
  if (!Number.isInteger(runId) || !parsed.success) {
    res.status(400).json({ error: parsed.success ? 'Requête invalide' : parsed.error.issues[0].message });
    return;
  }
  const run = await prisma.scraperRun.findUnique({ where: { id: runId } });
  if (!run) {
    res.status(404).json({ error: 'Exécution introuvable' });
    return;
  }

  await prisma.scraperRunItem.createMany({
    data: parsed.data.items.map((item) => ({
      runId,
      url: item.url,
      // La clé n'est gardée que si la page a bien été mémorisée : c'est elle
      // qui permettra, plus tard, de défaire exactement ce que ce run a mis
      // en mémoire (voir DELETE /runs/:id/data).
      key: item.remember ? (item.key ?? item.url) : null,
      title: item.title ?? null,
      decision: item.decision,
      reason: item.reason ?? null,
      eventId: item.eventId ?? null,
    })),
  });

  // La mémoire des pages est commune à toutes les configurations : c'est elle
  // qui évite de relire — donc de repayer — une page déjà analysée.
  for (const item of parsed.data.items.filter((i) => i.remember)) {
    // On mémorise la clé normalisée, pas le lien exact : sinon la même page
    // sous deux adresses équivalentes serait relue — et repayée.
    const key = item.key ?? item.url;
    await prisma.scrapedUrl.upsert({
      where: { url: key },
      create: {
        url: key,
        title: item.title ?? null,
        decision: item.decision,
        eventId: item.eventId ?? null,
      },
      update: {
        decision: item.decision,
        ...(item.title ? { title: item.title } : {}),
        ...(item.eventId ? { eventId: item.eventId } : {}),
      },
    });
  }

  res.json({ ok: true, recorded: parsed.data.items.length });
});

/**
 * Repli quand une exécution ne porte pas son propre graphe.
 *
 * La source de vérité reste `scraper/sortiesbot/stages.py`, transportée par
 * l'événement `run_start` : c'est elle qui donne les libellés, et renommer une
 * brique côté scraper la renomme partout. Ces tables ne servent que pour les
 * exécutions antérieures, dont on ne sait plus que l'identifiant d'étage.
 */
const FALLBACK_ORDER = ['discovery', 'identify', 'harvest', 'select', 'read', 'extract', 'publish'];

const FALLBACK_LABELS: Record<string, string> = {
  discovery: 'Découverte',
  identify: 'Reconnaissance',
  harvest: 'Dépouillement',
  select: 'Sélection',
  read: 'Lecture',
  extract: 'Extraction',
  publish: 'Publication',
};

const FALLBACK_ACTORS: Record<string, string> = {
  discovery: 'modele',
  // Gratuite tant qu'un signal certain tranche, facturée sinon.
  identify: 'mixte',
  harvest: 'python',
  select: 'modele',
  read: 'python',
  extract: 'modele',
  publish: 'python',
};

// ------------------------------------------------------- journal détaillé

/**
 * Le journal détaillé d'une exécution, envoyé par le worker au fil du run.
 *
 * Distinct de `/items` et c'est délibéré : `/items` décide du sort d'une page
 * et alimente la mémoire commune, cette route ne fait que raconter. Un bug
 * dans le journal ne peut donc pas mémoriser une page par accident.
 *
 * Les doublons sont possibles — un worker qui réessaie un paquet — d'où le
 * `skipDuplicates` sur la clé (runId, seq).
 */
scraperRouter.post('/runs/:id/logs', async (req, res) => {
  const runId = Number(req.params.id);
  const parsed = scraperLogsSchema.safeParse(req.body);
  if (!Number.isInteger(runId) || !parsed.success) {
    res
      .status(400)
      .json({ error: parsed.success ? 'Requête invalide' : parsed.error.issues[0].message });
    return;
  }
  const run = await prisma.scraperRun.findUnique({ where: { id: runId }, select: { id: true } });
  if (!run) {
    res.status(404).json({ error: 'Exécution introuvable' });
    return;
  }

  await prisma.scraperRunLog.createMany({
    data: parsed.data.entries.map((entry) => ({
      runId,
      seq: entry.seq,
      // L'horodatage vient du scraper : c'est lui qui a vu l'événement, et le
      // paquet peut arriver plusieurs secondes plus tard.
      at: entry.at ? new Date(entry.at) : new Date(),
      stage: entry.stage ?? null,
      kind: entry.kind,
      level: entry.level,
      url: entry.url ?? null,
      message: entry.message ?? null,
      data: entry.data ? JSON.stringify(entry.data) : null,
    })),
  });

  res.json({ ok: true, recorded: parsed.data.entries.length });
});

/** Un événement du journal, prêt pour la console. */
function serializeLog(row: {
  id: number;
  seq: number;
  at: Date;
  stage: string | null;
  kind: string;
  level: string;
  url: string | null;
  message: string | null;
  data: string | null;
}) {
  let data: unknown = null;
  if (row.data) {
    // Un JSON illisible ne doit pas faire échouer toute la page : on rend la
    // chaîne brute, la console l'affichera telle quelle.
    try {
      data = JSON.parse(row.data);
    } catch {
      data = { brut: row.data };
    }
  }
  return { ...row, data };
}

/**
 * Le journal, filtré. C'est ce que lit la page de débogage.
 *
 * `after` est un curseur sur `seq`, pas un décalage : la console charge la
 * suite sans risquer de sauter ou de répéter une ligne quand le run écrit
 * pendant qu'on lit.
 */
scraperRouter.get('/runs/:id/logs', async (req, res) => {
  const runId = Number(req.params.id);
  const parsed = scraperLogQuerySchema.safeParse(req.query);
  if (!Number.isInteger(runId) || !parsed.success) {
    res
      .status(400)
      .json({ error: parsed.success ? 'Requête invalide' : parsed.error.issues[0].message });
    return;
  }
  const { stage, kind, level, url, agenda, page, q, after, limit } = parsed.data;

  const where: Prisma.ScraperRunLogWhereInput = { runId };
  if (stage) where.stage = stage;
  if (kind) where.kind = kind;
  if (level) where.level = level;
  if (url) where.url = url;
  if (after !== undefined) where.seq = { gt: after };
  // La filiation vit dans la colonne JSON : on cherche le fragment exact
  // plutôt que l'URL seule, sinon un agenda attraperait aussi ses pages.
  const descendsFrom: Prisma.ScraperRunLogWhereInput[] = [];
  if (agenda) descendsFrom.push({ data: { contains: `"agenda":${JSON.stringify(agenda)}` } });
  if (page) descendsFrom.push({ data: { contains: `"page":${JSON.stringify(page)}` } });
  if (descendsFrom.length) where.AND = descendsFrom;
  if (q) {
    // La recherche libre porte sur ce qu'un humain lit : l'adresse, le
    // message, et le reste des champs sérialisés.
    where.OR = [{ url: { contains: q } }, { message: { contains: q } }, { data: { contains: q } }];
  }

  const rows = await prisma.scraperRunLog.findMany({
    where,
    orderBy: { seq: 'asc' },
    take: limit + 1,
  });
  const hasMore = rows.length > limit;

  res.json({
    logs: rows.slice(0, limit).map(serializeLog),
    hasMore,
    total: await prisma.scraperRunLog.count({ where: { runId } }),
  });
});

/**
 * Le graphe des étages, avec ce que chacun a produit et ce qu'il a coûté.
 *
 * Les libellés ne sont pas écrits ici : ils viennent de l'événement
 * `run_start`, que le scraper remplit depuis `stages.py`. Une brique renommée
 * côté scraper l'est donc partout, sans redéploiement du serveur.
 */
scraperRouter.get('/runs/:id/graph', async (req, res) => {
  const runId = Number(req.params.id);
  if (!Number.isInteger(runId)) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }

  const [start, ends, spend, byStage, errorsByStage] = await Promise.all([
    prisma.scraperRunLog.findFirst({ where: { runId, kind: 'run_start' }, orderBy: { seq: 'asc' } }),
    prisma.scraperRunLog.findMany({ where: { runId, kind: 'stage_end' }, orderBy: { seq: 'asc' } }),
    // La dépense est portée par les événements `usage`, un par appel au
    // modèle. Elle ne se somme pas en base : `data` est du JSON dans une
    // colonne texte. Une exécution en compte quelques dizaines, on additionne
    // ici plutôt que d'ajouter des colonnes pour un total qu'on sait dériver.
    prisma.scraperRunLog.findMany({ where: { runId, kind: 'usage' }, orderBy: { seq: 'asc' } }),
    prisma.scraperRunLog.groupBy({ by: ['stage'], where: { runId }, _count: { _all: true } }),
    prisma.scraperRunLog.groupBy({
      by: ['stage'],
      where: { runId, level: 'error' },
      _count: { _all: true },
    }),
  ]);

  const events = new Map(byStage.map((g) => [g.stage ?? '', g._count._all]));

  /** Ce que chaque étage a dépensé : dollars, jetons, recherches web. */
  const cost = new Map<string, { usd: number; tokens: number; searches: number; calls: number }>();
  for (const row of spend) {
    if (!row.stage) continue;
    let d: Record<string, unknown> = {};
    try {
      d = row.data ? (JSON.parse(row.data) as Record<string, unknown>) : {};
    } catch {
      continue;
    }
    const entry = cost.get(row.stage) ?? { usd: 0, tokens: 0, searches: 0, calls: 0 };
    entry.usd += Number(d.total_usd ?? 0);
    entry.tokens += Number(d.input_tokens ?? 0) + Number(d.output_tokens ?? 0);
    entry.searches += Number(d.web_searches ?? 0);
    entry.calls += 1;
    cost.set(row.stage, entry);
  }
  const errors = new Map(errorsByStage.map((g) => [g.stage ?? '', g._count._all]));

  // Un étage est traversé plusieurs fois par run — une fois par agenda, une
  // fois par page. On additionne les passages plutôt que de n'en montrer qu'un.
  const passes = new Map<string, { runs: number; seconds: number; produced: string[] }>();
  for (const row of ends) {
    if (!row.stage) continue;
    const parsedData = (() => {
      try {
        return row.data ? (JSON.parse(row.data) as Record<string, unknown>) : {};
      } catch {
        return {};
      }
    })();
    const entry = passes.get(row.stage) ?? { runs: 0, seconds: 0, produced: [] };
    entry.runs += 1;
    entry.seconds += Number(parsedData.seconds ?? 0);
    const produced = parsedData.produced;
    if (typeof produced === 'string' && produced !== '—') entry.produced.push(produced);
    passes.set(row.stage, entry);
  }

  const described = (() => {
    try {
      const data = start?.data ? (JSON.parse(start.data) as Record<string, unknown>) : {};
      if (Array.isArray(data.stages) && data.stages.length) {
        return data.stages as Record<string, unknown>[];
      }
    } catch {
      // JSON illisible : on retombe sur le repli ci-dessous.
    }
    // Repli pour les exécutions dont le `run_start` ne porte pas le graphe —
    // celles d'avant cette page, ou celles enregistrées quand le scraper
    // envoyait ses événements à plat. On dessine alors les briques réellement
    // traversées, à partir de la seule colonne `stage`.
    return byStage
      .map((g) => g.stage)
      .filter((s): s is string => Boolean(s))
      .map((s) => ({ stage: s, number: FALLBACK_ORDER.indexOf(s) + 1, label: FALLBACK_LABELS[s] ?? s, actor: FALLBACK_ACTORS[s] ?? '', takes: '', gives: '' }))
      .sort((a, b) => a.number - b.number);
  })();

  res.json({
    stages: described.map((s) => {
      const key = String(s.stage);
      const pass = passes.get(key);
      const spent = cost.get(key);
      return {
        ...s,
        events: events.get(key) ?? 0,
        errors: errors.get(key) ?? 0,
        passes: pass?.runs ?? 0,
        seconds: pass ? Math.round(pass.seconds * 10) / 10 : 0,
        produced: pass?.produced ?? [],
        // Quatre décimales : un appel de reconnaissance coûte un millième de
        // dollar, et l'arrondir au centime l'afficherait à zéro.
        costUsd: spent ? Math.round(spent.usd * 10000) / 10000 : 0,
        tokens: spent?.tokens ?? 0,
        searches: spent?.searches ?? 0,
        calls: spent?.calls ?? 0,
      };
    }),
    // Ce qui n'appartient à aucun étage : démarrage, clôture, erreurs hors run.
    outside: events.get('') ?? 0,
  });
});

/**
 * L'arbre d'une exécution : d'où vient chaque sortie.
 *
 * Le journal plat répond à « qu'est-ce qui s'est passé ? ». Il ne répond pas à
 * « d'où vient cette sortie ? », qui est la question qu'on se pose vraiment
 * devant une proposition douteuse. Les deux ne se déduisent pas l'une de
 * l'autre : il faut la filiation, que le scraper enregistre désormais sur
 * chaque événement (`data.query`, `data.agenda`, `data.page`).
 *
 * On assemble ici plutôt que côté navigateur : le client n'aurait pas à
 * télécharger deux mille lignes pour n'en afficher qu'un résumé.
 */
scraperRouter.get('/runs/:id/tree', async (req, res) => {
  const runId = Number(req.params.id);
  if (!Number.isInteger(runId)) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const rows = await prisma.scraperRunLog.findMany({
    where: { runId },
    orderBy: { seq: 'asc' },
    select: {
      seq: true, stage: true, kind: true, level: true,
      url: true, message: true, data: true,
    },
    // Un plafond franc : au-delà, l'arbre n'est plus lisible de toute façon,
    // et le journal plat reste là pour le détail.
    take: TREE_MAX_ROWS,
  });
  res.json({ ...buildTree(rows), truncated: rows.length >= TREE_MAX_ROWS });
});

/**
 * Oublie le journal détaillé d'une exécution, et lui seul.
 *
 * Ce journal est verbeux par construction : il garde chaque lien soumis au
 * tri, ce qui fait un millier de lignes par exécution. C'est exactement ce
 * qu'on veut pour déboguer, et exactement ce qu'on ne veut pas garder pour
 * cent exécutions passées.
 *
 * Distinct de `DELETE /runs/:id/data`, qui supprime les sorties et la mémoire
 * en laissant les journaux : ici c'est l'inverse. Les compteurs de
 * l'exécution et le sort de chaque page (`ScraperRunItem`) ne bougent pas.
 */
scraperRouter.delete('/runs/:id/logs', async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const run = await prisma.scraperRun.findUnique({ where: { id }, select: { status: true } });
  if (!run) {
    res.status(404).json({ error: 'Exécution introuvable' });
    return;
  }
  if (run.status === 'QUEUED' || run.status === 'RUNNING') {
    // Le worker écrit encore : ce qu'on supprimerait reviendrait aussitôt.
    res.status(409).json({
      error: "L'exécution est en cours. Attendez sa fin avant de vider son journal.",
    });
    return;
  }
  const { count } = await prisma.scraperRunLog.deleteMany({ where: { runId: id } });
  res.json({ ok: true, deleted: count });
});

/**
 * Supprime tout ce qu'une exécution a produit : ses sorties, et ce qu'elle
 * avait mis dans la mémoire des pages.
 *
 * Les deux vont ensemble et c'est tout l'intérêt du bouton. Supprimer les
 * sorties seules laisserait leurs pages mémorisées, donc jamais reproposées :
 * une recherche mal réglée resterait punie longtemps après sa correction.
 * Oublier la mémoire seule laisserait les sorties en place, donc reproposées
 * en double au prochain passage.
 *
 * Le journal de l'exécution, lui, survit : il dit ce qu'elle a fait, et c'est
 * précisément ce qu'on veut relire après coup. Seul `purgedAt` est posé, pour
 * que la console cesse de présenter ses compteurs comme s'ils décrivaient
 * quelque chose de vivant.
 */
scraperRouter.delete('/runs/:id/data', async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const run = await prisma.scraperRun.findUnique({
    where: { id },
    include: { items: { select: { url: true, key: true, eventId: true } } },
  });
  if (!run) {
    res.status(404).json({ error: 'Exécution introuvable' });
    return;
  }
  if (run.status === 'QUEUED' || run.status === 'RUNNING') {
    // Le worker écrit encore : ce qu'on supprimerait maintenant reviendrait
    // par la ligne suivante du même run.
    res.status(409).json({
      error: "L'exécution est en cours. Annulez-la ou attendez sa fin avant de la vider.",
    });
    return;
  }

  const eventIds = [...new Set(run.items.map((i) => i.eventId).filter((v): v is number => !!v))];
  const events = eventIds.length
    ? await prisma.event.findMany({ where: { id: { in: eventIds } }, select: { id: true, photoUrl: true } })
    : [];

  // La mémoire d'abord, les sorties ensuite — l'ordre n'est pas indifférent.
  // `ScrapedUrl.eventId` est en `onDelete: SetNull` : supprimer les sorties
  // en premier effacerait le lien qui sert justement à retrouver les lignes
  // de mémoire qu'elles ont produites.
  //
  // Deux façons de les retrouver, complémentaires :
  //
  // * par `eventId` — exact, et surtout rétroactif : il vaut pour les
  //   exécutions antérieures au champ `key`, qui n'ont rien d'autre ;
  // * par `key` — la clé réellement employée, seule à couvrir les pages
  //   mémorisées **sans** avoir donné de sortie (hors sujet, inexploitable).
  //
  // L'URL brute de la ligne de journal ne sert à rien ici : la mémoire est
  // indexée par URL normalisée (schéma, `www.`, barre finale, paramètres de
  // suivi retirés), et le journal garde le lien exact. Les deux ne coïncident
  // que par chance — et quand elles coïncident, ce serait pour supprimer une
  // ligne que cette exécution n'a peut-être pas écrite, puisqu'une décision
  // provisoire ne mémorise rien.
  const keys = [...new Set(run.items.map((i) => i.key).filter((v): v is string => !!v))];
  const retrouvables = [
    ...(eventIds.length ? [{ eventId: { in: eventIds } }] : []),
    ...(keys.length ? [{ url: { in: keys } }] : []),
  ];
  const { count: memory } = retrouvables.length
    ? await prisma.scrapedUrl.deleteMany({ where: { OR: retrouvables } })
    : { count: 0 };

  if (events.length) {
    await prisma.event.deleteMany({ where: { id: { in: events.map((e) => e.id) } } });
    // Les photos ne partent qu'une fois les lignes supprimées : un fichier
    // orphelin se repère, une fiche sans sa photo ne se répare pas.
    for (const event of events) {
      if (event.photoUrl) await deletePhoto(event.photoUrl);
    }
  }

  await prisma.scraperRun.update({ where: { id }, data: { purgedAt: new Date() } });
  res.json({ ok: true, events: events.length, memory });
});

/** Clôt une exécution avec ses compteurs. */
scraperRouter.post('/runs/:id/finish', async (req, res) => {
  const id = Number(req.params.id);
  const parsed = scraperFinishSchema.safeParse(req.body);
  if (!Number.isInteger(id) || !parsed.success) {
    res.status(400).json({ error: parsed.success ? 'Requête invalide' : parsed.error.issues[0].message });
    return;
  }
  const { status, error, ...counters } = parsed.data;
  try {
    const run = await prisma.scraperRun.update({
      where: { id },
      data: { ...counters, status, error: error ?? null, finishedAt: new Date() },
    });
    res.json({ run: serializeRun(run) });
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2025') {
      res.status(404).json({ error: 'Exécution introuvable' });
      return;
    }
    throw e;
  }
});

/**
 * Parmi ces URLs, lesquelles ont déjà été analysées ?
 *
 * Le worker interroge la mémoire avant de lire quoi que ce soit : une page
 * connue ne doit jamais être relue, ni repayée.
 */
scraperRouter.post('/seen', async (req, res) => {
  const parsed = scraperSeenSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const known = await prisma.scrapedUrl.findMany({
    where: { url: { in: parsed.data.urls } },
    select: { url: true, decision: true, eventId: true },
  });
  res.json({ seen: known });
});
