/**
 * Le banc d'évaluation : mesurer ce que chaque brique du scraper rend
 * vraiment, plutôt que d'espérer qu'elle rende ce qu'il faut.
 *
 * ## Trois choses, et elles ne se mélangent plus
 *
 * * le **corpus** — une entrée gelée et ce qu'un humain dit qu'elle contient.
 *   Ça vit des années, ça ne dépend d'aucun modèle, et c'est la seule chose
 *   qui coûte cher à produire ;
 * * un **run** — ce qu'une brique, à sa version du jour, rend sur ce corpus.
 *   Immuable, empilé, jamais écrasé ;
 * * la **mesure** — la confrontation des deux, calculée à la demande dans
 *   `lib/evalMetrics.ts` et jamais stockée.
 *
 * Elles vivaient dans les mêmes lignes, et ce n'était pas une gêne
 * d'architecture : rejouer un agenda supprimait ses pages, donc en cascade les
 * verdicts humains qu'il portait. Mesurer détruisait la mesure. La question
 * « est-ce que ça s'améliore ? » — la seule pour laquelle un banc existe —
 * était sans réponse possible.
 *
 * ## Capturer n'est pas mesurer
 *
 * Une entrée du corpus est **capturée** une fois : on télécharge, on gèle le
 * HTML, on n'y revient plus. Un run rejoue ensuite sur ce HTML gelé, hors
 * ligne, autant de fois qu'on veut — de sorte qu'un écart entre deux runs ne
 * peut venir que du code, jamais du site.
 *
 * C'est pourquoi il n'y a pas de « recapture » : elle réécrirait l'objet que
 * les étiquettes décrivent. Pour repartir d'une page fraîche, on crée une
 * nouvelle entrée, et l'ancienne garde ses étiquettes et son histoire.
 *
 * ## Pourquoi le worker, et pas ce fichier
 *
 * Les briques sont en Python. Les refaire en Node donnerait la vérité d'une
 * réimplémentation, c'est-à-dire aucune vérité. Le statut d'une capture et
 * celui d'un run servent donc de files, exactement comme pour une exécution du
 * scraper : le worker réclame, rend, et clôt.
 *
 * ## Qui a le droit
 *
 * La console est réservée aux **administrateurs** : elle fabrique la vérité de
 * référence sur laquelle tout le reste s'appuiera, et une vérité que plusieurs
 * mains modifient sans se concerter n'en est plus une.
 *
 * Les routes du worker se contentent du rôle **modérateur**, qui est celui que
 * porte sa clé d'API : exiger l'administration obligerait à donner ce rôle à
 * un programme.
 */
import { Prisma, Role, type EvalAudience, type EvalVerdict } from '@prisma/client';
import express from 'express';
import { safeRouter } from '../lib/asyncRoutes';
import { prisma } from '../db';
import { deleteEvalPages, readEvalPage, saveEvalPage } from '../lib/evalPages';
import { requireRole } from '../middleware/auth';
import {
  extractScore,
  harvestScore,
  readScore,
  relevanceOf,
  selectScore,
  sumHarvest,
  sumSelect,
  type FicheRendue,
  type LabelledLink,
  type RunScope,
} from '../lib/evalMetrics';
import {
  evalAgendaSchema,
  evalAgendaUpdateSchema,
  evalBulkVerdictSchema,
  evalCaptureSchema,
  evalExtractResultSchema,
  evalFailSchema,
  evalFicheSchema,
  evalLinkResultSchema,
  evalLinkSchema,
  evalNextSchema,
  evalReadResultSchema,
  evalSortieLabelSchema,
  evalSortieSchema,
  evalRunClaimSchema,
  evalRunFinishSchema,
  evalRunListSchema,
  evalRunSchema,
  evalSeedSchema,
  evalVerdictSchema,
} from '../lib/validators';

export const evalRouter = safeRouter();

// Le plancher : les routes du worker s'en contentent, la console exige plus.
evalRouter.use(requireRole(Role.MODERATOR));

const admin = requireRole(Role.ADMIN);

/**
 * Les comptes rendus du worker portent du HTML gzippé en base64 : quelques
 * centaines de kilo-octets, bien au-delà du plafond par défaut d'Express.
 */
const bigBody = express.json({ limit: '12mb' });

function parseJson<T>(raw: string | null | undefined, fallback: T): T {
  if (!raw) return fallback;
  try {
    const value = JSON.parse(raw) as unknown;
    return value === null || value === undefined ? fallback : (value as T);
  } catch {
    return fallback;
  }
}

// ══════════════════════════════════════════════════════════════ LE CORPUS
//
// Des étiquettes, et l'entrée gelée qu'elles décrivent. Rien de ce qu'une
// brique produit n'entre ici : c'est toute la règle, et elle se vérifie d'un
// coup d'œil — aucune route de cette section n'écrit ce qu'un run a rendu.

// ───────────────────────────────────────────── corpus des agendas (ét. 3/4)

evalRouter.get('/agendas', admin, async (_req, res) => {
  const agendas = await prisma.evalAgenda.findMany({
    orderBy: { createdAt: 'desc' },
    include: {
      author: { select: { id: true, displayName: true } },
      agendaPages: {
        orderBy: { pageNo: 'asc' },
        select: {
          id: true,
          pageNo: true,
          url: true,
          chars: true,
          htmlPath: true,
          nextExpected: true,
          _count: { select: { links: true } },
        },
      },
    },
  });
  res.json({ agendas: agendas.map(serializeAgenda) });
});

function serializeAgenda(agenda: {
  agendaPages: { htmlPath: string | null; _count: { links: number } }[];
  [k: string]: unknown;
}) {
  const { agendaPages, ...rest } = agenda;
  return {
    ...rest,
    pagesCaptured: agendaPages.length,
    // Le chemin sur le disque du serveur ne sort jamais : la console n'a
    // besoin que de savoir si l'archive existe.
    agendaPages: agendaPages.map(({ htmlPath, _count, ...page }) => ({
      ...page,
      archived: Boolean(htmlPath),
      labels: _count.links,
    })),
    /** Étiquettes posées sur l'ensemble de l'agenda. */
    labels: agendaPages.reduce((sum, p) => sum + p._count.links, 0),
  };
}

evalRouter.post('/agendas', admin, async (req, res) => {
  const parsed = evalAgendaSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  try {
    const agenda = await prisma.evalAgenda.create({
      data: { ...parsed.data, createdById: req.user!.id },
    });
    res.status(201).json({ agenda });
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
      res.status(409).json({ error: 'Cet agenda est déjà au corpus' });
      return;
    }
    throw e;
  }
});

evalRouter.patch('/agendas/:id(\\d+)', admin, async (req, res) => {
  const parsed = evalAgendaUpdateSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  try {
    const agenda = await prisma.evalAgenda.update({
      where: { id: Number(req.params.id) },
      data: parsed.data,
    });
    res.json({ agenda });
  } catch {
    res.status(404).json({ error: 'Agenda introuvable' });
  }
});

/**
 * Remet une capture en file. Refusé sur une entrée déjà capturée.
 *
 * Recapturer réécrirait le HTML que les étiquettes décrivent, et l'on
 * retomberait très exactement dans le défaut que la séparation corrige. Pour
 * repartir d'une page fraîche, on crée une nouvelle entrée : celle-ci garde
 * ses étiquettes, et les deux se comparent.
 */
evalRouter.post('/agendas/:id(\\d+)/capture', admin, async (req, res) => {
  const id = Number(req.params.id);
  const agenda = await prisma.evalAgenda.findUnique({ where: { id }, select: { capture: true } });
  if (!agenda) {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }
  if (agenda.capture === 'CAPTURED') {
    res.status(409).json({
      error:
        'Cet agenda est déjà capturé. Recapturer réécrirait le HTML que les ' +
        'étiquettes décrivent : créez plutôt une nouvelle entrée.',
    });
    return;
  }
  const updated = await prisma.evalAgenda.update({
    where: { id },
    data: { capture: 'QUEUED', captureError: null },
  });
  res.json({ agenda: updated });
});

