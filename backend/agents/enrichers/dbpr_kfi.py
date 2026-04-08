"""
DBPR Key Financial Indicators (KFI) Enricher

Reads the official DBPR Key Financial Indicators report (keyfinancialindicators.csv)
and matches it against entities by managing entity name + project number.

This is the SINGLE most useful financial signal for cream scoring:
  - Negative or thin operating fund balance = financially distressed
  - Bad debt growing = collections issues
  - Replacement (reserve) fund underfunded = imminent special assessment risk
  - Operating expenses > revenue = burning down cash

Associations under financial pressure are exactly the ones actively shopping
for cheaper insurance — they MUST cut premiums to survive.

Source file: keyfinancialindicators.csv
Schema (per DBPR online layout):
  Managing Entity Name, Fiscal Year End,
  Total Revenue (Operating Fund), Total Expenses (Operating Fund),
  Total Revenue (Replacement Fund), Total Expenses (Replacement Fund),
  Bad Debt (Operating Fund),
  Fund Balance (Operating Fund), Fund Balance (Replacement Fund)

Requires: dbpr_bulk (needs dbpr_managing_entity from bulk match first).
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

# Search paths for the KFI CSV
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KFI_PATHS = [
    os.path.join(BASE_DIR, "filestore", "System Data", "DBPR", "keyfinancialindicators.csv"),
    os.path.join(BASE_DIR, "data", "keyfinancialindicators.csv"),
]

# Cache TTL — reload every 6 hours
CACHE_TTL = 3600 * 6

# In-memory caches keyed by normalized managing entity name AND by project number
_kfi_by_mgr: dict[str, dict] | None = None
_kfi_by_project: dict[str, dict] | None = None
_cache_time: float = 0


# ─── Normalization ───────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """Normalize an entity name for matching."""
    s = name.upper()
    for noise in [
        "INC", "INC.", "LLC", "CORP", "CORP.", "LTD",
        "ASSOCIATION", "ASSN", "ASSOC",
        "OF FLORIDA", "OF FL",
        "A CONDOMINIUM", "A CONDO", "CONDOMINIUM", "CONDO",
        "NOT FOR PROFIT", "NOT-FOR-PROFIT", "NON-PROFIT", "NONPROFIT",
    ]:
        s = s.replace(noise, "")
    s = re.sub(r"[^A-Z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _safe_money(val) -> float | None:
    """Parse a money string from the KFI CSV — handles $, commas, parens for negatives."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.upper() in ("N/A", "NA", "NULL", "-"):
        return None
    # Parens indicate negative
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()$").replace(",", "").strip()
    try:
        n = float(s)
        return -n if negative else n
    except ValueError:
        return None


# ─── Header detection ────────────────────────────────────────────────

# Flexible header matching — different DBPR file revisions may use slightly
# different column names
COLUMN_PATTERNS = {
    "managing_entity":  ["managing entity name", "management entity", "managing entity"],
    "project_number":   ["project number", "project no", "project #"],
    "fiscal_year_end":  ["fiscal year end", "fye", "year end"],
    "operating_revenue":  ["total revenue, operating", "operating fund revenue", "operating revenue", "total revenue operating"],
    "operating_expenses": ["total expenses, operating", "operating fund expenses", "operating expenses", "total expenses operating"],
    "replacement_revenue":  ["total revenue, replacement", "replacement fund revenue", "reserve revenue", "total revenue replacement"],
    "replacement_expenses": ["total expenses, replacement", "replacement fund expenses", "reserve expenses", "total expenses replacement"],
    "bad_debt": ["bad debt"],
    "operating_fund_balance":  ["fund balance, operating", "operating fund balance", "operating balance"],
    "replacement_fund_balance": ["fund balance, replacement", "replacement fund balance", "reserve fund balance", "replacement balance"],
}


