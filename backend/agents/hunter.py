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
    OsmBuilding,
    OsmHarvestArea,
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

    # All building types filtered by min levels to avoid returning
    # thousands of small apartment buildings
    return f"""
[out:json][timeout:90];
(
  way["building"="apartments"]["building:levels"~"{levels_regex}"]({bb});
  way["building"="residential"]["building:levels"~"{levels_regex}"]({bb});
  way["building"="condominium"]["building:levels"~"{levels_regex}"]({bb});
  way["building"="hotel"]["building:levels"~"{levels_regex}"]({bb});
  way["building"]["building:levels"~"{levels_regex}"]["building"!="house"]["building"!="garage"]["building"!="yes"]({bb});
  relation["building"="apartments"]["building:levels"~"{levels_regex}"]({bb});
  relation["building"="condominium"]["building:levels"~"{levels_regex}"]({bb});
);
out center tags;
"""


def estimate_footprint_sqft(element: dict) -> float | None:
    """Estimate building footprint area from OSM geometry nodes."""
    geometry = element.get("geometry") or element.get("bounds")
    if not geometry:
        return None

    # If we have geometry nodes, estimate area using bounding rectangle
    if isinstance(geometry, list) and len(geometry) >= 3:
        lats = [p["lat"] for p in geometry]
        lons = [p["lon"] for p in geometry]
        # Rough conversion: 1 degree lat ≈ 364,000 ft, 1 degree lon ≈ 288,000 ft at FL latitude
        height_ft = (max(lats) - min(lats)) * 364_000
        width_ft = (max(lons) - min(lons)) * 288_000
        area_sqft = height_ft * width_ft * 0.85  # 85% fill factor for non-rectangular buildings
        return round(area_sqft) if area_sqft > 500 else None

    return None


# ─── Construction class inference ───

# ISO Building Construction Types:
# Class 1: Fire Resistive (concrete/steel frame, non-combustible throughout)
# Class 2: Non-Combustible (steel frame, non-combustible walls)
# Class 3: Non-Combustible (masonry, limited combustible)
# Class 4: Masonry Non-Combustible
# Class 5: Wood Frame (combustible)
# Class 6: Mixed/Other

MATERIAL_TO_CONSTRUCTION: dict[str, dict] = {
    "concrete":             {"class": "Fire Resistive",           "iso": 1, "cost_per_sqft": 350},
    "reinforced_concrete":  {"class": "Fire Resistive",           "iso": 1, "cost_per_sqft": 375},
    "steel":                {"class": "Non-Combustible",          "iso": 2, "cost_per_sqft": 325},
    "steel_frame":          {"class": "Non-Combustible",          "iso": 2, "cost_per_sqft": 325},
    "brick":                {"class": "Masonry Non-Combustible",  "iso": 4, "cost_per_sqft": 275},
    "masonry":              {"class": "Masonry Non-Combustible",  "iso": 4, "cost_per_sqft": 275},
    "block":                {"class": "Masonry Non-Combustible",  "iso": 4, "cost_per_sqft": 275},
    "wood":                 {"class": "Frame",                    "iso": 5, "cost_per_sqft": 200},
    "timber":               {"class": "Frame",                    "iso": 5, "cost_per_sqft": 200},
}

# Default: high-rise (7+) in FL is almost always fire resistive concrete
DEFAULT_HIGHRISE_CONSTRUCTION = {"class": "Fire Resistive (inferred)", "iso": 1, "cost_per_sqft": 325}
DEFAULT_MIDRISE_CONSTRUCTION  = {"class": "Unknown — verify",          "iso": 0, "cost_per_sqft": 275}

# Avg floor area estimates when footprint not available (sqft)
AVG_FLOOR_SQFT = {
    "small": 8_000,     # 3-5 stories
    "midrise": 15_000,  # 6-9 stories
    "highrise": 22_000, # 10+ stories
}


def infer_construction(tags: dict, stories: int | None) -> dict:
    """Infer construction class from OSM tags and building height."""
    material = (tags.get("building:material") or tags.get("building:structure") or "").lower()

    if material in MATERIAL_TO_CONSTRUCTION:
        return MATERIAL_TO_CONSTRUCTION[material]

    # Infer from height: FL high-rises (7+) are almost always fire resistive concrete
    if stories and stories >= 7:
        return DEFAULT_HIGHRISE_CONSTRUCTION
    return DEFAULT_MIDRISE_CONSTRUCTION


