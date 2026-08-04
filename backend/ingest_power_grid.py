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

# HIFLD substations are usually digitized right at (or within ~100m of) a
# transmission line vertex — verified against the real data before picking
# this threshold: 0.01deg (~1.1km) resolves ~82% of substations to at least
# one valid owner, with diminishing returns and rising false-association
# risk past that (see the investigation in conversation / PR description).
SUBSTATION_OWNER_JOIN_BUFFER_DEG = 0.01
_INVALID_OWNER_VALUES = ("NOT AVAILABLE", "Unknown", "")


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


_EARTH_RADIUS_MILES = 3958.7613


def _haversine_miles(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_MILES * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _geometry_length_miles(geometry: dict) -> float:
    """Geodesic length via Haversine, summed vertex-to-vertex. Computed
    ourselves rather than via DuckDB's ST_Length_Spheroid, which returns
    NaN for roughly half of this real dataset's (structurally ordinary,
    non-degenerate) MultiLineStrings for reasons that didn't turn up an
    an obvious root cause on inspection - not worth depending on.
    """
    geom_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geom_type == "LineString":
        parts = [coordinates]
    elif geom_type == "MultiLineString":
        parts = coordinates
    else:
        return 0.0

    total = 0.0
    for part in parts:
        for (lon1, lat1), (lon2, lat2) in zip(part, part[1:]):
            total += _haversine_miles(lon1, lat1, lon2, lat2)
    return total


def _load_sqlite_rows(sqlite_db_path: Path, table: str, columns: list[str]) -> list[tuple]:
    conn = sqlite3.connect(str(sqlite_db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT {', '.join(columns)}, geojson_geom FROM {table} WHERE geojson_geom IS NOT NULL"
    ).fetchall()
    conn.close()
    return rows


def _load_node_subregions(sqlite_db_path: Path) -> dict[int, Optional[str]]:
    """node_id -> subregion_name, from power/build_grid_topology.py's
    output — empty if that script hasn't been run yet against this db."""
    conn = sqlite3.connect(str(sqlite_db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='grid_nodes'"
        ).fetchone():
            return {}
        return {row["node_id"]: row["subregion_name"] for row in conn.execute("SELECT node_id, subregion_name FROM grid_nodes")}
    finally:
        conn.close()


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
            status TEXT, line_type TEXT, state TEXT, length_miles DOUBLE, subregion_name TEXT, geom GEOMETRY
        )
        """
    )
    conn.execute("DROP TABLE IF EXISTS power_plants")
    conn.execute(
        """
        CREATE TABLE power_plants (
            id INTEGER, plant_name TEXT, fuel_type TEXT, capacity_mw DOUBLE,
            owner TEXT, state TEXT, subregion_name TEXT, geom GEOMETRY
        )
        """
    )
    conn.execute("DROP TABLE IF EXISTS substations")
    conn.execute(
        """
        CREATE TABLE substations (
            id INTEGER, facility_name TEXT, sub_type TEXT, status TEXT,
            county TEXT, state TEXT, max_voltage_kv DOUBLE, min_voltage_kv DOUBLE,
            line_count INTEGER, nearby_line_owners VARCHAR[], subregion_name TEXT, geom GEOMETRY
        )
        """
    )

    if not sqlite_db_path.exists():
        logger.warning(f"No SQLite source at {sqlite_db_path}; power_grid/power_plants/substations will be empty.")
        return {"power_grid": 0, "power_plants": 0, "substations": 0}

    line_columns = ["id", "owner", "voltage", "volt_class", "status", "line_type", "state"]
    sconn = sqlite3.connect(str(sqlite_db_path))
    has_from_node_id = any(row[1] == "from_node_id" for row in sconn.execute("PRAGMA table_info(transmission_lines)"))
    sconn.close()
    if has_from_node_id:
        line_columns.append("from_node_id")
    node_subregion = _load_node_subregions(sqlite_db_path) if has_from_node_id else {}

    line_rows = _load_sqlite_rows(sqlite_db_path, "transmission_lines", line_columns)
    if line_rows:
        reprojected_lines = [
            (row, _reproject_geometry(json.loads(row["geojson_geom"]))) for row in line_rows
        ]
        conn.executemany(
            "INSERT INTO power_grid VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ST_GeomFromGeoJSON(?))",
            [
                (
                    row["id"], row["owner"], row["voltage"], row["volt_class"], row["status"], row["line_type"],
                    row["state"],
                    _geometry_length_miles(geometry),
                    node_subregion.get(row["from_node_id"]) if has_from_node_id else None,
                    json.dumps(geometry),
                )
                for row, geometry in reprojected_lines
            ],
        )

    plant_rows = _load_sqlite_rows(
        sqlite_db_path, "power_plants", ["id", "plant_name", "fuel_type", "capacity_mw", "owner", "state"]
    )
    if plant_rows:
        conn.executemany(
            "INSERT INTO power_plants VALUES (?, ?, ?, ?, ?, ?, NULL, ST_GeomFromGeoJSON(?))",
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
            "INSERT INTO substations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ST_GeomFromGeoJSON(?))",
            [
                (
                    row["id"], row["facility_name"], row["sub_type"], row["status"], row["county"], row["state"],
                    row["max_voltage_kv"], row["min_voltage_kv"], row["line_count"],
                    json.dumps(_reproject_geometry(json.loads(row["geojson_geom"]))),
                )
                for row in substation_rows
            ],
        )

    if line_rows and substation_rows:
        _link_substations_to_nearby_line_owners(conn)
        _infer_line_state_from_nearby_substations(conn)

    subregion_count = build_nerc_subregions_table(conn, sqlite_db_path)

    return {
        "power_grid": len(line_rows),
        "power_plants": len(plant_rows),
        "substations": len(substation_rows),
        "nerc_subregions": subregion_count,
    }


def build_nerc_subregions_table(conn: duckdb.DuckDBPyConnection, sqlite_db_path: Path) -> int:
    """Load the NERC subregion boundary polygons (power/ingest_to_sqlite.py's
    build_nerc_subregions_db) as a map layer — same table power/build_grid_topology.py
    already reads to tag grid_nodes, just exposed here for visual context
    alongside the trace itself.
    """
    conn.execute("DROP TABLE IF EXISTS nerc_subregions")
    conn.execute(
        """
        CREATE TABLE nerc_subregions (
            id INTEGER, nerc_region TEXT, subregion_name TEXT, geom GEOMETRY
        )
        """
    )

    if not sqlite_db_path.exists():
        return 0

    sconn = sqlite3.connect(str(sqlite_db_path))
    sconn.row_factory = sqlite3.Row
    try:
        if not sconn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nerc_subregions'"
        ).fetchone():
            return 0
        rows = sconn.execute(
            "SELECT id, nerc_region, subregion_name, geojson_geom FROM nerc_subregions WHERE geojson_geom IS NOT NULL"
        ).fetchall()
    finally:
        sconn.close()

    if rows:
        conn.executemany(
            "INSERT INTO nerc_subregions VALUES (?, ?, ?, ST_GeomFromGeoJSON(?))",
            [
                (row["id"], row["nerc_region"], row["subregion_name"], json.dumps(_reproject_geometry(json.loads(row["geojson_geom"]))))
                for row in rows
            ],
        )
    return len(rows)


def tag_points_with_nerc_subregion(conn: duckdb.DuckDBPyConnection, table_names: list[str]) -> None:
    """Point-in-polygon tag each table's rows with their NERC subregion,
    against the nerc_subregions polygons already loaded. Call after both
    the target tables and nerc_subregions exist - a no-op if
    nerc_subregions is empty (jurisdiction_nerc_subregion_v1/ wasn't
    available when the topology was built).

    power_grid's subregion_name is set separately, at insert time from
    its from_node_id (see build_power_grid_tables) - a line isn't a
    single point, so a direct polygon test doesn't apply the same way,
    and reusing the trace's own node-based subregion keeps what "in the
    home subregion" means consistent between the map and the trace.
    """
    subregion_count = conn.execute("SELECT COUNT(*) FROM nerc_subregions").fetchone()[0]
    if not subregion_count:
        return
    conn.execute("CREATE INDEX IF NOT EXISTS nerc_subregions_rtree ON nerc_subregions USING RTREE (geom)")
    for table in table_names:
        conn.execute(
            f"""
            UPDATE {table}
            SET subregion_name = (
                SELECT s.subregion_name FROM nerc_subregions s WHERE ST_Contains(s.geom, {table}.geom) LIMIT 1
            )
            """
        )


def _link_substations_to_nearby_line_owners(conn: duckdb.DuckDBPyConnection) -> None:
    """Derive each substation's `nearby_line_owners` from transmission
    lines within SUBSTATION_OWNER_JOIN_BUFFER_DEG. HIFLD substation data
    has no owner field of its own, so this is an inferred/proximity-based
    association, not an authoritative ownership record — a substation can
    legitimately show multiple owners if it's an interconnection point.
    """
    conn.execute("CREATE INDEX IF NOT EXISTS power_grid_geom_rtree ON power_grid USING RTREE (geom)")
    invalid_owners = ", ".join(f"'{v}'" for v in _INVALID_OWNER_VALUES)
    conn.execute(
        f"""
        UPDATE substations
        SET nearby_line_owners = (
            SELECT list(DISTINCT g.owner)
            FROM power_grid g
            WHERE ST_DWithin(substations.geom, g.geom, {SUBSTATION_OWNER_JOIN_BUFFER_DEG})
              AND g.owner NOT IN ({invalid_owners})
        )
        """
    )
    total, resolved = conn.execute(
        "SELECT COUNT(*), COUNT(*) FILTER (len(nearby_line_owners) >= 1) FROM substations"
    ).fetchone()
    logger.info(
        f"Resolved nearby_line_owners for {resolved}/{total} substations "
        f"({100 * resolved / total:.1f}%) within {SUBSTATION_OWNER_JOIN_BUFFER_DEG}deg"
    )


def _infer_line_state_from_nearby_substations(conn: duckdb.DuckDBPyConnection) -> None:
    """HIFLD transmission-line records carry no state property at all (unlike
    substations, which do) - infer each line's state from the nearest
    substation within SUBSTATION_OWNER_JOIN_BUFFER_DEG, the reverse of
    _link_substations_to_nearby_line_owners' lookup. Best-effort/approximate,
    not authoritative - a line can legitimately span into a neighboring state
    past whichever substation happens to be closest.
    """
    conn.execute("CREATE INDEX IF NOT EXISTS substations_geom_rtree ON substations USING RTREE (geom)")
    invalid_states = ", ".join(f"'{v}'" for v in _INVALID_OWNER_VALUES)
    conn.execute(
        f"""
        UPDATE power_grid
        SET state = (
            SELECT s.state
            FROM substations s
            WHERE ST_DWithin(power_grid.geom, s.geom, {SUBSTATION_OWNER_JOIN_BUFFER_DEG})
              AND s.state NOT IN ({invalid_states})
            ORDER BY ST_Distance(power_grid.geom, s.geom)
            LIMIT 1
        )
        WHERE state IN ({invalid_states})
        """
    )
    total, resolved = conn.execute(
        f"SELECT COUNT(*), COUNT(*) FILTER (state NOT IN ({invalid_states})) FROM power_grid"
    ).fetchone()
    logger.info(
        f"Inferred state for {resolved}/{total} transmission lines "
        f"({100 * resolved / total:.1f}%) within {SUBSTATION_OWNER_JOIN_BUFFER_DEG}deg of a substation"
    )
