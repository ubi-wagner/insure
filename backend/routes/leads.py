import logging
import os
import re
import time
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Float, or_

from database import get_db
from database.models import ActionType, Contact, DocType, Entity, EntityAsset, Engagement, LeadLedger, Policy
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
        return round(premium / tiv * 100, 3)
    return None


def _compute_heat_score(characteristics: dict) -> str:
    score = 0
    wind_ratio = _compute_wind_ratio(characteristics)
    if wind_ratio is not None:
        if wind_ratio >= 3.0:
            score += 30
        elif wind_ratio >= 1.5:
            score += 15
        elif wind_ratio >= 0.5:
            score += 5

    if characteristics.get("carrier"):
        score += 10
    if _parse_dollar(characteristics.get("premium")):
        score += 10
    if _parse_dollar(characteristics.get("tiv")):
        score += 5

    flood_impact = characteristics.get("flood_score_impact")
    if flood_impact and isinstance(flood_impact, (int, float)):
        score += int(flood_impact)

    if characteristics.get("has_user_intel"):
        score += 25
    user_docs = characteristics.get("user_doc_types") or []
    if "DEC_PAGE" in user_docs:
        score += 10
    if "LOSS_RUN" in user_docs:
        score += 10

    if characteristics.get("decision_maker") or characteristics.get("sunbiz_registered_agent"):
        score += 10

    stories = characteristics.get("stories")
    if stories and isinstance(stories, (int, float)) and stories >= 7:
        score += 5

    if score >= 40:
        return "hot"
    elif score >= 20:
        return "warm"
    elif score >= 5:
        return "cool"
    return "cold"


# JSONB helper for numeric extraction
def _jsonb_float(field: str):
    """Extract a JSONB field as a float for SQL sorting/filtering."""
    return cast(
        func.nullif(
            func.regexp_replace(
                Entity.characteristics[field].astext,
                r'[^\d.]', '', 'g'
            ),
            ''
        ),
        Float
    )


def _jsonb_int(field: str):
    """Extract a JSONB field as integer for SQL filtering."""
    return cast(
        func.nullif(
            func.regexp_replace(
                Entity.characteristics[field].astext,
                r'[^\d]', '', 'g'
            ),
            ''
        ),
        Float  # Use float to handle nulls, cast in comparison
    )


