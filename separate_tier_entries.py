import json
from pathlib import Path
from collections import Counter

src = Path("auto_facilities_north_america_master.jsonl")
tier1_out = Path("tier1_entries.jsonl")
tier2_out = Path("tier2_entries.jsonl")
unknown_out = Path("tier_unknown_entries.jsonl")
summary_out = Path("tier_split_summary.json")


def normalize_tier(value):
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in {"tier 1", "tier1", "t1", "1"}:
        return "tier1"
    if v in {"tier 2", "tier2", "t2", "2"}:
        return "tier2"
    if "tier 1" in v:
        return "tier1"
    if "tier 2" in v:
        return "tier2"
    return None


def extract_tier(record):
    for key in [
        "tier",
        "tier_level",
        "supplier_tier",
        "supply_chain_tier",
        "tier_class",
        "tier_classification",
        "category",
        "facility_type",
    ]:
        value = record.get(key)
        if isinstance(value, str):
            tier = normalize_tier(value)
            if tier:
                return tier
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    tier = normalize_tier(item)
                    if tier:
                        return tier

    # Check nested structures conservatively.
    for key in ["canonical_summary", "metadata"]:
        nested = record.get(key)
        if isinstance(nested, dict):
            for nested_key in [
                "tier",
                "tier_level",
                "supplier_tier",
                "supply_chain_tier",
                "tier_class",
                "tier_classification",
                "category",
            ]:
                value = nested.get(nested_key)
                if isinstance(value, str):
                    tier = normalize_tier(value)
                    if tier:
                        return tier
    return None


records = []
with src.open(encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if line:
            records.append(json.loads(line))

classified_tier1 = []
classified_tier2 = []
unknown = []

for record in records:
    tier = extract_tier(record)
    if tier == "tier1":
        classified_tier1.append(record)
    elif tier == "tier2":
        classified_tier2.append(record)
    else:
        unknown.append(record)

for path, rows in [(tier1_out, classified_tier1), (tier2_out, classified_tier2), (unknown_out, unknown)]:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

summary = {
    "source_file": str(src),
    "record_count": len(records),
    "tier1_count": len(classified_tier1),
    "tier2_count": len(classified_tier2),
    "unclassified_count": len(unknown),
    "facility_types_in_unclassified": dict(Counter(r.get("facility_type") for r in unknown if r.get("facility_type"))),
    "notes": "No explicit tier field was found in the current dataset, so the split is currently empty for Tier 1/Tier 2 and all supplier-style records fall into the unclassified bucket.",
}

with summary_out.open("w", encoding="utf-8") as handle:
    json.dump(summary, handle, indent=2, ensure_ascii=False)

print(json.dumps(summary, indent=2, ensure_ascii=False))
