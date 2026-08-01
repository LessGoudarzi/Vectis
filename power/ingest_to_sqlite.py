import argparse
import json
import sqlite3
import urllib.request
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import geopandas as gpd


TRANSMISSION_URL = "https://gem.anl.gov/tool/r/conus/layers/transmission_line_eia/versions/1/download.zip"
POWER_PLANTS_URL = "https://gem.anl.gov/tool/r/conus/layers/plant_power_eia/versions/9/download.zip"
SUBSTATIONS_URL = "https://gem.anl.gov/tool/r/conus/layers/electric_substation_hifld/versions/4/download.zip"


def _get_prop(row, *names):
    for name in names:
        if name in row.index:
            value = row.get(name)
            if value is not None:
                return value
    return None


def _get_feature_prop(properties, *names):
    for name in names:
        if name in properties:
            value = properties.get(name)
            if value is not None:
                return value
    return None


def _as_float(value, default=0.0):
    if value is None:
        return default
    try:
        if value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_fuel_bucket(primary_source, source_description=None, tech_desc=None):
    text_parts = [str(part).lower() for part in [primary_source, source_description, tech_desc] if part not in (None, "")]
    text = " ".join(text_parts)
    if not text or text == "unknown":
        return "Unknown"

    patterns = [
        ("Natural Gas", ["natural gas", "gas", "ng ", " ng", " lng", "cng"]),
        ("Hydro", ["hydro", "hydroelectric", "water"]),
        ("Solar", ["solar", "pv", "photovoltaic"]),
        ("Wind", ["wind"]),
        ("Nuclear", ["nuclear"]),
        ("Coal", ["coal"]),
        ("Petroleum", ["petroleum", "oil", "crude", "diesel", "distillate"]),
        ("Biomass", ["biomass", "bio", "wood", "landfill", "waste"]),
        ("Geothermal", ["geothermal"]),
        ("Storage", ["battery", "storage", "bess"]),
        ("Other", ["other", "misc"]),
    ]
    for bucket, needles in patterns:
        if any(needle in text for needle in needles):
            return bucket
    return str(primary_source or source_description or tech_desc or "Unknown").strip().title() or "Unknown"


