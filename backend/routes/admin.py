import logging
import os
import threading

import sqlalchemy as sa
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from database.models import Entity

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/admin/seed")
def run_seed(db: Session = Depends(get_db)):
    """Trigger the seed script to populate mock data."""
    from scripts.seed import seed
    seed()
    return {"success": True, "message": "Seed complete"}


# Full county harvest areas — covers entire county footprints
# Split into grid tiles (~0.15° ≈ 10 miles) to keep Overpass queries manageable
# Counties ordered south → north along both coasts

FL_HARVEST_AREAS = [
    # ─── Miami-Dade County ───
    {"name": "Miami-Dade South (Homestead)", "south": 25.40, "north": 25.55, "west": -80.50, "east": -80.30, "county": "Miami-Dade"},
    {"name": "Miami-Dade Central (Kendall/Coral Gables)", "south": 25.55, "north": 25.72, "west": -80.40, "east": -80.20, "county": "Miami-Dade"},
    {"name": "Miami-Dade Downtown/Brickell", "south": 25.72, "north": 25.82, "west": -80.25, "east": -80.15, "county": "Miami-Dade"},
    {"name": "Miami Beach / Key Biscayne", "south": 25.72, "north": 25.88, "west": -80.17, "east": -80.08, "county": "Miami-Dade"},
    {"name": "Miami-Dade North (Aventura/Sunny Isles)", "south": 25.88, "north": 26.00, "west": -80.20, "east": -80.08, "county": "Miami-Dade"},

    # ─── Broward County ───
    {"name": "Broward South (Hollywood/Hallandale)", "south": 25.97, "north": 26.08, "west": -80.20, "east": -80.08, "county": "Broward"},
    {"name": "Broward Central (Fort Lauderdale)", "south": 26.08, "north": 26.20, "west": -80.20, "east": -80.08, "county": "Broward"},
    {"name": "Broward North (Pompano/Deerfield)", "south": 26.20, "north": 26.35, "west": -80.15, "east": -80.05, "county": "Broward"},

    # ─── Palm Beach County ───
    {"name": "Palm Beach South (Boca Raton/Delray)", "south": 26.30, "north": 26.48, "west": -80.12, "east": -80.02, "county": "Palm Beach"},
    {"name": "Palm Beach Central (Boynton/Lake Worth)", "south": 26.48, "north": 26.63, "west": -80.10, "east": -80.00, "county": "Palm Beach"},
    {"name": "Palm Beach North (Palm Beach/Jupiter)", "south": 26.63, "north": 26.80, "west": -80.08, "east": -80.00, "county": "Palm Beach"},

    # ─── Collier County ───
    {"name": "Collier South (Marco Island)", "south": 25.88, "north": 26.02, "west": -81.80, "east": -81.68, "county": "Collier"},
    {"name": "Collier Central (Naples)", "south": 26.10, "north": 26.25, "west": -81.85, "east": -81.72, "county": "Collier"},
    {"name": "Collier North (Bonita area)", "south": 26.25, "north": 26.40, "west": -81.85, "east": -81.75, "county": "Collier"},

    # ─── Lee County ───
    {"name": "Lee South (Fort Myers Beach/Estero)", "south": 26.35, "north": 26.50, "west": -82.00, "east": -81.85, "county": "Lee"},
    {"name": "Lee Central (Fort Myers/Cape Coral)", "south": 26.50, "north": 26.70, "west": -82.05, "east": -81.85, "county": "Lee"},
    {"name": "Lee North (Sanibel/Pine Island)", "south": 26.42, "north": 26.55, "west": -82.15, "east": -82.00, "county": "Lee"},

    # ─── Charlotte County ───
    {"name": "Charlotte (Punta Gorda/Port Charlotte)", "south": 26.82, "north": 27.00, "west": -82.12, "east": -81.95, "county": "Charlotte"},
    {"name": "Charlotte Coast (Englewood)", "south": 26.92, "north": 27.05, "west": -82.40, "east": -82.25, "county": "Charlotte"},

    # ─── Sarasota County ───
    {"name": "Sarasota South (Venice/Nokomis)", "south": 27.05, "north": 27.18, "west": -82.50, "east": -82.38, "county": "Sarasota"},
    {"name": "Sarasota Central (Siesta/Lido)", "south": 27.18, "north": 27.35, "west": -82.60, "east": -82.48, "county": "Sarasota"},
    {"name": "Sarasota North (Longboat Key)", "south": 27.35, "north": 27.48, "west": -82.68, "east": -82.55, "county": "Sarasota"},
    {"name": "Sarasota Mainland", "south": 27.25, "north": 27.42, "west": -82.55, "east": -82.42, "county": "Sarasota"},

    # ─── Manatee County ───
    {"name": "Manatee Coast (Anna Maria/Holmes Beach)", "south": 27.47, "north": 27.55, "west": -82.75, "east": -82.65, "county": "Manatee"},
    {"name": "Manatee Central (Bradenton)", "south": 27.45, "north": 27.55, "west": -82.62, "east": -82.48, "county": "Manatee"},
    {"name": "Manatee East (Lakewood Ranch)", "south": 27.35, "north": 27.50, "west": -82.48, "east": -82.35, "county": "Manatee"},

    # ─── Hillsborough County ───
    {"name": "Hillsborough South (Sun City/Apollo Beach)", "south": 27.70, "north": 27.82, "west": -82.45, "east": -82.30, "county": "Hillsborough"},
    {"name": "Hillsborough Central (Tampa Downtown)", "south": 27.90, "north": 28.00, "west": -82.50, "east": -82.40, "county": "Hillsborough"},
    {"name": "Hillsborough West (Westchase/Town'n'Country)", "south": 28.00, "north": 28.10, "west": -82.62, "east": -82.48, "county": "Hillsborough"},
    {"name": "Hillsborough East (Brandon/Riverview)", "south": 27.85, "north": 28.00, "west": -82.35, "east": -82.20, "county": "Hillsborough"},

    # ─── Pinellas County ───
    {"name": "Pinellas South (St Pete/Gulfport)", "south": 27.68, "north": 27.80, "west": -82.78, "east": -82.62, "county": "Pinellas"},
    {"name": "Pinellas Beaches (Treasure Is → Indian Rocks)", "south": 27.75, "north": 27.92, "west": -82.86, "east": -82.78, "county": "Pinellas"},
    {"name": "Pinellas Central (Largo/Seminole)", "south": 27.80, "north": 27.92, "west": -82.78, "east": -82.68, "county": "Pinellas"},
    {"name": "Pinellas North (Clearwater/Dunedin)", "south": 27.92, "north": 28.05, "west": -82.82, "east": -82.68, "county": "Pinellas"},
    {"name": "Clearwater Beach / Sand Key", "south": 27.90, "north": 28.02, "west": -82.85, "east": -82.80, "county": "Pinellas"},

    # ─── Pasco County ───
    {"name": "Pasco South (New Port Richey/Hudson)", "south": 28.15, "north": 28.30, "west": -82.75, "east": -82.55, "county": "Pasco"},
    {"name": "Pasco Central (Wesley Chapel/Zephyrhills)", "south": 28.20, "north": 28.35, "west": -82.50, "east": -82.30, "county": "Pasco"},
    {"name": "Pasco Coast (Holiday/Tarpon Springs border)", "south": 28.05, "north": 28.20, "west": -82.80, "east": -82.65, "county": "Pasco"},
]


