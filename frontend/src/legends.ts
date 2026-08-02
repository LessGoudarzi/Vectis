import { LayerId, LegendEntry } from './types/gis';

// Voltage bucket thresholds and colors mirror power/templates/index.html's
// getLineStyle() exactly, so the two UIs read the same way.
export const VOLTAGE_LEGEND: LegendEntry[] = [
  { label: 'Under 69 kV', colorHex: '#84cc16' },
  { label: '69-160 kV', colorHex: '#f59e0b' },
  { label: '161-229 kV', colorHex: '#38bdf8' },
  { label: '230-344 kV', colorHex: '#8b5cf6' },
  { label: '345-499 kV', colorHex: '#f43f5e' },
  { label: '500+ kV', colorHex: '#dc2626' },
  { label: 'Unknown / missing', colorHex: '#64748b' },
];

export function voltageBucketLabel(voltage: number | null | undefined): string {
  if (voltage == null || voltage < 0) return 'Unknown / missing';
  if (voltage >= 500) return '500+ kV';
  if (voltage >= 345) return '345-499 kV';
  if (voltage >= 230) return '230-344 kV';
  if (voltage >= 161) return '161-229 kV';
  if (voltage >= 69) return '69-160 kV';
  return 'Under 69 kV';
}

const VOLTAGE_COLOR_BY_LABEL: Record<string, string> = Object.fromEntries(
  VOLTAGE_LEGEND.map((entry) => [entry.label, entry.colorHex])
);

export function voltageBucketColorHex(voltage: number | null | undefined): string {
  return VOLTAGE_COLOR_BY_LABEL[voltageBucketLabel(voltage)] ?? '#64748b';
}

// Matches power/templates/index.html's getPowerPlantStyle() and the fuel
// buckets power/ingest_to_sqlite.py's _normalize_fuel_bucket() produces.
export const FUEL_LEGEND: LegendEntry[] = [
  { label: 'Solar', colorHex: '#f59e0b' },
  { label: 'Wind', colorHex: '#14b8a6' },
  { label: 'Hydro', colorHex: '#3b82f6' },
  { label: 'Natural Gas', colorHex: '#ef4444' },
  { label: 'Coal', colorHex: '#334155' },
  { label: 'Nuclear', colorHex: '#8b5cf6' },
  { label: 'Biomass', colorHex: '#84cc16' },
  { label: 'Petroleum', colorHex: '#f97316' },
  { label: 'Storage', colorHex: '#22c55e' },
  { label: 'Geothermal', colorHex: '#c2410c' },
  { label: 'Other / Unknown', colorHex: '#64748b' },
];

const FUEL_COLOR_BY_LABEL: Record<string, string> = Object.fromEntries(
  FUEL_LEGEND.map((entry) => [entry.label, entry.colorHex])
);

export function fuelColorHex(fuelType: string | null | undefined): string {
  return FUEL_COLOR_BY_LABEL[fuelType ?? ''] ?? '#64748b';
}

// Matches the facility_type values in auto_facilities_VECA8.json
export const AUTO_PLANTS_LEGEND: LegendEntry[] = [
  { label: 'Assembly', colorHex: '#F59E0B' },
  { label: 'Battery', colorHex: '#22c55e' },
  { label: 'Engine', colorHex: '#ef4444' },
  { label: 'Transmission', colorHex: '#3b82f6' },
  { label: 'Body/Stamping', colorHex: '#a855f7' },
  { label: 'Other Major Component', colorHex: '#64748b' },
];

const AUTO_PLANTS_COLOR_BY_LABEL: Record<string, string> = Object.fromEntries(
  AUTO_PLANTS_LEGEND.map((entry) => [entry.label, entry.colorHex])
);

export function autoPlantColorHex(facilityType: string | null | undefined): string {
  return AUTO_PLANTS_COLOR_BY_LABEL[facilityType ?? ''] ?? '#64748b';
}

// The 8 top-level NERC regions in the real dataset (jurisdiction_nerc_subregion_v1) —
// legend groups by region, not by the 22 individual subregion polygons,
// same "don't clutter the selector" reasoning as owner search: WECC ≈ the
// Western Interconnection, TRE ≈ ERCOT, the other six are all subdivisions
// of the single Eastern Interconnection (see trace.py's docstring).
export const NERC_REGION_LEGEND: LegendEntry[] = [
  { label: 'WECC', colorHex: '#38bdf8' },
  { label: 'TRE', colorHex: '#f97316' },
  { label: 'SPP', colorHex: '#a3e635' },
  { label: 'MRO', colorHex: '#facc15' },
  { label: 'RFC', colorHex: '#22c55e' },
  { label: 'SERC', colorHex: '#f43f5e' },
  { label: 'NPCC', colorHex: '#a855f7' },
  { label: 'FRCC', colorHex: '#2dd4bf' },
];

const NERC_REGION_COLOR_BY_LABEL: Record<string, string> = Object.fromEntries(
  NERC_REGION_LEGEND.map((entry) => [entry.label, entry.colorHex])
);

export function nercRegionColorHex(nercRegion: string | null | undefined): string {
  return NERC_REGION_COLOR_BY_LABEL[nercRegion ?? ''] ?? '#64748b';
}

export const LAYER_LEGENDS: Record<LayerId, LegendEntry[]> = {
  'auto-plants': AUTO_PLANTS_LEGEND,
  'power-grid': VOLTAGE_LEGEND,
  'power-plants': FUEL_LEGEND,
  // Substations are categorized by max_voltage_kv (the highest voltage
  // line they tie into), so they share the same voltage buckets/colors
  // as transmission lines — selection state is still tracked per-layer
  // (see useLayerState.ts's categoryFilters), so toggling a bucket here
  // doesn't affect the Transmission Lines layer.
  substations: VOLTAGE_LEGEND,
  'nerc-subregions': NERC_REGION_LEGEND,
};

// The legend label a given feature belongs to, for both coloring and
// category filtering — keeps the two concerns from drifting apart.
export function getFeatureCategoryLabel(layerId: LayerId, properties: any): string {
  switch (layerId) {
    case 'power-grid':
      return voltageBucketLabel(properties?.voltage);
    case 'power-plants':
      return FUEL_COLOR_BY_LABEL[properties?.fuel_type] ? properties.fuel_type : 'Other / Unknown';
    case 'substations':
      return voltageBucketLabel(properties?.max_voltage_kv);
    case 'nerc-subregions':
      return NERC_REGION_COLOR_BY_LABEL[properties?.nerc_region] ? properties.nerc_region : 'Unknown';
    case 'auto-plants':
      return AUTO_PLANTS_COLOR_BY_LABEL[properties?.facility_type] ? properties.facility_type : 'Other Major Component';
    default:
      return 'Unknown';
  }
}
