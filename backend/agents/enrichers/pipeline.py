"""
Enrichment Pipeline Orchestrator

Pipeline stages and auto-advancement:

  NEW (from Overpass)
    → auto-enrich: FEMA flood + FDOT parcels + county PA
    → when complete: auto-advance to ENRICHED

  ENRICHED (data populated, waiting for Jason)
    → Jason clicks "Investigate"

  INVESTIGATING (Jason triggered)
    → auto-enrich: Sunbiz (officers, registered agent) + AI Kill & Cook
    → when complete: auto-advance to RESEARCHED

  RESEARCHED (investigation complete, waiting for Jason)
    → Jason clicks "Target"

  TARGETED (Jason triggered)
    → auto-enrich: DBPR condo + CAM lookup
    → stays TARGETED (Jason reviews and decides)
    → Jason clicks "Opportunity" to create full CRM profile

  OPPORTUNITY → CUSTOMER (manual gates)
"""

import logging

from sqlalchemy.orm import Session

from database.models import Entity
from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)

# Registry of enrichers by trigger stage
STAGE_ENRICHERS: dict[str, list] = {}

# Auto-advance rules: when all required sources complete, move to next stage
AUTO_ADVANCE = {
    "NEW": {
        "required_sources": ["fema_flood", "fdot_parcels"],  # PA is optional (many fail)
        "next_stage": "ENRICHED",
    },
    "INVESTIGATING": {
        "required_sources": ["sunbiz"],  # AI Kill & Cook tracked separately
        "next_stage": "RESEARCHED",
    },
}


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


def _check_auto_advance(entity: Entity, stage: str, db: Session):
    """Check if enrichment completion should auto-advance the entity's stage."""
    rule = AUTO_ADVANCE.get(stage)
    if not rule:
        return

    # Only advance if entity is still in the triggering stage
    if entity.pipeline_stage != stage:
        return

    sources = entity.enrichment_sources or {}
    required = rule["required_sources"]
    if all(s in sources for s in required):
        next_stage = rule["next_stage"]
        entity.pipeline_stage = next_stage
        db.commit()
        emit(EventType.DB_OPERATION, "auto_advance", EventStatus.SUCCESS,
             detail=f"'{entity.name}': {stage} → {next_stage} (enrichment complete)",
             entity_id=entity.id)
        logger.info(f"Auto-advanced entity {entity.id} from {stage} to {next_stage}")


def run_enrichment_for_stage(entity: Entity, stage: str, db: Session) -> list[str]:
    """Run all enrichers for a stage, then check auto-advance.

    Returns list of source_ids that ran successfully.
    """
    enrichers = STAGE_ENRICHERS.get(stage, [])
    if not enrichers:
        return []

    completed = []

    for enricher_info in enrichers:
        source_id = enricher_info["source_id"]
        existing_sources = entity.enrichment_sources or {}

        if source_id in existing_sources:
            continue

        missing = [r for r in enricher_info["requires"] if r not in existing_sources]
        if missing:
            continue

        try:
            emit(EventType.HUNTER, f"enrich_{source_id}_start", EventStatus.PENDING,
                 detail=f"Starting {source_id} for '{entity.name}'", entity_id=entity.id)

            result = enricher_info["function"](entity, db)
            if result:
                db.commit()
                completed.append(source_id)
                logger.info(f"Enrichment {source_id} completed for entity {entity.id}")
        except Exception as e:
            db.rollback()
            logger.error(f"Enrichment {source_id} failed for entity {entity.id}: {e}")
            emit(EventType.HUNTER, f"enrich_{source_id}", EventStatus.ERROR,
                 detail=str(e)[:200], entity_id=entity.id)

    # Check if we should auto-advance
    if completed:
        _check_auto_advance(entity, stage, db)

    return completed


def run_on_new_lead(entity: Entity, db: Session) -> list[str]:
    """Run NEW-stage enrichments (FEMA, FDOT, PA). Auto-advances to ENRICHED."""
    return run_enrichment_for_stage(entity, "NEW", db)


def run_on_investigate(entity: Entity, db: Session) -> list[str]:
    """Run INVESTIGATING-stage enrichments (Sunbiz). Auto-advances to RESEARCHED."""
    return run_enrichment_for_stage(entity, "INVESTIGATING", db)


def run_on_target(entity: Entity, db: Session) -> list[str]:
    """Run TARGETED-stage enrichments (DBPR)."""
    return run_enrichment_for_stage(entity, "TARGETED", db)


# Import enrichers to trigger their @register_enricher decorators
def _load_enrichers():
    modules = [
        "fema_flood",           # NEW: FEMA flood zone
        "fdot_parcels",         # NEW: FDOT/DOR statewide parcels
        "property_appraiser",   # NEW: County PA GIS lookup
        "dbpr_bulk",            # NEW: DBPR bulk CSV (condo name, units, managing entity, financials)
        "dbpr_payments",        # NEW: DBPR payment history (delinquency, financial stress)
        "sunbiz",               # INVESTIGATING: Sunbiz HOA/condo search
        "dbpr_condo",           # TARGETED: DBPR condo registry + CAM license
    ]
    for module in modules:
        try:
            __import__(f"agents.enrichers.{module}")
        except Exception as e:
            logger.warning(f"Failed to load {module} enricher: {e}")


_load_enrichers()
