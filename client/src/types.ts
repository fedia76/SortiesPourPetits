export type Role = 'USER' | 'MODERATOR' | 'ADMIN';
export type Setting = 'INDOOR' | 'OUTDOOR' | 'BOTH';
export type EventStatus = 'PENDING' | 'APPROVED' | 'REJECTED';

export interface User {
  id: number;
  email: string;
  displayName: string;
  role: Role;
}

export interface Category {
  id: number;
  name: string;
}

/**
 * Une zone géographique ouverte sur le site.
 *
 * Elle ne se rattache à aucune sortie : elle décrit un ensemble de préfixes de
 * code postal, et une sortie en fait partie si le code postal de son lieu
 * commence par l'un d'eux. Redessiner une zone n'a donc rien à migrer.
 */
export interface Area {
  id: number;
  slug: string;
  name: string;
  postalPrefixes: string;
  intro: string;
  position: number;
  /** Sorties à venir dans la zone — renseigné par la liste publique. */
  eventCount?: number;
}

export interface Venue {
  id: number;
  name: string;
  address: string;
  city: string;
  postalCode: string;
  lat: number;
  lng: number;
}

/** Pourquoi et à quel point une sortie ressemble à celle en cours de modération. */
export interface Similarity {
  /** Note de 0 à 100 : plus c'est haut, plus le doublon est probable. */
  score: number;
  reasons: string[];
  distanceKm?: number;
}

/**
 * Ce qui a désigné le lien source d'une sortie. Les quatre premiers sont les
 * signaux de l'étage attribution du scraper, du plus sûr au moins sûr ; le
 * dernier dit qu'un humain l'a saisi ou corrigé.
 */
export const SOURCE_SIGNAL_LABELS: Record<string, string> = {
  json_ld: 'déclaré par la page',
  venue_domain: 'domaine du lieu',
  page_link: 'lien « site officiel »',
  search: 'trouvé par recherche',
  manuel: 'saisi à la main',
};

export interface EventItem {
  id: number;
  title: string;
  description: string;
  /** Le meilleur lien connu : la page de l'organisateur, ou celle où on l'a lue. */
  sourceUrl: string | null;
  /**
   * La page où la recherche automatique a repéré la sortie, quand ce n'est pas
   * celle qu'on affiche — un agrégateur qui republiait un musée. Provenance :
   * elle ne s'affiche qu'aux modérateurs.
   */
  foundOnUrl?: string | null;
  /** Ce qui a désigné `sourceUrl` — voir `SOURCE_SIGNAL_LABELS`. */
  sourceUrlSignal?: string | null;
  /**
   * La fiche vient d'une recherche automatique. Ce qui en dépend : `sourceUrl`
   * et `foundOnUrl` sont alors deux **faits** — le meilleur lien connu et la
   * page réellement lue —, là où une proposition de visiteur n'a qu'une
   * adresse saisie, qui n'a été « trouvée » nulle part.
   */
  fromScraper?: boolean;
  isFree: boolean;
  price: number | null;
  photoUrl: string | null;
  ageMin: number | null;
  ageMax: number | null;
  isPermanent: boolean;
  dateStart: string | null;
  dateEnd: string | null;
  /** Jours de représentation. Vide = tous les jours de la période. */
  dates: string[];
  openTime: string | null;
  closeTime: string | null;
  setting: Setting | null;
  status: EventStatus;
  rejectionReason: string | null;
  venue: Venue;
  category: Category;
  author: { id: number; displayName: string; email?: string };
  /**
   * La recherche automatique qui a proposé cette sortie, `null` si elle vient
   * d'un visiteur. Renseigné par la file de modération.
   */
  origin?: { configId: number; configName: string } | null;
  distanceKm?: number;
  /** Renseigné par la recherche de doublons de la modération. */
  similarity?: Similarity;
}

export interface EventInput {
  title: string;
  description: string;
  sourceUrl: string | null;
  isFree: boolean;
  price: number | null;
  ageMin: number | null;
  ageMax: number | null;
  isPermanent: boolean;
  dateStart: string | null;
  dateEnd: string | null;
  dates: string[];
  openTime: string | null;
  closeTime: string | null;
  setting: Setting | null;
  categoryId: number;
  venue: Omit<Venue, 'id'>;
}

export const SETTING_LABELS: Record<Setting, string> = {
  INDOOR: 'Intérieur',
  OUTDOOR: 'Extérieur',
  BOTH: 'Intérieur & extérieur',
};

export const STATUS_LABELS: Record<EventStatus, string> = {
  PENDING: 'En attente de modération',
  APPROVED: 'Approuvée',
  REJECTED: 'Refusée',
};

export type ScraperRunStatus = 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED';

export const RUN_STATUS_LABELS: Record<ScraperRunStatus, string> = {
  QUEUED: 'En file',
  RUNNING: 'En cours',
  DONE: 'Terminée',
  FAILED: 'En échec',
};

/**
 * Les deux modes d'une recherche automatique.
 *
 * « recherche » : le modèle cherche sur le web, on dépouille les agendas
 * qu'il remonte. « site » : les adresses sont connues (le site d'un festival,
 * la saison d'un théâtre) et aucune recherche n'est lancée.
 */
export type ScraperMode = 'recherche' | 'site';

export const SCRAPER_MODE_LABELS: Record<ScraperMode, string> = {
  recherche: 'Recherche web',
  site: 'Site précis',
};

/**
 * Une recherche paramétrée du scraper. Thème, période et zone orientent la
 * recherche ; ils ne filtrent pas le résultat quand `keepOutOfScope` est vrai,
 * parce qu'une page déjà lue est déjà payée.
 */
export interface ScraperConfig {
  id: number;
  name: string;
  enabled: boolean;
  mode: ScraperMode;
  /** Adresses de départ du mode « site », une par ligne. */
  seedUrls: string;
  theme: string;
  area: string;
  period: string;
  horizonDays: number;
  maxEvents: number;
  maxSearches: number;
  maxAgendas: number;
  maxLinksPerAgenda: number;
  maxPageChars: number;
  maxCostUsd: number;
  keepOutOfScope: boolean;
  defaultCategory: string;
  postalPrefixes: string;
  /**
   * Refuser de lire les agrégateurs, au lieu de simplement remonter à la
   * source depuis leurs fiches. La liste, elle, est commune au site — voir
   * `Aggregator` et la page « Agrégateurs » de la console.
   */
  blockAggregators: boolean;
  /** Autorise l'attribution à chercher la page de l'organisateur (payant). */
  sourceSearch: boolean;
  /**
   * Verse au corpus du banc les agendas que cette recherche dépouille, à la
   * clôture de chaque exécution. C'est ce qui gèle la page **du jour du run**,
   * seule à porter encore les liens que la modération va trancher.
   */
  freezeAgendas: boolean;
  /**
   * Qui cherche, et qui tient le modèle derrière — un champ pour ces deux
   * choix, parce qu'il n'existe que ces trois croisements : l'outil serveur du
   * modèle avec Claude, Google avec Claude, Google avec un modèle d'OpenRouter.
   */
  provider: 'anthropic' | 'serper' | 'openrouter';
  /** Pages suivantes d'un agenda, suivies tant que la moisson est maigre. */
  maxNextPages: number;
  /** Requêtes imposées, une par ligne. Vide : le modèle les formule. */
  queries: string | null;
  /** Vide : la reconnaissance s'en tient aux signaux gratuits. */
  classifyModel: string;
  searchModel: string;
  selectModel: string;
  extractionModel: string;
  queriesPrompt: string | null;
  classifyPrompt: string | null;
  searchPrompt: string | null;
  selectPrompt: string | null;
  extractionPrompt: string | null;
  extractionMultiPrompt: string | null;
  createdAt: string;
  _count?: { runs: number };
  runs?: Pick<ScraperRun, 'id' | 'status' | 'queuedAt' | 'finishedAt' | 'retained'>[];
}

