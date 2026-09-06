/**
 * Le banc d'évaluation : mesurer ce que chaque brique du scraper rend
 * vraiment, plutôt que d'espérer qu'elle rende ce qu'il faut.
 *
 * Un seul étage est mesuré pour l'instant, le **dépouillement** (étage 3), et
 * c'est délibéré : il est en amont, donc son ratage plafonne tout ce qui
 * suit ; il est déterministe, ce qui ne veut pas dire juste ; et sa panne se
 * déguise en panne de l'étage suivant — un agenda dont les liens de fiche ont
 * été perdus rend son menu, et c'est le prompt de la sélection qu'on ira
 * accuser.
 *
 * ## Pourquoi le worker, et pas ce fichier
 *
 * L'extraction passe par le worker Python et par le vrai `links_of`. La
 * refaire en Node donnerait la vérité d'une réimplémentation — c'est-à-dire
 * aucune vérité. Le statut de l'agenda sert donc de file, exactement comme
 * celui d'une exécution du scraper : le worker réclame ce qui est en QUEUED,
 * rend les pages, et clôt.
 *
 * ## Qui a le droit
 *
 * La console est réservée aux **administrateurs** : elle fabrique la vérité de
 * référence sur laquelle tout le reste s'appuiera, et une vérité que plusieurs
 * mains modifient sans se concerter n'en est plus une.
 *
 * Les trois routes du worker se contentent du rôle **modérateur**, qui est
 * celui que porte sa clé d'API. Elles n'exposent rien qu'un modérateur ne
 * puisse déjà voir, et exiger l'administration ici obligerait à donner ce rôle
 * à un programme.
 */
import { Prisma, Role } from '@prisma/client';
import express, { Router } from 'express';
import { prisma } from '../db';
import { deleteEvalPages, readEvalPage, saveEvalPage } from '../lib/evalPages';
import { requireRole } from '../middleware/auth';
import {
  evalAgendaSchema,
  evalAgendaUpdateSchema,
  evalFailSchema,
  evalHarvestSchema,
  evalLinkSchema,
} from '../lib/validators';

export const evalRouter = Router();

// Le plancher : les routes du worker s'en contentent, la console exige plus.
evalRouter.use(requireRole(Role.MODERATOR));

const admin = requireRole(Role.ADMIN);

/** L'agenda tel que la console l'affiche : ses pages, et les liens de chacune. */
const AGENDA_INCLUDE = {
  author: { select: { id: true, displayName: true } },
  agendaPages: {
    orderBy: { pageNo: 'asc' },
    // `htmlPath` est un chemin sur le disque du serveur : la console n'a pas à
    // le connaître, seulement à savoir si l'archive existe. Il est donc
    // remplacé par un booléen à la sérialisation.
    include: { links: { orderBy: [{ source: 'asc' }, { id: 'asc' }] } },
  },
} satisfies Prisma.EvalAgendaInclude;

/**
 * Efface les pages archivées d'un agenda, puis rend la main.
 *
 * Prisma efface les lignes en cascade, pas les fichiers. Sans cet appel, chaque
 * analyse relancée laisserait derrière elle un HTML que plus rien ne
 * référence — et le disque du serveur finirait par se remplir de pages dont
 * personne ne saurait plus de quel agenda elles venaient.
 */
async function forgetArchive(agendaId: number): Promise<void> {
  const pages = await prisma.evalAgendaPage.findMany({
    where: { agendaId },
    select: { htmlPath: true },
  });
  await deleteEvalPages(pages.map((p) => p.htmlPath));
}

/**
 * Le rappel du dépouillement sur cet agenda.
 *
 * `harvested / total` : un lien ajouté à la main est très exactement un lien
 * que `links_of` aurait dû voir et n'a pas vu. Le chiffre ne vaut que si un
 * humain est passé — d'où `null` tant que l'agenda n'est pas validé, plutôt
 * qu'un 100 % flatteur qui ne dirait que « personne n'a encore regardé ».
 */
type SerializablePage = { htmlPath: string | null; links: { source: string }[] };
type SerializableAgenda = { status: string; agendaPages: SerializablePage[] };

function recallOf(agenda: SerializableAgenda): {
  harvested: number;
  manual: number;
  total: number;
  recall: number | null;
} {
  let harvested = 0;
  let manual = 0;
  for (const page of agenda.agendaPages) {
    for (const link of page.links) {
      if (link.source === 'MANUAL') manual += 1;
      else harvested += 1;
    }
  }
  const total = harvested + manual;
  return {
    harvested,
    manual,
    total,
    recall: agenda.status === 'VALIDATED' && total > 0 ? harvested / total : null,
  };
}

