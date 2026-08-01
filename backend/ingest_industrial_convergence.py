"""Ingest agent-produced IndustrialConvergencePayload JSON files into DuckDB.

Mirrors the data-handling conventions already proven in
power/ingest_to_sqlite.py: tolerant property lookups, numeric coercion
helpers, bucketing for filterable summaries, and a graceful fallback to
bundled sample data when no real payloads are present yet.
"""

import json
from pathlib import Path
from typing import Optional

import duckdb

REQUIRED_TOP_LEVEL_FIELDS = [
    "facility_id",
    "corridor",
    "location",
    "retooling_metrics",
    "robotics_profile",
    "energy_profile",
    "macro_yield",
]


def _get_nested(payload: dict, *path, default=None):
    node = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node if node is not None else default


def _as_float(value, default=0.0):
    if value is None:
        return default
    try:
        if value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _output_bucket(estimated_annual_output_usd):
    if estimated_annual_output_usd is None:
        return "Unknown"
    value = estimated_annual_output_usd
    if value < 10_000_000:
        return "<$10M"
    if value < 50_000_000:
        return "$10-50M"
    if value < 100_000_000:
        return "$50-100M"
    if value < 500_000_000:
        return "$100-500M"
    if value < 1_000_000_000:
        return "$500M-1B"
    return "$1B+"


def _validate_payload(payload: dict, source: Path) -> Optional[str]:
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in payload:
            return f"{source.name}: missing required field '{field}'"
    location = payload.get("location") or {}
    if "lat" not in location or "lon" not in location:
        return f"{source.name}: location missing lat/lon"
    return None


def load_payloads(payload_dir: Path) -> list[dict]:
    """Read and validate every *.json payload in payload_dir.

    Invalid files are skipped with a printed warning rather than raising,
    matching ingest_to_sqlite.py's tolerance for messy real-world input.
    """
    payload_dir = Path(payload_dir)
    if not payload_dir.exists():
        return []

    payloads = []
    for json_path in sorted(payload_dir.glob("*.json")):
        try:
            payload = json.loads(json_path.read_text())
        except json.JSONDecodeError as exc:
            print(f"Skipping {json_path.name}: invalid JSON ({exc})")
            continue

        error = _validate_payload(payload, json_path)
        if error:
            print(f"Skipping {error}")
            continue

        payloads.append(payload)

    return payloads


def _flatten_record(payload: dict) -> tuple:
    retooling = payload.get("retooling_metrics") or {}
    robotics = payload.get("robotics_profile") or {}
    energy = payload.get("energy_profile") or {}
    macro = payload.get("macro_yield") or {}
    location = payload.get("location") or {}

    estimated_annual_output_usd = _as_float(macro.get("estimated_annual_output_usd"), default=None)

    return (
        str(payload.get("facility_id")),
        str(payload.get("corridor")),
        _as_float(location.get("lat")),
        _as_float(location.get("lon")),
        location.get("address"),
        retooling.get("legacy_sector"),
        retooling.get("dual_use_target"),
        _as_float(retooling.get("line_flexibility_score"), default=None),
        _as_float(retooling.get("cots_component_overlap_pct"), default=None),
        _as_float(robotics.get("robot_density_per_10k_sqft"), default=None),
        robotics.get("embodied_ai_adoption_level"),
        _as_float(robotics.get("peak_robotics_kw_draw"), default=None),
        _as_float(robotics.get("throughput_multiplier"), default=None),
        energy.get("iso_rto_region"),
        _as_float(energy.get("substation_capacity_mw"), default=None),
        _as_float(energy.get("facility_base_load_mw"), default=None),
        _as_bool(energy.get("onsite_microgrid_installed")),
        _as_bool(energy.get("energy_bottleneck_flag")),
        estimated_annual_output_usd,
        _as_float(macro.get("labor_productivity_delta_pct"), default=None),
        macro.get("forecast_horizon_years"),
        _output_bucket(estimated_annual_output_usd),
    )


