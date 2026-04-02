"""
Overpass Association Worker

Background worker that continuously matches TARGET entities (NAL parcels)
to Overpass cached buildings to get coordinates + building metadata.

Match criteria:
1. Address match: NAL PHY_ADDR1 ↔ OsmBuilding address (normalized)
2. Name match: NAL OWN_NAME or entity name ↔ OsmBuilding name
3. County + proximity if coordinates are available

On successful match:
- Sets entity.osm_building_id → the matched building
- Copies lat/lon from OsmBuilding to Entity
- Copies stories, building_type from OsmBuilding to characteristics
- Advances pipeline_stage from TARGET → LEAD
- Triggers enrichment pipeline

Runs as a background thread, processing targets in batches.
"""

import logging
import re
import time
import threading

from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import Entity, OsmBuilding
from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds between association attempts
BATCH_SIZE = 100  # targets to process per cycle


def _normalize_address(addr: str) -> str:
    """Normalize address for matching."""
    if not addr:
        return ""
    addr = addr.upper().strip()
    addr = re.sub(r'\s*(APT|UNIT|STE|SUITE|#)\s*\S*$', '', addr)
    addr = re.sub(r'\bSTREET\b', 'ST', addr)
    addr = re.sub(r'\bAVENUE\b', 'AVE', addr)
    addr = re.sub(r'\bBOULEVARD\b', 'BLVD', addr)
    addr = re.sub(r'\bDRIVE\b', 'DR', addr)
    addr = re.sub(r'\bLANE\b', 'LN', addr)
    addr = re.sub(r'\bROAD\b', 'RD', addr)
    addr = re.sub(r'\bCOURT\b', 'CT', addr)
    addr = re.sub(r'\bCIRCLE\b', 'CIR', addr)
    addr = re.sub(r'\bHIGHWAY\b', 'HWY', addr)
    addr = re.sub(r'\bNORTH\b', 'N', addr)
    addr = re.sub(r'\bSOUTH\b', 'S', addr)
    addr = re.sub(r'\bEAST\b', 'E', addr)
    addr = re.sub(r'\bWEST\b', 'W', addr)
    addr = re.sub(r'\s+', ' ', addr).strip()
    return addr


def _try_associate(entity: Entity, db: Session) -> bool:
    """Try to match a TARGET entity to an Overpass building.

    Returns True if association was successful.
    """
    entity_addr = _normalize_address(entity.address or "")
    entity_name = (entity.name or "").upper().strip()
    county = entity.county

    if not entity_addr and not entity_name:
        return False

    # Query Overpass buildings in the same county
    query = db.query(OsmBuilding).filter(
        OsmBuilding.promoted_entity_id.is_(None),  # Not already matched
    )
    if county:
        query = query.filter(OsmBuilding.county == county)

    # Try address match first
    if entity_addr:
        # Extract street number + name for matching
        buildings = query.limit(5000).all()
        for building in buildings:
            bldg_addr = _normalize_address(building.address or "")
            if not bldg_addr:
                continue

            # Exact normalized match
            if entity_addr == bldg_addr:
                return _complete_association(entity, building, db, "address_exact")

            # Street number + name match (first 2 words)
            entity_parts = entity_addr.split()
            bldg_parts = bldg_addr.split()
            if (len(entity_parts) >= 2 and len(bldg_parts) >= 2 and
                entity_parts[0] == bldg_parts[0] and entity_parts[1] == bldg_parts[1]):
                return _complete_association(entity, building, db, "address_partial")

    # Try name match
    if entity_name:
        buildings = query.limit(5000).all()
        for building in buildings:
            bldg_name = (building.name or "").upper().strip()
            if not bldg_name or len(bldg_name) < 5:
                continue

            if entity_name == bldg_name:
                return _complete_association(entity, building, db, "name_exact")

            # Name contained in the other
            if len(entity_name) > 5 and (entity_name in bldg_name or bldg_name in entity_name):
                return _complete_association(entity, building, db, "name_contains")

    return False


def _complete_association(entity: Entity, building: OsmBuilding, db: Session, match_type: str) -> bool:
    """Complete the association: set coordinates, merge data, advance stage."""
    try:
        # Set the association
        entity.osm_building_id = building.id
        building.promoted_entity_id = entity.id

        # Copy coordinates
        entity.latitude = building.lat
        entity.longitude = building.lon

        # Merge Overpass metadata into characteristics
        chars = dict(entity.characteristics or {})
        if building.stories and not chars.get("stories"):
            chars["stories"] = building.stories
        if building.building_type and not chars.get("building_type"):
            chars["building_type"] = building.building_type
        if building.construction_class and not chars.get("osm_construction_class"):
            chars["osm_construction_class"] = building.construction_class
        if building.footprint_sqft and not chars.get("footprint_sqft"):
            chars["footprint_sqft"] = building.footprint_sqft
        if building.osm_id:
            chars["osm_id"] = building.osm_id
        chars["osm_match_type"] = match_type
        entity.characteristics = chars

        # Advance to LEAD
        entity.pipeline_stage = "LEAD"
        entity.enrichment_status = "idle"

        db.commit()

        emit(EventType.HUNTER, "associate", EventStatus.SUCCESS,
             detail=f"'{entity.name}' matched to OSM {building.osm_id} ({match_type})",
             entity_id=entity.id)

        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Association failed for entity {entity.id}: {e}")
        return False


def run_association_cycle(db: Session) -> int:
    """Run one cycle of association attempts. Returns count of matches made."""
    # Get unassociated TARGETs
    targets = db.query(Entity).filter(
        Entity.pipeline_stage == "TARGET",
        Entity.osm_building_id.is_(None),
    ).limit(BATCH_SIZE).all()

    if not targets:
        return 0

    matched = 0
    for entity in targets:
        if _try_associate(entity, db):
            matched += 1

    return matched


def run_association_loop():
    """Background loop: continuously try to associate TARGETs with Overpass buildings."""
    from services.registry import register, heartbeat

    register("associator", capabilities={
        "poll_interval": POLL_INTERVAL,
        "batch_size": BATCH_SIZE,
    }, detail="Starting Overpass association worker")

    logger.info("Starting Overpass association worker...")

    while True:
        db = SessionLocal()
        try:
            # Count pending targets
            pending = db.query(Entity).filter(
                Entity.pipeline_stage == "TARGET",
                Entity.osm_building_id.is_(None),
            ).count()

            if pending > 0:
                matched = run_association_cycle(db)
                heartbeat("associator",
                          detail=f"Matched {matched} of {pending} pending targets")
                if matched > 0:
                    emit(EventType.HUNTER, "association_cycle", EventStatus.SUCCESS,
                         detail=f"{matched} targets associated, {pending - matched} remaining")
            else:
                heartbeat("associator", detail="Idle, no pending targets")

        except Exception as e:
            logger.error(f"Association cycle error: {e}")
            heartbeat("associator", status="degraded", detail=f"Error: {str(e)[:100]}")
        finally:
            db.close()

        time.sleep(POLL_INTERVAL)


def start_association_worker():
    """Start the association worker as a daemon thread."""
    thread = threading.Thread(target=run_association_loop, daemon=True)
    thread.start()
    return thread
