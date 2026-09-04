/**
 * Mesure de l'étage 7 — l'attribution — à partir du journal d'une exécution.
 *
 * L'étage 7 remonte de la page lue (souvent un agrégateur : kidiklik,
 * citizenkid) à la page de l'organisateur, puis **ouvre** cette page et exige
 * qu'elle parle de la sortie avant de la retenir. Quatre signaux le
 * proposent — JSON-LD, domaine du lieu, texte du lien, moteur — et un seul
 * verdict compte : la page a-t-elle été vérifiée ?
 *
 * Le graphe des briques dit combien de fois l'étage a été traversé et combien
 * de secondes il a pris. Il ne dit pas ce qu'on veut savoir quand l'étage
 * déçoit : **où il perd**. Ne rien proposer et proposer quatre pages fausses
 * sont deux pannes opposées, qui se soignent à deux endroits opposés du code,
 * et le journal plat les affiche pareil — quelques lignes noyées dans mille.
 *
 * D'où cette lecture, qui range le journal en trois questions :
 *
 * 1. **le périmètre** — combien de fiches l'étage a-t-il seulement creusées ?
 *    Il ne fait rien quand la page lue n'est pas un agrégateur connu, et
 *    c'est déjà une réponse : un étage qui ne se déclenche jamais n'a pas un
 *    problème de cascade, il a un problème de liste ;
 * 2. **le rendement de chaque signal** — combien de candidates il a fait
 *    ouvrir, combien ont tenu. Un signal qui propose beaucoup et ne valide
 *    rien coûte des téléchargements et fait perdre les autres, puisque le
 *    plafond de candidates est commun ;
 * 3. **les motifs d'abandon** — ce que l'étage a répondu quand il est reparti
 *    les mains vides, groupé et compté.
 *
 * Rien n'est calculé par le scraper pour cette page : tout est relu du
 * journal tel qu'il est déjà écrit, donc une exécution d'hier se mesure aussi
 * bien qu'une de demain.
 */

import type { TreeRow } from './scraperTree';

/**
 * Une ligne de journal, réduite à ce qu'on lit ici. C'est exactement la
 * projection dont l'arbre se sert : en écrire une seconde, identique, ne
 * ferait qu'ajouter un endroit où se tromper.
 */
export type LogRow = TreeRow;

/** L'étage dont il est question. Voir `sortiesbot/stages/__init__.py`. */
export const ATTRIBUTE_STAGE = 'attribute';

/**
 * Les quatre signaux de la cascade, dans son ordre — du certain au flou.
 * Miroir de `sortiesbot/models.py` (`SIGNAL_*`).
 */
export const ATTRIBUTION_SIGNALS = ['json_ld', 'venue_domain', 'page_link', 'search'] as const;

/**
 * Les statuts que `stages/attribution.py` écrit au journal.
 *
 * C'est un contrat par chaînes de caractères, donc un contrat fragile. On ne
 * range donc jamais de force : un statut inconnu est compté à part
 * (`unknown`), ce qui fait apparaître un renommage côté scraper comme une
 * anomalie visible plutôt que comme une mesure fausse et silencieuse.
 */
const STATUS_OUTSIDE = 'page déjà à la source';
const STATUS_KEPT = 'source retenue';
const STATUS_REJECTED = 'candidate écartée';
const STATUS_UNREACHABLE = 'candidate injoignable';

/** Ce qu'un signal a proposé, et ce que l'épreuve en a fait. */
export interface AttributionSignalTally {
  signal: string;
  /** Candidates réellement téléchargées : c'est ce que le signal a coûté. */
  opened: number;
  /** Candidates qui ont parlé de la sortie. C'est la seule réussite. */
  kept: number;
  /** Ouvertes puis jetées : la page ne parlait pas de cette sortie. */
  rejected: number;
  /** Ouvertes sans succès : robots.txt, 404, délai. */
  unreachable: number;
}

/** Une candidate ouverte puis jetée — avec de quoi aller la regarder. */
export interface AttributionDrop {
  /** L'URL écartée. */
  candidate: string;
  /** La page lue qui l'avait proposée. */
  page: string;
  signal: string;
  reason: string;
  /** Vrai si elle n'a pas répondu, faux si elle a répondu autre chose. */
  unreachable: boolean;
  seq: number;
}

