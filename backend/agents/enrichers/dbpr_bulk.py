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
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)

# DBPR CSV download URLs by region
DBPR_CSV_URLS = {
    "central_west": "https://www2.myfloridalicense.com/sto/file_download/extracts/Condo_CW.csv",
    "dade_monroe": "https://www2.myfloridalicense.com/sto/file_download/extracts/Condo_MD.csv",
    "central_east": "https://www2.myfloridalicense.com/sto/file_download/extracts/condo_CE.csv",
    "southeast": "https://www2.myfloridalicense.com/sto/file_download/extracts/Condo_SE.csv",
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


def _download_and_parse_csv(region: str) -> list[dict]:
    """Download a DBPR CSV file and parse it into a list of dicts."""
    url = DBPR_CSV_URLS.get(region)
    if not url:
        return []

    try:
        with httpx.Client(timeout=60, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }) as client:
            resp = client.get(url)
            resp.raise_for_status()
            text = resp.text

            reader = csv.DictReader(io.StringIO(text))
            rows = []
            for row in reader:
                rows.append(row)
            logger.info(f"DBPR CSV {region}: loaded {len(rows)} records")
            return rows
    except Exception as e:
        logger.warning(f"DBPR CSV download failed for {region}: {e}")
        return []


def _get_csv_data(region: str) -> list[dict]:
    """Get CSV data, using cache if fresh."""
    now = datetime.now(timezone.utc).timestamp()
    if region in _csv_cache and (now - _csv_cache_time.get(region, 0)) < CSV_CACHE_TTL:
        return _csv_cache[region]

    data = _download_and_parse_csv(region)
    if data:
        _csv_cache[region] = data
        _csv_cache_time[region] = now
    return data


def _normalize(s: str) -> str:
    """Normalize a string for fuzzy matching."""
    return re.sub(r'[^a-z0-9\s]', '', s.lower()).strip()


def _match_entity_to_condo(entity: Entity, records: list[dict]) -> dict | None:
    """Find the best matching DBPR condo record for an entity."""
    entity_name = _normalize(entity.name or "")
    entity_addr = _normalize(entity.address or "")

    if not entity_name:
        return None

    best_match = None
    best_score = 0

    for record in records:
        condo_name = _normalize(record.get("Condo Name", "") or record.get("CONDO_NAME", "") or "")
        condo_addr = _normalize(record.get("Address", "") or record.get("ADDRESS", "") or "")

        if not condo_name:
            continue

        # Score based on name similarity
        score = 0

        # Exact name match
        if entity_name == condo_name:
            score = 100
        # Entity name contained in condo name or vice versa
        elif entity_name in condo_name or condo_name in entity_name:
            score = 80
        else:
            # Word overlap
            entity_words = set(entity_name.split())
            condo_words = set(condo_name.split())
            if entity_words and condo_words:
                overlap = len(entity_words & condo_words)
                total = max(len(entity_words), len(condo_words))
                if overlap > 0:
                    score = int(60 * overlap / total)

        # Boost for address match
        if entity_addr and condo_addr and (entity_addr in condo_addr or condo_addr in entity_addr):
            score += 20

        if score > best_score and score >= 40:
            best_score = score
            best_match = record

    return best_match


@register_enricher("NEW", "dbpr_bulk")
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
    def get(record: dict, *keys: str) -> str:
        for k in keys:
            val = record.get(k)
            if val and str(val).strip():
                return str(val).strip()
        return ""

    updates: dict = {}

    condo_name = get(match, "Condo Name", "CONDO_NAME", "PROJECT_NAME")
    if condo_name:
        updates["dbpr_condo_name"] = condo_name

    project_num = get(match, "Project Number", "PROJECT_NUMBER", "PROJ_NUM")
    if project_num:
        updates["dbpr_project_number"] = project_num

    file_num = get(match, "File Number", "FILE_NUMBER")
    if file_num:
        updates["dbpr_file_number"] = file_num

    units = get(match, "Units", "UNITS", "NO_UNITS", "NUMBER_OF_UNITS")
    if units and units.isdigit():
        updates["dbpr_official_units"] = int(units)
        updates["units_estimate"] = int(units)  # Override OSM estimate with official count

    status = get(match, "Primary Status", "PRIMARY_STATUS", "STATUS")
    if status:
        updates["dbpr_status"] = status

    mgmt_name = get(match, "Managing Entity Name", "MANAGING_ENTITY_NAME", "ME_NAME")
    if mgmt_name:
        updates["dbpr_managing_entity"] = mgmt_name
        updates["property_manager"] = mgmt_name

    mgmt_num = get(match, "Managing Entity Number", "MANAGING_ENTITY_NUMBER", "ME_NUMBER")
    if mgmt_num:
        updates["dbpr_managing_entity_number"] = mgmt_num

    # Managing entity address
    mgmt_addr_parts = [
        get(match, "ME Route", "ME_ROUTE", "Managing Entity Route"),
        get(match, "ME Street", "ME_STREET", "Managing Entity Street"),
        get(match, "ME City", "ME_CITY", "Managing Entity City"),
        get(match, "ME State", "ME_STATE", "Managing Entity State"),
        get(match, "ME Zip", "ME_ZIP", "Managing Entity Zip"),
    ]
    mgmt_addr = ", ".join(p for p in mgmt_addr_parts if p)
    if mgmt_addr:
        updates["dbpr_managing_entity_address"] = mgmt_addr

    # Financial data
    revenue = get(match, "Total Revenue (Operating Fund)", "TOTAL_REV_OP", "Operating Revenue")
    if revenue:
        updates["dbpr_operating_revenue"] = revenue

    expenses = get(match, "Total Expenses (Operating Fund)", "TOTAL_EXP_OP", "Operating Expenses")
    if expenses:
        updates["dbpr_operating_expenses"] = expenses

    reserve_rev = get(match, "Total Revenue (Replacement Fund)", "TOTAL_REV_REPL", "Replacement Revenue")
    if reserve_rev:
        updates["dbpr_reserve_revenue"] = reserve_rev

    fund_balance = get(match, "Fund Balance (Operating Fund)", "FUND_BAL_OP", "Operating Fund Balance")
    if fund_balance:
        updates["dbpr_operating_fund_balance"] = fund_balance

    reserve_balance = get(match, "Fund Balance (Replacement Fund)", "FUND_BAL_REPL", "Replacement Fund Balance")
    if reserve_balance:
        updates["dbpr_reserve_fund_balance"] = reserve_balance

    fiscal_yr = get(match, "Fiscal Year End", "FISCAL_YR_END")
    if fiscal_yr:
        updates["dbpr_fiscal_year_end"] = fiscal_yr

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
