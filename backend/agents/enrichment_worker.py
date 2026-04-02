"""
Continuous Enrichment Worker

Background worker that continuously enriches LEAD entities.
Runs all registered enrichers on LEADs that aren't fully enriched yet.

Each cycle:
1. Find LEADs with enrichment_status != "complete"
2. Run all applicable enrichers
3. Update heat score
4. Update enrichment_status

Runs as a background thread.
"""

import logging
import time
import threading

from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import Entity
from agents.enrichers.pipeline import run_lead_enrichment
from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)

POLL_INTERVAL = 45  # seconds between enrichment cycles
BATCH_SIZE = 25  # leads to enrich per cycle


def run_enrichment_cycle(db: Session) -> int:
    """Run one cycle of enrichment. Returns count of leads enriched."""
    # Find LEADs that need enrichment
    leads = db.query(Entity).filter(
        Entity.pipeline_stage == "LEAD",
        Entity.enrichment_status.in_(["idle", "error"]),
    ).order_by(Entity.created_at).limit(BATCH_SIZE).all()

    if not leads:
        return 0

    enriched = 0
    for entity in leads:
        try:
            completed = run_lead_enrichment(entity, db)
            if completed:
                enriched += 1
        except Exception as e:
            logger.error(f"Enrichment failed for entity {entity.id}: {e}")
            try:
                entity.enrichment_status = "error"
                db.commit()
            except Exception:
                db.rollback()

    return enriched


def run_enrichment_loop():
    """Background loop: continuously enrich LEADs."""
    from services.registry import register, heartbeat

    register("enrichment_worker", capabilities={
        "poll_interval": POLL_INTERVAL,
        "batch_size": BATCH_SIZE,
    }, detail="Starting continuous enrichment worker")

    logger.info("Starting continuous enrichment worker...")

    while True:
        db = SessionLocal()
        try:
            pending = db.query(Entity).filter(
                Entity.pipeline_stage == "LEAD",
                Entity.enrichment_status.in_(["idle", "error"]),
            ).count()

            if pending > 0:
                enriched = run_enrichment_cycle(db)
                heartbeat("enrichment_worker",
                          detail=f"Enriched {enriched}, {pending} pending")
                if enriched > 0:
                    emit(EventType.HUNTER, "enrichment_cycle", EventStatus.SUCCESS,
                         detail=f"{enriched} leads enriched, {pending - enriched} remaining")
            else:
                heartbeat("enrichment_worker", detail="Idle, all leads enriched")

        except Exception as e:
            logger.error(f"Enrichment cycle error: {e}")
            heartbeat("enrichment_worker", status="degraded", detail=f"Error: {str(e)[:100]}")
        finally:
            db.close()

        time.sleep(POLL_INTERVAL)


def start_enrichment_worker():
    """Start the enrichment worker as a daemon thread."""
    thread = threading.Thread(target=run_enrichment_loop, daemon=True)
    thread.start()
    return thread
