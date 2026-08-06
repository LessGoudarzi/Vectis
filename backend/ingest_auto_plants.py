"""Load real U.S. automobile assembly/component facility data into the
`auto_plants` DuckDB table, replacing the 5-row hardcoded mock.

Unlike power_grid/power_plants/substations, this dataset arrives as plain
JSON (not a GEM tool GeoPackage), so it's ingested directly here rather
than via power/ingest_to_sqlite.py + SQLite — the same direct-JSON
approach ingest_industrial_convergence.py already uses.
"""

import json
import logging
import re
from pathlib import Path

import duckdb

logger = logging.getLogger("uvicorn")

# Supply-chain tier/role per NAICS code, in place of the source data's own
# coarse facility_type (just "Assembly Plant" vs "Tier 1/2 Supplier
# Facility" — see products' embedded "NAICS: ######" tag for the actual
# per-facility manufacturing role). Order matters only for the fallback
# search below; every facility in the current dataset carries exactly one
# of these ten codes.
NAICS_CLASSIFICATION: dict[str, str] = {
    "336111": "OEM Assembly (Automobile)",
    "336112": "OEM Assembly (Light Truck/SUV)",
    "336211": "Body Manufacturing (Tier 1)",
    "336310": "Engine & Engine Parts (Tier 1/2)",
    "336320": "Electrical & Electronics (Tier 1/2)",
    "336330": "Steering & Suspension (Tier 1/2)",
    "336340": "Brake Systems (Tier 1/2)",
    "336350": "Transmission & Powertrain (Tier 1/2)",
    "336370": "Metal Stamping (Tier 1/2)",
    "336390": "Other Vehicle Parts (Tier 1/2)",
}

_NAICS_PATTERN = re.compile(r"NAICS:\s*(\d+)")


def _classify_facility_type(entry: dict, products: list) -> str:
    """Reclassifies by NAICS code embedded in `products` (e.g. "...
    (NAICS: 336111)"), falling back to the source's own facility_type for
    any record whose NAICS code isn't in NAICS_CLASSIFICATION (e.g. older,
    hand-curated entries that predate the EPA ECHO NAICS tagging)."""
    for product in products:
        match = _NAICS_PATTERN.search(str(product))
        if match and match.group(1) in NAICS_CLASSIFICATION:
            return NAICS_CLASSIFICATION[match.group(1)]
    return str(entry.get("facility_type") or "Unknown")


def _flatten_record(entry: dict) -> tuple | None:
    location = entry.get("location") or {}
    coordinates = location.get("coordinates") or {}
    lat, lon = coordinates.get("lat") or entry.get("latitude"), coordinates.get("lon") or entry.get("longitude")
    if lat is None or lon is None:
        return None

    products = entry.get("products") or []
    dcp = entry.get("defense_conversion_profile") or {}
    pc = dcp.get("production_capabilities") or {}
    ws = dcp.get("workforce_and_skills") or {}
    hdu = dcp.get("historical_or_current_dual_use") or {}

    current_procs = pc.get("current_processes") or []
    if isinstance(current_procs, list):
        procs_str = "; ".join(str(p).strip() for p in current_procs if p)
    else:
        procs_str = str(current_procs)

    proc_cats = entry.get("process_categories") or []
    if isinstance(proc_cats, list):
        proc_cats_str = "; ".join(str(c).strip() for c in proc_cats if c)
    else:
        proc_cats_str = str(proc_cats)

    data_gaps = dcp.get("data_gaps") or []
    if isinstance(data_gaps, list):
        data_gaps_str = "; ".join(str(g).strip() for g in data_gaps if g)
    else:
        data_gaps_str = str(data_gaps)

    cleanroom = pc.get("cleanroom_or_controlled_environment")
    has_cleanroom = entry.get("has_cleanroom")
    if has_cleanroom is None and cleanroom:
        cleanroom_lower = str(cleanroom).lower()
        has_cleanroom = "yes" in cleanroom_lower or "dry room" in cleanroom_lower

    tier_desc = entry.get("defense_conversion_tier") or "Tier 1: OEM Flagship Assembly"

    return (
        str(entry.get("facility_name") or entry.get("name") or "Unknown"),
        str(entry.get("oem_or_parent") or "Unknown"),
        str(entry.get("facility_type") or _classify_facility_type(entry, products)),
        str(entry.get("state_abbr") or entry.get("state") or ""),
        str(entry.get("status") or "Unknown"),
        ", ".join(str(p) for p in products) if products else None,
        entry.get("approximate_employment"),
        entry.get("annual_capacity_estimate"),
        dcp.get("conversion_indicators_summary"),
        procs_str if procs_str else None,
        proc_cats_str if proc_cats_str else None,
        tier_desc,
        str(pc.get("existing_automation_and_robotics") or "Unknown"),
        str(cleanroom or "No"),
        bool(has_cleanroom),
        str(ws.get("union_status_and_flexibility_notes") or "Unknown"),
        str(hdu.get("prior_defense_work") or "None identified"),
        str(hdu.get("ITAR_or_export_control_experience") or "Unknown"),
        data_gaps_str if data_gaps_str else None,
        float(lon),
        float(lat),
    )


def _load_entries(json_path: Path) -> list[dict]:
    """Parses either a single JSON array or JSON Lines (one object per
    line) - source data has switched between both formats, and the file
    extension alone doesn't reliably indicate which one a given file is."""
    text = json_path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def build_auto_plants_table(conn: duckdb.DuckDBPyConnection, json_path: Path) -> int:
    """(Re)create the `auto_plants` DuckDB table from real facility data.

    Falls back to leaving the table empty (rather than raising) if the
    source JSON isn't present, so a fresh checkout without this file
    still boots the API — the layer just renders nothing until it's added.
    """
    conn.execute("DROP TABLE IF EXISTS auto_plants")
    conn.execute(
        """
        CREATE TABLE auto_plants (
            id INTEGER, facility_name TEXT, oem_or_parent TEXT, facility_type TEXT,
            state TEXT, status TEXT, products TEXT, approximate_employment INTEGER,
            annual_capacity_estimate TEXT, conversion_summary TEXT,
            current_processes TEXT, process_categories TEXT, defense_conversion_tier TEXT,
            automation_level TEXT, cleanroom_specs TEXT,
            has_cleanroom BOOLEAN, union_notes TEXT, prior_defense_work TEXT,
            itar_experience TEXT, data_gaps TEXT, subregion_name TEXT, geom GEOMETRY
        )
        """
    )

    if not json_path.exists():
        logger.warning(f"No auto-facilities source at {json_path}; auto_plants will be empty.")
        return 0

    entries = _load_entries(json_path)
    records = [rec for entry in entries if (rec := _flatten_record(entry)) is not None]

    if records:
        conn.executemany(
            """
            INSERT INTO auto_plants (
                id, facility_name, oem_or_parent, facility_type, state, status,
                products, approximate_employment, annual_capacity_estimate,
                conversion_summary, current_processes, process_categories,
                defense_conversion_tier, automation_level, cleanroom_specs,
                has_cleanroom, union_notes, prior_defense_work, itar_experience,
                data_gaps, subregion_name, geom
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ST_Point(?, ?))
            """,
            [(i + 1, *rec) for i, rec in enumerate(records)],
        )

    skipped = len(entries) - len(records)
    if skipped:
        logger.warning(f"Skipped {skipped} auto facility record(s) missing coordinates.")

    return len(records)
