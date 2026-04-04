"""Email export/import routes.

Outbound: CRM generates .eml files from queued engagements → Jason imports into Outlook.
Inbound:  Jason dumps Outlook replies → uploads here → CRM parses and matches to entities.
"""

import io
import logging
import os
import re
import zipfile
from datetime import datetime, timezone
from email import policy as email_policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from database.models import Contact, Entity, Engagement, LeadLedger
from services.event_bus import EventStatus, EventType, emit

router = APIRouter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Outbound — export queued engagements as .eml files for Outlook import
# ---------------------------------------------------------------------------

DEFAULT_FROM = os.environ.get("CRM_FROM_EMAIL", "broker@insure-crm.local")


def _build_eml(engagement: Engagement, entity: Entity, to_email: str, from_email: str) -> bytes:
    """Build an RFC 2822 .eml file from an engagement."""
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = engagement.subject or f"Insurance inquiry — {entity.name}"
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    # Custom headers for re-import matching
    msg["X-Insure-Entity-Id"] = str(entity.id)
    msg["X-Insure-Engagement-Id"] = str(engagement.id)
    msg.set_content(engagement.body or "", subtype="plain")
    return msg.as_bytes(policy=email_policy.SMTP)


@router.get("/api/email/export")
def export_emails(
    status: str = Query("QUEUED", description="Engagement status to export"),
    stage: Optional[str] = Query(None, description="Filter by pipeline stage"),
    county: Optional[str] = Query(None, description="Filter by county"),
    cream_tier: Optional[str] = Query(None, description="Filter by cream tier"),
    from_email: str = Query(DEFAULT_FROM, description="From address for .eml files"),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Export engagements as a .zip of .eml files ready for Outlook import.

    Each .eml targets the entity's primary contact email (or first available).
    Engagements without a matching contact email are skipped.
    Exported engagements are marked SENT.
    """
    query = (
        db.query(Engagement, Entity)
        .join(Entity, Engagement.entity_id == Entity.id)
        .filter(Engagement.status == status)
        .filter(Engagement.channel == "EMAIL")
    )
    if stage:
        query = query.filter(Entity.pipeline_stage == stage)
    if county:
        query = query.filter(Entity.county == county)
    if cream_tier:
        chars_filter = Entity.characteristics["cream_tier"].astext == cream_tier
        query = query.filter(chars_filter)

    rows = query.limit(limit).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No queued email engagements found matching filters")

    # Build zip of .eml files
    buf = io.BytesIO()
    exported_ids = []
    skipped = 0

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for engagement, entity in rows:
            # Find best contact email
            contacts = db.query(Contact).filter(Contact.entity_id == entity.id).all()
            to_email = None
            for c in sorted(contacts, key=lambda c: (-c.is_primary, c.id)):
                if c.email:
                    to_email = c.email
                    break

            if not to_email:
                skipped += 1
                continue

            eml_bytes = _build_eml(engagement, entity, to_email, from_email)
            # Sanitize filename
            safe_name = re.sub(r'[^\w\s-]', '', entity.name)[:60].strip()
            filename = f"{entity.id}_{safe_name}_{engagement.id}.eml"
            zf.writestr(filename, eml_bytes)
            exported_ids.append(engagement.id)

    # Mark exported engagements as SENT
    if exported_ids:
        now = datetime.now(timezone.utc)
        db.query(Engagement).filter(Engagement.id.in_(exported_ids)).update(
            {"status": "SENT", "sent_at": now}, synchronize_session="fetch"
        )
        for eid in exported_ids:
            db.add(LeadLedger(
                entity_id=db.query(Engagement.entity_id).filter(Engagement.id == eid).scalar(),
                action_type="EMAIL_EXPORTED",
                detail=f"Engagement #{eid} exported as .eml for Outlook",
            ))
        try:
            db.commit()
        except Exception:
            db.rollback()

    buf.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    emit(EventType.SYSTEM, "email_export", EventStatus.SUCCESS,
         detail=f"Exported {len(exported_ids)} emails, skipped {skipped} (no contact email)")

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="insure_emails_{timestamp}.zip"'},
    )


@router.get("/api/email/export/preview")
def preview_export(
    status: str = Query("QUEUED"),
    stage: Optional[str] = Query(None),
    county: Optional[str] = Query(None),
    cream_tier: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Preview what would be exported — shows entity, contact, subject without generating files."""
    query = (
        db.query(Engagement, Entity)
        .join(Entity, Engagement.entity_id == Entity.id)
        .filter(Engagement.status == status)
        .filter(Engagement.channel == "EMAIL")
    )
    if stage:
        query = query.filter(Entity.pipeline_stage == stage)
    if county:
        query = query.filter(Entity.county == county)
    if cream_tier:
        chars_filter = Entity.characteristics["cream_tier"].astext == cream_tier
        query = query.filter(chars_filter)

    rows = query.limit(limit).all()
    items = []
    for engagement, entity in rows:
        contacts = db.query(Contact).filter(Contact.entity_id == entity.id).all()
        to_email = None
        contact_name = None
        for c in sorted(contacts, key=lambda c: (-c.is_primary, c.id)):
            if c.email:
                to_email = c.email
                contact_name = c.name
                break

        items.append({
            "engagement_id": engagement.id,
            "entity_id": entity.id,
            "entity_name": entity.name,
            "county": entity.county,
            "pipeline_stage": entity.pipeline_stage,
            "subject": engagement.subject,
            "style": engagement.style,
            "to_email": to_email,
            "contact_name": contact_name,
            "has_email": to_email is not None,
        })

    ready = sum(1 for i in items if i["has_email"])
    return {
        "total": len(items),
        "ready_to_send": ready,
        "missing_email": len(items) - ready,
        "items": items,
    }


# ---------------------------------------------------------------------------
#  Bulk generate — create engagements for filtered entities that don't have one
# ---------------------------------------------------------------------------

class BulkGenerateRequest(BaseModel):
    stage: str = "LEAD"
    county: Optional[str] = None
    cream_tier: Optional[str] = None
    style: str = "formal"
    limit: int = 200


@router.post("/api/email/generate-bulk")
def generate_bulk_engagements(req: BulkGenerateRequest, db: Session = Depends(get_db)):
    """Create QUEUED engagements from AI-generated email templates for entities that have
    emails in characteristics but no existing QUEUED/SENT engagement.

    Uses the pre-generated email templates from the AI analyzer (characteristics.emails).
    """
    # Find entities with email templates but no active engagement
    subq = (
        db.query(Engagement.entity_id)
        .filter(Engagement.status.in_(["QUEUED", "SENT", "DRAFT"]))
        .subquery()
    )

    query = (
        db.query(Entity)
        .filter(Entity.pipeline_stage == req.stage)
        .filter(Entity.characteristics["emails"].isnot(None))
        .filter(~Entity.id.in_(db.query(subq.c.entity_id)))
    )
    if req.county:
        query = query.filter(Entity.county == req.county)
    if req.cream_tier:
        query = query.filter(Entity.characteristics["cream_tier"].astext == req.cream_tier)

    entities = query.limit(req.limit).all()

    created = 0
    skipped = 0
    for entity in entities:
        chars = entity.characteristics or {}
        emails = chars.get("emails")
        if not emails or not isinstance(emails, dict):
            skipped += 1
            continue

        # Pick the requested style, fall back to first available
        template = emails.get(req.style)
        if not template:
            template = next(iter(emails.values()), None)
        if not template or not isinstance(template, dict):
            skipped += 1
            continue

        subject = template.get("subject", f"Insurance inquiry — {entity.name}")
        body = template.get("body", "")

        engagement = Engagement(
            entity_id=entity.id,
            engagement_type="OUTREACH",
            channel="EMAIL",
            status="QUEUED",
            subject=subject,
            body=body,
            style=req.style,
        )
        db.add(engagement)
        created += 1

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to generate engagements")

    emit(EventType.SYSTEM, "email_bulk_generate", EventStatus.SUCCESS,
         detail=f"Generated {created} engagements, skipped {skipped}")

    return {"created": created, "skipped": skipped, "style": req.style}


# ---------------------------------------------------------------------------
#  Inbound — ingest Outlook email dump (.eml / .msg / .zip of either)
# ---------------------------------------------------------------------------

def _parse_eml(raw: bytes) -> dict:
    """Parse an .eml file into a dict of fields."""
    parser = BytesParser(policy=email_policy.default)
    msg = parser.parsebytes(raw)

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                body = part.get_content()
                break
            elif ct == "text/html" and not body:
                body = part.get_content()
    else:
        body = msg.get_content()

    return {
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
        "message_id": msg.get("Message-ID", ""),
        "in_reply_to": msg.get("In-Reply-To", ""),
        "references": msg.get("References", ""),
        "x_entity_id": msg.get("X-Insure-Entity-Id", ""),
        "x_engagement_id": msg.get("X-Insure-Engagement-Id", ""),
        "body": body if isinstance(body, str) else str(body),
    }


def _extract_emails_from_addr(addr: str) -> list[str]:
    """Pull email addresses from a header value like 'Name <user@example.com>'."""
    return re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', addr or "")


def _match_entity(parsed: dict, db: Session) -> Optional[int]:
    """Try to match a parsed email to an entity.

    Priority:
    1. X-Insure-Entity-Id header (from our own exports)
    2. Email address match against contacts table
    3. Subject line entity name match
    """
    # 1. Direct header match
    if parsed["x_entity_id"]:
        try:
            eid = int(parsed["x_entity_id"])
            if db.query(Entity).filter(Entity.id == eid).first():
                return eid
        except (ValueError, TypeError):
            pass

    # 2. Email address match
    all_addrs = _extract_emails_from_addr(parsed["from"]) + _extract_emails_from_addr(parsed["to"])
    if all_addrs:
        contact = (
            db.query(Contact)
            .filter(Contact.email.in_(all_addrs))
            .first()
        )
        if contact:
            return contact.entity_id

    # 3. Subject line fuzzy match — look for entity names in subject
    subject = parsed["subject"] or ""
    if len(subject) > 5:
        # Try matching against entity names (simple ILIKE search)
        entities = (
            db.query(Entity)
            .filter(Entity.pipeline_stage.in_(["LEAD", "OPPORTUNITY", "CUSTOMER"]))
            .filter(Entity.name.ilike(f"%{subject[:80]}%"))
            .limit(1)
            .all()
        )
        if entities:
            return entities[0].id

    return None


@router.post("/api/email/ingest")
async def ingest_emails(
    file: UploadFile = File(..., description="Upload .eml, .msg, or .zip of email files"),
    db: Session = Depends(get_db),
):
    """Ingest exported Outlook emails. Parses, matches to entities, creates RESPONSE engagements.

    Accepts:
    - Single .eml file
    - .zip containing multiple .eml files

    Each matched email creates an engagement record linked to the entity.
    Unmatched emails are returned for manual review.
    """
    filename = os.path.basename(file.filename or "upload")
    raw = await file.read()

    if len(raw) > 100 * 1024 * 1024:  # 100MB limit
        raise HTTPException(status_code=413, detail="File too large (max 100MB)")

    eml_files: list[tuple[str, bytes]] = []

    if filename.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".eml"):
                        eml_files.append((name, zf.read(name)))
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file")
    elif filename.lower().endswith(".eml"):
        eml_files.append((filename, raw))
    else:
        raise HTTPException(status_code=400, detail="Unsupported format. Upload .eml or .zip of .eml files.")

    matched = []
    unmatched = []
    duplicates = 0

    for fname, eml_bytes in eml_files:
        try:
            parsed = _parse_eml(eml_bytes)
        except Exception as e:
            unmatched.append({"filename": fname, "error": str(e)})
            continue

        entity_id = _match_entity(parsed, db)

        # Check for duplicate by message_id
        if parsed["message_id"] and entity_id:
            existing = (
                db.query(Engagement)
                .filter(Engagement.entity_id == entity_id)
                .filter(Engagement.subject == parsed["subject"])
                .filter(Engagement.body == parsed["body"][:500])
                .first()
            )
            if existing:
                duplicates += 1
                continue

        if entity_id:
            # Update original engagement if this is a reply to our outreach
            if parsed["x_engagement_id"]:
                try:
                    orig_id = int(parsed["x_engagement_id"])
                    orig = db.query(Engagement).filter(Engagement.id == orig_id).first()
                    if orig and orig.status == "SENT":
                        orig.status = "RESPONDED"
                        orig.responded_at = datetime.now(timezone.utc)
                except (ValueError, TypeError):
                    pass

            # Create inbound engagement record
            engagement = Engagement(
                entity_id=entity_id,
                engagement_type="RESPONSE",
                channel="EMAIL",
                status="RESPONDED",
                subject=parsed["subject"],
                body=parsed["body"][:5000],  # Cap body length
                responded_at=datetime.now(timezone.utc),
            )
            db.add(engagement)
            db.add(LeadLedger(
                entity_id=entity_id,
                action_type="EMAIL_INGESTED",
                detail=f"Inbound email: {parsed['subject'][:100]}",
            ))
            matched.append({
                "filename": fname,
                "entity_id": entity_id,
                "from": parsed["from"],
                "subject": parsed["subject"],
            })
        else:
            unmatched.append({
                "filename": fname,
                "from": parsed["from"],
                "to": parsed["to"],
                "subject": parsed["subject"],
                "error": "No matching entity found",
            })

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save ingested emails")

    emit(EventType.SYSTEM, "email_ingest", EventStatus.SUCCESS,
         detail=f"Ingested {len(matched)} emails, {len(unmatched)} unmatched, {duplicates} duplicates")

    return {
        "matched": len(matched),
        "unmatched": len(unmatched),
        "duplicates": duplicates,
        "matched_details": matched,
        "unmatched_details": unmatched[:50],  # Cap for response size
    }


# ---------------------------------------------------------------------------
#  Manual link — associate an unmatched email with an entity
# ---------------------------------------------------------------------------

class ManualLinkRequest(BaseModel):
    entity_id: int
    subject: str
    body: str
    from_addr: str = ""


@router.post("/api/email/link")
def manual_link_email(req: ManualLinkRequest, db: Session = Depends(get_db)):
    """Manually link an unmatched email to an entity."""
    entity = db.query(Entity).filter(Entity.id == req.entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    engagement = Engagement(
        entity_id=req.entity_id,
        engagement_type="RESPONSE",
        channel="EMAIL",
        status="RESPONDED",
        subject=req.subject,
        body=req.body[:5000],
        responded_at=datetime.now(timezone.utc),
    )
    db.add(engagement)
    db.add(LeadLedger(
        entity_id=req.entity_id,
        action_type="EMAIL_LINKED",
        detail=f"Manually linked email from {req.from_addr}: {req.subject[:80]}",
    ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to link email")

    return {"success": True, "engagement_id": engagement.id}