@router.get("/api/leads")
def list_leads(
    sort_by: str = Query("date"),
    sort_dir: str = Query("desc"),
    status_filter: Optional[str] = Query(None),
    county: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    min_tiv: Optional[float] = Query(None),
    max_tiv: Optional[float] = Query(None),
    min_premium: Optional[float] = Query(None),
    max_premium: Optional[float] = Query(None),
    min_value: Optional[float] = Query(None),
    max_value: Optional[float] = Query(None),
    min_stories: Optional[int] = Query(None),
    min_units: Optional[int] = Query(None),
    min_year: Optional[int] = Query(None),
    use_code: Optional[str] = Query(None),
    heat: Optional[str] = Query(None),
    on_citizens: Optional[bool] = Query(None),
    cream_tier: Optional[str] = Query(None),
    min_cream: Optional[int] = Query(None),
    construction: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    valid_sorts = ("date", "value", "tiv", "units", "year_built", "stories",
                   "coast_distance", "wind_ratio", "premium", "name", "cream")
    if sort_by not in valid_sorts:
        raise HTTPException(status_code=400, detail=f"Invalid sort_by. Must be one of: {list(valid_sorts)}")

    start = time.time()
    query = db.query(Entity)

    # Stage filter (SQL)
    if status_filter:
        query = query.filter(Entity.pipeline_stage == status_filter)

    # Text search on name/address/owner
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                Entity.name.ilike(pattern),
                Entity.address.ilike(pattern),
                Entity.characteristics["dor_owner"].astext.ilike(pattern),
            )
        )

    # County filter (SQL)
    if county:
        query = query.filter(Entity.county.ilike(f"%{county}%"))

    # Heat score filter (SQL)
    if heat:
        query = query.filter(Entity.heat_score == heat)

    # DOR use code filter
    if use_code:
        query = query.filter(Entity.characteristics["dor_use_code"].astext == use_code)

    # Citizens insurance filter
    if on_citizens is True:
        query = query.filter(Entity.characteristics["on_citizens"].astext == "true")
    elif on_citizens is False:
        query = query.filter(
            or_(
                Entity.characteristics["on_citizens"].astext != "true",
                Entity.characteristics["on_citizens"].is_(None),
            )
        )

    # Cream tier filter
    if cream_tier:
        query = query.filter(Entity.characteristics["cream_tier"].astext == cream_tier)
    if min_cream is not None:
        query = query.filter(_jsonb_int("cream_score") >= min_cream)

    # Market value filter (dor_market_value is stored as integer in JSONB)
    if min_value is not None:
        query = query.filter(_jsonb_int("dor_market_value") >= min_value)
    if max_value is not None:
        query = query.filter(_jsonb_int("dor_market_value") <= max_value)

    # TIV filter
    if min_tiv is not None:
        query = query.filter(_jsonb_float("tiv") >= min_tiv)
    if max_tiv is not None:
        query = query.filter(_jsonb_float("tiv") <= max_tiv)

    # Stories filter
    if min_stories is not None:
        query = query.filter(_jsonb_int("stories") >= min_stories)

    # Units filter
    if min_units is not None:
        query = query.filter(_jsonb_int("dor_num_units") >= min_units)

    # Year built filter
    if min_year is not None:
        query = query.filter(_jsonb_int("dor_year_built") >= min_year)

    # Construction class filter (SQL)
    if construction:
        cc_col = Entity.characteristics["dor_construction_class"].astext
        if construction == "fire_resistive":
            query = query.filter(cc_col.ilike("%fire resistive%"))
        elif construction == "non_combustible":
            query = query.filter(
                cc_col.ilike("%fire resistive%") | cc_col.ilike("%non-combustible%") | cc_col.ilike("%non combustible%")
            )
        elif construction == "masonry":
            query = query.filter(cc_col.ilike("%masonry%"))
        elif construction == "frame":
            query = query.filter(cc_col.ilike("%frame%"))

    # Carrier filter
    if carrier:
        query = query.filter(Entity.characteristics["carrier"].astext.ilike(f"%{carrier}%"))

    # Premium filter
    if min_premium is not None:
        query = query.filter(_jsonb_float("premium") >= min_premium)
    if max_premium is not None:
        query = query.filter(_jsonb_float("premium") <= max_premium)

    # Get total before pagination
    total = query.count()

    # Sorting (SQL)
    is_desc = sort_dir == "desc"
    if sort_by == "value":
        order_col = _jsonb_int("dor_market_value")
        query = query.order_by(order_col.desc().nullslast() if is_desc else order_col.asc().nullsfirst())
    elif sort_by == "tiv":
        order_col = _jsonb_float("tiv")
        query = query.order_by(order_col.desc().nullslast() if is_desc else order_col.asc().nullsfirst())
    elif sort_by == "units":
        order_col = _jsonb_int("dor_num_units")
        query = query.order_by(order_col.desc().nullslast() if is_desc else order_col.asc().nullsfirst())
    elif sort_by == "year_built":
        order_col = _jsonb_int("dor_year_built")
        query = query.order_by(order_col.desc().nullslast() if is_desc else order_col.asc().nullsfirst())
    elif sort_by == "stories":
        order_col = _jsonb_int("stories")
        query = query.order_by(order_col.desc().nullslast() if is_desc else order_col.asc().nullsfirst())
    elif sort_by == "coast_distance":
        query = query.order_by(Entity.latitude.desc() if is_desc else Entity.latitude.asc())
    elif sort_by == "cream":
        order_col = _jsonb_int("cream_score")
        query = query.order_by(order_col.desc().nullslast() if is_desc else order_col.asc().nullsfirst())
    elif sort_by == "name":
        query = query.order_by(Entity.name.asc() if not is_desc else Entity.name.desc())
    elif sort_by in ("wind_ratio", "premium"):
        # These require computed values — sort by TIV as proxy
        order_col = _jsonb_float("tiv")
        query = query.order_by(order_col.desc().nullslast() if is_desc else order_col.asc().nullsfirst())
    else:
        query = query.order_by(Entity.created_at.desc() if is_desc else Entity.created_at.asc())

    # Pagination
    entities = query.offset(offset).limit(limit).all()

    results = []
    for entity in entities:
        characteristics = entity.characteristics or {}
        wind_ratio = _compute_wind_ratio(characteristics)
        heat_score = entity.heat_score or "cold"
        premium_val = _parse_dollar(characteristics.get("premium"))
        tiv_val = _parse_dollar(characteristics.get("tiv"))

        results.append({
            "id": entity.id,
            "name": entity.name,
            "address": entity.address or "",
            "county": entity.county or "",
            "latitude": entity.latitude,
            "longitude": entity.longitude,
            "characteristics": characteristics,
            "created_at": entity.created_at.isoformat() if entity.created_at else None,
            "status": entity.pipeline_stage or "TARGET",
            "pipeline_stage": entity.pipeline_stage,
            "parent_id": entity.parent_id,
            "emails": characteristics.get("emails"),
            "wind_ratio": wind_ratio,
            "heat_score": heat_score,
            "premium_parsed": premium_val,
            "tiv_parsed": tiv_val,
            "enrichment_status": entity.enrichment_status or "idle",
            "cream_score": characteristics.get("cream_score"),
            "cream_tier": characteristics.get("cream_tier"),
        })

    duration_ms = round((time.time() - start) * 1000, 1)
    emit(EventType.DB_OPERATION, "list_leads", EventStatus.SUCCESS,
         detail=f"{len(results)} of {total} entities, sort={sort_by}", duration_ms=duration_ms)

    return {"results": results, "total": total, "limit": limit, "offset": offset}


