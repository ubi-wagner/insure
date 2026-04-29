"""
Enrichment Pipeline — pluggable data sources for lead intelligence.

Each enricher:
1. Has a SOURCE_ID (e.g., "property_appraiser", "sunbiz", "fema_flood")
2. Implements enrich(entity, db) → dict of updated fields
3. Tracks provenance in entity.enrichment_sources
4. Logs to LeadLedger with source attribution

Enrichers run at different pipeline stages:
- TARGET → auto: Census batch geocoding → LEAD promotion
- LEAD → auto: FEMA flood zone (coordinate-based, instant)
- LEAD → auto: Property appraiser (address-based lookup)
- LEAD → auto: Sunbiz HOA/condo association search
- LEAD → auto: AI Kill & Cook (existing analyzer)
- Any stage → manual: User uploads (brochures, dec pages, loss runs)
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from database.models import Entity, LeadLedger
from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)


def record_enrichment(
    entity: Entity,
    db: Session,
    source_id: str,
    fields_updated: list[str],
    source_url: str | None = None,
    detail: str = "",
):
    """Record an enrichment event with full provenance tracking.

    Uses flush (not commit) so the caller controls the transaction boundary.
    """
    now = datetime.now(timezone.utc).isoformat()

    # MUST shallow-copy — SQLAlchemy won't detect in-place JSONB mutations
    sources = dict(entity.enrichment_sources or {})
    sources[source_id] = {
        "source": source_id,
        "timestamp": now,
        "fields_updated": fields_updated,
        "url": source_url,
    }
    entity.enrichment_sources = sources

    # Log to ledger
    ledger = LeadLedger(
        entity_id=entity.id,
        action_type=f"ENRICHMENT_{source_id.upper()}",
        detail=detail or f"Enriched via {source_id}: {', '.join(fields_updated)}",
        source=source_id,
        source_url=source_url,
    )
    db.add(ledger)

    try:
        db.flush()
    except Exception as e:
        logger.error(f"Failed to record enrichment {source_id} for entity {entity.id}: {e}")
        db.rollback()
        raise  # Let caller know it failed

    emit(EventType.HUNTER, f"enrich_{source_id}", EventStatus.SUCCESS,
         detail=f"{source_id}: {len(fields_updated)} fields for '{entity.name}'",
         entity_id=entity.id)


def update_characteristics(
    entity: Entity,
    updates: dict,
    source_id: str,
    overwrite: set[str] | None = None,
):
    """Merge new data into entity characteristics, tagging each field with its source.

    By default a non-null value already on the entity is NOT overwritten — the
    first source to write a field wins. This protects authoritative DOR/DBPR
    data from being clobbered by lower-confidence fallbacks.

    Pass ``overwrite={"stories", ...}`` to force specific keys to be replaced
    when the new source has stronger data than what's already there. Use
    sparingly — only when this enricher is genuinely authoritative for that
    key (e.g. DBPR Building Report is the truth on stories, even if
    name_parse already wrote a guess).
    """
    overwrite = overwrite or set()

    # MUST shallow-copy — SQLAlchemy won't detect in-place JSONB mutations
    chars = dict(entity.characteristics or {})

    # Store source attribution per field
    field_sources = dict(chars.get("_field_sources") or {})
    for key in updates:
        if updates[key] is not None:
            field_sources[key] = source_id
    chars["_field_sources"] = field_sources

    for key, value in updates.items():
        if value is None:
            continue
        is_empty = key not in chars or chars[key] is None
        if is_empty or key in overwrite:
            chars[key] = value

    entity.characteristics = chars