evalRouter.delete('/agendas/:id(\\d+)', admin, async (req, res) => {
  const id = Number(req.params.id);
  const pages = await prisma.evalAgendaPage.findMany({
    where: { agendaId: id },
    select: { htmlPath: true },
  });
  try {
    await prisma.evalAgenda.delete({ where: { id } });
  } catch {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }
  // Prisma efface les lignes en cascade, pas les fichiers.
  await deleteEvalPages(pages.map((p) => p.htmlPath));
  res.json({ ok: true });
});

/**
 * Le détail d'un agenda : ses étiquettes, et le relevé d'un run en regard.
 *
 * Le run sert de **précoche d'affichage** : sans lui, étiqueter deux cents
 * liens sur une page vierge serait invivable et personne ne le ferait deux
 * fois. Mais rien de ce qu'il dit n'entre au corpus tant qu'un humain n'a pas
 * cliqué — c'est la différence entre proposer et écrire, et c'est elle qui
 * empêche un rappel de 100 % obtenu sans que personne ait regardé.
 */
evalRouter.get('/agendas/:id(\\d+)', admin, async (req, res) => {
  const id = Number(req.params.id);
  const agenda = await prisma.evalAgenda.findUnique({
    where: { id },
    include: {
      author: { select: { id: true, displayName: true } },
      agendaPages: {
        orderBy: { pageNo: 'asc' },
        // Chaque lien porte la sortie vers laquelle il mène : c'est elle que
        // la console fait modifier, et c'est d'elle que la pertinence vient.
        include: {
          links: { orderBy: { id: 'asc' }, include: { sortie: { select: FAITS_SORTIE } } },
        },
      },
    },
  });
  if (!agenda) {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }

  const runId = Number(req.query.runId) || (await latestRunId(['HARVEST', 'SELECT']));
  const shown = runId
    ? await prisma.evalRun.findUnique({
        where: { id: runId },
        select: { settings: true, stage: true },
      })
    : null;
  const scope = scopeOf(shown);
  const pageIds = agenda.agendaPages.map((p) => p.id);
  const results = runId
    ? await prisma.evalLinkResult.findMany({
        where: { runId, pageId: { in: pageIds } },
        orderBy: [{ position: 'asc' }, { id: 'asc' }],
      })
    : [];

  const byPage = new Map<number, typeof results>();
  for (const row of results) {
    const list = byPage.get(row.pageId) ?? [];
    list.push(row);
    byPage.set(row.pageId, list);
  }

  res.json({
    agenda: {
      ...agenda,
      agendaPages: agenda.agendaPages.map(({ htmlPath, ...page }) => ({
        ...page,
        archived: Boolean(htmlPath),
        // La pertinence est **dérivée**, jamais stockée : c'est la même
        // étiquette qui sert à tous les runs, et c'est la portée du run
        // affiché qui tranche. On la calcule ici plutôt que dans la console,
        // pour qu'il n'y ait qu'une seule règle et qu'elle ne dérive pas.
        links: page.links.map((link) => ({
          ...link,
          relevance: relevanceOf(labelled(link), scope),
        })),
        /** Le relevé du run affiché, s'il y en a un. */
        results: byPage.get(page.id) ?? [],
        score: scorePage(page.links.map(labelled), byPage.get(page.id) ?? [], scope),
      })),
    },
    runId,
    scope,
  });
});

function scorePage(
  labels: LabelledLink[],
  results: { url: string; harvested: boolean; selected: boolean | null }[],
  scope: RunScope = {},
) {
  return {
    harvest: harvestScore(labels, results),
    select: results.some((r) => r.selected !== null) ? selectScore(labels, results, scope) : null,
  };
}

/**
 * Ce qu'on lit d'une sortie pour mesurer l'étage 4 : ses faits, et rien de
 * plus. Ni le titre, ni le tarif, ni le texte attendu — ils appartiennent au
 * corpus et servent aux étages 5 et 6. Chaque étage lit son sous-ensemble.
 */
const FAITS_SORTIE = {
  dateStart: true,
  dateEnd: true,
  postalCode: true,
  ageMin: true,
  ageMax: true,
  audience: true,
} as const;

type SortieRow = {
  dateStart: Date | null;
  dateEnd: Date | null;
  postalCode: string | null;
  ageMin: number | null;
  ageMax: number | null;
  audience: EvalAudience | null;
};

/**
 * Une ligne de la base, sous la forme que la mesure compare.
 *
 * Les colonnes `DATE` reviennent en `Date` calées sur minuit UTC : les rendre
 * en `YYYY-MM-DD` ici garde `evalMetrics` pur — il compare des jours, jamais
 * des instants, et n'a donc aucun fuseau où se tromper.
 */
function labelled<T extends { url: string; verdict: EvalVerdict; sortie?: SortieRow | null }>(
  link: T,
): LabelledLink {
  const s = link.sortie;
  return {
    url: link.url,
    verdict: link.verdict,
    sortie: s
      ? {
          dateStart: jour(s.dateStart),
          dateEnd: jour(s.dateEnd),
          postalCode: s.postalCode,
          ageMin: s.ageMin,
          ageMax: s.ageMax,
          audience: s.audience,
        }
      : null,
  };
}

function jour(value: Date | null): string | null {
  return value ? value.toISOString().slice(0, 10) : null;
}

/**
 * Ce que la recherche d'un run demandait, relu depuis ses réglages.
 *
 * C'est ce qui permet de dériver la pertinence sans l'avoir étiquetée — et
 * c'est pourquoi un run doit déclarer sa portée en se réclamant : sans elle,
 * aucune date ni aucun département ne peut écarter quoi que ce soit, et tout
 * devient indécidable.
 */
function scopeOf(run: { settings: string; stage: string } | null): RunScope {
  if (!run || run.stage !== 'SELECT') return {};
  const raw = parseJson<Record<string, unknown>>(run.settings, {});
  const text = (k: string) => (typeof raw[k] === 'string' ? (raw[k] as string) : undefined);
  return {
    dateFrom: text('dateFrom'),
    dateTo: text('dateTo'),
    postalPrefixes: Array.isArray(raw.postalPrefixes)
      ? (raw.postalPrefixes as unknown[]).map(String)
      : undefined,
    maxLinks: typeof raw.maxLinks === 'number' ? raw.maxLinks : undefined,
  };
}

/** La dernière exécution terminée d'un de ces étages. */
async function latestRunId(stages: ('HARVEST' | 'SELECT' | 'READ' | 'EXTRACT')[]): Promise<number> {
  const run = await prisma.evalRun.findFirst({
    where: { stage: { in: stages }, status: 'DONE' },
    orderBy: { finishedAt: 'desc' },
    select: { id: true },
  });
  return run?.id ?? 0;
}

// ── les étiquettes elles-mêmes ─────────────────────────────────────────

/** Pose ou change l'étiquette d'un lien. C'est un `upsert` : l'humain tranche. */
evalRouter.put('/pages/:pageId(\\d+)/links', admin, async (req, res) => {
  const parsed = evalLinkSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const pageId = Number(req.params.pageId);
  const page = await prisma.evalAgendaPage.findUnique({ where: { id: pageId } });
  if (!page) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  const { url, text, verdict, note, source } = parsed.data;
  // Un lien « sortie » rejoint la sortie du corpus qui porte la même adresse,
  // s'il y en a une. La jointure se fait donc toute seule dans le cas courant
  // — une sortie déjà moissonnée depuis la modération — sans qu'on ait à la
  // désigner à la main.
  //
  // On ne **crée** pas la sortie au passage : ce serait mettre au corpus, et
  // donc mettre en file de capture, deux cents pages que personne n'a demandé
  // à décrire. Le lien reste sans sortie, il est dit indécidable, et il
  // apparaît dans la liste de travail — où un bouton la crée pour de bon.
  //
  // Tout autre verdict détache : une pagination ne mène pas à une sortie, et
  // laisser un vieux rattachement la ferait compter comme telle.
  const sortie =
    verdict === 'SORTIE'
      ? await prisma.evalSortie.findUnique({ where: { url }, select: { id: true } })
      : null;
  const link = await prisma.evalLink.upsert({
    where: { pageId_url: { pageId, url } },
    create: {
      pageId,
      url,
      text,
      verdict,
      note,
      source,
      origin: 'HUMAIN',
      labelledById: req.user!.id,
      sortieId: sortie?.id ?? null,
    },
    update: {
      verdict,
      note,
      labelledAt: new Date(),
      labelledById: req.user!.id,
      sortieId: sortie?.id ?? null,
    },
  });
  res.json({ link });
});

