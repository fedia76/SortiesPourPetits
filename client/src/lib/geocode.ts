/**
 * Géocodage via l'API Adresse (Base Adresse Nationale) — gratuite, sans clé.
 * https://adresse.data.gouv.fr/api-doc/adresse
 */
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

export async function searchAddress(query: string): Promise<GeoSuggestion[]> {
  if (query.trim().length < 3) return [];
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
