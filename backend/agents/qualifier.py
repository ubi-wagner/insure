"""
Qualifier — TARGET → LEAD transition.

The seeder ingests every non-residential parcel as TARGET (skipping
only DOR_UC 001 single-family and 002 mobile homes). The qualifier
applies an admin-configurable allowlist of DOR use codes and promotes
matching TARGETs to LEAD in bulk. No external network calls, no AI,
no enrichment — pure deterministic SQL.

Defaults (overridable via /api/admin/qualifier/config):
  003 Multi-Family (small)
  004 Condominium
  005 Cooperatives
  006 Retirement Homes
  007 Misc Residential
  008 Multi-Family (10+)
  009 Residential Common
  011-024 Commercial (stores, mixed use, malls, restaurants, financial)
  039 Hotels/Motels
  048 Warehouses

The allowlist is persisted to the System Data folder so it survives
restarts and is readable by the admin UI for editing.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import Entity, LeadLedger
from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)


CONFIG_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "filestore",
    "System Data",
    "qualifier_config.json",
)


DEFAULT_USE_CODES: list[str] = [
    # Residential rentals / multi-unit
    "003",  # Multi-Family (small)
    "004",  # Condominium
    "005",  # Cooperatives
    "006",  # Retirement Homes
    "007",  # Misc Residential
    "008",  # Multi-Family (10+)
    "009",  # Residential Common (condo common elements)
    # Commercial — anything that needs commercial property insurance
    "011", "012", "013", "014", "015", "016", "017",
    "018", "019", "020", "021", "022", "023", "024",
    # Special-purpose income properties
    "038",  # Golf courses (clubhouses)
    "039",  # Hotels / Motels
    "048",  # Warehousing
    "049",  # Open storage
    # Mixed use / institutional with commercial property exposure
    "070", "071", "072", "073", "074",
]


# ─────────────────────────────────────────────────────────────────────────────
# Config persistence
# ─────────────────────────────────────────────────────────────────────────────


def _normalize_codes(codes: Iterable[str]) -> list[str]:
    """Zero-pad to 3 digits and dedupe, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for code in codes:
        if code is None:
            continue
        c = str(code).strip()
        if not c:
            continue
        try:
            c = str(int(float(c))).zfill(3)
        except (ValueError, TypeError):
            c = c.zfill(3)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def get_qualifier_config() -> dict:
    """Read the persisted allowlist, or seed defaults on first call."""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
            cfg["use_codes"] = _normalize_codes(cfg.get("use_codes", []))
            return cfg
    except Exception as e:
        logger.warning(f"Failed to read qualifier config: {e}")

    # Seed defaults on first read
    cfg = {
        "use_codes": _normalize_codes(DEFAULT_USE_CODES),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": "system",
    }
    save_qualifier_config(cfg["use_codes"], updated_by="system")
    return cfg


def save_qualifier_config(use_codes: Iterable[str], updated_by: str = "admin") -> dict:
    cfg = {
        "use_codes": _normalize_codes(use_codes),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": updated_by,
    }
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save qualifier config: {e}")
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────


def run_qualifier(db: Session, county: str | None = None) -> dict:
    """Promote every TARGET whose dor_use_code is in the allowlist to LEAD.

    Bulk SQL, no per-row Python overhead. Matched-row count comes back
    from the UPDATE result. Optional ``county`` filter scopes the run to
    one county at a time when the user re-runs after editing the
    allowlist for a specific market.
    """
    cfg = get_qualifier_config()
    allowlist = cfg["use_codes"]
    if not allowlist:
        return {
            "promoted": 0,
            "use_codes": [],
            "error": "Qualifier allowlist is empty — nothing to promote.",
        }

    started = datetime.now(timezone.utc)
    emit(EventType.HUNTER, "qualifier_start", EventStatus.PENDING,
         detail=f"Promoting TARGET → LEAD for codes {sorted(allowlist)}"
                + (f" in {county}" if county else ""))

    # Pull the candidate set so we can write a ledger row per promotion.
    # Bulk UPDATE would be faster but we want the audit trail.
    q = (
        db.query(Entity)
        .filter(Entity.pipeline_stage == "TARGET")
    )
    if county:
        q = q.filter(Entity.county == county)

    candidates = q.all()
    promoted = 0
    skipped_use_code: dict[str, int] = {}

    for entity in candidates:
        chars = entity.characteristics or {}
        code = str(chars.get("dor_use_code") or "").zfill(3)
        if code not in allowlist:
            skipped_use_code[code] = skipped_use_code.get(code, 0) + 1
            continue

        entity.pipeline_stage = "LEAD"
        ledger = LeadLedger(
            entity_id=entity.id,
            action_type="STAGE_CHANGE",
            detail=f"TARGET → LEAD via qualifier (use_code={code})",
            source="qualifier",
        )
        db.add(ledger)
        promoted += 1

        # Periodic commit to keep transactions sane on big runs.
        if promoted % 1000 == 0:
            db.commit()

    db.commit()

    finished = datetime.now(timezone.utc)
    duration = (finished - started).total_seconds()

    result = {
        "promoted": promoted,
        "scanned": len(candidates),
        "use_codes": sorted(allowlist),
        "skipped_by_use_code": dict(sorted(
            skipped_use_code.items(), key=lambda kv: -kv[1]
        )[:20]),
        "county_filter": county,
        "duration_sec": round(duration, 1),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
    }

    emit(EventType.HUNTER, "qualifier_done", EventStatus.SUCCESS,
         detail=(
             f"Qualifier: {promoted:,} promoted from {len(candidates):,} "
             f"TARGETs in {duration:.1f}s"
             + (f" ({county})" if county else "")
         ))
    logger.info(f"Qualifier: {result}")

    _save_run_stats(result)
    return result


def run_qualifier_background(county: str | None = None) -> dict:
    db = SessionLocal()
    try:
        return run_qualifier(db, county=county)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Last-run stats
# ─────────────────────────────────────────────────────────────────────────────


_STATS_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "filestore",
    "System Data",
    "qualifier_last_run.json",
)


def _save_run_stats(result: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_STATS_PATH), exist_ok=True)
        with open(_STATS_PATH, "w") as f:
            json.dump(result, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save qualifier last-run stats: {e}")


def get_last_run() -> dict | None:
    try:
        if os.path.exists(_STATS_PATH):
            with open(_STATS_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return None