export interface ScraperRun {
  id: number;
  status: ScraperRunStatus;
  submit: boolean;
  queuedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  /** Date à laquelle les sorties et la mémoire de l'exécution ont été supprimées. */
  purgedAt: string | null;
  error: string | null;
  candidates: number;
  /** Pages d'agenda téléchargées, pages suivantes comprises. */
  pages: number;
  /** Celles qui n'étaient pas la première page d'un agenda. */
  nextPages: number;
  retained: number;
  submitted: number;
  duplicates: number;
  skipped: number;
  errors: number;
  inputTokens: number;
  outputTokens: number;
  webSearches: number;
  costUsd: number;
  /**
   * La recherche jouée. Absente pour une **recherche de source** : celle-ci
   * n'explore rien, elle rejoue l'étage 7 sur une sortie déjà en base, et
   * c'est `event` qui la nomme.
   */
  config?: { id: number; name: string } | null;
  /** La sortie dont on cherchait la source, pour ce genre d'exécution. */
  event?: { id: number; title: string } | null;
  requestedBy?: { id: number; displayName: string } | null;
  items?: ScraperRunItem[];
}

/**
 * Un étage du pipeline, tel que la page de débogage le dessine.
 *
 * Les libellés ne sont pas définis ici : ils viennent du scraper
 * (`sortiesbot/stages/__init__.py`), transportés par l'événement `run_start`.
 * Renommer
 * une brique côté scraper suffit donc à la renommer partout.
 */
export interface ScraperStageNode {
  stage: string;
  number: number;
  label: string;
  /** « modele » = l'étage est facturé ; « python » = il est gratuit. */
  actor: 'modele' | 'python' | string;
  takes: string;
  gives: string;
  /** Nombre d'événements journalisés dans cet étage. */
  events: number;
  errors: number;
  /** Passages : un étage est traversé une fois par agenda, ou par page. */
  passes: number;
  seconds: number;
  /** Ce que chaque passage a produit, en une ligne. */
  produced: string[];
  /** Ce que l'étage a coûté sur ce run, jetons et recherches web compris. */
  costUsd: number;
  tokens: number;
  searches: number;
  /** Nombre d'appels au modèle. Zéro pour un étage gratuit. */
  calls: number;
}

/**
 * L'arbre d'une exécution : la filiation, pas la chronologie.
 *
 * Le journal dit ce qui s'est passé ; l'arbre dit d'où chaque sortie vient —
 * quelle requête a remonté quel agenda, quel agenda a donné quel lien, quel
 * lien a donné quelle fiche. Assemblé côté serveur (`lib/scraperTree.ts`).
 */
export interface ScraperTreePage {
  url: string;
  title: string;
  agenda: string;
  /** Le contexte du lien sur l'agenda — pourquoi il a été retenu. */
  why: string;
  chars: number;
  outcome: string;
  /** submitted, dry_run, skip, ou vide si la page n'a pas été tranchée. */
  decision: string;
  eventId: number | null;
  errors: number;
  seq: number;
}

export type ScraperResultFate = 'agenda' | 'direct' | 'ignore' | 'echec' | 'plafond' | 'annonce';

/** Ce qu'un résultat de recherche est devenu, dit en clair. */
export const FATE_LABELS: Record<ScraperResultFate, string> = {
  agenda: 'dépouillé comme agenda',
  direct: 'lue directement comme sortie',
  ignore: 'non retenu par le modèle',
  echec: 'retenu mais injoignable',
  plafond: 'retenu mais au-delà du plafond d\'agendas',
  annonce: 'désigné, jamais ouvert',
};

export const AGENDA_STATUS_LABELS: Record<string, string> = {
  depouille: 'dépouillé',
  echec: 'injoignable',
  plafond: 'au-delà du plafond',
  annonce: 'jamais ouvert',
};

export interface ScraperTreeAgenda {
  url: string;
  title: string;
  status: 'depouille' | 'echec' | 'plafond' | 'annonce';
  statusReason: string;
  /** Ce que le modèle dit avoir écarté, en une phrase. */
  droppedReason: string;
  links: number;
  /**
   * Pages de l'agenda téléchargées : 1, ou davantage s'il se pagine et que le
   * dépouillement a suivi. À ne pas confondre avec `pages`, qui sont les
   * sorties qu'il a données.
   */
  fetched: number;
  kept: number;
  seconds: number;
  errors: number;
  /** La requête web qui a remonté cet agenda, quand on la connaît. */
  fromQuery: string;
  pages: ScraperTreePage[];
}

export interface ScraperTree {
  searches: { query: string; results: { url: string; title: string; fate: ScraperResultFate }[] }[];
  agendas: ScraperTreeAgenda[];
  /** Ce qui n'est venu d'aucun agenda : sortie remontée telle quelle, ou seed. */
  direct: ScraperTreePage[];
  /** Compteurs cumulés par étage — des totaux, pas le dernier passage. */
  totals: Record<string, Record<string, number>>;
  truncated: boolean;
}

/**
 * La mesure de l'étage 7 — l'attribution — sur une exécution.
 *
 * L'étage remonte de la page lue à la page de l'organisateur, puis ouvre
 * cette page et exige qu'elle parle de la sortie. Le graphe dit combien de
 * fois il a été traversé ; il ne dit pas **où il perd** — ne rien proposer et
 * proposer quatre pages fausses sont deux pannes opposées. Assemblé côté
 * serveur (`lib/scraperAttribution.ts`), relu du journal tel qu'il est écrit :
 * une exécution d'hier se mesure comme une de demain.
 */
export interface ScraperAttributionSignal {
  signal: string;
  /** Candidates réellement téléchargées : ce que le signal a coûté. */
  opened: number;
  /** Candidates qui ont parlé de la sortie. C'est la seule réussite. */
  kept: number;
  /** Ouvertes puis jetées : la page parlait d'autre chose. */
  rejected: number;
  /** Ouvertes sans succès : robots.txt, 404, délai. */
  unreachable: number;
}

/**
 * Un résultat du moteur refusé **sans être ouvert** — agrégateur, domaine
 * bloqué, même site. Distinct d'une candidate écartée, et c'est la
 * distinction qui compte : celle-ci n'a rien coûté, et elle dit autre chose.
 */
export interface ScraperAttributionDiscard {
  candidate: string;
  reason: string;
  page: string;
  seq: number;
}

export interface ScraperAttributionDrop {
  candidate: string;
  page: string;
  signal: string;
  reason: string;
  unreachable: boolean;
  seq: number;
}

export interface ScraperAttributionKeep {
  page: string;
  title: string;
  source: string;
  signal: string;
  detail: string;
  seq: number;
}

export interface ScraperAttribution {
  /** Fiches passées par l'étage : un aller-retour de la brique par fiche. */
  fiches: number;
  /** Fiches dont la page lue n'était pas un agrégateur : rien à remonter. */
  outside: number;
  /** Fiches réellement creusées. */
  dug: number;
  /** Fiches reparties avec une source vérifiée. */
  kept: number;
  /** Candidates téléchargées, tous signaux confondus. */
  opened: number;
  /** Requêtes au moteur : le seul appel payant de l'étage. */
  queries: number;
  /**
   * Résultats rendus par le moteur, toutes requêtes confondues. Zéro alors
   * que `queries` ne l'est pas : le moteur n'a rien trouvé — ce qui ne se
   * soigne pas comme un moteur bavard dont tout est refusé.
   */
  engineResults: number;
  /** Résultats refusés au tamis, sans être ouverts. */
  discarded: number;
  alerts: number;
  /** Statuts que cette page ne sait plus lire — un renommage côté scraper. */
  unknown: number;
  bySignal: ScraperAttributionSignal[];
  giveUps: { reason: string; count: number }[];
  drops: ScraperAttributionDrop[];
  discards: ScraperAttributionDiscard[];
  keeps: ScraperAttributionKeep[];
  truncated: boolean;
}

