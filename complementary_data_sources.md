# Complementary EPA / DOE / EIA Datasets

Notes on federal datasets that could complement the data already ingested into Vectis Yield, gathered while reviewing the auto-facilities source schema (see [import_it_to_paperclip.md](import_it_to_paperclip.md) / [backend/ingest_auto_plants.py](backend/ingest_auto_plants.py)).

## Already in the codebase

| Layer | Source | Confirmed from file inspection |
|---|---|---|
| `auto_plants` | EPA ECHO (Enforcement & Compliance History Online) | `notes: "Seeded via EPA ECHO..."` |
| `power_plants` | EIA-860 / EIA-860M / EIA-923 | `"source": "EIA-860, EIA-860M and EIA-923"` in [plant_power_eia_v9.json](plant_power_eia_v9.json) |
| `power_grid` (transmission lines) | HIFLD (owner/voltage mostly `"NOT AVAILABLE"`) | [transmission_line_eia_v1.json](transmission_line_eia_v1.json) — despite the filename, this is HIFLD's transmission layer, not a pure EIA product |
| `substations`, `nerc_subregions` | HIFLD | separate `electric_substation_hifld_v4/` folder |

## Complementary EPA datasets

- **TRI (Toxics Release Inventory)** — facility-level, NAICS-coded, self-reported chemical throughput. A solid *proxy for production intensity* per facility since `approximate_employment`/`annual_capacity_estimate` are 100% null in the current source.
- **GHGRP (Greenhouse Gas Reporting Program)** — facility-level emissions by source category. Doubles as an energy-intensity proxy (ties directly into `vectis-yield-spec`'s `energy_profile`).
- **FRS (Facility Registry Service)** — the master ID system ECHO is built on; useful for cross-referencing the same facility across EPA/EIA/DOE datasets via a shared `registry_id`.

## Complementary DOE datasets

- **Industrial Assessment Center (IAC) Database** — real, audited facility-level energy-use data (by NAICS) from DOE's Advanced Manufacturing Office. Closest thing to ground-truth for `retooling_metrics.line_flexibility_score` / `energy_profile.facility_base_load_mw` that a federal source publishes.
- **Better Plants Program data** — voluntary large-manufacturer energy/water reporting, skews toward exactly the OEM-scale plants in the `auto_plants` table.
- **Grid interconnection queue data** (DOE/LBNL-maintained) — new generation/storage seeking grid connection, useful for forecasting future `substation_capacity_mw` and where `energy_bottleneck_flag` will get worse or better.
- **NREL** (DOE-funded) — renewable resource potential, relevant to `onsite_microgrid_installed` feasibility scoring.

## Complementary EIA datasets

- **MECS (Manufacturing Energy Consumption Survey)** — NAICS-coded industrial energy consumption/intensity by region. Directly fills the `energy_profile` schema at the sector level even without per-facility metering.
- **EIA-923 monthly generation/fuel data** — the existing 860/923 data is a capacity snapshot; the monthly *operational* data would let capacity factor (actual utilization vs. nameplate capacity) be computed for bottleneck modeling.
- **EIA Electricity Retail Price data** — regional $/MWh, feeds `macro_yield.estimated_annual_output_usd` cost assumptions.
- **AEO (Annual Energy Outlook)** — multi-year regional demand/price forecasts, matches `macro_yield.forecast_horizon_years` (3–10 yr).

## Also worth flagging (not EPA/DOE/EIA)

**Census County Business Patterns / QCEW** is the standard federal source for facility employment by NAICS+county — since `approximate_employment` is currently always null in the source data, this is likely the most direct fix for that specific gap.
