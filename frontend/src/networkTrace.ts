import { ActiveHighlight } from './types/gis';

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

export async function fetchTrace(plantId: number, maxMiles: number, allowCrossSubregion = false): Promise<TraceResult> {
  const params = new URLSearchParams({ max_miles: String(maxMiles), allow_cross_subregion: String(allowCrossSubregion) });
  const res = await fetch(`/api/v1/trace/power-plant/${plantId}?${params}`);
  if (!res.ok) {
    if (res.status === 404) return { status: 'not_found' };
    throw new Error(`Trace request failed: ${res.status}`);
  }
  return res.json();
}

// Traced lines keep their normal voltage-bucket color (so voltage stays
// readable during a trace) and are distinguished by boosted alpha + a
// thicker stroke instead (see layerFactory.ts's power-grid case); the
// traced plant itself is matched too so it doesn't fade along with every
// other power plant. When the trace's home subregion is known, that
// boundary brightens to TRACE_HIGHLIGHT_COLOR — showing visually where
// "stopped_reason: subregion_boundary" actually means, which is a
// different kind of highlight (a boundary outline, not a data color).
export function createTraceHighlight(
  plantId: number,
  revealedLineIds: Set<number>,
  homeSubregion?: string | null
): ActiveHighlight {
  return {
    isMatch: (layerId, properties) => {
      if (layerId === 'power-grid') return revealedLineIds.has(properties.id);
      if (layerId === 'power-plants') return properties.id === plantId;
      if (layerId === 'nerc-subregions') return homeSubregion != null && properties.subregion_name === homeSubregion;
      return false;
    },
    colorOverrideHex: { 'nerc-subregions': TRACE_HIGHLIGHT_COLOR },
  };
}