def _download_file(url: str, destination: Path, force: bool = False, fallback_path: Optional[Path] = None) -> Path:
    if destination.exists() and not force:
        print(f"Using cached file at {destination}")
        return destination

    print(f"Downloading file from {url} -> {destination}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            destination.write_bytes(response.read())
            return destination
    except Exception as exc:
        print(f"Download failed: {exc}")
        fallback = fallback_path or Path(__file__).with_name("sample_data.geojson")
        if fallback.exists():
            print(f"Falling back to local sample data at {fallback}")
            return fallback
        raise


def _extract_gpkg_from_zip(zip_path: Path, destination_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as zf:
        gpkg_name = next((name for name in zf.namelist() if name.endswith(".gpkg")), None)
        if not gpkg_name:
            raise FileNotFoundError(f"No GeoPackage found in {zip_path}")
        destination_path = destination_dir / Path(gpkg_name).name
        with zf.open(gpkg_name) as src, destination_path.open("wb") as dst:
            dst.write(src.read())
        return destination_path


def _prepare_source_dataset(source_url: str, cache_path: Path, force_download: bool, fallback_path: Optional[Path] = None) -> Path:
    if cache_path.exists() and not force_download:
        return cache_path

    if cache_path.exists() and force_download:
        print(f"Using existing local source at {cache_path} despite --refresh")
        return cache_path

    downloaded_zip = cache_path.with_suffix(".zip")
    downloaded_path = _download_file(source_url, downloaded_zip, force=force_download, fallback_path=fallback_path)

    if downloaded_path.suffix.lower() == ".zip" and downloaded_path.exists():
        return _extract_gpkg_from_zip(downloaded_path, cache_path.parent)
    return downloaded_path


def _make_json_safe(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_json_safe(item) for item in value]
    return str(value)


def _write_json_export(source_path: Path, output_path: Optional[Path] = None) -> Path:
    source_path = Path(source_path)
    if output_path is None:
        output_path = source_path.with_suffix(".json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_mtime >= source_path.stat().st_mtime:
        return output_path

    if source_path.suffix.lower() in {".json", ".geojson"}:
        payload = json.loads(source_path.read_text())
    else:
        gdf = gpd.read_file(source_path)
        features = []
        for _, row in gdf.iterrows():
            geom = row.geometry
            features.append(
                {
                    "type": "Feature",
                    "properties": {k: _make_json_safe(v) for k, v in row.to_dict().items()},
                    "geometry": None if geom is None else geom.__geo_interface__,
                }
            )
        payload = {"type": "FeatureCollection", "features": features}
    output_path.write_text(json.dumps(payload, indent=2))
    return output_path


def _load_feature_collection(source_path: Path) -> dict:
    json_path = _write_json_export(source_path)
    return json.loads(json_path.read_text())


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


def build_transmission_db(
    geojson_path="Electric_Power_Transmission_Lines.geojson",
    db_path="transmission.db",
    source_url=TRANSMISSION_URL,
    force_download=False,
):
    geojson_path = Path(geojson_path)
    db_path = Path(db_path)

    if not geojson_path.exists() or force_download:
        if source_url:
            cache_path = geojson_path if geojson_path.name != "" else Path(__file__).with_name("Electric_Power_Transmission_Lines.geojson")
            if not cache_path.parent.exists():
                cache_path.parent.mkdir(parents=True, exist_ok=True)
            geojson_path = _prepare_source_dataset(source_url, cache_path, force_download)
        else:
            fallback_path = Path(__file__).with_name("sample_data.geojson")
            if fallback_path.exists():
                geojson_path = fallback_path
            else:
                raise FileNotFoundError(f"Could not find input GeoJSON at {geojson_path}.")

    print(f"Loading dataset from {geojson_path}...")
    feature_collection = _load_feature_collection(geojson_path)
    features = feature_collection.get("features", [])

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS transmission_lines")
    cursor.execute(
        """
        CREATE TABLE transmission_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT,
            voltage INTEGER,
            volt_class TEXT,
            status TEXT,
            state TEXT,
            line_type TEXT,
            geojson_geom TEXT
        )
        """
    )

    records = []
    for feature in features:
        properties = feature.get("properties") or {}
        state_value = _get_feature_prop(properties, "STATE", "state", "STATE_NAME", "state_name") or ""
        if str(state_value).upper() in ["AK", "HI", "PR", "VI", "GU"]:
            continue
        geometry = feature.get("geometry")
        geom_str = json.dumps(geometry) if geometry is not None else None
        records.append(
            (
                str(_get_feature_prop(properties, "OWNER", "owner", "Owner") or "Unknown"),
                int(_get_feature_prop(properties, "VOLTAGE", "voltage", "Voltage") or 0),
                str(_get_feature_prop(properties, "VOLT_CLASS", "volt_class", "Volt_Class") or "N/A"),
                str(_get_feature_prop(properties, "STATUS", "status", "Status") or "N/A"),
                str(state_value),
                str(_get_feature_prop(properties, "TYPE", "type", "Type") or "UNKNOWN"),
                geom_str,
            )
        )

    cursor.executemany(
        """
        INSERT INTO transmission_lines (owner, voltage, volt_class, status, state, line_type, geojson_geom)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )

    conn.commit()
    conn.close()
    print(f"Database created at {db_path}")


def build_power_plants_db(
    geojson_path="power_plants.gpkg",
    db_path="transmission.db",
    source_url=POWER_PLANTS_URL,
    force_download=False,
):
    geojson_path = Path(geojson_path)
    db_path = Path(db_path)

    default_candidate = Path(__file__).with_name("power_plants.gpkg")
    bundled_candidate = Path(__file__).with_name("plant_power_eia_v9") / "plant_power_eia_v9.gpkg"
    if not force_download:
        if geojson_path.exists():
            pass
        elif geojson_path.name == default_candidate.name and bundled_candidate.exists():
            geojson_path = bundled_candidate

    if not geojson_path.exists() or force_download:
        if source_url:
            cache_path = geojson_path if geojson_path.name != "" else Path(__file__).with_name("power_plants.gpkg")
            if not cache_path.parent.exists():
                cache_path.parent.mkdir(parents=True, exist_ok=True)
            fallback_path = Path(__file__).with_name("sample_data.geojson")
            geojson_path = _prepare_source_dataset(source_url, cache_path, force_download, fallback_path=fallback_path)
        else:
            raise FileNotFoundError(f"Could not find input GeoPackage at {geojson_path}.")

    print(f"Loading power-plant dataset from {geojson_path}...")
    feature_collection = _load_feature_collection(geojson_path)
    features = feature_collection.get("features", [])

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS power_plants")
    cursor.execute("DROP TABLE IF EXISTS power_plant_fuel_summary")
    cursor.execute("DROP TABLE IF EXISTS power_plant_fuel_capacity_buckets")
    cursor.execute(
        """
        CREATE TABLE power_plants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plant_name TEXT,
            fuel_type TEXT,
            fuel_source TEXT,
            capacity_mw REAL,
            owner TEXT,
            utility_name TEXT,
            sector_name TEXT,
            source_des TEXT,
            tech_desc TEXT,
            state TEXT,
            geojson_geom TEXT
        )
        """
    )

    records = []
    for feature in features:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry")
        geom_str = json.dumps(geometry) if geometry is not None else None
        plant_name = str(_get_feature_prop(properties, "plant_name", "Plant_Name", "name", "Name") or "Unknown")
        primary_fuel = _get_feature_prop(properties, "primsource", "PrimSource", "primary_fuel", "Primary_Fuel", "fuel_type", "Fuel_Type", "energy_source", "Energy_Source")
        source_description = _get_feature_prop(properties, "source_des", "Source_Des", "source_description", "Source_Description")
        tech_desc = _get_feature_prop(properties, "tech_desc", "Tech_Desc", "technology", "Technology")
        fuel_bucket = _normalize_fuel_bucket(primary_fuel, source_description=source_description, tech_desc=tech_desc)
        total_capacity = _as_float(_get_feature_prop(properties, "total_mw", "Total_MW", "capacity_mw", "Capacity_MW", "capacity", "Capacity"), default=0.0)
        install_capacity = _as_float(_get_feature_prop(properties, "install_mw", "Install_MW"), default=0.0)
        capacity_mw = total_capacity if total_capacity > 0 else install_capacity
        records.append(
            (
                plant_name,
                fuel_bucket,
                str(primary_fuel or fuel_bucket),
                capacity_mw,
                str(_get_feature_prop(properties, "utility_na", "Utility_NA", "owner", "Owner", "operator", "Operator") or "Unknown"),
                str(_get_feature_prop(properties, "utility_na", "Utility_NA") or "Unknown"),
                str(_get_feature_prop(properties, "sector_nam", "Sector_Nam", "sector_name", "Sector_Name") or "Unknown"),
                str(source_description or "Unknown"),
                str(tech_desc or "Unknown"),
                str(_get_feature_prop(properties, "state", "State", "STATE", "state_name") or ""),
                geom_str,
            )
        )

    cursor.executemany(
        """
        INSERT INTO power_plants (plant_name, fuel_type, fuel_source, capacity_mw, owner, utility_name, sector_name, source_des, tech_desc, state, geojson_geom)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )

    cursor.execute(
        """
        CREATE TABLE power_plant_fuel_summary AS
        SELECT
            fuel_type,
            COUNT(*) AS plant_count,
            ROUND(SUM(capacity_mw), 2) AS total_capacity_mw,
            ROUND(AVG(capacity_mw), 2) AS avg_capacity_mw,
            ROUND(MAX(capacity_mw), 2) AS max_capacity_mw
        FROM power_plants
        GROUP BY fuel_type
        ORDER BY plant_count DESC, total_capacity_mw DESC, fuel_type
        """
    )
    cursor.execute(
        """
        CREATE TABLE power_plant_fuel_capacity_buckets AS
        SELECT
            fuel_type,
            CASE
                WHEN capacity_mw < 10 THEN '0-10 MW'
                WHEN capacity_mw < 50 THEN '10-50 MW'
                WHEN capacity_mw < 100 THEN '50-100 MW'
                WHEN capacity_mw < 250 THEN '100-250 MW'
                WHEN capacity_mw < 500 THEN '250-500 MW'
                WHEN capacity_mw < 1000 THEN '500-1000 MW'
                ELSE '1000+ MW'
            END AS capacity_bucket,
            COUNT(*) AS plant_count,
            ROUND(SUM(capacity_mw), 2) AS total_capacity_mw
        FROM power_plants
        GROUP BY fuel_type, capacity_bucket
        ORDER BY fuel_type, plant_count DESC, capacity_bucket
        """
    )
    conn.commit()
    conn.close()
    print(f"Power-plant database updated at {db_path}")


def build_substations_db(
    geojson_path="substations.gpkg",
    db_path="transmission.db",
    source_url=SUBSTATIONS_URL,
    force_download=False,
):
    geojson_path = Path(geojson_path)
    db_path = Path(db_path)

    default_candidate = Path(__file__).with_name("substations.gpkg")
    # GEM tool downloads for this layer land at the repo root as
    # electric_substation_hifld_v4/electric_substation_hifld_v4.gpkg; also
    # check the power/-local convention used by the other two datasets.
    bundled_candidates = [
        Path(__file__).resolve().parent.parent / "electric_substation_hifld_v4" / "electric_substation_hifld_v4.gpkg",
        Path(__file__).with_name("electric_substation_hifld_v4") / "electric_substation_hifld_v4.gpkg",
    ]
    if not force_download:
        if geojson_path.exists():
            pass
        elif geojson_path.name == default_candidate.name:
            for candidate in bundled_candidates:
                if candidate.exists():
                    geojson_path = candidate
                    break

    if not geojson_path.exists() or force_download:
        if source_url:
            cache_path = geojson_path if geojson_path.name != "" else Path(__file__).with_name("substations.gpkg")
            if not cache_path.parent.exists():
                cache_path.parent.mkdir(parents=True, exist_ok=True)
            fallback_path = Path(__file__).with_name("sample_data.geojson")
            geojson_path = _prepare_source_dataset(source_url, cache_path, force_download, fallback_path=fallback_path)
        else:
            raise FileNotFoundError(f"Could not find input GeoPackage at {geojson_path}.")

    print(f"Loading substation dataset from {geojson_path}...")
    feature_collection = _load_feature_collection(geojson_path)
    features = feature_collection.get("features", [])

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS substations")
    cursor.execute(
        """
        CREATE TABLE substations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            facility_name TEXT,
            sub_type TEXT,
            status TEXT,
            county TEXT,
            state TEXT,
            max_voltage_kv REAL,
            min_voltage_kv REAL,
            line_count INTEGER,
            naics_desc TEXT,
            geojson_geom TEXT
        )
        """
    )

    records = []
    for feature in features:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry")
        if geometry is None:
            continue
        state_value = _get_feature_prop(properties, "state", "State", "STATE") or ""
        if str(state_value).upper() in ["AK", "HI", "PR", "VI", "GU"]:
            continue
        geom_str = json.dumps(geometry)
        records.append(
            (
                str(_get_feature_prop(properties, "name", "Name") or "Unknown"),
                str(_get_feature_prop(properties, "type", "Type") or "Unknown"),
                str(_get_feature_prop(properties, "status", "Status") or "Unknown"),
                str(_get_feature_prop(properties, "county", "County") or ""),
                str(state_value),
                _as_float(_get_feature_prop(properties, "max_volt", "Max_Volt"), default=None),
                _as_float(_get_feature_prop(properties, "min_volt", "Min_Volt"), default=None),
                int(_as_float(_get_feature_prop(properties, "lines", "Lines"), default=0)),
                str(_get_feature_prop(properties, "naics_desc", "NAICS_Desc") or "Unknown"),
                geom_str,
            )
        )

    cursor.executemany(
        """
        INSERT INTO substations (
            facility_name, sub_type, status, county, state,
            max_voltage_kv, min_voltage_kv, line_count, naics_desc, geojson_geom
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )

    conn.commit()
    conn.close()
    print(f"Substation database updated at {db_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest transmission lines into SQLite")
    parser.add_argument("--refresh", action="store_true", help="Force a new download of the GeoJSON dataset")
    parser.add_argument("--db", default="transmission.db", help="Path to the SQLite output database")
    parser.add_argument("--geojson", default="Electric_Power_Transmission_Lines.geojson", help="Path to the cached GeoJSON file")
    args = parser.parse_args()

    build_transmission_db(
        geojson_path=args.geojson,
        db_path=args.db,
        force_download=args.refresh,
    )
    build_power_plants_db(
        geojson_path="power_plants.gpkg",
        db_path=args.db,
        force_download=args.refresh,
    )
    build_substations_db(
        geojson_path="substations.gpkg",
        db_path=args.db,
        force_download=args.refresh,
    )
