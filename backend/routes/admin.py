import threading

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db, SessionLocal

router = APIRouter()


@router.post("/api/admin/seed")
def run_seed(db: Session = Depends(get_db)):
    """Trigger the seed script to populate mock data."""
    from scripts.seed import seed
    seed()
    return {"success": True, "message": "Seed complete"}


# FL coastal bounding boxes for bulk harvest — covers beachfront strips
# Each box is ~5 miles of coastline, narrow (0.05° ≈ 3.5 miles inland)
FL_COASTAL_STRIPS = [
    {"name": "Clearwater Beach", "south": 27.94, "north": 28.01, "west": -82.84, "east": -82.79},
    {"name": "St Pete Beach", "south": 27.68, "north": 27.78, "west": -82.78, "east": -82.73},
    {"name": "Treasure Island", "south": 27.75, "north": 27.82, "west": -82.80, "east": -82.75},
    {"name": "Indian Rocks Beach", "south": 27.82, "north": 27.90, "west": -82.86, "east": -82.82},
    {"name": "Redington Beach", "south": 27.78, "north": 27.82, "west": -82.83, "east": -82.79},
    {"name": "Madeira Beach", "south": 27.77, "north": 27.80, "west": -82.82, "east": -82.78},
    {"name": "Sand Key / Belleair", "south": 27.90, "north": 27.94, "west": -82.85, "east": -82.81},
    {"name": "Sarasota / Lido Key", "south": 27.28, "north": 27.40, "west": -82.60, "east": -82.50},
    {"name": "Siesta Key", "south": 27.22, "north": 27.30, "west": -82.57, "east": -82.52},
    {"name": "Longboat Key", "south": 27.35, "north": 27.47, "west": -82.66, "east": -82.59},
    {"name": "Fort Myers Beach", "south": 26.40, "north": 26.50, "west": -82.00, "east": -81.92},
    {"name": "Naples / Marco", "south": 26.00, "north": 26.20, "west": -81.82, "east": -81.76},
    {"name": "Fort Lauderdale Beach", "south": 26.08, "north": 26.18, "west": -80.13, "east": -80.09},
    {"name": "Hollywood Beach", "south": 25.98, "north": 26.08, "west": -80.13, "east": -80.09},
    {"name": "Miami Beach", "south": 25.76, "north": 25.88, "west": -80.14, "east": -80.10},
    {"name": "Sunny Isles", "south": 25.93, "north": 25.97, "west": -80.13, "east": -80.10},
    {"name": "Palm Beach", "south": 26.66, "north": 26.76, "west": -80.06, "east": -80.02},
    {"name": "Boca Raton Beach", "south": 26.32, "north": 26.40, "west": -80.08, "east": -80.05},
    {"name": "Pompano Beach", "south": 26.20, "north": 26.28, "west": -80.10, "east": -80.06},
    {"name": "Deerfield Beach", "south": 26.28, "north": 26.34, "west": -80.10, "east": -80.06},
]


def _run_bulk_harvest():
    """Background job: harvest all FL coastal strips."""
    import logging
    from agents.hunter import _harvest_to_cache, _is_area_harvested
    from services.event_bus import EventStatus, EventType, emit

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    total = 0
    try:
        for strip in FL_COASTAL_STRIPS:
            bbox = {
                "south": strip["south"], "north": strip["north"],
                "west": strip["west"], "east": strip["east"],
            }
            if _is_area_harvested(bbox, db):
                logger.info(f"Skipping {strip['name']} — already harvested")
                continue

            logger.info(f"Harvesting {strip['name']}...")
            emit(EventType.HUNTER, "bulk_harvest", EventStatus.PENDING,
                 detail=f"Harvesting {strip['name']}...")
            cached = _harvest_to_cache(bbox, db, region_name=strip["name"])
            total += cached

            # Small delay between areas to be nice to Overpass
            import time
            time.sleep(5)

        emit(EventType.HUNTER, "bulk_harvest", EventStatus.SUCCESS,
             detail=f"Bulk harvest complete: {total} buildings cached across {len(FL_COASTAL_STRIPS)} coastal strips")
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
        "message": f"Bulk harvest started for {len(FL_COASTAL_STRIPS)} coastal strips",
        "strips": [s["name"] for s in FL_COASTAL_STRIPS],
    }


@router.get("/api/admin/harvest/status")
def get_harvest_status(db: Session = Depends(get_db)):
    """Get harvest cache statistics."""
    from database.models import OsmBuilding, OsmHarvestArea
    total_buildings = db.query(OsmBuilding).count()
    total_areas = db.query(OsmHarvestArea).count()
    promoted = db.query(OsmBuilding).filter(OsmBuilding.promoted_entity_id.isnot(None)).count()
    areas = db.query(OsmHarvestArea).order_by(OsmHarvestArea.harvested_at.desc()).all()
    return {
        "total_buildings_cached": total_buildings,
        "total_areas_harvested": total_areas,
        "buildings_promoted_to_leads": promoted,
        "areas": [
            {"name": a.name, "count": a.building_count, "harvested_at": a.harvested_at.isoformat()}
            for a in areas
        ],
    }