function serialize<T extends SerializableAgenda>(agenda: T) {
  return {
    ...agenda,
    agendaPages: agenda.agendaPages.map(({ htmlPath, ...page }) => ({
      ...page,
      archived: !!htmlPath,
    })),
    stats: recallOf(agenda),
  };
}

// ───────────────────────────────────────────────────────────────── console

/** Tous les agendas du banc, du plus récent au plus ancien. */
evalRouter.get('/agendas', admin, async (_req, res) => {
  const agendas = await prisma.evalAgenda.findMany({
    orderBy: { createdAt: 'desc' },
    include: AGENDA_INCLUDE,
  });
  res.json({ agendas: agendas.map(serialize) });
});

evalRouter.get('/agendas/:id(\\d+)', admin, async (req, res) => {
  const agenda = await prisma.evalAgenda.findUnique({
    where: { id: Number(req.params.id) },
    include: AGENDA_INCLUDE,
  });
  if (!agenda) {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }
  res.json({ agenda: serialize(agenda) });
});

/**
 * Ajoute un agenda au banc et le met en file.
 *
 * L'URL est unique : le même agenda analysé deux fois donnerait deux vérités
 * de référence pour une seule page, et rien ne dirait laquelle croire.
 */
evalRouter.post('/agendas', admin, async (req, res) => {
  const parsed = evalAgendaSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const existing = await prisma.evalAgenda.findUnique({
    where: { url: parsed.data.url },
    select: { id: true },
  });
  if (existing) {
    res.status(409).json({ error: 'Cet agenda est déjà au banc', id: existing.id });
    return;
  }
  const agenda = await prisma.evalAgenda.create({
    data: { ...parsed.data, createdById: req.user!.id },
    include: AGENDA_INCLUDE,
  });
  res.status(201).json({ agenda: serialize(agenda) });
});

evalRouter.patch('/agendas/:id(\\d+)', admin, async (req, res) => {
  const parsed = evalAgendaUpdateSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const id = Number(req.params.id);
  const current = await prisma.evalAgenda.findUnique({ where: { id }, select: { status: true } });
  if (!current) {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }
  if (current.status === 'RUNNING') {
    res.status(409).json({ error: 'Analyse en cours' });
    return;
  }
  const agenda = await prisma.evalAgenda.update({
    where: { id },
    data: parsed.data,
    include: AGENDA_INCLUDE,
  });
  res.json({ agenda: serialize(agenda) });
});

/**
 * Relance l'analyse : la moisson précédente est effacée, la validation avec.
 *
 * Les ajouts manuels partent aussi, et il n'y a pas d'autre choix honnête. Ils
 * disaient « `links_of` a manqué ceci **sur cette page telle qu'elle était** » ;
 * la page vient d'être retéléchargée, elle a pu changer, et garder ces liens
 * les rattacherait à un HTML qu'ils n'ont jamais décrit.
 */
evalRouter.post('/agendas/:id(\\d+)/analyze', admin, async (req, res) => {
  const id = Number(req.params.id);
  const current = await prisma.evalAgenda.findUnique({ where: { id }, select: { status: true } });
  if (!current) {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }
  if (current.status === 'RUNNING') {
    res.status(409).json({ error: 'Analyse déjà en cours' });
    return;
  }
  await forgetArchive(id);
  const agenda = await prisma.$transaction(async (tx) => {
    await tx.evalAgendaPage.deleteMany({ where: { agendaId: id } });
    return tx.evalAgenda.update({
      where: { id },
      data: { status: 'QUEUED', error: null, analyzedAt: null, validatedAt: null },
      include: AGENDA_INCLUDE,
    });
  });
  res.json({ agenda: serialize(agenda) });
});

/**
 * Ajoute à la main un lien que le dépouillement a manqué. C'est **la** mesure :
 * tout le banc de l'étage 3 tient dans ce bouton.
 *
 * Le lien se rattache à une page précise, parce que c'est la page qui est
 * l'unité de travail de `links_of` — dire « cet agenda a 30 liens » sans dire
 * de quelle page ne permettrait de reprocher son ratage à personne.
 */