def estimate_tiv(stories: int | None, footprint_sqft: float | None, construction: dict) -> float | None:
    """Estimate Total Insurable Value from building dimensions and construction type."""
    if not stories:
        return None

    if footprint_sqft and footprint_sqft > 500:
        floor_area = footprint_sqft
    elif stories >= 10:
        floor_area = AVG_FLOOR_SQFT["highrise"]
    elif stories >= 6:
        floor_area = AVG_FLOOR_SQFT["midrise"]
    else:
        floor_area = AVG_FLOOR_SQFT["small"]

    cost_per_sqft = construction.get("cost_per_sqft", 275)
    total_sqft = floor_area * stories
    tiv = total_sqft * cost_per_sqft

    return round(tiv, -3)  # Round to nearest thousand


def query_overpass(query: str, retries: int = 2) -> list[dict]:
    """Execute an Overpass API query and return elements. Retries on timeout."""
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=90) as client:
                resp = client.post(OVERPASS_URL, data={"data": query})
                resp.raise_for_status()
                data = resp.json()
                return data.get("elements", [])
        except Exception as e:
            is_timeout = "504" in str(e) or "timeout" in str(e).lower() or "429" in str(e)
            if is_timeout and attempt < retries:
                wait = (attempt + 1) * 15  # 15s, 30s
                logger.warning(f"Overpass timeout (attempt {attempt + 1}), retrying in {wait}s...")
                time.sleep(wait)
                continue
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
    """Parse an OSM element into a property candidate with construction + TIV estimate."""
    tags = element.get("tags", {})
    center = element.get("center") or {}

    lat = center.get("lat") or element.get("lat")
    lon = center.get("lon") or element.get("lon")

    # Fallback: compute center from geometry nodes
    if (lat is None or lon is None) and element.get("geometry"):
        geom = element["geometry"]
        if isinstance(geom, list) and len(geom) >= 2:
            lats = [p["lat"] for p in geom if "lat" in p]
            lons = [p["lon"] for p in geom if "lon" in p]
            if lats and lons:
                lat = sum(lats) / len(lats)
                lon = sum(lons) / len(lons)

    # Fallback: compute center from bounds
    if (lat is None or lon is None) and element.get("bounds"):
        bounds = element["bounds"]
        lat = (bounds.get("minlat", 0) + bounds.get("maxlat", 0)) / 2
        lon = (bounds.get("minlon", 0) + bounds.get("maxlon", 0)) / 2

    if lat is None or lon is None:
        return None

    name = tags.get("name", "")
    levels_str = tags.get("building:levels", "")
    stories = int(levels_str) if levels_str and levels_str.isdigit() else None

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

    # Construction class inference
    construction = infer_construction(tags, stories)

    # Footprint + TIV estimation
    footprint = estimate_footprint_sqft(element)
    tiv_estimate = estimate_tiv(stories, footprint, construction)

    # Units estimate (avg ~1,200 sqft per unit for FL condos)
    units_estimate = None
    if stories and footprint:
        total_sqft = footprint * stories
        units_estimate = max(1, round(total_sqft * 0.75 / 1200))  # 75% residential efficiency

    return {
        "name": name,
        "address": address,
        "latitude": float(lat),
        "longitude": float(lon),
        "characteristics": {
            "stories": stories,
            "construction_class": construction["class"],
            "iso_class": construction["iso"],
            "building_material": tags.get("building:material") or tags.get("building:structure"),
            "building_type": tags.get("building"),
            "year_built": tags.get("start_date") or tags.get("year_built"),
            "height_m": tags.get("height"),
            "units_estimate": units_estimate,
            "footprint_sqft": footprint,
            "tiv_estimate": tiv_estimate,
            "tiv": f"${tiv_estimate:,.0f}" if tiv_estimate else None,
            "osm_id": element.get("id"),
            "osm_tags": {
                k: v for k, v in tags.items()
                if k.startswith(("building", "roof", "addr", "name", "operator", "phone", "website"))
            },
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


def _harvest_to_cache(bbox: dict, db: Session, region_name: str = "") -> int:
    """Harvest ALL buildings from Overpass into osm_buildings cache.

    Caches every building regardless of filter criteria. Returns count cached.
    """
    bb_str = f"{bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']}"

    # Broad query: ALL multi-unit/commercial buildings (no levels filter)
    harvest_query = f"""
[out:json][timeout:90];
(
  way["building"="apartments"]({bb_str});
  way["building"="condominium"]({bb_str});
  way["building"="residential"]["building:levels"~"^[3-9]|[1-9][0-9]"]({bb_str});
  way["building"="hotel"]["building:levels"~"^[3-9]|[1-9][0-9]"]({bb_str});
  way["building"="commercial"]["building:levels"~"^[3-9]|[1-9][0-9]"]({bb_str});
  relation["building"="apartments"]({bb_str});
  relation["building"="condominium"]({bb_str});
);
out center tags;
"""
    elements = query_overpass(harvest_query)
    if not elements:
        return 0

    cached = 0
    for element in elements:
        osm_id = element.get("id")
        if not osm_id:
            continue

        # Skip if already cached
        existing = db.query(OsmBuilding).filter(OsmBuilding.osm_id == osm_id).first()
        if existing:
            continue

        # Parse basic info
        prop = parse_osm_element(element)
        if not prop:
            continue

        tags = element.get("tags", {})
        chars = prop.get("characteristics", {})

        building = OsmBuilding(
            osm_id=osm_id,
            osm_type=element.get("type", "way"),
            lat=prop["latitude"],
            lon=prop["longitude"],
            name=prop.get("name"),
            address=prop.get("address"),
            building_type=tags.get("building"),
            stories=chars.get("stories"),
            construction_class=chars.get("construction_class"),
            iso_class=chars.get("iso_class"),
            tiv_estimate=chars.get("tiv_estimate"),
            units_estimate=chars.get("units_estimate"),
            footprint_sqft=chars.get("footprint_sqft"),
            tags=tags,
            raw_element=element,
        )
        db.add(building)
        cached += 1

        # Batch commit every 50
        if cached % 50 == 0:
            db.flush()

    # Record this harvest area
    harvest_area = OsmHarvestArea(
        name=region_name,
        bbox_south=bbox["south"],
        bbox_north=bbox["north"],
        bbox_west=bbox["west"],
        bbox_east=bbox["east"],
        building_count=cached,
        query_params={"total_elements": len(elements)},
    )
    db.add(harvest_area)
    db.commit()

    emit(EventType.HUNTER, "harvest_cache", EventStatus.SUCCESS,
         detail=f"Cached {cached} new buildings from {len(elements)} elements ({region_name})")
    logger.info(f"Harvest cache: {cached} new from {len(elements)} elements ({region_name})")
    return cached


def _is_area_harvested(bbox: dict, db: Session) -> bool:
    """Check if a bounding box is substantially covered by existing harvests."""
    # Simple check: is there a harvest area that fully contains this bbox?
    existing = db.query(OsmHarvestArea).filter(
        OsmHarvestArea.bbox_south <= bbox["south"],
        OsmHarvestArea.bbox_north >= bbox["north"],
        OsmHarvestArea.bbox_west <= bbox["west"],
        OsmHarvestArea.bbox_east >= bbox["east"],
    ).first()
    return existing is not None


def _filter_cached_buildings(
    bbox: dict, db: Session, min_stories: int = 3, construction_filter: str = "any"
) -> list[OsmBuilding]:
    """Filter cached buildings by region parameters."""
    query = db.query(OsmBuilding).filter(
        OsmBuilding.lat >= bbox["south"],
        OsmBuilding.lat <= bbox["north"],
        OsmBuilding.lon >= bbox["west"],
        OsmBuilding.lon <= bbox["east"],
        OsmBuilding.promoted_entity_id.is_(None),  # Not yet promoted to lead
    )

    if min_stories and min_stories > 1:
        # Include buildings with stories >= min OR with no stories (unknown, could be multi-story)
        query = query.filter(
            (OsmBuilding.stories >= min_stories) | (OsmBuilding.stories.is_(None))
        )

    if construction_filter and construction_filter != "any":
        if construction_filter == "fire_resistive":
            query = query.filter(OsmBuilding.construction_class.ilike("%fire resistive%"))
        elif construction_filter == "non_combustible":
            query = query.filter(
                OsmBuilding.construction_class.ilike("%fire resistive%") |
                OsmBuilding.construction_class.ilike("%non-combustible%")
            )
        elif construction_filter == "masonry":
            query = query.filter(
                OsmBuilding.construction_class.ilike("%fire resistive%") |
                OsmBuilding.construction_class.ilike("%non-combustible%") |
                OsmBuilding.construction_class.ilike("%masonry%")
            )

    return query.all()


def _promote_to_lead(
    building: OsmBuilding, region: RegionOfInterest, county: str | None, db: Session
) -> int:
    """Promote a cached OSM building to a lead Entity."""
    # Geocode if not yet done
    if not building.geocoded and building.lat and building.lon:
        if not building.address or len(building.address) < 10:
            geo = reverse_geocode(building.lat, building.lon)
            if geo:
                address_data = geo.get("address", {})
                road = address_data.get("road", "")
                house = address_data.get("house_number", "")
                city = address_data.get("city") or address_data.get("town") or ""
                postcode = address_data.get("postcode", "")
                geo_county = address_data.get("county", "").replace(" County", "")

                if road:
                    addr = f"{house} {road}".strip() if house else road
                    if city:
                        addr += f", {city}"
                    addr += f", FL {postcode}".strip()
                    building.address = addr
                if geo_county:
                    building.county = geo_county

            building.geocoded = 1
            time.sleep(1.1)  # Nominatim rate limit

    # Build characteristics from cached data
    characteristics = {
        "stories": building.stories,
        "construction_class": building.construction_class,
        "iso_class": building.iso_class,
        "building_type": building.building_type,
        "tiv_estimate": building.tiv_estimate,
        "units_estimate": building.units_estimate,
        "footprint_sqft": building.footprint_sqft,
        "osm_id": building.osm_id,
        "osm_tags": building.tags or {},
    }
    if building.tiv_estimate:
        characteristics["tiv"] = f"${building.tiv_estimate:,.0f}"

    # Dedupe: check if Entity already exists for this OSM ID
    existing = db.query(Entity).filter(
        Entity.characteristics.op("->>")(  "osm_id") == str(building.osm_id)
    ).first()
    if existing:
        building.promoted_entity_id = existing.id
        return 0

    try:
        entity = Entity(
            name=building.name or f"Building at {building.lat:.4f}, {building.lon:.4f}",
            address=building.address or "",
            county=building.county or county or region.target_county,
            latitude=building.lat,
            longitude=building.lon,
            characteristics={k: v for k, v in characteristics.items() if v is not None},
            pipeline_stage="NEW",
        )
        db.add(entity)
        db.flush()

        building.promoted_entity_id = entity.id

        ledger = LeadLedger(
            entity_id=entity.id,
            action_type=ActionType.HUNT_FOUND.value,
            detail=f"Promoted from OSM cache (region '{region.name}')",
            source="overpass",
            source_url=f"https://www.openstreetmap.org/way/{building.osm_id}",
        )
        db.add(ledger)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Failed to promote building {building.osm_id}: {e}")
        return 0

    # Run enrichments on the new entity
    try:
        from agents.enrichers.pipeline import run_on_new_lead
        run_on_new_lead(entity, db)
    except Exception as e:
        logger.warning(f"Enrichment failed for promoted entity {entity.id}: {e}")

    return 1


def process_region(region: RegionOfInterest, db: Session) -> int:
    """Process a region: harvest to cache if needed, then filter + promote matches."""
    bbox = region.bounding_box
    center_lat, center_lng = get_bounding_box_center(bbox)
    params = region.parameters or {}

    # Determine county
    county = get_county_from_coords(center_lat, center_lng)
    if county:
        region.target_county = county
        db.commit()

    emit(EventType.HUNTER, "process_region", EventStatus.PENDING,
         detail=f"Region '{region.name}' county={county}", region_id=region.id)
    logger.info(f"Processing region '{region.name}' - County: {county}")

    # Step 1: Harvest to cache if this area hasn't been harvested yet
    if not _is_area_harvested(bbox, db):
        emit(EventType.HUNTER, "harvest_start", EventStatus.PENDING,
             detail=f"Harvesting Overpass for '{region.name}'", region_id=region.id)
        cached = _harvest_to_cache(bbox, db, region_name=region.name)
        emit(EventType.HUNTER, "harvest_complete", EventStatus.SUCCESS,
             detail=f"{cached} buildings cached for '{region.name}'", region_id=region.id)
    else:
        emit(EventType.HUNTER, "harvest_skip", EventStatus.SUCCESS,
             detail=f"Area already harvested for '{region.name}'", region_id=region.id)

    # Step 2: Filter cached buildings by region params
    min_stories = params.get("stories", MIN_LEVELS)
    construction_filter = params.get("construction_filter", "any")
    candidates = _filter_cached_buildings(bbox, db, min_stories, construction_filter)

    emit(EventType.HUNTER, "filter_cache", EventStatus.SUCCESS,
         detail=f"{len(candidates)} matching buildings for '{region.name}'", region_id=region.id)

    # Step 3: Promote matching buildings to leads
    found = 0
    for building in candidates:
        found += _promote_to_lead(building, region, county, db)

    # Mark region as completed
    region.status = RegionStatus.COMPLETED
    db.commit()

    detail = f"Region '{region.name}' done, {found} new leads from {len(candidates)} candidates"
    emit(EventType.HUNTER, "process_region", EventStatus.SUCCESS,
         detail=detail, region_id=region.id)
    logger.info(detail)
    return found






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
