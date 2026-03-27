from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from database.models import ActionType, Entity, EntityAsset, LeadLedger

router = APIRouter()


class VoteRequest(BaseModel):
    action_type: str


@router.get("/api/leads")
def list_leads(sort_by: str = "date", db: Session = Depends(get_db)):
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

    return results


@router.get("/api/leads/{entity_id}")
def get_lead(entity_id: int, db: Session = Depends(get_db)):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        return {"error": "Not found"}, 404

    assets = db.query(EntityAsset).filter(EntityAsset.entity_id == entity_id).all()
    contacts = entity.contacts

    characteristics = entity.characteristics or {}

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
        return {"error": "Not found"}, 404

    action = ActionType(vote.action_type)

    ledger_event = LeadLedger(entity_id=entity_id, action_type=action)
    db.add(ledger_event)
    db.commit()

    # If thumbed up, trigger the deep dive analysis (async in production)
    if action == ActionType.USER_THUMB_UP:
        try:
            from services.ai_analyzer import trigger_deep_dive
            trigger_deep_dive(entity_id, db)
        except Exception as e:
            print(f"Deep dive failed (non-blocking): {e}")

    return {"success": True, "action": action.value}
