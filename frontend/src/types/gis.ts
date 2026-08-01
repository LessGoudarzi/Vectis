export type LayerId = 'auto-plants' | 'power-grid' | 'power-plants' | 'substations' | 'industrial-convergence';

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

// Mirrors backend/ingest_power_grid.py's power_grid table columns
export interface TransmissionLineProperties {
  id: number;
  owner: string;
  voltage: number | null;
  volt_class: string;
  status: string;
  line_type: string;
}

// Mirrors backend/ingest_power_grid.py's power_plants table columns
export interface PowerPlantProperties {
  id: number;
  plant_name: string;
  fuel_type: string;
  capacity_mw: number | null;
  owner: string;
  state: string;
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
}

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
