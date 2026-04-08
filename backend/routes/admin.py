import logging
import os
import threading

import sqlalchemy as sa
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from database.models import Entity
from services.event_bus import EventStatus, EventType, emit

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/admin/seed")
def run_seed(db: Session = Depends(get_db)):
    """Trigger the seed script to populate mock data."""
    from scripts.seed import seed
    seed()
    return {"success": True, "message": "Seed complete"}


@router.post("/api/admin/reset")
def reset_database(db: Session = Depends(get_db)):
    """DESTRUCTIVE: Wipe all entity data and start fresh.

    Clears: entities, contacts, policies, engagements, entity_assets,
    lead_ledger, regions.
    Keeps: service_registry, broker_profiles.
    """
    try:
        # Order matters — children before parents, disable FK checks
        db.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
        db.execute(sa.text("TRUNCATE job_queue, engagements, policies, entity_assets, contacts, lead_ledger, regions_of_interest, entities CASCADE"))
        db.commit()
        logger.info("Database reset complete")
        emit(EventType.SYSTEM, "reset", EventStatus.SUCCESS, detail="All entity data cleared")
        return {"success": True, "message": "Database wiped. Ready for NAL seeding."}
    except Exception as e:
        db.rollback()
        logger.error(f"Reset failed: {e}")
        raise HTTPException(status_code=500, detail="Database reset failed. Check server logs.")


@router.get("/api/admin/counties")
def list_counties():
    """List available counties and their NAL/SDF file status."""
    from agents.seeder import get_available_counties
    counties = get_available_counties()

    # Also count existing leads per county
    from database.models import Entity
    db = SessionLocal()
    try:
        for c in counties:
            c["lead_count"] = db.query(Entity).filter(
                Entity.county == c["county_name"]
            ).count()
    finally:
        db.close()

    return {
        "counties": counties,
        "nal_download_url": "https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx",
        "instructions": "Download NAL and SDF files, upload to System Data/DOR/ via File Manager",
    }


@router.post("/api/admin/seed-county/{county_no}")
def seed_county_endpoint(county_no: str, min_value: int = Query(None, description="Min market value threshold (0 to disable)"), db: Session = Depends(get_db)):
    """Seed leads from NAL file for a specific county."""
    from agents.seeder import DOR_COUNTIES, _find_nal_file, seed_county

    if county_no not in DOR_COUNTIES:
        raise HTTPException(status_code=400, detail=f"Unknown county number: {county_no}")

    nal_file = _find_nal_file(county_no)
    if not nal_file:
        raise HTTPException(status_code=404, detail=f"NAL file not found for {DOR_COUNTIES[county_no]}. Searched filestore/System Data/DOR/ and data/. Upload via File Manager.")

    # Run synchronously so errors are visible
    result = seed_county(county_no, db, min_value=min_value)
    return result


@router.post("/api/admin/seed-all")
def seed_all_counties(min_value: int = Query(None, description="Min market value threshold (0 to disable)"), db: Session = Depends(get_db)):
    """Seed all counties that have NAL files."""
    from agents.seeder import get_available_counties, seed_county, DOR_COUNTIES

    available = [c for c in get_available_counties() if c["ready"]]
    if not available:
        # Debug: show what directories we searched
        import os
        base = os.path.dirname(os.path.dirname(__file__))
        dor_path = os.path.join(base, "filestore", "System Data", "DOR")
        data_path = os.path.join(base, "data")
        dor_exists = os.path.exists(dor_path)
        dor_files = os.listdir(dor_path) if dor_exists else []
        data_files = os.listdir(data_path) if os.path.exists(data_path) else []
        raise HTTPException(status_code=404, detail={
            "error": "No NAL files found",
            "dor_path": dor_path,
            "dor_exists": dor_exists,
            "dor_files": dor_files[:20],
            "data_path": data_path,
            "data_files": [f for f in data_files if "NAL" in f.upper()][:20],
        })

    results = []
    for c in available:
        try:
            emit(EventType.HUNTER, "seed_all", EventStatus.PENDING,
                 detail=f"Seeding {c['county_name']}...")
            result = seed_county(c["county_no"], db, min_value=min_value)
            results.append(result)
        except Exception as e:
            logger.error(f"Seed failed for {c['county_name']}: {e}")
            results.append({"county": c["county_name"], "error": str(e)})

    emit(EventType.HUNTER, "seed_all", EventStatus.SUCCESS,
         detail=f"Seeded {len(available)} counties")

    return {
        "success": True,
        "counties_seeded": len(results),
        "results": results,
    }


