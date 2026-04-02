import threading

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db, SessionLocal

router = APIRouter()


@router.post("/api/admin/seed")
def run_seed(db: Session = Depends(get_db)):
    """Trigger the seed script to populate mock data."""
    from scripts.seed import seed
    seed()
    return {"success": True, "message": "Seed complete"}


# Full county harvest areas — covers entire county footprints
# Split into grid tiles (~0.15° ≈ 10 miles) to keep Overpass queries manageable
# Counties ordered south → north along both coasts

FL_HARVEST_AREAS = [
    # ─── Miami-Dade County ───
    {"name": "Miami-Dade South (Homestead)", "south": 25.40, "north": 25.55, "west": -80.50, "east": -80.30, "county": "Miami-Dade"},
    {"name": "Miami-Dade Central (Kendall/Coral Gables)", "south": 25.55, "north": 25.72, "west": -80.40, "east": -80.20, "county": "Miami-Dade"},
    {"name": "Miami-Dade Downtown/Brickell", "south": 25.72, "north": 25.82, "west": -80.25, "east": -80.15, "county": "Miami-Dade"},
    {"name": "Miami Beach / Key Biscayne", "south": 25.72, "north": 25.88, "west": -80.17, "east": -80.08, "county": "Miami-Dade"},
    {"name": "Miami-Dade North (Aventura/Sunny Isles)", "south": 25.88, "north": 26.00, "west": -80.20, "east": -80.08, "county": "Miami-Dade"},

    # ─── Broward County ───
    {"name": "Broward South (Hollywood/Hallandale)", "south": 25.97, "north": 26.08, "west": -80.20, "east": -80.08, "county": "Broward"},
    {"name": "Broward Central (Fort Lauderdale)", "south": 26.08, "north": 26.20, "west": -80.20, "east": -80.08, "county": "Broward"},
    {"name": "Broward North (Pompano/Deerfield)", "south": 26.20, "north": 26.35, "west": -80.15, "east": -80.05, "county": "Broward"},

    # ─── Palm Beach County ───
    {"name": "Palm Beach South (Boca Raton/Delray)", "south": 26.30, "north": 26.48, "west": -80.12, "east": -80.02, "county": "Palm Beach"},
    {"name": "Palm Beach Central (Boynton/Lake Worth)", "south": 26.48, "north": 26.63, "west": -80.10, "east": -80.00, "county": "Palm Beach"},
    {"name": "Palm Beach North (Palm Beach/Jupiter)", "south": 26.63, "north": 26.80, "west": -80.08, "east": -80.00, "county": "Palm Beach"},

    # ─── Collier County ───
    {"name": "Collier South (Marco Island)", "south": 25.88, "north": 26.02, "west": -81.80, "east": -81.68, "county": "Collier"},
    {"name": "Collier Central (Naples)", "south": 26.10, "north": 26.25, "west": -81.85, "east": -81.72, "county": "Collier"},
    {"name": "Collier North (Bonita area)", "south": 26.25, "north": 26.40, "west": -81.85, "east": -81.75, "county": "Collier"},

    # ─── Lee County ───
    {"name": "Lee South (Fort Myers Beach/Estero)", "south": 26.35, "north": 26.50, "west": -82.00, "east": -81.85, "county": "Lee"},
    {"name": "Lee Central (Fort Myers/Cape Coral)", "south": 26.50, "north": 26.70, "west": -82.05, "east": -81.85, "county": "Lee"},
    {"name": "Lee North (Sanibel/Pine Island)", "south": 26.42, "north": 26.55, "west": -82.15, "east": -82.00, "county": "Lee"},

    # ─── Charlotte County ───
    {"name": "Charlotte (Punta Gorda/Port Charlotte)", "south": 26.82, "north": 27.00, "west": -82.12, "east": -81.95, "county": "Charlotte"},
    {"name": "Charlotte Coast (Englewood)", "south": 26.92, "north": 27.05, "west": -82.40, "east": -82.25, "county": "Charlotte"},

    # ─── Sarasota County ───
    {"name": "Sarasota South (Venice/Nokomis)", "south": 27.05, "north": 27.18, "west": -82.50, "east": -82.38, "county": "Sarasota"},
    {"name": "Sarasota Central (Siesta/Lido)", "south": 27.18, "north": 27.35, "west": -82.60, "east": -82.48, "county": "Sarasota"},
    {"name": "Sarasota North (Longboat Key)", "south": 27.35, "north": 27.48, "west": -82.68, "east": -82.55, "county": "Sarasota"},
    {"name": "Sarasota Mainland", "south": 27.25, "north": 27.42, "west": -82.55, "east": -82.42, "county": "Sarasota"},

    # ─── Manatee County ───
    {"name": "Manatee Coast (Anna Maria/Holmes Beach)", "south": 27.47, "north": 27.55, "west": -82.75, "east": -82.65, "county": "Manatee"},
    {"name": "Manatee Central (Bradenton)", "south": 27.45, "north": 27.55, "west": -82.62, "east": -82.48, "county": "Manatee"},
    {"name": "Manatee East (Lakewood Ranch)", "south": 27.35, "north": 27.50, "west": -82.48, "east": -82.35, "county": "Manatee"},

    # ─── Hillsborough County ───
    {"name": "Hillsborough South (Sun City/Apollo Beach)", "south": 27.70, "north": 27.82, "west": -82.45, "east": -82.30, "county": "Hillsborough"},
    {"name": "Hillsborough Central (Tampa Downtown)", "south": 27.90, "north": 28.00, "west": -82.50, "east": -82.40, "county": "Hillsborough"},
    {"name": "Hillsborough West (Westchase/Town'n'Country)", "south": 28.00, "north": 28.10, "west": -82.62, "east": -82.48, "county": "Hillsborough"},
    {"name": "Hillsborough East (Brandon/Riverview)", "south": 27.85, "north": 28.00, "west": -82.35, "east": -82.20, "county": "Hillsborough"},

    # ─── Pinellas County ───
    {"name": "Pinellas South (St Pete/Gulfport)", "south": 27.68, "north": 27.80, "west": -82.78, "east": -82.62, "county": "Pinellas"},
    {"name": "Pinellas Beaches (Treasure Is → Indian Rocks)", "south": 27.75, "north": 27.92, "west": -82.86, "east": -82.78, "county": "Pinellas"},
    {"name": "Pinellas Central (Largo/Seminole)", "south": 27.80, "north": 27.92, "west": -82.78, "east": -82.68, "county": "Pinellas"},
    {"name": "Pinellas North (Clearwater/Dunedin)", "south": 27.92, "north": 28.05, "west": -82.82, "east": -82.68, "county": "Pinellas"},
    {"name": "Clearwater Beach / Sand Key", "south": 27.90, "north": 28.02, "west": -82.85, "east": -82.80, "county": "Pinellas"},

    # ─── Pasco County ───
    {"name": "Pasco South (New Port Richey/Hudson)", "south": 28.15, "north": 28.30, "west": -82.75, "east": -82.55, "county": "Pasco"},
    {"name": "Pasco Central (Wesley Chapel/Zephyrhills)", "south": 28.20, "north": 28.35, "west": -82.50, "east": -82.30, "county": "Pasco"},
    {"name": "Pasco Coast (Holiday/Tarpon Springs border)", "south": 28.05, "north": 28.20, "west": -82.80, "east": -82.65, "county": "Pasco"},
]