def build_industrial_convergence_table(
    conn: duckdb.DuckDBPyConnection,
    payload_dir: Path,
    fallback_payload_dir: Optional[Path] = None,
) -> int:
    """Create/replace the industrial_convergence table plus its corridor
    summary and output-bucket tables, using the same "seed real data, and
    fall back to bundled samples if none exists yet" pattern used for
    transmission_lines / power_plants in power/app.py.
    """
    payloads = load_payloads(payload_dir)
    used_fallback = False
    if not payloads and fallback_payload_dir is not None:
        payloads = load_payloads(fallback_payload_dir)
        used_fallback = True

    conn.execute("DROP TABLE IF EXISTS industrial_convergence")
    conn.execute("DROP TABLE IF EXISTS industrial_convergence_corridor_summary")
    conn.execute("DROP TABLE IF EXISTS industrial_convergence_output_buckets")

    conn.execute(
        """
        CREATE TABLE industrial_convergence (
            facility_id TEXT,
            corridor TEXT,
            lat DOUBLE,
            lon DOUBLE,
            address TEXT,
            legacy_sector TEXT,
            dual_use_target TEXT,
            line_flexibility_score DOUBLE,
            cots_component_overlap_pct DOUBLE,
            robot_density_per_10k_sqft DOUBLE,
            embodied_ai_adoption_level TEXT,
            peak_robotics_kw_draw DOUBLE,
            throughput_multiplier DOUBLE,
            iso_rto_region TEXT,
            substation_capacity_mw DOUBLE,
            facility_base_load_mw DOUBLE,
            onsite_microgrid_installed BOOLEAN,
            energy_bottleneck_flag BOOLEAN,
            estimated_annual_output_usd DOUBLE,
            labor_productivity_delta_pct DOUBLE,
            forecast_horizon_years INTEGER,
            output_bucket TEXT,
            geom GEOMETRY
        )
        """
    )

    if payloads:
        records = [_flatten_record(payload) for payload in payloads]
        conn.executemany(
            """
            INSERT INTO industrial_convergence (
                facility_id, corridor, lat, lon, address,
                legacy_sector, dual_use_target, line_flexibility_score, cots_component_overlap_pct,
                robot_density_per_10k_sqft, embodied_ai_adoption_level, peak_robotics_kw_draw, throughput_multiplier,
                iso_rto_region, substation_capacity_mw, facility_base_load_mw,
                onsite_microgrid_installed, energy_bottleneck_flag,
                estimated_annual_output_usd, labor_productivity_delta_pct, forecast_horizon_years,
                output_bucket, geom
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ST_Point(?, ?)
            )
            """,
            [record + (record[3], record[2]) for record in records],
        )

    conn.execute(
        """
        CREATE TABLE industrial_convergence_corridor_summary AS
        SELECT
            corridor,
            COUNT(*) AS facility_count,
            ROUND(SUM(estimated_annual_output_usd), 2) AS total_estimated_output_usd,
            ROUND(AVG(line_flexibility_score), 3) AS avg_line_flexibility_score,
            SUM(CASE WHEN energy_bottleneck_flag THEN 1 ELSE 0 END) AS bottleneck_count
        FROM industrial_convergence
        GROUP BY corridor
        ORDER BY facility_count DESC, corridor
        """
    )
    conn.execute(
        """
        CREATE TABLE industrial_convergence_output_buckets AS
        SELECT
            corridor,
            output_bucket,
            COUNT(*) AS facility_count,
            ROUND(SUM(estimated_annual_output_usd), 2) AS total_estimated_output_usd
        FROM industrial_convergence
        GROUP BY corridor, output_bucket
        ORDER BY corridor, facility_count DESC, output_bucket
        """
    )

    if used_fallback:
        print(f"No payloads found in {payload_dir}; seeded from fallback sample data instead.")

    return len(payloads)
