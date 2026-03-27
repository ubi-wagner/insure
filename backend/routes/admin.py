from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter()


@router.post("/api/admin/seed")
def run_seed(db: Session = Depends(get_db)):
    """Trigger the seed script to populate mock data."""
    from scripts.seed import seed
    seed()
    return {"success": True, "message": "Seed complete"}
