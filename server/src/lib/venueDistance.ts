/**
 * « Quels lieux sont à moins de N kilomètres d'ici, et à quelle distance ? »
 *
 * La question est posée à deux endroits — la recherche publique et la détection
 * de doublons — et la requête y était recopiée à l'identique, Haversine
 * compris. Elle vit ici, une fois.
 *
 * ## L'encadrement, et pourquoi il n'était pas optionnel
 *
 * Haversine est une formule sur des colonnes : aucun index ne s'y applique, et
 * `HAVING distanceKm <= …` ne peut trancher qu'après l'avoir calculée. La
 * requête lisait donc **toute la table `Venue`** — sinus, cosinus et racine sur
 * chaque ligne — à chaque recherche par distance d'un visiteur. Le schéma porte
 * pourtant un `@@index([lat, lng])` depuis le début, et `moderation.ts` notait
 * en passant qu'il « n'aide pas ici ». Il n'aidait pas parce que rien ne lui
 * donnait de quoi mordre.
 *
 * On lui en donne : un rectangle autour du point, calculé avant la requête, qui
 * réduit les lignes à examiner à ce qui peut raisonnablement être dans le
 * rayon. Haversine tranche ensuite, sur ce reste, et le résultat est le même au
 * mètre près — le rectangle est circonscrit au cercle, donc il ne peut que
 * garder trop, jamais trop peu.
 */
import { Prisma } from '@prisma/client';

/** Un lieu et sa distance au point demandé. */
export interface VenueDistance {
  id: number;
  distanceKm: number;
}

/** Rayon moyen de la Terre, en kilomètres. Le même que dans la formule. */
const EARTH_RADIUS_KM = 6371;

/**
 * Kilomètres par degré de latitude. Constant : un méridien fait 40 008 km,
 * divisés par 360.
 */
const KM_PER_DEGREE_LAT = 111.32;

/**
 * Le rectangle qui contient à coup sûr le cercle de rayon `radiusKm`.
 *
 * En longitude, un degré vaut d'autant moins de kilomètres qu'on s'éloigne de
 * l'équateur — d'où le cosinus. Deux cas y échappent, et ils sont rendus
 * **sans borne de longitude** plutôt qu'avec une borne fausse :
 *
 * * tout près des pôles, où le cosinus tend vers zéro et où l'encadrement
 *   exploserait ;
 * * à cheval sur l'antiméridien, où le rectangle se couperait en deux et où un
 *   `BETWEEN` désignerait exactement le complément de ce qu'on cherche.
 *
 * Dans ces deux cas la latitude borne encore, et Haversine fait le reste : on
 * perd de la sélectivité, jamais de la justesse.
 */
export function boundingBox(
  lat: number,
  lng: number,
  radiusKm: number,
): { latMin: number; latMax: number; lngMin: number; lngMax: number } | null {
  const deltaLat = radiusKm / KM_PER_DEGREE_LAT;
  const latMin = lat - deltaLat;
  const latMax = lat + deltaLat;

  const cos = Math.cos((lat * Math.PI) / 180);
  if (Math.abs(cos) < 0.01) return null;

  const deltaLng = radiusKm / (KM_PER_DEGREE_LAT * cos);
  const lngMin = lng - deltaLng;
  const lngMax = lng + deltaLng;
  if (lngMin < -180 || lngMax > 180) return null;

  return { latMin, latMax, lngMin, lngMax };
}

/**
 * La requête des lieux dans le rayon, distance comprise.
 *
 * Haversine en SQL pur : compatible MySQL comme MariaDB, là où
 * `ST_Distance_Sphere` ne l'est pas partout.
 */
export function venuesWithinQuery(lat: number, lng: number, radiusKm: number): Prisma.Sql {
  const deltaLat = radiusKm / KM_PER_DEGREE_LAT;
  const box = boundingBox(lat, lng, radiusKm);
  const cadre = box
    ? Prisma.sql`lat BETWEEN ${box.latMin} AND ${box.latMax}
        AND lng BETWEEN ${box.lngMin} AND ${box.lngMax}`
    : Prisma.sql`lat BETWEEN ${lat - deltaLat} AND ${lat + deltaLat}`;

  return Prisma.sql`
    SELECT id,
      ${EARTH_RADIUS_KM} * 2 * ASIN(SQRT(
        POWER(SIN(RADIANS(lat - ${lat}) / 2), 2) +
        COS(RADIANS(${lat})) * COS(RADIANS(lat)) *
        POWER(SIN(RADIANS(lng - ${lng}) / 2), 2)
      )) AS distanceKm
    FROM Venue
    WHERE ${cadre}
    HAVING distanceKm <= ${radiusKm}
  `;
}

/** Ce que la base a rendu, prêt à être interrogé par identifiant de lieu. */
export function distanceByVenueId(rows: VenueDistance[]): Map<number, number> {
  return new Map(rows.map((r) => [r.id, Number(r.distanceKm)]));
}
