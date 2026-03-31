import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db
from database.models import RegionOfInterest, RegionStatus

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


class RegionCreate(BaseModel):
    name: str
    bounding_box: BoundingBox
    parameters: RegionParams | None = None


@router.post("/api/regions")
def create_region(region: RegionCreate, db: Session = Depends(get_db)):
    bb = region.bounding_box
    if bb.north <= bb.south:
        raise HTTPException(status_code=400, detail="north must be greater than south")
    if bb.east <= bb.west:
        raise HTTPException(status_code=400, detail="east must be greater than west")

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
        raise HTTPException(status_code=500, detail="Failed to create region")

    return {"id": db_region.id, "name": db_region.name, "status": db_region.status.value}


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
            "created_at": r.created_at.isoformat(),
        }
        for r in regions
    ]