evalRouter.patch('/links/:id(\\d+)', admin, async (req, res) => {
  const parsed = evalVerdictSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  try {
    const link = await prisma.evalLink.update({
      where: { id: Number(req.params.id) },
      // Seul ce que le corps porte est écrit : corriger la date d'un lien ne
      // doit pas remettre son verdict en cause, ni l'inverse.
      data: {
        ...parsed.data,
        origin: 'HUMAIN',
        labelledAt: new Date(),
        labelledById: req.user!.id,
      },
    });
    res.json({ link });
  } catch {
    res.status(404).json({ error: 'Étiquette introuvable' });
  }
});

/** Retirer une étiquette, c'est dire « je ne sais pas », pas « c'est faux ». */
evalRouter.delete('/links/:id(\\d+)', admin, async (req, res) => {
  try {
    await prisma.evalLink.delete({ where: { id: Number(req.params.id) } });
    res.json({ ok: true });
  } catch {
    res.status(404).json({ error: 'Étiquette introuvable' });
  }
});

/**
 * Étiqueter d'un coup les liens qu'un run a écartés sous un même motif.
 *
 * L'outil coupe dans les deux sens, et c'est assumé : expédier un motif qu'on
 * n'a pas lu fabrique un rappel flatteur. D'où l'obligation de viser un motif
 * précis plutôt que « tout le reste ».
 */
evalRouter.post('/pages/:pageId(\\d+)/bulk', admin, async (req, res) => {
  const parsed = evalBulkVerdictSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const pageId = Number(req.params.pageId);
  const { runId, verdict, reason } = parsed.data;
  const results = await prisma.evalLinkResult.findMany({
    where: { runId, pageId, harvested: false, ...(reason ? { dropReason: reason } : {}) },
    select: { url: true, text: true },
  });
  if (!results.length) {
    res.status(409).json({ error: 'Aucun lien écarté sous ce motif dans ce relevé' });
    return;
  }
  let written = 0;
  for (const row of results) {
    await prisma.evalLink.upsert({
      where: { pageId_url: { pageId, url: row.url } },
      create: {
        pageId,
        url: row.url,
        text: row.text,
        verdict,
        source: 'PAGE',
        origin: 'HUMAIN',
        labelledById: req.user!.id,
      },
      update: { verdict, labelledAt: new Date(), labelledById: req.user!.id },
    });
    written += 1;
  }
  res.json({ ok: true, labelled: written });
});

/** L'étiquette de pagination d'une page : l'adresse de la vraie suite. */
evalRouter.patch('/pages/:id(\\d+)/next', admin, async (req, res) => {
  const parsed = evalNextSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  try {
    const page = await prisma.evalAgendaPage.update({
      where: { id: Number(req.params.id) },
      data: { nextExpected: parsed.data.expected },
    });
    res.json({ page: { ...page, htmlPath: undefined, archived: Boolean(page.htmlPath) } });
  } catch {
    res.status(404).json({ error: 'Page introuvable' });
  }
});

evalRouter.get('/pages/:id(\\d+)/html', admin, async (req, res) => {
  const page = await prisma.evalAgendaPage.findUnique({
    where: { id: Number(req.params.id) },
    select: { htmlPath: true, url: true },
  });
  if (!page?.htmlPath) {
    res.status(404).json({ error: 'Aucune archive pour cette page' });
    return;
  }
  const html = await readEvalPage(page.htmlPath);
  if (html === null) {
    res.status(404).json({ error: 'Archive illisible' });
    return;
  }
  res.type('text/plain; charset=utf-8').send(html);
});

// ─────────────────────────────────────────────── corpus de lecture (ét. 5/6)

evalRouter.get('/sorties', admin, async (_req, res) => {
  const sorties = await prisma.evalSortie.findMany({
    orderBy: { createdAt: 'desc' },
    include: {
      author: { select: { id: true, displayName: true } },
      fiche: { select: { id: true, expected: true, labelledAt: true } },
    },
  });
  res.json({ sorties: sorties.map(serializeSortie) });
});

function serializeSortie<T extends { htmlPath: string | null; fiche?: unknown }>(sortie: T) {
  const { htmlPath, ...rest } = sortie;
  return { ...rest, archived: Boolean(htmlPath) };
}

evalRouter.post('/sorties', admin, async (req, res) => {
  const parsed = evalSortieSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  try {
    const sortie = await prisma.evalSortie.create({
      data: { ...parsed.data, createdById: req.user!.id },
    });
    res.status(201).json({ sortie: serializeSortie(sortie) });
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
      res.status(409).json({ error: 'Cette page est déjà au corpus' });
      return;
    }
    throw e;
  }
});

/**
 * Décrire la sortie vers laquelle un lien d'agenda mène.
 *
 * C'est le geste qui manquait. Un lien étiqueté « une sortie » dit ce qu'il
 * est, pas ce qu'elle est : tant que personne ne l'a décrite, l'étage 4 n'a
 * rien à quoi se comparer et le lien reste indécidable. Ce bouton crée la
 * sortie au corpus — ou rejoint celle qui portait déjà l'adresse — et
 * l'attache.
 *
 * La sortie n'est pas créée d'office à l'étiquetage : ce serait mettre en file
 * de capture deux cents pages que personne n'a demandé à décrire.
 */
evalRouter.post('/links/:id(\\d+)/sortie', admin, async (req, res) => {
  const link = await prisma.evalLink.findUnique({ where: { id: Number(req.params.id) } });
  if (!link) {
    res.status(404).json({ error: 'Étiquette introuvable' });
    return;
  }
  if (link.verdict !== 'SORTIE') {
    res.status(400).json({ error: 'Seul un lien étiqueté « une sortie » mène à une sortie' });
    return;
  }
  // `upsert` sur l'adresse : deux agendas peuvent annoncer la même sortie, et
  // c'est une seule sortie, décrite une seule fois.
  const sortie = await prisma.evalSortie.upsert({
    where: { url: link.url },
    create: {
      url: link.url,
      label: link.text,
      note: '',
      origin: 'MANUEL',
      createdById: req.user!.id,
    },
    update: {},
  });
  await prisma.evalLink.update({ where: { id: link.id }, data: { sortieId: sortie.id } });
  res.status(201).json({ sortie: serializeSortie(sortie) });
});

/** Les étiquettes d'une page : ce qu'elle contient. */
evalRouter.patch('/sorties/:id(\\d+)', admin, async (req, res) => {
  const parsed = evalSortieLabelSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { expectedDates, expectedMarkers, dateStart, dateEnd, ...rest } = parsed.data;
  try {
    const sortie = await prisma.evalSortie.update({
      where: { id: Number(req.params.id) },
      data: {
        ...rest,
        // Une colonne `DATE` attend un instant : on cale sur minuit UTC pour
        // que le jour saisi soit le jour relu, sous n'importe quel fuseau.
        ...(dateStart === undefined
          ? {}
          : { dateStart: dateStart === null ? null : new Date(`${dateStart}T00:00:00Z`) }),
        ...(dateEnd === undefined
          ? {}
          : { dateEnd: dateEnd === null ? null : new Date(`${dateEnd}T00:00:00Z`) }),
        ...(expectedDates === undefined
          ? {}
          : { expectedDates: expectedDates === null ? null : JSON.stringify(expectedDates) }),
        ...(expectedMarkers === undefined
          ? {}
          : { expectedMarkers: expectedMarkers === null ? null : JSON.stringify(expectedMarkers) }),
      },
    });
    res.json({ sortie: serializeSortie(sortie) });
  } catch {
    res.status(404).json({ error: 'Page introuvable' });
  }
});