def _run_bulk_harvest():
    """Background job: harvest all FL coastal strips."""
    import logging
    import time
    from agents.hunter import _harvest_to_cache, _is_area_harvested
    from services.event_bus import EventStatus, EventType, emit

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    total = 0
    skipped = 0
    failed = 0
    try:
        for i, strip in enumerate(FL_HARVEST_AREAS):
            bbox = {
                "south": strip["south"], "north": strip["north"],
                "west": strip["west"], "east": strip["east"],
            }
            if _is_area_harvested(bbox, db):
                skipped += 1
                continue

            logger.info(f"Harvesting {strip['name']} ({i+1}/{len(FL_HARVEST_AREAS)})...")
            emit(EventType.HUNTER, "bulk_harvest", EventStatus.PENDING,
                 detail=f"({i+1}/{len(FL_HARVEST_AREAS)}) {strip['name']}...")
            try:
                cached = _harvest_to_cache(bbox, db, region_name=strip["name"])
                total += cached
            except Exception as e:
                failed += 1
                logger.warning(f"Harvest failed for {strip['name']}: {e}")
                emit(EventType.HUNTER, "bulk_harvest_area_failed", EventStatus.ERROR,
                     detail=f"{strip['name']}: {str(e)[:100]}")

            # 15s between areas — Overpass rate limits aggressively
            time.sleep(15)

        detail = f"Bulk harvest done: {total} buildings cached, {skipped} skipped, {failed} failed"
        emit(EventType.HUNTER, "bulk_harvest", EventStatus.SUCCESS, detail=detail)
        logger.info(detail)
    except Exception as e:
        logger.error(f"Bulk harvest failed: {e}")
        emit(EventType.HUNTER, "bulk_harvest", EventStatus.ERROR,
             detail=str(e)[:200])
    finally:
        db.close()


