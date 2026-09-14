/**
 * La recherche de l'accueil, telle qu'elle s'écrit dans l'adresse.
 *
 * **Toute** la recherche y vit — la page et les filtres. La page s'y trouvait
 * déjà, et pour une raison qui vaut mot pour mot pour le reste : un robot ouvre
 * l'accueil, y lit douze liens, et n'a aucun moyen d'atteindre les suivants si
 * « page 2 » n'est qu'un bouton. Les filtres, eux, étaient restés dans la
 * mémoire du composant — donc une recherche ne se partageait pas, ne se mettait
 * pas en favori, et le bouton Retour du navigateur la perdait au lieu de la
 * défaire.
 *
 * Contrepartie assumée : le serveur ne pré-rend que la page, pas les filtres
 * (voir `server/src/seo/pages.ts`, dont la clé de cache ne retient que `page`).
 * Une adresse filtrée reçoit donc d'abord le catalogue entier, que Vue remplace
 * une seconde plus tard. C'est déjà ce qui arrivait aux paramètres de campagne,
 * et l'adresse canonique reste `/` : un moteur n'a pas deux pages à départager.
 *
 * ## Pourquoi ce fichier n'est pas dans la vue
 *
 * Parce que c'est la seule partie de l'accueil qui **décide** quelque chose, et
 * que l'aller-retour entre une adresse et un formulaire est exactement le genre
 * de code où une faute ne se voit pas : un paramètre oublié à l'écriture ne
 * casse rien, il fait juste disparaître un filtre au rechargement.
 */
import type { Setting } from '../types';

/** Rayon proposé par défaut, en kilomètres. */
export const RADIUS_DEFAUT = 10;

/**
 * Les filtres du formulaire.
 *
 * Les champs de saisie rendent des chaînes, y compris pour les nombres, et
 * « rien » s'y écrit `''` : les types le disent plutôt que de faire semblant.
 */
export interface Filtres {
  q: string;
  free: boolean;
  priceMax: string | number;
  age: string | number;
  from: string;
  to: string;
  setting: '' | Setting;
  categoryId: '' | number;
  /** Ce que le visiteur a tapé, pour le réafficher. Les coordonnées, elles, ne se relisent pas. */
  address: string;
  lat: number | null;
  lng: number | null;
  radiusKm: number;
}

/** Ce qu'un routeur rend pour `?a=1&b=2&b=3`. */
export type Query = Record<string, string | null | (string | null)[] | undefined>;

export function filtresVides(): Filtres {
  return {
    q: '',
    free: false,
    priceMax: '',
    age: '',
    from: '',
    to: '',
    setting: '',
    categoryId: '',
    address: '',
    lat: null,
    lng: null,
    radiusKm: RADIUS_DEFAUT,
  };
}

/**
 * La première valeur d'un paramètre, ou une chaîne vide.
 *
 * `?q=a&q=b` rend un tableau : on prend la première plutôt que d'afficher
 * « a,b » dans le champ de recherche.
 */
function param(query: Query, cle: string): string {
  const brut = query[cle];
  const valeur = Array.isArray(brut) ? brut[0] : brut;
  return typeof valeur === 'string' ? valeur : '';
}

/** Un nombre lu dans l'adresse, ou `null` si ce n'en est pas un. */
function nombre(query: Query, cle: string): number | null {
  const texte = param(query, cle);
  if (!texte) return null;
  const valeur = Number(texte);
  return Number.isFinite(valeur) ? valeur : null;
}

/**
 * La page demandée. Un numéro absurde ramène à la première plutôt qu'à une
 * page vide : une adresse tapée à la main ne doit pas donner un cul-de-sac.
 */
export function pageDepuisQuery(query: Query): number {
  const page = nombre(query, 'page');
  return page !== null && Number.isInteger(page) && page >= 1 ? page : 1;
}

/**
 * L'adresse, recopiée dans les filtres affichés.
 *
 * C'est l'adresse qui commande, jamais l'inverse : un retour arrière, un lien
 * partagé ou un lien suivi depuis la page pré-rendue la changent sans passer
 * par le formulaire, et le formulaire doit alors dire ce qu'elle dit.
 */
export function filtresDepuisQuery(query: Query): Filtres {
  const categorie = nombre(query, 'categoryId');
  const lat = nombre(query, 'lat');
  const lng = nombre(query, 'lng');
  return {
    q: param(query, 'q'),
    free: param(query, 'free') === 'true',
    priceMax: param(query, 'priceMax'),
    age: param(query, 'age'),
    from: param(query, 'from'),
    to: param(query, 'to'),
    setting: (param(query, 'setting') || '') as '' | Setting,
    categoryId: categorie ?? '',
    // Une position n'a de sens qu'entière : une latitude sans longitude ne
    // décrit aucun point, et le serveur refuserait la recherche.
    address: lat !== null && lng !== null ? param(query, 'adresse') : '',
    lat: lng === null ? null : lat,
    lng: lat === null ? null : lng,
    radiusKm: nombre(query, 'radiusKm') ?? RADIUS_DEFAUT,
  };
}

/**
 * L'adresse qui décrit ces filtres.
 *
 * Ce qui vaut sa valeur par défaut n'y figure pas : une adresse qui énumère
 * douze paramètres vides ne se partage pas, et le rayon d'une recherche sans
 * position ne veut rien dire.
 */
export function queryDepuisFiltres(f: Filtres, page: number): Record<string, string> {
  const query: Record<string, string> = {};
  if (f.q) query.q = f.q;
  // « Gratuit » et « prix maximum » se contredisent : le serveur ignore le
  // second quand le premier est coché, autant ne pas l'écrire.
  if (f.free) query.free = 'true';
  else if (f.priceMax !== '') query.priceMax = String(f.priceMax);
  if (f.age !== '') query.age = String(f.age);
  if (f.from) query.from = f.from;
  if (f.to) query.to = f.to;
  if (f.setting) query.setting = f.setting;
  if (f.categoryId !== '') query.categoryId = String(f.categoryId);
  if (f.lat !== null && f.lng !== null) {
    query.lat = String(f.lat);
    query.lng = String(f.lng);
    query.radiusKm = String(f.radiusKm);
    if (f.address) query.adresse = f.address;
  }
  if (page > 1) query.page = String(page);
  return query;
}

/**
 * Ce que l'API attend, pour ces filtres et cette page.
 *
 * Très proche de `queryDepuisFiltres`, et pourtant distinct : l'adresse est
 * faite pour être lue et partagée — d'où `adresse`, que l'API ignore — et la
 * requête porte en plus la taille de page.
 */
export function requeteApi(f: Filtres, page: number, pageSize: number): string {
  const params = new URLSearchParams(queryDepuisFiltres(f, page));
  params.delete('adresse');
  params.delete('page');
  params.set('page', String(page));
  params.set('pageSize', String(pageSize));
  return params.toString();
}