evalRouter.post('/sorties/:id(\\d+)/capture', admin, async (req, res) => {
  const id = Number(req.params.id);
  const sortie = await prisma.evalSortie.findUnique({ where: { id }, select: { capture: true } });
  if (!sortie) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  if (sortie.capture === 'CAPTURED') {
    res.status(409).json({
      error:
        'Cette page est déjà capturée. Recapturer réécrirait le HTML que les ' +
        'étiquettes décrivent : créez plutôt une nouvelle entrée.',
    });
    return;
  }
  const updated = await prisma.evalSortie.update({
    where: { id },
    data: { capture: 'QUEUED', captureError: null },
  });
  res.json({ sortie: serializeSortie(updated) });
});

evalRouter.delete('/sorties/:id(\\d+)', admin, async (req, res) => {
  const id = Number(req.params.id);
  const sortie = await prisma.evalSortie.findUnique({
    where: { id },
    select: { htmlPath: true },
  });
  try {
    await prisma.evalSortie.delete({ where: { id } });
  } catch {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  await deleteEvalPages([sortie?.htmlPath ?? null]);
  res.json({ ok: true });
});

evalRouter.get('/sorties/:id(\\d+)/html', admin, async (req, res) => {
  const sortie = await prisma.evalSortie.findUnique({
    where: { id: Number(req.params.id) },
    select: { htmlPath: true },
  });
  if (!sortie?.htmlPath) {
    res.status(404).json({ error: 'Aucune archive pour cette page' });
    return;
  }
  const html = await readEvalPage(sortie.htmlPath);
  if (html === null) {
    res.status(404).json({ error: 'Archive illisible' });
    return;
  }
  res.type('text/plain; charset=utf-8').send(html);
});

/** Ce que la page annonce, champ par champ : le corpus de l'étage 6. */
evalRouter.put('/sorties/:id(\\d+)/fiche', admin, async (req, res) => {
  const parsed = evalFicheSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const sortieId = Number(req.params.id);
  const sortie = await prisma.evalSortie.findUnique({ where: { id: sortieId } });
  if (!sortie) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  const expected = JSON.stringify(parsed.data.expected);
  const fiche = await prisma.evalFiche.upsert({
    where: { sortieId },
    create: { sortieId, expected, note: parsed.data.note, createdById: req.user!.id },
    update: { expected, note: parsed.data.note, labelledAt: new Date() },
  });
  res.json({ fiche });
});

// ═══════════════════════════════════════════════════════════════ LES RUNS

/**
 * Lance un run : une brique, sur tout ce que le corpus a de capturé.
 *
 * Le run part en file ; c'est le worker qui le joue, parce que les briques
 * sont en Python et qu'une réimplémentation ne mesurerait qu'elle-même.
 */
evalRouter.post('/runs', admin, async (req, res) => {
  const parsed = evalRunSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { stage, label } = parsed.data;
  const items = await countRunnable(stage);
  if (items === 0) {
    res.status(409).json({
      error: 'Rien à mesurer : le corpus de cet étage ne contient aucune entrée capturée.',
    });
    return;
  }
  const run = await prisma.evalRun.create({
    data: { stage, label, items, requestedById: req.user!.id },
  });
  res.status(201).json({ run });
});

/** Combien d'entrées capturées un run de cet étage aurait à traiter. */
async function countRunnable(stage: 'HARVEST' | 'SELECT' | 'READ' | 'EXTRACT'): Promise<number> {
  if (stage === 'HARVEST' || stage === 'SELECT') {
    return prisma.evalAgendaPage.count({
      where: { htmlPath: { not: null }, agenda: { capture: 'CAPTURED' } },
    });
  }
  return prisma.evalSortie.count({ where: { capture: 'CAPTURED', htmlPath: { not: null } } });
}

evalRouter.get('/runs', admin, async (req, res) => {
  const parsed = evalRunListSchema.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const runs = await prisma.evalRun.findMany({
    where: parsed.data.stage ? { stage: parsed.data.stage } : {},
    orderBy: { queuedAt: 'desc' },
    take: parsed.data.limit,
    include: { requestedBy: { select: { id: true, displayName: true } } },
  });
  // La mesure de chaque run, calculée ici : c'est elle qui fait la courbe, et
  // elle n'est stockée nulle part — un run ancien se re-mesure donc contre un
  // corpus qui a grandi depuis, ce qui est exactement ce qu'on veut.
  const scored = await Promise.all(
    runs.map(async (run) => ({ ...run, score: await scoreRun(run.id, run.stage) })),
  );
  res.json({ runs: scored });
});

evalRouter.get('/runs/:id(\\d+)', admin, async (req, res) => {
  const id = Number(req.params.id);
  const run = await prisma.evalRun.findUnique({
    where: { id },
    include: { requestedBy: { select: { id: true, displayName: true } } },
  });
  if (!run) {
    res.status(404).json({ error: 'Exécution introuvable' });
    return;
  }
  res.json({ run: { ...run, score: await scoreRun(id, run.stage) }, detail: await runDetail(id, run.stage) });
});

evalRouter.delete('/runs/:id(\\d+)', admin, async (req, res) => {
  try {
    await prisma.evalRun.delete({ where: { id: Number(req.params.id) } });
    res.json({ ok: true });
  } catch {
    res.status(404).json({ error: 'Exécution introuvable' });
  }
});

// ─────────────────────────────────────────────────────────── LA MESURE
//
// Calculée, jamais stockée. Un run mesuré aujourd'hui contre un corpus qui a
// grandi depuis rend un chiffre différent d'hier — et c'est voulu : c'est le
// corpus qui fait autorité, pas la photographie qu'on en avait prise.

/** Le résumé chiffré d'un run, tel que la courbe l'affiche. */
async function scoreRun(runId: number, stage: string) {
  if (stage === 'HARVEST' || stage === 'SELECT') {
    const [run, labels, results] = await Promise.all([
      prisma.evalRun.findUnique({ where: { id: runId }, select: { settings: true, stage: true } }),
      prisma.evalLink.findMany({
        select: { url: true, verdict: true, pageId: true, sortie: { select: FAITS_SORTIE } },
      }),
      prisma.evalLinkResult.findMany({
        where: { runId },
        select: { url: true, harvested: true, selected: true, pageId: true },
      }),
    ]);
    const scope = scopeOf(run);
    // Page par page : deux agendas différents peuvent porter la même URL, et
    // les mêler ferait compter une sortie de l'un comme manquée sur l'autre.
    // Le plafond se juge aussi par page — c'est par page que le tri l'applique,
    // et c'est page par page que `sumSelect` sait laquelle sortir du rappel.
    const pages = [...new Set(results.map((r) => r.pageId))].map((pageId) => ({
      labels: labels.filter((l) => l.pageId === pageId).map(labelled),
      results: results.filter((r) => r.pageId === pageId),
    }));
    const pagination = await paginationScore(runId);

    if (stage === 'SELECT') {
      return {
        kind: 'links' as const,
        ...sumSelect(pages.map((p) => selectScore(p.labels, p.results, scope))),
        pagination,
      };
    }
    // Le dépouillement ne juge pas la pertinence : lui faire dire « 0 écartée
    // à raison » serait lui prêter un jugement qu'il ne porte pas.
    return {
      kind: 'links' as const,
      ...sumHarvest(pages.map((p) => harvestScore(p.labels, p.results))),
      pagination,
    };
  }

  if (stage === 'READ') {
    const results = await prisma.evalReadResult.findMany({
      where: { runId },
      include: {
        sortie: {
          select: { expectedImage: true, expectedDates: true, expectedMarkers: true },
        },
      },
    });
    let textOk = 0;
    let textJudged = 0;
    let imageOk = 0;
    let imageJudged = 0;
    let datesOk = 0;
    let datesJudged = 0;
    let truncated = 0;
    let tooShort = 0;
    for (const row of results) {
      const score = readScore(row.sortie, row);
      if (score.textOk !== null) {
        textJudged += 1;
        if (score.textOk) textOk += 1;
      }
      if (score.imageOk !== null) {
        imageJudged += 1;
        if (score.imageOk) imageOk += 1;
      }
      if (score.datesOk !== null) {
        datesJudged += 1;
        if (score.datesOk) datesOk += 1;
      }
      if (score.truncated) truncated += 1;
      if (score.tooShort) tooShort += 1;
    }
    return {
      kind: 'read' as const,
      items: results.length,
      textOk,
      textJudged,
      imageOk,
      imageJudged,
      datesOk,
      datesJudged,
      truncated,
      tooShort,
      // Le taux qui fait la courbe : la part des textes entiers parmi ceux
      // qu'on sait juger. Les autres ne comptent pas — un corpus muet ne doit
      // ni flatter ni accabler.
      rate: textJudged > 0 ? textOk / textJudged : null,
    };
  }

  const results = await prisma.evalExtractResult.findMany({
    where: { runId },
    include: { sortie: { select: { fiche: { select: { expected: true } } } } },
  });
  const tally = { JUSTE: 0, FAUX: 0, INVENTE: 0, MANQUE: 0, inconnu: 0 };
  for (const row of results) {
    // `row.fiche` est la fiche **structurée** que la brique a rendue — la
    // pièce à conviction que le banc stockait déjà sans s'en servir pour
    // mesurer. C'est elle qu'on compare, et plus la mise en forme.
    const attendue = parseJson<FicheRendue>(row.sortie.fiche?.expected ?? null, {});
    const rendue = parseJson<FicheRendue>(row.fiche, {});
    const score = extractScore(attendue, rendue);
    for (const key of Object.keys(tally) as (keyof typeof tally)[]) {
      tally[key] += score.tally[key];
    }
  }
  const judged = tally.JUSTE + tally.FAUX + tally.INVENTE + tally.MANQUE;
  return {
    kind: 'extract' as const,
    items: results.length,
    ...tally,
    rate: judged > 0 ? tally.JUSTE / judged : null,
  };
}

/** La pagination : ce que le run a trouvé face à ce que le corpus déclare. */
async function paginationScore(runId: number) {
  const rows = await prisma.evalLinkResult.findMany({
    where: { runId },
    distinct: ['pageId'],
    select: { pageId: true, page: { select: { nextExpected: true } } },
  });
  // `nextUrl` n'est pas par lien mais par page : il est stocké sur la première
  // ligne de résultat de la page, faute d'une table par page. On le relit donc
  // depuis le relevé complet.
  const nexts = await prisma.$queryRaw<{ pageId: number; nextUrl: string }[]>`
    SELECT DISTINCT r.pageId AS pageId, r.selectReason AS nextUrl
    FROM EvalLinkResult r WHERE r.runId = ${runId} AND r.position = -1
  `;
  const foundBy = new Map(nexts.map((n) => [n.pageId, n.nextUrl]));
  let correct = 0;
  let missed = 0;
  let wrong = 0;
  let unjudged = 0;
  for (const row of rows) {
    const expected = row.page.nextExpected;
    if (expected === null) {
      unjudged += 1;
      continue;
    }
    const got = foundBy.get(row.pageId) ?? '';
    if (got === expected) correct += 1;
    else if (!got) missed += 1;
    else wrong += 1;
  }
  return { correct, missed, wrong, unjudged };
}

/** Le détail d'un run, page par page ou fiche par fiche. */
async function runDetail(runId: number, stage: string) {
  if (stage === 'READ') {
    const rows = await prisma.evalReadResult.findMany({
      where: { runId },
      include: {
        sortie: {
          select: {
            id: true,
            url: true,
            label: true,
            expectedImage: true,
            expectedDates: true,
            expectedMarkers: true,
          },
        },
      },
    });
    return rows.map((row) => ({
      sortieId: row.sortieId,
      url: row.sortie.url,
      label: row.sortie.label,
      textChars: row.textChars,
      error: row.error,
      score: readScore(row.sortie, row),
    }));
  }
  if (stage === 'EXTRACT') {
    const rows = await prisma.evalExtractResult.findMany({
      where: { runId },
      include: {
        sortie: { select: { id: true, url: true, label: true, fiche: { select: { expected: true } } } },
      },
    });
    return rows.map((row) => {
      const attendue = parseJson<FicheRendue>(row.sortie.fiche?.expected ?? null, {});
      return {
        sortieId: row.sortieId,
        url: row.sortie.url,
        label: row.sortie.label,
        costUsd: row.costUsd,
        error: row.error,
        ...extractScore(attendue, parseJson<FicheRendue>(row.fiche, {})),
      };
    });
  }
  const results = await prisma.evalLinkResult.findMany({
    where: { runId },
    select: { pageId: true, url: true, harvested: true, selected: true },
  });
  const pageIds = [...new Set(results.map((r) => r.pageId))];
  // La même portée que le résumé du run. Sans elle, le détail page par page
  // ignorerait la fenêtre et le plafond, et n'additionnerait donc pas au
  // chiffre affiché juste au-dessus — un écart que personne ne saurait
  // expliquer, et qui ferait douter des deux.
  const run = await prisma.evalRun.findUnique({
    where: { id: runId },
    select: { settings: true, stage: true },
  });
  const scope = scopeOf(run);
  const pages = await prisma.evalAgendaPage.findMany({
    where: { id: { in: pageIds } },
    select: {
      id: true,
      url: true,
      pageNo: true,
      agenda: { select: { label: true } },
      links: { select: { url: true, verdict: true, sortie: { select: FAITS_SORTIE } } },
    },
  });
  return pages.map((page) => {
    const rows = results.filter((r) => r.pageId === page.id);
    const labels = page.links.map(labelled);
    return {
      pageId: page.id,
      url: page.url,
      pageNo: page.pageNo,
      label: page.agenda.label,
      score:
        stage === 'SELECT' ? selectScore(labels, rows, scope) : harvestScore(labels, rows),
    };
  });
}

// ═══════════════════════════════════════════════════════════════ LE WORKER

/**
 * Réclame une capture. Le corpus se construit ici, jamais dans un run.
 *
 * Les agendas d'abord : ils portent plusieurs pages et sont donc les plus
 * longs à capturer.
 */
evalRouter.post('/capture/next', async (_req, res) => {
  const agenda = await prisma.evalAgenda.findFirst({
    where: { capture: 'QUEUED' },
    orderBy: { createdAt: 'asc' },
  });
  if (agenda) {
    await prisma.evalAgenda.update({ where: { id: agenda.id }, data: { capture: 'RUNNING' } });
    res.json({ job: { kind: 'agenda', id: agenda.id, url: agenda.url, pages: agenda.pages } });
    return;
  }
  const sortie = await prisma.evalSortie.findFirst({
    where: { capture: 'QUEUED' },
    orderBy: { createdAt: 'asc' },
  });
  if (!sortie) {
    res.json({ job: null });
    return;
  }
  await prisma.evalSortie.update({ where: { id: sortie.id }, data: { capture: 'RUNNING' } });
  res.json({ job: { kind: 'sortie', id: sortie.id, url: sortie.url, pages: 1 } });
});

evalRouter.post('/capture/agenda/:id(\\d+)', bigBody, async (req, res) => {
  const parsed = evalCaptureSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const id = Number(req.params.id);
  const agenda = await prisma.evalAgenda.findUnique({ where: { id }, select: { capture: true } });
  if (!agenda) {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }
  if (agenda.capture === 'CAPTURED') {
    res.status(409).json({ error: 'Cet agenda est déjà capturé' });
    return;
  }
  // Les fichiers d'abord, hors transaction : ils ne sont pas transactionnels,
  // et une archive orpheline coûte moins qu'une ligne pointant vers un fichier
  // qui n'existe pas.
  const archived = await Promise.all(
    parsed.data.pages.map((page) => (page.html ? saveEvalPage(page.html) : Promise.resolve(''))),
  );
  await prisma.$transaction(async (tx) => {
    for (const [index, page] of parsed.data.pages.entries()) {
      await tx.evalAgendaPage.create({
        data: {
          agendaId: id,
          pageNo: page.pageNo,
          url: page.url,
          chars: page.chars,
          htmlPath: archived[index] || null,
        },
      });
    }
    await tx.evalAgenda.update({
      where: { id },
      data: { capture: 'CAPTURED', captureError: null, capturedAt: new Date() },
    });
  });
  res.json({ ok: true, pages: parsed.data.pages.length });
});

evalRouter.post('/capture/sortie/:id(\\d+)', bigBody, async (req, res) => {
  const parsed = evalCaptureSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const id = Number(req.params.id);
  const page = parsed.data.pages[0];
  const archived = page.html ? await saveEvalPage(page.html) : '';
  try {
    await prisma.evalSortie.update({
      where: { id },
      data: {
        capture: 'CAPTURED',
        captureError: null,
        capturedAt: new Date(),
        chars: page.chars,
        htmlPath: archived || null,
      },
    });
  } catch {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  res.json({ ok: true });
});

evalRouter.post('/capture/:kind(agenda|sortie)/:id(\\d+)/fail', async (req, res) => {
  const parsed = evalFailSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const id = Number(req.params.id);
  const data = { capture: 'FAILED' as const, captureError: parsed.data.error };
  try {
    if (req.params.kind === 'agenda') await prisma.evalAgenda.update({ where: { id }, data });
    else await prisma.evalSortie.update({ where: { id }, data });
    res.json({ ok: true });
  } catch {
    res.status(404).json({ error: 'Entrée introuvable' });
  }
});

/** Réclame un run en file, et note de quoi il est le run. */
evalRouter.post('/runs/next', async (req, res) => {
  const parsed = evalRunClaimSchema.safeParse(req.body ?? {});
  if (!parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const run = await prisma.evalRun.findFirst({
    where: { status: 'QUEUED' },
    orderBy: { queuedAt: 'asc' },
  });
  if (!run) {
    res.json({ run: null });
    return;
  }
  const claimed = await prisma.evalRun.update({
    where: { id: run.id },
    data: {
      status: 'RUNNING',
      startedAt: new Date(),
      codeRef: parsed.data.codeRef,
      model: parsed.data.model,
      promptHash: parsed.data.promptHash,
      settings: JSON.stringify(parsed.data.settings),
    },
  });
  res.json({ run: { id: claimed.id, stage: claimed.stage, label: claimed.label } });
});

/**
 * L'entrée suivante d'un run, **avec son HTML gelé**.
 *
 * C'est ce qui garantit le rejeu hors ligne : le worker ne retélécharge rien,
 * il rejoue la brique sur ce que le corpus a figé. Un écart entre deux runs ne
 * peut donc venir que du code.
 */
evalRouter.post('/runs/:id(\\d+)/next-item', async (req, res) => {
  const runId = Number(req.params.id);
  const run = await prisma.evalRun.findUnique({ where: { id: runId } });
  if (!run) {
    res.status(404).json({ error: 'Exécution introuvable' });
    return;
  }

  if (run.stage === 'HARVEST' || run.stage === 'SELECT') {
    const done = await prisma.evalLinkResult.findMany({
      where: { runId },
      distinct: ['pageId'],
      select: { pageId: true },
    });
    const page = await prisma.evalAgendaPage.findFirst({
      where: {
        htmlPath: { not: null },
        agenda: { capture: 'CAPTURED' },
        id: { notIn: done.map((d) => d.pageId) },
      },
      orderBy: { id: 'asc' },
      include: { agenda: { select: { url: true } } },
    });
    if (!page) {
      res.json({ item: null });
      return;
    }
    const html = page.htmlPath ? await readEvalPage(page.htmlPath) : null;
    res.json({ item: { kind: 'page', pageId: page.id, url: page.url, html: html ?? '' } });
    return;
  }

  // Les deux tables ont la même colonne mais pas le même type : les unir en
  // une variable ferait perdre à TypeScript la signature de `findMany`.
  const done =
    run.stage === 'READ'
      ? await prisma.evalReadResult.findMany({ where: { runId }, select: { sortieId: true } })
      : await prisma.evalExtractResult.findMany({ where: { runId }, select: { sortieId: true } });
  const sortie = await prisma.evalSortie.findFirst({
    where: {
      capture: 'CAPTURED',
      htmlPath: { not: null },
      id: { notIn: done.map((d) => d.sortieId) },
    },
    orderBy: { id: 'asc' },
  });
  if (!sortie) {
    res.json({ item: null });
    return;
  }
  const html = sortie.htmlPath ? await readEvalPage(sortie.htmlPath) : null;
  res.json({
    item: { kind: 'sortie', sortieId: sortie.id, url: sortie.url, html: html ?? '' },
  });
});

evalRouter.post('/runs/:id(\\d+)/links', bigBody, async (req, res) => {
  const parsed = evalLinkResultSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const runId = Number(req.params.id);
  const { pageId, links, nextUrl } = parsed.data;
  const seen = new Set<string>();
  const rows = links.filter((l) => !seen.has(l.url) && seen.add(l.url));
  await prisma.evalLinkResult.createMany({
    data: [
      // La page suivante n'est pas un lien : elle se range en position -1, une
      // ligne technique que la mesure de pagination relit. Une table par page
      // pour un seul champ aurait coûté une jointure de plus partout.
      {
        runId,
        pageId,
        url: `#next#${pageId}`,
        text: '',
        context: '',
        position: -1,
        selectReason: nextUrl,
      },
      ...rows.map((link, position) => ({
        runId,
        pageId,
        url: link.url,
        text: link.text,
        context: link.context,
        harvested: link.harvested,
        dropReason: link.reason,
        position,
        selected: link.selected ?? null,
        selectReason: link.selectReason,
      })),
    ],
    skipDuplicates: true,
  });
  res.json({ ok: true, links: rows.length });
});

evalRouter.post('/runs/:id(\\d+)/read', bigBody, async (req, res) => {
  const parsed = evalReadResultSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { sortieId, dates, error, ...rest } = parsed.data;
  await prisma.evalReadResult.create({
    data: {
      runId: Number(req.params.id),
      sortieId,
      dates: JSON.stringify(dates),
      error: error ?? null,
      ...rest,
    },
  });
  res.json({ ok: true });
});

evalRouter.post('/runs/:id(\\d+)/extract', bigBody, async (req, res) => {
  const parsed = evalExtractResultSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { sortieId, fiche, aspects, error, ...rest } = parsed.data;
  await prisma.evalExtractResult.create({
    data: {
      runId: Number(req.params.id),
      sortieId,
      fiche: JSON.stringify(fiche),
      aspects: JSON.stringify(aspects),
      error: error ?? null,
      ...rest,
    },
  });
  res.json({ ok: true });
});

/**
 * Clôt un run. C'est ce qu'on ne peut pas perdre : sans clôture, il resterait
 * « en cours » et le worker n'en prendrait plus d'autre.
 */
evalRouter.post('/runs/:id(\\d+)/finish', async (req, res) => {
  const parsed = evalRunFinishSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { status, error, ...counters } = parsed.data;
  try {
    const run = await prisma.evalRun.update({
      where: { id: Number(req.params.id) },
      data: { ...counters, status, error: error ?? null, finishedAt: new Date() },
    });
    res.json({ run });
  } catch {
    res.status(404).json({ error: 'Exécution introuvable' });
  }
});

// ══════════════════ peupler le corpus avec ce que le pipeline a déjà fait
//
// Quatre paniers, et l'équilibre entre eux est la question. Ne prendre que les
// réussites mesurerait la brique sur ses propres succès : on lirait 96 % de
// textes corrects, et ça ne voudrait rien dire.

/** Le motif exact sous lequel l'étage 5 abandonne une page. */
const ABANDON_REASON = 'page vide ou illisible';

const BUCKETS = {
  approuvees: {
    where: {
      decision: 'submitted',
      event: { is: { status: 'APPROVED' as const } },
    } satisfies Prisma.ScraperRunItemWhereInput,
    origin: 'APPROUVEE' as const,
  },
  abandonnees: {
    where: { decision: 'invalid', reason: ABANDON_REASON } satisfies Prisma.ScraperRunItemWhereInput,
    origin: 'ABANDONNEE' as const,
  },
  /**
   * Le panier qui manquait, et c'est le pire des trois : la page **lue**, dont
   * le texte a passé le seuil mais ne valait rien. Elle n'a pas été
   * abandonnée — elle a coûté une extraction, et produit une fiche qu'un
   * modérateur a refusée pour description inutilisable. Rien ne capturait ce
   * cas, et c'est exactement là qu'atterrit une page mal décodée.
   */
  illisibles: {
    where: {
      event: { is: { rejectionCode: 'DESCRIPTION_INUTILISABLE' as const } },
    } satisfies Prisma.ScraperRunItemWhereInput,
    origin: 'ILLISIBLE' as const,
  },
};

/**
 * Les sorties du corpus qui viennent d'une fiche approuvée et n'ont pas
 * encore leur étiquette de fiche.
 *
 * C'est le groupe 3 du corpus — ce qu'une sortie **est**, champ par champ — et
 * c'est la seule partie du banc qui se remplisse sans travail humain : le
 * travail a déjà eu lieu, en modération, fiche sous les yeux.
 */
async function ficheCandidates(limit: number) {
  return prisma.evalSortie.findMany({
    where: { eventId: { not: null }, fiche: { is: null } },
    select: {
      id: true,
      event: {
        select: {
          title: true,
          description: true,
          isFree: true,
          price: true,
          ageMin: true,
          ageMax: true,
          isPermanent: true,
          dateStart: true,
          dateEnd: true,
          openTime: true,
          closeTime: true,
          setting: true,
          category: { select: { name: true } },
          venue: {
            select: { name: true, address: true, postalCode: true, city: true },
          },
          /// Les jours de représentation que le site a retenus. Les
          /// `weekdays` de la prose, eux, ne lui sont jamais parvenus.
          dates: { select: { day: true } },
          // Ce qu'un modérateur a réécrit avant d'approuver. Ça ne change pas
          // la valeur — elle est déjà dans la fiche publiée — mais ça dit d'où
          // elle vient, et c'est ce qui garde l'hypothèse vérifiable.
          corrections: { select: { field: true } },
        },
      },
    },
    orderBy: { id: 'desc' },
    take: limit,
  });
}

/**
 * Les noms de champ de la modération, vers ceux de la fiche.
 *
 * Presque l'identité — et c'est le signe que les deux bouts parlent enfin la
 * même langue. Tant que l'étiquette était de la prose, il fallait passer par
 * les libellés d'aspect (« tarif », « adresse ») ; maintenant qu'elle porte
 * les faits, `price` répond à `price`.
 */
const CHAMP_VERS_FICHE: Record<string, keyof FicheRendue> = {
  title: 'title',
  description: 'description',
  isFree: 'free',
  price: 'price',
  ageMin: 'ageMin',
  ageMax: 'ageMax',
  isPermanent: 'permanent',
  dateStart: 'dateStart',
  dateEnd: 'dateEnd',
  openTime: 'openTime',
  closeTime: 'closeTime',
  setting: 'setting',
  categoryId: 'category',
  venueName: 'venueName',
  venueAddress: 'venueAddress',
  venueCity: 'venueCity',
  venuePostalCode: 'venuePostalCode',
};

/**
 * D'où vient chaque champ de l'étiquette.
 *
 * `CORRIGE` : un modérateur a réécrit ce champ avant d'approuver — une
 * étiquette indépendante du modèle. `NON_CONTREDIT` : le modèle l'a rendu, le
 * modérateur l'a laissé passer.
 *
 * La mesure les traite à égalité : l'hypothèse retenue est qu'approuver, c'est
 * avoir vérifié. Mais la distinction est conservée pour que cette hypothèse
 * reste vérifiable — si le taux de correction s'effondre un jour sur tous les
 * champs à la fois, elle aura vieilli, et on ne pourra le voir que si on l'a
 * notée.
 */
function provenances(
  attendue: FicheRendue,
  corriges: Iterable<string>,
): Record<string, 'CORRIGE' | 'NON_CONTREDIT'> {
  const changes = new Set(corriges);
  const out: Record<string, 'CORRIGE' | 'NON_CONTREDIT'> = {};
  for (const champ of Object.keys(attendue)) {
    out[champ] = changes.has(champ) ? 'CORRIGE' : 'NON_CONTREDIT';
  }
  return out;
}

async function candidates(bucket: keyof typeof BUCKETS, limit: number) {
  const rows = await prisma.scraperRunItem.findMany({
    where: BUCKETS[bucket].where,
    orderBy: { at: 'desc' },
    take: Math.min(limit * 8, 800),
    select: {
      url: true,
      title: true,
      reason: true,
      decision: true,
      at: true,
      eventId: true,
      // Les faits que l'étage 4 juge, tels qu'un modérateur les a validés.
      // Sans eux la sortie arrive au corpus sans date ni lieu, donc
      // indécidable — et la moisson n'aurait servi qu'aux étages 5 et 6.
      event: {
        select: {
          dateStart: true,
          dateEnd: true,
          ageMin: true,
          ageMax: true,
          venue: { select: { postalCode: true } },
        },
      },
    },
  });
  const seen = new Set<string>();
  const unique = rows.filter((row) => row.url && !seen.has(row.url) && seen.add(row.url));
  const already = await prisma.evalSortie.findMany({
    where: { url: { in: unique.map((r) => r.url) } },
    select: { url: true },
  });
  const known = new Set(already.map((r) => r.url));
  return unique.filter((row) => !known.has(row.url));
}

/**
 * Les étiquettes que la modération a déjà payées, sur les liens d'agenda.
 *
 * Une page qui est devenue une sortie **approuvée** est une sortie : un
 * modérateur l'a vérifiée, fiche en main. Si cette page figure parmi les liens
 * d'un agenda du corpus, l'étiquette `SORTIE` est acquise — ce n'est pas une
 * supposition de la machine mais le travail d'un humain, fait ailleurs.
 *
 * Elle n'apporte que des positifs, et c'est sa limite : elle ne dira jamais
 * qu'un lien n'est **pas** une sortie, donc elle ne remplace pas la relecture.
 * Elle la raccourcit.
 */
async function linkLabelCandidates(limit: number) {
  return prisma.$queryRaw<{ pageId: number; url: string; title: string | null }[]>`
    SELECT p.id AS pageId, i.url AS url, i.title AS title
    FROM ScraperRunItem i
    JOIN Event e ON e.id = i.eventId AND e.status = 'APPROVED'
    JOIN EvalLinkResult r ON r.url = i.url
    JOIN EvalAgendaPage p ON p.id = r.pageId
    LEFT JOIN EvalLink l ON l.pageId = p.id AND l.url = i.url
    WHERE l.id IS NULL
    GROUP BY p.id, i.url, i.title
    LIMIT ${limit}
  `;
}

/**
 * Ce qu'il reste à faire à la main, compté.
 *
 * Un run modéré donne gratuitement la **précision** : parmi ce que le scraper
 * a proposé, ce qu'un humain a validé. Le **rappel** — ce qu'il a raté — n'est
 * visible nulle part dans ce qu'il a proposé, par construction. Il se paie en
 * ouvrant les liens qu'il a laissés, et c'est l'essentiel du travail humain.
 *
 * Ces deux comptes ne raccourcissent pas ce travail : ils l'affichent. Un coût
 * qu'on découvre au fil de l'eau fait abandonner un banc au bout de trois
 * semaines ; un coût annoncé se planifie.
 */
evalRouter.get('/reste', admin, async (_req, res) => {
  const [jamaisRegardes, sansSortie] = await Promise.all([
    // 1. Les liens qu'un run a relevés et que personne n'a étiquetés. Tant
    //    qu'ils sont là, le rappel de l'étage 3 est une illusion : on ne peut
    //    pas savoir si une sortie s'y cache.
    prisma.$queryRaw<{ pageId: number; url: string; label: string; manquants: bigint }[]>`
      SELECT p.id AS pageId, p.url AS url, a.label AS label, COUNT(DISTINCT r.url) AS manquants
      FROM EvalLinkResult r
      JOIN EvalAgendaPage p ON p.id = r.pageId
      JOIN EvalAgenda a ON a.id = p.agendaId
      LEFT JOIN EvalLink l ON l.pageId = r.pageId AND l.url = r.url
      WHERE r.position >= 0 AND l.id IS NULL
      GROUP BY p.id, p.url, a.label
      ORDER BY manquants DESC
      LIMIT 50
    `,
    // 2. Les liens dont on sait que c'est une sortie, mais dont personne n'a
    //    dit ce qu'elle est. L'étage 4 n'a rien à quoi se comparer : ils
    //    comptent indécidables, ni pour ni contre.
    //
    //    Deux dettes, et elles se soldent différemment : ou bien aucune sortie
    //    n'est attachée — il faut la créer —, ou bien elle l'est mais
    //    n'affirme rien — il faut la décrire. La seconde est de loin la plus
    //    courante : c'est l'état de toute sortie moissonnée avant que la
    //    moisson ne recopie les faits. Ne lister que la première laisserait
    //    l'essentiel du travail invisible, ce qui était tout le défaut qu'on
    //    cherche à corriger.
    prisma.evalLink.findMany({
      where: {
        verdict: 'SORTIE',
        OR: [
          { sortieId: null },
          { sortie: { is: { dateStart: null, postalCode: null, audience: null, ageMax: null } } },
        ],
      },
      select: {
        id: true,
        url: true,
        text: true,
        sortieId: true,
        page: { select: { id: true, pageNo: true, agenda: { select: { id: true, label: true } } } },
      },
      orderBy: { id: 'asc' },
      take: 200,
    }),
  ]);

  res.json({
    /** Par page d'agenda : combien de liens relevés que personne n'a tranchés. */
    jamaisRegardes: jamaisRegardes.map((row) => ({
      pageId: row.pageId,
      url: row.url,
      label: row.label,
      manquants: Number(row.manquants),
    })),
    /**
     * Les sorties reconnues mais dont rien n'est affirmé. `sortieId` nul : il
     * faut la créer. Renseigné : elle existe, il faut la décrire.
     */
    sansSortie,
  });
});

evalRouter.get('/seed', admin, async (_req, res) => {
  const [approuvees, abandonnees, illisibles, liens, fiches] = await Promise.all([
    candidates('approuvees', 100),
    candidates('abandonnees', 100),
    candidates('illisibles', 100),
    linkLabelCandidates(100),
    ficheCandidates(100),
  ]);
  res.json({
    approuvees: approuvees.length,
    abandonnees: abandonnees.length,
    illisibles: illisibles.length,
    liens: liens.length,
    fiches: fiches.length,
    abandonReason: ABANDON_REASON,
  });
});

evalRouter.post('/seed', admin, async (req, res) => {
  const parsed = evalSeedSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { bucket, limit } = parsed.data;

  if (bucket === 'liens') {
    const rows = (await linkLabelCandidates(limit)).slice(0, limit);
    if (!rows.length) {
      res.status(409).json({ error: 'Aucune étiquette nouvelle à reprendre de la modération' });
      return;
    }
    // La sortie du corpus qui porte la même adresse, s'il y en a une : le lien
    // doit y mener, sinon il serait étiqueté « une sortie » sans que rien ne
    // dise laquelle, et l'étage 4 le compterait indécidable alors que tout est
    // là.
    const sorties = await prisma.evalSortie.findMany({
      where: { url: { in: rows.map((r) => r.url) } },
      select: { id: true, url: true },
    });
    const parUrl = new Map(sorties.map((s) => [s.url, s.id]));
    const created = await prisma.evalLink.createMany({
      data: rows.map((row) => ({
        pageId: row.pageId,
        url: row.url,
        text: (row.title ?? '').slice(0, 200),
        verdict: 'SORTIE' as const,
        source: 'PAGE' as const,
        origin: 'MODERATION' as const,
        sortieId: parUrl.get(row.url) ?? null,
      })),
      skipDuplicates: true,
    });
    res.status(201).json({ added: created.count });
    return;
  }

  if (bucket === 'fiches') {
    const sorties = await ficheCandidates(limit);
    if (!sorties.length) {
      res.status(409).json({ error: 'Aucune fiche approuvée à reprendre' });
      return;
    }
    let added = 0;
    for (const sortie of sorties) {
      const e = sortie.event;
      if (!e) continue;
      // Une copie de champs, pas une mise en forme : l'étiquette a exactement
      // la forme que la brique rend, donc rien à faire concorder entre deux
      // langages. `weekdays` reste absent — le site ne les reçoit pas, le
      // pipeline s'en sert pour fabriquer les dates et les jette —, et une clé
      // absente veut dire « personne n'a regardé », ce qui est la vérité.
      const attendue: FicheRendue = {
        relevant: true,
        several: false,
        title: e.title,
        description: e.description,
        free: e.isFree,
        price: e.price === null ? null : Number(e.price),
        ageMin: e.ageMin,
        ageMax: e.ageMax,
        permanent: e.isPermanent,
        dateStart: e.dateStart ? e.dateStart.toISOString().slice(0, 10) : '',
        dateEnd: e.dateEnd ? e.dateEnd.toISOString().slice(0, 10) : '',
        dates: e.dates.map((d) => d.day.toISOString().slice(0, 10)),
        openTime: e.openTime ?? '',
        closeTime: e.closeTime ?? '',
        setting: e.setting ?? '',
        category: e.category.name,
        venueName: e.venue.name,
        venueAddress: e.venue.address,
        venuePostalCode: e.venue.postalCode,
        venueCity: e.venue.city,
      };
      const corriges = e.corrections
        .map((c) => CHAMP_VERS_FICHE[c.field])
        .filter((cle): cle is keyof FicheRendue => Boolean(cle));
      await prisma.evalFiche.create({
        data: {
          sortieId: sortie.id,
          expected: JSON.stringify(attendue),
          origins: JSON.stringify(provenances(attendue, corriges)),
          note: 'Reprise d’une fiche approuvée en modération.',
          createdById: req.user!.id,
        },
      });
      added += 1;
    }
    res.status(201).json({ added });
    return;
  }

  const rows = (await candidates(bucket, limit)).slice(0, limit);
  if (!rows.length) {
    res.status(409).json({ error: 'Rien de nouveau dans ce panier' });
    return;
  }
  const created = await prisma.evalSortie.createMany({
    data: rows.map((row) => ({
      url: row.url,
      label: (row.title ?? '').slice(0, 150),
      origin: BUCKETS[bucket].origin,
      eventId: bucket === 'approuvees' ? row.eventId : null,
      readAt: row.at,
      runDecision: row.decision.slice(0, 40),
      runReason: row.reason ?? '',
      createdById: req.user!.id,
      // Les faits viennent de la fiche approuvée : une copie de colonnes, pas
      // une analyse de prose. C'est ce qui rend cette moisson gratuite pour
      // l'étage 4 autant que pour les étages 5 et 6.
      dateStart: row.event?.dateStart ?? null,
      dateEnd: row.event?.dateEnd ?? null,
      ageMin: row.event?.ageMin ?? null,
      ageMax: row.event?.ageMax ?? null,
      postalCode: row.event?.venue?.postalCode || null,
      // Voir la migration 0027 : approuvée sur ce site veut dire jeune public,
      // et c'est un humain qui l'a tranché. Les deux autres paniers n'ont
      // jamais été approuvés — on ne sait rien de leur public.
      audience: BUCKETS[bucket].origin === 'APPROUVEE' ? ('ENFANTS' as const) : null,
    })),
    skipDuplicates: true,
  });
  res.status(201).json({ added: created.count });
});
