import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from ingest_to_sqlite import build_power_plants_db, build_transmission_db


class IngestToSqliteTests(unittest.TestCase):
    def test_app_imports_when_started_from_parent_directory(self):
        repo_root = Path(__file__).resolve().parents[1]
        app_path = repo_root / "power" / "app.py"
        previous_cwd = os.getcwd()
        os.chdir(repo_root)
        try:
            spec = importlib.util.spec_from_file_location("power_app", app_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertTrue(hasattr(module, "app"))
        finally:
            os.chdir(previous_cwd)

    def test_build_transmission_db_persists_line_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            geojson_path = tmpdir / "sample.geojson"
            db_path = tmpdir / "transmission.db"

            payload = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "OWNER": "Test Utility",
                            "VOLTAGE": 230,
                            "VOLT_CLASS": "230 kV",
                            "STATUS": "Active",
                            "STATE": "TX",
                            "TYPE": "OVERHEAD",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-100.0, 30.0], [-99.0, 31.0]],
                        },
                    }
                ],
            }
            geojson_path.write_text(json.dumps(payload))

            build_transmission_db(geojson_path=str(geojson_path), db_path=str(db_path))

            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT line_type FROM transmission_lines LIMIT 1").fetchone()
            conn.close()

            self.assertEqual(row[0], "OVERHEAD")

    def test_build_transmission_db_uses_existing_local_source_when_forced(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            geojson_path = tmpdir / "existing.geojson"
            db_path = tmpdir / "transmission.db"

            payload = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "OWNER": "Local Override",
                            "VOLTAGE": 230,
                            "VOLT_CLASS": "230 kV",
                            "STATUS": "Active",
                            "STATE": "TX",
                            "TYPE": "OVERHEAD",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-100.0, 30.0], [-99.0, 31.0]],
                        },
                    }
                ],
            }
            geojson_path.write_text(json.dumps(payload))

            build_transmission_db(geojson_path=str(geojson_path), db_path=str(db_path), force_download=True)

            conn = sqlite3.connect(db_path)
            owners = conn.execute("SELECT owner FROM transmission_lines").fetchall()
            conn.close()

            self.assertIn(("Local Override",), owners)

    def test_build_transmission_db_writes_json_export(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            geojson_path = tmpdir / "sample.geojson"
            db_path = tmpdir / "transmission.db"

            payload = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "OWNER": "Export Utility",
                            "VOLTAGE": 345,
                            "VOLT_CLASS": "345 kV",
                            "STATUS": "Active",
                            "STATE": "TX",
                            "TYPE": "OVERHEAD",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-100.0, 30.0], [-99.0, 31.0]],
                        },
                    }
                ],
            }
            geojson_path.write_text(json.dumps(payload))

            build_transmission_db(geojson_path=str(geojson_path), db_path=str(db_path))

            json_output = geojson_path.with_suffix(".json")
            self.assertTrue(json_output.exists())
            data = json.loads(json_output.read_text())
            self.assertEqual(data["type"], "FeatureCollection")

    def test_build_transmission_db_filters_out_non_contiguous_states(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            geojson_path = tmpdir / "sample.geojson"
            db_path = tmpdir / "transmission.db"

            payload = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "OWNER": "Test Utility",
                            "VOLTAGE": 230,
                            "VOLT_CLASS": "230 kV",
                            "STATUS": "Active",
                            "STATE": "TX",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-100.0, 30.0], [-99.0, 31.0]],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {
                            "OWNER": "Territory Utility",
                            "VOLTAGE": 345,
                            "VOLT_CLASS": "345 kV",
                            "STATUS": "Active",
                            "STATE": "AK",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-150.0, 60.0], [-149.0, 61.0]],
                        },
                    },
                ],
            }
            geojson_path.write_text(json.dumps(payload))

            build_transmission_db(geojson_path=str(geojson_path), db_path=str(db_path))

            conn = sqlite3.connect(db_path)
            row_count = conn.execute("SELECT COUNT(*) FROM transmission_lines").fetchone()[0]
            conn.close()

            self.assertEqual(row_count, 1)

    def test_home_page_includes_guided_loading_controls(self):
        template_path = Path(__file__).resolve().parents[1] / "power" / "templates" / "index.html"
        html = template_path.read_text()

        self.assertIn("Display selection", html)
        self.assertIn("Map actions", html)
        self.assertIn("Pick layers and filters", html)

    def test_api_lines_can_include_missing_voltage_rows_when_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            db_path = tmpdir / "transmission.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE transmission_lines (
                    id INTEGER PRIMARY KEY,
                    owner TEXT,
                    voltage REAL,
                    volt_class TEXT,
                    status TEXT,
                    state TEXT,
                    line_type TEXT,
                    geojson_geom TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO transmission_lines (id, owner, voltage, volt_class, status, state, line_type, geojson_geom) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (1, "Utility A", 230, "230 kV", "Active", "TX", "OVERHEAD", '{"type":"LineString","coordinates":[[0,0],[1,1]]}'),
            )
            conn.execute(
                "INSERT INTO transmission_lines (id, owner, voltage, volt_class, status, state, line_type, geojson_geom) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (2, "Utility B", -999999, "Unknown", "Active", "TX", "UNDERGROUND", '{"type":"LineString","coordinates":[[2,2],[3,3]]}'),
            )
            conn.commit()
            conn.close()

            app_path = Path(__file__).resolve().parents[1] / "power" / "app.py"
            previous_cwd = os.getcwd()
            os.chdir(Path(__file__).resolve().parents[1])
            try:
                spec = importlib.util.spec_from_file_location("power_app", app_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.DB_PATH = str(db_path)
                client = module.app.test_client()

                response = client.get("/api/lines")
                self.assertEqual(len(response.get_json()["features"]), 1)

                response = client.get("/api/lines?include_missing_voltage=1")
                self.assertEqual(len(response.get_json()["features"]), 2)
            finally:
                os.chdir(previous_cwd)

    def test_api_lines_normalizes_projected_geometries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            db_path = tmpdir / "transmission.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE transmission_lines (
                    id INTEGER PRIMARY KEY,
                    owner TEXT,
                    voltage REAL,
                    volt_class TEXT,
                    status TEXT,
                    state TEXT,
                    line_type TEXT,
                    geojson_geom TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO transmission_lines (id, owner, voltage, volt_class, status, state, line_type, geojson_geom) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (1, "Utility A", 230, "230 kV", "Active", "TX", "OVERHEAD", '{"type":"LineString","coordinates":[[-9397293.05,5271551.21],[-9397292.75,5272179.74]]}'),
            )
            conn.commit()
            conn.close()

            app_path = Path(__file__).resolve().parents[1] / "power" / "app.py"
            previous_cwd = os.getcwd()
            os.chdir(Path(__file__).resolve().parents[1])
            try:
                spec = importlib.util.spec_from_file_location("power_app", app_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.DB_PATH = str(db_path)
                client = module.app.test_client()

                response = client.get("/api/lines")
                payload = response.get_json()
                coords = payload["features"][0]["geometry"]["coordinates"]
                self.assertLess(abs(coords[0][0]), 180)
                self.assertLess(abs(coords[0][1]), 90)
            finally:
                os.chdir(previous_cwd)

    def test_api_lines_returns_a_preview_limit_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            db_path = tmpdir / "transmission.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE transmission_lines (
                    id INTEGER PRIMARY KEY,
                    owner TEXT,
                    voltage REAL,
                    volt_class TEXT,
                    status TEXT,
                    state TEXT,
                    line_type TEXT,
                    geojson_geom TEXT
                )
                """
            )
            for index in range(300):
                conn.execute(
                    "INSERT INTO transmission_lines (id, owner, voltage, volt_class, status, state, line_type, geojson_geom) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (index + 1, f"Utility {index}", 230, "230 kV", "Active", "TX", "OVERHEAD", '{"type":"LineString","coordinates":[[0,0],[1,1]]}'),
                )
            conn.commit()
            conn.close()

            app_path = Path(__file__).resolve().parents[1] / "power" / "app.py"
            previous_cwd = os.getcwd()
            os.chdir(Path(__file__).resolve().parents[1])
            try:
                spec = importlib.util.spec_from_file_location("power_app", app_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.DB_PATH = str(db_path)
                client = module.app.test_client()

                response = client.get("/api/lines")
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertLessEqual(len(payload["features"]), 250)
                self.assertEqual(payload["meta"]["total_count"], 300)
                self.assertTrue(payload["meta"]["is_preview"])
            finally:
                os.chdir(previous_cwd)

    def test_api_lines_respects_viewport_bounds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            db_path = tmpdir / "transmission.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE transmission_lines (
                    id INTEGER PRIMARY KEY,
                    owner TEXT,
                    voltage REAL,
                    volt_class TEXT,
                    status TEXT,
                    state TEXT,
                    line_type TEXT,
                    geojson_geom TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO transmission_lines (id, owner, voltage, volt_class, status, state, line_type, geojson_geom) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (1, "Utility A", 230, "230 kV", "Active", "TX", "OVERHEAD", '{"type":"LineString","coordinates":[[-100,30],[-99,31]]}'),
            )
            conn.execute(
                "INSERT INTO transmission_lines (id, owner, voltage, volt_class, status, state, line_type, geojson_geom) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (2, "Utility B", 230, "230 kV", "Active", "TX", "OVERHEAD", '{"type":"LineString","coordinates":[[10,10],[11,11]]}'),
            )
            conn.commit()
            conn.close()

            app_path = Path(__file__).resolve().parents[1] / "power" / "app.py"
            previous_cwd = os.getcwd()
            os.chdir(Path(__file__).resolve().parents[1])
            try:
                spec = importlib.util.spec_from_file_location("power_app", app_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.DB_PATH = str(db_path)
                client = module.app.test_client()

                response = client.get("/api/lines?min_lon=-101&max_lon=-98&min_lat=29&max_lat=32")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.get_json()["features"]), 1)
                self.assertEqual(response.get_json()["features"][0]["properties"]["owner"], "Utility A")
            finally:
                os.chdir(previous_cwd)

    def test_api_power_plants_returns_features(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            geojson_path = tmpdir / "plants.geojson"
            db_path = tmpdir / "transmission.db"
            payload = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "plant_name": "Sample Plant",
                            "primsource": "natural gas",
                            "source_des": "Natural Gas = 250 MW",
                            "total_mw": 250.0,
                            "utility_na": "Plant Co",
                            "sector_nam": "Electric Utility",
                            "state": "CA",
                        },
                        "geometry": {"type": "Point", "coordinates": [-120.0, 35.0]},
                    }
                ],
            }
            geojson_path.write_text(json.dumps(payload))
            build_power_plants_db(geojson_path=str(geojson_path), db_path=str(db_path))

            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT plant_name, fuel_type, fuel_source, capacity_mw, owner, utility_name, sector_name FROM power_plants LIMIT 1").fetchone()
            summary = conn.execute("SELECT fuel_type, plant_count, total_capacity_mw FROM power_plant_fuel_summary LIMIT 1").fetchone()
            conn.close()

            self.assertEqual(row[0], "Sample Plant")
            self.assertEqual(row[1], "Natural Gas")
            self.assertEqual(row[2], "natural gas")
            self.assertEqual(row[3], 250.0)
            self.assertEqual(row[4], "Plant Co")
            self.assertEqual(row[5], "Plant Co")
            self.assertEqual(row[6], "Electric Utility")
            self.assertEqual(summary[0], "Natural Gas")
            self.assertEqual(summary[1], 1)
            self.assertEqual(summary[2], 250.0)

            app_path = Path(__file__).resolve().parents[1] / "power" / "app.py"
            previous_cwd = os.getcwd()
            os.chdir(Path(__file__).resolve().parents[1])
            try:
                spec = importlib.util.spec_from_file_location("power_app", app_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.DB_PATH = str(db_path)
                client = module.app.test_client()

                response = client.get("/api/power-plants")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(len(response.get_json()["features"]) >= 1)
                self.assertTrue(bool(response.get_json()["features"][0]["properties"]["plant_name"]))
                self.assertEqual(response.get_json()["features"][0]["properties"]["fuel_type"], "Natural Gas")
            finally:
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
