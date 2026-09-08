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
  evalLinkSchema,
  evalNextSchema,
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
