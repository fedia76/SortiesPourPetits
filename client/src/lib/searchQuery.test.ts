/**
 * L'aller-retour entre une adresse et le formulaire de recherche.
 *
 * C'est le genre de code où une faute ne se voit pas : un paramètre oublié à
 * l'écriture ne casse rien, il fait juste disparaître un filtre au
 * rechargement — et personne ne s'en aperçoit avant de partager un lien qui ne
 * cherche pas ce qu'il annonce.
 *
 * D'où la propriété centrale, testée sur une douzaine de recherches : **écrire
 * puis relire rend les filtres de départ**. Le reste vérifie ce que
 * l'aller-retour ne peut pas dire — qu'une adresse tapée à la main ne fait
 * jamais tomber la page.
 */
import { describe, expect, test } from 'vitest';

import {
  RADIUS_DEFAUT,
  filtresDepuisQuery,
  filtresVides,
  pageDepuisQuery,
  queryDepuisFiltres,
  requeteApi,
  type Filtres,
} from './searchQuery';

/** Les filtres vides, avec ce que ce cas-ci change. */
function filtres(champs: Partial<Filtres> = {}): Filtres {
  return { ...filtresVides(), ...champs };
}

const RECHERCHES: [string, Filtres][] = [
  ['aucun filtre', filtres()],
  ['du texte', filtres({ q: 'marionnettes' })],
  ['du texte avec des accents et une apostrophe', filtres({ q: "l'été à Sénart" })],
  ['gratuit', filtres({ free: true })],
  ['un prix maximum', filtres({ priceMax: '12' })],
  ['un âge', filtres({ age: '4' })],
  ['une période', filtres({ from: '2026-10-01', to: '2026-10-31' })],
  ['un cadre', filtres({ setting: 'INDOOR' })],
  ['une catégorie', filtres({ categoryId: 3 })],
  [
    'une position',
    filtres({ lat: 49.4944, lng: 0.1079, radiusKm: 25, address: 'Le Havre' }),
  ],
  [
    'tout à la fois',
    filtres({
      q: 'cirque',
      priceMax: '8',
      age: '6',
      from: '2026-11-01',
      to: '2026-11-30',
      setting: 'BOTH',
      categoryId: 2,
      lat: 48.6937,
      lng: 6.1834,
      radiusKm: 15,
      address: 'Nancy',
    }),
  ],
];

describe('écrire puis relire rend la même recherche', () => {
  for (const [quoi, attendus] of RECHERCHES) {
    test(quoi, () => {
      expect(filtresDepuisQuery(queryDepuisFiltres(attendus, 1))).toEqual(attendus);
    });
  }

  test('la page aussi fait l’aller-retour', () => {
    for (const page of [1, 2, 17]) {
      expect(pageDepuisQuery(queryDepuisFiltres(filtres({ q: 'x' }), page))).toBe(page);
    }
  });
});

describe('l’adresse ne porte que ce qui a été demandé', () => {
  test('une recherche vide donne une adresse vide', () => {
    expect(queryDepuisFiltres(filtres(), 1)).toEqual({});
  });

  test('la première page ne se numérote pas', () => {
    expect(queryDepuisFiltres(filtres(), 1).page).toBeUndefined();
    expect(queryDepuisFiltres(filtres(), 2).page).toBe('2');
  });

  test('le rayon n’apparaît pas sans position', () => {
    const query = queryDepuisFiltres(filtres({ radiusKm: 42 }), 1);
    expect(query.radiusKm).toBeUndefined();
    expect(query.lat).toBeUndefined();
  });

  test('« gratuit » chasse le prix maximum, qu’il contredit', () => {
    // Le serveur ignore `priceMax` quand `free` est vrai : écrire les deux
    // ferait une adresse qui annonce autre chose que ce qu'elle cherche.
    const query = queryDepuisFiltres(filtres({ free: true, priceMax: '12' }), 1);
    expect(query.free).toBe('true');
    expect(query.priceMax).toBeUndefined();
  });

  test('l’adresse tapée ne suit que la position qu’elle a servi à trouver', () => {
    const query = queryDepuisFiltres(filtres({ address: 'Le Havre' }), 1);
    expect(query.adresse).toBeUndefined();
  });
});

describe('une adresse écrite à la main ne fait pas tomber la page', () => {
  test('une page absurde ramène à la première', () => {
    for (const page of ['0', '-3', 'deux', '1.5', '', 'Infinity']) {
      expect(pageDepuisQuery({ page })).toBe(1);
    }
    expect(pageDepuisQuery({})).toBe(1);
  });

  test('un nombre illisible retombe sur la valeur par défaut', () => {
    const lus = filtresDepuisQuery({ categoryId: 'abc', radiusKm: 'loin', lat: 'ici' });
    expect(lus.categoryId).toBe('');
    expect(lus.radiusKm).toBe(RADIUS_DEFAUT);
    expect(lus.lat).toBeNull();
  });

  test('une latitude sans longitude ne décrit aucun point', () => {
    // Le serveur refuse la recherche si les trois ne sont pas là : mieux vaut
    // ignorer la moitié d'une position que chercher autour de rien.
    expect(filtresDepuisQuery({ lat: '49.49' }).lat).toBeNull();
    expect(filtresDepuisQuery({ lng: '0.1' }).lng).toBeNull();
    const entiere = filtresDepuisQuery({ lat: '49.49', lng: '0.1' });
    expect(entiere.lat).toBe(49.49);
    expect(entiere.lng).toBe(0.1);
  });

  test('un paramètre répété se lit une fois', () => {
    // `?q=a&q=b` rend un tableau : afficher « a,b » dans le champ de recherche
    // n'aiderait personne.
    expect(filtresDepuisQuery({ q: ['chien', 'chat'] }).q).toBe('chien');
  });

  test('un paramètre inconnu est ignoré sans bruit', () => {
    // Les paramètres de campagne arrivent par là, et ils sont nombreux.
    expect(filtresDepuisQuery({ utm_source: 'facebook' })).toEqual(filtres());
  });

  test('un cadre inventé ne se propage pas en filtre', () => {
    // Il traverse — le serveur tranchera en 400 — mais il ne doit pas casser
    // la lecture du reste.
    const lus = filtresDepuisQuery({ setting: 'SOUS_LEAU', q: 'plongée' });
    expect(lus.q).toBe('plongée');
  });
});

describe('la requête envoyée à l’API', () => {
  test('porte la page et sa taille, toujours', () => {
    const params = new URLSearchParams(requeteApi(filtres(), 1, 12));
    expect(params.get('page')).toBe('1');
    expect(params.get('pageSize')).toBe('12');
  });

  test('n’envoie pas l’adresse tapée, que l’API ne connaît pas', () => {
    const f = filtres({ lat: 49.49, lng: 0.1, address: 'Le Havre' });
    const params = new URLSearchParams(requeteApi(f, 1, 12));
    expect(params.get('adresse')).toBeNull();
    expect(params.get('lat')).toBe('49.49');
    expect(params.get('radiusKm')).toBe(String(RADIUS_DEFAUT));
  });

  test('demande la page affichée, pas la première', () => {
    const params = new URLSearchParams(requeteApi(filtres({ q: 'x' }), 3, 12));
    expect(params.get('page')).toBe('3');
    expect(params.get('q')).toBe('x');
  });

  test('n’envoie que les filtres renseignés', () => {
    const params = new URLSearchParams(requeteApi(filtres(), 1, 12));
    expect([...params.keys()].sort()).toEqual(['page', 'pageSize']);
  });
});
