import logging
from pathlib import Path

import duckdb

from config import settings
from ingest_auto_plants import build_auto_plants_table
from ingest_industrial_convergence import build_industrial_convergence_table
from ingest_power_grid import build_power_grid_tables, tag_points_with_nerc_subregion
from trace import GridGraph, find_anchor_node, load_grid_graph, trace_from_node

logger = logging.getLogger("uvicorn")

BASE_DIR = Path(__file__).resolve().parent
SAMPLE_INDUSTRIAL_CONVERGENCE_DIR = BASE_DIR / "data" / "sample_industrial_convergence"
POWER_GRID_SQLITE_DB = BASE_DIR.parent / "transmission.db"
AUTO_PLANTS_JSON = BASE_DIR.parent / "auto_facilities_high_yield_defense.json"


class SpatialDatabase:
    def __init__(self):
        self.conn = duckdb.connect(database=':memory:')
        self._geojson_cache: dict = {}
        self._init_spatial()

    def _init_spatial(self):
        logger.info("Initializing DuckDB Spatial Extension...")
        self.conn.execute("INSTALL spatial; LOAD spatial;")
        self._seed_auto_plants()
        self._seed_power_grid()
        # power_grid's subregion_name is set at insert time (from its
        # from_node_id); these three are points, tagged here via
        # point-in-polygon against nerc_subregions now that it exists.
        tag_points_with_nerc_subregion(self.conn, ["power_plants", "substations", "auto_plants"])
        self._seed_industrial_convergence()
        line_length_miles = dict(self.conn.execute("SELECT id, length_miles FROM power_grid").fetchall())
        self.trace_graph: GridGraph = load_grid_graph(POWER_GRID_SQLITE_DB, line_length_miles)

    def _seed_auto_plants(self):
        # Layer: real U.S. automobile assembly/component facilities with
        # defense-conversion research notes. AUTO_PLANTS_JSON is generated
        # by ../build_high_yield_facilities.py (see that file's docstring) -
        # currently 72 hand-researched facilities; NAICS-derived scope-up
        # is blocked on re-geocoding the master source file (its lat/lon
        # are broken dataset-wide), not on this ingestion code.
        count = build_auto_plants_table(self.conn, AUTO_PLANTS_JSON)
        logger.info(f"Loaded {count} automobile facilities from {AUTO_PLANTS_JSON}")

    def _seed_power_grid(self):
        # Layers 2 & 3: real EIA/HIFLD transmission-line and power-plant
        # data, ingested by power/ingest_to_sqlite.py into SQLite and
        # reprojected from Web Mercator here. Replaces the old power_grid
        # mock entirely and adds power_plants as a new layer.
        counts = build_power_grid_tables(self.conn, POWER_GRID_SQLITE_DB)
        logger.info(
            f"Loaded {counts['power_grid']} transmission lines, "
            f"{counts['power_plants']} power plants, {counts['substations']} "
            f"substations, and {counts['nerc_subregions']} NERC subregions from {POWER_GRID_SQLITE_DB}"
        )

    def _seed_industrial_convergence(self):
        # Layer 3: Vectis Yield agent-swarm output (auto/defense/robotics/
        # energy convergence). Reads validated payloads dropped by
        # agent-ceo; falls back to bundled sample data if none exist yet,
        # the same cascading pattern power/app.py uses for its real vs.
        # sample GeoJSON sources.
        payload_dir = BASE_DIR / settings.INDUSTRIAL_CONVERGENCE_PAYLOAD_DIR
        count = build_industrial_convergence_table(
            self.conn,
            payload_dir=payload_dir,
            fallback_payload_dir=SAMPLE_INDUSTRIAL_CONVERGENCE_DIR,
        )
        logger.info(f"Loaded {count} industrial convergence facility payload(s) from {payload_dir}")

    def refresh_industrial_convergence(self):
        """Re-ingest agent payloads without restarting the process."""
        self._seed_industrial_convergence()

    # ~1.1m grid — snaps every layer's coordinates down from float64's ~14
    # decimal digits (physically meaningless at this scale) to something
    # actually relevant for a national-grid-scale map, shrinking the GeoJSON
    # text substantially before it's even simplified.
    _COORD_PRECISION = 0.00001
    # Douglas-Peucker tolerance per table, applied on top of the precision
    # snap above. No-ops on point geometries (auto_plants/power_plants/
    # substations), so only line/polygon tables actually shrink further.
    # nerc_subregions is background-only context (never precisely
    # inspected), so it tolerates a much coarser ~11m simplification than
    # power_grid's transmission lines (~3m, imperceptible at any real
    # zoom but still recognizably the same route).
    _SIMPLIFY_TOLERANCE = {
        "nerc_subregions": 0.0001,
    }
    _DEFAULT_SIMPLIFY_TOLERANCE = 0.00003

    def get_layer_geojson(self, table_name: str, bbox: tuple = None) -> str:
        # These tables are only ever (re)built at startup, never mutated
        # in place, so caching per (table, bbox) is safe for the process
        # lifetime — avoids re-running the json_group_array aggregation
        # (and the ST_AsGeoJSON pass over every geometry) on every request
        # for the same viewport/layer.
        cache_key = (table_name, bbox)
        cached = self._geojson_cache.get(cache_key)
        if cached is not None:
            return cached

        bbox_filter = ""
        if bbox:
            min_lon, min_lat, max_lon, max_lat = bbox
            bbox_filter = f"WHERE ST_Intersects(geom, ST_MakeEnvelope({min_lon}, {min_lat}, {max_lon}, {max_lat}))"

        tolerance = self._SIMPLIFY_TOLERANCE.get(table_name, self._DEFAULT_SIMPLIFY_TOLERANCE)
        geom_expr = f"ST_SimplifyPreserveTopology(ST_ReducePrecision(g.geom, {self._COORD_PRECISION}), {tolerance})"

        # `rowid`-correlated LATERAL join, rather than a plain `to_json(t)`
        # on the full row, so the geometry (already emitted once as GeoJSON
        # coordinates) isn't also duplicated as WKT text inside every
        # feature's properties — that duplication alone was ~7% of the
        # auto_plants payload.
        query = f'''
            WITH filtered AS (
                SELECT rowid AS _rid, * FROM {table_name} t
                {bbox_filter}
            )
            SELECT json_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_group_array(
                    json_object(
                        'type', 'Feature',
                        'geometry', json(ST_AsGeoJSON({geom_expr})),
                        'properties', json(to_json(p))
                    )
                ), json_array())
            ) AS geojson
            FROM filtered g,
            LATERAL (SELECT * EXCLUDE (geom, _rid) FROM filtered f WHERE f._rid = g._rid) p;
        '''
        result = self.conn.execute(query).fetchone()
        geojson = result[0] if result and result[0] else '{"type": "FeatureCollection", "features": []}'
        self._geojson_cache[cache_key] = geojson
        return geojson

    def get_industrial_convergence_geojson(
        self,
        bbox: tuple = None,
        corridor: str = None,
        energy_bottleneck_flag: bool = None,
    ) -> str:
        # Mirrors power/app.py's pattern of layering optional equality
        # filters (owner, voltage_bucket, ...) onto the base bbox query
        # rather than forcing every filter combination through one
        # generic WHERE clause builder.
        conditions = []
        params = []
        if bbox:
            min_lon, min_lat, max_lon, max_lat = bbox
            conditions.append("ST_Intersects(geom, ST_MakeEnvelope(?, ?, ?, ?))")
            params.extend([min_lon, min_lat, max_lon, max_lat])
        if corridor:
            conditions.append("corridor = ?")
            params.append(corridor)
        if energy_bottleneck_flag is not None:
            conditions.append("energy_bottleneck_flag = ?")
            params.append(bool(energy_bottleneck_flag))

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f'''
            SELECT json_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_group_array(
                    json_object(
                        'type', 'Feature',
                        'geometry', json(ST_AsGeoJSON(geom)),
                        'properties', json(to_json(t))
                    )
                ), json_array())
            ) AS geojson
            FROM industrial_convergence t
            {where_clause};
        '''
        result = self.conn.execute(query, params).fetchone()
        return result[0] if result and result[0] else '{"type": "FeatureCollection", "features": []}'

    # Any layer with point geometry can be a trace origin, not just power
    # plants — table name is interpolated below, so this whitelist is
    # also what stands between the URL path param and SQL injection.
    TRACE_SOURCE_TABLES = {"power-plants": "power_plants", "auto-plants": "auto_plants"}

    def trace_facility(self, layer_id: str, facility_id: int, max_miles: float, allow_cross_subregion: bool = False) -> dict:
        table_name = self.TRACE_SOURCE_TABLES.get(layer_id)
        if table_name is None:
            return {"status": "not_found"}
        if not self.trace_graph.available:
            return {"status": "unavailable", "detail": "Grid topology not built — run power/build_grid_topology.py."}

        row = self.conn.execute(
            f"SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat FROM {table_name} WHERE id = ?", [facility_id]
        ).fetchone()
        if row is None:
            return {"status": "not_found"}

        anchor = find_anchor_node(self.trace_graph, plant_lon=row[0], plant_lat=row[1])
        if anchor is None:
            return {"status": "not_connected"}

        return trace_from_node(self.trace_graph, anchor, max_miles=max_miles, allow_cross_subregion=allow_cross_subregion)

    def get_corridor_summary(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT corridor, facility_count, total_estimated_output_usd, avg_line_flexibility_score, bottleneck_count "
            "FROM industrial_convergence_corridor_summary"
        ).fetchall()
        columns = [desc[0] for desc in self.conn.description]
        return [dict(zip(columns, row)) for row in rows]


db = SpatialDatabase()
