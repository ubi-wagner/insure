"""
Aggregator — LEAD → VETTED transition.

Groups LEAD-stage entities by (county, zip5, normalized street address)
and consolidates each group into one master + N linked siblings via
Entity.parent_id. The master carries summed TIV, max(unit_count), and
max(stories); siblings stay as references for audit / contact
discovery / per-unit sale history but are hidden from the main
pipeline list (filtered by parent_id IS NULL).

Pure deterministic Python over already-ingested data — no network,
no AI, no enrichers. Safe to re-run; idempotent.

Aggregation key (cross-county collisions impossible because county
is the first key element):
    county, normalized_zip5, normalized_street_address

Master selection rule (in priority order):
    1. Any row flagged is_condo_master (the DOR common-elements parcel)
    2. Otherwise the row with the lowest id (first ingested wins)

Roll-up rules per master:
    - tiv_estimate_master = sum(group.tiv_estimate or 0)
    - dor_market_value_master = sum(group.dor_market_value or 0)
    - num_units_master = max(NAL master.num_units, count(siblings))
    - stories_master = max over siblings (biggest number wins)
    - sibling_count, sibling_ids stored on master.characteristics

Implementation note: runs strictly county-by-county. Each county
loads its own LEAD set (bounded by county size, typically tens of
thousands of rows) so RAM stays flat. Per-group sibling updates use
one bulk UPDATE statement instead of one ORM update per sibling.
Per-master enrichment queueing is deferred to the end of the run
and done in a single pass.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import Entity
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


def _list_counties_with_leads(db: Session) -> list[str]:
    """Distinct county names that currently hold un-linked LEADs."""
    rows = (
        db.query(Entity.county)
        .filter(Entity.pipeline_stage == "LEAD")
        .filter(Entity.parent_id.is_(None))
        .filter(Entity.county.isnot(None))
        .distinct()
        .all()
    )
    return sorted(r[0] for r in rows if r[0])


def _aggregate_one_county(db: Session, county_name: str) -> dict:
    """Run the LEAD → VETTED transition for a single county.

    Loads only that county's LEAD set, groups by (zip5, normalized
    street), and writes the result back via bulk SQL. Cross-county
    collisions are impossible because the load is county-filtered.
    """
    candidates = (
        db.query(Entity)
        .filter(Entity.pipeline_stage == "LEAD")
        .filter(Entity.parent_id.is_(None))
        .filter(Entity.county == county_name)
        .all()
    )

    groups: dict[tuple[str, str], list[Entity]] = defaultdict(list)
    skipped_no_address = 0

    for e in candidates:
        zip5 = _entity_zip(e)
        street = _entity_street(e)
        if not street:
            skipped_no_address += 1
            continue
        groups[(zip5, street)].append(e)

    masters_promoted = 0
    siblings_linked = 0
    singletons = 0
    new_master_ids: list[int] = []

    for (zip5, street), group in groups.items():
        master = _select_master(group)
        master.characteristics = _rollup_master(master, group)
        master.pipeline_stage = "VETTED"
        new_master_ids.append(master.id)
        masters_promoted += 1
        if len(group) == 1:
            singletons += 1
            continue

        sibling_ids = [e.id for e in group if e.id != master.id]
        # One bulk UPDATE per group instead of one ORM update per
        # sibling. synchronize_session=False because we don't reuse
        # these objects after the update — we only commit.
        if sibling_ids:
            db.query(Entity).filter(Entity.id.in_(sibling_ids)).update(
                {
                    "parent_id": master.id,
                    "pipeline_stage": "VETTED",
                },
                synchronize_session=False,
            )
            siblings_linked += len(sibling_ids)

    db.commit()
    db.expunge_all()

    return {
        "county": county_name,
        "scanned_leads": len(candidates),
        "groups_formed": len(groups),
        "masters_promoted": masters_promoted,
        "siblings_linked": siblings_linked,
        "singletons": singletons,
        "skipped_no_address": skipped_no_address,
        "new_master_ids": new_master_ids,
    }


def run_aggregator(db: Session, county: str | None = None) -> dict:
    """Group LEADs by (county, zip5, street) and promote to VETTED.

    Strictly county-by-county. Each county is its own load + group +
    bulk-update + commit cycle so RAM stays bounded and per-county
    progress shows up live in the ops dashboard. Cross-county
    collisions are impossible because each loop iteration only sees
    one county's rows.

    Master selection per group:
      1. is_condo_master flag if any row carries it (the DOR
         common-elements parcel)
      2. Otherwise the lowest-id row wins (first ingested)

    Master roll-up onto master.characteristics:
      tiv_estimate_master       sum(group.tiv_estimate)
      dor_market_value_master   sum(group.dor_market_value)
      num_units_master          max(NAL master count, sibling count, group size)
      stories_master            max across siblings (biggest number wins)
      sibling_count, sibling_ids[] for the UI's "linked parcels" list

    Idempotent: re-running skips already-VETTED rows and any LEAD
    that already has parent_id set.
    """
    from services import pipeline_state

    if county:
        counties = [county]
    else:
        counties = _list_counties_with_leads(db)

    pipeline_state.mark_started(
        "aggregator",
        summary=f"Aggregating LEADs in {len(counties)} "
                f"{'counties' if len(counties) != 1 else 'county'}",
    )

    started = datetime.now(timezone.utc)
    emit(EventType.HUNTER, "aggregator_start", EventStatus.PENDING,
         detail=f"Aggregating LEAD → VETTED across {len(counties)} counties")

    per_county: list[dict] = []
    total_masters = 0
    total_siblings = 0
    total_singletons = 0
    total_scanned = 0
    total_skipped = 0
    all_new_master_ids: list[int] = []

    for idx, c in enumerate(counties, start=1):
        pipeline_state.mark_progress(
            "aggregator",
            current=f"({idx}/{len(counties)}) {c}",
            details={
                "completed_counties": [r["county"] for r in per_county],
                "total_masters_promoted": total_masters,
                "total_siblings_linked": total_siblings,
            },
        )

        try:
            r = _aggregate_one_county(db, c)
        except Exception as e:
            db.rollback()
            logger.error(f"Aggregator failed for {c}: {e}")
            r = {
                "county": c, "error": str(e),
                "scanned_leads": 0, "groups_formed": 0,
                "masters_promoted": 0, "siblings_linked": 0,
                "singletons": 0, "skipped_no_address": 0,
                "new_master_ids": [],
            }

        per_county.append({k: v for k, v in r.items() if k != "new_master_ids"})
        total_masters += r["masters_promoted"]
        total_siblings += r["siblings_linked"]
        total_singletons += r["singletons"]
        total_scanned += r["scanned_leads"]
        total_skipped += r["skipped_no_address"]
        all_new_master_ids.extend(r["new_master_ids"])

        emit(EventType.HUNTER, "aggregator_county", EventStatus.SUCCESS,
             detail=(f"Aggregator {c}: {r['masters_promoted']:,} masters, "
                     f"{r['siblings_linked']:,} siblings"))

    # Defer enrichment queueing until after every county is done.
    # Doing this once at the end (instead of per-master inside the
    # group loop) means we run produce_jobs_for_entity in one pass
    # rather than one call per master.
    queued = 0
    if all_new_master_ids:
        try:
            from services.job_queue import produce_jobs_for_entity
            for mid in all_new_master_ids:
                try:
                    produce_jobs_for_entity(mid, db)
                    queued += 1
                except Exception as e:
                    logger.warning(f"Failed to queue enrichment for master {mid}: {e}")
        except Exception as e:
            logger.warning(f"Failed to import job_queue: {e}")

    finished = datetime.now(timezone.utc)
    duration = (finished - started).total_seconds()

    result = {
        "scanned_leads": total_scanned,
        "masters_promoted": total_masters,
        "siblings_linked": total_siblings,
        "singletons": total_singletons,
        "skipped_no_address": total_skipped,
        "counties_processed": len(counties),
        "per_county": per_county,
        "enrichment_jobs_queued": queued,
        "county_filter": county,
        "duration_sec": round(duration, 1),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
    }
    _save_run_stats(result)

    pipeline_state.mark_finished(
        "aggregator",
        summary=(
            f"{total_masters:,} VETTED masters across {len(counties)} counties "
            f"({total_siblings:,} siblings, {total_singletons:,} singletons, "
            f"{duration:.1f}s)"
        ),
        details=result,
    )

    emit(EventType.HUNTER, "aggregator_done", EventStatus.SUCCESS,
         detail=(
             f"Aggregator: {total_masters:,} masters across {len(counties)} "
             f"counties in {duration:.1f}s"
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
