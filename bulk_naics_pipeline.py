import argparse
import asyncio
import json
import logging
import os
import re
import aiohttp
from typing import Dict, Any, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

OUTPUT_FILE = "auto_facilities_north_america_master.jsonl"

# Core Automotive Manufacturing NAICS Codes
NAICS_CODES = [
    "336111",  # Automobile Manufacturing (OEM Assembly)
    "336112",  # Light Truck & Utility Vehicle Manufacturing (OEM Assembly)
    "336211",  # Motor Vehicle Body Manufacturing (Tier 1)
    "336310",  # Motor Vehicle Gasoline Engine & Engine Parts (Tier 1/2)
    "336320",  # Motor Vehicle Electrical & Electronic Equipment (Tier 1/2)
    "336330",  # Motor Vehicle Steering & Suspension Components (Tier 1/2)
    "336340",  # Motor Vehicle Brake System Manufacturing (Tier 1/2)
    "336350",  # Motor Vehicle Transmission & Power Train Parts (Tier 1/2)
    "336370",  # Motor Vehicle Metal Stamping (Tier 1/2)
    "336390"   # Other Motor Vehicle Parts Manufacturing (Tier 1/2)
]

class NorthAmericaAutoPipeline:
    def __init__(self, output_path: str = OUTPUT_FILE, resume: bool = True):
        self.output_path = output_path
        self.resume = resume
        self.headers = {
            "User-Agent": "IndustrialFacilityIntelligence/3.0 (contact: analyst@synleverage.com)"
        }
        self.request_delay_seconds = 2.0
        self.max_retries = 4
        self.existing_keys = self._load_existing_keys() if self.resume else set()

    def _load_existing_keys(self) -> set:
        if not self.output_path:
            return set()
        try:
            with open(self.output_path, mode="r", encoding="utf-8") as handle:
                keys = set()
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    key = (
                        record.get("plant_id") or "",
                        record.get("facility_name") or "",
                        (record.get("location") or {}).get("address_or_area") or "",
                        (record.get("location") or {}).get("city") or "",
                        record.get("state") or "",
                    )
                    keys.add(key)
                return keys
        except FileNotFoundError:
            return set()

    def _record_key(self, spec: Dict[str, Any]) -> tuple:
        location = spec.get("location") or {}
        return (
            spec.get("plant_id") or "",
            spec.get("facility_name") or "",
            location.get("address_or_area") or "",
            location.get("city") or "",
            spec.get("state") or "",
        )

    # -------------------------------------------------------------------------
    # 1. BULK SEEDING: EPA ECHO REST Endpoint (p_ncs parameter)
    # -------------------------------------------------------------------------
    async def _fetch_with_retry(self, session: aiohttp.ClientSession, url: str, params: Dict[str, Any], naics_code: str) -> Optional[str]:
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    backoff = min(30.0, 2 ** (attempt - 1))
                    logging.warning(f"[US Seeding] Retrying NAICS {naics_code} in {backoff}s after attempt {attempt}")
                    await asyncio.sleep(backoff)
                else:
                    await asyncio.sleep(self.request_delay_seconds)

                async with session.get(url, params=params, headers=self.headers, timeout=30) as resp:
                    text_response = await resp.text()

                    if resp.status == 200:
                        return text_response

                    retry_after = resp.headers.get("Retry-After")
                    if resp.status in {429, 500, 502, 503, 504}:
                        if attempt < self.max_retries:
                            wait_seconds = float(retry_after) if retry_after and retry_after.isdigit() else min(30.0, 2 ** attempt)
                            logging.warning(f"[US Seeding] NAICS {naics_code} hit HTTP {resp.status}; waiting {wait_seconds}s")
                            await asyncio.sleep(wait_seconds)
                            continue

                    logging.warning(f"NAICS {naics_code} returned HTTP {resp.status}")
                    return None
            except Exception as e:
                if attempt < self.max_retries:
                    logging.warning(f"[US Seeding] Error fetching NAICS {naics_code} (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(min(30.0, 2 ** attempt))
                    continue
                logging.error(f"Error fetching NAICS {naics_code}: {e}")
                return None

        return None

    async def fetch_us_epa_by_naics(self, session: aiohttp.ClientSession, naics_code: str) -> List[Dict[str, Any]]:
        """
        Queries EPA ECHO REST Service for facilities filtering by NAICS code (p_ncs),
        with retry/backoff to cope with throttling.
        """
        url = "https://echodata.epa.gov/echo/echo_rest_services.get_facility_info"
        params = {
            "output": "JSON",
            "p_ncs": naics_code
        }
        logging.info(f"[US Seeding] Querying EPA ECHO for NAICS {naics_code}...")

        text_response = await self._fetch_with_retry(session, url, params, naics_code)
        if not text_response:
            return []

        try:
            data = json.loads(text_response)
            facilities = data.get("Results", {}).get("Facilities", [])
            logging.info(f"[US Seeding] Retrieved {len(facilities)} EPA facilities for NAICS {naics_code}.")
            return facilities
        except json.JSONDecodeError:
            logging.error(f"EPA returned non-JSON response for NAICS {naics_code}.")
            return []

    # -------------------------------------------------------------------------
    # 2. ENRICHMENT & MULTI-ALIAS SCHEMA NORMALIZATION
    # -------------------------------------------------------------------------
    def _extract_coordinate_value(self, raw_record: Dict[str, Any], candidates: List[str]) -> Optional[float]:
        for key in candidates:
            value = raw_record.get(key)
            if value in (None, "", " "):
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if numeric not in (0.0, 0):
                return numeric
        return None

    def enrich_to_auto_spec(self, raw_record: Dict[str, Any], naics_code: str, country: str = "US") -> Dict[str, Any]:
        """
        Maps EPA ECHO facility attributes into the target auto_spec schema,
        using multi-alias fallbacks for names, addresses, and coordinates.
        """
        # Facility Name fallbacks
        fac_name = (
            raw_record.get("FacilityName") 
            or raw_record.get("FacName") 
            or raw_record.get("PRIMARY_NAME") 
            or raw_record.get("SourceID") 
            or "Automotive Manufacturing Facility"
        )

        # ID fallbacks
        registry_id = raw_record.get("SourceID") or raw_record.get("RegistryID") or raw_record.get("REGISTRY_ID") or "UNKNOWN"

        # Address fallbacks
        address = (
            raw_record.get("StreetAddress") 
            or raw_record.get("FacStreet") 
            or raw_record.get("LOCATION_ADDRESS") 
            or raw_record.get("Address") 
            or ""
        )
        city = (
            raw_record.get("City") 
            or raw_record.get("FacCity") 
            or raw_record.get("CITY_NAME") 
            or ""
        )
        state = (
            raw_record.get("State") 
            or raw_record.get("FacState") 
            or raw_record.get("StateCode") 
            or raw_record.get("STATE_ABBR") 
            or ""
        )
        
        # Geospatial coordinate fallbacks
        lat = self._extract_coordinate_value(
            raw_record,
            [
                "Latitude", "FacLat", "LATITUDE83", "Latitude83", "lat", "Lat", "Y", "latitude",
                "FacilityLatitude", "FAC_LATITUDE", "LAT", "CENTER_LAT"
            ]
        )
        lon = self._extract_coordinate_value(
            raw_record,
            [
                "Longitude", "FacLong", "LONGITUDE83", "Longitude83", "lon", "Lon", "X", "longitude",
                "FacilityLongitude", "FAC_LONGITUDE", "LONG", "CENTER_LON"
            ]
        )

        if lat is None:
            lat = 0.0
        if lon is None:
            lon = 0.0

        facility_type = "Assembly Plant" if naics_code in ["336111", "336112"] else "Tier 1/2 Supplier Facility"

        return {
            "state": state,
            "state_abbr": state,
            "facility_name": fac_name,
            "plant_id": f"FAC-{country}-{registry_id}",
            "name": fac_name,
            "oem_or_parent": fac_name,
            "facility_type": facility_type,
            "products": [f"Automotive Component Manufacturing (NAICS: {naics_code})"],
            "location": {
                "city": city,
                "address_or_area": address,
                "coordinates": {"lat": lat, "lon": lon}
            },
            "status": "Operational",
            "opened_or_announced": None,
            "approximate_employment": None,
            "annual_capacity_estimate": None,
            "notes": f"Seeded via EPA ECHO (NAICS: {naics_code}, ID: {registry_id})",
            "last_verified": "2026-08-03",
            "sources": [
                "https://echodata.epa.gov/echo/echo_rest_services.get_facility_info"
            ],
            "latitude": lat,
            "longitude": lon,
            "total_sq_ft": None,
            "clear_height_ft": None,
            "floor_load_lb_sqft": None,
            "existing_shops": [],
            "current_certifications": ["IATF 16949", "ISO 14001"],
            "has_cleanroom": False,
            "defense_conversion_profile": {
                "facility_characteristics": {
                    "building_type_and_clear_span": f"High-bay industrial structure ({facility_type})",
                    "floor_loading_capacity": None,
                    "crane_and_overhead_handling": None,
                    "available_utilities": "Industrial power and process water infrastructure",
                    "site_size_and_expansion_room": None,
                    "security_and_access_control": None
                },
                "production_capabilities": {
                    "current_processes": [f"NAICS {naics_code} Automotive Production"],
                    "precision_and_tolerance_levels": "Precision automotive OEM quality specifications",
                    "existing_automation_and_robotics": "Automated material handling and assembly cells",
                    "cleanroom_or_controlled_environment": None,
                    "testing_and_quality_infrastructure": None
                },
                "workforce_and_skills": {
                    "approximate_skilled_trades": "Mechatronics, tooling, PLC technicians, machining",
                    "engineering_presence_on_site": "Manufacturing & process quality engineering staff",
                    "union_status_and_flexibility_notes": None,
                    "training_infrastructure": None
                },
                "supply_chain_and_logistics": {
                    "proximity_to_key_suppliers_or_ports": f"Located in {state} manufacturing corridor",
                    "rail_or_heavy_transport_access": "Regional interstate / rail logistics access",
                    "existing_defense_or_aerospace_suppliers_nearby": None
                },
                "historical_or_current_dual_use": {
                    "prior_defense_work": None,
                    "ITAR_or_export_control_experience": "EAR/USMCA compliance standard",
                    "existing_security_clearances_on_site": "Commercial physical security"
                },
                "conversion_indicators_summary": "Indexed in EPA Federal Database. Structural load audit required.",
                "data_gaps": ["Floor load PSI", "Clear height ft", "Crane tonnage"]
            }
        }

    # -------------------------------------------------------------------------
    # 3. PIPELINE ORCHESTRATOR
    # -------------------------------------------------------------------------
    async def run(self):
        logging.info("Starting Bulk Industrial Seeding Pipeline across North America...")
        total_records_written = 0
        total_skipped_existing = 0

        mode = "w"
        if self.resume and os.path.exists(self.output_path):
            mode = "a"
            logging.info(f"Resume mode enabled; appending to existing '{self.output_path}'")
        elif not self.resume:
            logging.info("Full regeneration requested; overwriting existing output")

        async with aiohttp.ClientSession() as session:
            with open(self.output_path, mode=mode, encoding="utf-8") as out_file:
                for naics in NAICS_CODES:
                    raw_facilities = await self.fetch_us_epa_by_naics(session, naics)

                    for raw_item in raw_facilities:
                        spec = self.enrich_to_auto_spec(raw_item, naics_code=naics, country="US")
                        key = self._record_key(spec)
                        if self.resume and key in self.existing_keys:
                            total_skipped_existing += 1
                            continue

                        out_file.write(json.dumps(spec, ensure_ascii=False) + "\n")
                        self.existing_keys.add(key)
                        total_records_written += 1

        logging.info(
            f"Pipeline complete. Wrote {total_records_written} new facility records and skipped {total_skipped_existing} existing records in '{self.output_path}'."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Overwrite the existing output file instead of resuming")
    args = parser.parse_args()

    pipeline = NorthAmericaAutoPipeline(resume=not args.reset)
    asyncio.run(pipeline.run())