"""
Sunbiz Bulk Data Enricher

Matches LEAD-stage entities against the downloaded Sunbiz quarterly bulk
corporate data (sunbiz_corps.csv) to populate association details, officers,
and registered agent information.

This replaces/supplements the sunbiz web scraper which gets 403'd from cloud
servers. The bulk data is downloaded via scripts/download_sunbiz.py.

Match strategy (in order of priority):
  1. Entity name -> corp name (fuzzy normalized match)
  2. DBPR condo name -> corp name (if DBPR enricher ran first)
  3. Owner name -> corp name (for association-owned properties)
"""

import csv
import logging
import os
import re
import zipfile
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Contact, Entity

logger = logging.getLogger(__name__)

# ─── Configuration ───

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_PATHS = [
    os.path.join(BASE_DIR, "data", "sunbiz_corps.csv"),
    os.path.join(BASE_DIR, "filestore", "System Data", "Sunbiz", "sunbiz_corps.csv"),
]

# Cache TTL — reload CSV every 6 hours
CACHE_TTL = 3600 * 6

# In-memory cache
_cache: dict[str, list[dict]] | None = None
_cache_time: float = 0


# ─── Normalization ───

def _normalize(name: str) -> str:
    """Normalize a name for matching: lowercase, strip punctuation, collapse whitespace."""
    s = name.upper()
    # Remove common suffixes that vary between data sources
    for noise in [
        "INC", "INC.", "LLC", "CORP", "CORP.", "LTD", "LTD.",
        "OF FLORIDA", "OF FL", "A FLORIDA", "A FL",
        "A CONDOMINIUM", "A CONDO",
        "NOT FOR PROFIT", "NOT-FOR-PROFIT", "NON-PROFIT", "NONPROFIT",
    ]:
        s = s.replace(noise, "")
    # Strip punctuation, collapse whitespace
    s = re.sub(r"[^A-Z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _name_tokens(name: str) -> set[str]:
    """Extract significant tokens from a normalized name (drop very short words)."""
    return {w for w in _normalize(name).split() if len(w) > 2}


# ─── CSV Loading ───

def _find_csv() -> str | None:
    """Find the sunbiz_corps.csv file.

    Search order:
      1. Pre-built sunbiz_corps.csv in data/ or filestore/
      2. Any sunbiz_corps*.csv in the Sunbiz filestore directory
      3. Raw zip files (corpindata.zip, etc.) — auto-parse into CSV
    """
    # Check primary locations
    for path in CSV_PATHS:
        if os.path.exists(path):
            return path

    sunbiz_dir = os.path.join(BASE_DIR, "filestore", "System Data", "Sunbiz")

    # Check for any sunbiz_corps*.csv in the Sunbiz filestore directory
    if os.path.isdir(sunbiz_dir):
        csvs = sorted(
            [f for f in os.listdir(sunbiz_dir) if f.startswith("sunbiz_corps") and f.endswith(".csv")],
            reverse=True,  # newest first
        )
        if csvs:
            return os.path.join(sunbiz_dir, csvs[0])

    # No pre-built CSV found — check for raw zip files and auto-process
    zip_dirs = [
        sunbiz_dir,
        os.path.join(BASE_DIR, "data"),
        os.path.join(BASE_DIR, "data", "sunbiz_raw"),
    ]
    for d in zip_dirs:
        if not os.path.isdir(d):
            continue
        zips = [f for f in os.listdir(d)
                if f.lower().endswith(".zip") and ("corp" in f.lower() or "sunbiz" in f.lower())]
        if zips:
            zip_path = os.path.join(d, sorted(zips, reverse=True)[0])
            logger.info(f"Found raw Sunbiz zip: {zip_path} — auto-processing...")
            csv_path = _process_zip_to_csv(zip_path)
            if csv_path:
                return csv_path

    return None


def _process_zip_to_csv(zip_path: str) -> str | None:
    """Extract a Sunbiz corpindata zip, parse fixed-width records, produce sunbiz_corps.csv."""
    try:
        from scripts.download_sunbiz import parse_and_filter, write_csv

        # Extract the largest file from the zip
        with zipfile.ZipFile(zip_path, "r") as zf:
            data_files = [n for n in zf.namelist()
                          if not n.startswith("__") and not n.startswith(".")]
            if not data_files:
                logger.warning(f"Zip {zip_path} contains no data files")
                return None
            largest = max(data_files, key=lambda n: zf.getinfo(n).file_size)
            extract_dir = os.path.join(BASE_DIR, "data", "sunbiz_raw")
            os.makedirs(extract_dir, exist_ok=True)
            extract_path = os.path.join(extract_dir, largest)
            if not os.path.exists(extract_path):
                zf.extract(largest, extract_dir)
                logger.info(f"Extracted {largest} ({zf.getinfo(largest).file_size:,} bytes)")

        # Parse fixed-width records and filter for associations
        matches = parse_and_filter(extract_path)
        if not matches:
            logger.warning("No matching associations found in Sunbiz data")
            return None

        # Write CSV to standard location
        csv_path = os.path.join(BASE_DIR, "data", "sunbiz_corps.csv")
        write_csv(matches, csv_path)

        # Also copy to filestore for visibility
        filestore_dir = os.path.join(BASE_DIR, "filestore", "System Data", "Sunbiz")
        os.makedirs(filestore_dir, exist_ok=True)
        filestore_csv = os.path.join(filestore_dir, "sunbiz_corps.csv")
        write_csv(matches, filestore_csv)

        logger.info(f"Auto-processed Sunbiz zip: {len(matches):,} associations -> {csv_path}")
        return csv_path

    except Exception as e:
        logger.error(f"Failed to auto-process Sunbiz zip {zip_path}: {e}")
        return None


def _load_csv() -> dict[str, list[dict]]:
    """Load sunbiz_corps.csv into a dict keyed by normalized corp name.

    Returns dict mapping normalized name -> list of matching records.
    Multiple records can share the same normalized name (e.g. active + inactive filings).
    """
    csv_path = _find_csv()
    if not csv_path:
        logger.warning("sunbiz_corps.csv not found. Run 'python -m scripts.download_sunbiz' first.")
        return {}

    index: dict[str, list[dict]] = {}
    count = 0

    try:
        with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                corp_name = (row.get("corp_name") or "").strip()
                if not corp_name:
                    continue

                key = _normalize(corp_name)
                if key not in index:
                    index[key] = []
                index[key].append(row)
                count += 1

        logger.info(f"Sunbiz bulk: loaded {count:,} records ({len(index):,} unique names) from {csv_path}")
    except Exception as e:
        logger.error(f"Failed to load sunbiz_corps.csv: {e}")

    return index


def _get_cache() -> dict[str, list[dict]]:
    """Get the cached Sunbiz data, reloading if stale."""
    global _cache, _cache_time
    now = datetime.now(timezone.utc).timestamp()

    if _cache is not None and (now - _cache_time) < CACHE_TTL:
        return _cache

    _cache = _load_csv()
    _cache_time = now
    return _cache


# ─── Matching ───

def _match_name(search_name: str, index: dict[str, list[dict]]) -> dict | None:
    """Try to find a matching Sunbiz record for a given name.

    Strategy:
      1. Exact normalized match
      2. Containment match (one name contains the other)
      3. Token overlap match (>= 60% word overlap, minimum 3 shared words)

    Prefers active records over inactive ones.
    """
    if not search_name:
        return None

    normalized = _normalize(search_name)
    if not normalized:
        return None

    # 1. Exact match
    if normalized in index:
        return _pick_best(index[normalized])

    # 2. Containment match — check both directions
    candidates = []
    for key, records in index.items():
        if normalized in key or key in normalized:
            candidates.extend(records)

    if candidates:
        return _pick_best(candidates)

    # 3. Token overlap — only for names with enough tokens
    search_tokens = _name_tokens(search_name)
    if len(search_tokens) < 2:
        return None

    best_record = None
    best_score = 0

    for key, records in index.items():
        corp_tokens = {w for w in key.split() if len(w) > 2}
        if not corp_tokens:
            continue

        overlap = len(search_tokens & corp_tokens)
        total = max(len(search_tokens), len(corp_tokens))

        if overlap < 3:
            continue

        score = overlap / total
        if score > best_score and score >= 0.60:
            best_score = score
            best_record = _pick_best(records)

    return best_record


def _pick_best(records: list[dict]) -> dict | None:
    """From multiple matching records, pick the best one (prefer active, most recent)."""
    if not records:
        return None
    if len(records) == 1:
        return records[0]

    # Prefer active status
    # Active records: status code "A" (per Corporate File spec) or "AA" (legacy)
    active = [r for r in records if (r.get("status_code") or "").strip() in ("A", "AA")]
    pool = active if active else records

    # Among remaining, prefer most recent filing date
    def sort_key(r):
        fd = (r.get("filing_date") or "").strip()
        if len(fd) == 4 and fd.isdigit():
            # MMYY -> sortable YYMM
            return fd[2:] + fd[:2]
        return "0000"

    pool.sort(key=sort_key, reverse=True)
    return pool[0]


def _build_detail_url(doc_number: str) -> str:
    """Construct a Sunbiz detail URL from a document number."""
    return (
        f"https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResultDetail"
        f"?inquirytype=EntityName&directionType=Initial&searchNameOrder={doc_number}"
    )


# ─── Enricher ───

@register_enricher("sunbiz_bulk", requires=[])
def enrich_sunbiz_bulk(entity: Entity, db: Session) -> bool:
    """Match entity against Sunbiz bulk corporate data (quarterly extract)."""
    # Load cached data
    index = _get_cache()
    if not index:
        return False

    # Try multiple name sources in priority order
    chars = entity.characteristics or {}
    match = None
    match_source = None

    # 1. DBPR condo name (most reliable if DBPR ran first)
    dbpr_name = chars.get("dbpr_condo_name")
    if dbpr_name:
        match = _match_name(dbpr_name, index)
        if match:
            match_source = f"dbpr_condo_name: {dbpr_name}"

    # 2. Entity name
    if not match and entity.name:
        match = _match_name(entity.name, index)
        if match:
            match_source = f"entity_name: {entity.name}"

    # 3. DOR owner name (for association-owned properties)
    if not match:
        owner = chars.get("dor_owner", "")
        if owner and len(owner) > 5:
            match = _match_name(owner, index)
            if match:
                match_source = f"dor_owner: {owner}"

    if not match:
        return False

    # Extract matched data
    corp_name = (match.get("corp_name") or "").strip()
    doc_number = (match.get("document_number") or "").strip()
    status = (match.get("status") or match.get("status_code") or "").strip()
    filing_date = (match.get("filing_date_formatted") or match.get("filing_date") or "").strip()
    principal_addr = (match.get("principal_address") or "").strip()
    reg_agent = (match.get("registered_agent") or "").strip()
    detail_url = _build_detail_url(doc_number) if doc_number else None

    updates: dict = {}

    if corp_name:
        updates["sunbiz_corp_name"] = corp_name
    if doc_number:
        updates["sunbiz_doc_number"] = doc_number
    if status:
        updates["sunbiz_status"] = status
    if filing_date:
        updates["sunbiz_filing_date"] = filing_date
    if principal_addr:
        updates["sunbiz_principal_address"] = principal_addr
    if reg_agent:
        updates["sunbiz_registered_agent"] = reg_agent
        updates["property_manager"] = reg_agent
    if detail_url:
        updates["sunbiz_detail_url"] = detail_url

    # Create contacts from officers
    contacts_added = []
    for i in range(1, 7):
        officer_name = (match.get(f"officer_{i}_name") or "").strip()
        officer_title = (match.get(f"officer_{i}_title") or "").strip()

        if not officer_name:
            continue

        # Normalize title case
        officer_name = officer_name.title()

        # Check for existing contact to avoid duplicates
        existing = db.query(Contact).filter(
            Contact.entity_id == entity.id,
            Contact.name == officer_name,
        ).first()

        if not existing:
            is_president = "pres" in officer_title.lower() or "P" == officer_title.strip()
            contact = Contact(
                entity_id=entity.id,
                name=officer_name,
                title=officer_title,
                is_primary=1 if is_president else 0,
                source="sunbiz_bulk",
                source_url=detail_url,
            )
            db.add(contact)
            contacts_added.append(f"{officer_name} ({officer_title})")

            # First president-type officer becomes decision_maker
            if is_president and "decision_maker" not in updates:
                updates["decision_maker"] = officer_name
                updates["decision_maker_title"] = officer_title

    if contacts_added:
        db.flush()

    if not updates:
        return False

    update_characteristics(entity, updates, "sunbiz_bulk")

    fields = [k for k, v in updates.items() if v is not None]
    detail_parts = [f"Sunbiz bulk: {len(fields)} fields"]
    if corp_name:
        detail_parts.append(corp_name)
    if match_source:
        detail_parts.append(f"matched via {match_source}")
    if contacts_added:
        detail_parts.append(f"{len(contacts_added)} contacts")

    record_enrichment(
        entity, db,
        source_id="sunbiz_bulk",
        fields_updated=fields + [f"contact:{n}" for n in contacts_added],
        source_url=detail_url or "https://dos.fl.gov/sunbiz/other-services/data-downloads/",
        detail=", ".join(detail_parts),
    )

    logger.info(f"Sunbiz bulk matched entity {entity.id} '{entity.name}' -> {corp_name} ({doc_number})")
    return True