@router.post("/api/admin/harvest")
def trigger_bulk_harvest():
    """Trigger bulk harvest of all FL coastal areas. Runs in background."""
    thread = threading.Thread(target=_run_bulk_harvest, daemon=True)
    thread.start()
    return {
        "success": True,
        "message": f"Bulk harvest started for {len(FL_HARVEST_AREAS)} areas across 11 counties",
        "areas": [s["name"] for s in FL_HARVEST_AREAS],
    }


def _run_bulk_enrich():
    """Background job: enrich all leads that are missing enrichment data."""
    import time as _time
    from agents.enrichers.pipeline import run_enrichment_for_stage
    from services.event_bus import EventStatus, EventType, emit

    _logger = logging.getLogger(__name__)
    db = SessionLocal()
    enriched = 0
    skipped = 0
    failed = 0
    try:
        # Get all leads missing enrichment sources
        entities = db.query(Entity).filter(
            Entity.pipeline_stage.in_(["NEW", "ENRICHED", "INVESTIGATING", "RESEARCHED", "TARGETED", "OPPORTUNITY"]),
        ).order_by(Entity.id).all()

        total = len(entities)
        emit(EventType.HUNTER, "bulk_enrich", EventStatus.PENDING,
             detail=f"Starting bulk enrichment for {total} leads")
        _logger.info(f"Bulk enrichment: {total} leads to process")

        for i, entity in enumerate(entities):
            sources = entity.enrichment_sources or {}

            # Skip if already fully enriched for current stage
            stage = entity.pipeline_stage or "NEW"
            if stage in ("ENRICHED", "RESEARCHED") and all(s in sources for s in ["fema_flood", "fdot_parcels"]):
                skipped += 1
                continue

            try:
                # Run enrichments for the entity's current stage
                run_enrichment_for_stage(entity, stage, db)

                # Also backfill NEW enrichments if they haven't run yet
                if stage not in ("NEW",) and not any(s in sources for s in ["fema_flood", "fdot_parcels"]):
                    run_enrichment_for_stage(entity, "NEW", db)

                enriched += 1

                if enriched % 25 == 0:
                    emit(EventType.HUNTER, "bulk_enrich", EventStatus.PENDING,
                         detail=f"Progress: {enriched}/{total} enriched, {skipped} skipped, {failed} failed")
                    _logger.info(f"Bulk enrich progress: {enriched}/{total}")

            except Exception as e:
                failed += 1
                db.rollback()
                _logger.warning(f"Enrich failed for entity {entity.id}: {e}")

            # Brief pause to not hammer external APIs
            _time.sleep(0.5)

        detail = f"Bulk enrichment done: {enriched} enriched, {skipped} skipped, {failed} failed (of {total})"
        emit(EventType.HUNTER, "bulk_enrich", EventStatus.SUCCESS, detail=detail)
        _logger.info(detail)
    except Exception as e:
        _logger.error(f"Bulk enrichment failed: {e}")
        emit(EventType.HUNTER, "bulk_enrich", EventStatus.ERROR, detail=str(e)[:200])
    finally:
        db.close()


@router.post("/api/admin/enrich")
def trigger_bulk_enrich():
    """Trigger bulk enrichment for all leads missing data. Runs in background."""
    thread = threading.Thread(target=_run_bulk_enrich, daemon=True)
    thread.start()
    return {
        "success": True,
        "message": "Bulk enrichment started for all unenriched leads",
    }


