import { ActiveHighlight, LayerId } from './types/gis';

// Mirrors backend/database.py's TRACE_SOURCE_TABLES — any point layer a
// trace can originate from.
export type TraceableLayerId = 'power-plants' | 'auto-plants';

// Mirrors backend/trace.py's response shape
export interface TraceLine {
  line_id: number;
  distance_from_origin_miles: number;
  hop_count: number;
}

export interface TraceResult {
  status: 'ok' | 'not_connected' | 'not_found' | 'unavailable';
  home_subregion?: string | null;
  stopped_reason?: 'subregion_boundary' | 'max_miles' | 'component_exhausted';
  lines?: TraceLine[];
  detail?: string;
}

export const TRACE_HIGHLIGHT_COLOR = '#FFFFFF';

export async function fetchTrace(
  layerId: TraceableLayerId,
  facilityId: number,
  maxMiles: number,
  allowCrossSubregion = false
): Promise<TraceResult> {
  const params = new URLSearchParams({ max_miles: String(maxMiles), allow_cross_subregion: String(allowCrossSubregion) });
  const res = await fetch(`/api/v1/trace/${layerId}/${facilityId}?${params}`);
  if (!res.ok) {
    if (res.status === 404) return { status: 'not_found' };
    throw new Error(`Trace request failed: ${res.status}`);
  }
  return res.json();
}

// Layers whose features are point-in-polygon/from_node_id tagged with
// their NERC subregion (see ingest_power_grid.py's
// tag_points_with_nerc_subregion and build_power_grid_tables) — the set
// eligible for the "stay visible within the home subregion" exemption.
const SUBREGION_TAGGED_LAYERS = new Set<LayerId>(['power-grid', 'power-plants', 'substations', 'auto-plants']);

// Traced lines keep their normal voltage-bucket color (so voltage stays
// readable during a trace) and are distinguished by boosted alpha + a
// thicker stroke instead (see layerFactory.ts's power-grid case); the
// traced facility itself is matched too (on whichever layer it came
// from — power-plants or auto-plants) so it doesn't fade along with
// every other feature on that layer. When the trace's home subregion is
// known, that boundary brightens to TRACE_HIGHLIGHT_COLOR — showing
// visually where "stopped_reason: subregion_boundary" actually means,
// which is a different kind of highlight (a boundary outline, not a
// data color).
//
// Everything else in the same home subregion — transmission lines,
// substations, plants that weren't actually reached by the trace — stays
// at normal opacity too (isExempt), so the whole local grid is visible
// for context. Only things outside that subregion dim.
export function createTraceHighlight(
  sourceLayerId: TraceableLayerId,
  facilityId: number,
  revealedLineIds: Set<number>,
  homeSubregion?: string | null
): ActiveHighlight {
  return {
    isMatch: (layerId: LayerId, properties) => {
      if (layerId === 'power-grid') return revealedLineIds.has(properties.id);
      if (layerId === sourceLayerId) return properties.id === facilityId;
      if (layerId === 'nerc-subregions') return homeSubregion != null && properties.subregion_name === homeSubregion;
      return false;
    },
    isExempt: (layerId: LayerId, properties) => {
      if (homeSubregion == null || !SUBREGION_TAGGED_LAYERS.has(layerId)) return false;
      return properties.subregion_name === homeSubregion;
    },
    colorOverrideHex: { 'nerc-subregions': TRACE_HIGHLIGHT_COLOR },
  };
}