@router.post("/api/admin/download-cadastral")
def download_cadastral():
    """Download commercial parcels from FL ArcGIS Cadastral FeatureServer.

    Filters: DOR_UC 004/005/006/008/039, JV >= $10M, 11 coastal counties.
    Runs in background thread. Result saved to data/ and filestore/.
    """
    def _run():
        try:
            from scripts.download_cadastral import download_all_counties
            path = download_all_counties()
            emit(EventType.SYSTEM, "download_cadastral", EventStatus.SUCCESS,
                 detail=f"Downloaded to {os.path.basename(path)}" if path else "No parcels found")
        except Exception as e:
            logger.error(f"Cadastral download failed: {e}")
            emit(EventType.SYSTEM, "download_cadastral", EventStatus.ERROR,
                 detail=str(e)[:200])

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    emit(EventType.SYSTEM, "download_cadastral", EventStatus.PENDING,
         detail="Downloading from FL ArcGIS Cadastral FeatureServer...")
    return {
        "success": True,
        "message": "Cadastral download started. Check Events tab for progress.",
    }


@router.post("/api/admin/download-sunbiz")
def download_sunbiz_bulk():
    """Download Sunbiz quarterly corporate bulk data extract.

    Filters for condo/HOA associations, parses officers and registered agents.
    Runs in background thread. Result saved to data/ and filestore/.
    """
    def _run():
        try:
            from scripts.download_sunbiz import download_and_process
            result = download_and_process()
            if result.get("success"):
                detail = f"{result.get('total_matches', 0):,} associations"
                if result.get("csv_path"):
                    detail += f" -> {os.path.basename(result['csv_path'])}"
                emit(EventType.SYSTEM, "download_sunbiz", EventStatus.SUCCESS, detail=detail)
            else:
                emit(EventType.SYSTEM, "download_sunbiz", EventStatus.ERROR,
                     detail=result.get("error", "Unknown error")[:200])
        except Exception as e:
            logger.error(f"Sunbiz bulk download failed: {e}")
            emit(EventType.SYSTEM, "download_sunbiz", EventStatus.ERROR,
                 detail=str(e)[:200])

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    emit(EventType.SYSTEM, "download_sunbiz", EventStatus.PENDING,
         detail="Downloading Sunbiz quarterly corporate extract...")
    return {
        "success": True,
        "message": "Sunbiz bulk download started. Check Events tab for progress.",
    }


@router.post("/api/admin/refresh-data")
def refresh_all_data():
    """Download fresh data from all FL state sources.

    Refreshes: DBPR CSVs, Sunbiz corporate extract, ArcGIS cadastral parcels.
    Runs in background. Files saved to data/, filestore/, and S3.
    """
    def _run():
        try:
            from scripts.data_refresh import refresh_all
            results = refresh_all()
            total = results["total_files"]
            failed = results["total_failed"]
            emit(EventType.SYSTEM, "refresh_data", EventStatus.SUCCESS,
                 detail=f"{total} files downloaded, {failed} failed")
        except Exception as e:
            logger.error(f"Data refresh failed: {e}")
            emit(EventType.SYSTEM, "refresh_data", EventStatus.ERROR,
                 detail=str(e)[:200])

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    emit(EventType.SYSTEM, "refresh_data", EventStatus.PENDING,
         detail="Refreshing all data sources (DBPR, Sunbiz, ArcGIS)...")
    return {
        "success": True,
        "message": "Full data refresh started. DBPR CSVs + Sunbiz + ArcGIS Cadastral. Check Events tab.",
    }


@router.post("/api/admin/refresh-dor")
def refresh_dor_data():
    """Download fresh DOR NAL + SDF tax roll files for all target counties."""
    def _run():
        try:
            from scripts.data_refresh import refresh_dor_nal
            result = refresh_dor_nal()
            files = len(result.get("files", []))
            emit(EventType.SYSTEM, "refresh_dor", EventStatus.SUCCESS,
                 detail=f"{files} DOR files refreshed")
        except Exception as e:
            logger.error(f"DOR refresh failed: {e}")
            emit(EventType.SYSTEM, "refresh_dor", EventStatus.ERROR,
                 detail=str(e)[:200])

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"success": True, "message": "DOR NAL/SDF refresh started."}


