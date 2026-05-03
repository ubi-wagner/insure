"""
Aggregator — LEAD → VETTED transition.

Groups LEAD-stage entities by (county, zip5, normalized street address)
and consolidates each group into one master + N linked siblings via
Entity.parent_id. The master record carries summed TIV, max(unit_count),
and max(stories) across its siblings; siblings stay as references for
audit / contact discovery / per-unit sale history but are hidden from
the main pipeline list (filtered by parent_id IS NULL).

This is pure deterministic Python over already-ingested data — no
network, no AI, no enrichers. Safe to re-run; idempotent.

Aggregation key:
    county, normalized_zip5, normalized_street_address

Master selection rule (in priority order):
    1. Any row flagged is_condo_master (the DOR common-elements parcel)
    2. Otherwise the row with the lowest id (first ingested wins)

Roll-up rules per master:
    - tiv_estimate_master = sum(siblings.tiv_estimate or 0)
    - dor_market_value_master = sum(siblings.dor_market_value or 0)
    - num_units_master = max(NAL master.num_units, count(siblings))
    - stories_master = max over siblings (biggest number wins)
    - sibling_count, sibling_ids stored on master.characteristics
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import Entity, LeadLedger
from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Address normalization
# ─────────────────────────────────────────────────────────────────────────────


_SUFFIX_NORMALISE = {
    "avenue": "ave", "ave": "ave",
    "boulevard": "blvd", "blvd": "blvd",
    "street": "st", "st": "st",
    "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr",
    "lane": "ln", "ln": "ln",
    "place": "pl", "pl": "pl",
    "court": "ct", "ct": "ct",
    "terrace": "ter", "ter": "ter",
    "parkway": "pkwy", "pkwy": "pkwy",
    "highway": "hwy", "hwy": "hwy",
    "circle": "cir", "cir": "cir",
    "way": "way",
    "mile": "mile",
    "north": "n", "n": "n",
    "south": "s", "s": "s",
    "east": "e", "e": "e",
    "west": "w", "w": "w",
    "northeast": "ne", "ne": "ne",
    "northwest": "nw", "nw": "nw",
    "southeast": "se", "se": "se",
    "southwest": "sw", "sw": "sw",
}


def _normalize_street(addr: str | None) -> str:
    """Canonical key for the street segment of an address.

    Drops everything after the first comma (city/state/zip) so the
    aggregator key stays focused on "this exact street line in this
    zip in this county". Lowercases, normalises suffix/directional
    spelling, and squashes punctuation. Returns empty string when
    no usable street is present.
    """
    if not addr:
        return ""
    street = addr.split(",", 1)[0].lower()
    street = re.sub(r"[.,#]", " ", street)
    parts = [p for p in street.split() if p]
    out: list[str] = []
    for p in parts:
        out.append(_SUFFIX_NORMALISE.get(p, p))
    return " ".join(out)


def _normalize_zip5(zip_str: str | None) -> str:
    if not zip_str:
        return ""
    digits = re.sub(r"\D", "", str(zip_str))
    return digits[:5]


def _entity_zip(entity: Entity) -> str:
    chars = entity.characteristics or {}
    z = (
        chars.get("phy_zip")
        or chars.get("dor_zip_code")
        or chars.get("zip")
    )
    if z:
        return _normalize_zip5(str(z))
    # Fall back to the tail of entity.address
    addr = entity.address or ""
    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", addr)
    return m.group(1) if m else ""


def _entity_street(entity: Entity) -> str:
    return _normalize_street(entity.address)


def _aggregation_key(entity: Entity) -> tuple[str, str, str]:
    return (
        (entity.county or "").strip(),
        _entity_zip(entity),
        _entity_street(entity),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Roll-up helpers
# ─────────────────────────────────────────────────────────────────────────────


def _to_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _select_master(group: list[Entity]) -> Entity:
    """Master picked first by is_condo_master flag, otherwise lowest id."""
    masters = [
        e for e in group
        if (e.characteristics or {}).get("is_condo_master")
    ]
    if masters:
        return min(masters, key=lambda e: e.id)
    return min(group, key=lambda e: e.id)


def _rollup_master(master: Entity, group: list[Entity]) -> dict:
    """Compute summed/maxed values across the group; return the chars patch."""
    chars = dict(master.characteristics or {})

    sibling_ids = [e.id for e in group if e.id != master.id]

    tiv_sum = 0
    jv_sum = 0
    have_any_jv = False
    have_any_tiv = False
    units_seen: list[int] = []
    stories_seen: list[int] = []

    for e in group:
        ec = e.characteristics or {}
        t = _to_int(ec.get("tiv_estimate"))
        if t is not None:
            tiv_sum += t
            have_any_tiv = True
        m = _to_int(ec.get("dor_market_value"))
        if m is not None:
            jv_sum += m
            have_any_jv = True
        u = _to_int(ec.get("dor_num_units")) or _to_int(ec.get("units_estimate"))
        if u is not None:
            units_seen.append(u)
        s = _to_int(ec.get("stories")) or _to_int(ec.get("dbpr_max_stories"))
        if s is not None:
            stories_seen.append(s)

    # Unit count = max(NAL master count, count of physical sibling rows)
    sibling_unit_count = len([
        e for e in group
        if (e.characteristics or {}).get("is_condo_unit_parcel")
    ])
    nal_master_units = max(units_seen) if units_seen else 0
    units_master = max(nal_master_units, sibling_unit_count, len(group))

    stories_master = max(stories_seen) if stories_seen else None

    # Both _master and canonical keys get the rolled-up values, so
    # downstream readers (cream_score, validation, the UI) see master
    # truth without having to know about the _master suffix. The
    # _master copies stick around for forensics.
    rolled_units = units_master if units_master > 0 else None
    rolled_tiv = tiv_sum if have_any_tiv else None
    rolled_jv = jv_sum if have_any_jv else None

    patch: dict = {
        "tiv_estimate_master": rolled_tiv,
        "tiv_master_is_estimate": True,  # honest; Zillow phase replaces
        "dor_market_value_master": rolled_jv,
        "num_units_master": rolled_units,
        "stories_master": stories_master,
        "sibling_count": len(sibling_ids),
        "sibling_ids": sibling_ids[:500],  # cap stored list to keep JSON small
        "is_aggregation_master": True,
        "aggregated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Promote to canonical keys when the rolled-up value is meaningful.
    if rolled_tiv is not None and rolled_tiv > 0:
        patch["tiv_estimate"] = rolled_tiv
        patch["tiv"] = f"${rolled_tiv:,.0f}"
        patch["tiv_is_estimate"] = True
    if rolled_jv is not None and rolled_jv > 0:
        patch["dor_market_value"] = rolled_jv
    if rolled_units is not None and rolled_units > 0:
        patch["dor_num_units"] = rolled_units
        patch["units_estimate"] = rolled_units
    if stories_master is not None and stories_master > 0:
        patch["stories"] = stories_master
        patch["stories_source"] = "aggregator"

    chars.update(patch)
    return chars


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────


def run_aggregator(db: Session, county: str | None = None) -> dict:
    """Group LEADs by (county, zip5, street) and promote to VETTED.

    For every group:
      - select a master (is_condo_master flag, else lowest id)
      - set parent_id on siblings to master.id
      - update master.characteristics with rolled-up totals
      - advance master AND siblings to pipeline_stage = "VETTED"

    Re-runnable. Existing VETTED rows are skipped. Records that have
    already been linked under a parent are skipped.
    """
    from services import pipeline_state

    pipeline_state.mark_started(
        "aggregator",
        summary=f"Aggregating LEADs"
        + (f" in {county}" if county else " in all counties"),
    )

    started = datetime.now(timezone.utc)
    emit(EventType.HUNTER, "aggregator_start", EventStatus.PENDING,
         detail=f"Aggregating LEAD → VETTED"
                + (f" for {county}" if county else ""))

    q = (
        db.query(Entity)
        .filter(Entity.pipeline_stage == "LEAD")
        .filter(Entity.parent_id.is_(None))
    )
    if county:
        q = q.filter(Entity.county == county)

    candidates = q.all()
    groups: dict[tuple[str, str, str], list[Entity]] = defaultdict(list)
    skipped_no_address = 0

    for e in candidates:
        key = _aggregation_key(e)
        if not key[2]:  # no street → can't aggregate, leave as LEAD
            skipped_no_address += 1
            continue
        groups[key].append(e)

    masters_promoted = 0
    siblings_linked = 0
    singletons = 0  # one-LEAD groups still get promoted to VETTED master

    for key, group in groups.items():
        master = _select_master(group)
        # Roll up totals onto master.characteristics
        master.characteristics = _rollup_master(master, group)
        master.pipeline_stage = "VETTED"
        masters_promoted += 1
        if len(group) == 1:
            singletons += 1

        for sibling in group:
            if sibling.id == master.id:
                continue
            sibling.parent_id = master.id
            sibling.pipeline_stage = "VETTED"
            siblings_linked += 1

        ledger = LeadLedger(
            entity_id=master.id,
            action_type="STAGE_CHANGE",
            detail=(
                f"LEAD → VETTED via aggregator: {len(group)} parcel"
                f"{'s' if len(group) != 1 else ''} at "
                f"{key[2]} ({key[1]} {key[0]})"
            ),
            source="aggregator",
        )
        db.add(ledger)

        # Queue enrichment jobs for the new master — children skip.
        try:
            from services.job_queue import produce_jobs_for_entity
            produce_jobs_for_entity(master.id, db)
        except Exception as e:
            logger.warning(
                f"Failed to queue enrichment for master {master.id}: {e}"
            )

        if masters_promoted % 500 == 0:
            db.commit()

    db.commit()

    finished = datetime.now(timezone.utc)
    duration = (finished - started).total_seconds()

    result = {
        "scanned_leads": len(candidates),
        "groups_formed": len(groups),
        "masters_promoted": masters_promoted,
        "siblings_linked": siblings_linked,
        "singletons": singletons,
        "skipped_no_address": skipped_no_address,
        "county_filter": county,
        "duration_sec": round(duration, 1),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
    }
    _save_run_stats(result)

    pipeline_state.mark_finished(
        "aggregator",
        summary=(
            f"{masters_promoted:,} VETTED masters "
            f"({siblings_linked:,} siblings, {singletons:,} singletons, "
            f"{duration:.1f}s)"
        ),
        details=result,
    )

    emit(EventType.HUNTER, "aggregator_done", EventStatus.SUCCESS,
         detail=(
             f"Aggregator: {masters_promoted:,} masters "
             f"({siblings_linked:,} siblings linked, "
             f"{singletons:,} singletons) in {duration:.1f}s"
         ))
    logger.info(f"Aggregator: {result}")
    return result


def run_aggregator_background(county: str | None = None) -> dict:
    db = SessionLocal()
    try:
        return run_aggregator(db, county=county)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Last-run stats persistence
# ─────────────────────────────────────────────────────────────────────────────


_STATS_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "filestore",
    "System Data",
    "aggregator_last_run.json",
)


def _save_run_stats(result: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_STATS_PATH), exist_ok=True)
        with open(_STATS_PATH, "w") as f:
            json.dump(result, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save aggregator last-run stats: {e}")


def get_last_run() -> dict | None:
    try:
        if os.path.exists(_STATS_PATH):
            with open(_STATS_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return None
