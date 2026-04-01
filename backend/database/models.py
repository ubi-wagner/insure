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


class RegionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class ActionType(str, enum.Enum):
    HUNT_FOUND = "HUNT_FOUND"
    USER_THUMB_UP = "USER_THUMB_UP"
    USER_THUMB_DOWN = "USER_THUMB_DOWN"


class DocType(str, enum.Enum):
    AUDIT = "AUDIT"
    IE_REPORT = "IE_REPORT"
    SUNBIZ = "SUNBIZ"


class RegionOfInterest(Base):
    __tablename__ = "regions_of_interest"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    bounding_box = Column(JSONB, nullable=False)  # {north, south, east, west}
    target_county = Column(String, nullable=True)
    parameters = Column(JSONB, nullable=True)  # {stories, coast_distance}
    status = Column(Enum(RegionStatus), default=RegionStatus.PENDING, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=True)
    county = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    characteristics = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    ledger_events = relationship("LeadLedger", back_populates="entity")
    assets = relationship("EntityAsset", back_populates="entity")
    contacts = relationship("Contact", back_populates="entity")


class LeadLedger(Base):
    __tablename__ = "lead_ledger"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    action_type = Column(Enum(ActionType), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    entity = relationship("Entity", back_populates="ledger_events")


class EntityAsset(Base):
    __tablename__ = "entity_assets"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    doc_type = Column(Enum(DocType), nullable=False)
    s3_url = Column(String, nullable=True)
    extracted_text = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    entity = relationship("Entity", back_populates="assets")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    name = Column(String, nullable=False)
    title = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    entity = relationship("Entity", back_populates="contacts")


class ServiceRegistry(Base):
    __tablename__ = "service_registry"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, default="starting")  # starting, healthy, degraded, down
    last_heartbeat = Column(DateTime, server_default=func.now(), nullable=False)
    capabilities = Column(JSONB, nullable=True)  # {"crawl4ai": true, "anthropic_key": true, ...}
    version = Column(String, nullable=True)
    detail = Column(String, nullable=True)  # Human-readable status message
