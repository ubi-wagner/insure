"""
Job Queue — DB-backed enrichment pipeline.

Three roles:
  1. Producer: creates PENDING jobs when an entity reaches LEAD stage
  2. Consumer: picks PENDING jobs, runs the enricher, marks SUCCESS/FAILED
  3. Manager: sweeps stale locks, retries failed jobs, rejects permanently broken ones

Design principles:
  - No MUTEX — consumer uses SELECT ... FOR UPDATE SKIP LOCKED
  - Idempotent — unique constraint on (entity_id, enricher) prevents duplicates
  - Observable — every state change emits a namespaced event
  - Retry-aware — 3 attempts default, exponential backoff via Manager sweep
"""

import logging
import os
import time
import threading
import uuid
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import Entity, JobQueue
from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)

# Worker identity — unique per process
WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"

# Enricher dependency graph — enricher: [must complete first]
# cream_score runs last (depends on everything else)
ENRICHER_CHAIN = [
    {"enricher": "fema_flood",          "priority": 10, "depends_on": None},
    {"enricher": "property_appraiser",  "priority": 10, "depends_on": None},
    {"enricher": "dbpr_bulk",           "priority": 10, "depends_on": None},
    {"enricher": "dbpr_payments",       "priority": 8,  "depends_on": "dbpr_bulk"},
    {"enricher": "dbpr_sirs",           "priority": 8,  "depends_on": "dbpr_bulk"},
    {"enricher": "dbpr_building",       "priority": 8,  "depends_on": "dbpr_bulk"},
    {"enricher": "cam_license",         "priority": 7,  "depends_on": None},
    {"enricher": "sunbiz_bulk",         "priority": 9,  "depends_on": None},
    {"enricher": "dor_nal",             "priority": 6,  "depends_on": None},
    {"enricher": "citizens_insurance",  "priority": 4,  "depends_on": "oir_market"},
    {"enricher": "fdot_parcels",        "priority": 4,  "depends_on": None},
    {"enricher": "oir_market",          "priority": 5,  "depends_on": None},
    {"enricher": "cream_score",         "priority": -1, "depends_on": "__all__"},  # Runs last
]

CONSUMER_BATCH_SIZE = int(os.getenv("JOB_BATCH_SIZE", "10"))
CONSUMER_POLL_INTERVAL = int(os.getenv("JOB_POLL_INTERVAL", "15"))  # seconds
STALE_LOCK_MINUTES = 10  # Jobs locked longer than this are considered stale
MAX_ATTEMPTS = 3


# ─── Producer ───────────────────────────────────────────────────────

def produce_jobs_for_entity(entity_id: int, db: Session) -> int:
    """Create enrichment jobs for an entity that just reached LEAD stage.

    Skips enrichers that already ran (recorded in enrichment_sources).
    Uses INSERT ... ON CONFLICT DO NOTHING for idempotency.
    Returns number of jobs created.
    """
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        return 0

    existing_sources = set((entity.enrichment_sources or {}).keys())
    created = 0

    for spec in ENRICHER_CHAIN:
        enricher = spec["enricher"]

        # Skip if already enriched
        if enricher in existing_sources:
            continue

        depends_on = spec["depends_on"]

        try:
            job = JobQueue(
                entity_id=entity_id,
                enricher=enricher,
                status="PENDING",
                priority=spec["priority"],
                depends_on=depends_on,
                max_attempts=MAX_ATTEMPTS,
            )
            db.add(job)
            db.flush()  # Trigger unique constraint check
            created += 1
        except sa.exc.IntegrityError:
            db.rollback()
            # Job already exists — skip silently (idempotent)
            continue

    if created > 0:
        db.commit()
        emit(EventType.HUNTER, "pipeline:produce", EventStatus.SUCCESS,
             detail=f"Created {created} jobs for entity {entity_id}",
             entity_id=entity_id)

    return created


def produce_jobs_for_all_leads(db: Session) -> int:
    """Backfill: create jobs for all LEADs missing enrichment.

    Called on startup or after a DB reset to catch up.
    """
    leads = db.query(Entity).filter(
        Entity.pipeline_stage == "LEAD",
        Entity.enrichment_status.in_(["idle", "error"]),
    ).all()

    total_created = 0
    for entity in leads:
        try:
            created = produce_jobs_for_entity(entity.id, db)
            total_created += created
        except Exception as e:
            logger.warning(f"Failed to produce jobs for entity {entity.id}: {e}")
            db.rollback()

    if total_created > 0:
        emit(EventType.HUNTER, "pipeline:backfill", EventStatus.SUCCESS,
             detail=f"Backfilled {total_created} jobs for {len(leads)} leads")
        logger.info(f"Backfilled {total_created} jobs for {len(leads)} leads")

    return total_created