evalRouter.post('/pages/:pageId(\\d+)/links', admin, async (req, res) => {
  const parsed = evalLinkSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const pageId = Number(req.params.pageId);
  const page = await prisma.evalAgendaPage.findUnique({
    where: { id: pageId },
    select: { agendaId: true },
  });
  if (!page) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  const duplicate = await prisma.evalLink.findUnique({
    where: { pageId_url: { pageId, url: parsed.data.url } },
    select: { id: true, source: true },
  });
  if (duplicate) {
    res.status(409).json({
      error:
        duplicate.source === 'HARVEST'
          ? 'Ce lien a déjà été trouvé par le dépouillement'
          : 'Ce lien a déjà été ajouté',
    });
    return;
  }
  await prisma.evalLink.create({ data: { ...parsed.data, pageId, source: 'MANUAL' } });
  // Un ajout après validation rouvre l'agenda : la vérité a changé, et le
  // chiffre qu'on en tirait ne vaut plus pour ce qu'elle contient maintenant.
  const agenda = await prisma.evalAgenda.update({
    where: { id: page.agendaId },
    data: { status: 'ANALYZED', validatedAt: null },
    include: AGENDA_INCLUDE,
  });
  res.status(201).json({ agenda: serialize(agenda) });
});

/** Retire un lien ajouté à la main. Un lien de la moisson, lui, ne s'efface pas. */
evalRouter.delete('/links/:id(\\d+)', admin, async (req, res) => {
  const link = await prisma.evalLink.findUnique({
    where: { id: Number(req.params.id) },
    select: { id: true, source: true, page: { select: { agendaId: true } } },
  });
  if (!link) {
    res.status(404).json({ error: 'Lien introuvable' });
    return;
  }
  if (link.source === 'HARVEST') {
    res.status(409).json({
      error:
        "Ce lien vient du dépouillement : l'effacer falsifierait la mesure. " +
        'Relancez l\'analyse si la page a changé.',
    });
    return;
  }
  await prisma.evalLink.delete({ where: { id: link.id } });
  const agenda = await prisma.evalAgenda.update({
    where: { id: link.page.agendaId },
    data: { status: 'ANALYZED', validatedAt: null },
    include: AGENDA_INCLUDE,
  });
  res.json({ agenda: serialize(agenda) });
});

/**
 * Valide la moisson : un humain a relu, complété, et ce que l'agenda contient
 * fait désormais vérité.
 *
 * C'est cet instant qui rend la mesure lisible — avant, un rappel de 100 %
 * dirait seulement que personne n'a encore regardé.
 */
evalRouter.post('/agendas/:id(\\d+)/validate', admin, async (req, res) => {
  const id = Number(req.params.id);
  const current = await prisma.evalAgenda.findUnique({
    where: { id },
    select: { status: true, _count: { select: { agendaPages: true } } },
  });
  if (!current) {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }
  if (current.status !== 'ANALYZED') {
    res.status(409).json({ error: 'Seule une analyse terminée se valide' });
    return;
  }
  const agenda = await prisma.evalAgenda.update({
    where: { id },
    data: { status: 'VALIDATED', validatedAt: new Date() },
    include: AGENDA_INCLUDE,
  });
  res.json({ agenda: serialize(agenda) });
});

evalRouter.delete('/agendas/:id(\\d+)', admin, async (req, res) => {
  const id = Number(req.params.id);
  const current = await prisma.evalAgenda.findUnique({ where: { id }, select: { id: true } });
  if (!current) {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }
  await forgetArchive(id);
  await prisma.evalAgenda.delete({ where: { id } });
  res.json({ ok: true });
});

/**
 * Le HTML gelé d'une page, tel que le site l'a servi ce jour-là.
 *
 * C'est ce qui permet de rejouer `links_of` hors ligne après l'avoir modifié,
 * et de comparer à des étiquettes qui, elles, n'ont pas bougé. Servi en texte
 * brut plutôt qu'en HTML : cette page n'a pas à s'exécuter dans le navigateur
 * de la console, on vient la lire.
 */
evalRouter.get('/pages/:id(\\d+)/html', admin, async (req, res) => {
  const page = await prisma.evalAgendaPage.findUnique({
    where: { id: Number(req.params.id) },
    select: { htmlPath: true, url: true },
  });
  if (!page?.htmlPath) {
    res.status(404).json({ error: "Cette page n'a pas été archivée" });
    return;
  }
  const html = await readEvalPage(page.htmlPath);
  if (html === null) {
    res.status(410).json({ error: "L'archive de cette page a disparu du disque" });
    return;
  }
  res.type('text/plain; charset=utf-8').send(html);
});