def _find_column(headers: list[str], patterns: list[str]) -> int | None:
    """Find the index of the first column header matching any pattern."""
    lowered = [h.strip().lower() if h else "" for h in headers]
    for i, h in enumerate(lowered):
        for pat in patterns:
            if pat in h:
                return i
    return None


# ─── CSV Loading ─────────────────────────────────────────────────────

def _find_csv() -> str | None:
    for p in KFI_PATHS:
        if os.path.exists(p):
            return p
    return None


def _load_kfi() -> tuple[dict[str, dict], dict[str, dict]]:
    """Load KFI CSV and return two indices: by managing entity name, by project number."""
    by_mgr: dict[str, dict] = {}
    by_project: dict[str, dict] = {}

    csv_path = _find_csv()
    if not csv_path:
        logger.info("keyfinancialindicators.csv not found — KFI enricher disabled")
        return by_mgr, by_project

    try:
        with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            if not headers:
                logger.warning("KFI CSV has no headers")
                return by_mgr, by_project

            # Map known columns
            cols = {key: _find_column(headers, patterns) for key, patterns in COLUMN_PATTERNS.items()}
            logger.info(f"KFI columns detected: {cols}")

            count = 0
            for row in reader:
                if not row or not any(c for c in row):
                    continue

                def get(key: str) -> str:
                    idx = cols.get(key)
                    if idx is None or idx >= len(row):
                        return ""
                    return (row[idx] or "").strip()

                mgr_name = get("managing_entity")
                project = get("project_number")
                if not mgr_name and not project:
                    continue

                record = {
                    "managing_entity": mgr_name,
                    "project_number": project,
                    "fiscal_year_end": get("fiscal_year_end"),
                    "operating_revenue": _safe_money(get("operating_revenue")),
                    "operating_expenses": _safe_money(get("operating_expenses")),
                    "replacement_revenue": _safe_money(get("replacement_revenue")),
                    "replacement_expenses": _safe_money(get("replacement_expenses")),
                    "bad_debt": _safe_money(get("bad_debt")),
                    "operating_fund_balance": _safe_money(get("operating_fund_balance")),
                    "replacement_fund_balance": _safe_money(get("replacement_fund_balance")),
                }

                if mgr_name:
                    norm = _normalize_name(mgr_name)
                    if norm and norm not in by_mgr:
                        by_mgr[norm] = record
                if project:
                    proj = re.sub(r"[^A-Z0-9]", "", project.upper())
                    if proj and proj not in by_project:
                        by_project[proj] = record
                count += 1

            logger.info(
                f"KFI: loaded {count:,} records "
                f"({len(by_mgr):,} indexed by managing entity, "
                f"{len(by_project):,} by project number)"
            )

    except Exception as e:
        logger.error(f"Failed to load KFI CSV: {e}")

    return by_mgr, by_project


def _get_indices() -> tuple[dict[str, dict], dict[str, dict]]:
    global _kfi_by_mgr, _kfi_by_project, _cache_time
    now = datetime.now(timezone.utc).timestamp()
    if (
        _kfi_by_mgr is not None
        and _kfi_by_project is not None
        and (now - _cache_time) < CACHE_TTL
    ):
        return _kfi_by_mgr, _kfi_by_project
    _kfi_by_mgr, _kfi_by_project = _load_kfi()
    _cache_time = now
    return _kfi_by_mgr, _kfi_by_project


def _lookup_kfi(managing_entity: str, project_number: str) -> dict | None:
    """Look up a KFI record by managing entity name first, then project number."""
    by_mgr, by_project = _get_indices()

    if project_number:
        proj = re.sub(r"[^A-Z0-9]", "", project_number.upper())
        if proj in by_project:
            return by_project[proj]

    if managing_entity:
        norm = _normalize_name(managing_entity)
        if norm in by_mgr:
            return by_mgr[norm]

    return None


# ─── Enricher ───────────────────────────────────────────────────────