/** Les quatre signaux de la cascade, dits en clair. */
export const ATTRIBUTION_SIGNAL_LABELS: Record<string, string> = {
  json_ld: 'JSON-LD de la page',
  venue_domain: 'Domaine du lieu',
  page_link: 'Texte du lien',
  search: 'Moteur (payant)',
};

/** Ce que chaque signal lit, pour qui n'a pas le code sous les yeux. */
export const ATTRIBUTION_SIGNAL_HINTS: Record<string, string> = {
  json_ld: 'ce que la page déclare : Event.url, sameAs, offers.url',
  venue_domain: '« Musée Rodin » retrouvé dans musee-rodin.fr, parmi les liens sortants',
  page_link: "un lien qui s'annonce : « site officiel », « réserver », « billetterie »",
  search: 'une requête au moteur — titre et lieu — quand la page ne porte pas le lien',
};

export type ScraperLogLevel = 'info' | 'warn' | 'error';

/** Une ligne du journal détaillé d'une exécution. */
export interface ScraperRunLog {
  id: number;
  /** Numéro d'ordre émis par le scraper : c'est le curseur de pagination. */
  seq: number;
  at: string;
  /** L'un des six étages, ou null hors étage (démarrage, clôture). */
  stage: string | null;
  kind: string;
  level: ScraperLogLevel;
  url: string | null;
  message: string | null;
  /** Le reste des champs de l'événement. */
  data: Record<string, unknown> | null;
}

export const LOG_LEVEL_LABELS: Record<ScraperLogLevel, string> = {
  info: 'Information',
  warn: 'Avertissement',
  error: 'Erreur',
};

/** Rendu court d'un événement, par type. Miroir de `journal._CONSOLE`. */
/**
 * Un agrégateur : un grand agenda qui republie l'information d'autrui.
 *
 * La liste est commune à toutes les recherches — elle se tient dans
 * « Recherche auto → Agrégateurs » — et chaque recherche décide seulement de
 * lire ces sites ou de les refuser.
 */
export interface Aggregator {
  id: number;
  /** Le domaine seul, sans `www.` : `kidiklik.fr`. Sous-domaines compris. */
  domain: string;
  label: string;
  /** Faux : le site n'est plus tenu pour un agrégateur, la ligne reste. */
  enabled: boolean;
  note: string;
  createdAt: string;
  updatedAt: string;
}

export const LOG_KIND_LABELS: Record<string, string> = {
  run_start: 'Démarrage',
  run_end: 'Fin du run',
  stage_start: "Entrée dans l'étage",
  stage_end: "Sortie de l'étage",
  query: 'Requête web',
  search_result: 'Résultat de recherche',
  direct: 'Sortie trouvée directement',
  seed: 'Point de départ',
  fetching: 'Téléchargement',
  harvested: 'Liens extraits',
  next_page: "Page suivante de l'agenda",
  link: 'Lien proposé au tri',
  link_kept: 'Lien retenu',
  selected: 'Tri terminé',
  fallback: 'Repli',
  candidate: 'Page candidate',
  attribution: 'Attribution de la source',
  page: 'Page lue',
  prompt: 'Prompt envoyé',
  usage: 'Jetons consommés',
  programme: 'Programme dépouillé',
  extract: 'Fiche extraite',
  geocode: 'Géocodage',
  schedule: 'Calendrier',
  photo: 'Photo',
  incomplete: 'Champ à compléter',
  out_of_scope: 'Hors périmètre, gardée',
  skip: 'Écartée',
  budget: 'Budget atteint',
  dry_run: 'Retenue (essai)',
  submit: 'Proposée',
  nothing_found: 'Aucun candidat',
  error: 'Erreur',
};

export interface ScraperRunItem {
  id: number;
  url: string;
  /** Clé de mémorisation, quand la page a été mémorisée. */
  key: string | null;
  title: string | null;
  decision: string;
  reason: string | null;
  eventId: number | null;
  at: string;
}

/**
 * Une page dont le scraper se souvient (`ScrapedUrl`).
 *
 * L'URL est la clé normalisée — schéma, `www.`, paramètres de suivi et barre
 * finale retirés — pas forcément le lien exact rencontré : deux adresses
 * équivalentes ne doivent pas faire relire deux fois la même page.
 */
export interface ScrapedUrlEntry {
  id: number;
  url: string;
  title: string | null;
  decision: string;
  firstSeen: string;
  lastSeen: string;
  eventId: number | null;
  event?: { id: number; title: string; status: EventStatus } | null;
}

export interface ScraperMemory {
  entries: ScrapedUrlEntry[];
  total: number;
  page: number;
  pageSize: number;
  /** Poids de chaque verdict sur toute la mémoire, filtre courant ignoré. */
  decisions: { decision: string; count: number }[];
}

/** Ce que le scraper a décidé d'une page, en clair. */
export const DECISION_LABELS: Record<string, string> = {
  submitted: 'Proposée au site',
  dry_run: 'Retenue (essai)',
  duplicate: 'Doublon',
  irrelevant: 'Pas une sortie',
  invalid: 'Inexploitable',
  out_of_period: 'Hors période',
  out_of_area: 'Hors zone',
  seen: 'Déjà connue',
  blocked: 'Domaine bloqué',
  error: 'Erreur',
};

/**
 * Tableau de bord du scraping (`GET /api/scraper/stats`).
 *
 * Les parts se calculent côté vue : le serveur renvoie des comptes, ce qui
 * évite d'avoir à s'entendre sur un arrondi.
 */
export interface ScraperStats {
  scope: { configId: number | null; configName: string | null; days: number | null };
  totals: {
    runs: number;
    candidates: number;
    /** Pages d'agenda téléchargées, pages suivantes comprises. */
    pages: number;
    /** Agendas ouverts : `pages` moins les pages suivantes. */
    agendas: number;
    nextPages: number;
    retained: number;
    submitted: number;
    costUsd: number;
    inputTokens: number;
    outputTokens: number;
    webSearches: number;
  };
  /** Un domaine source, `www.` retiré : les pages qu'il a coûtées et ce qu'il a donné. */
  domains: { domain: string; pages: number; submitted: number; approved: number }[];
  categories: { id: number; name: string; events: number; approved: number }[];
  decisions: { decision: string; count: number }[];
  /** Statuts des sorties importées, indexés par `EventStatus`. */
  statuses: Partial<Record<EventStatus, number>>;
  configs: {
    id: number;
    name: string;
    runs: number;
    pages: number;
    retained: number;
    submitted: number;
    costUsd: number;
  }[];
}

// ────────────────────────────────────── ce que la modération apprend au scraper

/** Un étage du pipeline, tel que le scraper le numérote. */
export interface BlamedStage {
  stage: string;
  number: number;
  label: string;
}

/**
 * Un motif de refus, et l'étage qu'il met en cause.
 *
 * Servi par l'API plutôt que recopié ici : la même table remplit les puces de
 * la modération et groupe les refus par étage sur la page de qualité, et deux
 * copies auraient divergé au premier motif ajouté.
 */
export interface RejectionMeaning {
  code: string;
  label: string;
  hint: string;
  blames: BlamedStage[];
}

/** Une population classée sur ce qu'on sait de son taux, pas sur ce qu'on a vu. */
export interface QualityRanked {
  pages: number;
  submitted: number;
  /** Sorties effectivement jugées — les « en attente » n'y sont pas. */
  judged: number;
  approved: number;
  /** Taux d'approbation brut, ou `null` si rien n'a encore été jugé. */
  rate: number | null;
  /** Borne basse de Wilson à 95 % : c'est elle qui ordonne le tableau. */
  lower: number;
  /** Faux : l'effectif est sous le plancher, la ligne n'est pas classée. */
  enough: boolean;
}

