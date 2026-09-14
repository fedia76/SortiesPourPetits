/**
 * L'encadrement qui précède le calcul de distance.
 *
 * Haversine est une formule sur des colonnes : aucun index ne s'y applique, et
 * la requête lisait donc toute la table `Venue` — sinus, cosinus et racine sur
 * chaque ligne — à chaque recherche par distance d'un visiteur. Le rectangle
 * calculé ici rend l'index `[lat, lng]` utile.
 *
 * Ce qu'il faut vérifier tient en une phrase : **il ne doit jamais écarter un
 * lieu qui est dans le rayon**. Trop large est sans conséquence, Haversine
 * tranche derrière ; trop étroit fait disparaître des sorties sans que rien ne
 * le dise.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { boundingBox, distanceByVenueId, venuesWithinQuery } from '../src/lib/venueDistance';

/** Haversine, en TypeScript cette fois : la référence contre laquelle on juge. */
function distanceKm(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(bLat - aLat);
  const dLng = rad(bLng - aLng);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(rad(aLat)) * Math.cos(rad(bLat)) * Math.sin(dLng / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(h));
}

const PARIS = { lat: 48.8566, lng: 2.3522 };
const LE_HAVRE = { lat: 49.4944, lng: 0.1079 };

test('le rectangle contient le cercle, dans les quatre directions', () => {
  const box = boundingBox(PARIS.lat, PARIS.lng, 10);
  assert.ok(box);

  // Les quatre points du cercle, aux quatre points cardinaux exacts.
  const nord = PARIS.lat + 10 / 111.32;
  const sud = PARIS.lat - 10 / 111.32;
  const est = PARIS.lng + 10 / (111.32 * Math.cos((PARIS.lat * Math.PI) / 180));
  const ouest = PARIS.lng - 10 / (111.32 * Math.cos((PARIS.lat * Math.PI) / 180));

  assert.ok(box.latMax >= nord && box.latMin <= sud);
  assert.ok(box.lngMax >= est && box.lngMin <= ouest);
});

test('aucun point du rayon ne tombe hors du rectangle', () => {
  // Balayage du cercle, dans toutes les directions et à plusieurs rayons : le
  // seul défaut qui compte est un lieu du rayon que l'encadrement écarterait.
  for (const rayon of [0.5, 5, 50, 300]) {
    const box = boundingBox(LE_HAVRE.lat, LE_HAVRE.lng, rayon);
    assert.ok(box, `rayon ${rayon}`);
    for (let angle = 0; angle < 360; angle += 5) {
      const rad = (angle * Math.PI) / 180;
      // Un point à `rayon` km dans cette direction.
      const lat = LE_HAVRE.lat + (rayon * Math.cos(rad)) / 111.32;
      const lng =
        LE_HAVRE.lng +
        (rayon * Math.sin(rad)) / (111.32 * Math.cos((LE_HAVRE.lat * Math.PI) / 180));

      // On ne juge que ce qui est réellement dans le rayon : l'approximation
      // du point de test lui-même n'a pas à être mise sur le dos du cadre.
      if (distanceKm(LE_HAVRE.lat, LE_HAVRE.lng, lat, lng) > rayon) continue;
      assert.ok(
        lat >= box.latMin && lat <= box.latMax && lng >= box.lngMin && lng <= box.lngMax,
        `rayon ${rayon}, angle ${angle} : (${lat}, ${lng}) hors du cadre`,
      );
    }
  }
});

test('le rectangle reste serré : il ne rend pas l’encadrement inutile', () => {
  // Un cadre correct mais démesuré ne servirait à rien. Pour 10 km autour de
  // Paris, il doit rester de l'ordre du dixième de degré.
  const box = boundingBox(PARIS.lat, PARIS.lng, 10);
  assert.ok(box);
  assert.ok(box.latMax - box.latMin < 0.25);
  assert.ok(box.lngMax - box.lngMin < 0.35);
});

test('près des pôles, on renonce à borner la longitude plutôt que de la borner faux', () => {
  // Le cosinus tend vers zéro : l'encadrement exploserait, ou pire, se
  // tromperait. La latitude borne encore, Haversine fait le reste.
  assert.equal(boundingBox(89.99, 0, 10), null);
  assert.equal(boundingBox(-89.999, 0, 10), null);
});

test('à cheval sur l’antiméridien, on renonce aussi', () => {
  // Un `BETWEEN` y désignerait exactement le complément de ce qu'on cherche :
  // tout le globe **sauf** le voisinage du point.
  assert.equal(boundingBox(-13.3, 176.2, 600), null, 'Wallis-et-Futuna, rayon large');
  assert.equal(boundingBox(0, -179.9, 50), null);
  // Loin des bords, le cadre existe.
  assert.ok(boundingBox(-13.3, 176.2, 5));
});

test('un rayon minuscule donne un cadre minuscule, pas un cadre nul', () => {
  const box = boundingBox(PARIS.lat, PARIS.lng, 0.1);
  assert.ok(box);
  assert.ok(box.latMax > box.latMin && box.lngMax > box.lngMin);
});

// ─────────────────────────────────────────────────────────────── la requête

test('la requête encadre, puis calcule, puis tranche', () => {
  const sql = venuesWithinQuery(PARIS.lat, PARIS.lng, 10);
  assert.match(sql.sql, /FROM Venue/);
  assert.match(sql.sql, /WHERE lat BETWEEN/, 'le cadre doit précéder le calcul');
  assert.match(sql.sql, /HAVING distanceKm <=/);
  // Aucune valeur interpolée dans le texte : tout passe en paramètre.
  assert.ok(!sql.sql.includes('48.8566'));
  assert.ok(sql.values.includes(PARIS.lat));
  assert.ok(sql.values.includes(10));
});

test('sans cadre de longitude, la latitude borne quand même', () => {
  const sql = venuesWithinQuery(89.99, 0, 10);
  assert.match(sql.sql, /WHERE lat BETWEEN/);
  assert.ok(!sql.sql.includes('lng BETWEEN'));
});

test('les distances se relisent par identifiant de lieu', () => {
  const parLieu = distanceByVenueId([
    { id: 3, distanceKm: 1.25 },
    { id: 7, distanceKm: 0 },
  ]);
  assert.equal(parLieu.get(3), 1.25);
  assert.equal(parLieu.get(7), 0);
  assert.equal(parLieu.get(99), undefined);
});