@register_enricher("dbpr_kfi", requires=["dbpr_bulk"])
def enrich_dbpr_kfi(entity: Entity, db: Session) -> bool:
    """Enrich entity with Key Financial Indicators data."""
    chars = dict(entity.characteristics or {})

    managing_entity = str(chars.get("dbpr_managing_entity") or "")
    project_number = str(chars.get("dbpr_project_number") or "")

    if not managing_entity and not project_number:
        return False

    record = _lookup_kfi(managing_entity, project_number)
    if not record:
        return False

    updates: dict = {}

    # Direct financial fields
    if record["fiscal_year_end"]:
        updates["dbpr_fiscal_year_end"] = record["fiscal_year_end"]
    if record["operating_revenue"] is not None:
        updates["dbpr_operating_revenue"] = record["operating_revenue"]
    if record["operating_expenses"] is not None:
        updates["dbpr_operating_expenses"] = record["operating_expenses"]
    if record["replacement_revenue"] is not None:
        updates["dbpr_reserve_revenue"] = record["replacement_revenue"]
    if record["replacement_expenses"] is not None:
        updates["dbpr_reserve_expenses"] = record["replacement_expenses"]
    if record["bad_debt"] is not None:
        updates["dbpr_bad_debt"] = record["bad_debt"]
    if record["operating_fund_balance"] is not None:
        updates["dbpr_operating_fund_balance"] = record["operating_fund_balance"]
    if record["replacement_fund_balance"] is not None:
        updates["dbpr_reserve_fund_balance"] = record["replacement_fund_balance"]

    # ── Derived financial-distress signals ──
    op_rev = record["operating_revenue"] or 0
    op_exp = record["operating_expenses"] or 0
    op_bal = record["operating_fund_balance"]
    res_bal = record["replacement_fund_balance"]
    bad_debt = record["bad_debt"] or 0

    # Operating cash burn (expenses > revenue)
    if op_rev > 0:
        op_margin = (op_rev - op_exp) / op_rev
        updates["dbpr_operating_margin"] = round(op_margin, 3)
        if op_margin < -0.05:
            updates["dbpr_financial_distress"] = "burning_cash"
        elif op_margin < 0:
            updates["dbpr_financial_distress"] = "thin_margin"

    # Negative or empty operating fund balance = critical distress
    if op_bal is not None and op_bal <= 0:
        updates["dbpr_financial_distress"] = "negative_operating_fund"

    # Bad debt as % of operating revenue
    if op_rev > 0 and bad_debt > 0:
        bad_debt_ratio = bad_debt / op_rev
        updates["dbpr_bad_debt_ratio"] = round(bad_debt_ratio, 3)
        if bad_debt_ratio > 0.05:
            updates["dbpr_collections_issue"] = True

    # Replacement (reserve) fund underfunded for the building's needs.
    # Rough heuristic: a healthy reserve runs 10-30% of annual operating revenue.
    # Below 10% suggests underfunding.
    if res_bal is not None and op_rev > 0:
        reserve_ratio = res_bal / op_rev if op_rev else 0
        updates["dbpr_reserve_ratio"] = round(reserve_ratio, 3)
        if reserve_ratio < 0.05:
            updates["dbpr_reserve_underfunded"] = True

    if not updates:
        return False

    update_characteristics(entity, updates, "dbpr_kfi")

    fields = [k for k, v in updates.items() if v is not None]
    detail_parts = [f"KFI: {len(fields)} fields"]
    if updates.get("dbpr_financial_distress"):
        detail_parts.append(f"DISTRESS={updates['dbpr_financial_distress']}")
    if op_bal is not None:
        detail_parts.append(f"op_fund=${op_bal:,.0f}")

    record_enrichment(
        entity, db,
        source_id="dbpr_kfi",
        fields_updated=fields,
        source_url="https://www2.myfloridalicense.com/condos-timeshares-mobile-homes/public-records/",
        detail=", ".join(detail_parts),
    )

    return True