export interface ScraperQuality {
  codes: RejectionMeaning[];
  /** Effectif minimal pour qu'une ligne soit classée plutôt que constatée. */
  rankingFloor: number;
  judged: { approved: number; rejected: number; pending: number };
  corrections: {
    /** Approuvées sans la moindre retouche : la seule preuve positive. */
    untouched: number;
    touched: number;
    fields: { field: string; events: number }[];
  };
  /** `code` est nul pour les refus antérieurs au motif comptable. */
  rejections: { code: string | null; events: number }[];
  signals: (QualityRanked & { signal: string })[];
  queries: (QualityRanked & { query: string })[];
  domains: (QualityRanked & { domain: string })[];
}

/** Les champs d'une fiche, sous le nom que leur donne l'API du site. */
export const FIELD_LABELS: Record<string, string> = {
  title: 'Titre',
  description: 'Description',
  sourceUrl: 'Lien',
  isFree: 'Gratuité',
  price: 'Tarif',
  ageMin: 'Âge minimum',
  ageMax: 'Âge maximum',
  isPermanent: 'Permanente',
  dateStart: 'Date de début',
  dateEnd: 'Date de fin',
  openTime: 'Heure d’ouverture',
  closeTime: 'Heure de fermeture',
  setting: 'Cadre',
  categoryId: 'Catégorie',
  venueName: 'Nom du lieu',
  venueAddress: 'Adresse',
  venueCity: 'Ville',
  venuePostalCode: 'Code postal',
  dates: 'Jours de représentation',
};

// ───────────────────────────────────────────────────────── banc d'évaluation

// ══════════════════════════════════════════════════════ le banc d'évaluation
//
// Trois choses, et elles ne se mélangent plus : le **corpus** (une entrée
// gelée et ce qu'un humain dit qu'elle contient), les **runs** (ce qu'une
// brique en a rendu, un par exécution, jamais écrasés) et la **mesure**, qui
// se calcule de la confrontation des deux et n'est stockée nulle part.

export type EvalCaptureStatus = 'QUEUED' | 'RUNNING' | 'CAPTURED' | 'FAILED';

export const EVAL_CAPTURE_LABELS: Record<EvalCaptureStatus, string> = {
  QUEUED: 'À capturer',
  RUNNING: 'Capture en cours',
  CAPTURED: 'Gelée',
  FAILED: 'Capture en échec',
};

export type EvalStage = 'HARVEST' | 'SELECT' | 'READ' | 'EXTRACT';

export const EVAL_STAGE_LABELS: Record<EvalStage, string> = {
  HARVEST: '3. Dépouillement',
  SELECT: '4. Sélection',
  READ: '5. Lecture',
  EXTRACT: '6. Extraction',
};

/** Ce que chaque étage mesuré coûte à rejouer. */
export const EVAL_STAGE_COST: Record<EvalStage, string> = {
  HARVEST: 'gratuit — du Python sur du HTML gelé',
  SELECT: 'payant — un appel au modèle par page',
  READ: 'gratuit — du Python sur du HTML gelé',
  EXTRACT: 'payant — un appel au modèle par page',
};

export type EvalRunStatus = 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED';

export const EVAL_RUN_STATUS_LABELS: Record<EvalRunStatus, string> = {
  QUEUED: 'En file',
  RUNNING: 'En cours',
  DONE: 'Terminé',
  FAILED: 'En échec',
};

export type EvalVerdict = 'SORTIE' | 'PAGINATION' | 'SOUS_AGENDA' | 'AUTRE';

export const EVAL_VERDICT_LABELS: Record<EvalVerdict, string> = {
  SORTIE: 'Une sortie',
  PAGINATION: 'Page suivante',
  SOUS_AGENDA: 'Un autre agenda',
  AUTRE: 'Autre chose',
};

export const EVAL_VERDICT_HINTS: Record<EvalVerdict, string> = {
  SORTIE: 'Le lien mène à la fiche d’un événement précis.',
  PAGINATION: 'Le lien mène à la suite de cette même liste.',
  SOUS_AGENDA: 'Le lien mène à une autre liste de sorties — une facette, une catégorie.',
  AUTRE: 'Navigation, mentions légales, partage : rien qui mène à une sortie.',
};

/** D'où vient une étiquette. Les deux sont le travail d'un humain. */
export type EvalLabelOrigin = 'HUMAIN' | 'MODERATION';

export const EVAL_LABEL_ORIGIN_LABELS: Record<EvalLabelOrigin, string> = {
  HUMAIN: 'relu dans la console',
  MODERATION: 'approuvé en modération',
};

/**
 * Une étiquette sur un lien. **Il n'y a pas d'état « non étiqueté »** : la
 * ligne existe parce qu'un humain l'a posée, et son absence dit que personne
 * n'a regardé.
 */
export interface EvalLink {
  id: number;
  url: string;
  text: string;
  source: 'PAGE' | 'MANUAL';
  verdict: EvalVerdict;
  origin: EvalLabelOrigin;
  note: string;
  labelledAt: string;
  /**
   * La sortie vers laquelle ce lien mène.
   *
   * Un lien ne décrit pas une sortie, il y mène : ce qu'elle est — sa date,
   * son lieu, son âge — appartient à la sortie, qui le dit une fois pour les
   * étages 4, 5 et 6. `null` sur un lien « une sortie » veut dire que
   * personne ne l'a encore décrite.
   */
  sortieId: number | null;
  sortie?: EvalSortieFacts | null;
  /**
   * Ce que la sortie donne **pour le run affiché** — calculé par le serveur,
   * jamais stocké. La même sortie est pertinente sous une fenêtre et hors
   * recherche sous une autre : c'est tout l'intérêt de ne pas l'étiqueter.
   */
  relevance?: EvalRelevance;
}

/** Ce que l'étage 4 juge d'une sortie : sa date, son lieu, son âge. */
export interface EvalSortieFacts {
  dateStart: string | null;
  dateEnd: string | null;
  postalCode: string | null;
  ageMin: number | null;
  ageMax: number | null;
  audience: EvalAudience | null;
}

/** La pertinence d'un lien pour une recherche donnée. Toujours dérivée. */
export type EvalRelevance = 'PERTINENTE' | 'HORS_RECHERCHE' | 'INDECIDABLE';

export const EVAL_RELEVANCE_LABELS: Record<EvalRelevance, string> = {
  PERTINENTE: 'dans la recherche',
  HORS_RECHERCHE: 'hors recherche',
  INDECIDABLE: 'indécidable',
};

export const EVAL_RELEVANCE_HINTS: Record<EvalRelevance, string> = {
  PERTINENTE: 'Le tri doit la retenir : ne pas le faire compte comme une sortie manquée.',
  HORS_RECHERCHE:
    'Le tri a raison de l’écarter. La retenir compte comme du bruit — une lecture payée pour rien.',
  INDECIDABLE:
    'Les indices ne suffisent pas à trancher pour cette recherche : ce lien n’entre dans aucun ' +
    'dénominateur, et rien n’est reproché au modèle.',
};

/** À qui la sortie s'adresse, tel que la page l'annonce. */
export type EvalAudience = 'ENFANTS' | 'ADULTES' | 'INDETERMINE';

export const EVAL_AUDIENCE_LABELS: Record<EvalAudience, string> = {
  ENFANTS: 'jeune public',
  ADULTES: 'adultes',
  INDETERMINE: 'non dit',
};

export const EVAL_AUDIENCE_HINTS: Record<EvalAudience, string> = {
  ENFANTS: 'La page l’annonce pour les enfants ou les familles.',
  ADULTES: 'La page l’annonce pour un public adulte — écartée dans toute recherche.',
  INDETERMINE: 'La page ne dit rien du public. N’écarte rien.',
};

/** Ce qu'un run a relevé sur un lien : le relevé, jamais l'étiquette. */
export interface EvalLinkResult {
  id: number;
  url: string;
  text: string;
  context: string;
  harvested: boolean;
  dropReason: string;
  position: number;
  selected: boolean | null;
  selectReason: string;
}

