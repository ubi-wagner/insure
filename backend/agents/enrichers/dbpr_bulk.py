"""
DBPR Bulk Condo Data Enricher

Downloads and caches the DBPR condominium CSV extracts which contain:
- Condo association names, project numbers, file numbers
- Managing entity (property management company) name + address
- Number of units (official DBPR count)
- County, address, recorded date, status
- Financial data: revenue, expenses, fund balances (when available)

CSV sources (free, updated periodically by DBPR):
- Central West: Pinellas, Hillsborough, Pasco, Manatee, Sarasota, Charlotte, Lee, Collier
- Dade/Monroe: Miami-Dade
- Southeast: Broward, Palm Beach

This enricher matches entities against the cached DBPR data by name/address.
"""

import csv
import io
import logging
import os
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)

# DBPR CSV files — try local path first (uploaded), then remote URL
DBPR_CSV_FILES = {
    "central_west": {
        "local": "data/Condo_CW.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/Condo_CW.csv",
    },
    "dade_monroe": {
        "local": "data/Condo_MD.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/Condo_MD.csv",
    },
    "central_east": {
        "local": "data/condo_CE.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/condo_CE.csv",
    },
    "north_florida": {
        "local": "data/Condo_NF.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/Condo_NF.csv",
    },
    "condo_conversions": {
        "local": "data/condo_conv.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/condo_conv.csv",
    },
    "cooperatives": {
        "local": "data/coopmailing.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/coopmailing.csv",
    },
    "cam_licenses": {
        "local": "data/cams.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/cams.csv",
    },
    "payments_a": {
        "local": "data/paymenthist_8002A.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/paymenthist_8002A.csv",
    },
    "payments_d": {
        "local": "data/paymenthist_8002D.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/paymenthist_8002D.csv",
    },
    "payments_j": {
        "local": "data/paymenthist_8002J.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/paymenthist_8002J.csv",
    },
    "payments_p": {
        "local": "data/paymenthist_8002P.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/paymenthist_8002P.csv",
    },
    "payments_s": {
        "local": "data/paymenthist_8002S.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/paymenthist_8002S.csv",
    },
    "timeshare": {
        "local": "data/tsmailing.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/tsmailing.csv",
    },
}

# Map our target counties to CSV regions
COUNTY_TO_REGION = {
    "Pinellas": "central_west", "Hillsborough": "central_west",
    "Pasco": "central_west", "Manatee": "central_west",
    "Sarasota": "central_west", "Charlotte": "central_west",
    "Lee": "central_west", "Collier": "central_west",
    "Miami-Dade": "dade_monroe",
    "Broward": "central_east", "Palm Beach": "central_east",
}

# In-memory cache of parsed CSV data, keyed by region
_csv_cache: dict[str, list[dict]] = {}
_csv_cache_time: dict[str, float] = {}
CSV_CACHE_TTL = 3600 * 6  # 6 hours


def _load_csv(region: str) -> list[dict]:
    """Load a DBPR CSV — tries local file first, then remote download."""
    config = DBPR_CSV_FILES.get(region)
    if not config:
        return []

    # Search multiple locations for the CSV file
    bare_name = os.path.basename(config["local"])
    base = os.path.dirname(__file__)
    search_paths = [
        os.path.join(base, "..", "..", config["local"]),                          # backend/data/
        os.path.join(base, "..", "..", "filestore", "System Data", "DBPR", bare_name),  # filestore/System Data/DBPR/
        os.path.join(base, "..", "..", "..", config["local"]),                     # repo root/data/
        os.path.join(base, "..", "..", "..", bare_name),                           # repo root/
    ]

    for path in search_paths:
        resolved = os.path.abspath(path)
        if os.path.exists(resolved):
            try:
                with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                logger.info(f"DBPR CSV {region}: loaded {len(rows)} records from {resolved}")
                return rows
            except Exception as e:
                logger.warning(f"Failed to read local CSV {resolved}: {e}")

    # Fall back to remote download
    remote_url = config.get("remote")
    if not remote_url:
        return []

    try:
        with httpx.Client(timeout=60, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }) as client:
            resp = client.get(remote_url)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            rows = list(reader)
            logger.info(f"DBPR CSV {region}: downloaded {len(rows)} records from {remote_url}")
            return rows
    except Exception as e:
        logger.warning(f"DBPR CSV download failed for {region}: {e}")
        return []


