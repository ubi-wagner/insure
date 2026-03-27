from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from database.models import RegionOfInterest, RegionStatus

router = APIRouter()


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
    db_region = RegionOfInterest(
        name=region.name,
        bounding_box=region.bounding_box.model_dump(),
        parameters=region.parameters.model_dump() if region.parameters else {},
        status=RegionStatus.PENDING,
    )
    db.add(db_region)
    db.commit()
    db.refresh(db_region)
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
