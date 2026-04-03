"""
TARGET → LEAD Association Worker

Background worker that geocodes TARGET entities and promotes them to LEAD.

Primary geocoding: US Census Geocoder batch API (10,000 addresses per request)
Fallback: Nominatim single-address geocoding (1 req/sec)

On successful geocode:
- Sets entity latitude/longitude
- Advances pipeline_stage from TARGET → LEAD
- Sets enrichment_status to "idle" so enrichment worker picks it up

Also tries to match against Overpass cached buildings if available.
"""

import csv
import io
import logging
import os
import re
import time
import threading
import uuid

import httpx
from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import Entity, OsmBuilding
from services.event_bus import EventStatus, EventType, emit

FILE_STORE_ROOT = os.path.join(os.path.dirname(__file__), "..", "filestore")

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds between association attempts
BATCH_SIZE = 1000  # targets to process per cycle (Census handles 10K)
CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"


def _normalize_address(addr: str) -> str:
    """Normalize address for Overpass matching."""
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


def _parse_address_parts(entity: Entity) -> tuple[str, str, str, str]:
    """Extract street, city, state, zip from entity data."""
    chars = entity.characteristics or {}
    street = (entity.address or "").split(",")[0].strip()
    city = chars.get("phy_city", "") or ""
    zipcode = chars.get("phy_zip", "") or ""
    return street, city, "FL", zipcode


def _batch_geocode_census(entities: list[Entity]) -> dict[int, tuple[float, float]]:
    """Geocode a batch of entities using the US Census Geocoder.

    Accepts up to 10,000 addresses. Returns dict of entity_id -> (lat, lon).
    """
    # Build CSV for Census batch API
    # Format: Unique ID, Street address, City, State, ZIP
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    for entity in entities:
        street, city, state, zipcode = _parse_address_parts(entity)
        if not street:
            continue
        writer.writerow([entity.id, street, city, state, zipcode])

    csv_content = csv_buf.getvalue()
    if not csv_content.strip():
        return {}

    results = {}
    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                CENSUS_BATCH_URL,
                data={"benchmark": "Public_AR_Current", "vintage": "Current_Current"},
                files={"addressFile": ("addresses.csv", csv_content, "text/csv")},
            )
            resp.raise_for_status()

            # Parse response CSV
            # Format: ID, Input Address, Match, Match Type, Matched Address, Coordinates, TIGER ID, Side
            reader = csv.reader(io.StringIO(resp.text))
            for row in reader:
                if len(row) < 6:
                    continue
                entity_id = int(row[0].strip('" '))
                match_status = row[2].strip('" ').lower()
                if match_status in ("match", "exact"):
                    coords_str = row[5].strip('" ')
                    if "," in coords_str:
                        # Census returns lon,lat (not lat,lon)
                        lon, lat = coords_str.split(",")
                        results[entity_id] = (float(lat.strip()), float(lon.strip()))
    except Exception as e:
        logger.error(f"Census batch geocode failed: {e}")

    return results


def _try_overpass_match(entity: Entity, db: Session) -> bool:
    """Try to match entity against Overpass cached buildings."""
    entity_addr = _normalize_address(entity.address or "")
    entity_name = (entity.name or "").upper().strip()
    county = entity.county

    if not entity_addr and not entity_name:
        return False

    query = db.query(OsmBuilding).filter(
        OsmBuilding.promoted_entity_id.is_(None),
    )
    if county:
        query = query.filter(OsmBuilding.county == county)

    buildings = query.limit(5000).all()
    if not buildings:
        return False

    for building in buildings:
        # Address match
        if entity_addr:
            bldg_addr = _normalize_address(building.address or "")
            if bldg_addr and entity_addr == bldg_addr:
                return _complete_overpass_association(entity, building, db, "address_exact")
            if bldg_addr:
                ep = entity_addr.split()
                bp = bldg_addr.split()
                if len(ep) >= 2 and len(bp) >= 2 and ep[0] == bp[0] and ep[1] == bp[1]:
                    return _complete_overpass_association(entity, building, db, "address_partial")

        # Name match
        if entity_name:
            bldg_name = (building.name or "").upper().strip()
            if bldg_name and len(bldg_name) >= 5:
                if entity_name == bldg_name:
                    return _complete_overpass_association(entity, building, db, "name_exact")
                if len(entity_name) > 5 and (entity_name in bldg_name or bldg_name in entity_name):
                    return _complete_overpass_association(entity, building, db, "name_contains")

    return False


def _complete_overpass_association(entity: Entity, building: OsmBuilding, db: Session, match_type: str) -> bool:
    """Complete association with an Overpass building."""
    try:
        entity.osm_building_id = building.id
        building.promoted_entity_id = entity.id
        entity.latitude = building.lat
        entity.longitude = building.lon

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

        entity.pipeline_stage = "LEAD"
        entity.enrichment_status = "idle"
        _create_entity_folder(entity)
        db.commit()

        emit(EventType.HUNTER, "associate", EventStatus.SUCCESS,
             detail=f"'{entity.name}' matched to OSM {building.osm_id} ({match_type})",
             entity_id=entity.id)
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Overpass association failed for entity {entity.id}: {e}")
        return False