# ─── Consumer ───────────────────────────────────────────────────────

def _dependency_met(job: JobQueue, db: Session) -> bool:
    """Check if a job's dependency is satisfied."""
    if job.depends_on is None:
        return True

    if job.depends_on == "__all__":
        # cream_score: all other enrichers for this entity must be SUCCESS or REJECTED
        pending = db.query(JobQueue).filter(
            JobQueue.entity_id == job.entity_id,
            JobQueue.enricher != job.enricher,
            JobQueue.status.in_(["PENDING", "RUNNING", "FAILED"]),
        ).count()
        return pending == 0

    # Single dependency — check if that enricher succeeded for this entity
    dep_job = db.query(JobQueue).filter(
        JobQueue.entity_id == job.entity_id,
        JobQueue.enricher == job.depends_on,
    ).first()

    if dep_job is None:
        return True  # Dependency doesn't exist (enricher already ran before queue existed)
    return dep_job.status in ("SUCCESS", "REJECTED")


def consume_batch(db: Session) -> int:
    """Pick up to CONSUMER_BATCH_SIZE PENDING jobs and run them.

    Uses FOR UPDATE SKIP LOCKED to prevent multiple workers from grabbing
    the same job. Each job is processed in its own try/except so one failure
    doesn't block the batch.
    """
    # Fetch candidate jobs — PENDING, ordered by priority DESC (highest first)
    jobs = db.execute(
        sa.text("""
            SELECT id FROM job_queue
            WHERE status = 'PENDING'
            ORDER BY priority DESC, created_at ASC
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
        """),
        {"limit": CONSUMER_BATCH_SIZE * 2}  # Fetch extra in case some have unmet deps
    ).fetchall()

    if not jobs:
        return 0

    job_ids = [row[0] for row in jobs]
    job_objects = db.query(JobQueue).filter(JobQueue.id.in_(job_ids)).all()

    processed = 0
    for job in job_objects:
        if processed >= CONSUMER_BATCH_SIZE:
            break

        # Check dependency
        if not _dependency_met(job, db):
            continue

        # Lock the job
        job.status = "RUNNING"
        job.locked_by = WORKER_ID
        job.locked_at = datetime.utcnow()
        job.attempts += 1
        db.commit()

        emit(EventType.HUNTER, f"pipeline:enrich:{job.enricher}:started", EventStatus.PENDING,
             detail=f"Entity {job.entity_id}", entity_id=job.entity_id)

        # Run the enricher
        try:
            entity = db.query(Entity).filter(Entity.id == job.entity_id).first()
            if not entity:
                job.status = "REJECTED"
                job.last_error = "Entity not found"
                job.completed_at = datetime.utcnow()
                db.commit()
                continue

            # Mark entity as running
            entity.enrichment_status = "running"
            db.commit()

            result = _run_enricher(job.enricher, entity, db)

            if result:
                job.status = "SUCCESS"
                job.completed_at = datetime.utcnow()
                job.locked_by = None
                job.locked_at = None
                db.commit()
                emit(EventType.HUNTER, f"pipeline:enrich:{job.enricher}:success", EventStatus.SUCCESS,
                     detail=f"Entity {job.entity_id} '{entity.name}'", entity_id=job.entity_id)
            else:
                # Enricher returned False — no data written but not an error
                # Mark as success (enricher ran, just had nothing to add)
                job.status = "SUCCESS"
                job.completed_at = datetime.utcnow()
                job.locked_by = None
                job.locked_at = None
                db.commit()

            processed += 1

        except Exception as e:
            db.rollback()
            error_msg = str(e)[:500]
            logger.error(f"Job {job.id} ({job.enricher}) failed for entity {job.entity_id}: {error_msg}")

            # Reload job after rollback
            job = db.query(JobQueue).filter(JobQueue.id == job.id).first()
            if job:
                if job.attempts >= job.max_attempts:
                    job.status = "REJECTED"
                    emit(EventType.HUNTER, f"pipeline:enrich:{job.enricher}:rejected", EventStatus.ERROR,
                         detail=f"Entity {job.entity_id} — max attempts reached: {error_msg[:200]}",
                         entity_id=job.entity_id)
                else:
                    job.status = "FAILED"
                    emit(EventType.HUNTER, f"pipeline:enrich:{job.enricher}:failed", EventStatus.ERROR,
                         detail=f"Entity {job.entity_id} attempt {job.attempts}: {error_msg[:200]}",
                         entity_id=job.entity_id)
                job.last_error = error_msg
                job.locked_by = None
                job.locked_at = None
                db.commit()

            processed += 1

        # Brief pause between jobs to not hammer external APIs
        time.sleep(0.5)

    # After processing, update enrichment_status for affected entities
    _update_entity_statuses(db, [j.entity_id for j in job_objects[:processed]])

    return processed


