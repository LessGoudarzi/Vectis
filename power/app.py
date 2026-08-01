from flask import Flask, jsonify, make_response, render_template, request
import hashlib
import json
import math
import os
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from .ingest_to_sqlite import build_power_plants_db, build_transmission_db
except ImportError:
    from ingest_to_sqlite import build_power_plants_db, build_transmission_db

app = Flask(__name__)

DB_PATH = str(BASE_DIR / "transmission.db")
REAL_GEOJSON = str(BASE_DIR / "Electric_Power_Transmission_Lines.geojson")
SAMPLE_GEOJSON = str(BASE_DIR / "sample_data.geojson")
GEM_TRANSMISSION_GPKG = str(BASE_DIR / "transmission_line_eia_v1" / "transmission_line_eia_v1.gpkg")


def _voltage_bucket(voltage):
    if voltage is None:
        return "Unknown"
    if voltage >= 500:
        return "500+ kV"
    if voltage >= 345:
        return "345-499 kV"
    if voltage >= 230:
        return "230-344 kV"
    if voltage >= 161:
        return "161-229 kV"
    if voltage >= 69:
        return "69-160 kV"
    return "Under 69 kV"


def _capacity_bucket(capacity_mw):
    if capacity_mw is None:
        return "Unknown"
    if capacity_mw < 10:
        return "0-10 MW"
    if capacity_mw < 50:
        return "10-50 MW"
    if capacity_mw < 100:
        return "50-100 MW"
    if capacity_mw < 250:
        return "100-250 MW"
    if capacity_mw < 500:
        return "250-500 MW"
    if capacity_mw < 1000:
        return "500-1000 MW"
    return "1000+ MW"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _extract_geometry_coords(geometry, coords=None):
    if coords is None:
        coords = []
    if isinstance(geometry, dict):
        if "coordinates" in geometry:
            return _extract_geometry_coords(geometry["coordinates"], coords)
        for value in geometry.values():
            _extract_geometry_coords(value, coords)
    elif isinstance(geometry, (list, tuple)):
        if len(geometry) >= 2 and all(isinstance(item, (int, float)) for item in geometry[:2]):
            coords.append((float(geometry[0]), float(geometry[1])))
            return coords
        for item in geometry:
            _extract_geometry_coords(item, coords)
    return coords


