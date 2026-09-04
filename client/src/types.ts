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

/**
 * Champs qu'un programme d'import laisse à compléter par la modération
 * (voir server/src/lib/incomplete.ts) : une adresse qui n'a pas pu être
 * géocodée arrive à (0, 0), un tarif indéterminé arrive négatif. Le serveur
 * refuse d'approuver la sortie tant que ce n'est pas corrigé.
 */
export const UNKNOWN_PRICE = -1;

export function hasCoordinates(venue: Pick<Venue, 'lat' | 'lng'>): boolean {
  return venue.lat !== 0 || venue.lng !== 0;
}

export function hasPrice(event: { isFree: boolean; price: number | null }): boolean {
  return event.isFree || (event.price !== null && event.price >= 0);
}

/** Badge de tarif, y compris pour une sortie importée sans tarif connu. */
export function priceLabel(event: { isFree: boolean; price: number | null }): string {
  if (event.isFree) return 'Gratuit';
  if (!hasPrice(event)) return 'Tarif à compléter';
  return `${event.price} €`;
}

/**
 * Tranche d'âge en clair, y compris quand une seule borne est connue.
 *
 * Les deux bornes sont facultatives et indépendantes : n'afficher la tranche
 * que lorsque les deux sont renseignées faisait disparaître le « à partir de
 * 3 ans » de sorties qui ne se donnent pas d'âge maximum.
 */
export function ageLabel(event: Pick<EventItem, 'ageMin' | 'ageMax'>): string | null {
  const { ageMin, ageMax } = event;
  if (ageMin !== null && ageMax !== null) return `De ${ageMin} à ${ageMax} ans`;
  if (ageMin !== null) return `À partir de ${ageMin} ans`;
  if (ageMax !== null) return `Jusqu'à ${ageMax} ans`;
  return null;
}

/** Même tranche d'âge, en version courte pour un badge de vignette. */
export function shortAgeLabel(event: Pick<EventItem, 'ageMin' | 'ageMax'>): string | null {
  const { ageMin, ageMax } = event;
  if (ageMin !== null && ageMax !== null) return `${ageMin}–${ageMax} ans`;
  if (ageMin !== null) return `dès ${ageMin} ans`;
  if (ageMax !== null) return `jusqu'à ${ageMax} ans`;
  return null;
}

/**
 * Prochain jour où la sortie a lieu, à partir d'aujourd'hui.
 *
 * `null` quand elle n'énumère pas ses jours — le cas courant : sa période
 * suffit alors à la décrire. `undefined` quand elle est passée.
 */
export function nextDate(event: Pick<EventItem, 'dates'>, today = new Date()): string | undefined {
  const iso = today.toISOString().slice(0, 10);
  return event.dates.find((d) => d >= iso);
}

/** « dimanche 20 septembre » — un jour de représentation, en clair. */
export function dayLabel(day: string): string {
  return new Date(`${day}T12:00:00`).toLocaleDateString('fr-FR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
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
  /** Qui lance les recherches : l'outil serveur du modèle, ou Google. */
  provider: 'anthropic' | 'serper';
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
  config?: { id: number; name: string };
  requestedBy?: { id: number; displayName: string } | null;
  items?: ScraperRunItem[];
}

/**
 * Un étage du pipeline, tel que la page de débogage le dessine.
 *
 * Les libellés ne sont pas définis ici : ils viennent du scraper
 * (`sortiesbot/stages.py`), transportés par l'événement `run_start`. Renommer
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
