"""
CAM (Community Association Manager) License Enricher

Cross-references property managers from DBPR condo data against
the CAM license file to verify:
- Is the property manager actually a licensed CAM?
- What's their license status (active/expired)?
- Where are they located?

The cams.csv file is tab-delimited with no header row, 665K+ rows
(multiple CE records per CAM). We deduplicate by license number.

Columns (tab-separated):
0: License Type ("CAM")
1: License Type ("CAM")
2: License Number (CAM63657)
3: Name (LAST, FIRST MIDDLE)
4: Address Line 1
5: Address Line 2
6: City, State Zip
7: License Expiration (M/D/YYYY)
8: Course Number
9: Course Name
10: CE Hours
11: Completion Date
"""

import csv
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)

# In-memory cache: {normalized_name: {license_number, name, address, expiration}}
_cam_cache: dict[str, dict] | None = None
_cam_cache_time: float = 0
CACHE_TTL = 3600 * 12  # 12 hours — this file is big


def _normalize_name(name: str) -> str:
    """Normalize name for fuzzy matching: lowercase, strip punctuation."""
    import re
    return re.sub(r'[^a-z\s]', '', name.lower()).strip()


def _load_cam_data() -> dict[str, dict]:
    """Load and deduplicate CAM license data from cams.csv.

    Returns dict keyed by normalized name → CAM info.
    Also indexes by license number for direct lookup.
    """
    # Search multiple possible locations
    search_paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "filestore", "System Data", "DBPR", "cams.csv"),
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "cams.csv"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "cams.csv"),
    ]

    filepath = None
    for p in search_paths:
        resolved = os.path.abspath(p)
        if os.path.exists(resolved):
            filepath = resolved
            break

    if not filepath:
        logger.info("cams.csv not found — CAM enricher disabled")
        return {}

    cams: dict[str, dict] = {}
    seen_licenses: set[str] = set()

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                if len(row) < 8:
                    continue

                license_num = row[2].strip() if len(row) > 2 else ""
                if not license_num or license_num in seen_licenses:
                    continue
                seen_licenses.add(license_num)

                name = row[3].strip() if len(row) > 3 else ""
                addr1 = row[4].strip() if len(row) > 4 else ""
                addr2 = row[5].strip() if len(row) > 5 else ""
                city_state_zip = row[6].strip() if len(row) > 6 else ""
                expiration = row[7].strip() if len(row) > 7 else ""

                address = f"{addr1} {addr2}".strip()
                if city_state_zip:
                    address = f"{address}, {city_state_zip}" if address else city_state_zip

                cam_info = {
                    "license_number": license_num,
                    "name": name,
                    "address": address,
                    "expiration": expiration,
                }

                # Index by normalized name for fuzzy matching
                norm = _normalize_name(name)
                if norm:
                    cams[norm] = cam_info

                # Also index by license number
                cams[license_num.lower()] = cam_info

        logger.info(f"CAM data: loaded {len(seen_licenses)} unique licenses from {filepath}")
    except Exception as e:
        logger.warning(f"Failed to load CAM data: {e}")

    return cams


def _get_cam_data() -> dict[str, dict]:
    global _cam_cache, _cam_cache_time
    now = datetime.now(timezone.utc).timestamp()
    if _cam_cache is not None and (now - _cam_cache_time) < CACHE_TTL:
        return _cam_cache
    _cam_cache = _load_cam_data()
    _cam_cache_time = now
    return _cam_cache


def _find_cam(name: str, cams: dict[str, dict]) -> dict | None:
    """Find a CAM by name, trying exact then fuzzy match."""
    if not name:
        return None

    norm = _normalize_name(name)

    # Exact normalized match
    if norm in cams:
        return cams[norm]

    # Try matching last name + first initial
    parts = norm.split()
    if len(parts) >= 2:
        # CAM names are "LAST, FIRST" — try matching against that
        for key, val in cams.items():
            if parts[0] in key and parts[1][:3] in key:
                return val

    return None


@register_enricher("TARGETED", "cam_license")
def enrich_cam_license(entity: Entity, db: Session) -> bool:
    """Cross-reference property manager against CAM license records."""
    chars = entity.characteristics or {}

    # Get the property manager name to look up
    pm_name = str(chars.get("property_manager") or chars.get("dbpr_managing_entity") or
                   chars.get("sunbiz_registered_agent") or "")
    if not pm_name or len(pm_name) < 3:
        return False

    cams = _get_cam_data()
    if not cams:
        return False

    cam = _find_cam(pm_name, cams)

    updates: dict = {}
    if cam:
        updates["cam_license_number"] = cam["license_number"]
        updates["cam_license_name"] = cam["name"]
        updates["cam_license_address"] = cam["address"]
        updates["cam_license_expiration"] = cam["expiration"]

        # Check if license is current
        try:
            exp_date = datetime.strptime(cam["expiration"], "%m/%d/%Y")
            updates["cam_license_active"] = exp_date > datetime.now()
        except (ValueError, TypeError):
            updates["cam_license_active"] = None
    else:
        # No CAM license found — flag it
        updates["cam_license_found"] = False
        updates["cam_license_warning"] = f"No CAM license found for: {pm_name}"

    update_characteristics(entity, updates, "cam_license")

    fields = [k for k, v in updates.items() if v is not None]
    if cam:
        detail = f"CAM: {cam['license_number']} ({cam['name']}), expires {cam['expiration']}"
    else:
        detail = f"CAM: No license found for '{pm_name}'"

    record_enrichment(
        entity, db,
        source_id="cam_license",
        fields_updated=fields,
        source_url="https://www2.myfloridalicense.com/community-association-managers-and-firms/public-records/",
        detail=detail,
    )

    return True
