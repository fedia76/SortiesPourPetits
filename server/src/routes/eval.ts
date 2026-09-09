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
  evalBulkVerdictSchema,
  evalExtractSchema,
  evalExtractionSchema,
  evalFieldVerdictSchema,
  evalLinkSchema,
  evalNextSchema,
  evalReadSchema,
  evalReadingSchema,
  evalReadingVerdictSchema,
  evalSeedSchema,
  evalVerdictSchema,
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
    include: { links: { orderBy: [{ position: 'asc' }, { id: 'asc' }] } },
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

type SerializableLink = {
  url: string;
  harvested: boolean;
  verdict: string | null;
  reviewed: boolean;
};
type SerializablePage = {
  htmlPath: string | null;
  nextUrl: string;
  nextVerdict: string | null;
  error: string | null;
  links: SerializableLink[];
};
type SerializableAgenda = { status: string; pages: number; agendaPages: SerializablePage[] };

/**
 * Ce que le dépouillement a fait de cet agenda, une fois l'humain passé.
 *
 * Le croisement de deux colonnes donne les **deux** erreurs, là où ne montrer
 * que la moisson n'en donnait qu'une :
 *
 * |              | l'humain dit SORTIE | l'humain dit autre chose |
 * |--------------|---------------------|--------------------------|
 * | **retenu**   | juste               | retenu pour rien         |
 * | **écarté**   | **sortie perdue**   | juste                    |
 *
 * « Retenu pour rien » coûte un appel payant à l'étage 4. « Sortie perdue » ne
 * coûte rien du tout et ne se voit nulle part — c'est la plus chère des deux.
 *
 * ## Pourquoi deux précisions
 *
 * Compter tout ce qui n'est pas une sortie comme une faute du dépouillement
 * accuse la mauvaise brique. Un **sous-agenda** retenu mène bien quelque part —
 * vers d'autres sorties — et c'est l'étage 4 qui le jette, parce qu'on lui dit
 * d'écarter les catégories. Une **pagination** retenue mène à la suite de la
 * liste. Ni l'un ni l'autre n'est du bruit.
 *
 * D'où deux chiffres qui répondent à deux questions :
 *
 * * `precision` — de ce que la brique donne à l'étage 4, quelle part est une
 *   sortie. C'est la mesure du couple 3+4, et celle qui dit ce qu'on paie.
 * * `precisionUseful` — quelle part mène quelque part de réel, bruit exclu.
 *   C'est la mesure de l'étage 3 seul, celle qui dit s'il sait reconnaître un
 *   lien qui compte.
 *
 * ## Pourquoi la couverture compte autant que les taux
 *
 * `reviewed` dit combien de liens un humain a réellement tranchés. Sans lui,
 * les taux mentent : le dénominateur du rappel — les liens appelés « sortie » —
 * ne peut pas être juste si une partie des liens n'a jamais été lue. Un agenda
 * dont on n'a relu que la moisson affichait 100 % de rappel, non pas parce que
 * la brique n'avait rien raté, mais parce que personne n'avait regardé le
 * reste.
 *
 * ## Parcourir les pages fait partie du travail, donc en rater est une erreur
 *
 * L'étage 3 ne se contente pas de lire une page : il suit la pagination. Un
 * agenda pour lequel on demande deux pages et dont une seule est lue est donc
 * un **ratage**, au même titre qu'une sortie perdue — et il ne se voyait nulle
 * part : la deuxième page n'existait simplement pas dans l'arbre, sans un mot.
 *
 * `pagesRead` contre `pagesAsked` le dit tout de suite, sans attendre l'humain,
 * et `stop` dit pourquoi la moisson s'est arrêtée. Une fois la page relue,
 * `paginationManquee` le confirme : des liens que l'humain appelle
 * « pagination » sur une page où `next_page()` n'a rien trouvé, c'est une suite
 * que le site offrait et que la brique n'a pas su voir.
 */
function statsOf(agenda: SerializableAgenda) {
  let kept = 0;
  let sorties = 0;
  let keptRight = 0;
  let keptUseful = 0;
  let sousAgendas = 0;
  let paginationVue = 0;
  let pagesJugees = 0;
  let paginationManquee = 0;
  let paginationFausse = 0;
  let links = 0;
  let reviewed = 0;

  for (const page of agenda.agendaPages) {
    paginationVue += page.links.filter((l) => l.verdict === 'PAGINATION').length;
    // Le verdict vient de l'humain, pas d'une déduction sur les étiquettes des
    // liens : l'URL que `next_page()` a trouvée n'est pas toujours un lien de
    // la page — elle peut venir du `<link rel="next">` du `<head>` — et n'était
    // alors étiquetable par personne.
    if (page.nextVerdict) pagesJugees += 1;
    if (page.nextVerdict === 'MANQUEE') paginationManquee += 1;
    if (page.nextVerdict === 'FAUSSE') paginationFausse += 1;
    for (const link of page.links) {
      links += 1;
      if (link.reviewed) reviewed += 1;
      if (link.harvested) {
        kept += 1;
        // « Mène quelque part » : une sortie, la suite de la liste, ou une
        // autre liste. Tout sauf du bruit.
        if (link.verdict !== 'AUTRE') keptUseful += 1;
      }
      if (link.verdict === 'SORTIE') {
        sorties += 1;
        if (link.harvested) keptRight += 1;
      }
      if (link.verdict === 'SOUS_AGENDA') sousAgendas += 1;
    }
  }

  // ── la pagination, responsabilité de l'étage 3 comme une autre
  const pagesAsked = agenda.pages;
  const pagesRead = agenda.agendaPages.length;
  const last = agenda.agendaPages[pagesRead - 1];
  // Pourquoi la moisson s'est arrêtée avant le compte demandé. Dérivé de ce
  // qu'on garde déjà : une dernière page en erreur s'est vue refuser l'entrée,
  // une dernière page sans `rel="next"` n'a pas su désigner la suivante, et
  // sinon c'est que la suivante avait déjà été lue — un agenda qui boucle.
  let stop = '';
  if (pagesRead < pagesAsked && last) {
    if (last.error) stop = 'injoignable';
    else if (!last.nextUrl) stop = 'sans_suite';
    else stop = 'boucle';
  }

  // Les taux n'ont de sens qu'une fois l'humain passé — et passé **partout** :
  // la validation exige que tout soit relu, et c'est elle qui les débloque.
  const juge = agenda.status === 'VALIDATED';
  return {
    links,
    reviewed,
    pagesAsked,
    pagesRead,
    /** '' quand tout a été lu ; sinon injoignable, sans_suite ou boucle. */
    stop,
    kept,
    sorties,
    /** Retenus à tort : ils ont coûté un appel à l'étage 4 pour rien. */
    keptWrong: kept - keptRight,
    /** Sorties perdues : personne ne les aurait jamais vues. */
    missed: sorties - keptRight,
    sousAgendas,
    paginationVue,
    /** Pages dont la pagination a été tranchée par un humain. */
    pagesJugees,
    /** Il y avait une suite, la brique ne l'a pas vue. */
    paginationManquee,
    /** La brique a couru après une page qui n'était pas la suite. */
    paginationFausse,
    precision: juge && kept > 0 ? keptRight / kept : null,
    precisionUseful: juge && kept > 0 ? keptUseful / kept : null,
    recall: juge && sorties > 0 ? keptRight / sorties : null,
  };
}