# ─── Bulk Stage Change ───

class BulkStageRequest(BaseModel):
    entity_ids: List[int] = []  # Max 1000 per request
    stage: str
    filter_stage: Optional[str] = None
    filter_county: Optional[str] = None
    filter_min_value: Optional[float] = None
    filter_max_value: Optional[float] = None
    filter_min_stories: Optional[int] = None
    filter_min_units: Optional[int] = None
    filter_use_code: Optional[str] = None


@router.post("/api/leads/bulk-stage")
def bulk_stage_change(req: BulkStageRequest, db: Session = Depends(get_db)):
    """Change pipeline stage for multiple entities at once.

    Can specify explicit entity_ids OR use filters to match entities.
    """
    valid_stages = ["TARGET", "LEAD", "OPPORTUNITY", "CUSTOMER", "ARCHIVED"]
    if req.stage not in valid_stages:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Must be one of: {valid_stages}")

    if req.entity_ids:
        if len(req.entity_ids) > 1000:
            raise HTTPException(status_code=400, detail="Max 1000 entity_ids per request")
        query = db.query(Entity).filter(Entity.id.in_(req.entity_ids))
    else:
        # Filter-based — require at least one filter to prevent updating ALL entities
        has_filter = any([req.filter_stage, req.filter_county, req.filter_min_value is not None,
                         req.filter_max_value is not None, req.filter_min_stories is not None,
                         req.filter_min_units is not None, req.filter_use_code])
        if not has_filter:
            raise HTTPException(status_code=400, detail="Must provide entity_ids or at least one filter")
        query = db.query(Entity)
        if req.filter_stage:
            query = query.filter(Entity.pipeline_stage == req.filter_stage)
        if req.filter_county:
            query = query.filter(Entity.county.ilike(f"%{req.filter_county}%"))
        if req.filter_min_value is not None:
            query = query.filter(_jsonb_int("dor_market_value") >= req.filter_min_value)
        if req.filter_max_value is not None:
            query = query.filter(_jsonb_int("dor_market_value") <= req.filter_max_value)
        if req.filter_min_stories is not None:
            query = query.filter(_jsonb_int("stories") >= req.filter_min_stories)
        if req.filter_min_units is not None:
            query = query.filter(_jsonb_int("dor_num_units") >= req.filter_min_units)
        if req.filter_use_code:
            query = query.filter(Entity.characteristics["dor_use_code"].astext == req.filter_use_code)

    count = 0
    for entity in query.all():
        old_stage = entity.pipeline_stage
        if old_stage == req.stage:
            continue
        entity.pipeline_stage = req.stage
        if req.stage == "LEAD" and not entity.enrichment_status:
            entity.enrichment_status = "idle"
        count += 1

    if count > 0:
        db.commit()

    emit(EventType.DB_OPERATION, "bulk_stage_change", EventStatus.SUCCESS,
         detail=f"{count} entities → {req.stage}")

    return {"success": True, "changed": count, "stage": req.stage}