@router.get("/api/admin/enrich/status")
def get_enrich_status(db: Session = Depends(get_db)):
    """Get enrichment coverage stats."""
    from database.models import OsmBuilding

    total_leads = db.query(Entity).filter(
        Entity.pipeline_stage.in_(["NEW", "ENRICHED", "INVESTIGATING", "RESEARCHED", "TARGETED", "OPPORTUNITY", "CUSTOMER"])
    ).count()

    # Count leads with each enrichment source
    has_fema = db.execute(sa.text(
        "SELECT COUNT(*) FROM entities WHERE enrichment_sources ? 'fema_flood'"
    )).scalar() or 0
    has_fdot = db.execute(sa.text(
        "SELECT COUNT(*) FROM entities WHERE enrichment_sources ? 'fdot_parcels'"
    )).scalar() or 0
    has_pa = db.execute(sa.text(
        "SELECT COUNT(*) FROM entities WHERE enrichment_sources ? 'property_appraiser'"
    )).scalar() or 0
    has_sunbiz = db.execute(sa.text(
        "SELECT COUNT(*) FROM entities WHERE enrichment_sources ? 'sunbiz'"
    )).scalar() or 0
    has_overpass = db.execute(sa.text(
        "SELECT COUNT(*) FROM entities WHERE enrichment_sources ? 'overpass'"
    )).scalar() or 0

    # Count leads with no enrichment at all
    no_enrichment = db.execute(sa.text(
        "SELECT COUNT(*) FROM entities WHERE enrichment_sources IS NULL OR enrichment_sources = '{}'"
    )).scalar() or 0

    return {
        "total_leads": total_leads,
        "no_enrichment": no_enrichment,
        "coverage": {
            "overpass": has_overpass,
            "fema_flood": has_fema,
            "fdot_parcels": has_fdot,
            "property_appraiser": has_pa,
            "sunbiz": has_sunbiz,
        },
    }


@router.get("/api/admin/harvest/status")
def get_harvest_status(db: Session = Depends(get_db)):
    """Get harvest cache statistics."""
    from database.models import OsmBuilding, OsmHarvestArea
    total_buildings = db.query(OsmBuilding).count()
    total_areas = db.query(OsmHarvestArea).count()
    promoted = db.query(OsmBuilding).filter(OsmBuilding.promoted_entity_id.isnot(None)).count()
    by_county = db.execute(
        sa.text("SELECT county, COUNT(*) as cnt FROM osm_buildings WHERE county IS NOT NULL GROUP BY county ORDER BY cnt DESC")
    ).fetchall() if total_buildings > 0 else []
    areas = db.query(OsmHarvestArea).order_by(OsmHarvestArea.harvested_at.desc()).all()
    return {
        "total_buildings_cached": total_buildings,
        "total_areas_harvested": total_areas,
        "buildings_promoted_to_leads": promoted,
        "by_county": [{"county": r[0], "count": r[1]} for r in by_county],
        "areas": [
            {"name": a.name, "count": a.building_count, "harvested_at": a.harvested_at.isoformat()}
            for a in areas
        ],
    }


