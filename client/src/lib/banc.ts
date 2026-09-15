/**
 * Ce que la console du banc **décide**, sorti de la vue qui l'affiche.
 *
 * `AdminEvalView.vue` fait deux mille cinq cents lignes et porte cinq domaines.
 * Tout n'a pas vocation à en sortir — un gabarit est un gabarit — mais ces
 * fonctions-ci, si : ce sont elles qui décident quels liens apparaissent en
 * regard d'un relevé, ce qu'une chasse propose de précocher, et combien de
 * corrections un humain s'apprête à apporter.
 *
 * Ce dernier chiffre est le plus important du banc et le moins visible. Zéro
 * correction sur trente pages veut dire que le corpus vient de **recopier**
 * l'étage 2, donc que la mesure qui s'appuiera dessus mesurera la brique contre
 * elle-même. Une faute ici ne casse rien : elle rend les chiffres flatteurs.
 */
import type {
  EvalAgendaPage,
  EvalHunt,
  EvalHuntPage,
  EvalLabelOrigin,
  EvalLink,
  EvalLinkResult,
  EvalPageNature,
  EvalRunScope,
  EvalSortieFacts,
} from '../types';
import { EVAL_AUDIENCE_LABELS } from '../types';

/**
 * Un lien de la page, tel que la console l'affiche : ce que le run en a dit, et
 * ce qu'un humain en a dit. L'un des deux peut manquer.
 */
export interface LigneDeReleve {
  /** Ce que le run a relevé. `null` : le run ne l'a pas vu. */
  result: EvalLinkResult | null;
  /** L'étiquette du corpus. `null` : personne n'a encore tranché. */
  label: EvalLink | null;
}

/**
 * Les lignes d'un relevé, étiquettes en regard.
 *
 * Deux listes à apparier, et **aucune des deux n'est de référence** :
 *
 * * un lien relevé sans étiquette est de la dette — personne n'a dit ce qu'il
 *   valait ;
 * * une étiquette sans relevé est la mesure la plus intéressante du lot. Elle
 *   dit qu'un lien ajouté à la main, ou une sortie qu'on savait là, a disparu
 *   de ce que la brique rend. Les cacher reviendrait à effacer précisément ce
 *   qu'on cherche.
 *
 * L'ordre du relevé est conservé — c'est celui de la page — et les étiquettes
 * orphelines viennent après.
 */
export function apparierReleve(page: Pick<EvalAgendaPage, 'links' | 'results'>): LigneDeReleve[] {
  const parUrl = new Map(page.links.map((l) => [l.url, l]));
  const vues = new Set<string>();
  const lignes: LigneDeReleve[] = [];

  for (const result of page.results ?? []) {
    // La ligne technique de la pagination n'est pas un lien de la page.
    if (result.position < 0) continue;
    vues.add(result.url);
    lignes.push({ result, label: parUrl.get(result.url) ?? null });
  }
  for (const label of page.links) {
    if (!vues.has(label.url)) lignes.push({ result: null, label });
  }
  return lignes;
}

/**
 * Les motifs sous lesquels le dépouillement a écarté des liens, du plus
 * fréquent au moins fréquent.
 *
 * Ce qui a été retenu n'a pas de motif à donner, et la ligne de pagination
 * n'est pas un lien : ni l'un ni l'autre n'entre dans ce compte.
 */
export function motifsDeRejet(page: Pick<EvalAgendaPage, 'results'>): [string, number][] {
  const comptes = new Map<string, number>();
  for (const result of page.results ?? []) {
    if (result.position < 0 || result.harvested || !result.dropReason) continue;
    comptes.set(result.dropReason, (comptes.get(result.dropReason) ?? 0) + 1);
  }
  return [...comptes.entries()].sort((a, b) => b[1] - a[1]);
}

/** L'adresse de page suivante que le relevé a trouvée, s'il en a trouvé une. */
export function pageSuivanteTrouvee(page: Pick<EvalAgendaPage, 'results'>): string {
  return (page.results ?? []).find((r) => r.position < 0)?.selectReason ?? '';
}

/**
 * Ce qu'une sortie du corpus affirme, en une ligne.
 *
 * De la lecture seule : la saisie est ailleurs, parce que c'est là que la
 * donnée vit. Une sortie qui n'affirme rien le dit — c'est une étiquette à
 * remplir, pas une sortie sans particularité.
 */
export function resumeSortie(sortie: EvalSortieFacts | null | undefined): string {
  if (!sortie) return '';
  const bouts: string[] = [];

  if (sortie.dateStart) {
    bouts.push(
      sortie.dateEnd && sortie.dateEnd !== sortie.dateStart
        ? `du ${sortie.dateStart} au ${sortie.dateEnd}`
        : `le ${sortie.dateStart}`,
    );
  }
  if (sortie.postalCode) bouts.push(sortie.postalCode);
  if (sortie.ageMin != null && sortie.ageMax != null) {
    bouts.push(`${sortie.ageMin} à ${sortie.ageMax} ans`);
  } else if (sortie.ageMin != null) bouts.push(`dès ${sortie.ageMin} ans`);
  else if (sortie.ageMax != null) bouts.push(`jusqu’à ${sortie.ageMax} ans`);
  if (sortie.audience) bouts.push(EVAL_AUDIENCE_LABELS[sortie.audience]);

  return bouts.length ? `— ${bouts.join(' · ')}` : '— rien d’affirmé';
}