// ────────────────────────────────────────────────────────────────── worker

/**
 * Le worker réclame l'agenda en attente. La prise est atomique — le passage en
 * RUNNING est conditionné au statut QUEUED — donc deux workers ne peuvent pas
 * se disputer le même.
 */
evalRouter.post('/harvest/next', async (_req, res) => {
  const queued = await prisma.evalAgenda.findFirst({
    where: { status: 'QUEUED' },
    orderBy: { createdAt: 'asc' },
    select: { id: true, url: true, pages: true },
  });
  if (!queued) {
    res.json({ agenda: null });
    return;
  }
  const claimed = await prisma.evalAgenda.updateMany({
    where: { id: queued.id, status: 'QUEUED' },
    data: { status: 'RUNNING' },
  });
  if (claimed.count === 0) {
    // Un autre worker est passé devant : il repassera.
    res.json({ agenda: null });
    return;
  }
  res.json({ agenda: queued });
});

/**
 * Le worker rend ce qu'il a moissonné, page par page, et l'agenda passe en
 * ANALYZED : il attend maintenant un humain.
 *
 * L'écriture est transactionnelle et repart de zéro. Un compte rendu partiel
 * laisserait un agenda dont on ne saurait pas dire s'il est complet — et une
 * vérité de référence dont on doute ne sert à rien.
 */
/**
 * Le corps porte le HTML gzippé de chaque page : bien au-delà des 100 ko que
 * `express.json()` accepte par défaut, et ce plafond-là a de bonnes raisons
 * d'exister partout ailleurs. On l'élargit donc pour cette route seule, et pas
 * pour l'application entière.
 */
const harvestBody = express.json({ limit: '12mb' });

evalRouter.post('/harvest/:id(\\d+)/pages', harvestBody, async (req, res) => {
  const parsed = evalHarvestSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const id = Number(req.params.id);
  const current = await prisma.evalAgenda.findUnique({ where: { id }, select: { id: true } });
  if (!current) {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }
  // Les fichiers d'abord, hors transaction : ils ne sont pas transactionnels,
  // et une archive écrite pour une transaction qui échouerait ensuite serait
  // simplement orpheline — alors qu'une ligne pointant vers un fichier jamais
  // écrit serait, elle, un mensonge.
  await forgetArchive(id);
  const archived = await Promise.all(
    parsed.data.pages.map((page) => (page.html ? saveEvalPage(page.html) : Promise.resolve(''))),
  );

  await prisma.$transaction(async (tx) => {
    await tx.evalAgendaPage.deleteMany({ where: { agendaId: id } });
    for (const [index, page] of parsed.data.pages.entries()) {
      // Le worker envoie ce que `links_of` a rendu, donc déjà dédoublonné par
      // URL au sein d'une page. On s'en assure quand même : la contrainte
      // d'unicité ferait échouer tout le compte rendu pour un seul doublon.
      const seen = new Set<string>();
      const links = page.links.filter((l) => !seen.has(l.url) && seen.add(l.url));
      await tx.evalAgendaPage.create({
        data: {
          agendaId: id,
          pageNo: page.pageNo,
          url: page.url,
          chars: page.chars,
          error: page.error ?? null,
          htmlPath: archived[index] || null,
          links: { create: links.map((l) => ({ ...l, source: 'HARVEST' as const })) },
        },
      });
    }
    await tx.evalAgenda.update({
      where: { id },
      data: { status: 'ANALYZED', error: null, analyzedAt: new Date(), validatedAt: null },
    });
  });
  const agenda = await prisma.evalAgenda.findUnique({ where: { id }, include: AGENDA_INCLUDE });
  res.json({ agenda: agenda ? serialize(agenda) : null });
});

/**
 * Clôture en échec. Sans elle, l'agenda resterait « en cours » pour toujours
 * et ne serait plus jamais réclamé — c'est la même règle que pour une
 * exécution du scraper, et pour la même raison.
 */
evalRouter.post('/harvest/:id(\\d+)/fail', async (req, res) => {
  const parsed = evalFailSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const id = Number(req.params.id);
  const updated = await prisma.evalAgenda.updateMany({
    where: { id },
    data: { status: 'FAILED', error: parsed.data.error },
  });
  if (updated.count === 0) {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }
  res.json({ ok: true });
});
