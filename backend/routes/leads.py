import logging
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from database.models import ActionType, Entity, EntityAsset, LeadLedger
from services.event_bus import EventStatus, EventType, emit

router = APIRouter()
logger = logging.getLogger(__name__)


class VoteRequest(BaseModel):
    action_type: str


def _parse_dollar(val: str | None) -> float | None:
    """Parse a dollar string like '$1,234,567' into a float."""
    if not val:
        return None
    cleaned = re.sub(r'[^\d.]', '', str(val))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _compute_wind_ratio(characteristics: dict) -> float | None:
    """Compute wind premium as ratio of TIV (lower = hotter lead)."""
    premium = _parse_dollar(characteristics.get("premium"))
    tiv = _parse_dollar(characteristics.get("tiv"))
    if premium and tiv and tiv > 0:
        return round(premium / tiv * 100, 3)  # percentage
    return None


def _compute_heat_score(characteristics: dict) -> str:
    """Score a lead: hot, warm, cool based on available intel."""
    wind_ratio = _compute_wind_ratio(characteristics)
    has_carrier = bool(characteristics.get("carrier"))
    has_premium = bool(_parse_dollar(characteristics.get("premium")))
    has_tiv = bool(_parse_dollar(characteristics.get("tiv")))

    if wind_ratio is not None:
        if wind_ratio >= 3.0:
            return "hot"     # High premium/TIV = pain point = opportunity
        elif wind_ratio >= 1.5:
            return "warm"
        else:
            return "cool"
    elif has_carrier and has_premium:
        return "warm"
    elif has_carrier:
        return "cool"
    return "none"


