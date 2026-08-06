"""Reviewable mapping tables for the auto-facilities defense-conversion
pipeline. This is the single source of truth for two things:

1. PROCESS_CATEGORY_MAP - how the 54 distinct freeform `current_processes`
   strings found in the 72 hand-researched facilities (auto_facilities_VECA8
   copy.json) roll up into 9 standardized categories. Built by manually
   reading every distinct raw value once (see the full list in git history
   of this file / ask for the audit dump) rather than pattern-matching
   substrings, since near-duplicates like "welding (robotic)" vs "robotic
   welding" vs "welding" don't share a common substring to key off.

2. NAICS_TIER_MAP - for facilities that only have a products-embedded NAICS
   code (i.e. everything pulled from the 6,935-record EPA ECHO master list,
   not individually researched), what facility_type/tier/process-category
   *estimate* that NAICS code implies. This is a coarse, disclosed inference
   - not a substitute for per-facility research - which is why
   build_high_yield_facilities.py stores it separately from genuine
   per-facility `current_processes` data and never fabricates narrative
   fields (union status, supply chain, security posture, etc.) for these
   facilities.

Kept as a standalone module (rather than inline in the build script) so the
mapping itself can be reviewed/diffed independent of the pipeline logic that
applies it, and so ingest_auto_plants.py or other tooling can import it
without re-implementing the taxonomy.
"""

# --------------------------------------------------------------------------
# 1. Raw process text -> standardized category
# --------------------------------------------------------------------------
# Category set was chosen to mirror the physical production stages that
# matter for defense-conversion feasibility (what a line can be retooled to
# do), not the source data's own inconsistent phrasing.
PROCESS_CATEGORIES = (
    "Body in White & Structural Welding",
    "Painting & Surface Coating",
    "Final Assembly & Vehicle Integration",
    "Quality & End-of-Line Testing",
    "Precision Machining & Powertrain",
    "Stamping & Structural Forming",
    "Battery, EV & Energy Storage Production",
    "Advanced Automation & Robotics",
    "HVAC & Thermal Systems",
)

# Every key is lowercased/stripped before lookup (see categorize_processes).
# The two terms that map to None are real values in the source data that
# aren't manufacturing processes at all (a capacity stat and a historical
# note) - they're intentionally excluded from process_categories rather than
# dumped into a catch-all bucket.
PROCESS_CATEGORY_MAP: dict[str, str | None] = {
    # Body in White & Structural Welding
    "welding (robotic)": "Body in White & Structural Welding",
    "robotic welding": "Body in White & Structural Welding",
    "welding": "Body in White & Structural Welding",
    "body in white": "Body in White & Structural Welding",
    "body in white (robotic)": "Body in White & Structural Welding",
    "body in white (incl. large castings)": "Body in White & Structural Welding",

    # Painting & Surface Coating
    "painting": "Painting & Surface Coating",
    "paint": "Painting & Surface Coating",

    # Final Assembly & Vehicle Integration
    "final assembly": "Final Assembly & Vehicle Integration",
    "assembly": "Final Assembly & Vehicle Integration",
    "ev final assembly": "Final Assembly & Vehicle Integration",
    "ev integration": "Final Assembly & Vehicle Integration",
    "planned ev final assembly": "Final Assembly & Vehicle Integration",
    "planned final assembly, battery integration": "Final Assembly & Vehicle Integration",
    "to be final assembly, body, paint, trim": "Final Assembly & Vehicle Integration",

    # Quality & End-of-Line Testing
    "end of line test": "Quality & End-of-Line Testing",
    "testing": "Quality & End-of-Line Testing",
    "dyno testing": "Quality & End-of-Line Testing",
    "hot test/dyno": "Quality & End-of-Line Testing",
    "high voltage testing": "Quality & End-of-Line Testing",
    "formation/testing": "Quality & End-of-Line Testing",

    # Precision Machining & Powertrain
    "machining": "Precision Machining & Powertrain",
    "precision machining": "Precision Machining & Powertrain",
    "precision machining (blocks, heads, cranks)": "Precision Machining & Powertrain",
    "precision gear machining": "Precision Machining & Powertrain",
    "machining of blocks/heads/axles": "Precision Machining & Powertrain",
    "engine block/head machining": "Precision Machining & Powertrain",
    "gear cutting": "Precision Machining & Powertrain",
    "engine assembly": "Precision Machining & Powertrain",
    "transmission assembly": "Precision Machining & Powertrain",
    "powertrain assembly": "Precision Machining & Powertrain",
    "electric drive unit assembly": "Precision Machining & Powertrain",

    # Stamping & Structural Forming
    "stamping": "Stamping & Structural Forming",
    "aluminum stamping": "Stamping & Structural Forming",
    "blanking": "Stamping & Structural Forming",
    "panel assembly": "Stamping & Structural Forming",
    "aluminum casting (precision sand, semi-permanent mold)": "Stamping & Structural Forming",

    # Battery, EV & Energy Storage Production
    "battery module assembly": "Battery, EV & Energy Storage Production",
    "battery pack assembly (18650/2170 era)": "Battery, EV & Energy Storage Production",
    "battery cell to module to pack assembly": "Battery, EV & Energy Storage Production",
    "battery assembly": "Battery, EV & Energy Storage Production",
    "battery integration": "Battery, EV & Energy Storage Production",
    "pack integration": "Battery, EV & Energy Storage Production",
    "cell assembly": "Battery, EV & Energy Storage Production",
    "module": "Battery, EV & Energy Storage Production",
    "electrode production": "Battery, EV & Energy Storage Production",
    "in-house stator/rotor/motor mfg": "Battery, EV & Energy Storage Production",
    "stator winding/assembly for ev motors": "Battery, EV & Energy Storage Production",

    # Advanced Automation & Robotics
    "robot production (optimus)": "Advanced Automation & Robotics",
    "autonomous vehicle transport of bodies (no traditional conveyors)": "Advanced Automation & Robotics",

    # HVAC & Thermal Systems
    "heat exchanger manufacturing": "HVAC & Thermal Systems",
    "hvac module assembly": "HVAC & Thermal Systems",

    # Not manufacturing processes - excluded from process_categories.
    ">100m parts/yr capacity": None,
    "foundry support historically": None,
}


