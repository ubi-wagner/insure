"""
Enrichment Pipeline — 8-stage architecture, master-only enrichment.

Stages:
    TARGET → LEAD → VETTED → ANALYZED → VALIDATED → OPPORTUNITY → CUSTOMER → ARCHIVED
    └─seed─┘└qual─┘└─aggr──┘└enrich───┘└zillow/vrbo──── manual ─────────────────────┘

Enrichment rules:
  * Runs ONLY on VETTED masters (parent_id IS NULL). Sibling unit
    parcels inherit their building's data via the master and skip
    enrichment entirely. Enforced centrally in
    services/job_queue._run_enricher.
  * Per-stage gating is handled by the job queue's depends_on chain
    (see services/job_queue.ENRICHER_CHAIN). Order in _load_enrichers
    below is advisory.
  * "First source wins" is the default merge rule
    (agents/enrichers/__init__.update_characteristics). Authoritative
    enrichers can declare an `overwrite={...}` set for keys they own.

──────────────────────────────────────────────────────────────────────
WHAT EACH ENRICHER WRITES PER VETTED MASTER
──────────────────────────────────────────────────────────────────────

  name_parse           stories, units_from_name, year_built (low-confidence
                       fallback parsed from entity.name; overwritable
                       by DBPR Building when the scrape works)

  fema_flood           flood_zone, flood_risk, flood_sfha, flood_base_elev
                       (FEMA NFHL by lat/lng — exact coordinate query)

  property_appraiser   pa_owner, pa_assessed_value, pa_year_built,
                       pa_building_sqft, pa_use_code, pa_parcel_id,
                       pa_lookup_url (county PA GIS via ArcGIS REST,
                       lat/lng query; URL-only fallback for non-REST counties)

  dbpr_bulk            dbpr_condo_name, dbpr_project_number,
                       dbpr_managing_entity, dbpr_official_units,
                       dbpr_managing_entity_address (address-token match
                       against bulk DBPR condo CSVs)

  dbpr_payments        payment_total_pending, payment_is_delinquent,
                       payment_years_delinquent (exact project_number
                       lookup in payment-history CSV)

  dbpr_kfi             dbpr_operating_fund_balance, dbpr_reserve_ratio,
                       dbpr_financial_distress, dbpr_collections_issue,
                       dbpr_reserve_underfunded (managing-entity name OR
                       project-number lookup; fuzzy on legal-suffix
                       normalisation: "INC LLC CORP ASSOC..." stripped)

  dbpr_sirs            sirs_completed, sirs_compliance_risk, sirs_engineer,
                       sirs_needs_manual_verification (xlsx lookup —
                       defaults to compliance_risk=HIGH when not found)

  dbpr_building        dbpr_building_count, dbpr_max_stories, stories
                       (overwrite — authoritative), dbpr_building_units,
                       dbpr_current_assessment, dbpr_contact_*
                       (live portal scrape; saves lookup_url + retry flag
                       on 403)

  dbpr_noic            noic_match, noic_developer_name, noic_status
                       (address-token match against NOIC list)

  cam_license          cam_license_number, cam_license_active,
                       cam_license_warning (last-name + first-initial
                       fuzzy match against local CAM CSV)

  sunbiz_bulk          sunbiz_corp_name, sunbiz_registered_agent,
                       sunbiz_officers, sunbiz_filing_status
                       (progressive name match: exact → containment →
                       60% token overlap with legal suffixes stripped)

  citizens_insurance   citizens_likelihood (0-100), citizens_candidate,
                       citizens_estimated_premium, citizens_swap_opportunity
                       (heuristic from county penetration + flood + TIV
                       + construction + age — no external lookup)

  oir_market           oir_estimated_premium_low/high, oir_market_hardness,
                       oir_carrier_options, oir_wind_tier (hardcoded 2025
                       OIR rate tables — county / construction / wind tier)

  cream_score          cream_score (0-100), cream_tier (platinum/gold/
                       silver/bronze/prospect), cream_factors[] — runs
                       last via depends_on=__all__

──────────────────────────────────────────────────────────────────────
DEPRECATED (file kept on disk, NOT loaded into the chain)
──────────────────────────────────────────────────────────────────────
  dor_nal              Seeder writes the same DOR fields at TARGET
                       creation. Re-running the same CSV at enrichment
                       time was pure duplication.
  fdot_parcels         FDOT FeatureServer is backed by the same DOR tax
                       roll. Seeder already has the data; lat/lng query
                       at enrichment was redundant + slow.
  dbpr_condo           Web-scrapes the DBPR license portal for the same
                       CAM verification cam_license already does from a
                       local CSV. Slower, fragile (frequent 403s).
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
    """Run all applicable enrichers on a VETTED master.

    Enrichment runs at the master level only — sibling parcels (those
    with parent_id set) inherit nothing. The master's rolled-up TIV /
    unit / story numbers are the source of truth for cream scoring.

    Returns list of source_ids that ran.
    """
    # Children skip enrichment entirely — only masters get analyzed.
    if entity.parent_id is not None:
        return []
    if entity.pipeline_stage not in (
        "VETTED", "ANALYZED", "VALIDATED",
        "OPPORTUNITY", "CUSTOMER",
    ):
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
    On promotion, produces enrichment jobs via the job queue.
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

        # Produce enrichment jobs for this new LEAD
        try:
            from services.job_queue import produce_jobs_for_entity
            produce_jobs_for_entity(entity.id, db)
        except Exception as e:
            logger.warning(f"Failed to produce jobs for entity {entity.id}: {e}")

        return True

    return False


# Active enricher chain — runs on VETTED masters only (parent_id IS NULL,
# enforced centrally in services/job_queue._run_enricher).
#
# Every enricher in this list adds its own writes to master.characteristics
# and contributes to cream_score's final tier. Order is advisory; the
# job queue's depends_on chain enforces actual sequencing.
#
# Deprecated (file kept on disk for archeology, NOT loaded):
#   - dor_nal      Seeder writes the same DOR fields at TARGET creation,
#                  so this enricher just re-reads the CSV and overwrites
#                  with the same values. Pure duplicate.
#   - fdot_parcels Same data source as DOR via FDOT FeatureServer; lat/lng
#                  query that returns the parcel row the seeder already
#                  ingested. Pure duplicate.
#   - dbpr_condo   Web-scrapes the DBPR license portal for the same CAM
#                  data cam_license.py already has in a local CSV. Slow,
#                  fragile (403s), and writes the same fields.
def _load_enrichers():
    modules = [
        "name_parse",           # Regex stories / units / year from entity.name
        "fema_flood",           # FEMA NFHL — flood zone, SFHA flag, base elev
        "property_appraiser",   # County PA GIS — assessed value, lookup URLs
        "dbpr_bulk",            # DBPR condo CSV — project_number, managing_entity
        "dbpr_payments",        # DBPR payment history — delinquency flags
        "dbpr_kfi",             # DBPR Key Financial Indicators — distress flags
        "dbpr_sirs",            # DBPR SIRS — structural reserve study compliance
        "dbpr_building",        # DBPR building report portal — stories, units
        "dbpr_noic",            # DBPR Notice of Intended Conversion — new condos
        "cam_license",          # CAM license CSV — manager license verification
        "sunbiz_bulk",          # Sunbiz CSV — corp officers, registered agent
        "citizens_insurance",   # Heuristic — Citizens-likelihood + swap signal
        "oir_market",           # OIR rate tables — premium estimate + market hardness
        "cream_score",          # Final scoring — runs last via __all__ dependency
    ]
    for module in modules:
        try:
            __import__(f"agents.enrichers.{module}")
        except Exception as e:
            logger.warning(f"Failed to load {module} enricher: {e}")


_load_enrichers()