/** Une source retenue, pour pouvoir juger sur pièces. */
export interface AttributionKeep {
  page: string;
  title: string;
  source: string;
  signal: string;
  /** Ce qui a désigné puis vérifié cette page, en une phrase. */
  detail: string;
  seq: number;
}

/** Un motif d'abandon et le nombre de fiches qu'il explique. */
export interface AttributionGiveUp {
  reason: string;
  count: number;
}

export interface Attribution {
  /** Fiches passées par l'étage : un aller-retour de la brique par fiche. */
  fiches: number;
  /**
   * Fiches dont la page lue n'était pas un agrégateur connu : l'étage s'est
   * arrêté à la première ligne, sans rien chercher. Ce n'est pas un échec —
   * mais un run où ce nombre vaut le précédent est un run où l'étage n'a
   * jamais travaillé, ce qui ne se voit nulle part ailleurs.
   */
  outside: number;
  /** Fiches réellement creusées : `fiches` moins `outside`. */
  dug: number;
  /** Fiches reparties avec une source vérifiée. */
  kept: number;
  /** Candidates téléchargées, tous signaux confondus. */
  opened: number;
  /** Requêtes au moteur : le seul appel payant de l'étage. */
  queries: number;
  /** Avertissements et erreurs journalisés dans l'étage. */
  alerts: number;
  /**
   * Événements d'attribution dont le statut n'est plus l'un de ceux qu'on
   * sait lire. Non nul = le scraper a été renommé sans cette page.
   */
  unknown: number;
  bySignal: AttributionSignalTally[];
  giveUps: AttributionGiveUp[];
  drops: AttributionDrop[];
  keeps: AttributionKeep[];
  /** Vrai si les listes ont été coupées — les compteurs, eux, sont entiers. */
  truncated: boolean;
}

/** Au-delà, les deux listes n'apprennent plus rien qu'un compteur ne dise. */
export const ATTRIBUTION_MAX_ROWS = 200;

type Data = Record<string, unknown>;

function parse(raw: string | null): Data {
  if (!raw) return {};
  try {
    const value = JSON.parse(raw) as unknown;
    return value && typeof value === 'object' ? (value as Data) : {};
  } catch {
    // Un JSON illisible ne doit pas faire perdre toute la mesure : la ligne
    // est simplement muette.
    return {};
  }
}

const str = (d: Data, k: string) => (typeof d[k] === 'string' ? (d[k] as string) : '');

/**
 * Le motif d'abandon, rendu groupable.
 *
 * L'étage écrit « aucun résultat vérifiable pour « Ciné-goûter au Nova » » :
 * la requête est dedans, donc chaque fiche a son motif à elle, et grouper ne
 * grouperait rien. On efface ce qui est entre guillemets français — c'est par
 * construction la part propre à la fiche — et rien d'autre : un message
 * d'erreur entre parenthèses, lui, est précisément ce qu'on veut lire.
 */
function groupable(reason: string): string {
  return reason.replace(/«[^»]*»/g, '« … »').trim();
}

/** Ce qu'on sait d'une fiche entre l'ouverture et la fermeture de l'étage. */
interface Fiche {
  page: string;
  title: string;
  outside: boolean;
}

