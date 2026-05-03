"""
Qualifier — TARGET → LEAD transition.

The seeder ingests every non-residential parcel as TARGET (skipping
only DOR_UC 001 single-family and 002 mobile homes). The qualifier
applies an admin-configurable allowlist of DOR use codes and promotes
matching TARGETs to LEAD via one bulk SQL UPDATE per county.

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

Implementation note: this used to load every TARGET via q.all() and
loop in Python with per-row LeadLedger inserts. At 5M+ TARGETs it
would have OOM'd or taken hours. The current implementation uses one
bulk UPDATE per county against a JSONB filter, no Python iteration
over rows, no per-row audit fan-out. Per-run summary lives in
qualifier_last_run.json + pipeline_state.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import Entity
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


_BULK_UPDATE_SQL = text("""
    UPDATE entities
    SET pipeline_stage = 'LEAD'
    WHERE pipeline_stage = 'TARGET'
      AND county = :county
      AND (characteristics ->> 'dor_use_code') = ANY(:codes)
""")


def _list_counties_with_targets(db: Session) -> list[str]:
    """Distinct county names that currently hold TARGETs. We loop over
    these so the admin UI sees per-county progress and so memory stays
    bounded."""
    rows = (
        db.query(Entity.county)
        .filter(Entity.pipeline_stage == "TARGET")
        .filter(Entity.county.isnot(None))
        .distinct()
        .all()
    )
    return sorted(r[0] for r in rows if r[0])


def run_qualifier(db: Session, county: str | None = None) -> dict:
    """Promote every TARGET whose dor_use_code is in the allowlist to LEAD.

    Per-county bulk SQL UPDATE — one statement per county. With a JSONB
    filter on (characteristics ->> 'dor_use_code') Postgres handles the
    work in milliseconds even at 1M+ rows.

    Cross-county collisions are impossible: ``county`` is part of the
    WHERE clause and the seeder writes Entity.county directly, so each
    UPDATE only touches one county at a time.

    When ``county`` is None we iterate every county that still holds
    TARGETs, posting per-county progress so the ops dashboard can
    show "(12/35) Pinellas" while it runs.
    """
    from services import pipeline_state

    cfg = get_qualifier_config()
    allowlist = cfg["use_codes"]
    if not allowlist:
        return {
            "promoted": 0,
            "use_codes": [],
            "error": "Qualifier allowlist is empty — nothing to promote.",
        }

    if county:
        counties = [county]
    else:
        counties = _list_counties_with_targets(db)

    pipeline_state.mark_started(
        "qualifier",
        summary=f"Qualifying TARGETs in {len(counties)} "
                f"{'counties' if len(counties) != 1 else 'county'}",
    )

    started = datetime.now(timezone.utc)
    emit(EventType.HUNTER, "qualifier_start", EventStatus.PENDING,
         detail=f"Promoting TARGET → LEAD for codes {sorted(allowlist)} "
                f"across {len(counties)} counties")

    promoted_by_county: dict[str, int] = {}
    total_promoted = 0

    for idx, c in enumerate(counties, start=1):
        pipeline_state.mark_progress(
            "qualifier",
            current=f"({idx}/{len(counties)}) {c}",
            details={"promoted_by_county": promoted_by_county,
                     "total_promoted": total_promoted},
        )

        try:
            result = db.execute(
                _BULK_UPDATE_SQL,
                {"county": c, "codes": list(allowlist)},
            )
            row_count = result.rowcount or 0
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Qualifier failed for {c}: {e}")
            promoted_by_county[c] = 0
            continue

        promoted_by_county[c] = row_count
        total_promoted += row_count

        emit(EventType.HUNTER, "qualifier_county", EventStatus.SUCCESS,
             detail=f"Qualifier {c}: {row_count:,} TARGET → LEAD")

    finished = datetime.now(timezone.utc)
    duration = (finished - started).total_seconds()

    result = {
        "promoted": total_promoted,
        "promoted_by_county": promoted_by_county,
        "use_codes": sorted(allowlist),
        "counties_processed": len(counties),
        "county_filter": county,
        "duration_sec": round(duration, 1),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
    }

    emit(EventType.HUNTER, "qualifier_done", EventStatus.SUCCESS,
         detail=(
             f"Qualifier: {total_promoted:,} TARGETs → LEADs across "
             f"{len(counties)} counties in {duration:.1f}s"
         ))
    logger.info(f"Qualifier: {result}")

    pipeline_state.mark_finished(
        "qualifier",
        summary=(
            f"{total_promoted:,} TARGETs promoted to LEAD across "
            f"{len(counties)} counties ({duration:.1f}s)"
        ),
        details=result,
    )
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
