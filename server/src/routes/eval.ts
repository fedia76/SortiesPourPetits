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
import {
  Prisma,
  Role,
  type EvalAudience,
  type EvalPageNature,
  type EvalVerdict,
} from '@prisma/client';
import { safeRouter } from '../lib/asyncRoutes';
import { prisma } from '../db';
import { comptesChasse, natureProposee, origineDe, soucheCorpus } from '../lib/evalHunt';
import { deleteEvalPages, readEvalPage, saveEvalPage } from '../lib/evalPages';
import { avancements, reprendreLesAbandonnes } from '../lib/evalRuns';
import { requireRole } from '../middleware/auth';
import {
  aspectsDetail,
  couverture,
  criteresParEtage,
  acheverAspectTallies,
  cumulerAspects,
  emptyAspectTallies,
  extractScore,
  harvestLines,
  harvestScore,
  readDetail,
  readScore,
  relevanceOf,
  selectLines,
  sortieMuette,
  selectScore,
  sumHarvest,
  sumSelect,
  type FicheRendue,
  type LabelledLink,
  type ReadLabels,
  type RunScope,
} from '../lib/evalMetrics';
import {
  evalAgendaSchema,
  evalAgendaUpdateSchema,
  evalBulkVerdictSchema,
  evalCaptureSchema,
  evalExtractResultSchema,
  evalFailSchema,
  evalEtiquetteSchema,
  evalHuntClaimSchema,
  evalHuntDecisionSchema,
  evalHuntFinishSchema,
  evalHuntPagesSchema,
  evalHuntSchema,
  evalLinkResultSchema,
  evalLinkSchema,
  evalNatureSchema,
  evalNaturePatchSchema,
  evalNextSchema,
  evalReadResultSchema,
  evalSortieLabelSchema,
  evalSortieSchema,
  CHAMPS_ETIQUETTE,
  evalCorpusSchema,
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

// Le plafond de corps de ces routes — les comptes rendus du worker portent du
// HTML gzippé en base64, bien au-delà du plafond par défaut d'Express — se pose
// dans `lib/bodyLimits`, avec le parseur global. Le déclarer ici ne servirait à
// rien : Express applique le premier parseur monté, et celui-là a déjà lu, ou
// refusé, le corps.

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

/**
 * Les agendas que la recherche auto a réellement dépouillés, et ce qu'ils ont
 * rendu.
 *
 * ## Pourquoi ce panier existe
 *
 * Le corpus des agendas se remplissait en collant des adresses à la main. Rien
 * ne garantissait alors le moindre rapport entre ces agendas-là et ce que la
 * modération avait déjà tranché — et sans recouvrement, « reprendre ce qu'un
 * humain a validé » ne reprend rien : le panier des étiquettes de lien affiche
 * zéro, chaque lien reste à étiqueter à la main, et l'étage 4 ne mesure rien
 * parce qu'il n'a aucune sortie décrite à quoi se comparer.
 *
 * Un agenda que la production a dépouillé, lui, a **par construction** des
 * liens qu'un modérateur a déjà jugés. C'est le même principe que la chasse
 * pour l'étage 2 : on ne part pas d'une page blanche, on part de ce que le
 * pipeline a déjà fait, et on corrige.
 *
 * ## Ce que le rendement passé ne promet pas
 *
 * Il compte ce que cet agenda a rendu **alors**, et la page qu'on gèlera est
 * celle d'**aujourd'hui**. Les sorties expirent, les agendas tournent : un
 * agenda choisi pour ses vingt sorties de juin peut n'en porter aucune en
 * septembre. D'où le tri sur le rendement **récent**, et d'où le fait que le
 * vrai recouvrement ne se connaît qu'après la capture et un run d'étage 3.
 */
evalRouter.get('/agendas/candidats', admin, async (_req, res) => {
  const depuis = new Date(Date.now() - 90 * 24 * 3600 * 1000);
  const rows = await prisma.$queryRaw<
    {
      url: string;
      pages: bigint;
      approuvees: bigint;
      recentes: bigint;
      refusees: bigint;
      derniere: Date | null;
      query: string | null;
    }[]
  >`
    SELECT i.agendaUrl AS url,
           COUNT(DISTINCT i.url) AS pages,
           COUNT(DISTINCT CASE WHEN e.status = 'APPROVED' THEN i.url END) AS approuvees,
           COUNT(DISTINCT CASE WHEN e.status = 'APPROVED' AND i.at >= ${depuis} THEN i.url END)
             AS recentes,
           COUNT(DISTINCT CASE WHEN e.status = 'REJECTED' THEN i.url END) AS refusees,
           MAX(i.at) AS derniere,
           MAX(i.query) AS query
    FROM ScraperRunItem i
    LEFT JOIN Event e ON e.id = i.eventId
    WHERE i.agendaUrl IS NOT NULL AND i.agendaUrl <> ''
    GROUP BY i.agendaUrl
    HAVING approuvees > 0
    ORDER BY recentes DESC, approuvees DESC
    LIMIT 40
  `;
  // Ceux qui y sont déjà ne disparaissent pas de la liste : ils sont marqués.
  // Les cacher ferait croire que la production n'a dépouillé que le reste, et
  // c'est exactement le genre de trou qui fait rajouter un agenda en double
  // sous une adresse à peine différente.
  const dejaLa = await prisma.evalAgenda.findMany({
    where: { url: { in: rows.map((r) => r.url) } },
    select: { url: true },
  });
  const connus = new Set(dejaLa.map((a) => a.url));
  res.json({
    candidats: rows.map((row) => ({
      url: row.url,
      query: row.query ?? '',
      pages: Number(row.pages),
      approuvees: Number(row.approuvees),
      recentes: Number(row.recentes),
      refusees: Number(row.refusees),
      derniere: row.derniere,
      dejaAuCorpus: connus.has(row.url),
    })),
  });
});

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
  // Combien de liens un run du banc a relevés sur cet agenda. C'est le
  // dénominateur de l'étiquetage, et sans lui la console ne pouvait pas dire
  // où en est un agenda : « 12 étiquettes » ne se lit pas de la même façon
  // selon qu'il y a quinze liens ou deux cents.
  const releves = await prisma.$queryRaw<{ agendaId: number; releves: bigint }[]>`
    SELECT p.agendaId AS agendaId, COUNT(DISTINCT r.url) AS releves
    FROM EvalLinkResult r
    JOIN EvalAgendaPage p ON p.id = r.pageId
    WHERE r.position >= 0
    GROUP BY p.agendaId
  `;
  const parAgenda = new Map(releves.map((row) => [row.agendaId, Number(row.releves)]));
  res.json({ agendas: agendas.map((agenda) => serializeAgenda(agenda, parAgenda.get(agenda.id) ?? 0)) });
});

/**
 * Un agenda tel que la console le lit — avec **où il en est**.
 *
 * La chaîne des gestes est une dépendance réelle et elle n'était écrite nulle
 * part : ajouter l'agenda, le geler, jouer un run d'étage 3, et alors seulement
 * il y a des liens à étiqueter — donc alors seulement l'étage 4 a de quoi
 * mesurer. Sauter une étape ne produit aucune erreur : ça produit un zéro, plus
 * loin, qu'on attribue à la brique.
 */
