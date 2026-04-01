import logging
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from database.models import ActionType, Contact, Entity, EntityAsset, Engagement, LeadLedger, Policy
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
    construction: Optional[str] = Query(None),
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
        # Use pipeline_stage from DB; fall back to vote-based for legacy
        entity_status = entity.pipeline_stage or "NEW"
        if entity_status == "NEW":
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

        # Construction class filter
        if construction:
            cc = (characteristics.get("construction_class") or "").lower()
            if construction == "fire_resistive" and "fire resistive" not in cc:
                continue
            elif construction == "non_combustible" and "fire resistive" not in cc and "non-combustible" not in cc:
                continue
            elif construction == "masonry" and "fire resistive" not in cc and "non-combustible" not in cc and "masonry" not in cc:
                continue
            elif construction == "frame" and "frame" not in cc:
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
                "pipeline_stage": entity.pipeline_stage,
                "parent_id": entity.parent_id,
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
    policies = db.query(Policy).filter(Policy.entity_id == entity_id).order_by(Policy.is_active.desc()).all()
    engagements_list = db.query(Engagement).filter(Engagement.entity_id == entity_id).order_by(Engagement.created_at.desc()).all()
    contacts = entity.contacts
    children = entity.children or []
    characteristics = entity.characteristics or {}

    # Compute wind ratio from Policy records if available, else from characteristics
    active_wind = next((p for p in policies if p.coverage_type == "WIND" and p.is_active), None)
    if active_wind and active_wind.premium and active_wind.tiv and active_wind.tiv > 0:
        wind_ratio = round(active_wind.premium / active_wind.tiv * 100, 3)
    else:
        wind_ratio = _compute_wind_ratio(characteristics)

    heat_score = _compute_heat_score(characteristics) if wind_ratio is None else (
        "hot" if wind_ratio >= 3.0 else "warm" if wind_ratio >= 1.5 else "cool"
    )

    emit(EventType.DB_OPERATION, "get_lead", EventStatus.SUCCESS,
         detail=f"Entity {entity_id}: {entity.name}", entity_id=entity_id)

    return {
        "id": entity.id,
        "parent_id": entity.parent_id,
        "name": entity.name,
        "address": entity.address,
        "county": entity.county,
        "latitude": entity.latitude,
        "longitude": entity.longitude,
        "pipeline_stage": entity.pipeline_stage,
        "characteristics": characteristics,
        "emails": characteristics.get("emails"),
        "wind_ratio": wind_ratio,
        "heat_score": heat_score,
        "premium_parsed": active_wind.premium if active_wind else _parse_dollar(characteristics.get("premium")),
        "tiv_parsed": active_wind.tiv if active_wind else _parse_dollar(characteristics.get("tiv")),
        "policies": [
            {
                "id": p.id,
                "coverage_type": p.coverage_type,
                "carrier": p.carrier,
                "policy_number": p.policy_number,
                "premium": p.premium,
                "tiv": p.tiv,
                "deductible": p.deductible,
                "expiration": p.expiration,
                "prior_premium": p.prior_premium,
                "premium_increase_pct": p.premium_increase_pct,
                "is_active": p.is_active,
                "notes": p.notes,
            }
            for p in policies
        ],
        "engagements": [
            {
                "id": eng.id,
                "type": eng.engagement_type,
                "channel": eng.channel,
                "status": eng.status,
                "subject": eng.subject,
                "body": eng.body,
                "style": eng.style,
                "sent_at": eng.sent_at.isoformat() if eng.sent_at else None,
                "responded_at": eng.responded_at.isoformat() if eng.responded_at else None,
                "follow_up_at": eng.follow_up_at.isoformat() if eng.follow_up_at else None,
                "created_at": eng.created_at.isoformat(),
            }
            for eng in engagements_list
        ],
        "assets": [
            {"id": a.id, "doc_type": a.doc_type.value, "extracted_text": a.extracted_text}
            for a in assets
        ],
        "contacts": [
            {"id": c.id, "name": c.name, "title": c.title, "email": c.email, "phone": c.phone, "is_primary": c.is_primary}
            for c in contacts
        ],
        "children": [
            {"id": ch.id, "name": ch.name, "address": ch.address, "pipeline_stage": ch.pipeline_stage}
            for ch in children
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

    # Update pipeline stage
    if action == ActionType.USER_THUMB_UP and entity.pipeline_stage == "NEW":
        entity.pipeline_stage = "CANDIDATE"
    elif action == ActionType.USER_THUMB_DOWN:
        entity.pipeline_stage = "ARCHIVED"

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

    return {"success": True, "action": action.value, "pipeline_stage": entity.pipeline_stage}


class CreateEngagementRequest(BaseModel):
    style: str
    subject: str
    body: str
    channel: str = "EMAIL"


@router.post("/api/leads/{entity_id}/engagements")
def create_engagement(entity_id: int, req: CreateEngagementRequest, db: Session = Depends(get_db)):
    """Create an outreach engagement from a generated email."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    engagement = Engagement(
        entity_id=entity_id,
        engagement_type="OUTREACH",
        channel=req.channel,
        status="QUEUED",
        subject=req.subject,
        body=req.body,
        style=req.style,
    )
    db.add(engagement)

    ledger = LeadLedger(
        entity_id=entity_id,
        action_type="ENGAGEMENT_CREATED",
        detail=f"Outreach queued: {req.style} via {req.channel}",
    )
    db.add(ledger)
    db.commit()
    db.refresh(engagement)

    emit(EventType.DB_OPERATION, "create_engagement", EventStatus.SUCCESS,
         detail=f"Engagement {engagement.id} for '{entity.name}' ({req.style})", entity_id=entity_id)

    return {"success": True, "engagement_id": engagement.id, "status": engagement.status}


class StageChangeRequest(BaseModel):
    stage: str


@router.post("/api/leads/{entity_id}/stage")
def change_stage(entity_id: int, req: StageChangeRequest, db: Session = Depends(get_db)):
    """Manually advance or change an entity's pipeline stage."""
    valid_stages = ["NEW", "CANDIDATE", "TARGET", "OPPORTUNITY", "CUSTOMER", "CHURNED", "ARCHIVED"]
    if req.stage not in valid_stages:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Must be one of: {valid_stages}")

    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    old_stage = entity.pipeline_stage
    entity.pipeline_stage = req.stage

    ledger = LeadLedger(
        entity_id=entity_id,
        action_type="STAGE_CHANGE",
        detail=f"{old_stage} → {req.stage}",
    )
    db.add(ledger)
    db.commit()

    emit(EventType.DB_OPERATION, "stage_change", EventStatus.SUCCESS,
         detail=f"'{entity.name}': {old_stage} → {req.stage}", entity_id=entity_id)

    return {"success": True, "pipeline_stage": entity.pipeline_stage}


class CreateContactRequest(BaseModel):
    name: str
    title: str = ""
    email: str | None = None
    phone: str | None = None
    is_primary: int = 0


@router.post("/api/leads/{entity_id}/contacts")
def create_contact(entity_id: int, req: CreateContactRequest, db: Session = Depends(get_db)):
    """Add a contact/decision maker to an entity."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    contact = Contact(
        entity_id=entity_id,
        name=req.name,
        title=req.title,
        email=req.email,
        phone=req.phone,
        is_primary=req.is_primary,
    )
    db.add(contact)

    ledger = LeadLedger(
        entity_id=entity_id,
        action_type="CONTACT_ADDED",
        detail=f"Added contact: {req.name} ({req.title})",
    )
    db.add(ledger)
    db.commit()
    db.refresh(contact)

    emit(EventType.DB_OPERATION, "create_contact", EventStatus.SUCCESS,
         detail=f"Contact '{req.name}' added to '{entity.name}'", entity_id=entity_id)

    return {
        "success": True,
        "contact": {
            "id": contact.id, "name": contact.name, "title": contact.title,
            "email": contact.email, "phone": contact.phone, "is_primary": contact.is_primary,
        },
    }
