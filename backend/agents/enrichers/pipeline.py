"""
Enrichment Pipeline Orchestrator

Runs enrichers based on pipeline stage transitions and available data.
Each enricher is idempotent — safe to re-run if source data changes.
"""

import logging

from sqlalchemy.orm import Session

from database.models import Entity
from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)


# Registry of enrichers by trigger stage
# Format: {stage: [(source_id, enricher_function, requires_data)]}
STAGE_ENRICHERS: dict[str, list] = {}


def register_enricher(stage: str, source_id: str, requires: list[str] | None = None):
    """Decorator to register an enricher for a pipeline stage."""
    def decorator(func):
        if stage not in STAGE_ENRICHERS:
            STAGE_ENRICHERS[stage] = []
        STAGE_ENRICHERS[stage].append({
            "source_id": source_id,
            "function": func,
            "requires": requires or [],
        })
        return func
    return decorator


def run_enrichment_for_stage(entity: Entity, stage: str, db: Session) -> list[str]:
    """Run all enrichers appropriate for the given pipeline stage.

    Returns list of source_ids that ran successfully.
    """
    enrichers = STAGE_ENRICHERS.get(stage, [])
    if not enrichers:
        return []

    completed = []
    existing_sources = entity.enrichment_sources or {}

    for enricher_info in enrichers:
        source_id = enricher_info["source_id"]

        # Skip if already enriched from this source
        if source_id in existing_sources:
            logger.debug(f"Skipping {source_id} for entity {entity.id} — already enriched")
            continue

        # Check prerequisites
        missing = [r for r in enricher_info["requires"] if r not in existing_sources]
        if missing:
            logger.debug(f"Skipping {source_id} — missing prerequisites: {missing}")
            continue

        try:
            emit(EventType.HUNTER, f"enrich_{source_id}_start", EventStatus.PENDING,
                 detail=f"Starting {source_id} for '{entity.name}'", entity_id=entity.id)

            result = enricher_info["function"](entity, db)
            if result:
                completed.append(source_id)
                logger.info(f"Enrichment {source_id} completed for entity {entity.id}")
        except Exception as e:
            logger.error(f"Enrichment {source_id} failed for entity {entity.id}: {e}")
            emit(EventType.HUNTER, f"enrich_{source_id}", EventStatus.ERROR,
                 detail=str(e)[:200], entity_id=entity.id)

    return completed


def run_on_new_lead(entity: Entity, db: Session) -> list[str]:
    """Run enrichments appropriate for newly discovered leads."""
    return run_enrichment_for_stage(entity, "NEW", db)


def run_on_candidate(entity: Entity, db: Session) -> list[str]:
    """Run enrichments when a lead is promoted to CANDIDATE."""
    return run_enrichment_for_stage(entity, "CANDIDATE", db)


def run_on_target(entity: Entity, db: Session) -> list[str]:
    """Run enrichments when a lead is promoted to TARGET."""
    return run_enrichment_for_stage(entity, "TARGET", db)


# Import enrichers to trigger their @register_enricher decorators
def _load_enrichers():
    """Import all enricher modules so they register themselves."""
    modules = [
        "fema_flood",           # NEW stage: FEMA flood zone (coordinate-based)
        "fdot_parcels",         # NEW stage: FDOT/DOR statewide parcels (coordinate-based)
        "property_appraiser",   # NEW stage: County PA GIS lookup (coordinate-based)
        "sunbiz",               # CANDIDATE stage: Sunbiz HOA/condo search
        "dbpr_condo",           # TARGET stage: DBPR condo registry + CAM lookup
    ]
    for module in modules:
        try:
            __import__(f"agents.enrichers.{module}")
        except ImportError as e:
            logger.warning(f"Failed to load {module} enricher: {e}")


_load_enrichers()