export function buildAttribution(rows: LogRow[]): Attribution {
  const tallies = new Map<string, AttributionSignalTally>();
  const giveUps = new Map<string, number>();
  const drops: AttributionDrop[] = [];
  const keeps: AttributionKeep[] = [];

  let fiches = 0;
  let outside = 0;
  let kept = 0;
  let queries = 0;
  let alerts = 0;
  let unknown = 0;
  let truncated = false;

  const tally = (signal: string): AttributionSignalTally => {
    const key = signal || 'inconnu';
    let entry = tallies.get(key);
    if (!entry) {
      entry = { signal: key, opened: 0, kept: 0, rejected: 0, unreachable: 0 };
      tallies.set(key, entry);
    }
    return entry;
  };

  // L'étage s'ouvre et se ferme une fois par fiche, et tout ce qui le concerne
  // est journalisé entre les deux : suivre l'ouverture courante suffit à
  // rattacher chaque candidate à la fiche qui l'a fait chercher, sans avoir à
  // recoller les lignes par leur URL — deux fiches d'un même programme
  // partagent la même page lue.
  let current: Fiche | null = null;

  for (const row of rows) {
    if (row.stage !== ATTRIBUTE_STAGE) continue;
    const d = parse(row.data);

    switch (row.kind) {
      case 'stage_start':
        current = { page: row.url ?? '', title: str(d, 'title'), outside: false };
        break;

      case 'attribution': {
        const status = str(d, 'status');
        const signal = str(d, 'signal');
        if (status === STATUS_OUTSIDE) {
          if (current) current.outside = true;
          break;
        }
        if (status === STATUS_KEPT) {
          const entry = tally(signal);
          entry.opened += 1;
          entry.kept += 1;
          if (keeps.length < ATTRIBUTION_MAX_ROWS) {
            keeps.push({
              page: current?.page ?? row.url ?? '',
              title: current?.title ?? '',
              source: str(d, 'candidate'),
              signal,
              detail: str(d, 'detail'),
              seq: row.seq,
            });
          } else {
            truncated = true;
          }
          break;
        }
        if (status === STATUS_REJECTED || status === STATUS_UNREACHABLE) {
          const unreachable = status === STATUS_UNREACHABLE;
          const entry = tally(signal);
          entry.opened += 1;
          if (unreachable) entry.unreachable += 1;
          else entry.rejected += 1;
          if (drops.length < ATTRIBUTION_MAX_ROWS) {
            drops.push({
              candidate: str(d, 'candidate'),
              page: current?.page ?? row.url ?? '',
              signal,
              reason: str(d, 'reason'),
              unreachable,
              seq: row.seq,
            });
          } else {
            truncated = true;
          }
          break;
        }
        unknown += 1;
        break;
      }

      case 'query':
        // L'étage ne lance qu'une sorte de requête, mais `op` la nomme : s'y
        // fier plutôt qu'au seul étage laisse la mesure juste si un second
        // appel au moteur apparaît un jour ici.
        if (str(d, 'op') === 'source') queries += 1;
        break;

      case 'error':
        alerts += 1;
        break;

      case 'stage_end': {
        fiches += 1;
        const signal = str(d, 'signal');
        if (signal) {
          kept += 1;
        } else if (current?.outside) {
          outside += 1;
        } else {
          // `produced` porte le motif exact que la brique a rendu : « aucun
          // résultat vérifiable pour … », « recherche de source désactivée »,
          // « budget atteint ». Groupé tel quel, sans être réécrit : c'est la
          // phrase du scraper, et c'est elle qu'on ira relire dans le code.
          const reason = groupable(str(d, 'produced')) || 'motif non journalisé';
          giveUps.set(reason, (giveUps.get(reason) ?? 0) + 1);
        }
        current = null;
        break;
      }

      default:
        break;
    }
  }

  // Les signaux sont rendus dans l'ordre de la cascade, ceux qui n'ont rien
  // proposé compris : « JSON-LD n'a rien remonté de tout le run » est un
  // résultat, et une ligne absente se lirait comme une ligne oubliée.
  const ordered: AttributionSignalTally[] = ATTRIBUTION_SIGNALS.map(
    (signal) => tallies.get(signal) ?? { signal, opened: 0, kept: 0, rejected: 0, unreachable: 0 },
  );
  for (const [signal, entry] of tallies) {
    if (!(ATTRIBUTION_SIGNALS as readonly string[]).includes(signal)) ordered.push(entry);
  }

  return {
    fiches,
    outside,
    dug: fiches - outside,
    kept,
    opened: ordered.reduce((sum, s) => sum + s.opened, 0),
    queries,
    alerts,
    unknown,
    bySignal: ordered,
    giveUps: [...giveUps]
      .map(([reason, count]) => ({ reason, count }))
      .sort((a, b) => b.count - a.count),
    drops,
    keeps,
    truncated,
  };
}
