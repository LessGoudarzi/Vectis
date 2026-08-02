"""Precompute the transmission grid's inferred topology.

HIFLD/EIA transmission-line data has no explicit "connects to" field, so
this clusters line endpoints that sit within ENDPOINT_TOLERANCE_DEG of
each other into shared graph nodes, records each line's from/to node, and
(if jurisdiction_nerc_subregion_v1/ is present) tags each node with its
NERC subregion.

This is the expensive, one-time step behind backend/trace.py's power-plant
network tracing - it does a full endpoint self-join (~4-5 minutes for the
current dataset) and must be run manually, not at backend startup:

    python build_grid_topology.py [--db ../transmission.db]

The 0.0003deg tolerance (~33m at mid-latitudes) was validated against the
real data before this script was written: it produces one dominant
connected component covering 97.8% of all lines, matching the real grid's
few giant synchronous interconnections rather than an arbitrary artifact.
"""

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

import duckdb

ENDPOINT_TOLERANCE_DEG = 0.0003


def _mercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """Inverse Web Mercator projection (same formula used throughout the
    codebase - power/app.py, backend/ingest_power_grid.py)."""
    lon = (x / 20037508.34) * 180.0
    lat = (y / 20037508.34) * 180.0
    lat = 180.0 / math.pi * (2.0 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return lon, lat


def _reproject_coords(coords):
    if (
        len(coords) >= 2
        and isinstance(coords[0], (int, float))
        and isinstance(coords[1], (int, float))
    ):
        return list(_mercator_to_lonlat(coords[0], coords[1]))
    return [_reproject_coords(c) for c in coords]


def _reproject_geometry(geometry: dict) -> dict:
    return {**geometry, "coordinates": _reproject_coords(geometry["coordinates"])}


def _ensure_column(cursor: sqlite3.Cursor, table: str, column: str, coltype: str) -> None:
    existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def _table_exists(cursor: sqlite3.Cursor, table: str) -> bool:
    return cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def build_grid_topology(db_path: str = "transmission.db") -> dict:
    db_path = Path(db_path)

    sconn = sqlite3.connect(str(db_path))
    sconn.row_factory = sqlite3.Row
    line_rows = sconn.execute(
        "SELECT id, geojson_geom FROM transmission_lines WHERE geojson_geom IS NOT NULL"
    ).fetchall()
    subregion_rows = []
    if _table_exists(sconn.cursor(), "nerc_subregions"):
        subregion_rows = sconn.execute(
            "SELECT nerc_region, subregion_name, geojson_geom FROM nerc_subregions WHERE geojson_geom IS NOT NULL"
        ).fetchall()
    sconn.close()
    print(f"{len(line_rows)} transmission lines loaded from {db_path}")

    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL spatial; LOAD spatial;")

    conn.execute("CREATE TABLE lines (id INTEGER, geom GEOMETRY)")
    conn.executemany(
        "INSERT INTO lines VALUES (?, ST_GeomFromGeoJSON(?))",
        [(row["id"], json.dumps(_reproject_geometry(json.loads(row["geojson_geom"])))) for row in line_rows],
    )

    conn.execute("""
        CREATE TABLE endpoints AS
        SELECT
            ROW_NUMBER() OVER () AS endpoint_id,
            line_id, which, geom
        FROM (
            SELECT id AS line_id, 0 AS which, ST_StartPoint((ST_Dump(geom))[1].geom) AS geom FROM lines
            UNION ALL
            SELECT id AS line_id, 1 AS which, ST_EndPoint((ST_Dump(geom))[len(ST_Dump(geom))].geom) AS geom FROM lines
        )
    """)
    conn.execute("CREATE INDEX endpoints_rtree ON endpoints USING RTREE (geom)")
    n_endpoints = conn.execute("SELECT COUNT(*) FROM endpoints").fetchone()[0]
    print(f"{n_endpoints} endpoints indexed")

    print(f"Finding endpoint adjacency pairs within {ENDPOINT_TOLERANCE_DEG}deg (this is the slow step)...")
    pairs = conn.execute(f"""
        SELECT a.endpoint_id, b.endpoint_id
        FROM endpoints a JOIN endpoints b
          ON ST_DWithin(a.geom, b.geom, {ENDPOINT_TOLERANCE_DEG}) AND a.endpoint_id < b.endpoint_id
    """).fetchall()
    print(f"{len(pairs)} adjacency pairs found")

    endpoint_ids = [r[0] for r in conn.execute("SELECT endpoint_id FROM endpoints").fetchall()]
    parent = {e: e for e in endpoint_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in pairs:
        union(a, b)

    endpoint_rows = conn.execute(
        "SELECT endpoint_id, line_id, which, ST_X(geom), ST_Y(geom) FROM endpoints"
    ).fetchall()

    node_coords = defaultdict(list)
    line_endpoints: dict[int, dict[int, int]] = {}
    for endpoint_id, line_id, which, lon, lat in endpoint_rows:
        node_id = find(endpoint_id)
        node_coords[node_id].append((lon, lat))
        line_endpoints.setdefault(line_id, {})[which] = node_id

    node_centroid = {
        node_id: (sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords))
        for node_id, coords in node_coords.items()
    }
    print(f"{len(node_centroid)} distinct graph nodes (from {n_endpoints} endpoints)")

    node_subregion: dict[int, tuple[str, str]] = {}
    if subregion_rows:
        print(f"Tagging nodes with NERC subregion ({len(subregion_rows)} polygons)...")
        conn.execute("CREATE TABLE subregions (sid INTEGER, nerc_region TEXT, subregion_name TEXT, geom GEOMETRY)")
        conn.executemany(
            "INSERT INTO subregions VALUES (?, ?, ?, ST_GeomFromGeoJSON(?))",
            [
                (i, row["nerc_region"], row["subregion_name"], json.dumps(_reproject_geometry(json.loads(row["geojson_geom"]))))
                for i, row in enumerate(subregion_rows)
            ],
        )
        conn.execute("CREATE INDEX subregions_rtree ON subregions USING RTREE (geom)")

        conn.execute("CREATE TABLE node_points (node_id INTEGER, geom GEOMETRY)")
        conn.executemany(
            "INSERT INTO node_points VALUES (?, ST_Point(?, ?))",
            [(node_id, lon, lat) for node_id, (lon, lat) in node_centroid.items()],
        )
        tagged = conn.execute("""
            SELECT n.node_id, s.nerc_region, s.subregion_name
            FROM node_points n JOIN subregions s ON ST_Intersects(n.geom, s.geom)
        """).fetchall()
        for node_id, region, subname in tagged:
            node_subregion[node_id] = (region, subname)
        print(f"{len(node_subregion)}/{len(node_centroid)} nodes tagged with a subregion")
    else:
        print("No NERC subregion data found; skipping tagging (trace will fall back to a mileage cap)")

    write_conn = sqlite3.connect(str(db_path))
    cur = write_conn.cursor()
    cur.execute("DROP TABLE IF EXISTS grid_nodes")
    cur.execute("""
        CREATE TABLE grid_nodes (
            node_id INTEGER PRIMARY KEY,
            lat REAL, lon REAL,
            nerc_region TEXT, subregion_name TEXT
        )
    """)
    cur.executemany(
        "INSERT INTO grid_nodes VALUES (?, ?, ?, ?, ?)",
        [
            (node_id, lat, lon, *node_subregion.get(node_id, (None, None)))
            for node_id, (lon, lat) in node_centroid.items()
        ],
    )

    _ensure_column(cur, "transmission_lines", "from_node_id", "INTEGER")
    _ensure_column(cur, "transmission_lines", "to_node_id", "INTEGER")
    cur.executemany(
        "UPDATE transmission_lines SET from_node_id = ?, to_node_id = ? WHERE id = ?",
        [(endpoints.get(0), endpoints.get(1), line_id) for line_id, endpoints in line_endpoints.items()],
    )
    write_conn.commit()
    write_conn.close()

    print(f"Persisted {len(node_centroid)} grid_nodes and from/to node ids on {len(line_endpoints)} transmission_lines")
    return {"nodes": len(node_centroid), "lines_tagged": len(line_endpoints), "nodes_with_subregion": len(node_subregion)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Precompute transmission grid topology for network tracing")
    parser.add_argument("--db", default="transmission.db", help="Path to the SQLite database")
    args = parser.parse_args()
    build_grid_topology(db_path=args.db)