@router.get("/api/admin/timebombs")
def list_timebombs():
    """List all scheduled timebomb events."""
    from services.timebomb import list_pending
    return {"timebombs": list_pending()}


@router.post("/api/admin/timebombs/{name}/cancel")
def cancel_timebomb(name: str):
    """Cancel a scheduled timebomb."""
    from services.timebomb import cancel
    removed = cancel(name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Timebomb '{name}' not found")
    return {"success": True, "message": f"Timebomb '{name}' cancelled"}


@router.post("/api/admin/refresh-dbpr")
def refresh_dbpr_data():
    """Download fresh DBPR condo registry + payment history CSVs."""
    def _run():
        try:
            from scripts.data_refresh import refresh_dbpr
            result = refresh_dbpr()
            files = len(result.get("files", []))
            emit(EventType.SYSTEM, "refresh_dbpr", EventStatus.SUCCESS,
                 detail=f"{files} DBPR files refreshed")
        except Exception as e:
            logger.error(f"DBPR refresh failed: {e}")
            emit(EventType.SYSTEM, "refresh_dbpr", EventStatus.ERROR,
                 detail=str(e)[:200])

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"success": True, "message": "DBPR refresh started."}


def _run_bulk_enrich():
    """Background job: enrich all leads that are missing enrichment data."""
    import time as _time

    _logger = logging.getLogger(__name__)
    db = SessionLocal()
    enriched = 0
    skipped = 0
    failed = 0
    try:
        # Get all LEAD-stage entities for enrichment
        entities = db.query(Entity).filter(
            Entity.pipeline_stage == "LEAD",
        ).order_by(Entity.id).all()

        total = len(entities)
        emit(EventType.HUNTER, "bulk_enrich", EventStatus.PENDING,
             detail=f"Starting bulk enrichment for {total} leads")
        _logger.info(f"Bulk enrichment: {total} leads to process")

        for i, entity in enumerate(entities):
            try:
                from agents.enrichers.pipeline import run_lead_enrichment
                run_lead_enrichment(entity, db)
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
    total_leads = db.query(Entity).filter(
        Entity.pipeline_stage.in_(["TARGET", "LEAD", "OPPORTUNITY", "CUSTOMER"])
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
    has_dbpr = db.execute(sa.text(
        "SELECT COUNT(*) FROM entities WHERE enrichment_sources ? 'dbpr_bulk'"
    )).scalar() or 0
    has_citizens = db.execute(sa.text(
        "SELECT COUNT(*) FROM entities WHERE enrichment_sources ? 'citizens_insurance'"
    )).scalar() or 0
    has_dor_nal = db.execute(sa.text(
        "SELECT COUNT(*) FROM entities WHERE enrichment_sources ? 'dor_nal'"
    )).scalar() or 0

    # Count leads with no enrichment at all
    no_enrichment = db.execute(sa.text(
        "SELECT COUNT(*) FROM entities WHERE enrichment_sources IS NULL OR enrichment_sources = '{}'"
    )).scalar() or 0

    # Pipeline stage counts
    stage_counts = {}
    for stage in ["TARGET", "LEAD", "OPPORTUNITY", "CUSTOMER", "ARCHIVED"]:
        stage_counts[stage] = db.query(Entity).filter(Entity.pipeline_stage == stage).count()

    return {
        "total_leads": total_leads,
        "no_enrichment": no_enrichment,
        "stage_counts": stage_counts,
        "coverage": {
            "dor_nal": has_dor_nal,
            "fema_flood": has_fema,
            "fdot_parcels": has_fdot,
            "property_appraiser": has_pa,
            "sunbiz": has_sunbiz,
            "dbpr_bulk": has_dbpr,
            "citizens_insurance": has_citizens,
        },
    }


@router.get("/api/admin/ops-dashboard")
def ops_dashboard(db: Session = Depends(get_db)):
    """Single endpoint for the unified Ops page — county funnel, services, enrichment coverage."""
    from agents.seeder import get_seed_stats, get_available_counties, DOR_COUNTIES
    from services.registry import get_all_statuses

    # -- Seed stats from last run --
    seed_stats = get_seed_stats()
    available_counties = get_available_counties()

    # -- Per-county entity counts by stage --
    county_stage_rows = db.execute(sa.text(
        "SELECT county, pipeline_stage, COUNT(*) as cnt FROM entities "
        "WHERE county IS NOT NULL GROUP BY county, pipeline_stage"
    )).fetchall()
    county_stages: dict[str, dict[str, int]] = {}
    for row in county_stage_rows:
        county_stages.setdefault(row[0], {})[row[1]] = row[2]

    # -- Per-county enrichment_status counts --
    county_enrich_rows = db.execute(sa.text(
        "SELECT county, enrichment_status, COUNT(*) as cnt FROM entities "
        "WHERE county IS NOT NULL AND pipeline_stage != 'ARCHIVED' "
        "GROUP BY county, enrichment_status"
    )).fetchall()
    county_enrich: dict[str, dict[str, int]] = {}
    for row in county_enrich_rows:
        county_enrich.setdefault(row[0], {})[row[1]] = row[2]

    # -- Build county rows --
    counties = []
    for c in available_counties:
        cno = c["county_no"]
        cname = c["county_name"]
        ss = seed_stats.get(cno, {})
        stages = county_stages.get(cname, {})
        enrich = county_enrich.get(cname, {})
        total_entities = sum(stages.values())
        enriched = enrich.get("complete", 0)

        counties.append({
            "county_no": cno,
            "county": cname,
            "nal_ready": c["ready"],
            "nal_file": c.get("nal_file"),
            # Seed stats from last run
            "nal_total": ss.get("total_parcels"),
            "type_passed": ss.get("type_passed"),
            "value_filtered": ss.get("filtered"),
            "min_value_used": ss.get("min_value_used"),
            "last_seeded": ss.get("seeded_at"),
            # Live DB counts
            "total_entities": total_entities,
            "stages": {
                "TARGET": stages.get("TARGET", 0),
                "LEAD": stages.get("LEAD", 0),
                "OPPORTUNITY": stages.get("OPPORTUNITY", 0),
                "CUSTOMER": stages.get("CUSTOMER", 0),
                "ARCHIVED": stages.get("ARCHIVED", 0),
            },
            "enriched": enriched,
            "enriched_pct": round(enriched / total_entities * 100) if total_entities > 0 else 0,
        })

    # -- Global stage counts --
    stage_counts = {}
    for stage in ["TARGET", "LEAD", "OPPORTUNITY", "CUSTOMER", "ARCHIVED"]:
        stage_counts[stage] = db.query(Entity).filter(Entity.pipeline_stage == stage).count()

    # -- Enrichment coverage (global) --
    enricher_names = [
        "dor_nal", "fema_flood", "property_appraiser", "dbpr_bulk", "dbpr_payments",
        "cam_license", "sunbiz", "citizens_insurance", "fdot_parcels", "oir_market", "cream_score",
    ]
    total_active = sum(v for k, v in stage_counts.items() if k != "ARCHIVED")
    coverage = {}
    for name in enricher_names:
        count = db.execute(sa.text(
            f"SELECT COUNT(*) FROM entities WHERE enrichment_sources ? :name "
            f"AND pipeline_stage != 'ARCHIVED'"
        ), {"name": name}).scalar() or 0
        coverage[name] = {
            "count": count,
            "pct": round(count / total_active * 100) if total_active > 0 else 0,
        }

    # -- Services --
    services = get_all_statuses()

    # -- Job Queue Stats --
    queue_stats = {}
    try:
        from services.job_queue import get_queue_stats
        queue_stats = get_queue_stats(db)
    except Exception as e:
        logger.warning(f"Failed to get queue stats: {e}")

    return {
        "counties": counties,
        "stage_counts": stage_counts,
        "total_active": total_active,
        "coverage": coverage,
        "services": services,
        "queue": queue_stats,
    }


@router.get("/api/admin/queue")
def get_queue_status(db: Session = Depends(get_db)):
    """Get job queue statistics for the Ops dashboard."""
    from services.job_queue import get_queue_stats
    return get_queue_stats(db)


@router.post("/api/admin/queue/retry-all")
def retry_all_failed(db: Session = Depends(get_db)):
    """Reset all FAILED jobs back to PENDING for retry."""
    from services.job_queue import retry_failed_jobs
    count = retry_failed_jobs(db)
    return {"success": True, "retried": count}


@router.post("/api/admin/queue/backfill")
def backfill_queue(db: Session = Depends(get_db)):
    """Create missing jobs for all LEADs that need enrichment."""
    from services.job_queue import produce_jobs_for_all_leads
    count = produce_jobs_for_all_leads(db)
    return {"success": True, "jobs_created": count}


@router.post("/api/admin/queue/purge-rejected")
def purge_rejected(db: Session = Depends(get_db)):
    """Delete all REJECTED jobs (permanent failures) from the queue."""
    from database.models import JobQueue
    count = db.query(JobQueue).filter(JobQueue.status == "REJECTED").delete()
    db.commit()
    return {"success": True, "purged": count}


@router.post("/api/admin/queue/force-rerun/{enricher}")
def force_rerun_enricher(enricher: str, db: Session = Depends(get_db)):
    """Force re-run a specific enricher on all entities.

    Removes the enricher's record from enrichment_sources and resets/creates
    queue jobs as PENDING. Useful after fixing an enricher's logic.

    Also clears any characteristics fields the enricher writes (best-effort by prefix).
    """
    from database.models import Entity, JobQueue

    # Find all entities that have this enricher recorded
    entities = db.query(Entity).filter(
        Entity.enrichment_sources.op("?")(enricher)
    ).all()

    cleared_entities = 0
    for entity in entities:
        # Shallow-copy to trigger SQLAlchemy mutation detection
        sources = dict(entity.enrichment_sources or {})
        if enricher in sources:
            del sources[enricher]
            entity.enrichment_sources = sources

            # For citizens_insurance, clear the heuristic-derived fields so the
            # new math can repopulate them. Other enrichers can be added here
            # as needed.
            if enricher == "citizens_insurance":
                chars = dict(entity.characteristics or {})
                for key in [
                    "citizens_likelihood",
                    "citizens_likelihood_tier",
                    "citizens_county_penetration",
                    "citizens_estimated_premium",
                    "citizens_premium_display",
                    "citizens_risk_factors",
                    "citizens_candidate",
                    "citizens_swap_opportunity",
                ]:
                    chars.pop(key, None)
                entity.characteristics = chars

            cleared_entities += 1

    db.commit()

    # Reset/create queue jobs for these entities
    requeued = 0
    for entity in entities:
        existing_job = db.query(JobQueue).filter(
            JobQueue.entity_id == entity.id,
            JobQueue.enricher == enricher,
        ).first()
        if existing_job:
            existing_job.status = "PENDING"
            existing_job.attempts = 0
            existing_job.last_error = None
            existing_job.locked_by = None
            existing_job.locked_at = None
            existing_job.completed_at = None
        else:
            new_job = JobQueue(
                entity_id=entity.id,
                enricher=enricher,
                status="PENDING",
                priority=5,
            )
            db.add(new_job)
        requeued += 1

    db.commit()

    return {
        "success": True,
        "enricher": enricher,
        "entities_cleared": cleared_entities,
        "jobs_requeued": requeued,
    }


@router.get("/api/admin/query")
def query_data(
    q: str = Query(""),
    table: str = Query("entities"),
    county: str = Query(""),
    stage: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Guided data query — search entities or contacts.

    Supports simple NLP-style queries like:
    - "condos in Pinellas with 7+ stories"
    - "fire resistive buildings in Miami-Dade"
    - "all contacts for Clearwater"
    """
    from database.models import Contact, Entity

    results = []

    if table == "contacts":
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
            "created_at": e.created_at.isoformat() if e.created_at else None,
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
    filename = os.path.basename(file.filename or "unknown.csv")

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
except Exception as e:
    logger.debug(f"S3 sync skipped: {e}")  # Non-critical — S3 may not be configured


@router.get("/api/files")
def list_files(path: str = Query("")):
    """List files and folders at a given path."""
    safe_path = os.path.abspath(os.path.join(FILE_STORE_ROOT, path))
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
    safe_path = os.path.abspath(os.path.join(FILE_STORE_ROOT, path, name))
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

    filename = os.path.basename(file.filename or "unnamed")
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
    safe_path = os.path.abspath(os.path.join(FILE_STORE_ROOT, path))
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
    safe_path = os.path.abspath(os.path.join(FILE_STORE_ROOT, path))
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
    safe_path = os.path.abspath(os.path.join(FILE_STORE_ROOT, path))
    if not safe_path.startswith(os.path.abspath(FILE_STORE_ROOT)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not os.path.exists(safe_path):
        raise HTTPException(status_code=404, detail="Not found")

    parent = os.path.dirname(safe_path)
    new_path = os.path.join(parent, new_name)
    os.rename(safe_path, new_path)
    return {"success": True, "path": os.path.relpath(new_path, FILE_STORE_ROOT)}
