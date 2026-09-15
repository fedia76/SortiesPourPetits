/**
 * Géocodage du formulaire — deux fournisseurs, et le même défaut que le
 * scraper (`sortiesbot/geocode.py`), pour que les positions saisies à la main
 * et celles d'un import viennent de la même source.
 *
 * - **photon** (défaut) : Photon, sur OpenStreetMap, via komoot. Gratuit, sans
 *   clé, et il connaît les **lieux d'intérêt** — parcs, musées, aires de jeux —
 *   ce qui compte ici : on saisit « Théâtre de Vanves » plus souvent qu'une
 *   adresse postale. Son instance publique est en « fair use », et se
 *   self-héberge si le trafic le demande. https://photon.komoot.io
 * - **ban** : l'API Adresse (Base Adresse Nationale). Adresses uniquement,
 *   mais publique, sans quota et sans conditions.
 *   https://adresse.data.gouv.fr/api-doc/adresse
 *
 * Le choix se fait au **build**, par `VITE_GEOCODER=ban`. Il était écrit en dur
 * ici, alors que le README l'annonçait comme sélectionnable : en changer
 * demandait d'éditer ce fichier et de redéployer, ce qui n'est pas ce que « on
 * peut choisir » veut dire pour la personne qui lit le README un soir
 * d'incident.
 */
const PROVIDER: 'ban' | 'photon' =
  import.meta.env.VITE_GEOCODER === 'ban' ? 'ban' : 'photon';

export interface GeoSuggestion {
  label: string;
  name: string;
  city: string;
  postcode: string;
  lat: number;
  lng: number;
}

interface BanFeature {
  properties: { label: string; name: string; city: string; postcode: string };
  geometry: { coordinates: [number, number] };
}

interface PhotonFeature {
  properties: {
    name?: string;
    city?: string;
    postcode?: string;
    street?: string;
    housenumber?: string;
  };
  geometry: { coordinates: [number, number] };
}

async function searchAddressBan(query: string): Promise<GeoSuggestion[]> {
  const url = `https://api-adresse.data.gouv.fr/search/?q=${encodeURIComponent(query)}&limit=5`;
  const res = await fetch(url);
  if (!res.ok) return [];
  const body = (await res.json()) as { features: BanFeature[] };
  return body.features.map((f) => ({
    label: f.properties.label,
    name: f.properties.name,
    city: f.properties.city,
    postcode: f.properties.postcode,
    lng: f.geometry.coordinates[0],
    lat: f.geometry.coordinates[1],
  }));
}

async function searchAddressPhoton(query: string): Promise<GeoSuggestion[]> {
  const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(query)}&limit=5&lang=fr`;
  const res = await fetch(url);
  if (!res.ok) return [];
  const body = (await res.json()) as { features: PhotonFeature[] };
  return body.features.map((f) => {
    const { name, city, postcode, street, housenumber } = f.properties;
    const streetPart = [housenumber, street].filter(Boolean).join(' ');
    const displayName = name || streetPart;
    return {
      label: [displayName, postcode, city].filter(Boolean).join(', '),
      name: displayName,
      city: city ?? '',
      postcode: postcode ?? '',
      lng: f.geometry.coordinates[0],
      lat: f.geometry.coordinates[1],
    };
  });
}

export async function searchAddress(query: string): Promise<GeoSuggestion[]> {
  if (query.trim().length < 3) return [];
  return PROVIDER === 'photon' ? searchAddressPhoton(query) : searchAddressBan(query);
}
