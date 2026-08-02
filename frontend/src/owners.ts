import { ActiveHighlight, LayerId } from './types/gis';

// Where "owner" lives per layer — differs by field name and shape
// (scalar string vs. a list, for substations' inferred nearby_line_owners).
// industrial-convergence has no owner concept and is deliberately omitted.
const SCALAR_OWNER_FIELD: Partial<Record<LayerId, string>> = {
  'power-grid': 'owner',
  'power-plants': 'owner',
  'auto-plants': 'oem_or_parent',
};

const INVALID_OWNER_VALUES = new Set(['NOT AVAILABLE', 'Unknown', '']);

// The distinct owner string(s) a feature belongs to, regardless of which
// layer it's in or whether that layer stores owner as a scalar or a list.
export function getFeatureOwners(layerId: LayerId, properties: any): string[] {
  if (layerId === 'substations') {
    const owners = properties?.nearby_line_owners;
    return Array.isArray(owners) ? owners.filter((o) => o && !INVALID_OWNER_VALUES.has(o)) : [];
  }
  const field = SCALAR_OWNER_FIELD[layerId];
  if (!field) return [];
  const value = properties?.[field];
  return value && !INVALID_OWNER_VALUES.has(value) ? [value] : [];
}

export function featureMatchesOwnerQuery(layerId: LayerId, properties: any, query: string): boolean {
  if (!query.trim()) return true;
  const needle = query.trim().toLowerCase();
  return getFeatureOwners(layerId, properties).some((owner) => owner.toLowerCase().includes(needle));
}

// Every distinct owner string across every layer's already-fetched dataset,
// for the search box's autocomplete — computed client-side since all layer
// data is already loaded in the browser (see useGISData.ts), no extra
// backend round-trip needed.
export function collectDistinctOwners(datasets: Record<string, any>): string[] {
  const seen = new Set<string>();
  (Object.keys(datasets) as LayerId[]).forEach((layerId) => {
    const features = datasets[layerId]?.features ?? [];
    for (const feature of features) {
      for (const owner of getFeatureOwners(layerId, feature.properties)) {
        seen.add(owner);
      }
    }
  });
  return Array.from(seen).sort((a, b) => a.localeCompare(b));
}

export function createOwnerHighlight(query: string): ActiveHighlight | null {
  if (!query.trim()) return null;
  return { isMatch: (layerId, properties) => featureMatchesOwnerQuery(layerId, properties, query) };
}

export function countMatchesByLayer(
  datasets: Record<string, any>,
  query: string
): Partial<Record<LayerId, number>> {
  const counts: Partial<Record<LayerId, number>> = {};
  (Object.keys(datasets) as LayerId[]).forEach((layerId) => {
    const features = datasets[layerId]?.features ?? [];
    const count = features.filter((f: any) => featureMatchesOwnerQuery(layerId, f.properties, query)).length;
    if (count > 0) counts[layerId] = count;
  });
  return counts;
}
