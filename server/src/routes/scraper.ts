import { Prisma, Role } from '@prisma/client';
import { Router } from 'express';
import { prisma } from '../db';
import { requireRole } from '../middleware/auth';
import {
  scraperConfigSchema,
  scraperConfigUpdateSchema,
  scraperFinishSchema,
  scraperItemsSchema,
  scraperRunSchema,
  scraperSeenSchema,
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
