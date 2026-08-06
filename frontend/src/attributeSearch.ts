import { ActiveHighlight, LayerId } from './types/gis';

// Generic counterpart to owners.ts's owner-search helpers, for investigative
// modes where the searchable value is just a single scalar property per
// layer (no substations-style list-of-owners special case to handle).
export interface AttributeSearchConfig {
  /** Layer -> property key holding the searchable value. Layers omitted
   * here have no matching concept for this mode (e.g. nerc_subregions
   * has no `state` field) and are skipped, same as owners.ts does for
   * industrial-convergence. */
  fieldByLayer: Partial<Record<LayerId, string>>;
  invalidValues?: Set<string>;
  /** Collapses differently-formatted values from different layers (e.g.
   * power_plants' "Texas" vs. substations/auto_plants' "TX") down to one
   * canonical form, so they're treated as the same value everywhere. */
  normalize?: (value: string) => string;
}

function getFeatureAttributeValue(config: AttributeSearchConfig, layerId: LayerId, properties: any): string | null {
  const field = config.fieldByLayer[layerId];
  if (!field) return null;
  const value = properties?.[field];
  if (!value || config.invalidValues?.has(value)) return null;
  return config.normalize ? config.normalize(value) : value;
}

export function featureMatchesAttributeQuery(
  config: AttributeSearchConfig,
  layerId: LayerId,
  properties: any,
  query: string
): boolean {
  if (!query.trim()) return true;
  const value = getFeatureAttributeValue(config, layerId, properties);
  const normalizedQuery = config.normalize ? config.normalize(query.trim()) : query.trim();
  const needle = normalizedQuery.toLowerCase();
  
  if (!value) return false;

  // For multi-value semicolon-delimited fields like process_categories
  // or current_processes ("Body in White & Structural Welding; Final Assembly..."),
  // match if any individual trimmed process token matches the query.
  if (value.includes(';')) {
    return value
      .split(';')
      .some((part) => part.trim().toLowerCase().includes(needle));
  }

  return value.toLowerCase().includes(needle);
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

// power_plants (EIA) stores full state names; substations (HIFLD) and
// auto_plants (EPA ECHO) store 2-letter USPS codes. Without normalizing,
// picking "Texas" only matches power_plants and picking "TX" only matches
// the other two, even though they mean the same state.
const STATE_NAME_TO_ABBR: Record<string, string> = {
  alabama: 'AL', alaska: 'AK', arizona: 'AZ', arkansas: 'AR', california: 'CA',
  colorado: 'CO', connecticut: 'CT', delaware: 'DE', 'district of columbia': 'DC',
  florida: 'FL', georgia: 'GA', hawaii: 'HI', idaho: 'ID', illinois: 'IL',
  indiana: 'IN', iowa: 'IA', kansas: 'KS', kentucky: 'KY', louisiana: 'LA',
  maine: 'ME', maryland: 'MD', massachusetts: 'MA', michigan: 'MI', minnesota: 'MN',
  mississippi: 'MS', missouri: 'MO', montana: 'MT', nebraska: 'NE', nevada: 'NV',
  'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY',
  'north carolina': 'NC', 'north dakota': 'ND', ohio: 'OH', oklahoma: 'OK',
  oregon: 'OR', pennsylvania: 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
  'south dakota': 'SD', tennessee: 'TN', texas: 'TX', utah: 'UT', vermont: 'VT',
  virginia: 'VA', washington: 'WA', 'west virginia': 'WV', wisconsin: 'WI',
  wyoming: 'WY', 'puerto rico': 'PR', guam: 'GU', 'american samoa': 'AS',
  'virgin islands': 'VI', 'northern mariana islands': 'MP',
};

export function normalizeStateValue(value: string): string {
  return (STATE_NAME_TO_ABBR[value.trim().toLowerCase()] ?? value).toUpperCase();
}

export const STATE_SEARCH: AttributeSearchConfig = {
  fieldByLayer: {
    'power-grid': 'state',
    'power-plants': 'state',
    substations: 'state',
    'auto-plants': 'state',
  },
  invalidValues: new Set(['NOT AVAILABLE', 'Unknown', '']),
  normalize: normalizeStateValue,
};

// Processes may be stored as semicolon-delimited strings (e.g. "welding (robotic); body in white")
export function collectDistinctMultiValues(
  config: AttributeSearchConfig,
  datasets: Record<string, any>,
  delimiter = ';'
): string[] {
  const seen = new Set<string>();
  (Object.keys(datasets) as LayerId[]).forEach((layerId) => {
    const features = datasets[layerId]?.features ?? [];
    for (const feature of features) {
      const raw = getFeatureAttributeValue(config, layerId, feature.properties);
      if (raw) {
        raw.split(delimiter).forEach((part) => {
          const item = part.trim();
          if (item) seen.add(item);
        });
      }
    }
  });
  return Array.from(seen).sort((a, b) => a.localeCompare(b));
}

export const PROCESS_SEARCH: AttributeSearchConfig = {
  fieldByLayer: {
    'auto-plants': 'process_categories',
  },
  invalidValues: new Set(['Unknown', '', 'None']),
};

export const DEFENSE_WORK_SEARCH: AttributeSearchConfig = {
  fieldByLayer: {
    'auto-plants': 'prior_defense_work',
  },
  invalidValues: new Set(['Unknown', '', 'none identified in open sources', 'none']),
};