/** Les deux erreurs du dépouillement, comptées séparément. */
export interface EvalHarvestScore {
  found: number;
  missed: number;
  noise: number;
  unlabelled: number;
  recall: number | null;
  precision: number | null;
}

/**
 * Le tri fait trois métiers, et se mesure donc sur trois colonnes de plus.
 *
 * `rightlyDropped` est du travail bien fait qui n'apparaissait nulle part :
 * une sortie hors fenêtre ou pour adultes que le modèle a eu raison d'écarter,
 * et que l'ancienne mesure comptait comme une faute. `undecidable` est ce que
 * le corpus ne permet pas de trancher — hors de tout dénominateur, affiché
 * pour qu'on sache ce qu'on ignore. `cappedPages` compte les pages où le tri a
 * retenu exactement son plafond : elles sortent du rappel, parce qu'on ne
 * peut pas y distinguer un mauvais jugement d'un quota atteint.
 */
export interface EvalSelectScore extends EvalHarvestScore {
  rightlyDropped: number;
  undecidable: number;
  cappedPages: number;
}

/** Ce que la recherche d'un run demandait — ce sous quoi le tri a été joué. */
export interface EvalRunScope {
  dateFrom?: string;
  dateTo?: string;
  postalPrefixes?: string[];
  maxLinks?: number;
  theme?: string;
}

export interface EvalAgendaPage {
  id: number;
  pageNo: number;
  url: string;
  chars: number;
  archived: boolean;
  /** `null` : personne n'a regardé. `''` : il n'y a pas de suite. */
  nextExpected: string | null;
  links: EvalLink[];
  results?: EvalLinkResult[];
  score?: { harvest: EvalHarvestScore; select: EvalSelectScore | null };
  labels?: number;
}

/**
 * Un agenda que la recherche auto a dépouillé, et ce qu'il a rendu.
 *
 * Le corpus se remplissait en collant des adresses à la main, sans rapport avec
 * ce que la modération avait déjà tranché. Sans recouvrement, « reprendre ce
 * qu'un humain a validé » ne reprend rien, et l'étage 4 n'a rien à mesurer.
 */
export interface EvalAgendaCandidat {
  url: string;
  /** La requête web qui avait remonté cet agenda. Vide en mode « site ». */
  query: string;
  /** Pages distinctes que la production a tirées de cet agenda. */
  pages: number;
  /** Parmi elles, celles qu'un modérateur a approuvées. */
  approuvees: number;
  /** Les approuvées des trois derniers mois : ce qui a une chance d'y être encore. */
  recentes: number;
  refusees: number;
  derniere: string | null;
  dejaAuCorpus: boolean;
}

/**
 * Où en est un agenda du corpus.
 *
 * La chaîne des gestes est une dépendance réelle : geler, jouer un run
 * d'étage 3, étiqueter — et alors seulement l'étage 4 mesure. Sauter une étape
 * ne produit aucune erreur, seulement un zéro plus loin, qu'on attribue à la
 * brique.
 */
export type EvalAgendaEtape =
  | 'A_GELER'
  | 'SANS_RELEVE'
  | 'A_ETIQUETER'
  | 'EN_COURS'
  | 'COMPLET';

export const EVAL_ETAPE_LABELS: Record<EvalAgendaEtape, string> = {
  A_GELER: 'à geler',
  SANS_RELEVE: 'aucun run joué',
  A_ETIQUETER: 'à étiqueter',
  EN_COURS: 'étiquetage en cours',
  COMPLET: 'tous les liens étiquetés',
};

export const EVAL_ETAPE_SUITE: Record<EvalAgendaEtape, string> = {
  A_GELER: 'Le worker doit d’abord geler ses pages : rien ne peut être rejoué avant.',
  SANS_RELEVE:
    'Ses liens ne sont pas encore connus. Jouez un run de dépouillement depuis « Mesures » : c’est lui qui les relève.',
  A_ETIQUETER:
    'Ses liens sont relevés, aucun n’est étiqueté. Reprenez d’abord ce que la modération a déjà tranché, puis ouvrez-le.',
  EN_COURS:
    'Les liens non étiquetés sortent de tous les dénominateurs : le rappel ne porte que sur ce qui l’est.',
  COMPLET: 'Chaque lien relevé porte une étiquette : le rappel de cet agenda est complet.',
};

export interface EvalAgenda {
  id: number;
  url: string;
  label: string;
  pages: number;
  capture: EvalCaptureStatus;
  captureError: string | null;
  capturedAt: string | null;
  note: string;
  createdAt: string;
  /**
   * Nul pour un agenda enrôlé par la clôture d'un run de production : personne
   * ne l'a saisi, et `note` dit de quel run il vient.
   */
  author?: { id: number; displayName: string } | null;
  agendaPages: EvalAgendaPage[];
  /** Liens qu'un run du banc a relevés : le dénominateur de l'étiquetage. */
  releves: number;
  etape: EvalAgendaEtape;
  pagesCaptured?: number;
  labels?: number;
}

export type EvalSortieOrigin = 'MANUEL' | 'APPROUVEE' | 'ABANDONNEE' | 'ILLISIBLE';

export const EVAL_ORIGIN_LABELS: Record<EvalSortieOrigin, string> = {
  MANUEL: 'saisie à la main',
  APPROUVEE: 'sortie approuvée',
  ABANDONNEE: 'page abandonnée',
  ILLISIBLE: 'description refusée',
};

export const EVAL_ORIGIN_HINTS: Record<EvalSortieOrigin, string> = {
  MANUEL: 'Quelqu’un l’a ajoutée au corpus depuis cette console.',
  APPROUVEE: 'Le pipeline en a tiré une sortie qu’un modérateur a approuvée.',
  ABANDONNEE: 'L’étage 5 l’a écartée — page vide, illisible ou injoignable.',
  ILLISIBLE:
    'Elle a passé le seuil et coûté une extraction, et la fiche a été refusée ' +
    'pour description inutilisable : le point aveugle de cet étage.',
};

/**
 * Une page du corpus, et ce qu'un humain dit qu'elle contient.
 *
 * Chaque étiquette a trois états. `null` : personne n'a regardé. Une valeur
 * vide : la page n'en porte pas, et c'est une étiquette. Une valeur : la voici.
 */
export interface EvalSortie {
  id: number;
  url: string;
  label: string;
  capture: EvalCaptureStatus;
  captureError: string | null;
  capturedAt: string | null;
  chars: number;
  archived: boolean;
  note: string;

  /**
   * **L'étiquette** : tout ce qu'un humain affirme de cette sortie, en JSON.
   *
   * Une sortie, une étiquette. Elle était autrefois éparpillée entre des
   * colonnes pour l'étage 5, d'autres pour l'étage 4, et une table à part pour
   * l'étage 6 qui redécrivait les mêmes dates et les mêmes âges. Chaque étage
   * y lit désormais son sous-ensemble et ignore le reste.
   *
   * Clé absente : personne n'a regardé. Clé présente et vide : la page n'en
   * dit rien, et c'est une étiquette.
   */
  expected: string;
  /** D'où vient chaque champ : `CORRIGE`, `NON_CONTREDIT`, `SAISIE`. En JSON. */
  origins: string;
  /** L'étiquette d'avant, en toutes lettres. N'entre dans aucune mesure. */
  expectedLegacy: string | null;
  labelledAt: string | null;

  /** Annoncé en mots par la page. La seule affirmation qu'aucune brique ne rend. */
  audience: EvalAudience | null;

  /**
   * Ce que l'étiquette couvre, étage par étage — calculé par le serveur, à
   * partir du code de mesure lui-même.
   *
   * Jamais une liste recopiée ici : deux compteurs successifs ont menti pour
   * l'avoir été. Ajouter un critère à un étage déplace le dénominateur tout
   * seul, du côté où la mesure vit.
   */
  couverture: {
    /** Étage 4 — la date, le lieu, le public. */
    tri: { faits: number; total: number };
    /** Étage 5 — l'image, les dates déclarées, les fragments du texte. */
    lecture: { faits: number; total: number };
    /** Étage 6 — les aspects de la fiche qu'au moins un champ renseigne. */
    extraction: { faits: number; total: number };
  };

