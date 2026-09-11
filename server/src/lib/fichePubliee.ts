/**
 * La fiche telle qu'une sortie publiée l'affirme — le groupe 3 du corpus.
 *
 * ## À quoi ça sert
 *
 * Une sortie approuvée en modération est une étiquette gratuite : un humain a
 * lu chaque champ, fiche en main, avant de cliquer. On reprend donc ce qu'elle
 * affirme comme corpus de l'étage 6, sans redemander le travail à personne.
 *
 * ## Le piège, et comment il est tenu
 *
 * `extractScore` compare `EvalFiche.expected[clé]` à la valeur que la brique a
 * rendue — et cette valeur est **une chaîne mise en forme par Python**, dans
 * `evaluation.audit_fiche` : « gratuit », « dès 3 ans », « du 2026-09-20 au
 * 2026-09-22 ». Pour que la comparaison veuille dire quelque chose, ce module
 * doit produire exactement les mêmes chaînes.
 *
 * C'est une convention dupliquée entre deux langages, et c'est précisément ce
 * que j'évite ailleurs. Ici il n'y a pas de meilleure option sans réécrire un
 * banc qui marche : la mesure de l'étage 6 compare des chaînes à des chaînes,
 * par nature — c'est une reformulation qu'on juge, pas une donnée.
 *
 * Alors plutôt que de faire semblant que la duplication n'existe pas, elle est
 * **surveillée** : `fichePubliee.cas.json` porte des cas que les deux côtés
 * vérifient — un test Python contre `audit_fiche`, un test TypeScript contre
 * ce module. Si Python change sa mise en forme, un test casse bruyamment au
 * lieu que la mesure dérive en silence.
 *
 * ## Ce qu'on ne remplit pas
 *
 * `jours` reste **absent**, délibérément. La brique rend les jours de
 * représentation lus dans la prose (« tous les dimanches ») suivis des dates
 * annoncées ; le site, lui, ne reçoit que les dates — le pipeline se sert des
 * premiers pour fabriquer les secondes et les jette. Reconstituer `jours`
 * depuis une fiche publiée donnerait donc systématiquement une valeur amputée,
 * et chaque sortie à récurrence compterait « faux » sans que la brique ait
 * fauté.
 *
 * Une clé absente veut dire « personne n'a regardé ce champ », ce que le
 * corpus sait déjà exprimer, et c'est la vérité.
 */

/** Ce qu'une sortie publiée porte, réduit à ce que la fiche mesure. */
export interface SortiePubliee {
  title: string;
  description: string;
  isFree: boolean;
  /** En euros. `null` quand la sortie est gratuite ou sans tarif annoncé. */
  price: number | null;
  ageMin: number | null;
  ageMax: number | null;
  isPermanent: boolean;
  /** `YYYY-MM-DD`, ou vide. */
  dateStart: string;
  dateEnd: string;
  openTime: string;
  closeTime: string;
  /** `INDOOR`, `OUTDOOR`, `BOTH`, ou vide. */
  setting: string;
  category: string;
  venueName: string;
  venueAddress: string;
  venuePostalCode: string;
  venueCity: string;
}

/** Ce que `evaluation._SETTINGS` rend, et rien d'autre. */
const CADRES: Record<string, string> = {
  INDOOR: 'intérieur',
  OUTDOOR: 'extérieur',
  BOTH: 'les deux',
};

/**
 * Le `:g` de Python : la représentation la plus courte qui ne perde rien.
 * `8.0` donne « 8 », `8.50` donne « 8.5 ». Une virgule à la place du point
 * ferait lire « faux » sur chaque tarif.
 */
function nombre(value: number): string {
  return String(Number(value));
}

/** Les deux bornes réduites à leur jour, comme `_date_range`. */
function bornes(start: string, end: string): [string, string] {
  const debut = start.trim().slice(0, 10);
  return [debut, end.trim().slice(0, 10) || debut];
}

/**
 * Ce que la fiche publiée affirme, champ par champ, dans la forme où l'étage 6
 * sera comparé.
 *
 * Une valeur vide est une étiquette de plein droit — « la page n'en dit
 * rien » —, ce qui permet de reconnaître une valeur inventée. Seule `jours`
 * est absente, faute de pouvoir la reconstituer honnêtement.
 */
export function ficheAttendue(sortie: SortiePubliee): Record<string, string> {
  const [debut, fin] = bornes(sortie.dateStart, sortie.dateEnd);

  let tarif = '';
  if (sortie.isFree) tarif = 'gratuit';
  else if (sortie.price !== null) tarif = `${nombre(sortie.price)} €`;

  let age = '';
  if (sortie.ageMin !== null && sortie.ageMax !== null) age = `${sortie.ageMin} à ${sortie.ageMax} ans`;
  else if (sortie.ageMin !== null) age = `dès ${sortie.ageMin} ans`;
  else if (sortie.ageMax !== null) age = `jusqu'à ${sortie.ageMax} ans`;

  let plage = '';
  if (sortie.isPermanent) plage = "toute l'année";
  else if (debut && fin && fin !== debut) plage = `du ${debut} au ${fin}`;
  else if (debut) plage = `le ${debut}`;

  const horaires = [sortie.openTime, sortie.closeTime].filter(Boolean).join(' – ');
  const adresse = [sortie.venueAddress, sortie.venuePostalCode, sortie.venueCity]
    .filter(Boolean)
    .join(', ');

  return {
    // Une sortie publiée et approuvée est une sortie : c'est ce que
    // l'approbation dit, et c'est le seul verdict qu'elle puisse porter.
    verdict: 'une sortie',
    titre: sortie.title,
    description: sortie.description,
    tarif,
    age,
    dates: plage,
    horaires,
    cadre: CADRES[sortie.setting] ?? sortie.setting,
    categorie: sortie.category,
    lieu: sortie.venueName,
    adresse,
  };
}

/**
 * D'où vient chaque champ de l'étiquette.
 *
 * `CORRIGE` : un modérateur a réécrit ce champ avant d'approuver — une
 * étiquette indépendante du modèle. `NON_CONTREDIT` : le modèle l'a rendu, le
 * modérateur l'a laissé passer. `SAISIE` : quelqu'un l'a tapé dans la console.
 *
 * La mesure les traite à égalité : approuver, c'est avoir vérifié. Mais la
 * distinction est conservée, pour que cette hypothèse reste vérifiable — si un
 * jour le taux de correction s'effondre sur tous les champs, c'est qu'elle
 * aura vieilli, et on ne pourra le voir que si on l'a notée.
 */
export type Provenance = 'CORRIGE' | 'NON_CONTREDIT' | 'SAISIE';

/** Les champs de la fiche qu'un modérateur a réécrits, par clé d'aspect. */
export function provenances(
  attendue: Record<string, string>,
  corriges: Iterable<string>,
): Record<string, Provenance> {
  const changes = new Set(corriges);
  const out: Record<string, Provenance> = {};
  for (const cle of Object.keys(attendue)) {
    out[cle] = changes.has(cle) ? 'CORRIGE' : 'NON_CONTREDIT';
  }
  return out;
}
