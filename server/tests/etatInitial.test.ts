/**
 * L'accord entre les deux côtés de l'état initial.
 *
 * Le serveur écrit dans le document les réponses d'API qui correspondent à la
 * page demandée, rangées sous l'adresse de l'appel. L'application les reprend
 * si — et seulement si — elle reconnaît l'adresse qu'elle allait demander.
 *
 * Cet accord ne tient à rien d'autre qu'à deux chaînes construites dans deux
 * dépôts de fichiers différents. Une divergence ne casse pas le site : l'appel
 * part, comme avant. Elle rend juste le travail inutile, et sans bruit — le
 * genre de régression qu'on ne remarque que des mois plus tard, en retrouvant
 * dans la Search Console les pages qu'on croyait réparées. D'où ce test, qui
 * compare la chaîne du serveur à celle que le client fabrique vraiment.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { eventsApiPath } from '../src/seo/pages';
import { filtresVides, requeteApi } from '../../client/src/lib/searchQuery';

/**
 * L'adresse sous la forme que `client/src/lib/etatInitial.ts` compare :
 * chemin, puis paramètres triés — leur ordre ne veut rien dire.
 */
function cle(chemin: string): string {
  const url = new URL(chemin, 'https://sortiespourpetits.fr');
  const params = [...url.searchParams.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const query = new URLSearchParams(params).toString();
  return query ? `${url.pathname}?${query}` : url.pathname;
}

/** La taille de page, la même des deux côtés (`PAGE_SIZE`, `pageSize`). */
const PAGE_SIZE = 12;

for (const page of [1, 2, 7]) {
  test(`l'accueil page ${page} : le serveur écrit ce que la vue demande`, () => {
    // Ce que fait `HomeView` au premier affichage, sans filtre : l'adresse est
    // nue, donc les filtres sont vides.
    const demande = `/api/events?${requeteApi(filtresVides(), page, PAGE_SIZE)}`;
    assert.equal(cle(eventsApiPath(page, PAGE_SIZE)), cle(demande));
  });
}

test('une recherche filtrée ne reconnaît pas l’état de l’accueil', () => {
  // Et c'est voulu : le pré-rendu ignore les filtres (voir `searchQuery.ts`),
  // donc il n'a pas la réponse à cette question-là. L'appel doit partir.
  const filtres = { ...filtresVides(), q: 'poterie' };
  const demande = `/api/events?${requeteApi(filtres, 1, PAGE_SIZE)}`;
  assert.notEqual(cle(eventsApiPath(1, PAGE_SIZE)), cle(demande));
});

test('la page d’une zone : le serveur écrit ce que la vue demande', () => {
  // `AreaView` construit sa requête à la main — recopiée ici à l'identique.
  const params = new URLSearchParams({
    area: 'nancy',
    page: String(2),
    pageSize: String(PAGE_SIZE),
  });
  assert.equal(
    cle(eventsApiPath(2, PAGE_SIZE, 'nancy')),
    cle(`/api/events?${params.toString()}`),
  );
});

test("l'ordre des paramètres n'entre pas en ligne de compte", () => {
  assert.equal(cle('/api/events?pageSize=12&page=1'), cle('/api/events?page=1&pageSize=12'));
});