def _create_entity_folder(entity: Entity) -> str:
    """Create a UUID-based folder structure for the entity's artifacts."""
    folder_id = str(uuid.uuid4())[:8]
    county_slug = (entity.county or "unknown").replace(" ", "_").replace("-", "_")
    folder_name = f"{county_slug}/{folder_id}"
    folder_path = os.path.join(FILE_STORE_ROOT, "Associations", folder_name)

    # Create subfolders for different artifact types
    for sub in ["enrichment", "documents", "correspondence", "analysis"]:
        os.makedirs(os.path.join(folder_path, sub), exist_ok=True)

    entity.folder_path = f"Associations/{folder_name}"
    return entity.folder_path


def _promote_geocoded(entity: Entity, lat: float, lon: float, db: Session, source: str = "census") -> bool:
    """Promote a geocoded TARGET to LEAD."""
    try:
        entity.latitude = lat
        entity.longitude = lon

        chars = dict(entity.characteristics or {})
        chars["geocode_source"] = source
        entity.characteristics = chars

        entity.pipeline_stage = "LEAD"
        entity.enrichment_status = "idle"
        _create_entity_folder(entity)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Geocode promotion failed for entity {entity.id}: {e}")
        return False


def run_association_cycle(db: Session) -> int:
    """Run one cycle: batch geocode TARGETs → promote to LEAD."""
    targets = db.query(Entity).filter(
        Entity.pipeline_stage == "TARGET",
        Entity.latitude.is_(None),
    ).limit(BATCH_SIZE).all()

    if not targets:
        return 0

    matched = 0

    # First try Overpass matching if cache has data
    osm_count = db.query(OsmBuilding).count()
    overpass_matched = []
    if osm_count > 0:
        for entity in targets:
            if _try_overpass_match(entity, db):
                matched += 1
                overpass_matched.append(entity.id)

    # Filter out Overpass-matched entities
    remaining = [e for e in targets if e.id not in overpass_matched and e.pipeline_stage == "TARGET"]

    if not remaining:
        return matched

    # Batch geocode the rest via Census
    geocode_results = _batch_geocode_census(remaining)

    if geocode_results:
        for entity in remaining:
            if entity.id in geocode_results:
                lat, lon = geocode_results[entity.id]
                if _promote_geocoded(entity, lat, lon, db, "census"):
                    matched += 1

    # For any that Census missed, try Nominatim (limited to a few per cycle)
    nominatim_attempts = 0
    nominatim_limit = 10  # Only do a few Nominatim lookups per cycle
    for entity in remaining:
        if entity.pipeline_stage != "TARGET" or entity.latitude is not None:
            continue
        if nominatim_attempts >= nominatim_limit:
            break

        street, city, state, zipcode = _parse_address_parts(entity)
        if not street:
            continue

        coords = _geocode_nominatim(street, city, entity.county)
        if coords:
            if _promote_geocoded(entity, coords[0], coords[1], db, "nominatim"):
                matched += 1
        nominatim_attempts += 1
        time.sleep(1.1)

    return matched


def _geocode_nominatim(address: str, city: str = "", county: str = "") -> tuple[float, float] | None:
    """Geocode a single address via Nominatim. Returns (lat, lon) or None."""
    try:
        search = address
        if city:
            search += f", {city}"
        if county:
            search += f", {county} County"
        search += ", Florida"

        with httpx.Client(timeout=10, headers={"User-Agent": "insure-lead-gen/1.0"}) as client:
            resp = client.get("https://nominatim.openstreetmap.org/search", params={
                "q": search, "format": "json", "limit": 1,
            })
            resp.raise_for_status()
            data = resp.json()
            if data:
                return (float(data[0]["lat"]), float(data[0]["lon"]))
    except Exception as e:
        logger.debug(f"Nominatim geocode failed for '{address}': {e}")
    return None


def run_association_loop():
    """Background loop: continuously geocode TARGETs and promote to LEAD."""
    from services.registry import register, heartbeat

    register("associator", capabilities={
        "poll_interval": POLL_INTERVAL,
        "batch_size": BATCH_SIZE,
        "geocoder": "census_batch + nominatim_fallback",
    }, detail="Starting geocode association worker")

    logger.info("Starting geocode association worker...")

    while True:
        db = SessionLocal()
        try:
            pending = db.query(Entity).filter(
                Entity.pipeline_stage == "TARGET",
                Entity.latitude.is_(None),
            ).count()

            if pending > 0:
                matched = run_association_cycle(db)
                heartbeat("associator",
                          detail=f"Matched {matched} of {min(pending, BATCH_SIZE)} batch ({pending} pending)")
                if matched > 0:
                    emit(EventType.HUNTER, "association_cycle", EventStatus.SUCCESS,
                         detail=f"{matched} targets → LEAD, {pending - matched} remaining")
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