@router.get("/api/leads")
def list_leads(
    sort_by: str = Query("date"),
    status_filter: Optional[str] = Query(None),
    county: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    min_tiv: Optional[float] = Query(None),
    max_tiv: Optional[float] = Query(None),
    min_premium: Optional[float] = Query(None),
    max_premium: Optional[float] = Query(None),
    heat: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if sort_by not in ("date", "coast_distance", "wind_ratio", "premium", "tiv"):
        raise HTTPException(status_code=400, detail="Invalid sort_by value")

    start = time.time()
    query = db.query(Entity)

    # Text search on name/address
    if search:
        query = query.filter(
            Entity.name.ilike(f"%{search}%") | Entity.address.ilike(f"%{search}%")
        )

    # County filter
    if county:
        query = query.filter(Entity.county.ilike(f"%{county}%"))

    if sort_by == "coast_distance":
        query = query.order_by(Entity.latitude.desc())
    else:
        query = query.order_by(Entity.created_at.desc())

    entities = query.all()
    results = []

    for entity in entities:
        latest_vote = (
            db.query(LeadLedger)
            .filter(
                LeadLedger.entity_id == entity.id,
                LeadLedger.action_type.in_([ActionType.USER_THUMB_UP, ActionType.USER_THUMB_DOWN]),
            )
            .order_by(LeadLedger.created_at.desc())
            .first()
        )

        if latest_vote and latest_vote.action_type == ActionType.USER_THUMB_UP:
            entity_status = "CANDIDATE"
        elif latest_vote and latest_vote.action_type == ActionType.USER_THUMB_DOWN:
            entity_status = "REJECTED"
        else:
            entity_status = "NEW"

        # Status filter
        if status_filter and entity_status != status_filter:
            continue

        characteristics = entity.characteristics or {}

        # Compute scoring fields
        wind_ratio = _compute_wind_ratio(characteristics)
        heat_score = _compute_heat_score(characteristics)
        premium_val = _parse_dollar(characteristics.get("premium"))
        tiv_val = _parse_dollar(characteristics.get("tiv"))

        # Carrier filter
        if carrier and carrier.lower() not in (characteristics.get("carrier") or "").lower():
            continue

        # TIV range filter
        if min_tiv and (tiv_val is None or tiv_val < min_tiv):
            continue
        if max_tiv and (tiv_val is None or tiv_val > max_tiv):
            continue

        # Premium range filter
        if min_premium and (premium_val is None or premium_val < min_premium):
            continue
        if max_premium and (premium_val is None or premium_val > max_premium):
            continue

        # Heat filter
        if heat and heat_score != heat:
            continue

        results.append(
            {
                "id": entity.id,
                "name": entity.name,
                "address": entity.address or "",
                "county": entity.county or "",
                "latitude": entity.latitude,
                "longitude": entity.longitude,
                "characteristics": characteristics,
                "created_at": entity.created_at.isoformat(),
                "status": entity_status,
                "emails": characteristics.get("emails"),
                # Scoring fields
                "wind_ratio": wind_ratio,
                "heat_score": heat_score,
                "premium_parsed": premium_val,
                "tiv_parsed": tiv_val,
            }
        )

    # Sort by computed fields
    if sort_by == "wind_ratio":
        results.sort(key=lambda r: r["wind_ratio"] or 0, reverse=True)
    elif sort_by == "premium":
        results.sort(key=lambda r: r["premium_parsed"] or 0, reverse=True)
    elif sort_by == "tiv":
        results.sort(key=lambda r: r["tiv_parsed"] or 0, reverse=True)

    duration_ms = round((time.time() - start) * 1000, 1)
    emit(EventType.DB_OPERATION, "list_leads", EventStatus.SUCCESS,
         detail=f"{len(results)} entities, sort={sort_by}", duration_ms=duration_ms)

    return results


@router.get("/api/leads/{entity_id}")
def get_lead(entity_id: int, db: Session = Depends(get_db)):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        emit(EventType.DB_OPERATION, "get_lead", EventStatus.ERROR, detail=f"Entity {entity_id} not found")
        raise HTTPException(status_code=404, detail="Entity not found")

    assets = db.query(EntityAsset).filter(EntityAsset.entity_id == entity_id).all()
    contacts = entity.contacts
    characteristics = entity.characteristics or {}

    emit(EventType.DB_OPERATION, "get_lead", EventStatus.SUCCESS,
         detail=f"Entity {entity_id}: {entity.name}", entity_id=entity_id)

    return {
        "id": entity.id,
        "name": entity.name,
        "address": entity.address,
        "county": entity.county,
        "latitude": entity.latitude,
        "longitude": entity.longitude,
        "characteristics": characteristics,
        "emails": characteristics.get("emails"),
        "wind_ratio": _compute_wind_ratio(characteristics),
        "heat_score": _compute_heat_score(characteristics),
        "premium_parsed": _parse_dollar(characteristics.get("premium")),
        "tiv_parsed": _parse_dollar(characteristics.get("tiv")),
        "assets": [
            {
                "id": a.id,
                "doc_type": a.doc_type.value,
                "extracted_text": a.extracted_text,
            }
            for a in assets
        ],
        "contacts": [
            {"id": c.id, "name": c.name, "title": c.title}
            for c in contacts
        ],
    }


@router.post("/api/leads/{entity_id}/vote")
def vote_lead(entity_id: int, vote: VoteRequest, db: Session = Depends(get_db)):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        emit(EventType.DB_OPERATION, "vote_lead", EventStatus.ERROR,
             detail=f"Entity {entity_id} not found")
        raise HTTPException(status_code=404, detail="Entity not found")

    try:
        action = ActionType(vote.action_type)
    except ValueError:
        emit(EventType.API_CALL, "vote_lead", EventStatus.ERROR,
             detail=f"Invalid action_type: {vote.action_type}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action_type. Must be one of: {[e.value for e in ActionType]}"
        )

    ledger_event = LeadLedger(entity_id=entity_id, action_type=action)
    db.add(ledger_event)
    db.commit()

    emit(EventType.DB_OPERATION, "vote_lead", EventStatus.SUCCESS,
         detail=f"{action.value} on '{entity.name}'", entity_id=entity_id)

    # If thumbed up, trigger the deep dive analysis (non-blocking)
    if action == ActionType.USER_THUMB_UP:
        emit(EventType.AI_ANALYZER, "deep_dive_start", EventStatus.PENDING,
             detail=f"Starting for '{entity.name}'", entity_id=entity_id)
        try:
            from services.ai_analyzer import trigger_deep_dive
            trigger_deep_dive(entity_id, db)
        except Exception as e:
            logger.error(f"Deep dive failed for entity {entity_id}: {e}")
            emit(EventType.AI_ANALYZER, "deep_dive", EventStatus.ERROR,
                 detail=str(e)[:200], entity_id=entity_id)

    return {"success": True, "action": action.value}