  origin: EvalSortieOrigin;
  /**
   * **Vrai** : la sortie existe sur le site, un modérateur l'a approuvée, et
   * son étiquette est du travail humain déjà payé. **Faux** : elle n'existe
   * que dans le banc, et tout ce qu'elle affirme reste à saisir.
   */
  published: boolean;
  eventId: number | null;
  readAt: string | null;
  runDecision: string;
  runReason: string;
  createdAt: string;
  author?: { id: number; displayName: string };
}

/** Les champs de l'étiquette que la console fait saisir. */
export interface EvalSortieLabel {
  image: string | null;
  declaredDates: string[] | null;
  markers: string[] | null;
  dateStart: string | null;
  dateEnd: string | null;
  venuePostalCode: string | null;
  ageMin: number | null;
  ageMax: number | null;
}

/**
 * **Groupe 1 du corpus** : ce qu'une page *est*, avant qu'on en fasse quoi que
 * ce soit. C'est la question de l'étage 2.
 *
 * L'erreur n'y est pas symétrique, et c'est ce qui rend la mesure utile :
 * prendre une sortie pour un agenda coûte un appel de tri et se rattrape tout
 * seul ; prendre un agenda pour une sortie coûte **tous ses liens**, sans
 * rattrapage.
 */
export interface EvalNature {
  id: number;
  url: string;
  label: string;
  capture: EvalCaptureStatus;
  captureError: string | null;
  capturedAt: string | null;
  chars: number;
  archived: boolean;
  /** Ce que la page est, d'après un humain. Jamais nul : c'est l'étiquette. */
  nature: EvalPageNature;
  /** Ce que l'étage 2 proposait quand un humain a tranché. Nul si rien. */
  proposed: EvalPageNature | null;
  /** D'où vient l'étiquette : saisie, corrigée, ou laissée passer. */
  origin: EvalNatureOrigin;
  note: string;
  labelledAt: string;
  createdAt: string;
  author?: { id: number; displayName: string };
}

/**
 * D'où vient l'étiquette d'une page du corpus de l'étage 2.
 *
 * Le même vocabulaire que la provenance des champs d'une fiche, et pour la
 * même raison : une étiquette qui ne fait que reprendre ce que la brique
 * proposait ne la contredit jamais, donc ne la mesure pas vraiment.
 */
export type EvalNatureOrigin = 'SAISIE' | 'CORRIGE' | 'NON_CONTREDIT';

export const EVAL_NATURE_ORIGIN_LABELS: Record<EvalNatureOrigin, string> = {
  SAISIE: 'saisie',
  CORRIGE: 'corrigée',
  NON_CONTREDIT: 'non contredite',
};

export const EVAL_NATURE_ORIGIN_HINTS: Record<EvalNatureOrigin, string> = {
  SAISIE: 'Un humain a saisi l’adresse et la nature, sans que rien ne lui souffle.',
  CORRIGE:
    'Une chasse proposait autre chose, un humain a corrigé. La plus forte des ' +
    'trois : elle est indépendante de ce que la brique pensait.',
  NON_CONTREDIT:
    'Une chasse proposait ceci, un humain l’a laissé passer. Elle compte — il ' +
    'faut des cas où la brique a raison — mais un taux calculé surtout sur ' +
    'celles-là mesure l’étage 2 contre lui-même.',
};

/** Ce que le corpus de l'étage 2 doit à la brique qu'il mesure. */
export interface SoucheCorpus {
  total: number;
  saisies: number;
  corriges: number;
  nonContredits: number;
  /** Part de ce qui ne vient pas de la brique. Nulle si le corpus est vide. */
  independance: number | null;
}

// ─────────────────────────────────────────────────────────────── les chasses

export type EvalHuntStatus = 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED';
export type EvalHuntDecision = 'EN_ATTENTE' | 'RETENUE' | 'ECARTEE';

export const EVAL_HUNT_STATUS_LABELS: Record<EvalHuntStatus, string> = {
  QUEUED: 'en file',
  RUNNING: 'en cours',
  DONE: 'terminée',
  FAILED: 'en échec',
};

/**
 * Une page remontée par une chasse, et ce que l'étage 2 en pense.
 *
 * `proposed` est nul quand l'étage 2 n'a pas su trancher — et ce nul est la
 * seule chose qui empêche une chasse de se valider toute seule. Le pipeline,
 * lui, traite « inconnu » en agenda, mais c'est une décision d'orchestration :
 * la recopier écrirait au corpus ce que le pipeline fait au lieu de ce que la
 * page est.
 */
export interface EvalHuntPage {
  id: number;
  huntId: number;
  url: string;
  /** L'adresse d'avant l'échange de langue, quand il a joué. Vide sinon. */
  foundUrl: string;
  title: string;
  query: string;
  proposed: EvalPageNature | null;
  /** Le signal qui a tranché : `url`, `pagination`, `json-ld`, `modele`… */
  signal: string;
  detail: string;
  /** `certain` : le site le déclare. `probable` : on l'infère de sa forme. */
  confidence: string;
  /** Le modèle interrogé pour cette page-ci. Vide : la cascade a suffi. */
  asked: string;
  links: number;
  dated: number;
  heading: string;
  opening: string;
  chars: number;
  archived: boolean;
  /** Page injoignable ce jour-là : rendue quand même, sans précoche. */
  error: string;
  decision: EvalHuntDecision;
  decidedAt: string | null;
  natureId: number | null;
  createdAt: string;
}

export interface EvalHunt {
  id: number;
  prompt: string;
  area: string;
  /** Requêtes imposées au lancement. Vides : le modèle les a formulées. */
  queries: string[];
  /** Celles réellement lancées, écrites à la clôture. */
  ranQueries: string[];
  maxQueries: number;
  maxPages: number;
  provider: string;
  status: EvalHuntStatus;
  error: string | null;
  /** Ce que les recherches ont remonté au-delà du plafond, et qu'on n'a pas ouvert. */
  overCap: number;
  costUsd: number;
  model: string;
  codeRef: string;
  queuedAt: string;
  startedAt: string | null;
  endedAt: string | null;
  author?: { id: number; displayName: string };
  comptes: {
    total: number;
    enAttente: number;
    retenues: number;
    ecartees: number;
    indecises: number;
    injoignables: number;
  };
  pages: EvalHuntPage[];
}

export type EvalPageNature = 'AGENDA' | 'SORTIE' | 'PROGRAMME' | 'AUTRE';

export const EVAL_NATURE_LABELS: Record<EvalPageNature, string> = {
  AGENDA: 'un agenda',
  SORTIE: 'une sortie',
  PROGRAMME: 'un programme',
  AUTRE: 'autre chose',
};

export const EVAL_NATURE_HINTS: Record<EvalPageNature, string> = {
  AGENDA:
    'Une liste qui renvoie vers des fiches. Part au dépouillement. La prendre ' +
    'pour une sortie coûte tous ses liens, sans rattrapage.',
  SORTIE: 'La fiche d’un événement précis. Saute directement à la lecture.',
  PROGRAMME:
    'Un festival qui tient sur une page : plusieurs sorties reliées par des ' +
    'ancres. Lue d’un bloc, on en attend plusieurs fiches.',
  AUTRE:
    'Ni l’un ni l’autre — une page d’accueil, un article, une billetterie. ' +
    'Ces contre-exemples comptent : sans eux on ne mesurerait que les cas où ' +
    'l’étage 2 a déjà raison.',
};

/**
 * Ce que chaque étage cherche à savoir, et dans quels champs de l'étiquette il
 * le lit. Servi par le serveur, jamais recopié : c'est la liste même que les
 * compteurs appliquent.
 */
