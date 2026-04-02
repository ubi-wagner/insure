import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ─── Enums ───

class RegionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class PipelineStage(str, enum.Enum):
    TARGET = "TARGET"           # Raw NAL parcel, waiting for Overpass association
    LEAD = "LEAD"               # Associated, continuously enriching, scored cold/warm/hot
    OPPORTUNITY = "OPPORTUNITY"  # User-promoted for CRM engagement
    CUSTOMER = "CUSTOMER"        # Converted deal
    ARCHIVED = "ARCHIVED"        # Dismissed


class ActionType(str, enum.Enum):
    HUNT_FOUND = "HUNT_FOUND"
    USER_THUMB_UP = "USER_THUMB_UP"
    USER_THUMB_DOWN = "USER_THUMB_DOWN"
    STAGE_CHANGE = "STAGE_CHANGE"
    AI_KILL = "AI_KILL"
    AI_COOK = "AI_COOK"
    EMAIL_SENT = "EMAIL_SENT"
    EMAIL_RESPONDED = "EMAIL_RESPONDED"
    NOTE_ADDED = "NOTE_ADDED"
    ENGAGEMENT_CREATED = "ENGAGEMENT_CREATED"
    CONTACT_ADDED = "CONTACT_ADDED"
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"


class DocType(str, enum.Enum):
    AUDIT = "AUDIT"
    IE_REPORT = "IE_REPORT"
    SUNBIZ = "SUNBIZ"
    BROCHURE = "BROCHURE"
    DEC_PAGE = "DEC_PAGE"
    LOSS_RUN = "LOSS_RUN"
    PROPERTY_APPRAISER = "PROPERTY_APPRAISER"
    FEMA_FLOOD = "FEMA_FLOOD"
    OTHER = "OTHER"


class CoverageType(str, enum.Enum):
    WIND = "WIND"
    FLOOD = "FLOOD"
    GENERAL_LIABILITY = "GENERAL_LIABILITY"
    DIRECTORS_OFFICERS = "DIRECTORS_OFFICERS"
    UMBRELLA = "UMBRELLA"
    OTHER = "OTHER"


class EngagementType(str, enum.Enum):
    OUTREACH = "OUTREACH"
    FOLLOW_UP = "FOLLOW_UP"
    RESPONSE = "RESPONSE"
    NOTE = "NOTE"


class EngagementStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    SENT = "SENT"
    RESPONDED = "RESPONDED"
    ARCHIVED = "ARCHIVED"