def categorize_processes(raw_processes: list[str]) -> list[str]:
    """Maps a facility's freeform `current_processes` list to its distinct
    standardized categories, sorted for stable output. Any raw term not
    found in PROCESS_CATEGORY_MAP falls into "Other / Specialized" instead
    of being silently dropped, so new freeform terms added to future
    research show up as a visible gap here rather than disappearing."""
    categories: set[str] = set()
    for raw in raw_processes:
        key = str(raw).strip().lower()
        if not key:
            continue
        mapped = PROCESS_CATEGORY_MAP.get(key, "Other / Specialized")
        if mapped:
            categories.add(mapped)
    return sorted(categories)


# --------------------------------------------------------------------------
# 2. NAICS code -> (facility_type bucket, defense-conversion tier, default
#    process-category estimate) for facilities with no individual research
# --------------------------------------------------------------------------
# Scope follows the strategic recommendation: high-bay OEM assembly plants,
# engine/transmission/powertrain plants, and heavy stamping/body plants are
# the facilities worth carrying at EPA-ECHO-derived scale (~hundreds), since
# their physical characteristics (clear span, crane capacity, press tonnage)
# are inferable from their manufacturing role even without a site visit.
# Everything else (electrical, steering, brakes, generic "other parts") is
# left out of the high-yield set - too heterogeneous a NAICS bucket to infer
# anything defense-relevant from the code alone.
NaicsTierEntry = tuple[str, str, tuple[str, ...]]

NAICS_TIER_MAP: dict[str, NaicsTierEntry] = {
    "336111": ("OEM Assembly", "Tier 1: OEM Assembly", (
        "Body in White & Structural Welding", "Painting & Surface Coating",
        "Final Assembly & Vehicle Integration", "Quality & End-of-Line Testing",
    )),
    "336112": ("OEM Assembly", "Tier 1: OEM Assembly", (
        "Body in White & Structural Welding", "Painting & Surface Coating",
        "Final Assembly & Vehicle Integration", "Quality & End-of-Line Testing",
    )),
    "336310": ("Engine & Powertrain", "Tier 2: Powertrain & Propulsion", (
        "Precision Machining & Powertrain", "Quality & End-of-Line Testing",
    )),
    "336350": ("Engine & Powertrain", "Tier 2: Powertrain & Propulsion", (
        "Precision Machining & Powertrain", "Quality & End-of-Line Testing",
    )),
    "336370": ("Metal Stamping & Body", "Tier 2: Stamping & Structures", (
        "Stamping & Structural Forming", "Body in White & Structural Welding",
    )),
    "336211": ("Metal Stamping & Body", "Tier 2: Stamping & Structures", (
        "Stamping & Structural Forming", "Body in White & Structural Welding",
    )),
}

CURATED_TIER_LABEL = "Tier 1: Curated OEM Flagship"

# The 72 curated facilities carry their own facility_type values (finer-
# grained than the NAICS buckets above - e.g. "Transmission" as distinct
# from "Engine"). Mapped onto the same clean bucket set used for NAICS-
# derived facilities so the frontend legend colors both consistently.
# "Other Major Component" (5 facilities: foundries, a lithium refinery, an
# HVAC/motor-component plant) is genuinely heterogeneous - left as its own
# bucket rather than force-fit into one of the four, since e.g. a lithium
# refinery has nothing in common with a stamping plant.
CURATED_FACILITY_TYPE_MAP: dict[str, str] = {
    "Assembly": "OEM Assembly",
    "Engine": "Engine & Powertrain",
    "Transmission": "Engine & Powertrain",
    "Body/Stamping": "Metal Stamping & Body",
    "Battery": "Battery & Energy Storage",
    "Other Major Component": "Other Major Component",
}

NAICS_INFERRED_NOTE = (
    "NAICS-derived estimate only - process categories inferred from the "
    "facility's manufacturing-role classification, not individually "
    "researched. Verify union status, cleanroom capability, prior defense "
    "work, and physical specs before using this facility in a defense-"
    "conversion assessment."
)
