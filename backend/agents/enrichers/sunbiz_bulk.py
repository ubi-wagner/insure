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
# Secondary index — canonical street key (utils.address.canon_key) →
# list of matching Sunbiz records. Built lazily alongside _cache so the
# address-lookup endpoint (and the future address-fallback path inside
# enrich_sunbiz_bulk) can find "what entities are registered at this
# building" in O(1).
_address_cache: dict[str, list[dict]] | None = None
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

    # No pre-built CSV found — check for already-extracted .txt chunks
    # FIRST. Sunbiz publishes corprindata{,2..9}.txt; the chunk-1 zip
    # uses a compression method Python's zipfile can't extract, so the
    # ZIP-extract path fails on Railway. Using the chunks-2..9 .txt
    # files directly gives us ~88% of the data without needing the zip.
    raw_dirs = [
        sunbiz_dir,
        os.path.join(BASE_DIR, "data"),
        os.path.join(BASE_DIR, "data", "sunbiz_raw"),
    ]
    for d in raw_dirs:
        if not os.path.isdir(d):
            continue
        txts = sorted(
            f for f in os.listdir(d)
            if f.lower().startswith("corprindata") and f.lower().endswith(".txt")
        )
        if txts:
            csv_path = _process_chunks_to_csv([os.path.join(d, f) for f in txts])
            if csv_path:
                return csv_path

    # Last-ditch fallback: try the zip (some compression methods are supported).
    for d in raw_dirs:
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


def _process_chunks_to_csv(chunk_paths: list[str]) -> str | None:
    """Parse already-extracted Sunbiz fixed-width chunks into one CSV.

    Sunbiz publishes corprindata as a numbered series of fixed-width
    files. We just iterate through them, run parse_and_filter on each,
    accumulate matches, and write a single sunbiz_corps.csv.
    """
    if not chunk_paths:
        return None
    try:
        from scripts.download_sunbiz import parse_and_filter, write_csv

        all_matches: list[dict] = []
        for path in chunk_paths:
            try:
                logger.info(f"Parsing Sunbiz chunk: {os.path.basename(path)}")
                all_matches.extend(parse_and_filter(path))
            except Exception as e:
                logger.warning(f"Skipping Sunbiz chunk {path}: {e}")

        if not all_matches:
            logger.warning("No matching associations found across Sunbiz chunks")
            return None

        csv_path = os.path.join(BASE_DIR, "data", "sunbiz_corps.csv")
        write_csv(all_matches, csv_path)

        # Mirror to filestore for visibility.
        filestore_dir = os.path.join(BASE_DIR, "filestore", "System Data", "Sunbiz")
        os.makedirs(filestore_dir, exist_ok=True)
        write_csv(all_matches, os.path.join(filestore_dir, "sunbiz_corps.csv"))

        logger.info(
            f"Auto-processed {len(chunk_paths)} Sunbiz chunks: "
            f"{len(all_matches):,} associations -> {csv_path}"
        )
        return csv_path

    except Exception as e:
        logger.error(f"Failed to process Sunbiz chunks: {e}")
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
    global _cache, _address_cache, _cache_time
    now = datetime.now(timezone.utc).timestamp()

    if _cache is not None and (now - _cache_time) < CACHE_TTL:
        return _cache

    _cache = _load_csv()
    _address_cache = _build_address_index(_cache)
    _cache_time = now
    return _cache


def _get_address_cache() -> dict[str, list[dict]]:
    """Address-keyed Sunbiz index. Triggers full cache rebuild if cold."""
    global _address_cache
    if _address_cache is None:
        _get_cache()  # populates both
    return _address_cache or {}