@router.get("/api/leads/{entity_id}")
def get_lead(entity_id: int, db: Session = Depends(get_db)):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        emit(EventType.DB_OPERATION, "get_lead", EventStatus.ERROR, detail=f"Entity {entity_id} not found")
        raise HTTPException(status_code=404, detail="Entity not found")

    assets = db.query(EntityAsset).filter(EntityAsset.entity_id == entity_id).all()
    policies = db.query(Policy).filter(Policy.entity_id == entity_id).order_by(Policy.is_active.desc()).all()
    engagements_list = db.query(Engagement).filter(Engagement.entity_id == entity_id).order_by(Engagement.created_at.desc()).all()
    contacts = entity.contacts or []
    children = entity.children or []
    characteristics = entity.characteristics or {}

    active_wind = next((p for p in policies if p.coverage_type == "WIND" and p.is_active), None)
    if active_wind and active_wind.premium and active_wind.tiv and active_wind.tiv > 0:
        wind_ratio = round(active_wind.premium / active_wind.tiv * 100, 3)
    else:
        wind_ratio = _compute_wind_ratio(characteristics)

    heat_score = _compute_heat_score(characteristics)

    emit(EventType.DB_OPERATION, "get_lead", EventStatus.SUCCESS,
         detail=f"Entity {entity_id}: {entity.name}", entity_id=entity_id)

    return {
        "id": entity.id,
        "parent_id": entity.parent_id,
        "name": entity.name or "",
        "address": entity.address or "",
        "county": entity.county or "",
        "latitude": entity.latitude,
        "longitude": entity.longitude,
        "pipeline_stage": entity.pipeline_stage,
        "status": entity.pipeline_stage,  # Alias for frontend compatibility
        "enrichment_status": entity.enrichment_status,
        "created_at": entity.created_at.isoformat() if entity.created_at else None,
        "characteristics": characteristics,
        "emails": characteristics.get("emails"),
        "wind_ratio": wind_ratio,
        "heat_score": heat_score,
        "premium_parsed": active_wind.premium if active_wind else _parse_dollar(characteristics.get("premium")),
        "tiv_parsed": active_wind.tiv if active_wind else _parse_dollar(characteristics.get("tiv")),
        "policies": [
            {
                "id": p.id, "coverage_type": p.coverage_type, "carrier": p.carrier,
                "policy_number": p.policy_number, "premium": p.premium, "tiv": p.tiv,
                "deductible": p.deductible, "expiration": p.expiration,
                "prior_premium": p.prior_premium, "premium_increase_pct": p.premium_increase_pct,
                "is_active": p.is_active, "notes": p.notes,
            }
            for p in policies
        ],
        "engagements": [
            {
                "id": eng.id, "type": eng.engagement_type, "channel": eng.channel,
                "status": eng.status, "subject": eng.subject, "body": eng.body,
                "style": eng.style,
                "sent_at": eng.sent_at.isoformat() if eng.sent_at else None,
                "responded_at": eng.responded_at.isoformat() if eng.responded_at else None,
                "follow_up_at": eng.follow_up_at.isoformat() if eng.follow_up_at else None,
                "created_at": eng.created_at.isoformat() if eng.created_at else None,
            }
            for eng in engagements_list
        ],
        "assets": [
            {"id": a.id, "doc_type": a.doc_type.value, "extracted_text": a.extracted_text, "source": a.source, "filename": a.filename}
            for a in assets
        ],
        "contacts": [
            {"id": c.id, "name": c.name, "title": c.title, "email": c.email, "phone": c.phone, "is_primary": c.is_primary, "source": c.source, "source_url": c.source_url}
            for c in contacts
        ],
        "children": [
            {"id": ch.id, "name": ch.name, "address": ch.address, "pipeline_stage": ch.pipeline_stage}
            for ch in children
        ],
        "enrichment_sources": entity.enrichment_sources or {},
        "enrichment_status": entity.enrichment_status or "idle",
        "readiness": _compute_readiness(entity, db),
    }