export interface EvalCriteres {
  etages: {
    etage: number;
    nom: string;
    criteres: { libelle: string; champs: string[] }[];
  }[];
}

/**
 * Ce qu'il reste à faire à la main, compté.
 *
 * La modération paie la précision — parmi ce que le scraper a proposé, ce
 * qu'un humain a validé. Elle ne paiera jamais le rappel : ce qu'il a raté
 * n'apparaît pas dans ce qu'il a proposé, par construction. Ces deux comptes
 * ne raccourcissent pas ce travail, ils l'affichent — un coût qu'on découvre
 * au fil de l'eau fait abandonner un banc au bout de trois semaines.
 */
export interface EvalReste {
  /** Par page d'agenda : les liens relevés que personne n'a tranchés. */
  jamaisRegardes: { pageId: number; url: string; label: string; manquants: number }[];
  /**
   * Le lien dit « une sortie », mais **aucune sortie n'existe au corpus**.
   * L'objet est à créer avant de pouvoir rien en affirmer.
   */
  aCreer: EvalDette[];
  /**
   * La sortie **existe**, mais son étiquette n'affirme rien que l'étage 4
   * puisse lire — ni date, ni code postal, ni âge, ni public.
   */
  aDecrire: EvalDette[];
}

/** Un lien « une sortie » que l'étage 4 ne peut pas juger, et pourquoi. */
export interface EvalDette {
  id: number;
  url: string;
  text: string;
  sortieId: number | null;
  /** `HUMAIN` : cliqué dans la console. `MODERATION` : repris d'une sortie approuvée. */
  origin: EvalLabelOrigin;
  page: { id: number; pageNo: number; agenda: { id: number; label: string } };
}

/**
 * La recherche sous laquelle un run de tri est joué.
 *
 * En **dates absolues** : une fenêtre relative ferait qu'un même run ne mesure
 * plus la même chose selon le jour où on le rejoue.
 *
 * Ces valeurs servent deux fois — elles partent dans le prompt de l'étage 4, et
 * elles servent à juger ce qu'il a rendu. Venant du même endroit, elles ne
 * peuvent pas se contredire.
 */
export interface EvalRecherche {
  dateFrom: string;
  dateTo: string;
  postalPrefixes: string[];
  maxLinks: number;
  theme: string;
}

/**
 * Qui joue la brique mesurée — l'étage 6, et l'étage 4 pour les deux premiers.
 *
 * La clé s'appelle toujours `extraction` en base, parce que c'est là qu'elle
 * est née ; ce qu'elle porte vaut pour les deux étages qui appellent quelqu'un.
 */
export type EvalProvider = 'anthropic' | 'gliner' | 'openrouter';

/**
 * Combien le modèle a le droit de réfléchir. `''` : celui du scraper.
 *
 * Une chaîne libre, et non trois valeurs : ce vocabulaire est celui du
 * **modèle**, pas du routeur. « low », « high » et « max » sont ceux du modèle
 * par défaut ; un autre éditeur dit « minimal » ou « medium », et celui qui ne
 * raisonne pas n'en a aucun.
 */
export type EvalEffort = string;

/** Ceux qu'on connaît, pour les **proposer**. La saisie reste libre. */
export const EVAL_EFFORTS_CONNUS = ['low', 'high', 'max'];

export interface EvalExtraction {
  provider: EvalProvider;
  /**
   * Le modèle, selon le fournisseur : un point de contrôle Hugging Face pour
   * l'étiqueteur, un slug « éditeur/modèle » pour le routeur. Vide : celui par
   * défaut du scraper.
   */
  model?: string;
  /**
   * L'effort de raisonnement, pour un run OpenRouter et lui seul.
   *
   * C'est la comparaison la plus intéressante que ce fournisseur permette :
   * passer de « rien demandé » à « low » a divisé le coût d'une reconnaissance
   * par seize, et ce que « high » rend de plus reste à mesurer.
   */
  effort?: EvalEffort;
}

export const EVAL_PROVIDER_LABELS: Record<EvalProvider, string> = {
  anthropic: 'Le modèle (Haiku) — celui de la production',
  openrouter: 'Un modèle d’OpenRouter — au choix, au tarif qu’il annonce',
  gliner: 'Un étiqueteur local (GLiNER) — gratuit, sans rédaction',
};

/**
 * Ce que deux verdicts font ensemble, du point de vue du run de référence.
 *
 * C'est la seule chose que la comparaison ajoute au banc : elle ne juge rien,
 * elle rapproche deux jugements déjà rendus.
 */
export type EvalBascule = 'PERDU' | 'GAGNE' | 'TENU' | 'RATE' | 'NON_JUGE';

export const EVAL_BASCULE_LABELS: Record<EvalBascule, string> = {
  PERDU: 'La référence avait bon, l’autre non',
  GAGNE: 'L’autre a bon, la référence non',
  TENU: 'Les deux ont bon',
  RATE: 'Les deux se trompent',
  NON_JUGE: 'Le corpus ne dit rien',
};

/** Une ligne de comparaison : une page du corpus, un aspect, deux réponses. */
export interface EvalLigneComparee {
  sortieId: number;
  url: string;
  label: string;
  key: string;
  libelle: string;
  attendu: string;
  renduA: string;
  renduB: string;
  verdictA: 'JUSTE' | 'FAUX' | 'INVENTE' | 'MANQUE' | null;
  verdictB: 'JUSTE' | 'FAUX' | 'INVENTE' | 'MANQUE' | null;
  bascule: EvalBascule;
}

export interface EvalBasculesAspect {
  key: string;
  libelle: string;
  tenu: number;
  perdu: number;
  gagne: number;
  rate: number;
  nonJuge: number;
}

/** Ce que rend `/api/eval/runs/:a/comparer/:b`. */
export interface EvalComparaison {
  a: EvalRun & { erreurs: number; traites: number };
  b: EvalRun & { erreurs: number; traites: number };
  /** Pages lues par les **deux** runs : les seules qui se comparent. */
  communes: number;
  aspects: EvalBasculesAspect[];
  lignes: EvalLigneComparee[];
  /** Aspects où les deux runs disent la même chose, comptés et non listés. */
  identiques: number;
}

/** Le résumé chiffré d'un run, calculé à la lecture et jamais stocké. */
export type EvalScore =
  | ({ kind: 'links' } & EvalHarvestScore &
      // Les trois colonnes du tri ne viennent que des runs de tri : le
      // dépouillement ne juge pas la pertinence, et il ne prétend pas le faire.
      Partial<Pick<EvalSelectScore, 'rightlyDropped' | 'undecidable' | 'cappedPages'>> & {
        pagination: { correct: number; missed: number; wrong: number; unjudged: number };
      })
  | {
      kind: 'read';
      items: number;
      textOk: number;
      textJudged: number;
      imageOk: number;
      imageJudged: number;
      datesOk: number;
      datesJudged: number;
      truncated: number;
      tooShort: number;
      rate: number | null;
    }
  | {
      kind: 'extract';
      items: number;
      JUSTE: number;
      FAUX: number;
      INVENTE: number;
      MANQUE: number;
      inconnu: number;
      /**
       * Entrées dont la fiche n'est jamais revenue : appel refusé, réponse
       * tronquée, hébergeur tombé.
       *
       * À lire **avant** les manquants : une fiche absente compte MANQUÉ sur
       * ses douze aspects, et un incident technique prend alors l'apparence
       * d'un effondrement de qualité. Les deux ne se corrigent pas au même
       * endroit.
       */
      erreurs: number;
      rate: number | null;
      /** Le même décompte, aspect par aspect. Voir `EvalAspectTally`. */
      parAspect: EvalAspectTally[];
    };