@router.get("/api/admin/query")
def query_data(
    q: str = Query(""),
    table: str = Query("entities"),
    county: str = Query(""),
    stage: str = Query(""),
    limit: int = Query(50),
    db: Session = Depends(get_db),
):
    """Guided data query — search entities, osm_buildings, or contacts.

    Supports simple NLP-style queries like:
    - "condos in Pinellas with 7+ stories"
    - "fire resistive buildings in Miami-Dade"
    - "all contacts for Clearwater"
    """
    from database.models import Contact, Entity, OsmBuilding

    results = []

    if table == "osm_cache":
        query = db.query(OsmBuilding)
        if county:
            query = query.filter(OsmBuilding.county.ilike(f"%{county}%"))
        if q:
            # Parse simple NLP patterns
            q_lower = q.lower()
            # Stories filter
            import re
            stories_match = re.search(r'(\d+)\+?\s*(?:stories|floors|levels)', q_lower)
            if stories_match:
                min_stories = int(stories_match.group(1))
                query = query.filter(OsmBuilding.stories >= min_stories)
            # Construction filter
            if "fire resistive" in q_lower:
                query = query.filter(OsmBuilding.construction_class.ilike("%fire resistive%"))
            elif "non-combustible" in q_lower or "non combustible" in q_lower:
                query = query.filter(
                    OsmBuilding.construction_class.ilike("%fire resistive%") |
                    OsmBuilding.construction_class.ilike("%non-combustible%")
                )
            # Name/address search
            name_search = re.sub(r'\d+\+?\s*(?:stories|floors|levels|fire resistive|non.combustible|masonry|frame)', '', q_lower).strip()
            if name_search and len(name_search) > 2:
                query = query.filter(
                    OsmBuilding.name.ilike(f"%{name_search}%") |
                    OsmBuilding.address.ilike(f"%{name_search}%")
                )
        total = query.count()
        rows = query.order_by(OsmBuilding.stories.desc().nullslast()).limit(limit).all()
        results = [{
            "osm_id": r.osm_id, "name": r.name, "address": r.address,
            "county": r.county, "building_type": r.building_type,
            "stories": r.stories, "construction_class": r.construction_class,
            "tiv_estimate": r.tiv_estimate, "units_estimate": r.units_estimate,
            "promoted": r.promoted_entity_id is not None,
        } for r in rows]
        return {"table": "osm_cache", "total": total, "showing": len(results), "results": results}

    elif table == "contacts":
        query = db.query(Contact).join(Entity, Contact.entity_id == Entity.id)
        if county:
            query = query.filter(Entity.county.ilike(f"%{county}%"))
        if q:
            query = query.filter(
                Contact.name.ilike(f"%{q}%") |
                Contact.title.ilike(f"%{q}%") |
                Contact.email.ilike(f"%{q}%")
            )
        total = query.count()
        rows = query.limit(limit).all()
        results = [{
            "id": c.id, "entity_id": c.entity_id, "name": c.name,
            "title": c.title, "email": c.email, "phone": c.phone,
            "source": c.source, "is_primary": c.is_primary,
        } for c in rows]
        return {"table": "contacts", "total": total, "showing": len(results), "results": results}

    else:  # entities (default)
        query = db.query(Entity)
        if county:
            query = query.filter(Entity.county.ilike(f"%{county}%"))
        if stage:
            query = query.filter(Entity.pipeline_stage == stage)
        if q:
            query = query.filter(
                Entity.name.ilike(f"%{q}%") |
                Entity.address.ilike(f"%{q}%")
            )
        total = query.count()
        rows = query.order_by(Entity.created_at.desc()).limit(limit).all()
        results = [{
            "id": e.id, "name": e.name, "address": e.address,
            "county": e.county, "pipeline_stage": e.pipeline_stage,
            "characteristics_keys": list((e.characteristics or {}).keys()),
            "sources": list((e.enrichment_sources or {}).keys()),
            "created_at": e.created_at.isoformat(),
        } for e in rows]
        return {"table": "entities", "total": total, "showing": len(results), "results": results}


# ─── S3 Bucket Storage ───