def _run_enricher(enricher_name: str, entity: Entity, db: Session) -> bool:
    """Run a single enricher function by name. Returns True if data was written."""
    from agents.enrichers.pipeline import ENRICHERS

    for enricher_info in ENRICHERS:
        if enricher_info["source_id"] == enricher_name:
            return enricher_info["function"](entity, db)

    logger.warning(f"Enricher '{enricher_name}' not found in registry")
    return False


def _update_entity_statuses(db: Session, entity_ids: list[int]):
    """Update enrichment_status for entities based on their job queue state."""
    for eid in set(entity_ids):
        try:
            entity = db.query(Entity).filter(Entity.id == eid).first()
            if not entity:
                continue

            # Count job states for this entity
            total = db.query(JobQueue).filter(JobQueue.entity_id == eid).count()
            done = db.query(JobQueue).filter(
                JobQueue.entity_id == eid,
                JobQueue.status.in_(["SUCCESS", "REJECTED"]),
            ).count()
            running = db.query(JobQueue).filter(
                JobQueue.entity_id == eid,
                JobQueue.status == "RUNNING",
            ).count()

            if total == 0:
                entity.enrichment_status = "idle"
            elif done >= total:
                entity.enrichment_status = "complete"
            elif running > 0:
                entity.enrichment_status = "running"
            else:
                entity.enrichment_status = "idle"

            # Update heat score after enrichment progress
            from agents.enrichers.pipeline import compute_heat_score
            entity.heat_score = compute_heat_score(entity)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"Failed to update status for entity {eid}: {e}")


# ─── Queue Manager ──────────────────────────────────────────────────

def sweep_stale_locks(db: Session) -> int:
    """Find jobs locked for too long and reset them to FAILED for retry."""
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_LOCK_MINUTES)
    stale = db.query(JobQueue).filter(
        JobQueue.status == "RUNNING",
        JobQueue.locked_at < cutoff,
    ).all()

    count = 0
    for job in stale:
        logger.warning(f"Stale lock: job {job.id} ({job.enricher}) for entity {job.entity_id}, "
                       f"locked by {job.locked_by} at {job.locked_at}")
        if job.attempts >= job.max_attempts:
            job.status = "REJECTED"
            job.last_error = f"Stale lock after {job.attempts} attempts"
            job.completed_at = datetime.utcnow()
        else:
            job.status = "FAILED"
            job.last_error = f"Stale lock (was locked by {job.locked_by})"
        job.locked_by = None
        job.locked_at = None
        count += 1

    if count > 0:
        db.commit()
        emit(EventType.SYSTEM, "pipeline:sweep:stale", EventStatus.SUCCESS,
             detail=f"Reset {count} stale-locked jobs")
        logger.info(f"Swept {count} stale locks")

    return count


def retry_failed_jobs(db: Session) -> int:
    """Reset FAILED jobs back to PENDING for retry (respects max_attempts)."""
    failed = db.query(JobQueue).filter(
        JobQueue.status == "FAILED",
        JobQueue.attempts < JobQueue.max_attempts,
    ).all()

    count = 0
    for job in failed:
        job.status = "PENDING"
        job.locked_by = None
        job.locked_at = None
        count += 1

    if count > 0:
        db.commit()
        emit(EventType.HUNTER, "pipeline:retry", EventStatus.SUCCESS,
             detail=f"Retried {count} failed jobs")

    return count