def _mercator_to_lonlat(x, y):
    lon = (x / 20037508.34) * 180.0
    lat = (y / 20037508.34) * 180.0
    lat = 180.0 / math.pi * (2.0 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return [lon, lat]


def _normalize_geometry_coords(geometry):
    if isinstance(geometry, dict):
        geometry_type = geometry.get("type")
        if geometry_type == "GeometryCollection":
            return {
                **geometry,
                "geometries": [_normalize_geometry_coords(item) for item in geometry.get("geometries", [])],
            }
        if "coordinates" in geometry:
            return {**geometry, "coordinates": _normalize_geometry_coords(geometry["coordinates"])}
        return geometry
    if isinstance(geometry, (list, tuple)):
        if len(geometry) >= 2 and all(isinstance(item, (int, float)) for item in geometry[:2]):
            x, y = float(geometry[0]), float(geometry[1])
            if abs(x) > 180 or abs(y) > 90:
                return _mercator_to_lonlat(x, y)
            return [x, y]
        return [_normalize_geometry_coords(item) for item in geometry]
    return geometry


def _geometry_bounds(geometry):
    coords = _extract_geometry_coords(geometry)
    if not coords:
        return None
    lons = [coord[0] for coord in coords]
    lats = [coord[1] for coord in coords]
    return {
        "min_lon": min(lons),
        "max_lon": max(lons),
        "min_lat": min(lats),
        "max_lat": max(lats),
    }


def _intersects_bounds(geometry_bounds, selection_bounds):
    if not geometry_bounds:
        return False
    return not (
        geometry_bounds["max_lon"] < selection_bounds["min_lon"]
        or geometry_bounds["min_lon"] > selection_bounds["max_lon"]
        or geometry_bounds["max_lat"] < selection_bounds["min_lat"]
        or geometry_bounds["min_lat"] > selection_bounds["max_lat"]
    )


def _map_geometry(geometry):
    return _normalize_geometry_coords(geometry)


def _stable_sample_score(item_id):
    token = str(item_id).encode("utf-8")
    digest = hashlib.md5(token).hexdigest()
    return int(digest[:8], 16)


def ensure_db_exists():
    db_exists = os.path.exists(DB_PATH)
    needs_transmission = not db_exists
    needs_power_plants = not db_exists

    if db_exists:
        conn = sqlite3.connect(DB_PATH)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        needs_transmission = "transmission_lines" not in tables
        needs_power_plants = "power_plants" not in tables

        db_mtime = os.path.getmtime(DB_PATH)
        transmission_source = next((path for path in [GEM_TRANSMISSION_GPKG, REAL_GEOJSON, SAMPLE_GEOJSON] if os.path.exists(path)), None)
        power_source = next((path for path in [str(BASE_DIR / "plant_power_eia_v9" / "plant_power_eia_v9.gpkg")] if os.path.exists(path)), None)

        if transmission_source and os.path.getmtime(transmission_source) > db_mtime:
            needs_transmission = True
        if power_source and os.path.getmtime(power_source) > db_mtime:
            needs_power_plants = True

    if needs_transmission:
        candidate_paths = [
            GEM_TRANSMISSION_GPKG,
            REAL_GEOJSON,
            SAMPLE_GEOJSON,
        ]
        source_path = next((path for path in candidate_paths if os.path.exists(path)), GEM_TRANSMISSION_GPKG)
        build_transmission_db(geojson_path=source_path, db_path=DB_PATH)

    if needs_power_plants:
        build_power_plants_db(db_path=DB_PATH)


ensure_db_exists()


@app.route("/")
def home():
    response = make_response(render_template("index.html"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/api/bucket-summaries")
def api_bucket_summaries():
    ensure_db_exists()
    conn = get_db_connection()

    transmission_voltage_rows = conn.execute(
        """
        SELECT
            CASE
                WHEN voltage IS NULL OR voltage < 0 THEN 'Unknown'
                WHEN voltage < 69 THEN 'Under 69 kV'
                WHEN voltage < 161 THEN '69-160 kV'
                WHEN voltage < 230 THEN '161-229 kV'
                WHEN voltage < 345 THEN '230-344 kV'
                WHEN voltage < 500 THEN '345-499 kV'
                ELSE '500+ kV'
            END AS bucket,
            COUNT(*) AS count
        FROM transmission_lines
        GROUP BY bucket
        ORDER BY CASE bucket
            WHEN '500+ kV' THEN 1
            WHEN '345-499 kV' THEN 2
            WHEN '230-344 kV' THEN 3
            WHEN '161-229 kV' THEN 4
            WHEN '69-160 kV' THEN 5
            WHEN 'Under 69 kV' THEN 6
            ELSE 7
        END
        """
    ).fetchall()

    transmission_line_type_rows = conn.execute(
        """
        SELECT
            CASE
                WHEN UPPER(COALESCE(line_type, 'UNKNOWN')) LIKE '%UNDERGROUND%' THEN 'Underground'
                WHEN UPPER(COALESCE(line_type, 'UNKNOWN')) LIKE '%OVERHEAD%' THEN 'Overhead'
                ELSE 'Other'
            END AS bucket,
            COUNT(*) AS count
        FROM transmission_lines
        GROUP BY bucket
        ORDER BY CASE bucket WHEN 'Overhead' THEN 1 WHEN 'Underground' THEN 2 ELSE 3 END
        """
    ).fetchall()

    power_fuel_rows = conn.execute(
        """
        SELECT fuel_type, plant_count, total_capacity_mw, avg_capacity_mw, max_capacity_mw
        FROM power_plant_fuel_summary
        ORDER BY plant_count DESC, total_capacity_mw DESC, fuel_type
        """
    ).fetchall()

    power_capacity_rows = conn.execute(
        """
        SELECT fuel_type, capacity_bucket, plant_count, total_capacity_mw
        FROM power_plant_fuel_capacity_buckets
        ORDER BY fuel_type, plant_count DESC, capacity_bucket
        """
    ).fetchall()

    conn.close()

    response = jsonify({
        "transmission": {
            "voltage_buckets": [dict(row) for row in transmission_voltage_rows],
            "line_type_buckets": [dict(row) for row in transmission_line_type_rows],
        },
        "power_plants": {
            "fuel_buckets": [dict(row) for row in power_fuel_rows],
            "capacity_buckets": [dict(row) for row in power_capacity_rows],
        },
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/lines")
def api_lines():
    ensure_db_exists()
    min_voltage = request.args.get("min_voltage", default=0, type=int)
    owner_filter = request.args.get("owner", default="", type=str)
    voltage_bucket_filter = request.args.get("voltage_bucket", default="", type=str)
    voltage_category_filter = request.args.get("voltage_category", default="", type=str)
    line_type_filter = request.args.get("line_type", default="", type=str)
    include_missing_voltage = request.args.get("include_missing_voltage", default="0", type=str).lower() in {"1", "true", "yes", "on"}
    preview_limit = request.args.get("limit", default=250, type=int)
    preview_limit = max(1, min(preview_limit, 2500))
    viewport_bounds = {
        "min_lon": request.args.get("min_lon", default=None, type=float),
        "max_lon": request.args.get("max_lon", default=None, type=float),
        "min_lat": request.args.get("min_lat", default=None, type=float),
        "max_lat": request.args.get("max_lat", default=None, type=float),
    }

    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT id, owner, voltage, volt_class, status, state, line_type, geojson_geom FROM transmission_lines"
    params = []

    if include_missing_voltage:
        query += " WHERE (voltage >= ? OR (voltage < 0 AND ? = 1))"
        params.extend([min_voltage, 1])
    else:
        query += " WHERE voltage >= ?"
        params.append(min_voltage)

    if owner_filter:
        query += " AND owner = ?"
        params.append(owner_filter)

    rows = cursor.execute(query, params).fetchall()
    conn.close()

    sampled_features = []
    total_count = 0
    for row in rows:
        if not row["geojson_geom"]:
            continue

        geometry = json.loads(row["geojson_geom"])
        map_geometry = _map_geometry(geometry)
        geometry_bounds = _geometry_bounds(map_geometry)
        if all(viewport_bounds[key] is not None for key in ["min_lon", "max_lon", "min_lat", "max_lat"]):
            if not geometry_bounds or not _intersects_bounds(geometry_bounds, viewport_bounds):
                continue

        voltage_bucket = _voltage_bucket(row["voltage"])
        if voltage_bucket_filter and voltage_bucket != voltage_bucket_filter:
            continue
        if voltage_category_filter and voltage_bucket != voltage_category_filter:
            continue
        if line_type_filter and str(row["line_type"] or "UNKNOWN").upper() != line_type_filter.upper():
            continue

        total_count += 1
        feature = {
            "type": "Feature",
            "properties": {
                "id": row["id"],
                "owner": row["owner"],
                "voltage": row["voltage"],
                "volt_class": row["volt_class"],
                "voltage_bucket": voltage_bucket,
                "status": row["status"],
                "state": row["state"],
                "line_type": row["line_type"],
            },
            "geometry": map_geometry,
        }

        if len(sampled_features) < preview_limit:
            sampled_features.append((_stable_sample_score(row["id"]), feature))
        else:
            candidate_score = _stable_sample_score(row["id"])
            worst_index, worst_entry = max(enumerate(sampled_features), key=lambda item: item[1][0])
            if candidate_score < worst_entry[0]:
                sampled_features[worst_index] = (candidate_score, feature)

    sampled_features.sort(key=lambda item: item[0])
    features = [item[1] for item in sampled_features]

    response = jsonify({
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "total_count": total_count,
            "is_preview": total_count > len(features),
            "limit": preview_limit,
        },
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/power-plants")
def api_power_plants():
    ensure_db_exists()
    preview_limit = request.args.get("limit", default=250, type=int)
    preview_limit = max(1, min(preview_limit, 2500))
    viewport_bounds = {
        "min_lon": request.args.get("min_lon", default=None, type=float),
        "max_lon": request.args.get("max_lon", default=None, type=float),
        "min_lat": request.args.get("min_lat", default=None, type=float),
        "max_lat": request.args.get("max_lat", default=None, type=float),
    }
    fuel_type_filter = request.args.get("fuel_type", default="", type=str).strip()
    capacity_bucket_filter = request.args.get("capacity_bucket", default="", type=str).strip()

    conn = get_db_connection()
    rows = conn.execute("SELECT id, plant_name, fuel_type, capacity_mw, owner, state, geojson_geom FROM power_plants").fetchall()
    conn.close()

    features = []
    total_count = 0
    for row in rows:
        if not row["geojson_geom"]:
            continue
        geometry = json.loads(row["geojson_geom"])
        map_geometry = _map_geometry(geometry)
        geometry_bounds = _geometry_bounds(map_geometry)
        if all(viewport_bounds[key] is not None for key in ["min_lon", "max_lon", "min_lat", "max_lat"]):
            if not geometry_bounds or not _intersects_bounds(geometry_bounds, viewport_bounds):
                continue
        if fuel_type_filter and str(row["fuel_type"] or "").strip().lower() != fuel_type_filter.lower():
            continue
        capacity_bucket = None
        if row["capacity_mw"] is not None:
            capacity_bucket = _capacity_bucket(float(row["capacity_mw"]))
        else:
            capacity_bucket = "Unknown"
        if capacity_bucket_filter and capacity_bucket != capacity_bucket_filter:
            continue
        total_count += 1
        if len(features) < preview_limit:
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": row["id"],
                        "plant_name": row["plant_name"],
                        "fuel_type": row["fuel_type"],
                        "capacity_mw": row["capacity_mw"],
                        "capacity_bucket": capacity_bucket,
                        "owner": row["owner"],
                        "state": row["state"],
                    },
                    "geometry": map_geometry,
                }
            )

    response = jsonify({
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "total_count": total_count,
            "is_preview": total_count > len(features),
            "limit": preview_limit,
        },
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/owners-in-bounds")
def api_owners_in_bounds():
    ensure_db_exists()
    selection_bounds = {
        "min_lon": request.args.get("min_lon", default=None, type=float),
        "max_lon": request.args.get("max_lon", default=None, type=float),
        "min_lat": request.args.get("min_lat", default=None, type=float),
        "max_lat": request.args.get("max_lat", default=None, type=float),
    }
    if any(value is None for value in selection_bounds.values()):
        return jsonify({"owners": [], "message": "Select a map area first."}), 400

    min_voltage = request.args.get("min_voltage", default=0, type=int)
    owner_filter = request.args.get("owner", default="", type=str)
    voltage_category_filter = request.args.get("voltage_category", default="", type=str)
    include_missing_voltage = request.args.get("include_missing_voltage", default="0", type=str).lower() in {"1", "true", "yes", "on"}

    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT owner, voltage, geojson_geom FROM transmission_lines"
    params = []

    if include_missing_voltage:
        query += " WHERE (voltage >= ? OR (voltage < 0 AND ? = 1))"
        params.extend([min_voltage, 1])
    else:
        query += " WHERE voltage >= ?"
        params.append(min_voltage)

    if owner_filter:
        query += " AND owner = ?"
        params.append(owner_filter)

    rows = cursor.execute(query, params).fetchall()
    conn.close()

    owners = {}
    for row in rows:
        if not row["geojson_geom"]:
            continue

        voltage_bucket = _voltage_bucket(row["voltage"])
        if voltage_category_filter and voltage_bucket != voltage_category_filter:
            continue

        geometry = json.loads(row["geojson_geom"])
        geometry_bounds = _geometry_bounds(_map_geometry(geometry))
        if _intersects_bounds(geometry_bounds, selection_bounds):
            owner_name = row["owner"] or "Unknown"
            owners[owner_name] = owners.get(owner_name, 0) + 1

    ranked_owners = [{"owner": owner_name, "count": count} for owner_name, count in sorted(owners.items())]
    response = jsonify({"owners": ranked_owners, "bbox": selection_bounds})
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    app.run(debug=False, use_reloader=False, host="0.0.0.0", port=5008)
