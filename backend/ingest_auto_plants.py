"""Load real U.S. automobile assembly/component facility data into the
`auto_plants` DuckDB table, replacing the 5-row hardcoded mock.

Unlike power_grid/power_plants/substations, this dataset arrives as plain
JSON (not a GEM tool GeoPackage), so it's ingested directly here rather
than via power/ingest_to_sqlite.py + SQLite — the same direct-JSON
approach ingest_industrial_convergence.py already uses.
"""

import json
import logging
from pathlib import Path

import duckdb

logger = logging.getLogger("uvicorn")


def _flatten_record(entry: dict) -> tuple | None:
    location = entry.get("location") or {}
    coordinates = location.get("coordinates") or {}
    lat, lon = coordinates.get("lat"), coordinates.get("lon")
    if lat is None or lon is None:
        return None

    products = entry.get("products") or []
    conversion_profile = entry.get("defense_conversion_profile") or {}

    return (
        str(entry.get("facility_name") or "Unknown"),
        str(entry.get("oem_or_parent") or "Unknown"),
        str(entry.get("facility_type") or "Unknown"),
        str(entry.get("state_abbr") or ""),
        str(entry.get("status") or "Unknown"),
        ", ".join(str(p) for p in products) if products else None,
        entry.get("approximate_employment"),
        entry.get("annual_capacity_estimate"),
        conversion_profile.get("conversion_indicators_summary"),
        float(lon),
        float(lat),
    )


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
            annual_capacity_estimate TEXT, conversion_summary TEXT, geom GEOMETRY
        )
        """
    )

    if not json_path.exists():
        logger.warning(f"No auto-facilities source at {json_path}; auto_plants will be empty.")
        return 0

    entries = json.loads(json_path.read_text())
    records = [rec for entry in entries if (rec := _flatten_record(entry)) is not None]

    if records:
        conn.executemany(
            """
            INSERT INTO auto_plants (
                id, facility_name, oem_or_parent, facility_type, state, status,
                products, approximate_employment, annual_capacity_estimate,
                conversion_summary, geom
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ST_Point(?, ?))
            """,
            [(i + 1, *rec) for i, rec in enumerate(records)],
        )

    skipped = len(entries) - len(records)
    if skipped:
        logger.warning(f"Skipped {skipped} auto facility record(s) missing coordinates.")

    return len(records)
