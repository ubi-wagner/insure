"""
Enrichment Pipeline — 5-Stage Architecture

Stages:
  TARGET → LEAD → OPPORTUNITY → CUSTOMER → ARCHIVED

Auto-advance:
  TARGET → LEAD: When geocoding succeeds (Census batch or Nominatim fallback)

  Everything else is manual (user clicks Promote/Convert).

Enrichers:
  All enrichers run on LEAD stage continuously.
  Each enricher populates real data and documents.
  Each contributes to heat scoring (cold/warm/hot).
  No enricher changes pipeline stage.
"""

import logging

from sqlalchemy.orm import Session

from database.models import Entity
from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)

# All enrichers registered here — they all run on LEAD stage
ENRICHERS: list[dict] = []


def register_enricher(source_id: str, requires: list[str] | None = None):
    """Decorator to register an enricher. All enrichers run on LEAD stage."""
    def decorator(func):
        ENRICHERS.append({
            "source_id": source_id,
            "function": func,
            "requires": requires or [],
        })
        return func
    return decorator


def run_lead_enrichment(entity: Entity, db: Session) -> list[str]:
    """Run all applicable enrichers on a LEAD.

    Skips enrichers that have already run. Returns list of source_ids that ran.
    """
    if entity.pipeline_stage not in ("LEAD", "OPPORTUNITY", "CUSTOMER"):
        return []

    completed = []

    # Mark as running
    entity.enrichment_status = "running"
    db.commit()

    for enricher_info in ENRICHERS:
        source_id = enricher_info["source_id"]
        existing_sources = entity.enrichment_sources or {}

        # Skip if already enriched from this source
        if source_id in existing_sources:
            continue

        # Check prerequisites
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

    # Update enrichment status
    sources = entity.enrichment_sources or {}
    total_enrichers = len(ENRICHERS)
    completed_enrichers = sum(1 for e in ENRICHERS if e["source_id"] in sources)

    if completed_enrichers >= total_enrichers:
        entity.enrichment_status = "complete"
    elif completed:
        entity.enrichment_status = "idle"  # Made progress, will continue later
    else:
        entity.enrichment_status = "idle"

    # Compute and store heat score
    entity.heat_score = compute_heat_score(entity)
    db.commit()

    return completed


def compute_heat_score(entity: Entity) -> str:
    """Compute heat score: cold, warm, or hot.

    Based on data completeness + risk indicators, not arbitrary thresholds.
    """
    chars = entity.characteristics or {}
    sources = entity.enrichment_sources or {}
    score = 0

    # Data completeness
    if chars.get("dor_owner"):
        score += 5
    if chars.get("dor_market_value"):
        score += 5
    if chars.get("dor_construction_class"):
        score += 3
    if chars.get("dor_num_units"):
        score += 3

    # Flood risk
    flood_risk = chars.get("flood_risk", "")
    if flood_risk in ("extreme", "high"):
        score += 15
    elif flood_risk == "moderate_high":
        score += 8

    # Association data
    if chars.get("dbpr_managing_entity"):
        score += 5
    if chars.get("dbpr_condo_name"):
        score += 3
    if chars.get("payment_is_delinquent"):
        score += 10  # Financially stressed = opportunity

    # Contact availability
    contacts = entity.contacts if hasattr(entity, 'contacts') else []
    if any(c.email for c in contacts):
        score += 10
    elif len(contacts) > 0:
        score += 5

    # Insurance intel
    if chars.get("carrier"):
        score += 10
    if chars.get("on_citizens"):
        score += 15  # Citizens = hot by definition
    if chars.get("premium"):
        score += 5
    if chars.get("decision_maker"):
        score += 5

    # User-uploaded documents
    if chars.get("has_user_intel"):
        score += 15

    # Sunbiz data — officers identified = decision makers known
    if "sunbiz_bulk" in sources:
        score += 5
    if chars.get("sunbiz_registered_agent"):
        score += 3  # Management company identified

    # SIRS compliance risk — non-compliant associations are actively shopping
    if chars.get("sirs_completed") is False:
        score += 12  # Compliance deadline pressure
    elif chars.get("sirs_compliance_risk") == "HIGH":
        score += 15  # Imminent special assessments

    # OIR market intelligence — hard market = more opportunity
    market_hardness = chars.get("oir_market_hardness", "")
    if market_hardness == "hard":
        score += 8
    elif market_hardness == "moderate":
        score += 3

    # Building report data (DBPR)
    if chars.get("dbpr_current_assessment"):
        score += 3  # Financial data available

    # Premium estimate available = ready for quoting
    if chars.get("oir_estimated_premium_range"):
        score += 5

    # Classify
    if score >= 35:
        return "hot"
    elif score >= 18:
        return "warm"
    return "cold"


def check_target_to_lead(entity: Entity, db: Session) -> bool:
    """Check if a TARGET should auto-advance to LEAD.

    Only condition: entity has been geocoded (latitude is set).
    """
    if entity.pipeline_stage != "TARGET":
        return False

    if entity.latitude is not None:
        entity.pipeline_stage = "LEAD"
        entity.enrichment_status = "idle"
        db.commit()
        emit(EventType.DB_OPERATION, "auto_advance", EventStatus.SUCCESS,
             detail=f"'{entity.name}': TARGET → LEAD (geocoded)",
             entity_id=entity.id)
        return True

    return False


# Import enrichers to trigger their @register_enricher decorators
def _load_enrichers():
    modules = [
        "fema_flood",           # FEMA flood zone (real API)
        "property_appraiser",   # County PA GIS lookup + direct parcel links
        "dbpr_bulk",            # DBPR condo CSV (managing entity, project number)
        "dbpr_payments",        # DBPR payment history (delinquency)
        "dbpr_sirs",            # DBPR SIRS compliance (structural reserve studies)
        "dbpr_building",        # DBPR building reports (stories, units, assessments)
        "cam_license",          # CAM license cross-reference
        "sunbiz_bulk",          # Sunbiz bulk data (quarterly corporate extract)
        "dor_nal",              # DOR NAL cross-reference (supplemental)
        "citizens_insurance",   # Citizens insurance likelihood + swap opportunity
        "fdot_parcels",         # FDOT statewide parcel API
        "oir_market",           # OIR market intelligence (rates, carriers, wind tiers)
    ]
    for module in modules:
        try:
            __import__(f"agents.enrichers.{module}")
        except Exception as e:
            logger.warning(f"Failed to load {module} enricher: {e}")


_load_enrichers()
