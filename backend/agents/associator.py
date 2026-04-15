"""
TARGET → LEAD Association Worker

Background worker that geocodes TARGET entities and promotes them to LEAD.

Primary geocoding: US Census Geocoder batch API (10,000 addresses per request)
Fallback: Nominatim single-address geocoding (1 req/sec)

On successful geocode:
- Sets entity latitude/longitude
- Advances pipeline_stage from TARGET → LEAD
- Sets enrichment_status to "idle" so enrichment worker picks it up

"""

import csv
import io
import logging
import os
import time
import threading
import uuid

import httpx
from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import Entity
from services.event_bus import EventStatus, EventType, emit

FILE_STORE_ROOT = os.path.join(os.path.dirname(__file__), "..", "filestore")

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds between association attempts
BATCH_SIZE = 1000  # targets to process per cycle (Census handles 10K)
CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"




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
    for attempt in range(3):
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
            break  # Success — exit retry loop
        except Exception as e:
            logger.warning(f"Census batch geocode attempt {attempt + 1}/3 failed: {e}")
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))  # 2s, 4s backoff

    return results



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
        from utils.geo import distance_to_ocean_miles

        entity.latitude = lat
        entity.longitude = lon

        chars = dict(entity.characteristics or {})
        chars["geocode_source"] = source
        # Compute distance to ocean now that we have coordinates
        ocean_dist = distance_to_ocean_miles(lat, lon)
        if ocean_dist is not None:
            chars["distance_to_ocean_miles"] = ocean_dist
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

    # Batch geocode via Census
    geocode_results = _batch_geocode_census(targets)

    if geocode_results:
        for entity in targets:
            if entity.id in geocode_results:
                lat, lon = geocode_results[entity.id]
                if _promote_geocoded(entity, lat, lon, db, "census"):
                    matched += 1

    # For any that Census missed, try Nominatim (limited to a few per cycle)
    nominatim_attempts = 0
    nominatim_limit = 10  # Only do a few Nominatim lookups per cycle
    for entity in targets:
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
