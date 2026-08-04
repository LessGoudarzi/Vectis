export type LayerId = 'auto-plants' | 'power-grid' | 'power-plants' | 'substations' | 'nerc-subregions';

export interface LayerConfig {
  id: LayerId;
  name: string;
  visible: boolean;
  opacity: number;
  colorHex: string;
  zIndex: number;
  legendVisible: boolean;
}

export interface LegendEntry {
  label: string;
  colorHex: string;
}

// Shared by owner search and network tracing: exactly one "investigative
// mode" is active on the map at a time (see owners.ts's
// createOwnerHighlight, networkTrace.ts's createTraceHighlight).
// Three tiers per feature (see layerFactory.ts's highlightAlpha):
//   1. isMatch        -> boosted alpha (+ optional color override)
//   2. isExempt        -> normal alpha, no dim (but no boost either)
//   3. neither          -> dimmed
// Owner search has no exemptions (dims everything but direct matches, to
// isolate a company's footprint). Network trace exempts every feature in
// the traced facility's home NERC subregion, not just the traced lines
// themselves, so the whole local grid stays visible for context — only
// stuff outside that subregion dims.
export interface ActiveHighlight {
  isMatch: (layerId: LayerId, properties: any) => boolean;
  isExempt?: (layerId: LayerId, properties: any) => boolean;
  colorOverrideHex?: Partial<Record<LayerId, string>>;
}

// Mirrors backend/ingest_auto_plants.py's auto_plants table columns
export interface AutoPlantProperties {
  id: number;
  facility_name: string;
  oem_or_parent: string;
  facility_type: string;
  state: string;
  status: string;
  products: string | null;
  approximate_employment: number | null;
  annual_capacity_estimate: string | null;
  conversion_summary: string | null;
  // Point-in-polygon tagged against nerc_subregions — null for the ~1%
  // outside CONUS coverage (see ingest_power_grid.py's
  // tag_points_with_nerc_subregion).
  subregion_name: string | null;
}

// Mirrors backend/ingest_power_grid.py's power_grid table columns
export interface TransmissionLineProperties {
  id: number;
  owner: string;
  voltage: number | null;
  volt_class: string;
  status: string;
  line_type: string;
  // Inferred from the nearest substation at ingest time (HIFLD lines carry
  // no state property of their own) - see
  // _infer_line_state_from_nearby_substations in ingest_power_grid.py.
  state: string;
  // Derived from the line's from_node_id at ingest time, not a separate
  // polygon test — keeps "in the home subregion" consistent with what
  // trace.py's own subregion-bounded stopping condition means.
  subregion_name: string | null;
}

// Mirrors backend/ingest_power_grid.py's power_plants table columns
export interface PowerPlantProperties {
  id: number;
  plant_name: string;
  fuel_type: string;
  capacity_mw: number | null;
  owner: string;
  state: string;
  subregion_name: string | null;
}

// Mirrors backend/ingest_power_grid.py's substations table columns
export interface SubstationProperties {
  id: number;
  facility_name: string;
  sub_type: string;
  status: string;
  county: string;
  state: string;
  max_voltage_kv: number | null;
  min_voltage_kv: number | null;
  line_count: number | null;
  // Inferred from nearby transmission lines (see ingest_power_grid.py's
  // _link_substations_to_nearby_line_owners) — not an authoritative
  // ownership record, and can be null/empty if nothing resolved nearby.
  nearby_line_owners: string[] | null;
  subregion_name: string | null;
}

// Mirrors backend/ingest_power_grid.py's nerc_subregions table columns —
// the boundary a network trace stops at by default (see trace.py)
export interface NercSubregionProperties {
  id: number;
  nerc_region: string;
  subregion_name: string;
}

// Not currently a rendered layer (dropped from the map — see LayerId —
// until the agent swarm actually produces real payloads; the backend
// table/endpoint are still there). Kept here for when it comes back.
// Mirrors backend/ingest_industrial_convergence.py's flattened
// IndustrialConvergencePayload columns (see vectis-yield-spec/COMPANY.md
// for the full nested schema the agent swarm produces).
export interface IndustrialConvergenceProperties {
  facility_id: string;
  corridor: string;
  lat: number;
  lon: number;
  address: string | null;
  legacy_sector: string | null;
  dual_use_target: string | null;
  line_flexibility_score: number | null;
  cots_component_overlap_pct: number | null;
  robot_density_per_10k_sqft: number | null;
  embodied_ai_adoption_level: string | null;
  peak_robotics_kw_draw: number | null;
  throughput_multiplier: number | null;
  iso_rto_region: string | null;
  substation_capacity_mw: number | null;
  facility_base_load_mw: number | null;
  onsite_microgrid_installed: boolean;
  energy_bottleneck_flag: boolean;
  estimated_annual_output_usd: number | null;
  labor_productivity_delta_pct: number | null;
  forecast_horizon_years: number | null;
  output_bucket: string;
}
