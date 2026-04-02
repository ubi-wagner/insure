import logging
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from database.models import Entity, RegionOfInterest, RegionStatus
from services.event_bus import EventStatus, EventType, emit

router = APIRouter()
logger = logging.getLogger(__name__)


class BoundingBox(BaseModel):
    north: float
    south: float
    east: float
    west: float


class RegionParams(BaseModel):
    stories: int = 3
    coast_distance: float = 5.0
    construction_filter: str = "any"
    search_profile: str = "custom"


class RegionCreate(BaseModel):
    name: str
    bounding_box: BoundingBox
    parameters: RegionParams | None = None


def _process_region_background(region_id: int):
    """Process a region in a background thread — called immediately on creation."""
    db = SessionLocal()
    try:
        region = db.query(RegionOfInterest).filter(RegionOfInterest.id == region_id).first()
        if not region or region.status != RegionStatus.PENDING:
            return
        from agents.hunter import process_region
        process_region(region, db)
    except Exception as e:
        logger.error(f"Background region processing failed for region {region_id}: {e}")
        emit(EventType.HUNTER, "process_region", EventStatus.ERROR,
             detail=f"Background processing failed: {str(e)[:200]}")
    finally:
        db.close()


@router.post("/api/regions")
def create_region(region: RegionCreate, db: Session = Depends(get_db)):
    bb = region.bounding_box
    if bb.north <= bb.south:
        raise HTTPException(status_code=400, detail="north must be greater than south")
    if bb.east <= bb.west:
        raise HTTPException(status_code=400, detail="east must be greater than west")

    start = time.time()
    try:
        db_region = RegionOfInterest(
            name=region.name,
            bounding_box=bb.model_dump(),
            parameters=region.parameters.model_dump() if region.parameters else {},
            status=RegionStatus.PENDING,
        )
        db.add(db_region)
        db.commit()
        db.refresh(db_region)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Failed to create region: {e}")
        emit(EventType.DB_OPERATION, "create_region", EventStatus.ERROR,
             detail=str(e)[:200], region_name=region.name)
        raise HTTPException(status_code=500, detail="Failed to create region")

    duration_ms = round((time.time() - start) * 1000, 1)
    emit(EventType.DB_OPERATION, "create_region", EventStatus.SUCCESS,
         detail=f"Region '{db_region.name}' created (id={db_region.id})",
         duration_ms=duration_ms, region_id=db_region.id)

    # Start processing immediately in background thread (don't wait for poll)
    thread = threading.Thread(
        target=_process_region_background,
        args=(db_region.id,),
        daemon=True,
    )
    thread.start()

    return {"id": db_region.id, "name": db_region.name, "status": db_region.status.value}


@router.get("/api/regions/{region_id}")
def get_region(region_id: int, db: Session = Depends(get_db)):
    """Get region status + count of discovered leads."""
    region = db.query(RegionOfInterest).filter(RegionOfInterest.id == region_id).first()
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")

    # Count leads discovered in this region's bounding box
    bbox = region.bounding_box or {}
    lead_count = 0
    if bbox:
        lead_count = db.query(Entity).filter(
            Entity.latitude >= bbox.get("south", 0),
            Entity.latitude <= bbox.get("north", 0),
            Entity.longitude >= bbox.get("west", 0),
            Entity.longitude <= bbox.get("east", 0),
        ).count()

    return {
        "id": region.id,
        "name": region.name,
        "bounding_box": region.bounding_box,
        "parameters": region.parameters,
        "status": region.status.value,
        "lead_count": lead_count,
        "created_at": region.created_at.isoformat(),
    }


@router.get("/api/regions")
def list_regions(db: Session = Depends(get_db)):
    regions = db.query(RegionOfInterest).order_by(RegionOfInterest.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "bounding_box": r.bounding_box,
            "parameters": r.parameters,
            "status": r.status.value,
            "target_county": r.target_county,
            "created_at": r.created_at.isoformat(),
        }
        for r in regions
    ]
