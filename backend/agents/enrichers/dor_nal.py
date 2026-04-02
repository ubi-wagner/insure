"""
FL DOR NAL (Name-Address-Legal) Tax Roll Enricher

The authoritative source for every parcel in Florida. 11 county files,
tab-delimited, ~90 columns each. This enricher matches leads by
physical address (PHY_ADDR1) and extracts:

- Owner name and mailing address
- Just/market value (JV) → TIV baseline
- Construction class (CONST_CLASS) → ISO rating
- Year built (ACT_YR_BLT, EFF_YR_BLT)
- Total living area sqft (TOT_LVG_AREA)
- Number of buildings (NO_BULDNG)
- Number of residential units (NO_RES_UNTS)
- DOR use code (DOR_UC) — 004=condo, 008=multifamily, etc.
- Land value (LND_VAL)
- Sale price and date (SALE_PRC1, SALE_YR1, SALE_MO1)
- Parcel ID, county number

Files: NAL{CO_NO}F2025{01}.csv (tab-delimited, one per county)
Upload to: System Data/DOR/

County numbers for our 11:
52=Pasco, 53=Pinellas, 29=Hillsborough, 41=Manatee, 58=Sarasota,
08=Charlotte, 36=Lee, 11=Collier, 50=Palm Beach, 13=Miami-Dade, 06=Broward
"""

import csv
import logging
import os
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)

# County number to name mapping
COUNTY_NUMBERS = {
    "52": "Pasco", "53": "Pinellas", "29": "Hillsborough",
    "41": "Manatee", "58": "Sarasota", "08": "Charlotte",
    "36": "Lee", "11": "Collier", "50": "Palm Beach",
    "13": "Miami-Dade", "06": "Broward",
}

COUNTY_NAME_TO_NUMBER = {v: k for k, v in COUNTY_NUMBERS.items()}

# DOR use codes relevant to insurance leads
DOR_USE_CODES = {
    "001": "Single Family", "002": "Mobile Home", "003": "Multi-Family (2-9)",
    "004": "Condominium", "005": "Cooperatives", "006": "Retirement Homes",
    "007": "Misc Residential", "008": "Multi-Family (10+)",
    "009": "Residential Common", "010": "Vacant Commercial",
    "011": "Stores", "012": "Mixed Use", "013": "Dept Stores",
    "014": "Supermarkets", "016": "Community Shopping", "017": "Regional Malls",
    "021": "Restaurants", "022": "Drive-in Restaurants",
    "023": "Financial Institutions", "024": "Insurance Companies",
    "027": "Auto Sales/Service", "028": "Parking Lots",
    "029": "Wholesale/Manufacturing", "030": "Florist/Greenhouses",
    "033": "Nightclubs/Bars", "034": "Bowling/Skating",
    "038": "Golf Courses", "039": "Hotels/Motels",
    "048": "Warehousing", "049": "Open Storage",
}

# In-memory cache: {county_number: {normalized_address: record}}
_nal_cache: dict[str, dict[str, dict]] = {}
_nal_cache_time: dict[str, float] = {}
CACHE_TTL = 3600 * 12  # 12 hours


def _normalize_address(addr: str) -> str:
    """Normalize address for matching."""
    if not addr:
        return ""
    addr = addr.upper().strip()
    # Remove unit/apt/suite suffixes
    addr = re.sub(r'\s*(APT|UNIT|STE|SUITE|#)\s*\S*$', '', addr)
    # Normalize common abbreviations
    addr = re.sub(r'\bSTREET\b', 'ST', addr)
    addr = re.sub(r'\bAVENUE\b', 'AVE', addr)
    addr = re.sub(r'\bBOULEVARD\b', 'BLVD', addr)
    addr = re.sub(r'\bDRIVE\b', 'DR', addr)
    addr = re.sub(r'\bLANE\b', 'LN', addr)
    addr = re.sub(r'\bROAD\b', 'RD', addr)
    addr = re.sub(r'\bCOURT\b', 'CT', addr)
    addr = re.sub(r'\bCIRCLE\b', 'CIR', addr)
    addr = re.sub(r'\bHIGHWAY\b', 'HWY', addr)
    addr = re.sub(r'\bNORTH\b', 'N', addr)
    addr = re.sub(r'\bSOUTH\b', 'S', addr)
    addr = re.sub(r'\bEAST\b', 'E', addr)
    addr = re.sub(r'\bWEST\b', 'W', addr)
    # Remove extra whitespace
    addr = re.sub(r'\s+', ' ', addr).strip()
    return addr


