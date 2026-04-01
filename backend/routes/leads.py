import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from database.models import ActionType, Entity, EntityAsset, LeadLedger
from services.event_bus import EventStatus, EventType, emit

router = APIRouter()
logger = logging.getLogger(__name__)


class VoteRequest(BaseModel):
    action_type: str


@router.get("/api/leads")
def list_leads(sort_by: str = "date", db: Session = Depends(get_db)):
    if sort_by not in ("date", "coast_distance"):
        raise HTTPException(status_code=400, detail="sort_by must be 'date' or 'coast_distance'")

    start = time.time()
    query = db.query(Entity)

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
            status = "CANDIDATE"
        elif latest_vote and latest_vote.action_type == ActionType.USER_THUMB_DOWN:
            status = "REJECTED"
        else:
            status = "NEW"

        characteristics = entity.characteristics or {}

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
                "status": status,
                "emails": characteristics.get("emails"),
            }
        )

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
