import { ActiveHighlight, LayerId } from './types/gis';

// Generic counterpart to owners.ts's owner-search helpers, for investigative
// modes where the searchable value is just a single scalar property per
// layer (no substations-style list-of-owners special case to handle).
export interface AttributeSearchConfig {
  /** Layer -> property key holding the searchable value. Layers omitted
   * here have no matching concept for this mode (e.g. transmission lines
   * have no `state` field) and are skipped, same as owners.ts does for
   * industrial-convergence. */
  fieldByLayer: Partial<Record<LayerId, string>>;
  invalidValues?: Set<string>;
}

function getFeatureAttributeValue(config: AttributeSearchConfig, layerId: LayerId, properties: any): string | null {
  const field = config.fieldByLayer[layerId];
  if (!field) return null;
  const value = properties?.[field];
  if (!value || config.invalidValues?.has(value)) return null;
  return value;
}

export function featureMatchesAttributeQuery(
  config: AttributeSearchConfig,
  layerId: LayerId,
  properties: any,
  query: string
): boolean {
  if (!query.trim()) return true;
  const value = getFeatureAttributeValue(config, layerId, properties);
  return value ? value.toLowerCase().includes(query.trim().toLowerCase()) : false;
}

// Every distinct value across every layer's already-fetched dataset, for
// the search box's autocomplete — see owners.ts's collectDistinctOwners.
export function collectDistinctAttributeValues(config: AttributeSearchConfig, datasets: Record<string, any>): string[] {
  const seen = new Set<string>();
  (Object.keys(datasets) as LayerId[]).forEach((layerId) => {
    const features = datasets[layerId]?.features ?? [];
    for (const feature of features) {
      const value = getFeatureAttributeValue(config, layerId, feature.properties);
      if (value) seen.add(value);
    }
  });
  return Array.from(seen).sort((a, b) => a.localeCompare(b));
}

export function createAttributeHighlight(config: AttributeSearchConfig, query: string): ActiveHighlight | null {
  if (!query.trim()) return null;
  return {
    isMatch: (layerId, properties) => featureMatchesAttributeQuery(config, layerId, properties, query),
    // No exemptions — dims everything but direct matches, same as owner search.
  };
}

export function countAttributeMatchesByLayer(
  config: AttributeSearchConfig,
  datasets: Record<string, any>,
  query: string
): Partial<Record<LayerId, number>> {
  const counts: Partial<Record<LayerId, number>> = {};
  (Object.keys(datasets) as LayerId[]).forEach((layerId) => {
    const features = datasets[layerId]?.features ?? [];
    const count = features.filter((f: any) => featureMatchesAttributeQuery(config, layerId, f.properties, query)).length;
    if (count > 0) counts[layerId] = count;
  });
  return counts;
}

// subregion_name is the only NERC-related field common to every layer —
// points/lines are tagged with it at ingest time (tag_points_with_nerc_
// subregion / power_grid's from_node_id lookup), and nerc_subregions itself
// carries it as its own identity, so matching also highlights the
// corresponding background polygon. There's no separate top-level
// nerc_region field on points/lines to search by (see gis.ts).
export const NERC_REGION_SEARCH: AttributeSearchConfig = {
  fieldByLayer: {
    'power-grid': 'subregion_name',
    'power-plants': 'subregion_name',
    substations: 'subregion_name',
    'auto-plants': 'subregion_name',
    'nerc-subregions': 'subregion_name',
  },
};

// Transmission lines can span multiple states and nerc_subregions has no
// state concept at all, so both are omitted here (same pattern as owners.ts
// omitting industrial-convergence).
export const STATE_SEARCH: AttributeSearchConfig = {
  fieldByLayer: {
    'power-plants': 'state',
    substations: 'state',
    'auto-plants': 'state',
  },
  invalidValues: new Set(['NOT AVAILABLE', 'Unknown', '']),
};