def _get_s3_client():
    """Get S3 client for Railway bucket."""
    import boto3
    # Railway injects bucket creds as AWS_* env vars
    endpoint = os.getenv("AWS_ENDPOINT_URL_S3") or os.getenv("AWS_ENDPOINT_URL") or os.getenv("BUCKET_ENDPOINT")
    access_key = os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("BUCKET_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("BUCKET_SECRET_ACCESS_KEY")

    if not all([endpoint, access_key, secret_key]):
        return None, None

    bucket_name = os.getenv("AWS_S3_BUCKET_NAME") or os.getenv("AWS_BUCKET_NAME") or os.getenv("BUCKET_NAME") or "default"

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    return client, bucket_name


@router.post("/api/admin/upload-data")
async def upload_data_file(file: UploadFile = File(...)):
    """Upload a large data file (CSV, etc.) to the S3 bucket.

    Streams to disk in chunks — handles files of any size.
    Also saves a local copy to backend/data/ for enricher access.
    """
    filename = file.filename or "unknown.csv"

    # Stream to disk in chunks
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    local_path = os.path.join(data_dir, filename)
    total_size = 0
    with open(local_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            total_size += len(chunk)
    logger.info(f"Saved {filename} locally ({total_size:,} bytes)")

    # Upload to S3 bucket if configured
    s3_url = None
    s3_client, bucket_name = _get_s3_client()
    if s3_client:
        try:
            s3_key = f"data/{filename}"
            s3_client.upload_file(local_path, bucket_name, s3_key)
            s3_url = f"s3://{bucket_name}/{s3_key}"
            logger.info(f"Uploaded {filename} to bucket ({total_size:,} bytes)")
        except Exception as e:
            logger.warning(f"S3 upload failed for {filename}: {e}")

    return {
        "success": True,
        "filename": filename,
        "size_bytes": total_size,
        "local_path": local_path,
        "s3_url": s3_url,
    }


@router.get("/api/admin/bucket/files")
def list_bucket_files():
    """List files in the S3 bucket."""
    s3_client, bucket_name = _get_s3_client()
    if not s3_client:
        # Fall back to listing local data dir
        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        if os.path.exists(data_dir):
            files = []
            for f in sorted(os.listdir(data_dir)):
                path = os.path.join(data_dir, f)
                if os.path.isfile(path):
                    files.append({
                        "name": f,
                        "size_bytes": os.path.getsize(path),
                        "source": "local",
                    })
            return {"bucket": "local", "files": files}
        return {"bucket": "none", "files": []}

    try:
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix="data/")
        files = []
        for obj in response.get("Contents", []):
            files.append({
                "name": obj["Key"].replace("data/", ""),
                "size_bytes": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
                "source": "s3",
            })
        return {"bucket": bucket_name, "files": files}
    except Exception as e:
        logger.warning(f"Failed to list bucket files: {e}")
        return {"bucket": bucket_name, "files": [], "error": str(e)}


# ─── File Manager (folder structure) ───

FILE_STORE_ROOT = os.path.join(os.path.dirname(__file__), "..", "filestore")


def _ensure_filestore():
    """Create default folder structure and sync CSV data files."""
    import shutil

    defaults = [
        "System Data",
        "System Data/DBPR",
        "System Data/Overpass Cache",
        "Associations",
        "Associations/_templates",
        "Proposals",
        "Reports",
        "Uploads",
    ]
    for folder in defaults:
        path = os.path.join(FILE_STORE_ROOT, folder)
        os.makedirs(path, exist_ok=True)

    # Copy CSV data files to filestore so they're visible in the file manager
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    dbpr_dir = os.path.join(FILE_STORE_ROOT, "System Data", "DBPR")
    if os.path.exists(data_dir):
        for filename in os.listdir(data_dir):
            if filename.endswith(".csv"):
                src = os.path.join(data_dir, filename)
                dst = os.path.join(dbpr_dir, filename)
                if not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        pass  # Non-critical — file manager convenience only


_ensure_filestore()


def _sync_from_s3():
    """On startup, download files from S3 bucket to local filestore.
    This restores uploaded files that were lost on redeploy."""
    s3_client, bucket_name = _get_s3_client()
    if not s3_client:
        return

    try:
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix="files/")
        for obj in response.get("Contents", []):
            s3_key = obj["Key"]
            # Strip "files/" prefix to get the local path
            local_rel = s3_key.replace("files/", "", 1)
            if not local_rel:
                continue
            local_path = os.path.join(FILE_STORE_ROOT, local_rel)
            if os.path.exists(local_path):
                continue  # Already have it locally
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            try:
                s3_client.download_file(bucket_name, s3_key, local_path)
                logger.info(f"S3 sync: restored {local_rel}")
            except Exception as e:
                logger.warning(f"S3 sync failed for {s3_key}: {e}")
    except Exception as e:
        logger.warning(f"S3 sync listing failed: {e}")


# Sync from S3 on startup (restores files lost on redeploy)
try:
    _sync_from_s3()
except Exception:
    pass  # Non-critical — S3 may not be configured