def _get_csv_data(region: str) -> list[dict]:
    """Get CSV data, using cache if fresh."""
    now = datetime.now(timezone.utc).timestamp()
    if region in _csv_cache and (now - _csv_cache_time.get(region, 0)) < CSV_CACHE_TTL:
        return _csv_cache[region]

    data = _load_csv(region)
    if data:
        _csv_cache[region] = data
        _csv_cache_time[region] = now
    return data


def _normalize(s: str) -> str:
    """Normalize a string for fuzzy matching."""
    return re.sub(r'[^a-z0-9\s]', '', s.lower()).strip()


def _normalize_addr(s: str) -> str:
    """Normalize an address for matching — strip unit/apt, abbreviate."""
    addr = s.upper().strip()
    # Remove unit/apt/suite suffixes
    addr = re.sub(r'\s*(APT|UNIT|STE|SUITE|#|BLDG|NO)\s*\S*$', '', addr)
    # Standard abbreviations
    for full, abbr in [("STREET", "ST"), ("AVENUE", "AVE"), ("BOULEVARD", "BLVD"),
                       ("DRIVE", "DR"), ("LANE", "LN"), ("ROAD", "RD"), ("COURT", "CT"),
                       ("CIRCLE", "CIR"), ("HIGHWAY", "HWY"), ("PLACE", "PL"),
                       ("NORTH", "N"), ("SOUTH", "S"), ("EAST", "E"), ("WEST", "W")]:
        addr = re.sub(rf'\b{full}\b', abbr, addr)
    # Extract just street number + name (first 2-3 tokens)
    return re.sub(r'\s+', ' ', addr).strip()


def _extract_street_number(addr: str) -> str:
    """Extract the street number from an address for quick matching."""
    match = re.match(r'(\d+)', addr)
    return match.group(1) if match else ""


def _match_entity_to_condo(entity: Entity, records: list[dict]) -> dict | None:
    """Find the best matching DBPR condo record for an entity.

    Strategy (in priority order):
    1. County + street address match (most reliable for physical properties)
    2. County + name match (for when addresses differ)
    3. Name-only match (fallback)
    """
    entity_name = _normalize(entity.name or "")
    entity_addr_raw = entity.address or ""
    entity_addr = _normalize_addr(entity_addr_raw)
    entity_street_num = _extract_street_number(entity_addr)
    entity_county = (entity.county or "").lower()
    chars = entity.characteristics or {}
    entity_owner = _normalize(str(chars.get("dor_owner", "") or ""))

    if not entity_name and not entity_addr:
        return None

    best_match = None
    best_score = 0

    for record in records:
        condo_name = _normalize(record.get("Condo Name", "") or "")
        condo_addr = _normalize_addr(record.get("Street City State Zip", "") or "")
        condo_county = (record.get("County", "") or "").lower()
        condo_street_num = _extract_street_number(condo_addr)

        score = 0

        # ─── Strategy 1: Address matching (most reliable) ───
        if entity_addr and condo_addr:
            # Same street number is a strong signal
            if entity_street_num and condo_street_num and entity_street_num == condo_street_num:
                # Check if street names overlap
                entity_parts = set(entity_addr.split())
                condo_parts = set(condo_addr.split())
                shared = entity_parts & condo_parts
                if len(shared) >= 2:  # Street number + at least one street name word
                    score = 85
                    # County match bonus
                    if entity_county and condo_county and entity_county in condo_county:
                        score = 95

        # ─── Strategy 2: Name matching ───
        if score < 80 and entity_name and condo_name:
            name_score = 0
            if entity_name == condo_name:
                name_score = 100
            elif entity_name in condo_name or condo_name in entity_name:
                name_score = 80
            else:
                # Word overlap
                entity_words = set(entity_name.split())
                condo_words = set(condo_name.split())
                if entity_words and condo_words:
                    overlap = len(entity_words & condo_words)
                    total = max(len(entity_words), len(condo_words))
                    if overlap >= 2:
                        name_score = int(60 * overlap / total)

            # Owner name match (DOR owner → condo name)
            if name_score < 60 and entity_owner and condo_name:
                if entity_owner in condo_name or condo_name in entity_owner:
                    name_score = max(name_score, 70)

            # County match bonus for name matches
            if name_score >= 40 and entity_county and condo_county:
                if entity_county in condo_county or condo_county in entity_county:
                    name_score += 10

            score = max(score, name_score)

        # ─── Address partial match bonus ───
        if score >= 30 and score < 85 and entity_addr and condo_addr:
            if entity_addr in condo_addr or condo_addr in entity_addr:
                score += 15

        if score > best_score and score >= 35:
            best_score = score
            best_match = record

    return best_match