def _find_nal_files(county_no: str) -> list[str]:
    """Find NAL files for a county in filestore and data directories."""
    search_dirs = [
        os.path.join(os.path.dirname(__file__), "..", "..", "filestore", "System Data", "DOR"),
        os.path.join(os.path.dirname(__file__), "..", "..", "data"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".."),
    ]

    matches = []
    # NAL files are named like: NAL52F202501.csv or Pasco 52 Final NAL 2025F.csv etc.
    # Match any file containing the county number and NAL
    for d in search_dirs:
        resolved = os.path.abspath(d)
        if not os.path.exists(resolved):
            continue
        for f in os.listdir(resolved):
            f_upper = f.upper()
            # Match patterns: NAL{county}F, NAL{county_padded}F, or contains county number
            if (f.endswith('.csv') or f.endswith('.CSV')) and 'NAL' in f_upper:
                # Check if county number appears in filename
                if county_no in f or county_no.zfill(2) in f:
                    matches.append(os.path.join(resolved, f))
    return matches


def _load_county_nal(county_no: str) -> dict[str, dict]:
    """Load NAL data for a county, indexed by normalized physical address."""
    files = _find_nal_files(county_no)
    if not files:
        return {}

    filepath = files[0]  # Use first match
    records: dict[str, dict] = {}

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                phy_addr = row.get("PHY_ADDR1", "").strip()
                if not phy_addr:
                    continue

                norm = _normalize_address(phy_addr)
                if norm and norm not in records:
                    records[norm] = row

        logger.info(f"DOR NAL county {county_no}: loaded {len(records)} parcels from {filepath}")
    except Exception as e:
        logger.warning(f"Failed to load NAL for county {county_no}: {e}")

    return records


def _get_county_data(county_no: str) -> dict[str, dict]:
    """Get county NAL data with caching."""
    now = datetime.now(timezone.utc).timestamp()
    if county_no in _nal_cache and (now - _nal_cache_time.get(county_no, 0)) < CACHE_TTL:
        return _nal_cache[county_no]

    data = _load_county_nal(county_no)
    if data:
        _nal_cache[county_no] = data
        _nal_cache_time[county_no] = now
    return data


def _match_address(entity_addr: str, records: dict[str, dict]) -> dict | None:
    """Find best matching NAL record by normalized address."""
    if not entity_addr:
        return None

    norm = _normalize_address(entity_addr)
    if not norm:
        return None

    # Exact match
    if norm in records:
        return records[norm]

    # Try without street number (match just street name)
    parts = norm.split(" ", 1)
    if len(parts) > 1:
        street = parts[1]
        for key, record in records.items():
            if street in key:
                return record

    return None


def _safe_int(val) -> int | None:
    """Safely convert to int."""
    if not val:
        return None
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


def _safe_float(val) -> float | None:
    """Safely convert to float."""
    if not val:
        return None
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return None