@router.get("/api/files")
def list_files(path: str = Query("")):
    """List files and folders at a given path."""
    safe_path = os.path.normpath(os.path.join(FILE_STORE_ROOT, path))
    if not safe_path.startswith(os.path.abspath(FILE_STORE_ROOT)):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not os.path.exists(safe_path):
        return {"path": path, "items": []}

    items = []
    try:
        for entry in sorted(os.listdir(safe_path)):
            full = os.path.join(safe_path, entry)
            rel = os.path.relpath(full, FILE_STORE_ROOT)
            if os.path.isdir(full):
                # Count children
                child_count = len(os.listdir(full)) if os.path.isdir(full) else 0
                items.append({
                    "name": entry,
                    "path": rel,
                    "type": "folder",
                    "children": child_count,
                })
            else:
                stat = os.stat(full)
                items.append({
                    "name": entry,
                    "path": rel,
                    "type": "file",
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
    except Exception as e:
        logger.warning(f"Failed to list files at {safe_path}: {e}")

    return {"path": path, "items": items}


@router.post("/api/files/folder")
def create_folder(name: str = Query(...), path: str = Query("")):
    """Create a new folder."""
    safe_path = os.path.normpath(os.path.join(FILE_STORE_ROOT, path, name))
    if not safe_path.startswith(os.path.abspath(FILE_STORE_ROOT)):
        raise HTTPException(status_code=400, detail="Invalid path")
    os.makedirs(safe_path, exist_ok=True)
    return {"success": True, "path": os.path.relpath(safe_path, FILE_STORE_ROOT)}


@router.post("/api/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    path: str = Query(""),
    chunk_index: int = Query(0),
    total_chunks: int = Query(1),
    original_size: int = Query(0),
):
    """Upload a file to a specific folder. Supports chunked uploads for large files."""
    safe_dir = os.path.normpath(os.path.join(FILE_STORE_ROOT, path))
    if not safe_dir.startswith(os.path.abspath(FILE_STORE_ROOT)):
        raise HTTPException(status_code=400, detail="Invalid path")
    os.makedirs(safe_dir, exist_ok=True)

    filename = file.filename or "unnamed"
    filepath = os.path.join(safe_dir, filename)

    if total_chunks > 1:
        # Chunked upload: append to temp file, finalize on last chunk
        tmp_path = filepath + ".uploading"
        mode = "ab" if chunk_index > 0 else "wb"
        chunk_data = await file.read()
        with open(tmp_path, mode) as f:
            f.write(chunk_data)

        if chunk_index < total_chunks - 1:
            # More chunks coming
            return {"success": True, "chunk": chunk_index, "of": total_chunks, "status": "partial"}

        # Last chunk — rename to final path
        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(tmp_path, filepath)
        total_size = os.path.getsize(filepath)
        logger.info(f"Chunked upload complete: {filename} ({total_size:,} bytes, {total_chunks} chunks)")
    else:
        # Single-chunk upload
        total_size = 0
        with open(filepath, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                total_size += len(chunk)
        logger.info(f"Uploaded {filename} ({total_size:,} bytes)")

    # S3 upload for persistence
    s3_client, bucket_name = _get_s3_client()
    if s3_client:
        try:
            s3_key = f"files/{path}/{filename}" if path else f"files/{filename}"
            s3_client.upload_file(filepath, bucket_name, s3_key)
        except Exception as e:
            logger.warning(f"S3 upload failed: {e}")

    rel = os.path.relpath(filepath, FILE_STORE_ROOT)
    return {
        "success": True,
        "name": filename,
        "path": rel,
        "size": total_size,
    }


@router.get("/api/files/download")
def download_file(path: str = Query(...)):
    """Download a file."""
    from fastapi.responses import FileResponse
    safe_path = os.path.normpath(os.path.join(FILE_STORE_ROOT, path))
    if not safe_path.startswith(os.path.abspath(FILE_STORE_ROOT)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not os.path.isfile(safe_path):
        raise HTTPException(status_code=404, detail="File not found")

    filename = os.path.basename(safe_path)
    # Determine content type
    import mimetypes
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    return FileResponse(
        safe_path,
        filename=filename,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.delete("/api/files")
def delete_file(path: str = Query(...)):
    """Delete a file or empty folder."""
    import shutil
    safe_path = os.path.normpath(os.path.join(FILE_STORE_ROOT, path))
    if not safe_path.startswith(os.path.abspath(FILE_STORE_ROOT)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not os.path.exists(safe_path):
        raise HTTPException(status_code=404, detail="Not found")

    if os.path.isdir(safe_path):
        shutil.rmtree(safe_path)
    else:
        os.remove(safe_path)

    # Also delete from S3
    s3_client, bucket_name = _get_s3_client()
    if s3_client:
        try:
            s3_key = f"files/{path}"
            s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
        except Exception:
            pass

    return {"success": True}


@router.post("/api/files/rename")
def rename_file(path: str = Query(...), new_name: str = Query(...)):
    """Rename a file or folder."""
    safe_path = os.path.normpath(os.path.join(FILE_STORE_ROOT, path))
    if not safe_path.startswith(os.path.abspath(FILE_STORE_ROOT)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not os.path.exists(safe_path):
        raise HTTPException(status_code=404, detail="Not found")

    parent = os.path.dirname(safe_path)
    new_path = os.path.join(parent, new_name)
    os.rename(safe_path, new_path)
    return {"success": True, "path": os.path.relpath(new_path, FILE_STORE_ROOT)}