/** La portée sous laquelle un run a été joué, en une phrase. Vide s'il n'y a rien à dire. */
export function phraseDePortee(scope: EvalRunScope): string {
  const bouts: string[] = [];
  if (scope.dateFrom && scope.dateTo) bouts.push(`du ${scope.dateFrom} au ${scope.dateTo}`);
  if (scope.postalPrefixes?.length) bouts.push(`départements ${scope.postalPrefixes.join(', ')}`);
  if (scope.maxLinks) bouts.push(`${scope.maxLinks} liens au plus par page`);
  if (scope.theme) bouts.push(`« ${scope.theme} »`);
  return bouts.join(' · ');
}

/**
 * D'où vient une étiquette de lien.
 *
 * Les deux origines ne se relisent pas pareil : ce qu'on a cliqué soi-même, on
 * sait pourquoi ; ce qui vient de la modération a été tranché ailleurs, fiche
 * en main, et n'a jamais été revu ici.
 */
export function venueDeLEtiquette(origin: EvalLabelOrigin): string {
  return origin === 'MODERATION'
    ? 'repris d’une sortie approuvée en modération'
    : 'cliqué dans cette console';
}

/** De quoi souligner ce qui est complet, et ce que personne n'a encore touché. */
export function etatDeCompletude(part: { faits: number; total: number }): string {
  if (part.faits === 0) return 'vide';
  return part.faits === part.total ? 'complete' : '';
}

// ══════════════════════════════════════════════════════════════ la chasse

/** Ce qui est coché, par identifiant de page candidate. */
export type Choix = Record<number, EvalPageNature>;

/**
 * La précoche, reposée sur ce qui attend encore.
 *
 * Elle n'est **qu'un affichage** : rien n'entre au corpus tant que personne n'a
 * cliqué. Deux règles la gouvernent, et les deux existent pour la même raison —
 * un corpus rempli en trois clics mesurerait l'étage 2 contre lui-même :
 *
 * * une candidate que l'étage 2 n'a pas su reconnaître reste **décochée**. Lui
 *   donner « agenda », comme le fait le pipeline faute de mieux, écrirait au
 *   corpus un repli d'orchestration au lieu de ce que la page est ;
 * * ce qu'un humain a déjà corrigé à l'écran l'emporte sur la proposition,
 *   sans quoi un rechargement effacerait son travail.
 */
export function precocher(chasses: EvalHunt[], dejaChoisi: Choix): Choix {
  const suivant: Choix = {};
  for (const chasse of chasses) {
    for (const page of chasse.pages) {
      if (page.decision !== 'EN_ATTENTE') continue;
      const propose = dejaChoisi[page.id] ?? page.proposed;
      if (propose) suivant[page.id] = propose;
    }
  }
  return suivant;
}

/** Cocher une nature, ou la décocher en recliquant dessus. */
export function basculer(choix: Choix, pageId: number, nature: EvalPageNature): Choix {
  const suivant = { ...choix };
  if (suivant[pageId] === nature) delete suivant[pageId];
  else suivant[pageId] = nature;
  return suivant;
}

/** Les candidates qui attendent encore qu'on en dise quelque chose. */
export function enAttente(chasse: EvalHunt): EvalHuntPage[] {
  return chasse.pages.filter((p) => p.decision === 'EN_ATTENTE');
}

/** Celles qu'on s'apprête à verser au corpus. */
export function cochees(chasse: EvalHunt, choix: Choix): EvalHuntPage[] {
  return enAttente(chasse).filter((p) => Boolean(choix[p.id]));
}

/**
 * Ce qu'on s'apprête à **contredire**.
 *
 * Le seul chiffre qui dise si la chasse apprend quelque chose au banc. Zéro
 * correction sur trente pages veut dire que le corpus vient de recopier
 * l'étage 2 — et une mesure calculée là-dessus mesurerait la brique contre
 * elle-même.
 *
 * Une candidate que l'étage 2 n'avait pas su reconnaître et qu'un humain
 * étiquette compte pour une correction : l'absence de proposition est un aveu,
 * et le corriger apprend autant que démentir.
 */
export function corrections(chasse: EvalHunt, choix: Choix): number {
  return cochees(chasse, choix).filter((p) => p.proposed !== choix[p.id]).length;
}

/** Ce qui reste en attente sans être coché : ce qu'« écarter le reste » emporte. */
export function restantes(chasse: EvalHunt, choix: Choix): EvalHuntPage[] {
  return enAttente(chasse).filter((p) => !choix[p.id]);
}
