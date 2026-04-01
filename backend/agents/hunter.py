"""
Hunter Agent - Phase II

Polls for PENDING regions and discovers real multi-story residential
buildings using the OpenStreetMap Overpass API (free, no key needed).

Flow: Draw region → Hunter queries Overpass → Filters for condos/apartments
→ Reverse geocodes for address/county → Saves as NEW leads

Target counties (V1): Pasco, Pinellas, Hillsborough, Manatee, Sarasota,
Charlotte, Lee, Collier, Palm Beach, Miami-Dade, Broward
"""

import json
import logging
import os
import time

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import (
    ActionType,
    Entity,
    LeadLedger,
    RegionOfInterest,
    RegionStatus,
)
from agents.geo_helper import get_bounding_box_center, get_county_from_coords, is_within_bounds
from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("HUNTER_POLL_INTERVAL", "30"))

# V1 target counties — Jason's territory
TARGET_COUNTIES = {
    "Pasco", "Pinellas", "Hillsborough", "Manatee", "Sarasota",
    "Charlotte", "Lee", "Collier", "Palm Beach", "Miami-Dade", "Broward",
}

# Overpass API endpoint (free, no key)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Min building levels to consider (filters out small residential)
MIN_LEVELS = 3

# Nominatim endpoint for reverse geocoding
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"


def build_overpass_query(bbox: dict, min_levels: int = MIN_LEVELS) -> str:
    """Build an Overpass QL query for multi-story residential buildings in a bounding box."""
    # Overpass bbox format: south,west,north,east
    bb = f"{bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']}"
    levels_regex = f"^[{min_levels}-9]|[1-9][0-9]"

    return f"""
[out:json][timeout:60];
(
  way["building"="apartments"]({bb});
  way["building"="residential"]["building:levels"~"{levels_regex}"]({bb});
  way["building"="condominium"]({bb});
  way["building"="hotel"]["building:levels"~"{levels_regex}"]({bb});
  relation["building"="apartments"]({bb});
  relation["building"="condominium"]({bb});
);
out center tags;
"""


def query_overpass(query: str) -> list[dict]:
    """Execute an Overpass API query and return elements."""
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            data = resp.json()
            return data.get("elements", [])
    except Exception as e:
        logger.error(f"Overpass API error: {e}")
        emit(EventType.HUNTER, "overpass_query", EventStatus.ERROR, detail=str(e)[:200])
        return []


def reverse_geocode(lat: float, lon: float) -> dict:
    """Reverse geocode coordinates to get address details via Nominatim."""
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(NOMINATIM_URL, params={
                "format": "json",
                "lat": lat,
                "lon": lon,
                "zoom": 18,
                "addressdetails": 1,
            }, headers={"User-Agent": "insure-lead-gen/1.0"})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"Geocode failed for {lat},{lon}: {e}")
        return {}


def parse_osm_element(element: dict) -> dict | None:
    """Parse an OSM element into a property candidate."""
    tags = element.get("tags", {})
    center = element.get("center", {})

    lat = center.get("lat") or element.get("lat")
    lon = center.get("lon") or element.get("lon")
    if not lat or not lon:
        return None

    name = tags.get("name", "")
    levels = tags.get("building:levels", "")
    addr_street = tags.get("addr:street", "")
    addr_number = tags.get("addr:housenumber", "")
    addr_city = tags.get("addr:city", "")
    addr_state = tags.get("addr:state", "FL")
    addr_zip = tags.get("addr:postcode", "")

    # Build address from components
    address_parts = []
    if addr_number and addr_street:
        address_parts.append(f"{addr_number} {addr_street}")
    elif addr_street:
        address_parts.append(addr_street)
    if addr_city:
        address_parts.append(addr_city)
    address_parts.append(addr_state)
    if addr_zip:
        address_parts.append(addr_zip)

    address = ", ".join(address_parts) if address_parts else ""

    # If no name, generate from address or coordinates
    if not name:
        if addr_street:
            name = f"{addr_number} {addr_street}".strip() if addr_number else addr_street
        else:
            name = f"Building at {lat:.4f}, {lon:.4f}"

    return {
        "name": name,
        "address": address,
        "latitude": float(lat),
        "longitude": float(lon),
        "characteristics": {
            "stories": int(levels) if levels and levels.isdigit() else None,
            "construction": tags.get("building:material"),
            "building_type": tags.get("building"),
            "osm_id": element.get("id"),
        },
    }


def enrich_with_geocode(prop: dict) -> dict:
    """Enrich a property with reverse geocode data if address is incomplete."""
    if prop.get("address") and len(prop["address"]) > 10:
        return prop  # Already has a decent address

    geo = reverse_geocode(prop["latitude"], prop["longitude"])
    if not geo:
        return prop

    address_data = geo.get("address", {})
    display = geo.get("display_name", "")

    # Build address from geocode
    road = address_data.get("road", "")
    house = address_data.get("house_number", "")
    city = address_data.get("city") or address_data.get("town") or address_data.get("village", "")
    state = address_data.get("state", "Florida")
    postcode = address_data.get("postcode", "")
    county = address_data.get("county", "").replace(" County", "")

    if road:
        addr = f"{house} {road}".strip() if house else road
        if city:
            addr += f", {city}"
        addr += f", FL {postcode}".strip()
        prop["address"] = addr

    if not prop.get("address") and display:
        prop["address"] = display.split(",")[0]

    prop["county"] = county
    return prop


