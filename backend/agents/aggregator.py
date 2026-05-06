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

# Tokens that anchor the building street line. Anything after one of
# these (plus an optional trailing directional like "S" or "N") is
# unit / suite / apartment noise that must be stripped before
# aggregation, otherwise every condo unit becomes its own group.
_STREET_SUFFIXES = {
    "ave", "blvd", "st", "rd", "dr", "ln", "pl", "ct", "ter",
    "pkwy", "hwy", "cir", "way", "mile",
}
_DIRECTIONALS = {"n", "s", "e", "w", "ne", "nw", "se", "sw"}

# Tokens that explicitly mark unit-level information. Encountering one
# stops street parsing immediately even if no suffix has been seen.
_UNIT_MARKERS = {
    "unit", "apt", "apartment", "ste", "suite", "bldg", "building",
    "lot", "fl", "floor", "rm", "room", "ph",
}


def _normalize_street(addr: str | None) -> str:
    """Canonical key for the street segment of an address.

    Strips city / state / zip (everything past the first comma), then
    normalises directional and street-suffix spellings, then walks the
    tokens left-to-right and TRUNCATES at the first sign of a
    unit / apartment / suite suffix. The truncation rule:

      [number] [name…] [suffix] [optional one directional]

    Anything after that — bare numeric (e.g. "1702" in
    "1451 BRICKELL AVE 1702") or an explicit unit marker (#, UNIT,
    APT, STE, FL, RM, etc.) — is dropped. Without this every condo
    unit row produces a unique aggregation key and we end up with
    171 single-row "masters" instead of one Echo Brickell master
    with 171 linked siblings.
    """
    if not addr:
        return ""
    street = addr.split(",", 1)[0].lower()
    # Pre-tokenise: replace #, dashes, commas, dots with spaces so they
    # don't fuse to neighbouring tokens. "AVE-S" → "AVE S", "#106" → " 106".
    street = re.sub(r"[#.,\-]", " ", street)
    raw_tokens = [t for t in street.split() if t]
    tokens = [_SUFFIX_NORMALISE.get(t, t) for t in raw_tokens]

    out: list[str] = []
    have_suffix = False
    for t in tokens:
        # Explicit unit marker terminates parsing regardless of whether
        # we've seen a suffix yet.
        if t in _UNIT_MARKERS:
            break
        if have_suffix:
            # We've already captured a suffix — accept exactly one
            # trailing directional, then stop. Bare numbers / letters
            # after the directional are unit codes.
            if t in _DIRECTIONALS:
                out.append(t)
                # Don't allow another suffix or anything else past this.
                break
            # Any other token after the suffix is unit noise.
            break
        out.append(t)
        if t in _STREET_SUFFIXES:
            have_suffix = True
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
    """Canonical street key for grouping.

    Prefers the precomputed ``street_canon`` field that the seeder
    writes via utils.address.canonicalize_address. Falls back to
    re-deriving from entity.address for old rows that landed before
    the seeder started writing the field.
    """
    chars = entity.characteristics or {}
    cached = chars.get("street_canon")
    if cached:
        return str(cached)
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
    """Counties that hold rows the aggregator should consider.

    Includes LEAD AND VETTED at parent_id IS NULL so that re-clicking
    Aggregate after a code fix can re-group previously-promoted
    singletons (the broken pre-fix pass left ~1.9M of them).
    """
    rows = (
        db.query(Entity.county)
        .filter(Entity.pipeline_stage.in_(["LEAD", "VETTED"]))
        .filter(Entity.parent_id.is_(None))
        .filter(Entity.county.isnot(None))
        .distinct()
        .all()
    )
    return sorted(r[0] for r in rows if r[0])


def _is_orphan_condo_unit(entity: Entity) -> bool:
    """A DOR_UC=004 row with no master flag and no real unit count is
    an orphan unit parcel — a single condo unit that didn't find any
    sibling rows at the same building. Promoting it to VETTED produces
    the "1-unit condo" UI bug; keep it as LEAD until siblings show up.
    """
    chars = entity.characteristics or {}
    if str(chars.get("dor_use_code") or "").zfill(3) != "004":
        return False
    if chars.get("is_condo_master"):
        return False
    units = _to_int(chars.get("dor_num_units")) or 0
    return units <= 1


def _is_already_aggregated_master(entity: Entity) -> bool:
    """A VETTED row whose siblings already point at it. Re-grouping it
    alone (siblings are filtered out by parent_id IS NOT NULL) would
    wrongly reset its sibling_count. Skip."""
    chars = entity.characteristics or {}
    return bool(
        chars.get("is_aggregation_master")
        and (chars.get("sibling_count") or 0) > 0
    )