class EngagementChannel(str, enum.Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    MEETING = "MEETING"
    OTHER = "OTHER"


# ─── Core Models ───

class RegionOfInterest(Base):
    __tablename__ = "regions_of_interest"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    bounding_box = Column(JSONB, nullable=False)
    target_county = Column(String, nullable=True)
    parameters = Column(JSONB, nullable=True)
    status = Column(Enum(RegionStatus), default=RegionStatus.PENDING, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Entity(Base):
    """Core CRM unit — represents a property, association, or customer.
    Self-referential: a customer entity can have child property entities."""
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("entities.id"), nullable=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=True)
    county = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    characteristics = Column(JSONB, nullable=True)
    enrichment_sources = Column(JSONB, nullable=True)  # {source_id: {source, timestamp, fields, url}}
    pipeline_stage = Column(String, default="TARGET", nullable=False)
    heat_score = Column(String, nullable=True)  # cold, warm, hot
    folder_path = Column(String, nullable=True)  # Per-lead document folder in bucket
    osm_building_id = Column(Integer, ForeignKey("osm_buildings.id"), nullable=True)
    enrichment_status = Column(String, default="idle", nullable=False)  # idle, running, complete, error
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    parent = relationship("Entity", remote_side="Entity.id", backref="children")
    osm_building = relationship("OsmBuilding", foreign_keys=[osm_building_id])
    ledger_events = relationship("LeadLedger", back_populates="entity")
    assets = relationship("EntityAsset", back_populates="entity")
    contacts = relationship("Contact", back_populates="entity")
    policies = relationship("Policy", back_populates="entity")
    engagements = relationship("Engagement", back_populates="entity")


class LeadLedger(Base):
    """Immutable event log — every action on an entity is recorded."""
    __tablename__ = "lead_ledger"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    action_type = Column(String, nullable=False)  # Using String for flexibility with new types
    detail = Column(String, nullable=True)  # Human-readable context
    source = Column(String, nullable=True)  # e.g., "overpass", "sunbiz", "property_appraiser"
    source_url = Column(String, nullable=True)  # Link to original source
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    entity = relationship("Entity", back_populates="ledger_events")


class EntityAsset(Base):
    __tablename__ = "entity_assets"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    doc_type = Column(Enum(DocType), nullable=False)
    s3_url = Column(String, nullable=True)
    extracted_text = Column(Text, nullable=True)
    source = Column(String, nullable=True)  # "user_upload", "web_scrape", "api"
    filename = Column(String, nullable=True)  # Original filename for uploads
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    entity = relationship("Entity", back_populates="assets")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    name = Column(String, nullable=False)
    title = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    is_primary = Column(Integer, default=0, nullable=False)
    source = Column(String, nullable=True)  # "sunbiz", "property_appraiser", "manual", "user_upload"
    source_url = Column(String, nullable=True)  # Link to source document
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    entity = relationship("Entity", back_populates="contacts")


class Policy(Base):
    """Structured insurance policy record."""
    __tablename__ = "policies"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    coverage_type = Column(String, nullable=False)  # WIND, FLOOD, GL, D&O, UMBRELLA, OTHER
    carrier = Column(String, nullable=True)
    policy_number = Column(String, nullable=True)
    premium = Column(Float, nullable=True)
    tiv = Column(Float, nullable=True)
    deductible = Column(String, nullable=True)
    expiration = Column(String, nullable=True)
    prior_premium = Column(Float, nullable=True)
    premium_increase_pct = Column(Float, nullable=True)
    is_active = Column(Integer, default=1, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    entity = relationship("Entity", back_populates="policies")


class Engagement(Base):
    """Outreach and communication tracking."""
    __tablename__ = "engagements"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    broker_id = Column(Integer, ForeignKey("broker_profiles.id"), nullable=True)
    engagement_type = Column(String, nullable=False)  # OUTREACH, FOLLOW_UP, RESPONSE, NOTE
    channel = Column(String, default="EMAIL", nullable=False)  # EMAIL, PHONE, MEETING
    status = Column(String, default="DRAFT", nullable=False)  # DRAFT, QUEUED, SENT, RESPONDED, ARCHIVED
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    style = Column(String, nullable=True)  # informal, formal, cost_effective, risk_averse
    sent_at = Column(DateTime, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    follow_up_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    entity = relationship("Entity", back_populates="engagements")
    broker = relationship("BrokerProfile")


class BrokerProfile(Base):
    __tablename__ = "broker_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    title = Column(String, nullable=True)
    company = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone_office = Column(String, nullable=True)
    phone_cell = Column(String, nullable=True)
    address = Column(String, nullable=True)
    signature_block = Column(Text, nullable=True)
    preferences = Column(JSONB, nullable=True)
    is_active = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class ServiceRegistry(Base):
    __tablename__ = "service_registry"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, default="starting")
    last_heartbeat = Column(DateTime, server_default=func.now(), nullable=False)
    capabilities = Column(JSONB, nullable=True)
    version = Column(String, nullable=True)
    detail = Column(String, nullable=True)


class OsmBuilding(Base):
    """Cache of every building Overpass has ever returned. Keyed by osm_id.
    Used to avoid re-querying the same buildings and enable instant local filtering."""
    __tablename__ = "osm_buildings"

    id = Column(Integer, primary_key=True, index=True)
    osm_id = Column(Integer, nullable=False, unique=True, index=True)
    osm_type = Column(String, nullable=False)  # way, relation
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    name = Column(String, nullable=True)
    address = Column(String, nullable=True)
    county = Column(String, nullable=True)
    building_type = Column(String, nullable=True)
    stories = Column(Integer, nullable=True)
    construction_class = Column(String, nullable=True)
    iso_class = Column(Integer, nullable=True)
    tiv_estimate = Column(Float, nullable=True)
    units_estimate = Column(Integer, nullable=True)
    footprint_sqft = Column(Float, nullable=True)
    tags = Column(JSONB, nullable=True)
    raw_element = Column(JSONB, nullable=True)
    geocoded = Column(Integer, default=0, nullable=False)
    promoted_entity_id = Column(Integer, ForeignKey("entities.id"), nullable=True)
    harvested_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)

    promoted_entity = relationship("Entity", foreign_keys=[promoted_entity_id])


class OsmHarvestArea(Base):
    """Tracks which geographic areas have been harvested from Overpass."""
    __tablename__ = "osm_harvest_areas"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    bbox_south = Column(Float, nullable=False)
    bbox_north = Column(Float, nullable=False)
    bbox_west = Column(Float, nullable=False)
    bbox_east = Column(Float, nullable=False)
    building_count = Column(Integer, default=0, nullable=False)
    query_params = Column(JSONB, nullable=True)
    harvested_at = Column(DateTime, server_default=func.now(), nullable=False)