def process_region(region: RegionOfInterest, db: Session) -> int:
    """Process a single region: query Overpass and save discovered properties."""
    bbox = region.bounding_box
    center_lat, center_lng = get_bounding_box_center(bbox)

    # Determine county
    county = get_county_from_coords(center_lat, center_lng)
    if county:
        region.target_county = county
        db.commit()

    emit(EventType.HUNTER, "process_region", EventStatus.PENDING,
         detail=f"Region '{region.name}' county={county}", region_id=region.id)
    logger.info(f"Processing region '{region.name}' - County: {county}")

    # Query OSM Overpass for buildings
    min_levels = (region.parameters or {}).get("stories", MIN_LEVELS)
    query = build_overpass_query(bbox, min_levels)
    elements = query_overpass(query)

    if not elements:
        logger.info(f"No buildings found in region '{region.name}'")
        emit(EventType.HUNTER, "overpass_query", EventStatus.SUCCESS,
             detail=f"0 buildings in '{region.name}'", region_id=region.id)

    found = 0
    for element in elements:
        prop = parse_osm_element(element)
        if not prop:
            continue

        # Verify within bounds (Overpass bbox is approximate)
        if not is_within_bounds(prop["latitude"], prop["longitude"], bbox):
            continue

        # Enrich with geocode if address is sparse
        prop = enrich_with_geocode(prop)

        # Set county from geocode or region
        if not prop.get("county"):
            prop["county"] = county

        # Rate limit Nominatim (1 req/sec policy)
        time.sleep(1.1)

        found += save_property(prop, region, db)

    # Mark region as completed
    region.status = RegionStatus.COMPLETED
    db.commit()

    emit(EventType.HUNTER, "process_region", EventStatus.SUCCESS,
         detail=f"Region '{region.name}' done, {found}/{len(elements)} properties saved",
         region_id=region.id)
    logger.info(f"Region '{region.name}' completed. Found {found} new properties from {len(elements)} OSM elements.")
    return found


def save_property(prop: dict, region: RegionOfInterest, db: Session) -> int:
    """Save a property to the database if not already exists."""
    # Dedupe by name+address or by OSM ID
    osm_id = (prop.get("characteristics") or {}).get("osm_id")
    if osm_id:
        existing = db.query(Entity).filter(
            Entity.characteristics.op("->>")(  "osm_id") == str(osm_id)
        ).first()
        if existing:
            return 0

    existing = db.query(Entity).filter(
        Entity.name == prop["name"],
        Entity.address == prop.get("address", ""),
    ).first()
    if existing:
        return 0

    try:
        entity = Entity(
            name=prop["name"],
            address=prop.get("address", ""),
            county=prop.get("county") or region.target_county,
            latitude=prop.get("latitude"),
            longitude=prop.get("longitude"),
            characteristics=prop.get("characteristics", {}),
            pipeline_stage="NEW",
        )
        db.add(entity)
        db.commit()
        db.refresh(entity)

        ledger = LeadLedger(
            entity_id=entity.id,
            action_type=ActionType.HUNT_FOUND.value,
            detail=f"Discovered via OSM Overpass in region '{region.name}'",
        )
        db.add(ledger)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Failed to save property '{prop.get('name')}': {e}")
        emit(EventType.DB_OPERATION, "save_property", EventStatus.ERROR,
             detail=f"'{prop.get('name')}': {str(e)[:200]}")
        return 0

    emit(EventType.DB_OPERATION, "save_property", EventStatus.SUCCESS,
         detail=f"Saved '{entity.name}' (id={entity.id})", entity_id=entity.id)
    return 1


def run_hunter_loop():
    """Main polling loop — runs as a background task."""
    from services.registry import register, heartbeat

    logger.info("Starting hunter agent loop (Phase II - OSM Overpass)...")

    register("hunter", capabilities={
        "data_source": "OpenStreetMap Overpass API",
        "target_counties": list(TARGET_COUNTIES),
        "min_building_levels": MIN_LEVELS,
        "poll_interval": POLL_INTERVAL,
    }, detail=f"Polling every {POLL_INTERVAL}s — OSM Overpass")

    while True:
        db = SessionLocal()
        try:
            pending_regions = (
                db.query(RegionOfInterest)
                .filter(RegionOfInterest.status == RegionStatus.PENDING)
                .all()
            )

            if pending_regions:
                heartbeat("hunter", detail=f"Processing {len(pending_regions)} region(s)")
            else:
                heartbeat("hunter", detail="Idle, no pending regions")

            for region in pending_regions:
                try:
                    process_region(region, db)
                except Exception as e:
                    logger.error(f"Region '{region.name}' failed: {e}")
                    emit(EventType.HUNTER, "process_region", EventStatus.ERROR,
                         detail=f"'{region.name}': {str(e)[:200]}")

        except Exception as e:
            logger.error(f"Hunter loop error: {e}")
            heartbeat("hunter", status="degraded", detail=f"Error: {str(e)[:100]}")
        finally:
            db.rollback()
            db.close()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_hunter_loop()