_MASTER_KEYS_TO_CLEAR = (
    "is_aggregation_master", "sibling_count", "sibling_ids",
    "aggregated_at", "tiv_estimate_master", "dor_market_value_master",
    "num_units_master", "stories_master", "tiv_master_is_estimate",
)


def _strip_master_metadata(chars: dict) -> dict:
    """Remove rolled-up master fields from a row that's being demoted
    back to LEAD. Returns a fresh dict (SQLAlchemy needs a new object
    on the JSONB column to detect the change)."""
    out = dict(chars or {})
    for k in _MASTER_KEYS_TO_CLEAR:
        out.pop(k, None)
    return out


def _aggregate_one_county(db: Session, county_name: str) -> dict:
    """Run the LEAD/VETTED → VETTED transition for a single county.

    Loads only that county's un-linked rows, groups by (zip5,
    normalized street), and writes the result back via bulk SQL.
    Cross-county collisions are impossible because the load is
    county-filtered.

    Idempotent. Safe to re-run after a code change in the address
    normaliser — singleton VETTED rows from a previous pass get
    re-considered and either group correctly or fall back to LEAD
    if they're orphan condo units.
    """
    candidates = (
        db.query(Entity)
        .filter(Entity.pipeline_stage.in_(["LEAD", "VETTED"]))
        .filter(Entity.parent_id.is_(None))
        .filter(Entity.county == county_name)
        .all()
    )

    groups: dict[tuple[str, str], list[Entity]] = defaultdict(list)
    skipped_no_address = 0
    skipped_existing_master = 0

    for e in candidates:
        # Don't re-touch already-correctly-aggregated masters — they
        # appear as a group of 1 because their siblings are filtered
        # out, and re-rolling-up would reset their sibling_count.
        if _is_already_aggregated_master(e):
            skipped_existing_master += 1
            continue
        zip5 = _entity_zip(e)
        street = _entity_street(e)
        if not street:
            skipped_no_address += 1
            continue
        groups[(zip5, street)].append(e)

    masters_promoted = 0
    siblings_linked = 0
    singletons = 0
    orphan_units = 0
    new_master_ids: list[int] = []

    for (zip5, street), group in groups.items():
        # ── Singleton path ─────────────────────────────────────────
        if len(group) == 1:
            only = group[0]
            if _is_orphan_condo_unit(only):
                # Don't promote a 1-unit condo. If a previous broken
                # pass already promoted it to VETTED, demote it back
                # to LEAD and strip the bogus master metadata so the
                # pipeline list doesn't show a "1-unit master".
                orphan_units += 1
                if only.pipeline_stage == "VETTED":
                    only.pipeline_stage = "LEAD"
                    only.characteristics = _strip_master_metadata(only.characteristics)
                continue

            # Legitimate singleton (small commercial / hotel / etc.)
            only.characteristics = _rollup_master(only, group)
            only.pipeline_stage = "VETTED"
            new_master_ids.append(only.id)
            masters_promoted += 1
            singletons += 1
            continue

        # ── Multi-row group ────────────────────────────────────────
        master = _select_master(group)
        master.characteristics = _rollup_master(master, group)
        master.pipeline_stage = "VETTED"
        new_master_ids.append(master.id)
        masters_promoted += 1

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
        "orphan_units_demoted": orphan_units,
        "skipped_existing_master": skipped_existing_master,
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
    total_orphans = 0
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
                "total_orphan_units_demoted": total_orphans,
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
                "singletons": 0, "orphan_units_demoted": 0,
                "skipped_existing_master": 0, "skipped_no_address": 0,
                "new_master_ids": [],
            }

        per_county.append({k: v for k, v in r.items() if k != "new_master_ids"})
        total_masters += r["masters_promoted"]
        total_siblings += r["siblings_linked"]
        total_singletons += r["singletons"]
        total_orphans += r.get("orphan_units_demoted", 0)
        total_scanned += r["scanned_leads"]
        total_skipped += r["skipped_no_address"]
        all_new_master_ids.extend(r["new_master_ids"])

        emit(EventType.HUNTER, "aggregator_county", EventStatus.SUCCESS,
             detail=(
                 f"Aggregator {c}: {r['masters_promoted']:,} masters, "
                 f"{r['siblings_linked']:,} siblings, "
                 f"{r.get('orphan_units_demoted', 0):,} orphan units → LEAD"
             ))

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
        "orphan_units_demoted": total_orphans,
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
            f"{total_orphans:,} orphan units → LEAD, {duration:.1f}s)"
        ),
        details=result,
    )

    emit(EventType.HUNTER, "aggregator_done", EventStatus.SUCCESS,
         detail=(
             f"Aggregator: {total_masters:,} masters across {len(counties)} "
             f"counties in {duration:.1f}s "
             f"({total_orphans:,} orphan units demoted to LEAD)"
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
