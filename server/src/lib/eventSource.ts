/**
 * Les deux liens d'une fiche, et ce qu'une correction leur fait.
 *
 * Une sortie en porte deux, et ils ne disent pas la même chose :
 *
 *  * `sourceUrl` — le **meilleur lien connu**, celui que la fiche montre aux
 *    parents : la page de l'organisateur quand on a su la trouver ;
 *  * `foundOnUrl` — la page que la recherche automatique a réellement **lue**,
 *    quand elle n'est pas celle qu'on affiche. Un agenda, un agrégateur.
 *
 * ## La faute que ça corrige
 *
 * L'attribution ne renseigne `foundOnUrl` que lorsqu'elle a trouvé mieux que
 * la page lue. Quand elle échoue — le cas le plus courant — la fiche arrive
 * avec la page lue dans `sourceUrl` et `foundOnUrl` vide. Le modérateur ne
 * voyait alors qu'un seul champ, contenant l'agenda ; il y collait le site de
 * l'organisateur, et la seule trace de l'endroit d'où la sortie venait
 * disparaissait. Deux faits, un champ, l'un écrasant l'autre.
 *
 * L'ancien lien descend donc d'un cran au lieu d'être perdu — exactement ce
 * que fait déjà la recherche de source (`POST /runs/:id/source`) : le meilleur
 * lien connu passe devant, la page d'où l'on est parti devient la provenance.
 *
 * Calcul pur, sans base de données : c'est ce qui permet de l'éprouver, et il
 * y a trois façons de mentir dans quatre lignes.
 */

/** L'état des liens d'une fiche avant qu'on y touche. */
export interface LiensExistants {
  sourceUrl: string | null;
  foundOnUrl: string | null;
  sourceUrlSignal: string | null;
  /**
   * La fiche vient d'une recherche automatique. Sans ça, il n'y a pas de
   * « page lue » : l'adresse qu'un visiteur avait tapée n'a été trouvée nulle
   * part, et la faire descendre en provenance inventerait un fait.
   */
  fromScraper: boolean;
}

/** Ce qu'on écrit en base après la correction d'un modérateur. */
export interface LiensEcrits {
  sourceUrl: string | null;
  foundOnUrl: string | null;
  sourceUrlSignal: string | null;
}

export function liensApresCorrection(
  existants: LiensExistants,
  sourceUrl: string | null,
): LiensEcrits {
  const change = sourceUrl !== existants.sourceUrl;

  // Changer le lien reprend la main sur ce que le scraper avait déduit : le
  // signal ne décrit plus rien de vrai, et le garder ferait passer une saisie
  // pour une trouvaille vérifiée. Inchangé, il préserve ce qu'on savait d'elle
  // — on corrige un titre sans effacer la provenance du lien.
  const sourceUrlSignal = change ? (sourceUrl ? 'manuel' : null) : existants.sourceUrlSignal;

  // Une provenance déjà connue n'est jamais réécrite : d'où la sortie est
  // arrivée est un fait, et corriger une fiche ne le change pas.
  const descendue =
    change && !existants.foundOnUrl && existants.fromScraper
      ? existants.sourceUrl
      : existants.foundOnUrl;

  // Et si les deux finissent égaux, la provenance n'apprend rien : elle repart
  // à vide plutôt que de répéter le lien affiché, ce qui est l'invariant du
  // champ depuis le premier jour.
  const foundOnUrl = descendue && descendue !== sourceUrl ? descendue : null;

  return { sourceUrl, foundOnUrl, sourceUrlSignal };
}