/**
 * Le décompte d'un aspect sur tout un run.
 *
 * Le taux global d'un run d'extraction est une moyenne sur douze aspects très
 * différents, et il cache ce qu'on veut savoir : **lequel lâche**. Douze
 * aspects médiocres et onze corrects pour un effondré donnent le même chiffre,
 * et n'appellent pas le même travail.
 *
 * `inconnu` compte à part, et c'est capital : un aspect que le corpus
 * n'étiquette nulle part n'est pas un aspect raté, c'est une dette du corpus.
 */
export interface EvalAspectTally {
  key: string;
  libelle: string;
  JUSTE: number;
  FAUX: number;
  INVENTE: number;
  MANQUE: number;
  inconnu: number;
  /** JUSTE sur ce qui a été jugé, ou `null` si personne n'a rien étiqueté. */
  rate: number | null;
}

export interface EvalRun {
  id: number;
  stage: EvalStage;
  status: EvalRunStatus;
  error: string | null;
  label: string;
  /** De quoi ce run est le run. Sans ça, la courbe ne s'attribue à rien. */
  codeRef: string;
  model: string;
  promptHash: string;
  settings: string;
  inputTokens: number;
  outputTokens: number;
  /**
   * Ceux de la sortie partis en raisonnement, **compris** dans `outputTokens`.
   *
   * Sans eux, un modèle qui réfléchit et un modèle bavard rendent le même
   * chiffre pour deux causes opposées — et elles ne se corrigent pas au même
   * endroit : l'effort de raisonnement d'un côté, le prompt de l'autre.
   */
  reasoningTokens: number;
  costUsd: number;
  /**
   * Combien d'entrées du corpus ce run avait à traiter — et, une fois clos, ce
   * que le worker déclare avoir traité. C'est le dénominateur de l'avancement.
   */
  items: number;
  queuedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  /**
   * Le dernier signe de vie du worker sur ce run. Nul pour un run jamais
   * réclamé, ou réclamé avant que cette colonne n'existe.
   */
  heartbeatAt: string | null;
  requestedBy?: { id: number; displayName: string } | null;
  /**
   * Ce qui est **fait**, compté depuis ce que le run a écrit. Sans lui,
   * « En cours » ne disait pas la différence entre un run qui avance et un run
   * qui n'avancera plus — et c'est exactement la question qu'on se pose en
   * regardant cette ligne.
   */
  traites?: number;
  score?: EvalScore;
}

/**
 * Le détail d'une mesure : la ligne, et pas un total plus petit.
 *
 * Un taux surprenant ne se corrige pas, il se **remonte** — jusqu'au lien qui
 * l'a fait, et jusqu'à la phrase qui dit dans quelle case il tombe. Ces types
 * décrivent ce que le serveur rend pour ça ; les raisons y sont fabriquées par
 * la mesure elle-même, jamais reconstituées ici : une explication écrite à côté
 * du test finit toujours par décrire un test qui a changé.
 */
export type EvalLinkCase =
  | 'TROUVEE'
  | 'MANQUEE'
  | 'BRUIT'
  | 'ECARTEE_A_RAISON'
  | 'INDECIDABLE'
  | 'SANS_ETIQUETTE'
  | 'NON_SOUMISE';

export const EVAL_LINK_CASE_LABELS: Record<EvalLinkCase, string> = {
  TROUVEE: 'trouvée',
  MANQUEE: 'manquée',
  BRUIT: 'bruit',
  ECARTEE_A_RAISON: 'écartée à raison',
  INDECIDABLE: 'indécidable',
  SANS_ETIQUETTE: 'sans étiquette',
  NON_SOUMISE: 'jamais soumise',
};

export const EVAL_LINK_CASE_HINTS: Record<EvalLinkCase, string> = {
  TROUVEE: 'Le corpus la veut, la brique l’a retenue. Compte dans le rappel.',
  MANQUEE: 'Le corpus la veut, la brique l’a laissée. La faute chère, et silencieuse.',
  BRUIT: 'La brique l’a retenue, le corpus n’en veut pas. Une lecture payée pour rien.',
  ECARTEE_A_RAISON:
    'Le corpus n’en veut pas, la brique ne l’a pas prise. Du travail bien fait, hors de tout taux.',
  INDECIDABLE:
    'Le corpus ne permet pas de trancher — personne n’a décrit la sortie. Hors de tout dénominateur.',
  SANS_ETIQUETTE:
    'Retenue, mais le corpus ne dit rien de ce lien. Un trou du corpus, pas une faute de la brique.',
  NON_SOUMISE:
    'Le dépouillement ne l’a pas soumise au tri : l’étage 4 ne l’a jamais vue, et ne paie pas pour elle.',
};

/** Un lien de la mesure : ce que le corpus dit, ce que la brique a fait, et la case. */
export interface EvalLinkLine {
  url: string;
  cas: EvalLinkCase;
  retenu: boolean;
  verdict: EvalVerdict | null;
  relevance: EvalRelevance | null;
  /** Pourquoi cette case-là, fabriqué par la mesure. */
  raison: string;
  /** Hors du taux affiché — page plafonnée, ou hors dénominateur. */
  horsTaux: boolean;
  texte: string;
  contexte: string;
  /** Ce que la brique a dit d’elle-même : motif de rejet, ou motif du tri. */
  motif: string;
}

/** Le détail d'un run de dépouillement ou de tri, page par page. */
export interface EvalRunDetailPage {
  pageId: number;
  url: string;
  pageNo: number;
  label: string;
  /** Le tri a pris exactement son quota : cette page sort du rappel. */
  plafonnee: boolean;
  score: EvalHarvestScore & Partial<EvalSelectScore>;
  pagination: { attendu: string | null; trouve: string };
  liens: EvalLinkLine[];
}

/** Le détail d'un run de lecture, sortie par sortie. */
export interface EvalRunDetailRead {
  sortieId: number;
  url: string;
  label: string;
  textChars: number;
  error: string | null;
  score: {
    markersFound: number;
    markersMissing: number;
    textOk: boolean | null;
    truncated: boolean;
    tooShort: boolean;
    imageOk: boolean | null;
    datesOk: boolean | null;
  };
  detail: {
    image: { attendu: string | null; rendu: string; verdict: boolean | null };
    dates: { attendues: string[] | null; rendues: string[]; verdict: boolean | null };
    fragments: { trouves: string[]; manquants: string[]; verdict: boolean | null };
    truncated: boolean;
    tooShort: boolean;
  };
}

/** Un aspect de la fiche, avec les deux valeurs qu'on a comparées. */
export interface EvalAspectDetail {
  key: string;
  libelle: string;
  verdict: EvalFieldVerdict | null;
  attendu: string;
  rendu: string;
}

/** Le détail d'un run d'extraction, sortie par sortie. */
export interface EvalRunDetailExtract {
  sortieId: number;
  url: string;
  label: string;
  costUsd: number;
  error: string | null;
  tally: { JUSTE: number; FAUX: number; INVENTE: number; MANQUE: number; inconnu: number };
  byField: Record<string, EvalFieldVerdict | null>;
  aspects: EvalAspectDetail[];
}

export type EvalRunDetail =
  | EvalRunDetailPage[]
  | EvalRunDetailRead[]
  | EvalRunDetailExtract[];

/** Les quatre verdicts de l'étage 6, dérivés et non plus stockés. */
export type EvalFieldVerdict = 'JUSTE' | 'FAUX' | 'INVENTE' | 'MANQUE';

export const EVAL_FIELD_VERDICT_LABELS: Record<EvalFieldVerdict, string> = {
  JUSTE: 'juste',
  FAUX: 'faux',
  INVENTE: 'inventé',
  MANQUE: 'manquant',
};

/** Ce que le corpus peut encore recevoir de ce que le pipeline a déjà fait. */
export interface EvalSeedCounts {
  approuvees: number;
  abandonnees: number;
  illisibles: number;
  liens: number;
  /** Sorties venues du site, dont l'étiquette reste à reprendre. */
  fiches: number;
  abandonReason: string;
}
