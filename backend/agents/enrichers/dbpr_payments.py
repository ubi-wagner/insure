"""
DBPR Payment History Enricher

Cross-references leads against DBPR payment history CSVs to identify:
- Delinquent associations (pending amount due > 0)
- Payment trends (billed vs paid over multiple years)
- Financial stress indicators

Payment history files: paymenthist_8002{A,D,J,P,S}.csv
Split alphabetically by project name.

Fields: Program Area, Project County Code, Project Number, Project Name,
Project Street, Address Line2, City, State, Zip, Billing Year,
Amount Billed, Amount Paid, Pending Amount Due
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

PAYMENT_FILES = [
    "paymenthist_8002A.csv",
    "paymenthist_8002D.csv",
    "paymenthist_8002J.csv",
    "paymenthist_8002P.csv",
    "paymenthist_8002S.csv",
]

# In-memory cache
_payment_cache: dict[str, list[dict]] | None = None
_payment_cache_time: float = 0
CACHE_TTL = 3600 * 6


def _load_all_payments() -> dict[str, list[dict]]:
    """Load all payment history CSVs, indexed by project number."""
    by_project: dict[str, list[dict]] = {}
    base = os.path.dirname(__file__)
    search_dirs = [
        os.path.join(base, "..", "..", "data"),
        os.path.join(base, "..", "..", "filestore", "System Data", "DBPR"),
        os.path.join(base, "..", "..", ".."),
    ]

    for filename in PAYMENT_FILES:
        filepath = None
        for d in search_dirs:
            candidate = os.path.abspath(os.path.join(d, filename))
            if os.path.exists(candidate):
                filepath = candidate
                break
        if not filepath:
            continue

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pnum = (row.get("Project Number") or "").strip()
                    if pnum:
                        if pnum not in by_project:
                            by_project[pnum] = []
                        by_project[pnum].append(row)
        except Exception as e:
            logger.warning(f"Failed to load payment history {filename}: {e}")

    logger.info(f"Payment history: loaded {sum(len(v) for v in by_project.values())} records for {len(by_project)} projects")
    return by_project


def _get_payments() -> dict[str, list[dict]]:
    global _payment_cache, _payment_cache_time
    now = datetime.now(timezone.utc).timestamp()
    if _payment_cache is not None and (now - _payment_cache_time) < CACHE_TTL:
        return _payment_cache
    _payment_cache = _load_all_payments()
    _payment_cache_time = now
    return _payment_cache


@register_enricher("NEW", "dbpr_payments")
def enrich_payment_history(entity: Entity, db: Session) -> bool:
    """Cross-reference payment history to find delinquency and financial stress."""
    chars = entity.characteristics or {}

    # Need a DBPR project number to look up — get from dbpr_bulk enrichment
    project_num = chars.get("dbpr_project_number")
    if not project_num:
        return False

    payments = _get_payments()
    records = payments.get(str(project_num), [])
    if not records:
        return False

    # Analyze payment history
    total_billed = 0
    total_paid = 0
    total_pending = 0
    latest_year = 0
    years_delinquent = 0

    for rec in records:
        try:
            yr = int(rec.get("Billing Year", "0") or "0")
            billed = float(rec.get("Amount Billed", "0") or "0")
            paid = float(rec.get("Amount Paid", "0") or "0")
            pending = float(rec.get("Pending Amount Due", "0") or "0")

            total_billed += billed
            total_paid += paid
            total_pending += pending

            if yr > latest_year:
                latest_year = yr
            if pending > 0:
                years_delinquent += 1
        except (ValueError, TypeError):
            continue

    updates: dict = {
        "payment_total_billed": total_billed,
        "payment_total_paid": total_paid,
        "payment_total_pending": total_pending,
        "payment_years_tracked": len(records),
        "payment_latest_year": latest_year if latest_year > 0 else None,
        "payment_years_delinquent": years_delinquent,
        "payment_is_delinquent": total_pending > 0,
    }

    update_characteristics(entity, updates, "dbpr_payments")

    fields = [k for k, v in updates.items() if v is not None]
    detail = f"Payments: {len(records)} years tracked"
    if total_pending > 0:
        detail += f", DELINQUENT (${total_pending:,.0f} pending)"
    else:
        detail += f", current (${total_paid:,.0f} paid)"

    record_enrichment(
        entity, db,
        source_id="dbpr_payments",
        fields_updated=fields,
        source_url="https://www2.myfloridalicense.com/condos-timeshares-mobile-homes/public-records/",
        detail=detail,
    )

    return True
