import logging
from pathlib import Path

import duckdb

from config import settings
from ingest_industrial_convergence import build_industrial_convergence_table
from ingest_power_grid import build_power_grid_tables

logger = logging.getLogger("uvicorn")

BASE_DIR = Path(__file__).resolve().parent
SAMPLE_INDUSTRIAL_CONVERGENCE_DIR = BASE_DIR / "data" / "sample_industrial_convergence"
POWER_GRID_SQLITE_DB = BASE_DIR.parent / "transmission.db"


class SpatialDatabase:
    def __init__(self):
        self.conn = duckdb.connect(database=':memory:')
        self._init_spatial()

    def _init_spatial(self):
        logger.info("Initializing DuckDB Spatial Extension...")
        self.conn.execute("INSTALL spatial; LOAD spatial;")
        self._seed_mock_layers()
        self._seed_power_grid()
        self._seed_industrial_convergence()

    def _seed_mock_layers(self):
        # Layer 1: Automobile Assembly Plants (still mock — no real
        # per-facility dataset for this yet, unlike power_grid/power_plants)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS auto_plants AS
            SELECT id, name, brand, capacity, ST_Point(lon, lat) as geom
            FROM (VALUES
                (1, 'Detroit Assembly Complex', 'Stellantis', 350000, -82.9780, 42.3664),
                (2, 'Smyrna Assembly Plant', 'Nissan', 640000, -86.5186, 35.9828),
                (3, 'Gigafactory Texas', 'Tesla', 500000, -97.6171, 30.2223),
                (4, 'Chattanooga Plant', 'Volkswagen', 250000, -85.1328, 35.0806),
                (5, 'Greer Plant', 'BMW', 450000, -82.2263, 34.8958)
            ) AS t(id, name, brand, capacity, lon, lat);
        ''')

    def _seed_power_grid(self):
        # Layers 2 & 3: real EIA/HIFLD transmission-line and power-plant
        # data, ingested by power/ingest_to_sqlite.py into SQLite and
        # reprojected from Web Mercator here. Replaces the old power_grid
        # mock entirely and adds power_plants as a new layer.
        counts = build_power_grid_tables(self.conn, POWER_GRID_SQLITE_DB)
        logger.info(
            f"Loaded {counts['power_grid']} transmission lines, "
            f"{counts['power_plants']} power plants, and {counts['substations']} "
            f"substations from {POWER_GRID_SQLITE_DB}"
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

    def get_layer_geojson(self, table_name: str, bbox: tuple = None) -> str:
        bbox_filter = ""
        if bbox:
            min_lon, min_lat, max_lon, max_lat = bbox
            bbox_filter = f"WHERE ST_Intersects(geom, ST_MakeEnvelope({min_lon}, {min_lat}, {max_lon}, {max_lat}))"

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
            FROM {table_name} t
            {bbox_filter};
        '''
        result = self.conn.execute(query).fetchone()
        return result[0] if result and result[0] else '{"type": "FeatureCollection", "features": []}'

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

    def get_corridor_summary(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT corridor, facility_count, total_estimated_output_usd, avg_line_flexibility_score, bottleneck_count "
            "FROM industrial_convergence_corridor_summary"
        ).fetchall()
        columns = [desc[0] for desc in self.conn.description]
        return [dict(zip(columns, row)) for row in rows]


db = SpatialDatabase()
