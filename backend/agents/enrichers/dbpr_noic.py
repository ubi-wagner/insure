"""
DBPR Notice of Intended Conversion (NOIC) Enricher

Reads the official DBPR Notice of Intended Conversion file (noic.csv).
NOIC filings indicate a building (apartments, hotel, office, etc.) is being
or has been converted into a condominium.

Insurance relevance:
- Newly converted condos = brand new associations needing master policies
- Conversion projects often have aging building stock = higher risk profile
- The developer is still on the hook for warranty disputes during the
  initial transition period — useful for due-diligence outreach.

Schema (per DBPR readme):
  File Number, NOIC Name, County, Street, City, State, Zip, Approval Date,
  Status, Developer Name, Developer Route, Developer Street, Developer City,
  Developer State, Developer Zip
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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NOIC_PATHS = [
    os.path.join(BASE_DIR, "filestore", "System Data", "DBPR", "noic.csv"),
    os.path.join(BASE_DIR, "data", "noic.csv"),
]

CACHE_TTL = 3600 * 6
_noic_cache: list[dict] | None = None
_cache_time: float = 0


# Reuse address parser from dbpr_bulk so matching logic stays consistent
def _import_addr_helpers():
    from agents.enrichers.dbpr_bulk import _parse_address, _county_matches
    return _parse_address, _county_matches


def _find_csv() -> str | None:
    for p in NOIC_PATHS:
        if os.path.exists(p):
            return p
    return None


def _load_noic() -> list[dict]:
    """Load all NOIC records into a flat list."""
    csv_path = _find_csv()
    if not csv_path:
        logger.info("noic.csv not found — NOIC enricher disabled")
        return []

    records: list[dict] = []
    try:
        with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize the dict — DBPR sometimes ships extra whitespace in keys
                clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                if not any(clean.values()):
                    continue
                records.append(clean)

        logger.info(f"NOIC: loaded {len(records):,} records from {csv_path}")
    except Exception as e:
        logger.error(f"Failed to load NOIC CSV: {e}")

    return records


def _get_records() -> list[dict]:
    global _noic_cache, _cache_time
    now = datetime.now(timezone.utc).timestamp()
    if _noic_cache is not None and (now - _cache_time) < CACHE_TTL:
        return _noic_cache
    _noic_cache = _load_noic()
    _cache_time = now
    return _noic_cache


def _build_address(row: dict) -> str:
    """Compose a single address string from NOIC's separate columns."""
    parts = [
        row.get("Street", ""),
        row.get("City", ""),
        row.get("State", ""),
        row.get("Zip", ""),
    ]
    return ", ".join(p for p in parts if p)


def _match_entity(entity: Entity, records: list[dict]) -> dict | None:
    """Match an entity to a NOIC record using strict address matching.

    Required: same county + same street number + ≥1 shared street name token.
    """
    if not records:
        return None

    parse_address, county_matches = _import_addr_helpers()

    if not entity.address or not entity.county:
        return None

    parsed_entity = parse_address(entity.address)
    if not parsed_entity["street_num"]:
        return None

    for row in records:
        if not county_matches(entity.county, row.get("County", "") or ""):
            continue
        addr = _build_address(row)
        if not addr:
            continue
        parsed_noic = parse_address(addr)
        if not parsed_noic["street_num"]:
            continue
        if parsed_entity["street_num"] != parsed_noic["street_num"]:
            continue
        if not (parsed_entity["street_core"] & parsed_noic["street_core"]):
            continue
        return row

    return None


@register_enricher("dbpr_noic", requires=[])
def enrich_dbpr_noic(entity: Entity, db: Session) -> bool:
    """Match entity against the NOIC list of intended condo conversions."""
    records = _get_records()
    if not records:
        return False

    match = _match_entity(entity, records)
    if not match:
        return False

    updates: dict = {
        "noic_match": True,
        "noic_file_number": match.get("File Number") or match.get("FileNumber") or "",
        "noic_name": match.get("NOIC Name") or match.get("Name") or "",
        "noic_approval_date": match.get("Approval Date") or "",
        "noic_status": match.get("Status") or "",
        "noic_developer_name": match.get("Developer Name") or "",
    }

    dev_addr_parts = [
        match.get("Developer Street", ""),
        match.get("Developer City", ""),
        match.get("Developer State", ""),
        match.get("Developer Zip", ""),
    ]
    dev_addr = ", ".join(p for p in dev_addr_parts if p)
    if dev_addr:
        updates["noic_developer_address"] = dev_addr

    # Drop empty fields so they don't clutter the modal
    updates = {k: v for k, v in updates.items() if v}

    if not updates.get("noic_match"):
        return False

    update_characteristics(entity, updates, "dbpr_noic")

    fields = list(updates.keys())
    detail = f"NOIC: {updates.get('noic_name', '?')} (file {updates.get('noic_file_number', '?')})"

    record_enrichment(
        entity, db,
        source_id="dbpr_noic",
        fields_updated=fields,
        source_url="https://www2.myfloridalicense.com/sto/file_download/extracts/noic.csv",
        detail=detail,
    )

    return True
