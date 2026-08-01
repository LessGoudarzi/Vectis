"""Load the real EIA/HIFLD transmission-line, power-plant, and substation
data that power/ingest_to_sqlite.py already ingested into a SQLite
database, and seed it into DuckDB as the `power_grid` / `power_plants` /
`substations` spatial layers.

The SQLite geometries are stored in Web Mercator (EPSG:3857), matching
power/app.py's convention of reprojecting to WGS84 at read time rather
than at ingest time. This module reprojects up front instead, since
DuckDB's spatial functions (ST_Intersects, etc.) need WGS84 degrees to
line up with the other layers' ST_Point(lon, lat) data.
"""

import json
import logging
import math
import sqlite3
from pathlib import Path
from typing import Optional

import duckdb

logger = logging.getLogger("uvicorn")


def _mercator_to_lonlat(x: float, y: float) -> list[float]:
    """Inverse Web Mercator projection, ported from power/app.py."""
    lon = (x / 20037508.34) * 180.0
    lat = (y / 20037508.34) * 180.0
    lat = 180.0 / math.pi * (2.0 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return [lon, lat]


def _reproject_coords(coords):
    if (
        len(coords) >= 2
        and isinstance(coords[0], (int, float))
        and isinstance(coords[1], (int, float))
    ):
        return _mercator_to_lonlat(coords[0], coords[1])
    return [_reproject_coords(c) for c in coords]


def _reproject_geometry(geometry: dict) -> dict:
    return {**geometry, "coordinates": _reproject_coords(geometry["coordinates"])}


def _load_sqlite_rows(sqlite_db_path: Path, table: str, columns: list[str]) -> list[tuple]:
    conn = sqlite3.connect(str(sqlite_db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT {', '.join(columns)}, geojson_geom FROM {table} WHERE geojson_geom IS NOT NULL"
    ).fetchall()
    conn.close()
    return rows


def build_power_grid_tables(conn: duckdb.DuckDBPyConnection, sqlite_db_path: Path) -> dict[str, int]:
    """(Re)create the `power_grid`, `power_plants`, and `substations`
    DuckDB tables from the real data in power/ingest_to_sqlite.py's
    SQLite output.

    Leaves all three tables empty (rather than raising) if the SQLite
    file isn't present yet, so a fresh checkout without the local db
    still boots the API.
    """
    conn.execute("DROP TABLE IF EXISTS power_grid")
    conn.execute(
        """
        CREATE TABLE power_grid (
            id INTEGER, owner TEXT, voltage INTEGER, volt_class TEXT,
            status TEXT, line_type TEXT, geom GEOMETRY
        )
        """
    )
    conn.execute("DROP TABLE IF EXISTS power_plants")
    conn.execute(
        """
        CREATE TABLE power_plants (
            id INTEGER, plant_name TEXT, fuel_type TEXT, capacity_mw DOUBLE,
            owner TEXT, state TEXT, geom GEOMETRY
        )
        """
    )
    conn.execute("DROP TABLE IF EXISTS substations")
    conn.execute(
        """
        CREATE TABLE substations (
            id INTEGER, facility_name TEXT, sub_type TEXT, status TEXT,
            county TEXT, state TEXT, max_voltage_kv DOUBLE, min_voltage_kv DOUBLE,
            line_count INTEGER, geom GEOMETRY
        )
        """
    )

    if not sqlite_db_path.exists():
        logger.warning(f"No SQLite source at {sqlite_db_path}; power_grid/power_plants/substations will be empty.")
        return {"power_grid": 0, "power_plants": 0, "substations": 0}

    line_rows = _load_sqlite_rows(
        sqlite_db_path, "transmission_lines", ["id", "owner", "voltage", "volt_class", "status", "line_type"]
    )
    if line_rows:
        conn.executemany(
            "INSERT INTO power_grid VALUES (?, ?, ?, ?, ?, ?, ST_GeomFromGeoJSON(?))",
            [
                (
                    row["id"], row["owner"], row["voltage"], row["volt_class"], row["status"], row["line_type"],
                    json.dumps(_reproject_geometry(json.loads(row["geojson_geom"]))),
                )
                for row in line_rows
            ],
        )

    plant_rows = _load_sqlite_rows(
        sqlite_db_path, "power_plants", ["id", "plant_name", "fuel_type", "capacity_mw", "owner", "state"]
    )
    if plant_rows:
        conn.executemany(
            "INSERT INTO power_plants VALUES (?, ?, ?, ?, ?, ?, ST_GeomFromGeoJSON(?))",
            [
                (
                    row["id"], row["plant_name"], row["fuel_type"], row["capacity_mw"], row["owner"], row["state"],
                    json.dumps(_reproject_geometry(json.loads(row["geojson_geom"]))),
                )
                for row in plant_rows
            ],
        )

    substation_rows = _load_sqlite_rows(
        sqlite_db_path,
        "substations",
        ["id", "facility_name", "sub_type", "status", "county", "state", "max_voltage_kv", "min_voltage_kv", "line_count"],
    )
    if substation_rows:
        conn.executemany(
            "INSERT INTO substations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ST_GeomFromGeoJSON(?))",
            [
                (
                    row["id"], row["facility_name"], row["sub_type"], row["status"], row["county"], row["state"],
                    row["max_voltage_kv"], row["min_voltage_kv"], row["line_count"],
                    json.dumps(_reproject_geometry(json.loads(row["geojson_geom"]))),
                )
                for row in substation_rows
            ],
        )

    return {"power_grid": len(line_rows), "power_plants": len(plant_rows), "substations": len(substation_rows)}
