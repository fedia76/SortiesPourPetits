import { Prisma, Role } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { requireRole } from '../middleware/auth';
import {
  scraperConfigSchema,
  scraperConfigUpdateSchema,
  scraperFinishSchema,
  scraperItemsSchema,
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
