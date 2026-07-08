/**
 * Géocodage — deux fournisseurs disponibles, sélection via PROVIDER ci-dessous.
 * - "ban": API Adresse (Base Adresse Nationale) — gratuite, sans clé, adresses uniquement.
 *   https://adresse.data.gouv.fr/api-doc/adresse
 * - "photon": Photon (OpenStreetMap, via komoot) — gratuit, sans clé, inclut aussi les
 *   lieux d'intérêt (parcs, musées, aires de jeux...). Instance publique en "fair use",
 *   à self-host si le trafic devient important. https://photon.komoot.io
 */
const PROVIDER: 'ban' | 'photon' = 'photon';

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
