"""Builds auto_facilities_high_yield_defense.json - the scoped, defense-
conversion-relevant subset of automobile facilities actually served by the
backend (see AUTO_PLANTS_JSON in backend/database.py).

Replaces an earlier ad hoc terminal session that produced the same output
file by hand: that version is gone (never saved as a script), wasn't
reproducible, and turned out to have two real bugs this version fixes:

1. It fabricated a full defense_conversion_profile (union status, supply
   chain notes, security posture, etc.) for every NAICS-derived facility,
   using the same boilerplate prose for all of them - i.e. it reintroduced
   the exact "meaningless boilerplate" problem that motivated scoping down
   from the 6,935-record master file in the first place. This version only
   ever fabricates a NAICS-inferred *category estimate* (disclosed as such
   via NAICS_INFERRED_NOTE) - never per-facility narrative text.
2. It didn't reject bad coordinates before this script was pointed at
   auto_facilities_north_america_master.jsonl, whose longitude field is
   zeroed out dataset-wide (every one of its 6,935 records has
   longitude == 0.0). That file turned out to be an already-corrupted
   derivative of auto_facilities_VECA8.json - same 6,935 records, same
   products/NAICS/defense_conversion_profile content, but with genuinely
   correct coordinates. This script reads VECA8.json instead, so the
   NAICS-derived facilities need no re-geocoding at all. The coordinate-
   validity check stays in place as a defensive guard against future data
   corruption, not because it's currently rejecting anything.

Two source files, two different confidence levels:
  - auto_facilities_VECA8 copy.json (72 facilities): hand-researched,
    genuine per-facility current_processes/workforce/security data. Kept
    verbatim, just tagged with process_categories + defense_conversion_tier.
  - auto_facilities_VECA8.json (6,935 facilities): EPA ECHO bulk pull,
    NAICS-code-only, no individual research. Filtered down to the
    high-yield NAICS codes (see process_taxonomy.NAICS_TIER_MAP) and given
    a disclosed NAICS-based estimate in place of per-facility research.
    (Despite the near-identical filename, this is NOT the same file as the
    72-facility "VECA8 copy.json" - no per-facility research here.)

Run: python3 build_high_yield_facilities.py
"""

import json
import re
from pathlib import Path

from process_taxonomy import (
    CURATED_FACILITY_TYPE_MAP,
    CURATED_TIER_LABEL,
    NAICS_INFERRED_NOTE,
    NAICS_TIER_MAP,
    categorize_processes,
)

BASE_DIR = Path(__file__).resolve().parent
MASTER_PATH = BASE_DIR / "auto_facilities_VECA8.json"
CURATED_PATH = BASE_DIR / "auto_facilities_VECA8 copy.json"
OUTPUT_PATH = BASE_DIR / "auto_facilities_high_yield_defense.json"

# Disabled: auto_facilities_VECA8.json is unreliable at the individual-
# facility level - NAICS classification doesn't correlate with facility
# size (e.g. a Family Dollar retail store is tagged facility_type
# "Assembly Plant" / NAICS 336111), and oem_or_parent is just a copy of
# facility_name, not real parent-company data, so it can't be used to
# filter shops/retail out either. Until a reliable size or corporate-
# identity signal exists for this source, NAICS_TIER_MAP facilities are
# skipped and only the 72 hand-researched curated facilities are emitted.
INCLUDE_NAICS_DERIVED = False

_NAICS_PATTERN = re.compile(r"NAICS:\s*(\d+)")

# North America bounding box (rough) used only to reject obviously-broken
# coordinates (e.g. the master file's dataset-wide longitude == 0.0 bug),
# not to validate real precision.
_NA_LON_RANGE = (-170.0, -50.0)
_NA_LAT_RANGE = (15.0, 72.0)


def _load_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_json(path: Path) -> list[dict]:
    with path.open() as f:
        return json.load(f)


def _extract_naics(entry: dict) -> str | None:
    for product in entry.get("products") or []:
        match = _NAICS_PATTERN.search(str(product))
        if match:
            return match.group(1)
    return None


def _coordinates(entry: dict) -> tuple[float, float] | None:
    location = entry.get("location") or {}
    coords = location.get("coordinates") or {}
    lat = coords.get("lat")
    lon = coords.get("lon")
    if lat is None or lon is None:
        return None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (_NA_LAT_RANGE[0] < lat < _NA_LAT_RANGE[1]):
        return None
    if not (_NA_LON_RANGE[0] < lon < _NA_LON_RANGE[1]):
        return None
    return lat, lon