def _run_bulk_harvest():
    """Background job: harvest all FL coastal strips."""
    import logging
    import time
    from agents.hunter import _harvest_to_cache, _is_area_harvested
    from services.event_bus import EventStatus, EventType, emit

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    total = 0
    skipped = 0
    failed = 0
    try:
        for i, strip in enumerate(FL_HARVEST_AREAS):
            bbox = {
                "south": strip["south"], "north": strip["north"],
                "west": strip["west"], "east": strip["east"],
            }
            if _is_area_harvested(bbox, db):
                skipped += 1
                continue

            logger.info(f"Harvesting {strip['name']} ({i+1}/{len(FL_HARVEST_AREAS)})...")
            emit(EventType.HUNTER, "bulk_harvest", EventStatus.PENDING,
                 detail=f"({i+1}/{len(FL_HARVEST_AREAS)}) {strip['name']}...")
            try:
                cached = _harvest_to_cache(bbox, db, region_name=strip["name"])
                total += cached
            except Exception as e:
                failed += 1
                logger.warning(f"Harvest failed for {strip['name']}: {e}")
                emit(EventType.HUNTER, "bulk_harvest_area_failed", EventStatus.ERROR,
                     detail=f"{strip['name']}: {str(e)[:100]}")

            # 15s between areas — Overpass rate limits aggressively
            time.sleep(15)

        detail = f"Bulk harvest done: {total} buildings cached, {skipped} skipped, {failed} failed"
        emit(EventType.HUNTER, "bulk_harvest", EventStatus.SUCCESS, detail=detail)
        logger.info(detail)
    except Exception as e:
        logger.error(f"Bulk harvest failed: {e}")
        emit(EventType.HUNTER, "bulk_harvest", EventStatus.ERROR,
             detail=str(e)[:200])
    finally:
        db.close()


@router.post("/api/admin/harvest")
def trigger_bulk_harvest():
    """Trigger bulk harvest of all FL coastal areas. Runs in background."""
    thread = threading.Thread(target=_run_bulk_harvest, daemon=True)
    thread.start()
    return {
        "success": True,
        "message": f"Bulk harvest started for {len(FL_HARVEST_AREAS)} areas across 11 counties",
        "areas": [s["name"] for s in FL_HARVEST_AREAS],
    }


