import argparse
import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

import requests


GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def build_query(record: Dict[str, Any]) -> str:
    location = record.get("location") or {}
    address = (location.get("address_or_area") or "").strip()
    city = (location.get("city") or "").strip()
    state = (record.get("state") or "").strip()

    parts = [part for part in [address, city, state] if part]
    if not parts:
        return ""
    return ", ".join(parts)


def is_missing_coordinates(record: Dict[str, Any]) -> bool:
    lat = record.get("latitude")
    lon = record.get("longitude")
    return lat in (None, 0, 0.0) or lon in (None, 0, 0.0)


def geocode_with_google(query: str, api_key: str, delay_seconds: float = 0.1) -> Optional[Dict[str, float]]:
    if not query or not api_key:
        return None

    params = {"address": query, "key": api_key}
    for attempt in range(5):
        try:
            response = requests.get(GOOGLE_GEOCODE_URL, params=params, timeout=15)
            response.raise_for_status()
            payload = response.json()
            status = payload.get("status")
            if status == "OK":
                result = payload["results"][0]
                geometry = result.get("geometry", {}).get("location", {})
                return {
                    "lat": float(geometry.get("lat", 0.0)),
                    "lon": float(geometry.get("lng", 0.0)),
                }
            if status in {"OVER_QUERY_LIMIT", "RESOURCE_EXHAUSTED", "INVALID_REQUEST"}:
                if attempt < 4:
                    time.sleep((2 ** attempt) + delay_seconds)
                    continue
            return None
        except Exception:
            if attempt < 4:
                time.sleep((2 ** attempt) + delay_seconds)
                continue
            return None

    return None


def process_file(input_path: str, output_path: Optional[str] = None, delay_seconds: float = 0.1) -> int:
    if output_path is None:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_geocoded{ext}"

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not set")

    existing_records: List[Dict[str, Any]] = []
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        with open(output_path, "r", encoding="utf-8") as existing_file:
            for line in existing_file:
                line = line.strip()
                if not line:
                    continue
                try:
                    existing_records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    total = 0
    updated = 0
    skipped = 0
    temp_output_path = None

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=os.path.dirname(output_path) or ".") as tmp_file:
        temp_output_path = tmp_file.name

    try:
        with open(input_path, "r", encoding="utf-8") as src, open(temp_output_path, "w", encoding="utf-8") as dst:
            for line_number, line in enumerate(src, start=1):
                line = line.strip()
                if not line:
                    continue

                total += 1
                if existing_records and line_number <= len(existing_records):
                    record = existing_records[line_number - 1]
                else:
                    record = json.loads(line)

                if not is_missing_coordinates(record):
                    skipped += 1
                    dst.write(json.dumps(record, ensure_ascii=False) + "\n")
                    continue

                query = build_query(record)
                coords = geocode_with_google(query, api_key, delay_seconds=delay_seconds)
                if coords:
                    record["latitude"] = coords["lat"]
                    record["longitude"] = coords["lon"]
                    location = record.setdefault("location", {})
                    location.setdefault("coordinates", {})
                    location["coordinates"]["lat"] = coords["lat"]
                    location["coordinates"]["lon"] = coords["lon"]
                    updated += 1
                else:
                    record["latitude"] = record.get("latitude", 0.0)
                    record["longitude"] = record.get("longitude", 0.0)

                dst.write(json.dumps(record, ensure_ascii=False) + "\n")

        os.replace(temp_output_path, output_path)
    finally:
        if temp_output_path and os.path.exists(temp_output_path):
            os.remove(temp_output_path)

    print(f"Processed {total} records")
    print(f"Updated {updated} records")
    print(f"Skipped {skipped} records")
    print(f"Wrote {output_path}")
    return updated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Geocode a JSONL facility dataset using Google Maps")
    parser.add_argument("input_path", help="Path to the input JSONL file")
    parser.add_argument("--output", help="Optional output path")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay between geocoding requests in seconds")
    args = parser.parse_args()
    process_file(args.input_path, args.output, delay_seconds=args.delay)