function serialize<T extends SerializableAgenda>(agenda: T) {
  return {
    ...agenda,
    agendaPages: agenda.agendaPages.map(({ htmlPath, ...page }) => ({
      ...page,
      archived: !!htmlPath,
    })),
    stats: statsOf(agenda),
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
        duplicate.source === 'PAGE'
          ? 'Ce lien est déjà relevé sur la page : donnez-lui son verdict.'
          : 'Ce lien a déjà été ajouté',
    });
    return;
  }
  await prisma.evalLink.create({
    data: {
      ...parsed.data,
      pageId,
      source: 'MANUAL',
      harvested: false,
      position: 10_000,
      reviewed: true,
      reviewedAt: new Date(),
    },
  });
  // Un ajout après validation rouvre l'agenda : la vérité a changé, et le
  // chiffre qu'on en tirait ne vaut plus pour ce qu'elle contient maintenant.
  const agenda = await prisma.evalAgenda.update({
    where: { id: page.agendaId },
    data: { status: 'ANALYZED', validatedAt: null },
    include: AGENDA_INCLUDE,
  });
  res.status(201).json({ agenda: serialize(agenda) });
});

/**
 * Corrige le verdict d'un lien. **C'est la mesure**, et tout le reste de cette
 * console est la mise en scène autour de ce geste.
 *
 * La brique a précoché ; l'humain confirme ou corrige. Un lien retenu qu'il
 * fait passer en `AUTRE` est un appel payant dépensé pour rien ; un lien
 * écarté qu'il fait passer en `SORTIE` est une sortie que personne n'aurait
 * jamais vue.
 *
 * Rien n'est refusé ici, pas même de contredire la brique sur un lien qu'elle
 * a retenu : c'est précisément le but.
 */
evalRouter.patch('/links/:id(\\d+)', admin, async (req, res) => {
  const parsed = evalVerdictSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const link = await prisma.evalLink.findUnique({
    where: { id: Number(req.params.id) },
    select: { id: true, page: { select: { agendaId: true } } },
  });
  if (!link) {
    res.status(404).json({ error: 'Lien introuvable' });
    return;
  }
  // `reviewed` est ce qui sépare « la machine a deviné » de « un humain a
  // tranché ». C'est ce clic-ci qui le pose, et c'est lui qui rend les taux
  // lisibles plus tard.
  await prisma.evalLink.update({
    where: { id: link.id },
    data: { ...parsed.data, reviewed: true, reviewedAt: new Date() },
  });
  // Corriger après validation rouvre l'agenda : la vérité a changé, et les
  // taux qu'on en tirait ne valent plus pour ce qu'elle contient maintenant.
  const agenda = await prisma.evalAgenda.update({
    where: { id: link.page.agendaId },
    data: { status: 'ANALYZED', validatedAt: null },
    include: AGENDA_INCLUDE,
  });
  res.json({ agenda: serialize(agenda) });
});

/**
 * Tranche la pagination d'une page. **L'autre moitié de la mesure de l'étage 3.**
 *
 * Suivre les pages fait partie de son travail, et ce verdict-là ne se déduit
 * pas des étiquettes des liens : `next_page()` lit aussi le `<link rel="next">`
 * du `<head>`, qui n'est pas un `<a href>`. L'URL qu'il en tire n'apparaît alors
 * dans aucune ligne — la console demandait de l'étiqueter « pagination » sans
 * qu'aucune ligne ne puisse l'être.
 *
 * Trois valeurs, parce que savoir que la brique s'est trompée ne dit pas
 * comment : rater une suite et courir après une fausse ne se réparent pas
 * pareil.
 */
evalRouter.patch('/pages/:id(\\d+)/next', admin, async (req, res) => {
  const parsed = evalNextSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const pageId = Number(req.params.id);
  const page = await prisma.evalAgendaPage.findUnique({
    where: { id: pageId },
    select: { agendaId: true },
  });
  if (!page) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  await prisma.evalAgendaPage.update({
    where: { id: pageId },
    // L'adresse attendue ne se garde que lorsqu'elle apprend quelque chose :
    // sur un verdict « correct », la brique a déjà trouvé la bonne.
    data: {
      nextVerdict: parsed.data.verdict,
      nextExpected: parsed.data.verdict === 'CORRECT' ? '' : parsed.data.expected,
    },
  });
  const agenda = await prisma.evalAgenda.update({
    where: { id: page.agendaId },
    data: { status: 'ANALYZED', validatedAt: null },
    include: AGENDA_INCLUDE,
  });
  res.json({ agenda: serialize(agenda) });
});

/**
 * Donne le même verdict à tous les liens **écartés** d'une page, ou d'un seul
 * motif de rejet.
 *
 * Soixante-seize écartés se lisent mal un par un, et la plupart sont du bruit
 * évident : quinze liens vers un réseau social, douze vers la racine du site.
 * Les expédier d'un clic laisse le temps là où il compte — sous « texte trop
 * court », le motif où se cachent les sorties perdues.
 *
 * L'opération ne touche **jamais** les liens retenus. Ceux-là sont peu nombreux
 * et sont l'objet même de la relecture : les trancher en masse reviendrait à
 * approuver la brique sans la lire, c'est-à-dire à ne rien mesurer.
 */
evalRouter.post('/pages/:id(\\d+)/verdict', admin, async (req, res) => {
  const parsed = evalBulkVerdictSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const pageId = Number(req.params.id);
  const page = await prisma.evalAgendaPage.findUnique({
    where: { id: pageId },
    select: { agendaId: true },
  });
  if (!page) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  const { count } = await prisma.evalLink.updateMany({
    where: {
      pageId,
      harvested: false,
      ...(parsed.data.reason ? { dropReason: parsed.data.reason } : {}),
    },
    data: { verdict: parsed.data.verdict, reviewed: true, reviewedAt: new Date() },
  });
  const agenda = await prisma.evalAgenda.update({
    where: { id: page.agendaId },
    data: { status: 'ANALYZED', validatedAt: null },
    include: AGENDA_INCLUDE,
  });
  res.json({ agenda: serialize(agenda), count });
});

/**
 * Retire un lien ajouté à la main. Un lien relevé sur la page, lui, ne s'efface
 * pas : il **est** sur la page, et le faire disparaître falsifierait le
 * dénominateur. Pour dire qu'il ne mène nulle part, il y a le verdict `AUTRE`.
 */
