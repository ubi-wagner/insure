"""
Hunter Agent - Polls for PENDING regions and scrapes for condo/HOA properties.

Uses Crawl4AI to crawl public property directories, filtering results
to fall within the bounding box of each region of interest.
"""

import os
import time
import json
import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import (
    ActionType,
    Entity,
    LeadLedger,
    RegionOfInterest,
    RegionStatus,
)
from agents.geo_helper import get_bounding_box_center, get_county_from_coords, is_within_bounds
from services.event_bus import EventStatus, EventType, emit


logger = logging.getLogger(__name__)

PROXY_URL = os.getenv("PROXY_URL")
POLL_INTERVAL = int(os.getenv("HUNTER_POLL_INTERVAL", "30"))


def process_region(region: RegionOfInterest, db: Session) -> int:
    """Process a single region: determine county and scrape for properties."""
    bbox = region.bounding_box
    center_lat, center_lng = get_bounding_box_center(bbox)

    # Determine the county via reverse geocoding
    county = get_county_from_coords(center_lat, center_lng)
    if county:
        region.target_county = county
        db.commit()

    logger.info(f"Processing region '{region.name}' - County: {county}")
    emit(EventType.HUNTER, "process_region", EventStatus.PENDING,
         detail=f"Region '{region.name}' county={county}", region_id=region.id)

    found_count = 0

    try:
        found_count = crawl_for_properties(region, county, db)
    except Exception as e:
        logger.error(f"Crawl error for region '{region.name}': {e}")
        emit(EventType.HUNTER, "crawl", EventStatus.ERROR,
             detail=f"Region '{region.name}': {str(e)[:200]}", region_id=region.id)
        return 0

    # Only mark region as completed on success
    region.status = RegionStatus.COMPLETED
    db.commit()

    emit(EventType.HUNTER, "process_region", EventStatus.SUCCESS,
         detail=f"Region '{region.name}' done, {found_count} properties found", region_id=region.id)
    return found_count


def crawl_for_properties(region: RegionOfInterest, county: str | None, db: Session) -> int:
    """
    Use Crawl4AI to scrape public property/condo directories.
    Filters results to fall within the region's bounding box.
    """
    try:
        from crawl4ai import WebCrawler

        crawler = WebCrawler()
        crawler.warmup()
    except ImportError:
        logger.warning("Crawl4AI not available, using fallback scraper")
        return crawl_fallback(region, county, db)
    except Exception as e:
        logger.warning(f"Crawl4AI init error: {e}, using fallback")
        return crawl_fallback(region, county, db)

    bbox = region.bounding_box
    params = region.parameters or {}
    min_stories = params.get("stories", 3)

    # Target Florida condo/HOA public registries
    search_county = county or "Florida"
    target_urls = [
        f"https://www.myfloridalicense.com/datamart/search-condos?county={search_county}",
    ]

    found = 0
    for url in target_urls:
        try:
            result = crawler.run(url=url, proxy=PROXY_URL if PROXY_URL else None)
            if result and result.success:
                properties = parse_property_results(result.extracted_content or result.html, bbox)
                for prop in properties:
                    found += save_property(prop, region, db)
        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")

    return found


def crawl_fallback(region: RegionOfInterest, county: str | None, db: Session) -> int:
    """Fallback when Crawl4AI is not available - does nothing in dev."""
    logger.info("Fallback mode - no properties scraped. Use seed script for testing.")
    return 0


def parse_property_results(content: str, bbox: dict) -> list[dict]:
    """Parse crawled content and extract properties within bounding box."""
    properties = []

    if not content:
        return properties

    # Try to parse as JSON first (structured extraction)
    try:
        data = json.loads(content) if isinstance(content, str) else content
        if isinstance(data, list):
            for item in data:
                lat = item.get("latitude") or item.get("lat")
                lng = item.get("longitude") or item.get("lng") or item.get("lon")
                if lat and lng and is_within_bounds(float(lat), float(lng), bbox):
                    properties.append({
                        "name": item.get("name", "Unknown Property"),
                        "address": item.get("address", ""),
                        "latitude": float(lat),
                        "longitude": float(lng),
                    })
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse property results: {e}, content preview: {str(content)[:200]}")

    return properties


def save_property(prop: dict, region: RegionOfInterest, db: Session) -> int:
    """Save a property to the database if not already exists."""
    existing = db.query(Entity).filter(
        Entity.name == prop["name"],
        Entity.address == prop.get("address", ""),
    ).first()

    if existing:
        return 0

    try:
        entity = Entity(
            name=prop["name"],
            address=prop.get("address", ""),
            county=region.target_county,
            latitude=prop.get("latitude"),
            longitude=prop.get("longitude"),
            characteristics={},
        )
        db.add(entity)
        db.commit()
        db.refresh(entity)

        # Write HUNT_FOUND ledger event
        ledger = LeadLedger(
            entity_id=entity.id,
            action_type=ActionType.HUNT_FOUND,
        )
        db.add(ledger)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Failed to save property '{prop.get('name')}': {e}")
        emit(EventType.DB_OPERATION, "save_property", EventStatus.ERROR,
             detail=f"'{prop.get('name')}': {str(e)[:200]}")
        return 0

    emit(EventType.DB_OPERATION, "save_property", EventStatus.SUCCESS,
         detail=f"Saved '{entity.name}' (id={entity.id})", entity_id=entity.id)
    return 1


def run_hunter_loop():
    """Main polling loop - runs as a background task."""
    from services.registry import register, heartbeat

    logger.info("Starting hunter agent loop...")

    # Check capabilities
    crawl4ai_ok = False
    try:
        from crawl4ai import WebCrawler
        crawl4ai_ok = True
    except ImportError:
        pass

    register("hunter", capabilities={
        "crawl4ai": crawl4ai_ok,
        "poll_interval": POLL_INTERVAL,
        "proxy": bool(PROXY_URL),
    }, detail=f"Polling every {POLL_INTERVAL}s" + (" (no Crawl4AI)" if not crawl4ai_ok else ""))

    while True:
        db = SessionLocal()
        try:
            pending_regions = (
                db.query(RegionOfInterest)
                .filter(RegionOfInterest.status == RegionStatus.PENDING)
                .all()
            )

            if pending_regions:
                heartbeat("hunter", detail=f"Processing {len(pending_regions)} region(s)")
            else:
                heartbeat("hunter", detail="Idle, no pending regions")

            for region in pending_regions:
                process_region(region, db)

        except Exception as e:
            logger.error(f"Hunter loop error: {e}")
            heartbeat("hunter", status="degraded", detail=f"Error: {str(e)[:100]}")
        finally:
            db.rollback()
            db.close()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_hunter_loop()