function serializeAgenda(
  agenda: {
    agendaPages: { htmlPath: string | null; _count: { links: number } }[];
    [k: string]: unknown;
  },
  releves = 0,
) {
  const { agendaPages, ...rest } = agenda;
  const etiquetes = agendaPages.reduce((sum, p) => sum + p._count.links, 0);
  return {
    ...rest,
    pagesCaptured: agendaPages.length,
    /** Liens qu'un run du banc a relevés : le dénominateur de l'étiquetage. */
    releves,
    /**
     * L'étape où cet agenda est bloqué, et rien de plus — la console dit quoi
     * faire, elle ne le fait pas.
     */
    etape:
      agendaPages.length === 0
        ? ('A_GELER' as const)
        : releves === 0
          ? ('SANS_RELEVE' as const)
          : etiquetes === 0
            ? ('A_ETIQUETER' as const)
            : etiquetes < releves
              ? ('EN_COURS' as const)
              : ('COMPLET' as const),
    // Le chemin sur le disque du serveur ne sort jamais : la console n'a
    // besoin que de savoir si l'archive existe.
    agendaPages: agendaPages.map(({ htmlPath, _count, ...page }) => ({
      ...page,
      archived: Boolean(htmlPath),
      labels: _count.links,
    })),
    /** Étiquettes posées sur l'ensemble de l'agenda. */
    labels: etiquetes,
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
const FAITS_SORTIE = { expected: true, audience: true } as const;

type SortieRow = { expected: string; audience: EvalAudience | null };

/**
 * Une ligne de la base, sous la forme que la mesure compare.
 *
 * Les faits de l'étage 4 vivent dans l'étiquette, au même endroit que ceux des
 * étages 5 et 6 : une sortie n'a qu'une étiquette, et chaque étage y lit son
 * sous-ensemble. Seule `audience` est à part — c'est la seule affirmation du
 * banc qu'aucune brique ne rend.
 */
function labelled<T extends { url: string; verdict: EvalVerdict; sortie?: SortieRow | null }>(
  link: T,
): LabelledLink {
  const s = link.sortie;
  if (!s) return { url: link.url, verdict: link.verdict, sortie: null };
  const e = parseJson<FicheRendue>(s.expected, {});
  return {
    url: link.url,
    verdict: link.verdict,
    sortie: {
      dateStart: e.dateStart ?? null,
      dateEnd: e.dateEnd ?? null,
      postalCode: e.venuePostalCode ?? null,
      ageMin: e.ageMin ?? null,
      ageMax: e.ageMax ?? null,
      audience: s.audience,
    },
  };
}

/**
 * Rattache à leur sortie les liens « une sortie » qui portent la même adresse.
 *
 * ## La faute que ça corrige
 *
 * Le rattachement ne se faisait qu'au moment d'**étiqueter le lien** : on
 * cherchait alors la sortie portant cette adresse, et s'il n'y en avait pas
 * encore, le lien restait orphelin **pour toujours**. Rien ne repassait quand
 * la sortie arrivait ensuite.
 *
 * Deux clics dans un ordre plutôt que dans l'autre — « Liens d'agenda déjà
 * tranchés » avant « Sorties publiées » — et l'étage 4 ne mesurait plus rien :
 * chaque lien comptait *indécidable*, le rappel n'existait pas, et la console
 * répondait « la sortie n'existe pas » en la montrant dans l'onglet d'à côté.
 * Un ordre de clics ne doit pas décider de ce qu'un banc sait mesurer.
 *
 * L'appariement se fait sur l'**adresse**, et c'est un fait, pas un jugement :
 * la même adresse est la même page. Un lien déjà rattaché n'est jamais
 * redirigé — on peut désigner une sortie à l'adresse différente (échange de
 * langue, redirection), et ce choix-là appartient à l'humain.
 */
async function rattacherLiens(urls: string[]): Promise<number> {
  const uniques = [...new Set(urls.filter(Boolean))];
  if (!uniques.length) return 0;
  const sorties = await prisma.evalSortie.findMany({
    where: { url: { in: uniques } },
    select: { id: true, url: true },
  });
  let rattaches = 0;
  for (const sortie of sorties) {
    const { count } = await prisma.evalLink.updateMany({
      where: { url: sortie.url, verdict: 'SORTIE', sortieId: null },
      data: { sortieId: sortie.id },
    });
    rattaches += count;
  }
  return rattaches;
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
  const text = (k: string) => (typeof raw[k] === 'string' ? raw[k] : undefined);
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
    },
  });
  res.json({ sorties: sorties.map(serializeSortie) });
});

/**
 * Une sortie telle que la console la reçoit.
 *
 * `published` dit d'où elle vient, et c'est la distinction qui compte quand on
 * regarde le corpus : ou bien elle existe sur le site — un modérateur l'a
 * approuvée, et son étiquette est donc du travail humain déjà payé —, ou bien
 * elle n'existe que dans le banc, et tout ce qu'elle affirme reste à saisir.
 *
 * Dérivé, jamais stocké : `eventId` n'est renseigné que par la moisson des
 * sorties approuvées, et c'est déjà la réponse.
 */
function serializeSortie<
  T extends {
    htmlPath: string | null;
    eventId: number | null;
    expected: string;
    audience: EvalAudience | null;
  },
>(sortie: T) {
  const { htmlPath, ...rest } = sortie;
  return {
    ...rest,
    archived: Boolean(htmlPath),
    published: sortie.eventId !== null,
    // Calculée ici et non dans la console : c'est le serveur qui détient le
    // code de mesure, donc lui seul peut dire ce qu'un étage sait lire. Une
    // liste recopiée dans la console finirait par mentir — deux compteurs l'ont
    // déjà fait.
    couverture: couverture(parseJson<FicheRendue>(sortie.expected, {}), sortie.audience),
  };
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
    // Une sortie qui entre au corpus retrouve les liens qui l'annonçaient :
    // sans ça, un lien étiqueté avant elle restait orphelin pour toujours.
    await rattacherLiens([sortie.url]);
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
  // Et tous les liens de même adresse, sur les autres agendas : deux agendas
  // peuvent annoncer la même sortie, et décrire celle-ci une fois doit les
  // servir tous. Les laisser orphelins les aurait comptés indécidables alors
  // que la sortie venait d'être créée.
  await rattacherLiens([link.url]);
  res.status(201).json({ sortie: serializeSortie(sortie) });
});

