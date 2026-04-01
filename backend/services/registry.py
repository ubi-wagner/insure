"""
Service Registry - Services register themselves, heartbeat, and report capabilities.

Each worker/component calls register() on startup and heartbeat() periodically.
The /api/status endpoint reads from the DB to show real system health.
"""

import logging
import os
from datetime import datetime

from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import ServiceRegistry

logger = logging.getLogger(__name__)


def register(name: str, capabilities: dict | None = None, detail: str = "Starting"):
    """Register or update a service in the registry."""
    db = SessionLocal()
    try:
        svc = db.query(ServiceRegistry).filter(ServiceRegistry.name == name).first()
        if svc:
            svc.status = "healthy"
            svc.last_heartbeat = datetime.utcnow()
            svc.capabilities = capabilities or svc.capabilities
            svc.detail = detail
        else:
            svc = ServiceRegistry(
                name=name,
                status="healthy",
                capabilities=capabilities or {},
                detail=detail,
            )
            db.add(svc)
        db.commit()
        logger.info(f"Service '{name}' registered: {detail}")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to register service '{name}': {e}")
    finally:
        db.close()


def heartbeat(name: str, status: str = "healthy", detail: str | None = None):
    """Update a service heartbeat."""
    db = SessionLocal()
    try:
        svc = db.query(ServiceRegistry).filter(ServiceRegistry.name == name).first()
        if svc:
            svc.status = status
            svc.last_heartbeat = datetime.utcnow()
            if detail is not None:
                svc.detail = detail
            db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Heartbeat failed for '{name}': {e}")
    finally:
        db.close()


def set_status(name: str, status: str, detail: str):
    """Set a service status explicitly (e.g., on error)."""
    db = SessionLocal()
    try:
        svc = db.query(ServiceRegistry).filter(ServiceRegistry.name == name).first()
        if svc:
            svc.status = status
            svc.detail = detail
            svc.last_heartbeat = datetime.utcnow()
            db.commit()
    except Exception as e:
        db.rollback()
    finally:
        db.close()


def get_all_statuses() -> list[dict]:
    """Get all registered services and their status."""
    db = SessionLocal()
    try:
        services = db.query(ServiceRegistry).all()
        now = datetime.utcnow()
        results = []
        for svc in services:
            age_seconds = (now - svc.last_heartbeat).total_seconds()
            # If no heartbeat in 90s, mark as stale
            effective_status = svc.status
            if age_seconds > 90 and svc.status == "healthy":
                effective_status = "stale"

            results.append({
                "name": svc.name,
                "status": effective_status,
                "last_heartbeat": svc.last_heartbeat.isoformat(),
                "age_seconds": round(age_seconds),
                "capabilities": svc.capabilities or {},
                "detail": svc.detail or "",
            })
        return results
    except Exception as e:
        logger.error(f"Failed to get service statuses: {e}")
        return []
    finally:
        db.close()