@router.get("/api/admin/harvest/status")
def get_harvest_status(db: Session = Depends(get_db)):
    """Get harvest cache statistics."""
    from database.models import OsmBuilding, OsmHarvestArea
    total_buildings = db.query(OsmBuilding).count()
    total_areas = db.query(OsmHarvestArea).count()
    promoted = db.query(OsmBuilding).filter(OsmBuilding.promoted_entity_id.isnot(None)).count()
    by_county = db.execute(
        sa.text("SELECT county, COUNT(*) as cnt FROM osm_buildings WHERE county IS NOT NULL GROUP BY county ORDER BY cnt DESC")
    ).fetchall() if total_buildings > 0 else []
    areas = db.query(OsmHarvestArea).order_by(OsmHarvestArea.harvested_at.desc()).all()
    return {
        "total_buildings_cached": total_buildings,
        "total_areas_harvested": total_areas,
        "buildings_promoted_to_leads": promoted,
        "by_county": [{"county": r[0], "count": r[1]} for r in by_county],
        "areas": [
            {"name": a.name, "count": a.building_count, "harvested_at": a.harvested_at.isoformat()}
            for a in areas
        ],
    }


@router.get("/api/admin/query")
def query_data(
    q: str = Query(""),
    table: str = Query("entities"),
    county: str = Query(""),
    stage: str = Query(""),
    limit: int = Query(50),
    db: Session = Depends(get_db),
):
    """Guided data query — search entities, osm_buildings, or contacts.

    Supports simple NLP-style queries like:
    - "condos in Pinellas with 7+ stories"
    - "fire resistive buildings in Miami-Dade"
    - "all contacts for Clearwater"
    """
    from database.models import Contact, Entity, OsmBuilding

    results = []

    if table == "osm_cache":
        query = db.query(OsmBuilding)
        if county:
            query = query.filter(OsmBuilding.county.ilike(f"%{county}%"))
        if q:
            # Parse simple NLP patterns
            q_lower = q.lower()
            # Stories filter
            import re
            stories_match = re.search(r'(\d+)\+?\s*(?:stories|floors|levels)', q_lower)
            if stories_match:
                min_stories = int(stories_match.group(1))
                query = query.filter(OsmBuilding.stories >= min_stories)
            # Construction filter
            if "fire resistive" in q_lower:
                query = query.filter(OsmBuilding.construction_class.ilike("%fire resistive%"))
            elif "non-combustible" in q_lower or "non combustible" in q_lower:
                query = query.filter(
                    OsmBuilding.construction_class.ilike("%fire resistive%") |
                    OsmBuilding.construction_class.ilike("%non-combustible%")
                )
            # Name/address search
            name_search = re.sub(r'\d+\+?\s*(?:stories|floors|levels|fire resistive|non.combustible|masonry|frame)', '', q_lower).strip()
            if name_search and len(name_search) > 2:
                query = query.filter(
                    OsmBuilding.name.ilike(f"%{name_search}%") |
                    OsmBuilding.address.ilike(f"%{name_search}%")
                )
        total = query.count()
        rows = query.order_by(OsmBuilding.stories.desc().nullslast()).limit(limit).all()
        results = [{
            "osm_id": r.osm_id, "name": r.name, "address": r.address,
            "county": r.county, "building_type": r.building_type,
            "stories": r.stories, "construction_class": r.construction_class,
            "tiv_estimate": r.tiv_estimate, "units_estimate": r.units_estimate,
            "promoted": r.promoted_entity_id is not None,
        } for r in rows]
        return {"table": "osm_cache", "total": total, "showing": len(results), "results": results}

    elif table == "contacts":
        query = db.query(Contact).join(Entity, Contact.entity_id == Entity.id)
        if county:
            query = query.filter(Entity.county.ilike(f"%{county}%"))
        if q:
            query = query.filter(
                Contact.name.ilike(f"%{q}%") |
                Contact.title.ilike(f"%{q}%") |
                Contact.email.ilike(f"%{q}%")
            )
        total = query.count()
        rows = query.limit(limit).all()
        results = [{
            "id": c.id, "entity_id": c.entity_id, "name": c.name,
            "title": c.title, "email": c.email, "phone": c.phone,
            "source": c.source, "is_primary": c.is_primary,
        } for c in rows]
        return {"table": "contacts", "total": total, "showing": len(results), "results": results}

    else:  # entities (default)
        query = db.query(Entity)
        if county:
            query = query.filter(Entity.county.ilike(f"%{county}%"))
        if stage:
            query = query.filter(Entity.pipeline_stage == stage)
        if q:
            query = query.filter(
                Entity.name.ilike(f"%{q}%") |
                Entity.address.ilike(f"%{q}%")
            )
        total = query.count()
        rows = query.order_by(Entity.created_at.desc()).limit(limit).all()
        results = [{
            "id": e.id, "name": e.name, "address": e.address,
            "county": e.county, "pipeline_stage": e.pipeline_stage,
            "characteristics_keys": list((e.characteristics or {}).keys()),
            "sources": list((e.enrichment_sources or {}).keys()),
            "created_at": e.created_at.isoformat(),
        } for e in rows]
        return {"table": "entities", "total": total, "showing": len(results), "results": results}