@register_enricher("NEW", "dor_nal")
def enrich_dor_nal(entity: Entity, db: Session) -> bool:
    """Match entity against FL DOR NAL tax roll data."""
    county = entity.county
    if not county:
        return False

    county_no = COUNTY_NAME_TO_NUMBER.get(county)
    if not county_no:
        return False

    records = _get_county_data(county_no)
    if not records:
        return False

    # Try matching by physical address
    match = _match_address(entity.address, records)
    if not match:
        return False

    updates: dict = {}

    # Parcel ID
    parcel_id = match.get("PARCEL_ID", "").strip()
    if parcel_id:
        updates["dor_parcel_id"] = parcel_id

    # Owner
    owner = match.get("OWN_NAME", "").strip()
    if owner:
        updates["dor_owner"] = owner
        owner_parts = [
            match.get("OWN_ADDR1", "").strip(),
            match.get("OWN_ADDR2", "").strip(),
            match.get("OWN_CITY", "").strip(),
            match.get("OWN_STATE", "").strip(),
            match.get("OWN_ZIPCD", "").strip(),
        ]
        updates["dor_owner_address"] = ", ".join(p for p in owner_parts if p)

    # Values
    jv = _safe_int(match.get("JV"))
    if jv and jv > 0:
        updates["dor_market_value"] = jv
        # TIV = replacement cost ≈ 1.3x market value for FL condos
        replacement = round(jv * 1.3, -3)
        if not (entity.characteristics or {}).get("tiv_estimate"):
            updates["tiv_estimate"] = replacement
            updates["tiv"] = f"${replacement:,.0f}"

    lnd_val = _safe_int(match.get("LND_VAL"))
    if lnd_val and lnd_val > 0:
        updates["dor_land_value"] = lnd_val

    # Construction
    const_class = match.get("CONST_CLASS", "").strip()
    if const_class:
        updates["dor_construction_class"] = const_class

    # DOR use code
    dor_uc = match.get("DOR_UC", "").strip()
    if dor_uc:
        updates["dor_use_code"] = dor_uc
        updates["dor_use_description"] = DOR_USE_CODES.get(dor_uc, f"Code {dor_uc}")

    # Year built
    act_yr = _safe_int(match.get("ACT_YR_BLT"))
    if act_yr and 1800 <= act_yr <= 2026:
        updates["year_built"] = str(act_yr)
        updates["dor_year_built"] = act_yr

    eff_yr = _safe_int(match.get("EFF_YR_BLT"))
    if eff_yr and 1800 <= eff_yr <= 2026:
        updates["dor_effective_year_built"] = eff_yr

    # Building details
    sqft = _safe_int(match.get("TOT_LVG_AREA"))
    if sqft and sqft > 0:
        updates["dor_living_sqft"] = sqft

    num_bldg = _safe_int(match.get("NO_BULDNG"))
    if num_bldg and num_bldg > 0:
        updates["dor_num_buildings"] = num_bldg

    num_units = _safe_int(match.get("NO_RES_UNTS"))
    if num_units and num_units > 0:
        updates["dor_num_units"] = num_units
        updates["units_estimate"] = num_units  # Authoritative count

    # Sale history
    sale_prc = _safe_int(match.get("SALE_PRC1"))
    if sale_prc and sale_prc > 0:
        updates["dor_last_sale_price"] = sale_prc
    sale_yr = _safe_int(match.get("SALE_YR1"))
    sale_mo = _safe_int(match.get("SALE_MO1"))
    if sale_yr:
        updates["dor_last_sale_year"] = sale_yr
        if sale_mo:
            updates["dor_last_sale_date"] = f"{sale_mo}/{sale_yr}"

    # Special features value
    spec_val = _safe_int(match.get("SPEC_FEAT_VAL"))
    if spec_val and spec_val > 0:
        updates["dor_special_features_value"] = spec_val

    # Land sqft
    lnd_sqft = _safe_int(match.get("LND_SQFOOT"))
    if lnd_sqft and lnd_sqft > 0:
        updates["dor_land_sqft"] = lnd_sqft

    if not updates:
        return False

    update_characteristics(entity, updates, "dor_nal")

    fields = [k for k, v in updates.items() if v is not None]
    detail_parts = [f"DOR NAL: {len(fields)} fields"]
    if updates.get("dor_owner"):
        detail_parts.append(f"owner={updates['dor_owner'][:30]}")
    if updates.get("dor_market_value"):
        detail_parts.append(f"JV=${updates['dor_market_value']:,}")
    if updates.get("dor_construction_class"):
        detail_parts.append(f"const={updates['dor_construction_class']}")

    record_enrichment(
        entity, db,
        source_id="dor_nal",
        fields_updated=fields,
        source_url="https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx",
        detail=", ".join(detail_parts),
    )

    return True