@register_enricher("dbpr_bulk")
def enrich_dbpr_bulk(entity: Entity, db: Session) -> bool:
    """Match entity against DBPR bulk condo CSV data."""
    county = entity.county
    if not county:
        return False

    region = COUNTY_TO_REGION.get(county)
    if not region:
        return False

    records = _get_csv_data(region)
    if not records:
        return False

    match = _match_entity_to_condo(entity, records)
    if not match:
        return False

    # Extract fields — CSV headers vary between files, try common variations
    # Exact headers from real Condo_CW.csv:
    # "Project Number","File Number","Condo Name","County",
    # "Street City State Zip","Units","Recorded Date",
    # "Primary Status","Secondary Status",
    # "Managing Entity Number","Managing Entity Name",
    # "Managing Entity Route","Managing Entity Street",
    # "Managing Entity City","Managing Entity State","Managing Entity Zip"

    def get(record: dict, *keys: str) -> str:
        for k in keys:
            val = record.get(k)
            if val and str(val).strip():
                return str(val).strip()
        return ""

    updates: dict = {}

    condo_name = get(match, "Condo Name")
    if condo_name:
        updates["dbpr_condo_name"] = condo_name

    project_num = get(match, "Project Number")
    if project_num:
        updates["dbpr_project_number"] = project_num

    file_num = get(match, "File Number")
    if file_num:
        updates["dbpr_file_number"] = file_num

    condo_addr = get(match, "Street City State Zip")
    if condo_addr:
        updates["dbpr_address"] = condo_addr

    units = get(match, "Units")
    if units and units.isdigit():
        updates["dbpr_official_units"] = int(units)
        updates["units_estimate"] = int(units)  # Override OSM estimate

    recorded = get(match, "Recorded Date")
    if recorded:
        updates["dbpr_recorded_date"] = recorded

    status = get(match, "Primary Status")
    if status:
        updates["dbpr_status"] = status

    secondary = get(match, "Secondary Status")
    if secondary:
        updates["dbpr_secondary_status"] = secondary

    mgmt_name = get(match, "Managing Entity Name")
    if mgmt_name:
        updates["dbpr_managing_entity"] = mgmt_name
        updates["property_manager"] = mgmt_name

    mgmt_num = get(match, "Managing Entity Number")
    if mgmt_num:
        updates["dbpr_managing_entity_number"] = mgmt_num

    # Managing entity address from individual fields
    mgmt_addr_parts = [
        get(match, "Managing Entity Route"),
        get(match, "Managing Entity Street"),
        get(match, "Managing Entity City"),
        get(match, "Managing Entity State"),
        get(match, "Managing Entity Zip"),
    ]
    mgmt_addr = ", ".join(p for p in mgmt_addr_parts if p)
    if mgmt_addr:
        updates["dbpr_managing_entity_address"] = mgmt_addr

    if not updates:
        return False

    update_characteristics(entity, updates, "dbpr_bulk")

    fields = [k for k, v in updates.items() if v is not None]
    detail_parts = [f"DBPR bulk: {len(fields)} fields"]
    if updates.get("dbpr_condo_name"):
        detail_parts.append(updates["dbpr_condo_name"])
    if updates.get("dbpr_managing_entity"):
        detail_parts.append(f"mgmt={updates['dbpr_managing_entity']}")
    if updates.get("dbpr_official_units"):
        detail_parts.append(f"{updates['dbpr_official_units']} units")

    record_enrichment(
        entity, db,
        source_id="dbpr_bulk",
        fields_updated=fields,
        source_url="https://www2.myfloridalicense.com/condos-timeshares-mobile-homes/public-records/",
        detail=", ".join(detail_parts),
    )

    return True