def _dedupe_key(entry: dict) -> tuple[str, str]:
    """Same physical plant can appear in both source files under slightly
    different name casing/punctuation and with different (or broken)
    coordinates - see BMW Spartanburg, which appears once in the curated
    file with real coordinates and twice in the master file at the same
    street address with lon == 0.0. Dedup on normalized name + state
    instead of exact name/coordinate match so the curated (higher-
    confidence) record always wins regardless of coordinate quality."""
    name = str(entry.get("facility_name") or entry.get("name") or "")
    name = re.sub(r"[^a-z0-9]", "", name.lower())
    state = str(entry.get("state_abbr") or entry.get("state") or "").strip().upper()
    return name, state


def _build_curated_records(curated: list[dict]) -> dict[tuple[str, str], dict]:
    records = {}
    for entry in curated:
        dcp = entry.get("defense_conversion_profile") or {}
        pc = dcp.get("production_capabilities") or {}
        raw_processes = pc.get("current_processes") or []

        entry = dict(entry)  # don't mutate the source file's parsed data
        entry["process_categories"] = categorize_processes(raw_processes)
        entry["defense_conversion_tier"] = CURATED_TIER_LABEL
        source_type = str(entry.get("facility_type") or "")
        entry["facility_type"] = CURATED_FACILITY_TYPE_MAP.get(source_type, source_type)
        records[_dedupe_key(entry)] = entry
    return records


def _build_naics_records(master: list[dict], skip_keys: set[tuple[str, str]]) -> list[dict]:
    records = []
    skipped_bad_coords = 0
    skipped_duplicate = 0
    for entry in master:
        naics = _extract_naics(entry)
        if naics not in NAICS_TIER_MAP:
            continue

        key = _dedupe_key(entry)
        if key in skip_keys:
            skipped_duplicate += 1
            continue

        if _coordinates(entry) is None:
            skipped_bad_coords += 1
            continue

        facility_type, tier, default_categories = NAICS_TIER_MAP[naics]
        entry = dict(entry)
        entry["facility_type"] = facility_type
        entry["defense_conversion_tier"] = tier
        entry["process_categories"] = list(default_categories)
        # Disclosed NAICS-based estimate - deliberately NOT a fabricated
        # defense_conversion_profile. workforce/security/supply-chain
        # fields are simply absent, so downstream ingestion shows "Unknown"
        # rather than invented specifics.
        entry["defense_conversion_profile"] = {
            "production_capabilities": {"current_processes": []},
            "conversion_indicators_summary": NAICS_INFERRED_NOTE,
            "data_gaps": [
                "individual facility research not yet conducted",
                "union status, cleanroom capability, prior defense work, ITAR history unverified",
            ],
        }
        records.append(entry)
        skip_keys.add(key)  # collapse duplicate NAICS entries for the same plant

    print(f"  master: {len(records)} kept, {skipped_bad_coords} skipped (invalid/placeholder coordinates), "
          f"{skipped_duplicate} skipped (duplicate of a curated facility)")
    return records


def main() -> None:
    print("Loading source files...")
    curated_raw = _load_json(CURATED_PATH)
    master_raw = _load_jsonl(MASTER_PATH)
    print(f"  curated: {len(curated_raw)} records, master: {len(master_raw)} records")

    curated_records = _build_curated_records(curated_raw)
    print(f"  curated: {len(curated_records)} unique after internal dedup")

    if INCLUDE_NAICS_DERIVED:
        naics_records = _build_naics_records(master_raw, skip_keys=set(curated_records.keys()))
    else:
        print("  master: skipped (INCLUDE_NAICS_DERIVED=False - see module docstring)")
        naics_records = []

    combined = list(curated_records.values()) + naics_records
    OUTPUT_PATH.write_text(json.dumps(combined, indent=2))

    print(f"\nWrote {len(combined)} facilities to {OUTPUT_PATH.name}")
    tiers: dict[str, int] = {}
    for r in combined:
        t = r["defense_conversion_tier"]
        tiers[t] = tiers.get(t, 0) + 1
    for tier, count in sorted(tiers.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {tier}")


if __name__ == "__main__":
    main()