def get_queue_stats(db: Session) -> dict:
    """Get current queue statistics for the Ops dashboard.

    Returns aggregate counts per-enricher AND per-enricher-per-county
    so the Ops page can expand each enricher row into a county breakdown.
    """
    rows = db.execute(sa.text(
        "SELECT status, COUNT(*) as cnt FROM job_queue GROUP BY status"
    )).fetchall()
    status_counts = {row[0]: row[1] for row in rows}

    # Per-enricher aggregate
    enricher_rows = db.execute(sa.text(
        "SELECT enricher, status, COUNT(*) as cnt FROM job_queue "
        "GROUP BY enricher, status ORDER BY enricher"
    )).fetchall()
    enricher_stats: dict[str, dict[str, int]] = {}
    for row in enricher_rows:
        enricher_stats.setdefault(row[0], {})[row[1]] = row[2]

    # Per-enricher per-county breakdown (single query for efficiency)
    by_county_rows = db.execute(sa.text(
        "SELECT jq.enricher, e.county, jq.status, COUNT(*) as cnt "
        "FROM job_queue jq "
        "LEFT JOIN entities e ON jq.entity_id = e.id "
        "WHERE e.county IS NOT NULL "
        "GROUP BY jq.enricher, e.county, jq.status"
    )).fetchall()
    enricher_by_county: dict[str, dict[str, dict[str, int]]] = {}
    for enricher, county, status, cnt in by_county_rows:
        enricher_by_county.setdefault(enricher, {}).setdefault(county, {})[status] = cnt

    # Recent failures
    recent_failures = db.execute(sa.text(
        "SELECT jq.id, jq.entity_id, jq.enricher, jq.last_error, jq.attempts, "
        "e.name as entity_name "
        "FROM job_queue jq LEFT JOIN entities e ON jq.entity_id = e.id "
        "WHERE jq.status IN ('FAILED', 'REJECTED') "
        "ORDER BY jq.id DESC LIMIT 20"
    )).fetchall()
    failures = [{
        "job_id": r[0], "entity_id": r[1], "enricher": r[2],
        "error": r[3], "attempts": r[4], "entity_name": r[5],
    } for r in recent_failures]

    total = sum(status_counts.values())

    return {
        "total_jobs": total,
        "status_counts": status_counts,
        "enricher_stats": enricher_stats,
        "enricher_by_county": enricher_by_county,
        "recent_failures": failures,
        "worker_id": WORKER_ID,
    }


# ─── Background Loops ───────────────────────────────────────────────

def _consumer_loop():
    """Background thread: continuously consume jobs from the queue."""
    from services.registry import register, heartbeat

    register("job_consumer", capabilities={
        "worker_id": WORKER_ID,
        "batch_size": CONSUMER_BATCH_SIZE,
        "poll_interval": CONSUMER_POLL_INTERVAL,
    }, detail="Starting job consumer")

    logger.info(f"Job consumer started (worker={WORKER_ID})")

    while True:
        db = SessionLocal()
        try:
            processed = consume_batch(db)
            if processed > 0:
                # Get pending count for heartbeat
                pending = db.query(JobQueue).filter(JobQueue.status == "PENDING").count()
                heartbeat("job_consumer",
                          detail=f"Processed {processed} jobs, {pending} pending")
            else:
                pending = db.query(JobQueue).filter(JobQueue.status == "PENDING").count()
                heartbeat("job_consumer",
                          detail=f"Idle, {pending} pending" if pending > 0 else "Idle, queue empty")
        except Exception as e:
            logger.error(f"Consumer loop error: {e}")
            heartbeat("job_consumer", status="degraded", detail=f"Error: {str(e)[:100]}")
        finally:
            db.close()

        time.sleep(CONSUMER_POLL_INTERVAL)


def _manager_loop():
    """Background thread: periodic queue maintenance."""
    from services.registry import register, heartbeat

    register("queue_manager", capabilities={
        "stale_lock_minutes": STALE_LOCK_MINUTES,
        "max_attempts": MAX_ATTEMPTS,
    }, detail="Starting queue manager")

    logger.info("Queue manager started")

    while True:
        time.sleep(60)  # Run every 60 seconds

        db = SessionLocal()
        try:
            swept = sweep_stale_locks(db)
            retried = retry_failed_jobs(db)

            # Also backfill any LEADs that don't have jobs yet
            backfilled = produce_jobs_for_all_leads(db)

            detail_parts = []
            if swept:
                detail_parts.append(f"{swept} stale swept")
            if retried:
                detail_parts.append(f"{retried} retried")
            if backfilled:
                detail_parts.append(f"{backfilled} backfilled")

            detail = ", ".join(detail_parts) if detail_parts else "All clear"
            heartbeat("queue_manager", detail=detail)

        except Exception as e:
            logger.error(f"Queue manager error: {e}")
            heartbeat("queue_manager", status="degraded", detail=f"Error: {str(e)[:100]}")
        finally:
            db.close()


def start_job_consumer():
    """Start the job consumer as a daemon thread."""
    thread = threading.Thread(target=_consumer_loop, daemon=True, name="job-consumer")
    thread.start()
    return thread


def start_queue_manager():
    """Start the queue manager as a daemon thread."""
    thread = threading.Thread(target=_manager_loop, daemon=True, name="queue-manager")
    thread.start()
    return thread