@router.post("/api/leads/{entity_id}/vote")
def vote_lead(entity_id: int, vote: VoteRequest, db: Session = Depends(get_db)):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    try:
        action = ActionType(vote.action_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid action_type. Must be one of: {[e.value for e in ActionType]}")

    ledger_event = LeadLedger(entity_id=entity_id, action_type=action)
    db.add(ledger_event)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to record vote")

    return {"success": True, "action": action.value, "pipeline_stage": entity.pipeline_stage}


class CreateEngagementRequest(BaseModel):
    style: str
    subject: str
    body: str
    channel: str = "EMAIL"


@router.post("/api/leads/{entity_id}/engagements")
def create_engagement(entity_id: int, req: CreateEngagementRequest, db: Session = Depends(get_db)):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    engagement = Engagement(
        entity_id=entity_id, engagement_type="OUTREACH", channel=req.channel,
        status="QUEUED", subject=req.subject, body=req.body, style=req.style,
    )
    db.add(engagement)

    ledger = LeadLedger(
        entity_id=entity_id, action_type="ENGAGEMENT_CREATED",
        detail=f"Outreach queued: {req.style} via {req.channel}",
    )
    db.add(ledger)
    db.commit()
    db.refresh(engagement)

    return {"success": True, "engagement_id": engagement.id, "status": engagement.status}


def _compute_readiness(entity: Entity, db: Session) -> dict:
    chars = entity.characteristics or {}
    sources = entity.enrichment_sources or {}
    contacts = entity.contacts or []
    has_contacts = len(contacts) > 0
    has_primary_contact = any(c.is_primary for c in contacts)
    has_contact_email = any(c.email for c in contacts)
    has_carrier = bool(chars.get("carrier"))
    has_tiv = bool(chars.get("tiv") or chars.get("tiv_estimate"))
    has_flood = "fema_flood" in sources
    has_property_data = "fdot_parcels" in sources or "property_appraiser" in sources
    has_sunbiz = "sunbiz" in sources
    has_dbpr = "dbpr_bulk" in sources or "dbpr_condo" in sources
    has_decision_maker = bool(chars.get("decision_maker") or has_primary_contact)
    has_property_manager = bool(chars.get("property_manager") or chars.get("dbpr_management_company"))
    has_emails = bool(chars.get("emails"))

    return {
        "lead": {
            "ready": True,
            "checks": {
                "geocoded": {"done": bool(entity.latitude), "label": "Geocoded"},
                "flood_zone": {"done": has_flood, "label": "FEMA flood zone"},
                "tiv": {"done": has_tiv, "label": "TIV estimate"},
            },
        },
        "opportunity": {
            "ready": has_decision_maker and (has_emails or has_contact_email),
            "checks": {
                "decision_maker": {"done": has_decision_maker, "label": "Decision maker"},
                "contact_email": {"done": has_contact_email, "label": "Contact email"},
                "emails_generated": {"done": has_emails, "label": "Outreach emails"},
                "property_manager": {"done": has_property_manager, "label": "Property manager"},
                "dbpr_lookup": {"done": has_dbpr, "label": "DBPR checked"},
                "sunbiz": {"done": has_sunbiz, "label": "Sunbiz searched"},
            },
        },
    }


@router.get("/api/leads/{entity_id}/readiness")
def get_readiness(entity_id: int, db: Session = Depends(get_db)):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    return {
        "entity_id": entity_id,
        "current_stage": entity.pipeline_stage,
        "readiness": _compute_readiness(entity, db),
    }


class StageChangeRequest(BaseModel):
    stage: str
    force: bool = False
    assigned_by: str | None = None   # Display name of user making the change
    assigned_role: str | None = None # "admin" or "user"


@router.post("/api/leads/{entity_id}/stage")
def change_stage(entity_id: int, req: StageChangeRequest, db: Session = Depends(get_db)):
    valid_stages = ["TARGET", "LEAD", "OPPORTUNITY", "CUSTOMER", "ARCHIVED"]
    if req.stage not in valid_stages:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Must be one of: {valid_stages}")

    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    if req.stage in ("OPPORTUNITY", "CUSTOMER") and not req.force:
        readiness = _compute_readiness(entity, db)
        stage_key = req.stage.lower()
        if stage_key in readiness and not readiness[stage_key].get("ready", True):
            missing = [
                check["label"] for check in readiness[stage_key]["checks"].values() if not check["done"]
            ]
            raise HTTPException(status_code=422, detail={
                "error": "readiness_check_failed",
                "message": f"Not ready for {req.stage}. Missing: {', '.join(missing)}",
                "missing": missing,
            })

    old_stage = entity.pipeline_stage
    entity.pipeline_stage = req.stage

    # When moving to OPPORTUNITY or CUSTOMER, tag who claimed it
    if req.stage in ("OPPORTUNITY", "CUSTOMER") and req.assigned_by:
        chars = dict(entity.characteristics or {})
        chars["assigned_to"] = req.assigned_by
        chars["assigned_at"] = datetime.utcnow().isoformat()
        if req.assigned_role:
            chars["assigned_role"] = req.assigned_role
        entity.characteristics = chars

    detail_text = f"{old_stage} → {req.stage}"
    if req.assigned_by:
        detail_text += f" (by {req.assigned_by})"

    ledger = LeadLedger(entity_id=entity_id, action_type="STAGE_CHANGE", detail=detail_text)
    db.add(ledger)
    db.commit()

    emit(EventType.DB_OPERATION, "stage_change", EventStatus.SUCCESS,
         detail=f"'{entity.name}': {detail_text}", entity_id=entity_id)

    if req.stage == "LEAD":
        try:
            from agents.enrichers.pipeline import run_lead_enrichment
            run_lead_enrichment(entity, db)
        except Exception as e:
            logger.warning(f"Enrichment failed for entity {entity_id}: {e}")

    return {"success": True, "pipeline_stage": entity.pipeline_stage}


class CreateContactRequest(BaseModel):
    name: str
    title: str = ""
    email: str | None = None
    phone: str | None = None
    is_primary: int = 0


@router.post("/api/leads/{entity_id}/contacts")
def create_contact(entity_id: int, req: CreateContactRequest, db: Session = Depends(get_db)):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    contact = Contact(
        entity_id=entity_id, name=req.name, title=req.title,
        email=req.email, phone=req.phone, is_primary=req.is_primary,
    )
    db.add(contact)

    ledger = LeadLedger(entity_id=entity_id, action_type="CONTACT_ADDED", detail=f"Added contact: {req.name} ({req.title})")
    db.add(ledger)
    db.commit()
    db.refresh(contact)

    return {
        "success": True,
        "contact": {
            "id": contact.id, "name": contact.name, "title": contact.title,
            "email": contact.email, "phone": contact.phone, "is_primary": contact.is_primary,
        },
    }


@router.post("/api/leads/{entity_id}/upload")
async def upload_document(
    entity_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form("OTHER"),
    db: Session = Depends(get_db),
):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    valid_types = [dt.value for dt in DocType]
    if doc_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid doc_type. Must be one of: {valid_types}")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50MB max
        raise HTTPException(status_code=413, detail="File too large (max 50MB)")

    text_content = ""
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        text_content = f"[Binary file: {file.filename}, {len(content)} bytes]"

    safe_filename = os.path.basename(file.filename or "unnamed")

    asset = EntityAsset(
        entity_id=entity_id, doc_type=doc_type,
        extracted_text=text_content, source="user_upload", filename=safe_filename,
    )
    db.add(asset)

    ledger = LeadLedger(
        entity_id=entity_id, action_type="DOCUMENT_UPLOADED",
        detail=f"Uploaded {doc_type}: {safe_filename}", source="user_upload",
    )
    db.add(ledger)

    from agents.enrichers import record_enrichment
    record_enrichment(
        entity, db, source_id="user_upload",
        fields_updated=[f"document:{doc_type}:{safe_filename}"],
        detail=f"User uploaded {doc_type}: {safe_filename}",
    )

    chars = dict(entity.characteristics or {})
    if doc_type in ("BROCHURE", "DEC_PAGE", "LOSS_RUN"):
        chars["has_user_intel"] = True
        chars["user_doc_types"] = list(set((chars.get("user_doc_types") or []) + [doc_type]))
        entity.characteristics = chars

    try:
        db.commit()
        db.refresh(asset)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save document")

    return {"success": True, "asset_id": asset.id, "doc_type": doc_type, "filename": safe_filename}
