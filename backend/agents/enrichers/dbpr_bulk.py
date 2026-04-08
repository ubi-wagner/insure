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
    "county_summary": {
        "local": "data/countysummary.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/countysummary.csv",
    },
    "developer_summary": {
        "local": "data/developersummary.csv",
        "remote": "https://www2.myfloridalicense.com/sto/file_download/extracts/developersummary.csv",
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


# Street suffix abbreviations (full → abbr)
_STREET_ABBR = {
    "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "BLVD": "BLVD",
    "DRIVE": "DR", "LANE": "LN", "ROAD": "RD", "COURT": "CT",
    "CIRCLE": "CIR", "HIGHWAY": "HWY", "PLACE": "PL", "PARKWAY": "PKWY",
    "TERRACE": "TER", "TRAIL": "TRL", "WAY": "WAY",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}

# Common street suffix words to drop when comparing core street name tokens
_STREET_SUFFIX_TOKENS = {
    "ST", "AVE", "BLVD", "DR", "LN", "RD", "CT", "CIR", "HWY", "PL", "PKWY",
    "TER", "TRL", "WAY", "N", "S", "E", "W", "NE", "NW", "SE", "SW",
}


def _parse_address(raw: str) -> dict:
    """Parse a free-form address into structured components.

    Returns:
        {
            "street_num": "2200",
            "street_tokens": {"NW", "72", "AVE"},     # for comparison (incl directionals)
            "street_core": {"72"},                     # name tokens only (suffixes/dirs removed)
            "city": "MIAMI",
            "state": "FL",
            "zip": "33137",
            "raw_normalized": "2200 NW 72 AVE MIAMI FL 33137",
        }
    """
    if not raw:
        return {"street_num": "", "street_tokens": set(), "street_core": set(),
                "city": "", "state": "", "zip": "", "raw_normalized": ""}

    addr = raw.upper().strip()
    # Strip unit/apt/suite suffixes
    addr = re.sub(r'\s*(APT|UNIT|STE|SUITE|#|BLDG|NO)\s*\S*', '', addr)
    # Apply standard abbreviations as whole-word replacements
    for full, abbr in _STREET_ABBR.items():
        addr = re.sub(rf'\b{full}\b', abbr, addr)
    # Collapse whitespace and punctuation
    addr = re.sub(r'[,]+', ' ', addr)
    addr = re.sub(r'\s+', ' ', addr).strip()

    # Extract zip (5 digit, optionally + 4)
    zip_match = re.search(r'\b(\d{5})(?:-\d{4})?\b', addr)
    zipcode = zip_match.group(1) if zip_match else ""

    # Extract state (2-letter, usually right before zip)
    state = ""
    if zip_match:
        before_zip = addr[:zip_match.start()].rstrip()
        state_match = re.search(r'\b([A-Z]{2})\s*$', before_zip)
        if state_match:
            state = state_match.group(1)

    # Extract street number (first numeric token)
    num_match = re.match(r'(\d+)', addr)
    street_num = num_match.group(1) if num_match else ""

    # All tokens for comparison
    tokens = set(addr.split())
    # Drop the zip, state from tokens
    tokens.discard(zipcode)
    if state:
        tokens.discard(state)

    # Core street name tokens — drop directionals and street suffixes
    core = {t for t in tokens if t not in _STREET_SUFFIX_TOKENS and not t.isdigit()}
    # If everything is a directional/suffix, fall back to numeric tokens
    if not core:
        core = {t for t in tokens if t != street_num}

    # City: token sequence between street part and state (best effort)
    # We don't do strict city extraction — we just keep it for display
    city = ""
    if state and zip_match:
        # Take tokens between numeric street and state
        try:
            head = addr[: addr.rfind(state)].strip()
            tail_tokens = head.split()
            # Skip numeric/directional tokens at start
            city_tokens = []
            for t in reversed(tail_tokens):
                if t.isdigit() or t in _STREET_SUFFIX_TOKENS:
                    break
                city_tokens.append(t)
            city = " ".join(reversed(city_tokens))
        except Exception:
            city = ""

    return {
        "street_num": street_num,
        "street_tokens": tokens,
        "street_core": core,
        "city": city,
        "state": state,
        "zip": zipcode,
        "raw_normalized": addr,
    }


def _county_matches(entity_county: str, condo_county: str) -> bool:
    """Strict county comparison."""
    if not entity_county or not condo_county:
        return False
    e = entity_county.lower().replace("-", " ").strip()
    c = condo_county.lower().replace("-", " ").strip()
    return e == c or e in c or c in e


def _match_entity_to_condo(entity: Entity, records: list[dict]) -> dict | None:
    """Find the best matching DBPR condo record for an entity.

    STRICT address-based matching ONLY. No name-based fallback.

    Required for any match:
      1. County must match (entity.county == condo.County)
      2. Street number must match exactly
      3. At least one core street name token must overlap

    Tiebreaker bonus:
      4. Zip match adds confidence
      5. Name overlap adds confidence (only as a tiebreaker, never the sole signal)

    Returns None if no record meets the strict requirements.
    """
    entity_addr_raw = entity.address or ""
    entity_county = entity.county or ""

    if not entity_addr_raw or not entity_county:
        return None

    parsed_entity = _parse_address(entity_addr_raw)
    if not parsed_entity["street_num"]:
        return None  # Can't match without a street number

    entity_name = _normalize(entity.name or "")

    best_match = None
    best_score = 0

    for record in records:
        condo_county = record.get("County", "") or ""
        if not _county_matches(entity_county, condo_county):
            continue

        condo_addr_raw = record.get("Street City State Zip", "") or ""
        if not condo_addr_raw:
            continue

        parsed_condo = _parse_address(condo_addr_raw)
        if not parsed_condo["street_num"]:
            continue

        # REQUIRED: street number must match exactly
        if parsed_entity["street_num"] != parsed_condo["street_num"]:
            continue

        # REQUIRED: at least one core street name token must overlap
        core_overlap = parsed_entity["street_core"] & parsed_condo["street_core"]
        if not core_overlap:
            continue

        # Base score for satisfying all required conditions
        score = 80

        # Bonus: zip match
        if parsed_entity["zip"] and parsed_condo["zip"]:
            if parsed_entity["zip"] == parsed_condo["zip"]:
                score += 10

        # Bonus: more shared core street tokens = stronger match
        score += min(5, len(core_overlap))

        # Bonus: full token overlap (suffixes + directionals)
        shared_tokens = parsed_entity["street_tokens"] & parsed_condo["street_tokens"]
        if len(shared_tokens) >= 3:
            score += 5

        # Bonus: name overlap as tiebreaker (only if address already matches)
        condo_name = _normalize(record.get("Condo Name", "") or "")
        if entity_name and condo_name:
            entity_words = set(entity_name.split())
            condo_words = set(condo_name.split())
            name_overlap = len(entity_words & condo_words)
            if name_overlap >= 2:
                score += 5

        if score > best_score:
            best_score = score
            best_match = record

    # best_score is 0 when no candidate met the strict requirements above.
    # Otherwise it's at least 80 (base for satisfying all required conditions).
    return best_match if best_score >= 80 else None


@register_enricher("dbpr_bulk")
def enrich_dbpr_bulk(entity: Entity, db: Session) -> bool:
    """Match entity against DBPR bulk condo CSV data.

    Searches the county-mapped regional CSV first; if no match, falls back
    to searching ALL regional condo CSVs (some counties span multiple regions
    or get filed in unexpected files).
    """
    county = entity.county
    if not county:
        return False

    # Primary search: the county's expected region
    match = None
    primary_region = COUNTY_TO_REGION.get(county)
    if primary_region:
        records = _get_csv_data(primary_region)
        if records:
            match = _match_entity_to_condo(entity, records)

    # Fallback: search every condo CSV (CW, MD, NF, CE, conv, coopmailing)
    if not match:
        for region in ("central_west", "dade_monroe", "central_east",
                       "north_florida", "condo_conversions", "cooperatives"):
            if region == primary_region:
                continue
            records = _get_csv_data(region)
            if records:
                match = _match_entity_to_condo(entity, records)
                if match:
                    break

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