def _build_address_index(by_name: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Re-index the Sunbiz records by canonical street key.

    Every record's principal_address + mailing_address are canonicalized
    via utils.address.canon_key (same algorithm the seeder / matcher
    use) so a property's street_canon matches the same string here.
    Multiple corps at the same building (typical for condo associations,
    LLCs holding individual units, etc.) all bucket under the same key.
    """
    from utils.address import canon_key

    out: dict[str, list[dict]] = {}
    seen_ids: dict[str, set[str]] = {}
    total = 0
    for records in by_name.values():
        for rec in records:
            doc_num = (rec.get("document_number") or "").strip()
            for field in ("principal_address", "mailing_address"):
                addr = (rec.get(field) or "").strip()
                if not addr:
                    continue
                key = canon_key(addr)
                if not key:
                    continue
                # De-duplicate: same record under both principal + mailing
                # at the same canon shouldn't appear twice.
                bucket_seen = seen_ids.setdefault(key, set())
                if doc_num and doc_num in bucket_seen:
                    continue
                if doc_num:
                    bucket_seen.add(doc_num)
                out.setdefault(key, []).append(rec)
                total += 1
    logger.info(
        f"Sunbiz address index built: {total:,} records under "
        f"{len(out):,} unique canonical addresses"
    )
    return out


def lookup_by_address(addr: str) -> list[dict]:
    """Find Sunbiz entities registered at the given street address.

    Returns the raw record dicts (corp_name, document_number, status,
    principal/mailing addresses, officers) sorted with active filings
    first. Empty list if no canon match. Designed for the on-demand UI
    lookup — answers "which entity name should I search Sunbiz for at
    this property?" without scraping the portal.
    """
    from utils.address import canon_key

    key = canon_key(addr)
    if not key:
        return []
    matches = list(_get_address_cache().get(key, []))
    # Active filings first, then by corp_name for stable order.
    matches.sort(key=lambda r: (
        0 if (r.get("status") or "").upper().startswith("A") else 1,
        (r.get("corp_name") or "").upper(),
    ))
    return matches


# ─── Board cross-reference ───
#
# Given a building's address, identify which of its unit owners also
# sit on the association board. The condo association (and any HOA /
# co-op) is one of the Sunbiz records registered at the building's
# address; that record carries up to six officer names + one
# registered agent. Cross-matching those names against each unit
# parcel's DOR owner name surfaces the board members — the actual
# decision-makers Jason wants to call.

_BOARD_ASSOCIATION_KEYWORDS = (
    "CONDO", "CONDOMINIUM", "COOPERATIVE", "CO-OP", "COOP",
    "HOA", "HOMEOWNER", "OWNERS ASSOCIATION", "OWNER ASSN",
    "ASSOCIATION", "ASSN", "ASSOC", "MASTER ASSOC",
)

# Words that show up inside owner-name strings but don't identify a
# person — strip before token comparison so "SMITH, JOHN A TRUSTEE"
# matches "SMITH JOHN A".
_NAME_NOISE_TOKENS = frozenset({
    "ttee", "tte", "tre", "tr", "trs", "trustee", "trustees",
    "trust", "trusts", "living", "revocable", "irrevocable",
    "et", "ux", "al", "etux", "uxor", "estate", "of",
    "jr", "sr", "ii", "iii", "iv",
    "as", "and", "for", "the", "co", "llc", "inc",
    "lp", "llp", "ltd", "tte",
})


def _is_association_name(corp_name: str | None) -> bool:
    if not corp_name:
        return False
    upper = corp_name.upper()
    return any(kw in upper for kw in _BOARD_ASSOCIATION_KEYWORDS)


def _person_name_tokens(name: str | None) -> frozenset[str]:
    """Tokenize a person's name down to comparable lowercase tokens.

    Strips punctuation, drops trustee/role noise, drops 1-char tokens
    (middle initials are too ambiguous as a sole match anchor).
    Returns a frozenset so it can be cached / compared cheaply.
    """
    if not name:
        return frozenset()
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", name).lower()
    return frozenset(
        t for t in cleaned.split()
        if t and len(t) > 1 and t not in _NAME_NOISE_TOKENS
    )


def _names_match(owner_tokens: frozenset[str], principal_tokens: frozenset[str]) -> bool:
    """True when owner and principal plausibly refer to the same person.

    Require at least TWO shared non-noise tokens — typically the last
    name + first name. One-token matches (e.g. just "smith") are
    rejected because they generate too many false positives at large
    condos. Trusts/LLCs don't share last+first with a person, so they
    naturally fall out.
    """
    if not owner_tokens or not principal_tokens:
        return False
    return len(owner_tokens & principal_tokens) >= 2


def extract_principals(rec: dict) -> list[dict]:
    """Return every named person on a Sunbiz record — registered agent
    + up to six officers — with role and title context for downstream
    matching."""
    out: list[dict] = []
    ra = (rec.get("registered_agent") or "").strip()
    if ra:
        out.append({
            "name": ra,
            "role": "registered_agent",
            "title": "Registered Agent",
            "corp_name": rec.get("corp_name"),
            "document_number": rec.get("document_number"),
        })
    for i in range(1, 7):
        name = (rec.get(f"officer_{i}_name") or "").strip()
        if not name:
            continue
        title = (
            (rec.get(f"officer_{i}_title_label") or "").strip()
            or (rec.get(f"officer_{i}_title") or "").strip()
            or "Officer"
        )
        out.append({
            "name": name,
            "role": "officer",
            "title": title,
            "corp_name": rec.get("corp_name"),
            "document_number": rec.get("document_number"),
        })
    return out


def board_members_at_address(addr: str, associations_only: bool = True) -> list[dict]:
    """Every officer/agent of every Sunbiz entity at this address.

    When ``associations_only=True`` (default), filters to records whose
    corp_name contains CONDO / HOA / ASSOCIATION / etc. — i.e. the
    actual association board, not the holding LLCs of individual units.
    Set False to also surface principals of unit-owning LLCs.
    """
    records = lookup_by_address(addr)
    if associations_only:
        records = [r for r in records if _is_association_name(r.get("corp_name"))]
    out: list[dict] = []
    for rec in records:
        out.extend(extract_principals(rec))
    return out


def match_owner_to_board(
    owner_name: str | None,
    board: list[dict],
) -> dict | None:
    """If ``owner_name`` matches any board member's name, return that
    board record with the match score; otherwise None. First strong
    match wins (board is small — at most ~7 names per association)."""
    if not owner_name or not board:
        return None
    owner_tokens = _person_name_tokens(owner_name)
    if not owner_tokens:
        return None
    for member in board:
        if _names_match(owner_tokens, _person_name_tokens(member.get("name"))):
            return member
    return None


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


def build_search_url(corp_name: str) -> str:
    """Construct the live Sunbiz ByName SearchResults URL for a corp.

    Real format (observed in the portal's address bar — not the
    legacy ?inquirytype query string):

        https://search.sunbiz.org/Inquiry/CorporationSearch/
            SearchResults/EntityName/<lowercase-original-as-path>/Page1
            ?searchNameOrder=<UPPERCASE-ALNUM-ONLY>

    The path segment is the user's original casing+spacing URL-encoded
    (so spaces become %20); the searchNameOrder query is the
    alphabetical sort key — Sunbiz's index removes spaces and
    non-alphanumerics and uppercases everything. Example:

        "Echo Brickell Assoc"
            → /SearchResults/EntityName/echo%20brickell%20assoc/Page1
              ?searchNameOrder=ECHOBRICKELLASSOC
    """
    from urllib.parse import quote
    name_path = quote(corp_name.lower(), safe="")
    name_order = re.sub(r"[^A-Z0-9]", "", corp_name.upper())
    return (
        "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults"
        f"/EntityName/{name_path}/Page1?searchNameOrder={name_order}"
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