evalRouter.delete('/links/:id(\\d+)', admin, async (req, res) => {
  const link = await prisma.evalLink.findUnique({
    where: { id: Number(req.params.id) },
    select: { id: true, source: true, page: { select: { agendaId: true } } },
  });
  if (!link) {
    res.status(404).json({ error: 'Lien introuvable' });
    return;
  }
  if (link.source === 'PAGE') {
    res.status(409).json({
      error:
        "Ce lien est sur la page : l'effacer falsifierait la mesure. " +
        'Donnez-lui plutôt le verdict « autre ».',
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
    select: { status: true },
  });
  if (!current) {
    res.status(404).json({ error: 'Agenda introuvable' });
    return;
  }
  if (current.status !== 'ANALYZED') {
    res.status(409).json({ error: 'Seule une analyse terminée se valide' });
    return;
  }
  // Tout doit avoir été relu, et ce n'est pas de la rigidité : le dénominateur
  // du rappel — les liens qu'un humain appelle « sortie » — ne peut pas être
  // juste si une partie des liens n'a jamais été lue. Valider en n'ayant relu
  // que la moisson produisait un rappel de 100 % qui ne disait rien.
  const reste = await prisma.evalLink.count({
    where: { page: { agendaId: id }, reviewed: false },
  });
  const pagesSansVerdict = await prisma.evalAgendaPage.count({
    where: { agendaId: id, nextVerdict: null },
  });
  if (pagesSansVerdict > 0) {
    res.status(409).json({
      error:
        `${pagesSansVerdict} page(s) n'ont pas de verdict de pagination. Suivre les ` +
        "pages fait partie du travail de l'étage 3 : dites, pour chacune, si ce " +
        "qu'il a trouvé — ou n'a pas trouvé — est juste.",
    });
    return;
  }
  if (reste > 0) {
    res.status(409).json({
      error:
        `${reste} lien(s) n'ont pas encore été tranchés par un humain — ils portent ` +
        'encore la précoche de la brique. Valider maintenant donnerait des taux qui ' +
        "ne diraient que « personne n'a regardé ». Le filtre « À revoir » les liste, et " +
        "l'action de groupe permet d'en expédier un motif entier.",
    });
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
          nextUrl: page.nextUrl,
          htmlPath: archived[index] || null,
          links: {
            create: links.map((l, position) => ({
              url: l.url,
              text: l.text,
              context: l.context,
              harvested: l.harvested,
              dropReason: l.reason,
              position,
              source: 'PAGE' as const,
              // **La précoche.** Ce que la brique a décidé devient la
              // proposition faite à l'humain : retenu, donc probablement une
              // sortie ; écarté, donc probablement du bruit. Il n'a plus qu'à
              // corriger ce qui est faux — et ce sont ces corrections-là qui
              // sont la mesure.
              verdict: l.harvested ? ('SORTIE' as const) : ('AUTRE' as const),
            })),
          },
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

// ═══════════════════════════════════════════ étage 5 — le banc de lecture

/**
 * La sortie approuvée, telle que le banc s'en sert.
 *
 * Approuver, sur ce site, veut dire qu'un modérateur a vérifié **chaque champ**.
 * Ce n'est donc pas une précoche de plus : c'est une étiquette humaine déjà
 * payée, et elle donne le verdict de l'étage 6 gratuitement — y compris sur
 * `setting`, le seul aspect qu'aucun instrument ne sait atteindre.
 */
const EVENT_REFERENCE_SELECT = {
  id: true, title: true, status: true, isFree: true, price: true,
  ageMin: true, ageMax: true, isPermanent: true, dateStart: true, dateEnd: true,
  openTime: true, closeTime: true, setting: true, sourceUrl: true,
  category: { select: { name: true } },
  venue: { select: { name: true, address: true, city: true, postalCode: true } },
  dates: { select: { day: true }, orderBy: { day: 'asc' } },
} satisfies Prisma.EventSelect;

/**
 * L'étage 5 lit trois fois un même HTML : le texte qui part au modèle, les
 * dates que le site déclare, l'illustration. Et il en tire une décision — sous
 * deux cents caractères, la page est **abandonnée** avant le moindre appel
 * payant.
 *
 * ## Trois verdicts plutôt qu'un
 *
 * Parce que les trois lectures se ratent séparément et ne se réparent pas au
 * même endroit. Un texte amputé accuse la liste des balises décapées ; un texte
 * tronqué accuse le plafond de caractères ; une illustration qui est le logo du
 * site accuse le tamis des images. Un verdict unique les mélangerait et ne
 * pointerait rien.
 *
 * ## Rien n'est précoché en base
 *
 * À l'étage 3 il fallait précocher : cent trente-neuf liens ne se tranchent pas
 * un par un, et il fallait distinguer ensuite ce qu'un humain avait dit de ce
 * que la machine avait deviné. Ici il y a **trois** clics par page : la console
 * met en avant ce que la brique prétend, mais rien de cette proposition n'est
 * écrit. Un verdict nul veut dire « personne n'a encore regardé », sans
 * ambiguïté et sans colonne de plus.
 */
const READING_SELECT = {
  id: true, url: true, label: true, status: true, error: true, note: true,
  readUrl: true, swapped: true, text: true, textChars: true, dates: true,
  imageUrl: true, chars: true, htmlPath: true,
  heading: true, h1InText: true, truncated: true, tooShort: true, imageLooksLogo: true,
  textVerdict: true, imageVerdict: true, datesVerdict: true,
  origin: true, readAt: true, runDecision: true, runReason: true,
  createdAt: true, analyzedAt: true, validatedAt: true,
  author: { select: { id: true, displayName: true } },
  // La sortie approuvée tirée de cette page. En **contexte** pour l'étage 5, et
  // pas en verdict : les trois verdicts de cet étage portent sur ce que la page
  // *contient*, la fiche dit ce que la sortie *est*. Confondre les deux
  // fabriquerait des taux qui ne mesurent pas ce qu'ils annoncent.
  //
  // C'est en revanche la vérité de référence de l'étage 6, où la question est
  // exactement « ces champs sont-ils les bons ? ».
  event: { select: EVENT_REFERENCE_SELECT },
} satisfies Prisma.EvalReadingSelect;

type ReferenceRow = {
  id: number;
  title: string;
  isFree: boolean;
  price: Prisma.Decimal | null;
  ageMin: number | null;
  ageMax: number | null;
  isPermanent: boolean;
  dateStart: Date | null;
  dateEnd: Date | null;
  openTime: string | null;
  closeTime: string | null;
  setting: string | null;
  sourceUrl: string | null;
  category: { name: string };
  venue: { name: string; address: string; city: string; postalCode: string };
  dates: { day: Date }[];
};

/** Un jour, en ISO, sans l'heure : les dates du site sont des `DATE`. */
function isoDay(value: Date | null): string {
  return value ? value.toISOString().slice(0, 10) : '';
}

/**
 * La fiche approuvée mise à plat, dans le vocabulaire que le worker attend.
 *
 * Les mêmes clés que `evaluation.fiche_payload`, pour que la comparaison se
 * fasse champ contre champ sans traduction au milieu — une traduction de plus
 * serait un endroit de plus où deux vocabulaires peuvent diverger.
 */
function flattenReference(event: ReferenceRow) {
  return {
    id: event.id,
    title: event.title,
    isFree: event.isFree,
    price: event.price === null ? null : Number(event.price),
    ageMin: event.ageMin,
    ageMax: event.ageMax,
    isPermanent: event.isPermanent,
    dateStart: isoDay(event.dateStart),
    dateEnd: isoDay(event.dateEnd),
    openTime: event.openTime ?? '',
    closeTime: event.closeTime ?? '',
    setting: event.setting ?? '',
    sourceUrl: event.sourceUrl ?? '',
    category: event.category.name,
    venueName: event.venue.name,
    venueAddress: event.venue.address,
    venueCity: event.venue.city,
    venuePostalCode: event.venue.postalCode,
    days: event.dates.map((d) => isoDay(d.day)),
  };
}

type SerializableReading = {
  status: string;
  htmlPath: string | null;
  dates: string;
  textVerdict: string | null;
  imageVerdict: string | null;
  datesVerdict: string | null;
  event: (ReferenceRow & { status: string }) | null;
};

function serializeReading<T extends SerializableReading>(reading: T) {
  const { htmlPath, dates, event, ...rest } = reading;
  let parsed: string[] = [];
  try {
    // Écrit par le serveur lui-même à l'import, donc bien formé — mais une
    // ligne d'un import raté ne doit pas faire échouer toute la console.
    parsed = JSON.parse(dates);
  } catch {
    parsed = [];
  }
  const judged =
    !!reading.textVerdict && !!reading.imageVerdict && !!reading.datesVerdict;
  return {
    ...rest,
    dates: Array.isArray(parsed) ? parsed : [],
    archived: !!htmlPath,
    /** Les trois verdicts sont posés : cette page compte dans la mesure. */
    judged,
    /**
     * La sortie approuvée tirée de cette page — du **contexte** ici, la vérité
     * de référence à l'étage 6. Nulle tant qu'elle n'est pas approuvée : une
     * fiche en attente n'a été vérifiée par personne.
     */
    reference: event && event.status === 'APPROVED' ? flattenReference(event) : null,
  };
}

/**
 * Ce que l'étage 5 rend juste, sur l'ensemble du banc.
 *
 * Un taux par aspect, parce que les trois se ratent séparément. Et les motifs
 * comptés à côté, parce que « 60 % de textes corrects » ne dit pas quoi
 * réparer, alors que « douze textes amputés » désigne la liste des balises
 * décapées.
 */
function readingStats(rows: ReturnType<typeof serializeReading>[]) {
  const judged = rows.filter((r) => r.judged);
  const n = judged.length;
  const part = (predicate: (r: (typeof judged)[number]) => boolean) =>
    n > 0 ? judged.filter(predicate).length / n : null;
  const count = (predicate: (r: (typeof rows)[number]) => boolean) =>
    rows.filter(predicate).length;
  return {
    pages: rows.length,
    judged: n,
    textOk: part((r) => r.textVerdict === 'CORRECT'),
    imageOk: part((r) => r.imageVerdict === 'CORRECTE'),
    datesOk: part((r) => r.datesVerdict === 'CORRECTES'),
    /** Le décapage a emporté une partie de la page. */
    ampute: count((r) => r.textVerdict === 'AMPUTE'),
    /** Le plafond de caractères a coupé la fin. */
    tronque: count((r) => r.textVerdict === 'TRONQUE'),
    /** Ce n'est pas la page de la sortie. */
    horsSujet: count((r) => r.textVerdict === 'HORS_SUJET'),
    /**
     * Sous le seuil, donc abandonnée avant tout appel payant — le ratage le
     * plus cher, et le seul que la brique décide toute seule. Compté sur le
     * signal, pas sur un verdict : c'est un fait, pas un jugement.
     */
    abandonnees: count((r) => r.tooShort),
  };
}

evalRouter.get('/readings', admin, async (_req, res) => {
  const rows = await prisma.evalReading.findMany({
    orderBy: { createdAt: 'desc' },
    select: READING_SELECT,
  });
  const readings = rows.map(serializeReading);
  res.json({ readings, stats: readingStats(readings) });
});

evalRouter.post('/readings', admin, async (req, res) => {
  const parsed = evalReadingSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const existing = await prisma.evalReading.findUnique({
    where: { url: parsed.data.url },
    select: { id: true },
  });
  if (existing) {
    res.status(409).json({ error: 'Cette page est déjà au banc' });
    return;
  }
  const reading = await prisma.evalReading.create({
    data: { ...parsed.data, createdById: req.user!.id },
    select: READING_SELECT,
  });
  res.status(201).json({ reading: serializeReading(reading) });
});

/**
 * Relance la lecture. Les verdicts partent avec, et il n'y a pas d'autre choix
 * honnête : ils décrivaient la page telle qu'elle était, et elle va être
 * retéléchargée.
 */
evalRouter.post('/readings/:id(\\d+)/analyze', admin, async (req, res) => {
  const id = Number(req.params.id);
  const current = await prisma.evalReading.findUnique({
    where: { id },
    select: { status: true, htmlPath: true },
  });
  if (!current) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  if (current.status === 'RUNNING') {
    res.status(409).json({ error: 'Lecture déjà en cours' });
    return;
  }
  await deleteEvalPages([current.htmlPath]);
  const reading = await prisma.evalReading.update({
    where: { id },
    data: {
      status: 'QUEUED', error: null, analyzedAt: null, validatedAt: null, htmlPath: null,
      textVerdict: null, imageVerdict: null, datesVerdict: null,
    },
    select: READING_SELECT,
  });
  res.json({ reading: serializeReading(reading) });
});

/** Trancher un aspect, ou plusieurs. **C'est la mesure.** */
evalRouter.patch('/readings/:id(\\d+)', admin, async (req, res) => {
  const parsed = evalReadingVerdictSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const id = Number(req.params.id);
  const current = await prisma.evalReading.findUnique({ where: { id }, select: { id: true } });
  if (!current) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  // Corriger après validation rouvre la page : la vérité a changé.
  const reading = await prisma.evalReading.update({
    where: { id },
    data: { ...parsed.data, status: 'ANALYZED', validatedAt: null },
    select: READING_SELECT,
  });
  res.json({ reading: serializeReading(reading) });
});

evalRouter.post('/readings/:id(\\d+)/validate', admin, async (req, res) => {
  const id = Number(req.params.id);
  const current = await prisma.evalReading.findUnique({
    where: { id },
    select: { status: true, textVerdict: true, imageVerdict: true, datesVerdict: true },
  });
  if (!current) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  if (current.status !== 'ANALYZED') {
    res.status(409).json({ error: 'Seule une lecture terminée se valide' });
    return;
  }
  // Les trois aspects, ou rien. Valider en n'ayant jugé que le texte
  // produirait un taux d'illustration calculé sur des pages que personne n'a
  // regardées — c'est le même mensonge que le rappel à 100 % de l'étage 3.
  if (!current.textVerdict || !current.imageVerdict || !current.datesVerdict) {
    res.status(409).json({
      error:
        "Les trois aspects doivent être tranchés — texte, illustration, dates. " +
        "Valider à moitié donnerait des taux calculés sur des pages que personne n'a regardées.",
    });
    return;
  }
  const reading = await prisma.evalReading.update({
    where: { id },
    data: { status: 'VALIDATED', validatedAt: new Date() },
    select: READING_SELECT,
  });
  res.json({ reading: serializeReading(reading) });
});

evalRouter.delete('/readings/:id(\\d+)', admin, async (req, res) => {
  const id = Number(req.params.id);
  const current = await prisma.evalReading.findUnique({
    where: { id },
    select: { htmlPath: true },
  });
  if (!current) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  await deleteEvalPages([current.htmlPath]);
  await prisma.evalReading.delete({ where: { id } });
  res.json({ ok: true });
});

/** Le HTML gelé de la page lue. */
evalRouter.get('/readings/:id(\\d+)/html', admin, async (req, res) => {
  const row = await prisma.evalReading.findUnique({
    where: { id: Number(req.params.id) },
    select: { htmlPath: true },
  });
  if (!row?.htmlPath) {
    res.status(404).json({ error: "Cette page n'a pas été archivée" });
    return;
  }
  const html = await readEvalPage(row.htmlPath);
  if (html === null) {
    res.status(410).json({ error: "L'archive de cette page a disparu du disque" });
    return;
  }
  res.type('text/plain; charset=utf-8').send(html);
});

// ─────────────────────────────────────────────────────── worker (lecture)

evalRouter.post('/reading/next', async (_req, res) => {
  const queued = await prisma.evalReading.findFirst({
    where: { status: 'QUEUED' },
    orderBy: { createdAt: 'asc' },
    select: { id: true, url: true },
  });
  if (!queued) {
    res.json({ reading: null });
    return;
  }
  const claimed = await prisma.evalReading.updateMany({
    where: { id: queued.id, status: 'QUEUED' },
    data: { status: 'RUNNING' },
  });
  if (claimed.count === 0) {
    res.json({ reading: null });
    return;
  }
  res.json({ reading: queued });
});

evalRouter.post('/reading/:id(\\d+)/result', harvestBody, async (req, res) => {
  const parsed = evalReadSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const id = Number(req.params.id);
  const current = await prisma.evalReading.findUnique({
    where: { id },
    select: { htmlPath: true },
  });
  if (!current) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  const { html, dates, url, error, ...rest } = parsed.data;
  await deleteEvalPages([current.htmlPath]);
  const archived = html ? await saveEvalPage(html) : '';
  const reading = await prisma.evalReading.update({
    where: { id },
    data: {
      ...rest,
      readUrl: url,
      dates: JSON.stringify(dates),
      htmlPath: archived || null,
      // Une page injoignable est une réponse : elle reste au banc avec son
      // motif, plutôt que de disparaître comme si on ne l'avait pas demandée.
      status: error ? 'FAILED' : 'ANALYZED',
      error: error ?? null,
      analyzedAt: new Date(),
      validatedAt: null,
    },
    select: READING_SELECT,
  });
  res.json({ reading: serializeReading(reading) });
});

evalRouter.post('/reading/:id(\\d+)/fail', async (req, res) => {
  const parsed = evalFailSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const updated = await prisma.evalReading.updateMany({
    where: { id: Number(req.params.id) },
    data: { status: 'FAILED', error: parsed.data.error },
  });
  if (updated.count === 0) {
    res.status(404).json({ error: 'Page introuvable' });
    return;
  }
  res.json({ ok: true });
});

// ═══════════════════════════════════ étage 6 — le banc d'extraction

/**
 * L'étage 6 est le premier que le banc mesure et qui **coûte**. Trois choses
 * changent par rapport aux deux précédents, et toutes les trois en découlent.
 *
 * ## 1. Champ par champ, jamais fiche par fiche
 *
 * Une fiche « fausse » ne dit pas quel champ a lâché, donc ne dit pas quoi
 * réparer. Douze aspects jugés séparément disent « le tarif se rate une fois
 * sur trois » — et c'est une ligne de prompt à réécrire.
 *
 * ## 2. Trois instruments gratuits avant le premier clic
 *
 * L'**ancrage** (toute valeur doit se retrouver dans le texte), la **cohérence**
 * interne (un âge minimum au-dessus du maximum), l'**accord** avec les dates
 * JSON-LD que l'étage 5 a relevées. Aucun ne demande d'étiquette humaine, et à
 * eux trois ils désignent la plupart des fautes. Ils sont calculés côté Python,
 * par `evaluation.audit_fiche`, et arrivent tels quels : les recalculer ici
 * donnerait la vérité d'une réimplémentation.
 *
 * Ce ne sont pas des verdicts. Comme les motifs de rejet de l'étage 3 et les
 * signaux de l'étage 5, ce sont des libellés : ils disent **où regarder
 * d'abord**, et c'est beaucoup quand douze aspects sur trente fiches font trois
 * cent soixante décisions dont l'écrasante majorité est « juste ».
 *
 * ## 3. L'entrée est le texte de l'étage 5, jamais la page
 *
 * C'est ce qui fait qu'une fiche fautive accuse bien cet étage-ci. Retélécharger
 * mêlerait deux mesures : une fiche sans tarif dirait aussi bien « le modèle ne
 * l'a pas vu » que « la lecture l'avait déjà emporté avec un `<aside>` ». Le
 * banc de lecture a mesuré cela séparément, et l'a déjà dit.
 */
const EXTRACTION_SELECT = {
  id: true, status: true, error: true, note: true, model: true,
  fiche: true, aspects: true, verdicts: true,
  hasReference: true, pageMoved: true,
  inputTokens: true, outputTokens: true, costUsd: true,
  createdAt: true, analyzedAt: true, validatedAt: true,
  author: { select: { id: true, displayName: true } },
  // Le texte voyage avec la fiche : c'est la pièce à conviction. Juger « ce
  // tarif est-il dans la page ? » sans l'avoir sous les yeux obligerait à
  // rouvrir la vraie page — donc à comparer à un HTML qui a pu changer, ce que
  // le corpus gelé existe précisément pour éviter.
  reading: {
    select: {
      id: true, url: true, label: true, text: true, textChars: true,
      dates: true, heading: true, truncated: true, tooShort: true,
      textVerdict: true, origin: true, readAt: true,
      // De quoi renvoyer vers la fiche publiée : le motif de chaque proposition
      // cite déjà la valeur approuvée, mais un doute se lève en ouvrant la
      // sortie elle-même.
      event: { select: { id: true, title: true, status: true } },
    },
  },
} satisfies Prisma.EvalExtractionSelect;

/** Un aspect tel que `audit_fiche` le rend. */
type Aspect = {
  key: string;
  label: string;
  value: string;
  filled: boolean;
  instrument: string;
  flags: string[];
  /** Le verdict que la fiche approuvée propose. Vide quand elle ne tranche pas. */
  proposed?: string;
  because?: string;
};

type SerializableExtraction = {
  fiche: string;
  aspects: string;
  verdicts: string;
  costUsd: number;
  hasReference: boolean;
  pageMoved: boolean;
  reading: { dates: string };
};

/** Un JSON écrit par le serveur lui-même, donc bien formé — mais une ligne
 * abîmée ne doit pas faire échouer toute la console. */
function parseJson<T>(raw: string, fallback: T): T {
  try {
    const parsed = JSON.parse(raw);
    return parsed === null ? fallback : (parsed as T);
  } catch {
    return fallback;
  }
}

function serializeExtraction<T extends SerializableExtraction>(row: T) {
  const { fiche, aspects, verdicts, reading, ...rest } = row;
  const parsedAspects = parseJson<Aspect[]>(aspects, []);
  const parsedVerdicts = parseJson<Record<string, string>>(verdicts, {});
  return {
    ...rest,
    fiche: parseJson<Record<string, unknown>>(fiche, {}),
    aspects: Array.isArray(parsedAspects) ? parsedAspects : [],
    verdicts: parsedVerdicts,
    reading: { ...reading, dates: parseJson<string[]>(reading.dates, []) },
    /**
     * Tous les aspects sont tranchés : cette fiche compte dans la mesure.
     *
     * Calculé sur les aspects de **cette** fiche, pas sur une liste tenue ici :
     * `audit_fiche` en ajoutera, et une liste écrite côté serveur deviendrait
     * une seconde vérité qui finirait par diverger.
     */
    judged:
      parsedAspects.length > 0 && parsedAspects.every((a) => !!parsedVerdicts[a.key]),
  };
}

type SerializedExtraction = ReturnType<typeof serializeExtraction>;

/**
 * Les trois taux, aspect par aspect.
 *
 * Le croisement de « le modèle a-t-il rempli ce champ ? » et de ce que l'humain
 * en dit :
 *
 * |                | la page le dit  | la page n'en dit rien |
 * |----------------|-----------------|-----------------------|
 * | **renseigné**  | JUSTE ou FAUX   | **INVENTE**           |
 * | **vide**       | **MANQUE**      | JUSTE (vide à raison) |
 *
 * * **exactitude** — parmi les valeurs qu'il a osé écrire, la part juste. C'est
 *   la précision, et elle se lit vite : un tarif inexact vaut un parent qui
 *   arrive avec le mauvais billet.
 * * **couverture** — parmi ce que la page offrait, la part qu'il a rapportée
 *   juste. C'est le rappel, et c'est le chiffre qui demande vraiment un
 *   humain : il faut avoir lu la page pour savoir que l'information y était.
 * * **invention** — la part de ses valeurs que la page ne dit nulle part. La
 *   faute propre à un modèle, et la seule que l'ancrage sait pré-signaler
 *   gratuitement.
 *
 * Rien n'est compté sur une fiche non jugée : un taux calculé sur des lignes
 * que personne n'a regardées dit seulement que personne n'a regardé.
 */
function extractionStats(rows: SerializedExtraction[]) {
  const judged = rows.filter((r) => r.judged);
  const perAspect = new Map<
    string,
    {
      key: string;
      label: string;
      instrument: string;
      /** Fiches jugées où le modèle a rempli ce champ. */
      renseigne: number;
      justeRenseigne: number;
      faux: number;
      invente: number;
      manque: number;
      videJuste: number;
      /** Fiches — jugées ou non — où un instrument a levé un drapeau. */
      signale: number;
      /** Verdicts humains qui n'ont fait que confirmer la fiche approuvée. */
      confirme: number;
      /** Verdicts humains qui l'ont contredite. */
      corrige: number;
    }
  >();

  for (const row of rows) {
    for (const aspect of row.aspects) {
      const slot = perAspect.get(aspect.key) ?? {
        key: aspect.key,
        label: aspect.label,
        instrument: aspect.instrument,
        renseigne: 0, justeRenseigne: 0, faux: 0, invente: 0, manque: 0, videJuste: 0,
        signale: 0, confirme: 0, corrige: 0,
      };
      if (aspect.flags.length) slot.signale += 1;
      const verdict = row.judged ? row.verdicts[aspect.key] : undefined;
      if (verdict && aspect.proposed) {
        if (verdict === aspect.proposed) slot.confirme += 1;
        else slot.corrige += 1;
      }
      if (verdict) {
        if (aspect.filled) {
          slot.renseigne += 1;
          if (verdict === 'JUSTE') slot.justeRenseigne += 1;
          else if (verdict === 'FAUX') slot.faux += 1;
          else if (verdict === 'INVENTE') slot.invente += 1;
        } else if (verdict === 'MANQUE') slot.manque += 1;
        else slot.videJuste += 1;
      }
      perAspect.set(aspect.key, slot);
    }
  }

  const rate = (num: number, den: number) => (den > 0 ? num / den : null);
  const aspects = [...perAspect.values()].map((a) => ({
    ...a,
    // Ce qu'il a osé écrire, et qui était juste.
    exactitude: rate(a.justeRenseigne, a.justeRenseigne + a.faux + a.invente),
    // Ce que la page offrait, et qu'il a rapporté juste. FAUX y compte : la
    // page le disait, et il ne l'a pas rapporté.
    couverture: rate(a.justeRenseigne, a.justeRenseigne + a.faux + a.manque),
    invention: rate(a.invente, a.renseigne),
  }));

  return {
    fiches: rows.length,
    judged: judged.length,
    /** Fiches que le modèle a déclarées hors sujet. */
    ecartees: rows.filter((r) => r.fiche.relevant === false).length,
    /** Fiches qu'il a renvoyées comme programmes, à relire d'un bloc. */
    programmes: rows.filter((r) => r.fiche.several === true).length,
    inventions: aspects.reduce((sum, a) => sum + a.invente, 0),
    manques: aspects.reduce((sum, a) => sum + a.manque, 0),
    /** Fiches jugées contre une sortie approuvée. */
    avecReference: rows.filter((r) => r.hasReference).length,
    /** Fiches dont la page a changé depuis le run : comparaison suspendue. */
    bougees: rows.filter((r) => r.pageMoved).length,
    /**
     * Ce que la fiche approuvée a fait gagner, et ce qu'elle n'a pas dit.
     *
     * `confirmes` mesure la part de la vérité de référence qui n'a fait que
     * confirmer une proposition. C'est le chiffre à garder sous les yeux : une
     * mesure entièrement confirmative reste vraie — un humain a cliqué — mais
     * elle dit surtout que le modèle et le modérateur sont d'accord, ce qui est
     * une information plus faible qu'une relecture indépendante.
     */
    confirmes: aspects.reduce((sum, a) => sum + a.confirme, 0),
    corriges: aspects.reduce((sum, a) => sum + a.corrige, 0),
    costUsd: Math.round(rows.reduce((sum, r) => sum + r.costUsd, 0) * 10000) / 10000,
    aspects,
  };
}

evalRouter.get('/extractions', admin, async (_req, res) => {
  const rows = await prisma.evalExtraction.findMany({
    orderBy: { createdAt: 'desc' },
    select: EXTRACTION_SELECT,
  });
  const extractions = rows.map(serializeExtraction);
  res.json({ extractions, stats: extractionStats(extractions) });
});

/**
 * Met une fiche du banc de lecture en file d'extraction.
 *
 * Une lecture **analysée**, et pas n'importe laquelle : sans texte il n'y a
 * rien à extraire, et une page que l'étage 5 aurait abandonnée n'aurait jamais
 * atteint l'étage 6 dans le pipeline. La mettre au banc mesurerait un appel que
 * la production ne fait pas.
 */
evalRouter.post('/extractions', admin, async (req, res) => {
  const parsed = evalExtractionSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const reading = await prisma.evalReading.findUnique({
    where: { id: parsed.data.readingId },
    select: { id: true, status: true, textChars: true, tooShort: true },
  });
  if (!reading) {
    res.status(404).json({ error: 'Page introuvable au banc de lecture' });
    return;
  }
  if (reading.status !== 'ANALYZED' && reading.status !== 'VALIDATED') {
    res.status(409).json({ error: "Cette page n'a pas encore été lue par l'étage 5" });
    return;
  }
  if (reading.tooShort || reading.textChars === 0) {
    res.status(409).json({
      error:
        "Le texte de cette page est sous le seuil de l'étage 5 : le pipeline l'aurait " +
        "abandonnée avant l'extraction. La mettre ici mesurerait un appel qui n'a jamais lieu.",
    });
    return;
  }
  const existing = await prisma.evalExtraction.findUnique({
    where: { readingId: reading.id },
    select: { id: true },
  });
  if (existing) {
    res.status(409).json({ error: 'Cette page est déjà au banc d’extraction' });
    return;
  }
  const created = await prisma.evalExtraction.create({
    data: { readingId: reading.id, model: parsed.data.model, createdById: req.user!.id },
    select: EXTRACTION_SELECT,
  });
  res.status(201).json({ extraction: serializeExtraction(created) });
});

/**
 * Relance l'extraction. Les verdicts partent avec, et il n'y a pas d'autre
 * choix honnête : ils décrivaient une fiche que le modèle va réécrire.
 */
evalRouter.post('/extractions/:id(\\d+)/analyze', admin, async (req, res) => {
  const id = Number(req.params.id);
  const current = await prisma.evalExtraction.findUnique({
    where: { id },
    select: { status: true },
  });
  if (!current) {
    res.status(404).json({ error: 'Extraction introuvable' });
    return;
  }
  if (current.status === 'RUNNING') {
    res.status(409).json({ error: 'Extraction déjà en cours' });
    return;
  }
  const extraction = await prisma.evalExtraction.update({
    where: { id },
    data: {
      status: 'QUEUED', error: null, analyzedAt: null, validatedAt: null,
      fiche: '{}', aspects: '[]', verdicts: '{}',
      inputTokens: 0, outputTokens: 0, costUsd: 0,
    },
    select: EXTRACTION_SELECT,
  });
  res.json({ extraction: serializeExtraction(extraction) });
});

/**
 * Trancher un aspect, ou plusieurs d'un coup. **C'est la mesure.**
 *
 * Les clés sont vérifiées contre les aspects de **cette** fiche, et pas contre
 * une liste tenue ici : `audit_fiche` en ajoutera, et deux listes finissent
 * toujours par diverger. Une clé inconnue est refusée plutôt qu'ignorée — un
 * verdict qui n'entre dans aucun taux serait un clic perdu sans le dire.
 */
evalRouter.patch('/extractions/:id(\\d+)', admin, async (req, res) => {
  const parsed = evalFieldVerdictSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const id = Number(req.params.id);
  const current = await prisma.evalExtraction.findUnique({
    where: { id },
    select: { aspects: true, verdicts: true },
  });
  if (!current) {
    res.status(404).json({ error: 'Extraction introuvable' });
    return;
  }
  const known = new Set(parseJson<Aspect[]>(current.aspects, []).map((a) => a.key));
  const unknown = Object.keys(parsed.data.verdicts).filter((key) => !known.has(key));
  if (unknown.length) {
    res.status(400).json({ error: `Aspect inconnu de cette fiche : ${unknown.join(', ')}` });
    return;
  }
  const merged = {
    ...parseJson<Record<string, string>>(current.verdicts, {}),
    ...parsed.data.verdicts,
  };
  // Corriger après validation rouvre la fiche : la vérité a changé.
  const extraction = await prisma.evalExtraction.update({
    where: { id },
    data: {
      verdicts: JSON.stringify(merged),
      ...(parsed.data.note === undefined ? {} : { note: parsed.data.note }),
      status: 'ANALYZED',
      validatedAt: null,
    },
    select: EXTRACTION_SELECT,
  });
  res.json({ extraction: serializeExtraction(extraction) });
});

evalRouter.post('/extractions/:id(\\d+)/validate', admin, async (req, res) => {
  const id = Number(req.params.id);
  const current = await prisma.evalExtraction.findUnique({
    where: { id },
    select: { status: true, aspects: true, verdicts: true },
  });
  if (!current) {
    res.status(404).json({ error: 'Extraction introuvable' });
    return;
  }
  if (current.status !== 'ANALYZED') {
    res.status(409).json({ error: 'Seule une extraction terminée se valide' });
    return;
  }
  const aspects = parseJson<Aspect[]>(current.aspects, []);
  const verdicts = parseJson<Record<string, string>>(current.verdicts, {});
  const left = aspects.filter((a) => !verdicts[a.key]);
  // Tous les aspects, ou rien. Valider en n'ayant jugé que le tarif produirait
  // un taux d'âge calculé sur des fiches que personne n'a regardées — le même
  // mensonge que le rappel à 100 % de l'étage 3.
  if (left.length) {
    res.status(409).json({
      error:
        `Il reste ${left.length} aspect(s) à trancher : ${left.map((a) => a.label).join(', ')}. ` +
        "Valider à moitié donnerait des taux calculés sur des champs que personne n'a regardés.",
    });
    return;
  }
  const extraction = await prisma.evalExtraction.update({
    where: { id },
    data: { status: 'VALIDATED', validatedAt: new Date() },
    select: EXTRACTION_SELECT,
  });
  res.json({ extraction: serializeExtraction(extraction) });
});

evalRouter.delete('/extractions/:id(\\d+)', admin, async (req, res) => {
  const deleted = await prisma.evalExtraction.deleteMany({ where: { id: Number(req.params.id) } });
  if (deleted.count === 0) {
    res.status(404).json({ error: 'Extraction introuvable' });
    return;
  }
  res.json({ ok: true });
});

// ──────────────────────────────────────────────────── worker (extraction)

evalRouter.post('/extraction/next', async (_req, res) => {
  const queued = await prisma.evalExtraction.findFirst({
    where: { status: 'QUEUED' },
    orderBy: { createdAt: 'asc' },
    select: {
      id: true,
      model: true,
      reading: {
        select: {
          readUrl: true, url: true, text: true, dates: true,
          event: { select: EVENT_REFERENCE_SELECT },
        },
      },
    },
  });
  if (!queued) {
    res.json({ extraction: null });
    return;
  }
  const claimed = await prisma.evalExtraction.updateMany({
    where: { id: queued.id, status: 'QUEUED' },
    data: { status: 'RUNNING' },
  });
  if (claimed.count === 0) {
    res.json({ extraction: null });
    return;
  }
  res.json({
    extraction: {
      id: queued.id,
      model: queued.model,
      // L'adresse réellement lue quand l'échange de langue a joué : c'est celle
      // que le pipeline aurait donnée au modèle, et le prompt la cite.
      url: queued.reading.readUrl || queued.reading.url,
      // Le texte gelé, jamais la page : l'entrée de cet étage est la sortie du
      // précédent, et c'est ce qui rend les deux mesures séparables.
      text: queued.reading.text,
      // Les dates JSON-LD de l'étage 5, pour l'instrument d'accord.
      dates: parseJson<string[]>(queued.reading.dates, []),
      // La sortie approuvée tirée de cette page, quand il y en a une : une
      // étiquette humaine déjà payée, champ par champ. Elle propose un verdict
      // pour chaque aspect ; elle n'en écrit aucun.
      reference:
        queued.reading.event && queued.reading.event.status === 'APPROVED'
          ? flattenReference(queued.reading.event)
          : null,
    },
  });
});

evalRouter.post('/extraction/:id(\\d+)/result', harvestBody, async (req, res) => {
  const parsed = evalExtractSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const id = Number(req.params.id);
  const { error, fiche, aspects, model, hasReference, pageMoved, ...usage } = parsed.data;
  const updated = await prisma.evalExtraction.updateMany({
    where: { id },
    data: {
      ...usage,
      ...(model ? { model } : {}),
      fiche: JSON.stringify(fiche),
      aspects: JSON.stringify(aspects),
      hasReference,
      pageMoved,
      verdicts: '{}',
      status: error ? 'FAILED' : 'ANALYZED',
      error: error ?? null,
      analyzedAt: new Date(),
      validatedAt: null,
    },
  });
  if (updated.count === 0) {
    res.status(404).json({ error: 'Extraction introuvable' });
    return;
  }
  const row = await prisma.evalExtraction.findUnique({ where: { id }, select: EXTRACTION_SELECT });
  res.json({ extraction: row ? serializeExtraction(row) : null });
});

evalRouter.post('/extraction/:id(\\d+)/fail', async (req, res) => {
  const parsed = evalFailSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const updated = await prisma.evalExtraction.updateMany({
    where: { id: Number(req.params.id) },
    data: { status: 'FAILED', error: parsed.data.error },
  });
  if (updated.count === 0) {
    res.status(404).json({ error: 'Extraction introuvable' });
    return;
  }
  res.json({ ok: true });
});

// ══════════════════ peupler le banc avec ce que le pipeline a déjà fait

/**
 * Le motif exact que l'étage 5 écrit quand il abandonne une page, dans
 * `scraper/sortiesbot/stages/reading.py`. C'est ce qui isole **ses** abandons de
 * ceux de l'étage 8, qui écrit le même `invalid` avec d'autres motifs.
 *
 * Le couplage est une chaîne de caractères, et il faut le savoir : si ce libellé
 * changeait côté scraper, le panier se viderait en silence. C'est pourquoi la
 * route rend toujours le compte disponible — un panier vide se voit.
 */
const ABANDON_REASON = 'page vide ou illisible';

/**
 * Les deux paniers, et pourquoi il en faut deux.
 *
 * Une sortie **approuvée** est une page où l'étage 5 a réussi : son texte était
 * lisible, sinon elle ne serait jamais devenue une sortie. Peupler le banc avec
 * elles seules mesurerait la brique sur ses propres succès — on lirait 96 % de
 * textes corrects, et ça ne voudrait rien dire. C'est le rappel à 100 % de
 * l'étage 3 sous un autre déguisement.
 *
 * L'autre moitié est gratuite et déjà en base : les pages que la lecture a
 * **abandonnées**. Personne n'a jamais vérifié si ces abandons étaient
 * justifiés, et c'est très exactement le point aveugle de cet étage.
 *
 * ## Pourquoi `ScraperRunItem` et pas `Event.sourceUrl`
 *
 * Parce que `sourceUrl` a pu être réécrit par l'étage 7 : quand l'attribution a
 * remonté de l'agrégateur au site du musée, il désigne une page que le pipeline
 * n'a **jamais lue**. `ScraperRunItem.url` est l'adresse réellement ouverte,
 * après l'échange de langue — c'est celle-là qu'il faut relire pour mesurer.
 *
 * ## Ce qui n'entre dans aucun panier
 *
 * Les erreurs réseau (`decision = 'error'`). Une page injoignable ce jour-là est
 * un fait du web, pas un jugement de la brique, et elle répond peut-être
 * aujourd'hui : il n'y a rien à mesurer.
 */
const BUCKETS = {
  approuvees: {
    where: {
      decision: 'submitted',
      event: { is: { status: 'APPROVED' as const } },
    } satisfies Prisma.ScraperRunItemWhereInput,
    origin: 'APPROUVEE' as const,
  },
  abandonnees: {
    where: {
      decision: 'invalid',
      reason: ABANDON_REASON,
    } satisfies Prisma.ScraperRunItemWhereInput,
    origin: 'ABANDONNEE' as const,
  },
};

/**
 * Les pages d'un panier qui ne sont pas déjà au banc, la plus récente d'abord.
 *
 * Dédoublonnées par URL : une même page revient dans plusieurs runs, et deux
 * lignes du banc pour une seule page compteraient deux fois la même mesure.
 */
async function candidates(bucket: keyof typeof BUCKETS, limit: number) {
  const rows = await prisma.scraperRunItem.findMany({
    where: BUCKETS[bucket].where,
    orderBy: { at: 'desc' },
    // Large devant `limit` : on dédoublonne et on écarte les déjà-présentes
    // après coup, donc il faut de la marge pour remplir la demande.
    take: Math.min(limit * 8, 800),
    select: { url: true, title: true, reason: true, decision: true, at: true, eventId: true },
  });

  const seen = new Set<string>();
  const unique = rows.filter((row) => {
    if (!row.url || seen.has(row.url)) return false;
    seen.add(row.url);
    return true;
  });

  const already = await prisma.evalReading.findMany({
    where: { url: { in: unique.map((r) => r.url) } },
    select: { url: true },
  });
  const known = new Set(already.map((r) => r.url));
  return unique.filter((row) => !known.has(row.url));
}

/** Ce que chaque panier peut encore donner. */
evalRouter.get('/seed', admin, async (_req, res) => {
  const [approuvees, abandonnees] = await Promise.all([
    candidates('approuvees', 100),
    candidates('abandonnees', 100),
  ]);
  res.json({
    approuvees: approuvees.length,
    abandonnees: abandonnees.length,
    /** Le libellé qui isole les abandons de l'étage 5. Affiché pour qu'un
     *  panier vide se diagnostique sans lire le code. */
    abandonReason: ABANDON_REASON,
  });
});

/**
 * Met en file un lot de pages tirées d'un panier.
 *
 * Les lignes partent en `QUEUED` : le worker les relira et les gèlera comme
 * n'importe quelle page du banc. Le HTML d'époque n'existe pas — le pipeline ne
 * l'archive pas — donc `readAt` voyage avec, pour que la console puisse dire
 * depuis combien de temps la page a pu bouger.
 */
evalRouter.post('/seed', admin, async (req, res) => {
  const parsed = evalSeedSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { bucket, limit } = parsed.data;
  const rows = (await candidates(bucket, limit)).slice(0, limit);
  if (!rows.length) {
    res.status(409).json({ error: 'Rien de nouveau dans ce panier' });
    return;
  }
  const created = await prisma.evalReading.createMany({
    data: rows.map((row) => ({
      url: row.url,
      label: (row.title ?? '').slice(0, 150),
      origin: BUCKETS[bucket].origin,
      eventId: bucket === 'approuvees' ? row.eventId : null,
      readAt: row.at,
      runDecision: row.decision.slice(0, 40),
      runReason: row.reason ?? '',
      createdById: req.user!.id,
    })),
    // Une course entre deux onglets ne doit pas faire échouer le lot.
    skipDuplicates: true,
  });
  res.status(201).json({ added: created.count });
});