/** Les étiquettes d'une page : ce qu'elle contient. */
evalRouter.patch('/sorties/:id(\\d+)', admin, async (req, res) => {
  const parsed = evalSortieLabelSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { audience, note, ...champs } = parsed.data;
  const id = Number(req.params.id);
  const avant = await prisma.evalSortie.findUnique({
    where: { id },
    select: { expected: true, origins: true },
  });
  if (!avant) {
    res.status(404).json({ error: 'Sortie introuvable' });
    return;
  }

  // On fusionne dans l'étiquette au lieu de la réécrire : corriger une date ne
  // doit pas effacer le titre que la moisson avait rempli.
  //
  // Les trois états sont tenus par la présence de la clé. Une valeur — même
  // vide — dit « la page annonce ceci », et c'est une étiquette de plein
  // droit : c'est elle qui permet de reconnaître une valeur inventée. `null`
  // retire la clé, c'est-à-dire revient à « personne n'a regardé ».
  const expected = parseJson<Record<string, unknown>>(avant.expected, {});
  const origins = parseJson<Record<string, string>>(avant.origins, {});
  for (const cle of CHAMPS_ETIQUETTE) {
    const valeur = champs[cle];
    if (valeur === undefined) continue;
    if (valeur === null) {
      delete expected[cle];
      delete origins[cle];
    } else {
      expected[cle] = valeur;
      origins[cle] = 'SAISIE';
    }
  }

  try {
    const sortie = await prisma.evalSortie.update({
      where: { id },
      data: {
        expected: JSON.stringify(expected),
        origins: JSON.stringify(origins),
        ...(audience === undefined ? {} : { audience }),
        ...(note === undefined ? {} : { note }),
        labelledAt: new Date(),
        labelledById: req.user!.id,
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
evalRouter.put('/sorties/:id(\\d+)/etiquette', admin, async (req, res) => {
  const parsed = evalEtiquetteSchema.safeParse(req.body);
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
  // L'étiquette s'écrit sur la sortie : il n'y a qu'un objet, et qu'une
  // étiquette. Ce que chaque champ doit valoir se marque `SAISIE` — c'est un
  // humain qui l'a tapé, la provenance la plus forte qu'on ait.
  const expected = parsed.data.expected;
  const origins = Object.fromEntries(Object.keys(expected).map((cle) => [cle, 'SAISIE']));
  const updated = await prisma.evalSortie.update({
    where: { id: sortieId },
    data: {
      expected: JSON.stringify(expected),
      origins: JSON.stringify(origins),
      note: parsed.data.note,
      labelledAt: new Date(),
      labelledById: req.user!.id,
    },
  });
  res.json({ sortie: serializeSortie(updated) });
});

/**
 * Vider le corpus des sorties.
 *
 * Tout ce qui a été moissonné se remoissonne : les boutons de reprise vont
 * rechercher dans la modération, qui n'a rien perdu. Ce qui **ne** revient pas
 * tout seul, c'est ce qu'un humain a saisi à la main — d'où le compte rendu,
 * qui dit combien d'étiquettes saisies partent avec.
 *
 * Les relevés des runs passés s'en vont aussi, par cascade : ils décrivaient
 * ce que des briques ont fait sur des sorties qui n'existent plus. Les runs
 * eux-mêmes restent, avec leur date et leur coût.
 */
evalRouter.delete('/sorties', admin, async (_req, res) => {
  const [total, saisies] = await Promise.all([
    prisma.evalSortie.count(),
    prisma.evalSortie.count({ where: { labelledById: { not: null }, eventId: null } }),
  ]);
  await prisma.evalSortie.deleteMany({});
  res.json({ removed: total, handLabelled: saisies });
});

// ═══════════════════════ le corpus de l'étage 2 : ce qu'une page est
//
// La découverte rend des adresses sans rien en dire. L'étage 2 décide où
// chacune va — agenda, sortie, programme, ou rien du tout — **en lisant la
// page**. D'où le HTML gelé : une étiquette posée sur une adresse nue ne serait
// rejouable contre rien.
//
// L'erreur n'y est pas symétrique, et c'est pourquoi la mesurer vaut le coup :
// prendre une sortie pour un agenda se rattrape tout seul, prendre un agenda
// pour une sortie coûte tous ses liens.

evalRouter.get('/natures', admin, async (_req, res) => {
  const natures = await prisma.evalNature.findMany({
    orderBy: { createdAt: 'desc' },
    include: { author: { select: { id: true, displayName: true } } },
  });
  res.json({
    natures: natures.map(({ htmlPath, ...rest }) => ({ ...rest, archived: Boolean(htmlPath) })),
    // Ce que ce corpus doit à la brique qu'il mesure. La taille ne dit rien :
    // un corpus rempli en acceptant les précoches d'une chasse grossit sans
    // rien mesurer d'autre que l'étage 2 contre lui-même.
    souche: soucheCorpus(natures),
  });
});

/**
 * Mettre une page au corpus de l'étage 2, avec ce qu'elle est.
 *
 * La nature est obligatoire : cette table ne contient que des étiquettes. Pour
 * dire « je ne sais pas », on n'ajoute pas la page.
 */
evalRouter.post('/natures', admin, async (req, res) => {
  const parsed = evalNatureSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  try {
    const nature = await prisma.evalNature.create({
      data: { ...parsed.data, createdById: req.user!.id },
    });
    res.status(201).json({ nature: { ...nature, archived: false } });
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
      res.status(409).json({ error: 'Cette page est déjà au corpus' });
      return;
    }
    throw e;
  }
});

evalRouter.patch('/natures/:id(\\d+)', admin, async (req, res) => {
  const parsed = evalNaturePatchSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  try {
    const nature = await prisma.evalNature.update({
      where: { id: Number(req.params.id) },
      data: { ...parsed.data, labelledAt: new Date() },
    });
    res.json({ nature: { ...nature, archived: Boolean(nature.htmlPath) } });
  } catch {
    res.status(404).json({ error: 'Page introuvable' });
  }
});

evalRouter.delete('/natures/:id(\\d+)', admin, async (req, res) => {
  try {
    const nature = await prisma.evalNature.findUnique({
      where: { id: Number(req.params.id) },
      select: { htmlPath: true },
    });
    await prisma.evalNature.delete({ where: { id: Number(req.params.id) } });
    await deleteEvalPages([nature?.htmlPath ?? null]);
    res.json({ ok: true });
  } catch {
    res.status(404).json({ error: 'Page introuvable' });
  }
});

/**
 * Remettre une page en file de capture.
 *
 * Refusé si elle est déjà gelée : recapturer réécrirait le HTML que l'étiquette
 * décrit, et l'étiquette se retrouverait à parler d'une page qui n'existe plus.
 */
evalRouter.post('/natures/:id(\\d+)/capture', admin, async (req, res) => {
  const id = Number(req.params.id);
  const nature = await prisma.evalNature.findUnique({ where: { id }, select: { capture: true } });
  if (!nature) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  if (nature.capture === 'CAPTURED') {
    res.status(409).json({
      error:
        'Cette page est déjà capturée. Recapturer réécrirait le HTML que ' +
        'l’étiquette décrit : créez plutôt une nouvelle entrée.',
    });
    return;
  }
  const updated = await prisma.evalNature.update({
    where: { id },
    data: { capture: 'QUEUED', captureError: null },
  });
  res.json({ nature: { ...updated, archived: Boolean(updated.htmlPath) } });
});

/** Le HTML gelé d'une page du corpus de l'étage 2. */
evalRouter.get('/natures/:id(\\d+)/html', admin, async (req, res) => {
  const nature = await prisma.evalNature.findUnique({
    where: { id: Number(req.params.id) },
    select: { htmlPath: true },
  });
  if (!nature?.htmlPath) {
    res.status(404).json({ error: 'Aucun HTML gelé pour cette page' });
    return;
  }
  const html = await readEvalPage(nature.htmlPath);
  res.type('html').send(html);
});

// ═══════════════════════════ la chasse : peupler le corpus de l'étage 2
//
// Étiqueter est le seul travail coûteux du banc, et ce corpus-ci le payait au
// prix fort : une adresse collée à la main, une nature choisie, un gel
// demandé, et on recommence. Une chasse fait le trajet d'un coup — l'étage 1
// lance les recherches depuis un prompt, l'étage 2 dit ce qu'il pense de
// chaque page qu'elles remontent, et il ne reste qu'à corriger ce qui est
// faux.
//
// ## Le danger, et il faut le nommer ici plutôt que le découvrir dans six mois
//
// Un corpus rempli en acceptant les propositions de la brique mesurerait la
// brique **contre elle-même** : le taux monterait à mesure qu'on valide vite,
// et rien ne distinguerait ce chiffre-là d'un vrai. D'où deux choses, dans
// `lib/evalHunt.ts` :
//
// * une page que l'étage 2 ne sait pas reconnaître part **sans précoche**. Le
//   pipeline, lui, tranche — il traite « inconnu » en agenda — mais c'est une
//   décision d'orchestration, et la recopier écrirait au corpus ce que le
//   pipeline *fait* au lieu de ce que la page *est* ;
// * ce qu'un humain a **corrigé** est gardé à part de ce qu'il a laissé
//   passer (`EvalNature.origin`). Les renseignements sont dans les `CORRIGE`.

/** Ce qu'une chasse montre dans la console, candidates comprises. */
const CHASSE_AVEC_PAGES = {
  author: { select: { id: true, displayName: true } },
  pages: { orderBy: { id: 'asc' } },
} as const;

/**
 * Ce qu'une candidate porte de nécessaire au compte. Le reste part tel quel.
 *
 * `htmlPath` ne sort **jamais** : le chemin d'une archive n'a rien à faire
 * dans une réponse, et la console n'a besoin que de savoir si elle existe.
 */
interface CandidateRendue {
  htmlPath: string | null;
  decision: string;
  proposed: EvalPageNature | null;
  error: string;
}

function chasseRendue<
  T extends { queries: string; ranQueries: string; pages: CandidateRendue[] },
>(hunt: T) {
  const { queries, ranQueries, pages, ...rest } = hunt;
  return {
    ...rest,
    queries: parseJson<string[]>(queries, []),
    ranQueries: parseJson<string[]>(ranQueries, []),
    comptes: comptesChasse(pages),
    pages: pages.map(({ htmlPath, ...page }) => ({ ...page, archived: Boolean(htmlPath) })),
  };
}

evalRouter.get('/hunts', admin, async (_req, res) => {
  await reprendreLesAbandonnes();
  const hunts = await prisma.evalHunt.findMany({
    orderBy: { queuedAt: 'desc' },
    take: 20,
    include: CHASSE_AVEC_PAGES,
  });
  res.json({ hunts: hunts.map(chasseRendue) });
});

/**
 * Met une chasse en file. C'est le worker qui la joue — les recherches et la
 * reconnaissance sont en Python, et les refaire ici mesurerait autre chose.
 */
evalRouter.post('/hunts', admin, async (req, res) => {
  const parsed = evalHuntSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { queries, ...reste } = parsed.data;
  const hunt = await prisma.evalHunt.create({
    data: {
      ...reste,
      queries: JSON.stringify(queries),
      ranQueries: '[]',
      createdById: req.user!.id,
    },
    include: CHASSE_AVEC_PAGES,
  });
  res.status(201).json({ hunt: chasseRendue(hunt) });
});

/**
 * Oublie une chasse et ce qu'elle avait ramené.
 *
 * Les pages **retenues** ne bougent pas : elles sont au corpus, elles ont leur
 * propre archive, et elles ne doivent rien à la chasse qui les a trouvées. Ce
 * qu'on efface ici, ce sont les candidates qu'on n'a pas prises — et leurs
 * archives avec, faute de quoi le disque garderait pour toujours le HTML de
 * pages que personne n'a voulues.
 */
evalRouter.delete('/hunts/:id(\\d+)', admin, async (req, res) => {
  const id = Number(req.params.id);
  const pages = await prisma.evalHuntPage.findMany({
    where: { huntId: id },
    select: { htmlPath: true },
  });
  try {
    await prisma.evalHunt.delete({ where: { id } });
  } catch {
    res.status(404).json({ error: 'Chasse introuvable' });
    return;
  }
  await deleteEvalPages(pages.map((p) => p.htmlPath));
  res.json({ ok: true });
});

/** Le HTML gelé d'une candidate, tel que la précoche l'a vu. */
evalRouter.get('/hunts/pages/:id(\\d+)/html', admin, async (req, res) => {
  const page = await prisma.evalHuntPage.findUnique({
    where: { id: Number(req.params.id) },
    select: { htmlPath: true },
  });
  if (!page?.htmlPath) {
    res.status(404).json({ error: 'Aucun HTML gelé pour cette candidate' });
    return;
  }
  res.type('html').send(await readEvalPage(page.htmlPath));
});

/**
 * Ce qu'un humain fait des candidates : le seul endroit où le corpus grandit.
 *
 * Une nature retient la page et l'écrit au corpus ; `null` l'écarte. Une
 * candidate qu'on ne nomme pas **reste en attente** — valider par paquets ne
 * doit pas trancher à la place de personne sur ce qu'on n'a pas regardé.
 *
 * L'archive change de main sans être retéléchargée : la page qu'un run
 * rejouera est donc exactement celle sur laquelle la précoche a été faite, et
 * non celle que le site servirait aujourd'hui. Une candidate injoignable le
 * jour de la chasse entre quand même, en file de capture : c'est le seul cas
 * où le corpus attend encore un gel.
 */
evalRouter.post('/hunts/:id(\\d+)/decide', admin, async (req, res) => {
  const parsed = evalHuntDecisionSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const huntId = Number(req.params.id);
  const voulues = new Map(parsed.data.decisions.map((d) => [d.pageId, d.nature]));
  const pages = await prisma.evalHuntPage.findMany({
    where: { huntId, id: { in: [...voulues.keys()] }, decision: 'EN_ATTENTE' },
  });

  const retenues: number[] = [];
  const doublons: string[] = [];
  const aEffacer: (string | null)[] = [];

  for (const page of pages) {
    const nature = voulues.get(page.id) ?? null;
    if (nature === null) {
      aEffacer.push(page.htmlPath);
      await prisma.evalHuntPage.update({
        where: { id: page.id },
        data: { decision: 'ECARTEE', decidedAt: new Date(), htmlPath: null },
      });
      continue;
    }
    try {
      const entree = await prisma.evalNature.create({
        data: {
          url: page.url,
          label: page.title.slice(0, 150),
          nature,
          proposed: page.proposed,
          origin: origineDe(page.proposed, nature),
          // Le HTML est déjà là : l'entrée naît gelée. Sans archive — la page
          // était injoignable —, elle part en file de capture comme une
          // adresse saisie à la main.
          capture: page.htmlPath ? 'CAPTURED' : 'QUEUED',
          capturedAt: page.htmlPath ? new Date() : null,
          chars: page.chars,
          htmlPath: page.htmlPath,
          createdById: req.user!.id,
        },
      });
      await prisma.evalHuntPage.update({
        where: { id: page.id },
        // L'archive appartient désormais à l'entrée du corpus. La laisser
        // aussi ici ferait qu'écarter la candidate, plus tard, effacerait le
        // fichier sous les pieds du corpus.
        data: {
          decision: 'RETENUE',
          decidedAt: new Date(),
          natureId: entree.id,
          htmlPath: null,
        },
      });
      retenues.push(page.id);
    } catch (e) {
      if (!(e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002')) throw e;
      // Déjà au corpus, par une autre chasse ou à la main. On n'écrase pas une
      // étiquette existante : elle a peut-être coûté une vérification.
      doublons.push(page.url);
      aEffacer.push(page.htmlPath);
      await prisma.evalHuntPage.update({
        where: { id: page.id },
        data: { decision: 'ECARTEE', decidedAt: new Date(), htmlPath: null },
      });
    }
  }

  await deleteEvalPages(aEffacer);
  const hunt = await prisma.evalHunt.findUnique({
    where: { id: huntId },
    include: CHASSE_AVEC_PAGES,
  });
  res.json({
    retenues: retenues.length,
    ecartees: pages.length - retenues.length - doublons.length,
    doublons,
    hunt: hunt ? chasseRendue(hunt) : null,
  });
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
  const { stage, label, recherche, extraction } = parsed.data;
  const items = await countRunnable(stage);
  if (items === 0) {
    res.status(409).json({
      error: 'Rien à mesurer : le corpus de cet étage ne contient aucune entrée capturée.',
    });
    return;
  }
  const run = await prisma.evalRun.create({
    // La recherche est fixée **ici**, au lancement, et en dates absolues. Le
    // worker la lira au lieu de la fabriquer : c'est la console qui décide sous
    // quoi on mesure, pas la machine qui mesure.
    //
    // Le fournisseur voyage dans les mêmes réglages, sous sa propre clé. Pas
    // de colonne pour lui : `settings` est prévue pour ça — « les réglages en
    // vigueur, en JSON » —, et un run lancé avant ce changement n'a
    // simplement pas la clé, donc retombe sur le fournisseur de production.
    data: {
      stage,
      label,
      items,
      requestedById: req.user!.id,
      settings: JSON.stringify({
        ...(recherche ?? {}),
        ...(extraction ? { extraction } : {}),
      }),
    },
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
  await reprendreLesAbandonnes();
  const runs = await prisma.evalRun.findMany({
    where: parsed.data.stage ? { stage: parsed.data.stage } : {},
    orderBy: { queuedAt: 'desc' },
    take: parsed.data.limit,
    include: { requestedBy: { select: { id: true, displayName: true } } },
  });
  // Ce qui est fait, compté depuis ce que les runs ont écrit. Sans ce chiffre,
  // « En cours » ne disait pas la différence entre un run qui avance et un run
  // qui n'avancera plus.
  const faits = await avancements(runs);
  // La mesure de chaque run, calculée ici : c'est elle qui fait la courbe, et
  // elle n'est stockée nulle part — un run ancien se re-mesure donc contre un
  // corpus qui a grandi depuis, ce qui est exactement ce qu'on veut.
  const scored = await Promise.all(
    runs.map(async (run) => ({
      ...run,
      traites: faits.get(run.id) ?? 0,
      score: await scoreRun(run.id, run.stage),
    })),
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
  const faits = await avancements([run]);
  res.json({
    run: { ...run, traites: faits.get(id) ?? 0, score: await scoreRun(id, run.stage) },
    detail: await runDetail(id, run.stage),
  });
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
        sortie: { select: { expected: true } },
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
      const score = readScore(parseJson<ReadLabels>(row.sortie.expected, {}), row);
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
    include: { sortie: { select: { expected: true } } },
  });
  const tally = { JUSTE: 0, FAUX: 0, INVENTE: 0, MANQUE: 0, inconnu: 0 };
  // Le même décompte, **aspect par aspect**. Le taux global d'un run est une
  // moyenne sur douze choses très différentes, et il cache ce qu'on veut
  // savoir : lequel lâche. Douze aspects médiocres et onze corrects pour un
  // effondré donnent le même chiffre, et n'appellent pas le même travail.
  const parAspect = emptyAspectTallies();

  for (const row of results) {
    // `row.fiche` est la fiche **structurée** que la brique a rendue — la
    // pièce à conviction que le banc stockait déjà sans s'en servir pour
    // mesurer. C'est elle qu'on compare, et plus la mise en forme.
    const attendue = parseJson<FicheRendue>(row.sortie.expected, {});
    const rendue = parseJson<FicheRendue>(row.fiche, {});
    const score = extractScore(attendue, rendue);
    for (const key of Object.keys(tally) as (keyof typeof tally)[]) {
      tally[key] += score.tally[key];
    }
    // `byField` était calculé puis jeté : c'est lui qui portait la réponse.
    cumulerAspects(parAspect, score.byField);
  }
  const judged = tally.JUSTE + tally.FAUX + tally.INVENTE + tally.MANQUE;
  return {
    kind: 'extract' as const,
    items: results.length,
    ...tally,
    rate: judged > 0 ? tally.JUSTE / judged : null,
    parAspect: acheverAspectTallies(parAspect),
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

/** Ce qu'on garde d'un texte de contexte : de quoi reconnaître le lien, pas plus. */
function coupe(value: string, max = 300): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

/**
 * Le détail d'un run — et « détail » veut dire **la ligne**, pas un total plus
 * petit.
 *
 * Un résumé ne se relit pas : « 12 manquées » ne dit ni lesquelles, ni
 * pourquoi, et un chiffre surprenant qu'on ne peut pas remonter jusqu'à la
 * ligne qui l'a produit ne laisse le choix qu'entre le croire et le jeter.
 * Chaque ligne porte donc trois choses : ce que le corpus dit, ce que la brique
 * a fait, et la phrase qui explique dans quelle case elle tombe — phrase
 * fabriquée par la mesure elle-même, jamais reconstituée ici.
 */
async function runDetail(runId: number, stage: string) {
  if (stage === 'READ') {
    const rows = await prisma.evalReadResult.findMany({
      where: { runId },
      include: {
        sortie: { select: { id: true, url: true, label: true, expected: true } },
      },
    });
    return rows.map((row) => {
      const labels = parseJson<ReadLabels>(row.sortie.expected, {});
      return {
        sortieId: row.sortieId,
        url: row.sortie.url,
        label: row.sortie.label,
        textChars: row.textChars,
        error: row.error,
        score: readScore(labels, row),
        // L'attendu et le rendu côte à côte : sans eux, « le texte n'est pas
        // entier » n'indique pas si la page est tronquée, si elle passe par du
        // JavaScript, ou si le fragment attendu était mal choisi — et les trois
        // se corrigent à trois endroits différents.
        detail: readDetail(labels, row),
      };
    });
  }
  if (stage === 'EXTRACT') {
    const rows = await prisma.evalExtractResult.findMany({
      where: { runId },
      include: {
        sortie: { select: { id: true, url: true, label: true, expected: true } },
      },
    });
    return rows.map((row) => {
      const attendue = parseJson<FicheRendue>(row.sortie.expected, {});
      const rendue = parseJson<FicheRendue>(row.fiche, {});
      return {
        sortieId: row.sortieId,
        url: row.sortie.url,
        label: row.sortie.label,
        costUsd: row.costUsd,
        error: row.error,
        ...extractScore(attendue, rendue),
        // Les deux valeurs comparées, aspect par aspect. « FAUX » sans elles est
        // une accusation sans pièce jointe : on ne sait pas si le modèle s'est
        // trompé, si l'étiquette était fautive, ou si les deux disent la même
        // chose autrement — et ce dernier cas est une faute de la mesure, qu'aucun
        // total ne révélera.
        aspects: aspectsDetail(attendue, rendue),
      };
    });
  }
  const results = await prisma.evalLinkResult.findMany({
    where: { runId },
    select: {
      pageId: true,
      url: true,
      text: true,
      context: true,
      position: true,
      harvested: true,
      dropReason: true,
      selected: true,
      selectReason: true,
    },
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
      nextExpected: true,
      agenda: { select: { label: true } },
      links: { select: { url: true, verdict: true, sortie: { select: FAITS_SORTIE } } },
    },
  });
  return pages.map((page) => {
    // La ligne de position négative n'est pas un lien : c'est la pagination,
    // rangée là faute d'une table par page. La montrer parmi les liens ferait
    // une ligne fantôme que le total ne compte nulle part.
    const rows = results.filter((r) => r.pageId === page.id && r.position >= 0);
    const labels = page.links.map(labelled);
    const tri = stage === 'SELECT';
    const { lignes, plafonnee } = tri
      ? selectLines(labels, rows, scope)
      : { lignes: harvestLines(labels, rows), plafonnee: false };
    // Ce que la brique a dit d'elle-même, à côté de ce que la mesure conclut.
    // C'est le seul moyen de distinguer « le modèle a mal jugé » de « le modèle
    // n'a jamais vu ce lien », qui ne se corrigent pas au même étage.
    const parUrl = new Map(rows.map((r) => [r.url, r]));
    return {
      pageId: page.id,
      url: page.url,
      pageNo: page.pageNo,
      label: page.agenda.label,
      plafonnee,
      score: tri ? selectScore(labels, rows, scope) : harvestScore(labels, rows),
      pagination: {
        attendu: page.nextExpected,
        trouve: results.find((r) => r.pageId === page.id && r.position < 0)?.selectReason ?? '',
      },
      liens: lignes.map((ligne) => {
        const releve = parUrl.get(ligne.url);
        return {
          ...ligne,
          texte: releve?.text ?? '',
          // Le contexte et le motif sont coupés : une page d'agenda porte deux
          // cents liens, et le détail d'un run en couvre toutes les pages. Un
          // contexte entier par ligne ferait plusieurs mégaoctets de réponse
          // pour un tableau qui n'en affiche de toute façon que le début.
          contexte: coupe(releve?.context ?? ''),
          motif: coupe((tri ? releve?.selectReason : releve?.dropReason) ?? ''),
        };
      }),
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
  if (sortie) {
    await prisma.evalSortie.update({ where: { id: sortie.id }, data: { capture: 'RUNNING' } });
    res.json({ job: { kind: 'sortie', id: sortie.id, url: sortie.url, pages: 1 } });
    return;
  }
  // Le corpus de l'étage 2 passe en dernier : c'est le plus récent, et le moins
  // pressé — rien ne dépend de lui pour jouer un run.
  const nature = await prisma.evalNature.findFirst({
    where: { capture: 'QUEUED' },
    orderBy: { createdAt: 'asc' },
  });
  if (!nature) {
    res.json({ job: null });
    return;
  }
  await prisma.evalNature.update({ where: { id: nature.id }, data: { capture: 'RUNNING' } });
  res.json({ job: { kind: 'nature', id: nature.id, url: nature.url, pages: 1 } });
});

evalRouter.post('/capture/agenda/:id(\\d+)', async (req, res) => {
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

/**
 * Le HTML gelé d'une page à une seule page — une sortie, ou une page du corpus
 * de l'étage 2. Le geste est le même, seule la table change.
 */
async function rendreCapture(
  table: 'sortie' | 'nature',
  id: number,
  page: { html?: string; chars: number },
) {
  const archived = page.html ? await saveEvalPage(page.html) : '';
  const data = {
    capture: 'CAPTURED' as const,
    captureError: null,
    capturedAt: new Date(),
    chars: page.chars,
    htmlPath: archived || null,
  };
  if (table === 'sortie') await prisma.evalSortie.update({ where: { id }, data });
  else await prisma.evalNature.update({ where: { id }, data });
}

evalRouter.post('/capture/:kind(sortie|nature)/:id(\\d+)', async (req, res) => {
  const parsed = evalCaptureSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  try {
    await rendreCapture(
      req.params.kind as 'sortie' | 'nature',
      Number(req.params.id),
      parsed.data.pages[0],
    );
  } catch {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  res.json({ ok: true });
});

evalRouter.post('/capture/:kind(agenda|sortie|nature)/:id(\\d+)/fail', async (req, res) => {
  const parsed = evalFailSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  const id = Number(req.params.id);
  const data = { capture: 'FAILED' as const, captureError: parsed.data.error };
  try {
    if (req.params.kind === 'agenda') await prisma.evalAgenda.update({ where: { id }, data });
    else if (req.params.kind === 'nature') await prisma.evalNature.update({ where: { id }, data });
    else await prisma.evalSortie.update({ where: { id }, data });
    res.json({ ok: true });
  } catch {
    res.status(404).json({ error: 'Entrée introuvable' });
  }
});

/**
 * Réclame une chasse. Elle passe **après** les captures et **avant** les runs.
 *
 * Après les captures parce que geler ne coûte rien, là où une chasse lance de
 * vraies recherches. Avant les runs pour la raison qui met déjà les captures
 * avant eux : un run joué sur un corpus incomplet mesure ce qu'on avait sous
 * la main plutôt que ce qu'on voulait mesurer.
 */
evalRouter.post('/hunts/next', async (req, res) => {
  const parsed = evalHuntClaimSchema.safeParse(req.body ?? {});
  if (!parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  // Un worker qui réclame du travail est le meilleur moment pour solder ce qui
  // traîne : il n'en joue qu'un à la fois, donc ce qui est encore « en cours »
  // ici a de bonnes chances d'appartenir à un worker qui n'existe plus. C'est
  // le seuil qui tranche, pas cette réclamation — mais c'est ici qu'il tombe
  // sans qu'on ait à faire tourner une minuterie de plus.
  await reprendreLesAbandonnes();
  const hunt = await prisma.evalHunt.findFirst({
    where: { status: 'QUEUED' },
    orderBy: { queuedAt: 'asc' },
  });
  if (!hunt) {
    res.json({ hunt: null });
    return;
  }
  const maintenant = new Date();
  await prisma.evalHunt.update({
    where: { id: hunt.id },
    data: {
      status: 'RUNNING',
      startedAt: maintenant,
      heartbeatAt: maintenant,
      codeRef: parsed.data.codeRef,
    },
  });
  res.json({
    hunt: {
      id: hunt.id,
      prompt: hunt.prompt,
      area: hunt.area,
      queries: parseJson<string[]>(hunt.queries, []),
      maxQueries: hunt.maxQueries,
      maxPages: hunt.maxPages,
      provider: hunt.provider,
    },
  });
});

/**
 * Les candidates d'une chasse, par paquets, avec leur HTML gelé.
 *
 * Une chasse interrompue laisse donc ce qu'elle avait déjà trouvé, qui reste
 * bon à valider — le contraire de tout ou rien.
 *
 * Deux fois la même adresse ne fait qu'une candidate : les moteurs remontent
 * la même page sous deux requêtes, et la dédoublonner ici évite de faire
 * trancher deux fois le même cas à un humain.
 */
evalRouter.post('/hunts/:id(\\d+)/pages', async (req, res) => {
  const parsed = evalHuntPagesSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const huntId = Number(req.params.id);
  const hunt = await prisma.evalHunt.findUnique({ where: { id: huntId }, select: { id: true } });
  if (!hunt) {
    res.status(404).json({ error: 'Chasse introuvable' });
    return;
  }
  // Une chasse ne réclame rien au fil de l'eau : ce paquet est le seul signe
  // de vie qu'elle donne, et il tombe toutes les cinq pages.
  await prisma.evalHunt.update({ where: { id: huntId }, data: { heartbeatAt: new Date() } });
  // Les fichiers d'abord, hors transaction : une archive orpheline coûte moins
  // qu'une ligne pointant vers un fichier qui n'existe pas.
  const archives = await Promise.all(
    parsed.data.pages.map((page) => (page.html ? saveEvalPage(page.html) : Promise.resolve(''))),
  );
  let ecrites = 0;
  for (const [index, page] of parsed.data.pages.entries()) {
    const { html: _html, nature, foundUrl, ...reste } = page;
    try {
      await prisma.evalHuntPage.create({
        data: {
          ...reste,
          huntId,
          foundUrl: foundUrl === page.url ? '' : foundUrl,
          proposed: natureProposee(nature),
          htmlPath: archives[index] || null,
        },
      });
      ecrites += 1;
    } catch (e) {
      if (!(e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002')) throw e;
      await deleteEvalPages([archives[index] || null]);
    }
  }
  res.json({ ok: true, pages: ecrites });
});

/**
 * Clôt une chasse, et lui fait dire ce qu'elle a été.
 *
 * Les requêtes **réellement lancées** s'écrivent ici, et pas au lancement : la
 * console n'en impose pas toujours, et une chasse qui tait celles que le
 * modèle a formulées ne se rejoue pas. Même raison que le modèle et
 * l'empreinte du prompt d'un run — on ne déclare que ce qui est déjà vrai.
 */
evalRouter.post('/hunts/:id(\\d+)/finish', async (req, res) => {
  const parsed = evalHuntFinishSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { status, queries, overCap, model, costUsd, error } = parsed.data;
  const id = Number(req.params.id);
  const avant = await prisma.evalHunt.findUnique({ where: { id }, select: { status: true } });
  if (!avant) {
    res.status(404).json({ error: 'Chasse introuvable' });
    return;
  }
  // Même règle que pour un run : une chasse reprise par le site garde son
  // verdict, et ne reçoit de sa clôture tardive que ce qu'elle a coûté.
  const repris = avant.status !== 'RUNNING';
  const declare = { ranQueries: JSON.stringify(queries), overCap, model, costUsd };
  await prisma.evalHunt.update({
    where: { id },
    data: repris
      ? { ...declare, endedAt: new Date() }
      : { ...declare, status, error: error ?? null, endedAt: new Date() },
  });
  res.json({ ok: true, repris });
});

/** Réclame un run en file, et note de quoi il est le run. */
evalRouter.post('/runs/next', async (req, res) => {
  const parsed = evalRunClaimSchema.safeParse(req.body ?? {});
  if (!parsed.success) {
    res.status(400).json({ error: 'Requête invalide' });
    return;
  }
  // Même moment, même raison que pour les chasses.
  await reprendreLesAbandonnes();
  const run = await prisma.evalRun.findFirst({
    where: { status: 'QUEUED' },
    orderBy: { queuedAt: 'asc' },
  });
  if (!run) {
    res.json({ run: null });
    return;
  }
  // Le worker déclare la **révision** qui tourne. Pas son modèle ni l'empreinte
  // de son prompt : il ne les connaît qu'une fois ce run réclamé, puisque c'est
  // l'étage du run qui les dit. Ils arrivent à la clôture, et c'est pour cela
  // que les deux colonnes restaient vides jusqu'ici.
  //
  // Il ne déclare pas non plus **ce qu'on cherche** : ça vient du run, fixé au
  // lancement depuis la console. Sans quoi la recherche que le modèle reçoit et
  // celle contre laquelle on le juge pourraient diverger.
  //
  // Un run mis en file avant ce changement porte des réglages vides : le worker
  // retombe alors sur la configuration par défaut du banc, et le dit.
  const maintenant = new Date();
  const claimed = await prisma.evalRun.update({
    where: { id: run.id },
    data: {
      status: 'RUNNING',
      startedAt: maintenant,
      heartbeatAt: maintenant,
      codeRef: parsed.data.codeRef,
    },
  });
  // Les deux réglages voyagent ensemble en base et se séparent ici : le worker
  // reçoit « sous quelle recherche » et « par qui » comme deux choses
  // distinctes, parce qu'elles le sont. Mêler le fournisseur à la recherche
  // ferait qu'un run d'extraction — qui n'a pas de recherche — devrait en
  // porter une factice pour dire qui le joue.
  const { extraction, ...recherche } = parseJson<Record<string, unknown>>(claimed.settings, {});
  res.json({
    run: {
      id: claimed.id,
      stage: claimed.stage,
      label: claimed.label,
      // Combien d'entrées l'attendent. Le worker n'en fait rien d'autre que
      // l'afficher — « 42/160 » plutôt que « 42 » —, mais un run de banc est
      // muet pendant une heure, et un compteur sans total ne dit pas s'il
      // reste dix entrées ou cent.
      items: claimed.items,
      recherche,
      extraction: extraction ?? null,
    },
  });
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
  // Un run que le site a reconnu abandonné n'a plus d'entrée à donner. C'est
  // ce qui rend la reprise sans danger : si le worker était vivant après tout,
  // il s'arrête ici proprement et clôt le run avec ses vrais compteurs, au lieu
  // de continuer à écrire dans une mesure que la console dit close.
  if (run.status !== 'RUNNING') {
    res.json({ item: null });
    return;
  }
  // Le battement, gratuit : c'est l'appel que le worker fait déjà, une fois par
  // entrée. Rien à déclarer, donc rien qui puisse mentir.
  await prisma.evalRun.update({ where: { id: runId }, data: { heartbeatAt: new Date() } });

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

/**
 * Le corpus étiqueté, tel quel : ce dont un classifieur local s'entraîne.
 *
 * C'est la première route qui rend une **étiquette** au worker, et ça mérite
 * d'être dit : partout ailleurs il travaille en aveugle, parce qu'une brique
 * qui verrait la réponse ne mesurerait plus rien. Ici il ne mesure pas, il
 * apprend — et un jeu d'entraînement sans étiquettes n'apprend rien.
 *
 * Le HTML part avec, parce que le texte qu'un classifieur doit lire est celui
 * que l'étage 5 produira en production, et l'étage 5 est en Python. Le
 * recalculer ici comparerait deux implémentations au lieu d'entraîner sur la
 * bonne.
 *
 * Seules les entrées **étiquetées** sortent : une page capturée que personne
 * n'a relue n'a pas de vérité à enseigner.
 */
evalRouter.post('/corpus/etiquettes', async (req, res) => {
  const parsed = evalCorpusSchema.safeParse(req.body ?? {});
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { after, limit } = parsed.data;
  const sorties = await prisma.evalSortie.findMany({
    where: {
      capture: 'CAPTURED',
      htmlPath: { not: null },
      labelledAt: { not: null },
      id: { gt: after },
    },
    orderBy: { id: 'asc' },
    take: limit,
    select: { id: true, url: true, expected: true, htmlPath: true },
  });
  const items = [];
  for (const sortie of sorties) {
    const html = sortie.htmlPath ? await readEvalPage(sortie.htmlPath) : null;
    items.push({
      sortieId: sortie.id,
      url: sortie.url,
      expected: sortie.expected,
      html: html ?? '',
    });
  }
  // `next` est le curseur à redemander, et il vaut le dernier identifiant
  // **servi** — pas le dernier lu en base. Une page dont le HTML a disparu
  // sort quand même, avec un HTML vide : la sauter silencieusement ferait
  // compter un corpus plus petit qu'il n'est, sans dire pourquoi.
  const next = sorties.length === limit ? sorties[sorties.length - 1].id : null;
  res.json({ items, next });
});

evalRouter.post('/runs/:id(\\d+)/links', async (req, res) => {
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

evalRouter.post('/runs/:id(\\d+)/read', async (req, res) => {
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

evalRouter.post('/runs/:id(\\d+)/extract', async (req, res) => {
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
 *
 * C'est aussi ici que le run dit **de quoi il était le run** — le modèle et
 * l'empreinte de son prompt —, faute d'avoir pu le dire avant de connaître son
 * étage. Ces deux champs entrent par `counters`, comme les compteurs.
 */
evalRouter.post('/runs/:id(\\d+)/finish', async (req, res) => {
  const parsed = evalRunFinishSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { status, error, ...counters } = parsed.data;
  const id = Number(req.params.id);
  const avant = await prisma.evalRun.findUnique({ where: { id }, select: { status: true } });
  if (!avant) {
    res.status(404).json({ error: 'Exécution introuvable' });
    return;
  }
  // Un run que le site a déjà repris ne redevient pas « terminé ».
  //
  // Le worker qui revient après une reprise a cessé au premier `next-item`
  // refusé, donc il clôt sur ce qu'il avait fait — et il le déclare DONE, parce
  // que de son point de vue la file d'entrées était vide. L'accepter
  // présenterait une mesure tronquée comme complète, et ce point-là entrerait
  // dans la courbe sans rien pour le distinguer.
  //
  // Ses compteurs, eux, sont bons à prendre : les jetons ont été consommés et
  // l'argent dépensé, que la mesure aille au bout ou non.
  const repris = avant.status !== 'RUNNING';
  const run = await prisma.evalRun.update({
    where: { id },
    data: repris
      ? { ...counters, finishedAt: new Date() }
      : { ...counters, status, error: error ?? null, finishedAt: new Date() },
  });
  res.json({ run, repris });
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
 * encore leur étiquette.
 *
 * C'est le groupe 3 du corpus — ce qu'une sortie **est**, champ par champ — et
 * c'est la seule partie du banc qui se remplisse sans travail humain : le
 * travail a déjà eu lieu, en modération, fiche sous les yeux.
 */
/**
 * Ce qu'il faut lire d'une fiche approuvée pour en tirer une étiquette.
 *
 * Déclarée une fois, et utilisée par les deux chemins qui moissonnent la
 * modération — « Étiqueter les sorties publiées », et la reprise des étiquettes
 * de lien. Deux sélections parallèles auraient fini par diverger d'un champ,
 * et l'étiquette obtenue aurait alors dépendu du bouton par lequel on est
 * passé.
 */
const FICHE_APPROUVEE = {
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
  venue: { select: { name: true, address: true, postalCode: true, city: true } },
  /// Les jours de représentation que le site a retenus. Les `weekdays` de la
  /// prose, eux, ne lui sont jamais parvenus.
  dates: { select: { day: true } },
  // Ce qu'un modérateur a réécrit avant d'approuver. Ça ne change pas la
  // valeur — elle est déjà dans la fiche publiée — mais ça dit d'où elle
  // vient, et c'est ce qui garde l'hypothèse vérifiable.
  corrections: { select: { field: true } },
} as const;

type FicheApprouvee = Prisma.EventGetPayload<{ select: typeof FICHE_APPROUVEE }>;

/**
 * L'étiquette que porte une fiche approuvée.
 *
 * Une copie de champs, pas une mise en forme : l'étiquette a exactement la
 * forme que la brique rend, donc rien à faire concorder entre deux langages.
 * `weekdays` reste absent — le site ne les reçoit pas, le pipeline s'en sert
 * pour fabriquer les dates et les jette —, et une clé absente veut dire
 * « personne n'a regardé », ce qui est la vérité.
 */
function etiquetteDeFiche(e: FicheApprouvee): { expected: string; origins: string } {
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
  return {
    expected: JSON.stringify(attendue),
    origins: JSON.stringify(provenances(attendue, corriges)),
  };
}

async function sortiesAEtiqueter(limit: number) {
  return prisma.evalSortie.findMany({
    // Jamais étiquetée : l'étiquette est le JSON vide. Pas de jointure à faire,
    // il n'y a plus qu'un objet.
    where: { eventId: { not: null }, expected: '{}' },
    select: {
      id: true,
      // L'adresse sert au rattachement des liens qui annoncent cette sortie.
      url: true,
      event: { select: FICHE_APPROUVEE },
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
  // `eventId` remonte avec le reste : c'est lui qui permet de **décrire** la
  // sortie au passage, et non seulement de la nommer. Sans lui, on reposait une
  // étiquette de lien qui comptait *indécidable* faute d'avoir de quoi la
  // comparer — l'étiquette la moins utile qu'on puisse poser.
  return prisma.$queryRaw<
    { pageId: number; url: string; title: string | null; eventId: number }[]
  >`
    SELECT p.id AS pageId, i.url AS url, MAX(i.title) AS title, MAX(e.id) AS eventId
    FROM ScraperRunItem i
    JOIN Event e ON e.id = i.eventId AND e.status = 'APPROVED'
    JOIN EvalLinkResult r ON r.url = i.url
    JOIN EvalAgendaPage p ON p.id = r.pageId
    LEFT JOIN EvalLink l ON l.pageId = p.id AND l.url = i.url
    WHERE l.id IS NULL
    GROUP BY p.id, i.url
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
/**
 * Ce que chaque étage cherche à savoir, et dans quels champs il le lit.
 *
 * Servi plutôt que recopié dans la console : c'est la liste même que les
 * compteurs appliquent. Deux compteurs écrits à la main ont déjà menti, dont
 * un qui annonçait « 6/6 » sur six champs choisis arbitrairement quand l'étage
 * en juge douze.
 */
/**
 * La recherche que le formulaire propose par défaut.
 *
 * Servie plutôt qu'écrite dans la console : c'est la configuration du banc, et
 * elle doit être la même pour tous ceux qui lancent un run — sinon deux
 * personnes mesureraient sous deux fenêtres sans s'en apercevoir.
 *
 * La fenêtre part d'aujourd'hui, mais elle est **figée en dates absolues** dès
 * que le run est lancé : c'est ce qui rend un run rejouable à l'identique.
 */
evalRouter.get('/recherche', admin, (_req, res) => {
  const aujourdhui = new Date();
  const dans = (jours: number) =>
    new Date(aujourdhui.getTime() + jours * 86400000).toISOString().slice(0, 10);
  res.json({
    recherche: {
      dateFrom: dans(0),
      dateTo: dans(30),
      postalPrefixes: ['75', '77', '78', '91', '92', '93', '94', '95'],
      maxLinks: 8,
      theme: 'sorties enfants',
    },
  });
});

evalRouter.get('/criteres', admin, (_req, res) => {
  res.json({ etages: criteresParEtage() });
});

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
      where: { verdict: 'SORTIE' },
      select: {
        id: true,
        url: true,
        text: true,
        sortieId: true,
        // Qui a posé l'étiquette : `HUMAIN` — quelqu'un a cliqué « une sortie »
        // dans la console ; `MODERATION` — le bouton « Liens d'agenda déjà
        // tranchés » l'a reprise d'une sortie approuvée. Sans ça, la liste
        // compte une dette sans dire d'où elle vient.
        origin: true,
        sortie: { select: { expected: true, audience: true } },
        page: { select: { id: true, pageNo: true, agenda: { select: { id: true, label: true } } } },
      },
      orderBy: { id: 'asc' },
    }),
  ]);

  // Deux dettes, et elles ne se soldent pas du même geste : ou bien la sortie
  // n'existe pas au corpus — il faut la créer —, ou bien elle existe et
  // n'affirme rien — il faut la décrire. Les mêler sous un seul compte obligeait
  // à ouvrir chaque ligne pour savoir laquelle des deux on avait sous les yeux.
  //
  // Le tri se fait ici et non en SQL : les faits vivent dans l'étiquette, et
  // fouiller du JSON en base coûterait une requête illisible et sans index pour
  // un filtre que le serveur fait en mémoire sans effort. À revoir si le corpus
  // dépasse quelques dizaines de milliers de sorties.
  //
  // Le test de « muette », lui, vient de la **mesure** et n'est pas réécrit ici.
  // Il l'a été, et les deux listes de champs avaient déjà divergé : celle-ci
  // testait `!ageMax`, donc rangeait « jusqu'à 0 an » parmi les sorties qui ne
  // disent rien, quand la mesure en déduisait « enfants » et tranchait. Une
  // dette comptée sur d'autres champs que le taux n'annonce pas le travail qui
  // ferait bouger le taux.
  const muette = (lien: (typeof sansSortie)[number]) => {
    if (!lien.sortie) return false;
    return sortieMuette(labelled({ url: lien.url, verdict: 'SORTIE', sortie: lien.sortie }).sortie!);
  };
  const nu = ({ sortie: _sortie, ...reste }: (typeof sansSortie)[number]) => reste;

  const aCreer = sansSortie.filter((l) => !l.sortieId).slice(0, 200).map(nu);
  const aDecrire = sansSortie.filter(muette).slice(0, 200).map(nu);

  res.json({
    /** Par page d'agenda : combien de liens relevés que personne n'a tranchés. */
    jamaisRegardes: jamaisRegardes.map((row) => ({
      pageId: row.pageId,
      url: row.url,
      label: row.label,
      manquants: Number(row.manquants),
    })),
    /** Le lien dit « une sortie », mais aucune sortie n'existe au corpus. */
    aCreer,
    /** La sortie existe, mais son étiquette n'affirme rien que l'étage 4 lise. */
    aDecrire,
  });
});

evalRouter.get('/seed', admin, async (_req, res) => {
  const [approuvees, abandonnees, illisibles, liens, fiches] = await Promise.all([
    candidates('approuvees', 100),
    candidates('abandonnees', 100),
    candidates('illisibles', 100),
    linkLabelCandidates(100),
    sortiesAEtiqueter(100),
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

    // ── les trois gestes, et pourquoi ils n'en font plus qu'un ──────────
    //
    // Ce panier posait l'étiquette de lien et s'arrêtait là. Si la sortie
    // n'était pas déjà au corpus, le lien restait sans rien au bout : l'étage 4
    // le comptait *indécidable*, et il fallait deviner qu'il fallait ensuite
    // cliquer « Sorties publiées » puis « Étiqueter les sorties publiées », dans
    // cet ordre, pour que l'étiquette serve à quelque chose. Trois boutons, un
    // ordre à connaître, et aucun rattrapage si on se trompait.
    //
    // Or les trois gestes reposent sur **le même fait** : un modérateur a
    // approuvé cette page. Il dit à la fois que le lien mène à une sortie, que
    // cette sortie mérite d'être au corpus, et ce qu'elle affirme. Les séparer
    // était un découpage d'implémentation, pas une distinction réelle.
    const events = await prisma.event.findMany({
      where: { id: { in: rows.map((row) => row.eventId) } },
      select: { id: true, ...FICHE_APPROUVEE },
    });
    const fiches = new Map(events.map((e) => [e.id, e]));

    const dejaLa = await prisma.evalSortie.findMany({
      where: { url: { in: rows.map((r) => r.url) } },
      select: { id: true, url: true, expected: true },
    });
    const parUrl = new Map(dejaLa.map((sortie) => [sortie.url, sortie.id]));
    // Celles qui sont là mais que personne n'a décrites. Les laisser vides
    // aurait rattaché le lien à un objet muet — l'étage 4 l'aurait compté
    // indécidable, ce qui est précisément l'état qu'on vient supprimer.
    const muettes = new Map(dejaLa.filter((s) => s.expected === '{}').map((s) => [s.url, s.id]));

    // La sortie manquante est créée **avec son étiquette**, pas vide : la
    // remplir demandait sinon un second bouton, et une sortie au corpus qui
    // n'affirme rien ne sert à aucun étage.
    //
    // Elle part aussi en file de capture, comme toute sortie du corpus. C'est
    // assumé : la page d'une sortie approuvée est une entrée légitime des
    // étages 5 et 6, et c'est très exactement ce que fait déjà le panier
    // « Sorties publiées ». Le plafond du panier borne ce que ça coûte.
    let creees = 0;
    let decrites = 0;
    for (const row of rows) {
      const fiche = fiches.get(row.eventId);
      if (!fiche) continue;
      const { id: _id, ...champs } = fiche;
      const etiquette = {
        ...etiquetteDeFiche(champs),
        note: 'Reprise d’une fiche approuvée en modération.',
        labelledAt: new Date(),
        labelledById: req.user!.id,
      };

      const muette = muettes.get(row.url);
      if (muette !== undefined) {
        await prisma.evalSortie.update({
          where: { id: muette },
          data: { ...etiquette, eventId: row.eventId, audience: 'ENFANTS' },
        });
        muettes.delete(row.url);
        decrites += 1;
        continue;
      }
      if (parUrl.has(row.url)) continue;

      // `upsert` plutôt que `create` : deux pages d'agenda peuvent annoncer la
      // même sortie, et une adresse déjà prise ne doit pas faire échouer tout
      // le panier.
      const sortie = await prisma.evalSortie.upsert({
        where: { url: row.url },
        create: {
          url: row.url,
          label: (row.title ?? '').slice(0, 150),
          origin: 'APPROUVEE',
          eventId: row.eventId,
          // Le public : la seule affirmation qu'aucune brique ne rend, et
          // qu'approuver sur ce site tranche à lui seul.
          audience: 'ENFANTS',
          ...etiquette,
          createdById: req.user!.id,
        },
        update: {},
        select: { id: true, url: true },
      });
      parUrl.set(sortie.url, sortie.id);
      creees += 1;
    }

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
    // Et les liens que ce panier avait déjà posés lors d'un passage précédent,
    // quand la sortie n'était pas encore au corpus : `skipDuplicates` les
    // laisse intacts, orphelins compris. Un second clic ne doit pas être sans
    // effet sur eux.
    const rattaches = await rattacherLiens(rows.map((row) => row.url));
    res.status(201).json({ added: created.count, creees, decrites, rattaches });
    return;
  }

  if (bucket === 'fiches') {
    const sorties = await sortiesAEtiqueter(limit);
    if (!sorties.length) {
      res.status(409).json({ error: 'Aucune fiche approuvée à reprendre' });
      return;
    }
    let added = 0;
    for (const sortie of sorties) {
      const e = sortie.event;
      if (!e) continue;
      await prisma.evalSortie.update({
        where: { id: sortie.id },
        data: {
          ...etiquetteDeFiche(e),
          note: 'Reprise d’une fiche approuvée en modération.',
          labelledAt: new Date(),
          labelledById: req.user!.id,
        },
      });
      added += 1;
    }
    // Ce bouton est celui qu'on presse en découvrant qu'un étage 4 ne mesure
    // rien : qu'il répare aussi le rattachement évite d'avoir à deviner lequel
    // des deux manquait.
    const rattaches = await rattacherLiens(sorties.map((sortie) => sortie.url));
    res.status(201).json({ added, rattaches });
    return;
  }

  const rows = (await candidates(bucket, limit)).slice(0, limit);
  if (!rows.length) {
    res.status(409).json({ error: 'Rien de nouveau dans ce panier' });
    return;
  }
  // Le type de retour est **annoté**, et ce n'est pas du zèle : sans lui, le
  // résultat d'un `map` échappe au contrôle des propriétés en trop, et une
  // colonne supprimée depuis se laisse écrire sans que rien ne bronche jusqu'à
  // l'erreur 500 en production. C'est exactement ce qui est arrivé ici.
  const created = await prisma.evalSortie.createMany({
    data: rows.map(
      (row): Prisma.EvalSortieCreateManyInput => ({
        url: row.url,
        label: (row.title ?? '').slice(0, 150),
        origin: BUCKETS[bucket].origin,
        eventId: bucket === 'approuvees' ? row.eventId : null,
        readAt: row.at,
        runDecision: row.decision.slice(0, 40),
        runReason: row.reason ?? '',
        createdById: req.user!.id,
        // Ce que la sortie **est** n'entre pas ici : ça appartient à son
        // étiquette, que « Étiqueter les sorties publiées » remplit ensuite
        // depuis la fiche approuvée. Une sortie créée ici arrive donc sans rien
        // d'affirmé, ce que le corpus sait dire — `expected` vaut `{}`.
        //
        // Sauf le public : la seule affirmation qu'aucune brique ne rend, et
        // qu'approuver sur ce site tranche à lui seul.
        audience: BUCKETS[bucket].origin === 'APPROUVEE' ? ('ENFANTS' as const) : null,
      }),
    ),
    skipDuplicates: true,
  });
  // Le même rattachement, et c'est ici qu'il manquait le plus : ce panier crée
  // des sorties en masse, souvent **après** que « Liens d'agenda déjà tranchés »
  // a posé les étiquettes de lien. Sans lui, l'ordre des deux clics décidait si
  // l'étage 4 mesurait quelque chose.
  const rattaches = await rattacherLiens(rows.map((row) => row.url));
  res.status(201).json({ added: created.count, rattaches });
});
