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
    """Compact Ops dashboard — global stage counts, services, available counties for seeding,
    and the job queue (which is the single source of truth for per-enricher pipeline state)."""
    from agents.seeder import get_available_counties, get_seed_stats
    from services.registry import get_all_statuses

    # Available counties — only for the seed dropdown / NAL readiness check
    available_counties = get_available_counties()
    seed_stats = get_seed_stats()
    counties = []
    for c in available_counties:
        cno = c["county_no"]
        ss = seed_stats.get(cno, {})
        counties.append({
            "county_no": cno,
            "county": c["county_name"],
            "nal_ready": c["ready"],
            "nal_total": ss.get("total_parcels"),
            "type_passed": ss.get("type_passed"),
            "value_filtered": ss.get("filtered"),
            "last_seeded": ss.get("seeded_at"),
        })

    # Global stage counts (for the headline number)
    stage_counts = {}
    for stage in ["TARGET", "LEAD", "OPPORTUNITY", "CUSTOMER", "ARCHIVED"]:
        stage_counts[stage] = db.query(Entity).filter(Entity.pipeline_stage == stage).count()
    total_active = sum(v for k, v in stage_counts.items() if k != "ARCHIVED")

    # Services
    services = get_all_statuses()

    # Job Queue — per-enricher and per-enricher-per-county breakdowns
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


@router.post("/api/admin/sql")
def run_sql_query(
    body: dict,
    db: Session = Depends(get_db),
):
    """Execute a read-only SQL query (admin only).

    Accepts: {"sql": "SELECT ...", "limit": 100}
    Only SELECT/WITH statements are allowed. Mutations are blocked.
    Results capped at 500 rows. Timeout 10 seconds.
    """
    sql = (body.get("sql") or "").strip()
    limit = min(int(body.get("limit", 100)), 500)

    if not sql:
        raise HTTPException(status_code=400, detail="sql field is required")

    # Security: only allow SELECT-like statements
    first_word = sql.split()[0].upper() if sql.split() else ""
    if first_word not in ("SELECT", "WITH", "EXPLAIN"):
        raise HTTPException(
            status_code=400,
            detail=f"Only SELECT/WITH/EXPLAIN queries are allowed. Got: {first_word}"
        )

    # Block common mutation keywords even inside subqueries
    upper = sql.upper()
    for banned in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE"):
        if banned in upper:
            raise HTTPException(status_code=400, detail=f"Mutation keyword '{banned}' is not allowed in read-only queries")

    try:
        # Wrap in a read-only transaction with a timeout
        db.execute(sa.text("SET LOCAL statement_timeout = '10s'"))
        result = db.execute(sa.text(sql))

        # Get column names
        columns = list(result.keys()) if result.returns_rows else []
        rows = []
        if result.returns_rows:
            for i, row in enumerate(result):
                if i >= limit:
                    break
                rows.append({col: (val.isoformat() if hasattr(val, 'isoformat') else val) for col, val in zip(columns, row)})

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": len(rows) >= limit,
        }
    except Exception as e:
        db.rollback()
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": str(e)[:500],
        }


# Canned query presets — shown in the SQL Query Tool UI
CANNED_QUERIES = [
    {
        "name": "Dataset Diagnostics",
        "description": "Use code distribution, value histogram, top entities",
        "sql": "SELECT characteristics->>'dor_use_code' AS use_code, characteristics->>'dor_use_description' AS label, COUNT(*) AS cnt FROM entities WHERE characteristics->>'dor_use_code' IS NOT NULL GROUP BY 1, 2 ORDER BY cnt DESC",
    },
    {
        "name": "Value Histogram",
        "description": "DOR market value distribution across all entities",
        "sql": """SELECT
  CASE
    WHEN (characteristics->>'dor_market_value')::bigint < 2000000 THEN '<$2M'
    WHEN (characteristics->>'dor_market_value')::bigint < 5000000 THEN '$2-5M'
    WHEN (characteristics->>'dor_market_value')::bigint < 10000000 THEN '$5-10M'
    WHEN (characteristics->>'dor_market_value')::bigint < 20000000 THEN '$10-20M'
    WHEN (characteristics->>'dor_market_value')::bigint < 50000000 THEN '$20-50M'
    ELSE '$50M+'
  END AS value_bucket,
  COUNT(*) AS cnt
FROM entities
WHERE characteristics->>'dor_market_value' IS NOT NULL
GROUP BY 1 ORDER BY MIN((characteristics->>'dor_market_value')::bigint)""",
    },
    {
        "name": "Top 20 by Value",
        "description": "Highest DOR market value entities",
        "sql": "SELECT id, name, county, (characteristics->>'dor_market_value')::bigint AS market_value, (characteristics->>'dor_num_units')::int AS units, characteristics->>'dor_use_description' AS use_type, characteristics->>'dbpr_condo_name' AS dbpr_name FROM entities WHERE characteristics->>'dor_market_value' IS NOT NULL ORDER BY (characteristics->>'dor_market_value')::bigint DESC LIMIT 20",
    },
    {
        "name": "Top 20 by Units",
        "description": "Largest entities by unit count",
        "sql": "SELECT id, name, county, (characteristics->>'dor_num_units')::int AS units, (characteristics->>'dor_market_value')::bigint AS market_value, characteristics->>'dor_use_description' AS use_type FROM entities WHERE (characteristics->>'dor_num_units')::int >= 10 ORDER BY (characteristics->>'dor_num_units')::int DESC LIMIT 20",
    },
    {
        "name": "Cream Score - Platinum",
        "description": "All platinum-tier leads (cream score 90+)",
        "sql": "SELECT id, name, county, (characteristics->>'cream_score')::int AS score, characteristics->>'cream_tier' AS tier, (characteristics->>'dor_market_value')::bigint AS market_value FROM entities WHERE (characteristics->>'cream_score')::int >= 90 ORDER BY (characteristics->>'cream_score')::int DESC",
    },
    {
        "name": "Cream Score - Gold",
        "description": "All gold-tier leads (cream score 70-89)",
        "sql": "SELECT id, name, county, (characteristics->>'cream_score')::int AS score, characteristics->>'cream_tier' AS tier, (characteristics->>'dor_market_value')::bigint AS market_value FROM entities WHERE (characteristics->>'cream_score')::int BETWEEN 70 AND 89 ORDER BY (characteristics->>'cream_score')::int DESC",
    },
    {
        "name": "Financial Distress",
        "description": "Entities flagged with financial distress from KFI",
        "sql": "SELECT id, name, county, characteristics->>'dbpr_financial_distress' AS distress, (characteristics->>'dbpr_operating_fund_balance')::numeric AS op_balance, (characteristics->>'dbpr_reserve_fund_balance')::numeric AS reserve_balance FROM entities WHERE characteristics->>'dbpr_financial_distress' IS NOT NULL ORDER BY (characteristics->>'dbpr_operating_fund_balance')::numeric ASC NULLS LAST",
    },
    {
        "name": "Citizens Candidates",
        "description": "Properties likely on Citizens Insurance",
        "sql": "SELECT id, name, county, (characteristics->>'citizens_likelihood')::int AS likelihood, characteristics->>'citizens_likelihood_tier' AS tier, characteristics->>'citizens_premium_display' AS est_premium FROM entities WHERE characteristics->>'citizens_candidate' = 'true' ORDER BY (characteristics->>'citizens_likelihood')::int DESC",
    },
    {
        "name": "SIRS Non-Compliant",
        "description": "Associations that haven't filed SIRS (high compliance risk)",
        "sql": "SELECT id, name, county, characteristics->>'sirs_compliance_risk' AS risk, characteristics->>'sirs_completed' AS completed, characteristics->>'dbpr_condo_name' AS condo_name FROM entities WHERE characteristics->>'sirs_compliance_risk' = 'HIGH' ORDER BY county, name",
    },
    {
        "name": "Enrichment Coverage",
        "description": "Count of entities with each enrichment source",
        "sql": "SELECT key AS enricher, COUNT(*) AS entities FROM entities, jsonb_object_keys(enrichment_sources) AS key GROUP BY key ORDER BY COUNT(*) DESC",
    },
    {
        "name": "County Summary",
        "description": "Entity count and stage distribution per county",
        "sql": "SELECT county, pipeline_stage, COUNT(*) AS cnt FROM entities WHERE county IS NOT NULL GROUP BY county, pipeline_stage ORDER BY county, pipeline_stage",
    },
    {
        "name": "Contacts with Email",
        "description": "All contacts that have email addresses",
        "sql": "SELECT c.id, c.name, c.title, c.email, c.source, e.name AS entity_name, e.county FROM contacts c JOIN entities e ON c.entity_id = e.id WHERE c.email IS NOT NULL AND c.email != '' ORDER BY e.county, e.name",
    },
]


@router.get("/api/admin/sql/presets")
def get_sql_presets():
    """Return the list of canned SQL query presets."""
    return {"presets": CANNED_QUERIES}


@router.get("/api/admin/dataset-diagnostics")
def dataset_diagnostics(db: Session = Depends(get_db)):
    """Quick dataset health check — use code distribution, value histogram,
    unit count distribution, county breakdown, and a few canned spot-checks.

    Useful for confirming whether the seeded dataset actually contains the
    kinds of properties we think it does (e.g. are we getting real
    condo master parcels or just small apartment buildings).
    """
    # 1. DOR use code distribution — how many of each type
    use_code_rows = db.execute(sa.text("""
        SELECT
            characteristics->>'dor_use_code' AS use_code,
            characteristics->>'dor_use_description' AS use_label,
            COUNT(*) AS cnt
        FROM entities
        WHERE characteristics->>'dor_use_code' IS NOT NULL
        GROUP BY 1, 2
        ORDER BY cnt DESC
    """)).fetchall()
    use_codes = [
        {"code": r[0], "label": r[1], "count": r[2]}
        for r in use_code_rows
    ]

    # 2. Value histogram by DOR market value — tells us if the dataset is
    # dominated by small properties or has real high-value buildings
    value_buckets = [
        ("<$2M",     0,           2_000_000),
        ("$2-5M",    2_000_000,   5_000_000),
        ("$5-10M",   5_000_000,   10_000_000),
        ("$10-20M",  10_000_000,  20_000_000),
        ("$20-50M",  20_000_000,  50_000_000),
        ("$50-100M", 50_000_000,  100_000_000),
        (">$100M",   100_000_000, 999_999_999_999),
    ]
    value_hist = []
    for label, low, high in value_buckets:
        cnt = db.execute(sa.text("""
            SELECT COUNT(*) FROM entities
            WHERE (characteristics->>'dor_market_value')::bigint >= :low
              AND (characteristics->>'dor_market_value')::bigint < :high
        """), {"low": low, "high": high}).scalar() or 0
        value_hist.append({"bucket": label, "count": cnt})

    # 3. Unit count histogram — distinguishes individual unit parcels from
    # building-level parcels
    unit_buckets = [
        ("1 unit",     1,    2),
        ("2-9 units",  2,    10),
        ("10-24",      10,   25),
        ("25-49",      25,   50),
        ("50-99",      50,   100),
        ("100-199",    100,  200),
        ("200+",       200,  100000),
    ]
    unit_hist = []
    for label, low, high in unit_buckets:
        cnt = db.execute(sa.text("""
            SELECT COUNT(*) FROM entities
            WHERE (characteristics->>'dor_num_units')::int >= :low
              AND (characteristics->>'dor_num_units')::int < :high
        """), {"low": low, "high": high}).scalar() or 0
        unit_hist.append({"bucket": label, "count": cnt})

    # 4. County breakdown — how many entities per county
    county_rows = db.execute(sa.text("""
        SELECT county, COUNT(*) AS cnt
        FROM entities
        WHERE county IS NOT NULL
        GROUP BY county
        ORDER BY cnt DESC
    """)).fetchall()
    counties = [{"county": r[0], "count": r[1]} for r in county_rows]

    # 5. Spot checks — highest-value entities in the dataset
    top_value_rows = db.execute(sa.text("""
        SELECT
            id,
            name,
            county,
            (characteristics->>'dor_market_value')::bigint AS jv,
            (characteristics->>'dor_num_units')::int AS units,
            characteristics->>'dor_use_code' AS use_code,
            characteristics->>'dor_use_description' AS use_label,
            characteristics->>'dbpr_condo_name' AS dbpr_name
        FROM entities
        WHERE characteristics->>'dor_market_value' IS NOT NULL
        ORDER BY (characteristics->>'dor_market_value')::bigint DESC
        LIMIT 20
    """)).fetchall()
    top_by_value = [
        {
            "id": r[0], "name": r[1], "county": r[2],
            "market_value": r[3], "units": r[4],
            "use_code": r[5], "use_label": r[6],
            "dbpr_condo_name": r[7],
        }
        for r in top_value_rows
    ]

    # 6. Spot checks — largest by unit count
    top_unit_rows = db.execute(sa.text("""
        SELECT
            id,
            name,
            county,
            (characteristics->>'dor_num_units')::int AS units,
            (characteristics->>'dor_market_value')::bigint AS jv,
            characteristics->>'dor_use_code' AS use_code,
            characteristics->>'dbpr_condo_name' AS dbpr_name
        FROM entities
        WHERE characteristics->>'dor_num_units' IS NOT NULL
          AND (characteristics->>'dor_num_units')::int >= 10
        ORDER BY (characteristics->>'dor_num_units')::int DESC
        LIMIT 20
    """)).fetchall()
    top_by_units = [
        {
            "id": r[0], "name": r[1], "county": r[2],
            "units": r[3], "market_value": r[4],
            "use_code": r[5], "dbpr_condo_name": r[6],
        }
        for r in top_unit_rows
    ]

    # 7. Total counts
    total_entities = db.query(Entity).count()
    lead_count = db.query(Entity).filter(Entity.pipeline_stage == "LEAD").count()

    return {
        "total_entities": total_entities,
        "lead_count": lead_count,
        "use_codes": use_codes,
        "value_histogram": value_hist,
        "unit_histogram": unit_hist,
        "counties": counties,
        "top_20_by_value": top_by_value,
        "top_20_by_units": top_by_units,
    }


@router.post("/api/admin/services/prune")
def prune_services(stale_only: bool = Query(False, description="Only prune services with no heartbeat in an hour")):
    """Remove ghost / stale service rows from the registry.

    - Default: deletes known-legacy services (enrichment_worker, hunter).
      Safe because we know these were replaced by job_consumer + queue_manager.
    - With stale_only=true: deletes any service that hasn't heartbeated in
      over an hour. Useful after architecture changes.
    """
    from services.registry import prune_legacy_services, prune_stale_services
    if stale_only:
        count = prune_stale_services()
    else:
        count = prune_legacy_services()
    return {"success": True, "pruned": count}


@router.post("/api/admin/backfill-ocean-distance")
def backfill_ocean_distance(db: Session = Depends(get_db)):
    """Compute distance_to_ocean_miles for every geocoded entity that's
    missing it. Useful after shipping the geo utility to enrich existing
    LEADs without a full reseed."""
    from utils.geo import distance_to_ocean_miles

    entities = db.query(Entity).filter(
        Entity.latitude.isnot(None),
        Entity.longitude.isnot(None),
    ).all()

    updated = 0
    for entity in entities:
        chars = dict(entity.characteristics or {})
        if "distance_to_ocean_miles" in chars:
            continue
        d = distance_to_ocean_miles(entity.latitude, entity.longitude)
        if d is not None:
            chars["distance_to_ocean_miles"] = d
            entity.characteristics = chars
            updated += 1

    db.commit()
    return {"success": True, "updated": updated, "total_geocoded": len(entities)}


@router.post("/api/admin/extract-dor-zips")
def extract_dor_zips_endpoint():
    """Manually trigger extraction of DOR NAL/SDF zip files in System Data/DOR/.

    Scans for zip files matching '{County} {code} Final {NAL|SDF} {year}.zip',
    extracts the CSV inside, renames to standard format, then runs the auto-seed
    scanner. Skips TPP (tangible personal property) zips.
    """
    dor_dir = os.path.join(FILE_STORE_ROOT, "System Data", "DOR")
    extracted = _extract_dor_zips(dor_dir)

    # Auto-seed after extraction
    seed_result = {}
    if extracted:
        try:
            from agents.seeder import scan_dor_dir_and_auto_seed
            seed_result = scan_dor_dir_and_auto_seed()
        except Exception as e:
            seed_result = {"error": str(e)[:200]}

    return {
        "success": True,
        "extracted": extracted,
        "auto_seed": seed_result,
    }


@router.post("/api/admin/backfill-tiv")
def backfill_tiv(db: Session = Depends(get_db)):
    """Recompute tiv_estimate for entities that already have a DBPR
    official unit count but were seeded before the post-DBPR TIV
    recomputation logic shipped.

    Walks every entity with dbpr_official_units > 1 and recomputes TIV
    from the unit count, taking the larger of the new and existing TIV.
    """
    from agents.seeder import _compute_replacement_tiv

    # Use ORM with the JSONB ? operator — more reliable than raw SQL
    # cast syntax which has tripped over psycopg2 type inference before.
    entities = db.query(Entity).filter(
        Entity.characteristics.op("?")("dbpr_official_units")
    ).all()

    scanned = 0
    updated = 0
    errors: list[str] = []

    for entity in entities:
        scanned += 1
        try:
            chars = dict(entity.characteristics or {})
            unit_count_raw = chars.get("dbpr_official_units")
            if unit_count_raw is None:
                continue
            unit_count = int(unit_count_raw)
            if unit_count <= 1:
                continue

            living_sqft_raw = chars.get("dor_living_sqft")
            living_sqft = int(living_sqft_raw) if living_sqft_raw else None
            const_class = chars.get("dor_construction_class") or chars.get("construction_class")
            jv_raw = chars.get("dor_market_value")
            jv = int(jv_raw) if jv_raw else None

            new_tiv = _compute_replacement_tiv(
                num_units=unit_count,
                living_sqft=living_sqft,
                construction_class=const_class,
                county=entity.county,
                jv=jv,
            )

            existing_tiv_raw = chars.get("tiv_estimate")
            existing_tiv = int(existing_tiv_raw) if existing_tiv_raw else 0

            if new_tiv and new_tiv > existing_tiv:
                # Shallow copy already done above — SQLAlchemy will detect
                # the mutation when we reassign entity.characteristics
                chars["tiv_estimate"] = new_tiv
                chars["tiv"] = f"${new_tiv:,.0f}"
                chars["tiv_method"] = "unit_replacement_backfill"
                entity.characteristics = chars
                updated += 1
        except Exception as e:
            errors.append(f"Entity {entity.id}: {str(e)[:100]}")
            if len(errors) >= 10:
                break

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return {"success": False, "error": f"Commit failed: {str(e)[:300]}"}

    return {
        "success": True,
        "scanned": scanned,
        "updated": updated,
        "errors": errors if errors else None,
    }


@router.post("/api/admin/seed-users")
def manual_seed_users():
    """Manually trigger user + canned filter seeding.

    Useful when the startup-time seeding silently failed or when the
    canned filter list has been updated and you want them re-inserted
    without a redeploy.
    """
    from routes.user import ensure_default_users
    db = SessionLocal()
    try:
        ensure_default_users(db)
        # Report current state
        from database.models import User, UserSavedFilter
        users = db.query(User).all()
        filters = db.query(UserSavedFilter).all()
        return {
            "success": True,
            "users": [{"username": u.username, "role": u.role, "uuid": u.uuid} for u in users],
            "filters_count": len(filters),
            "filters": [{"name": f.name, "is_shared": bool(f.is_shared)} for f in filters],
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)[:500]}
    finally:
        db.close()


@router.post("/api/admin/auto-seed-scan")
def manual_auto_seed_scan(min_value: int = Query(None, description="Min market value override")):
    """Manually trigger the auto-seed scanner to look for NAL+SDF pairs.

    Useful when files have been uploaded out-of-band (e.g. directly to S3 or
    via shell) and the upload-triggered scan didn't fire.
    """
    from agents.seeder import scan_dor_dir_and_auto_seed
    result = scan_dor_dir_and_auto_seed(min_value=min_value)
    return {"success": True, **result}


@router.post("/api/admin/recalibrate-all")
def recalibrate_all(db: Session = Depends(get_db)):
    """Apply all post-seed corrections to existing entities and re-run enrichers.

    Two phases:

    1. IN-PLACE FIX (no DB wipe needed):
       - Map raw DOR construction codes ('1'..'6') to readable labels
         on entities seeded before the mapping was added
       - Map raw DOR use codes ('003', '004', etc.) to friendly descriptions
         on entities seeded before label expansion

    2. FORCE RE-RUN ENRICHERS:
       - Clear enrichment_sources entries for every enricher whose logic
         has changed (Sunbiz field positions, Citizens math, DBPR address
         matching, KFI/NOIC new enrichers, cream score new signals)
       - Reset / create job_queue entries so the consumer picks them up

    Returns a summary of what was patched and how many jobs were requeued.
    """
    from agents.seeder import DOR_CONSTRUCTION_CLASSES, TARGET_USE_CODES

    summary: dict = {
        "phase_1_inplace": {},
        "phase_2_requeue": {},
    }

    # ── Phase 1: in-place characteristic patches ──

    # 1a. DOR construction class numeric → label
    construction_patched = 0
    for raw_code, label in DOR_CONSTRUCTION_CLASSES.items():
        # Only update entities where the raw numeric code is currently stored.
        # Explicit ::text casts so PostgreSQL can infer the jsonb scalar type.
        result = db.execute(sa.text("""
            UPDATE entities
            SET characteristics = jsonb_set(
                jsonb_set(
                    characteristics,
                    '{dor_construction_class_raw}',
                    to_jsonb(CAST(:raw AS text)),
                    true
                ),
                '{dor_construction_class}',
                to_jsonb(CAST(:label AS text)),
                true
            )
            WHERE characteristics->>'dor_construction_class' = :raw
        """), {"raw": raw_code, "label": label})
        construction_patched += result.rowcount or 0
    summary["phase_1_inplace"]["dor_construction_class_patched"] = construction_patched

    # 1b. DOR use description "Code XXX" → friendly label
    use_desc_patched = 0
    for raw_code, label in TARGET_USE_CODES.items():
        result = db.execute(sa.text("""
            UPDATE entities
            SET characteristics = jsonb_set(
                characteristics,
                '{dor_use_description}',
                to_jsonb(CAST(:label AS text)),
                true
            )
            WHERE characteristics->>'dor_use_code' = :raw
              AND characteristics->>'dor_use_description' LIKE 'Code %'
        """), {"raw": raw_code, "label": label})
        use_desc_patched += result.rowcount or 0
    summary["phase_1_inplace"]["dor_use_description_patched"] = use_desc_patched

    db.commit()

    # ── Phase 2: force-rerun enrichers whose logic changed ──
    #
    # Implemented in bulk SQL (not ORM loops) so this finishes in seconds
    # instead of minutes. Previously each enricher did a per-entity Python
    # loop that generated ~N queries × 9 enrichers which would HTTP-timeout
    # on large datasets.

    # Import the canonical ENRICHER_CHAIN so we use the SAME priorities
    # the producer uses. Hardcoding priority=5 meant new jobs landed at a
    # lower tier than the original producer priorities, which caused
    # dbpr_kfi/noic/oir_market/citizens/cream_score to stall behind the
    # priority-10 dbpr_bulk backlog.
    from services.job_queue import ENRICHER_CHAIN
    priority_map = {spec["enricher"]: spec["priority"] for spec in ENRICHER_CHAIN}

    # Order matters because of dependencies:
    #   dbpr_bulk → dbpr_payments / dbpr_kfi / dbpr_sirs / dbpr_building
    #   oir_market → citizens_insurance
    #   <everything> → cream_score
    enrichers_to_rerun = [
        "dbpr_bulk",       # Strict address matching fix
        "dbpr_payments",   # Re-runs after dbpr_bulk
        "dbpr_kfi",        # New enricher — first pass
        "dbpr_sirs",       # Now reads xlsx instead of portal scrape
        "dbpr_noic",       # New enricher — first pass
        "sunbiz_bulk",     # Field position fix
        "oir_market",      # Updated for 24 new counties
        "citizens_insurance",  # Markup over OIR market
        "cream_score",     # New financial-distress + hurricane signals
    ]

    # Per-enricher characteristic fields to clear when re-running
    # (so the new enricher logic repopulates them cleanly)
    field_cleanups: dict[str, list[str]] = {
        "citizens_insurance": [
            "citizens_likelihood", "citizens_likelihood_tier",
            "citizens_county_penetration", "citizens_estimated_premium",
            "citizens_premium_display", "citizens_risk_factors",
            "citizens_candidate", "citizens_swap_opportunity",
            "citizens_estimate_source",
        ],
    }

    requeue_summary: dict[str, dict] = {}
    for enricher in enrichers_to_rerun:
        # Pull the correct priority from the producer chain. Default to 5
        # for anything unknown (shouldn't happen, but safe).
        priority = priority_map.get(enricher, 5)
        try:
            # Step 1: Remove this enricher from enrichment_sources on every
            # entity that had it (single UPDATE).
            cleared_res = db.execute(sa.text("""
                UPDATE entities
                SET enrichment_sources = enrichment_sources - :enricher
                WHERE enrichment_sources ? :enricher
            """), {"enricher": enricher})
            cleared = cleared_res.rowcount or 0

            # Step 2: For enrichers with derived characteristic fields
            # (currently only citizens_insurance), strip those fields in
            # one bulk UPDATE. We chain `- 'key'` operators because the
            # field names are hardcoded constants (no SQL injection risk)
            # and this avoids psycopg2 array binding edge cases.
            if enricher in field_cleanups:
                fields = field_cleanups[enricher]
                # Safe: all field names are internal Python constants
                chain = " ".join(f"- '{f}'" for f in fields)
                db.execute(sa.text(f"""
                    UPDATE entities
                    SET characteristics = characteristics {chain}
                    WHERE pipeline_stage = 'LEAD'
                """))

            # Step 3: Bulk upsert job_queue entries for every LEAD-stage
            # entity. Uses the unique index (entity_id, enricher) so
            # existing jobs get reset and missing ones get created in a
            # single statement. CRITICAL: the DO UPDATE clause sets both
            # priority AND created_at from EXCLUDED so requeued jobs
            # sort correctly in the consumer's batch query.
            upsert_res = db.execute(sa.text("""
                INSERT INTO job_queue
                    (entity_id, enricher, status, priority, attempts,
                     max_attempts, last_error, locked_by, locked_at,
                     completed_at, created_at)
                SELECT e.id, :enricher, 'PENDING', :priority, 0,
                       3, NULL, NULL, NULL,
                       NULL, NOW()
                FROM entities e
                WHERE e.pipeline_stage = 'LEAD'
                ON CONFLICT (entity_id, enricher) DO UPDATE SET
                    status = 'PENDING',
                    priority = EXCLUDED.priority,
                    attempts = 0,
                    last_error = NULL,
                    locked_by = NULL,
                    locked_at = NULL,
                    completed_at = NULL,
                    created_at = EXCLUDED.created_at
            """), {"enricher": enricher, "priority": priority})
            requeued = upsert_res.rowcount or 0

            db.commit()

            requeue_summary[enricher] = {
                "cleared": cleared,
                "requeued": requeued,
                "priority": priority,
            }
        except Exception as e:
            db.rollback()
            requeue_summary[enricher] = {"error": str(e)[:200]}
            logger.warning(f"Recalibrate failed for {enricher}: {e}")

    summary["phase_2_requeue"] = requeue_summary

    total_requeued = sum(
        r.get("requeued", 0)
        for r in requeue_summary.values()
        if isinstance(r, dict)
    )
    total_cleared = sum(
        r.get("cleared", 0)
        for r in requeue_summary.values()
        if isinstance(r, dict)
    )

    emit(EventType.SYSTEM, "recalibrate_all", EventStatus.SUCCESS,
         detail=f"Patched {construction_patched + use_desc_patched} fields, "
                f"cleared {total_cleared}, requeued {total_requeued} jobs")

    summary["totals"] = {
        "fields_patched": construction_patched + use_desc_patched,
        "sources_cleared": total_cleared,
        "jobs_requeued": total_requeued,
    }

    return {"success": True, **summary}


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


def _extract_dor_zips(dor_dir: str) -> list[str]:
    """Extract DOR NAL/SDF zip files into standard-named CSVs.

    DOR DataPortal downloads are named like:
      'Broward 16 Final NAL 2025.zip'
      'Miami-Dade 23 Final SDF 2025 (1).zip'

    We extract the CSV inside, rename it to the standard format that the
    seeder expects (NAL{code}F202501.csv / SDF{code}F202501.csv), and
    leave the zip in place (so re-extraction is idempotent).

    TPP (Tangible Personal Property) zips are silently skipped.
    """
    import re
    import zipfile

    if not os.path.isdir(dor_dir):
        return []

    extracted = []
    for fname in os.listdir(dor_dir):
        if not fname.lower().endswith(".zip"):
            continue

        # Parse: "{County} {code} Final {NAL|SDF|TPP} 2025*.zip"
        match = re.search(r'(\d+)\s+Final\s+(NAL|SDF|TPP)\s+(\d{4})', fname, re.IGNORECASE)
        if not match:
            continue

        county_code = match.group(1)
        roll_type = match.group(2).upper()
        year = match.group(3)

        # Skip TPP — tangible personal property, not real estate
        if roll_type == "TPP":
            continue

        # Check if we already extracted this one
        standard_name = f"{roll_type}{county_code}F{year}01.csv"
        standard_path = os.path.join(dor_dir, standard_name)
        if os.path.exists(standard_path):
            continue  # Already extracted

        zip_path = os.path.join(dor_dir, fname)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # Find the CSV inside — usually just one file
                csv_files = [n for n in zf.namelist()
                             if n.lower().endswith(".csv") and not n.startswith("__")]
                if not csv_files:
                    logger.warning(f"DOR zip has no CSV: {fname}")
                    continue

                # Extract the largest CSV (in case of multiple)
                target = max(csv_files, key=lambda n: zf.getinfo(n).file_size)
                # Extract to a temp name, then rename to standard
                zf.extract(target, dor_dir)
                extracted_path = os.path.join(dor_dir, target)

                # Rename to standard format
                if extracted_path != standard_path:
                    if os.path.exists(standard_path):
                        os.remove(standard_path)
                    os.rename(extracted_path, standard_path)

                size_mb = os.path.getsize(standard_path) / (1024 * 1024)
                logger.info(f"Extracted DOR {roll_type} for county {county_code}: "
                            f"{standard_name} ({size_mb:.1f} MB)")
                extracted.append(standard_name)

        except zipfile.BadZipFile:
            logger.warning(f"Bad zip file: {fname}")
        except Exception as e:
            logger.warning(f"Failed to extract {fname}: {e}")

    if extracted:
        emit(EventType.SYSTEM, "dor_zip_extract", EventStatus.SUCCESS,
             detail=f"Extracted {len(extracted)} DOR files: {', '.join(extracted[:5])}"
                    + (f"... +{len(extracted)-5} more" if len(extracted) > 5 else ""))

    return extracted


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

    # Auto-process: if a DOR zip was uploaded, extract the CSV inside and
    # rename to standard format (NAL{code}F202501.csv / SDF{code}F202501.csv).
    # Then the auto-seed scanner picks up the extracted CSVs.
    auto_seed_result: dict | None = None
    is_dor_upload = (
        path.replace("\\", "/").lower().startswith("system data/dor")
    )
    if is_dor_upload:
        # Extract any zips that just landed
        try:
            _extract_dor_zips(os.path.dirname(filepath))
        except Exception as e:
            logger.warning(f"DOR zip extraction failed: {e}")

        # Scan for complete NAL+SDF pairs and auto-seed
        try:
            from agents.seeder import scan_dor_dir_and_auto_seed
            auto_seed_result = scan_dor_dir_and_auto_seed()
            if auto_seed_result.get("triggered"):
                triggered_names = ", ".join(t["county"] for t in auto_seed_result["triggered"])
                logger.info(f"Auto-seed triggered for: {triggered_names}")
                emit(EventType.SYSTEM, "auto_seed_scan", EventStatus.SUCCESS,
                     detail=f"Triggered: {triggered_names}")
        except Exception as e:
            logger.warning(f"Auto-seed scan failed: {e}")

    rel = os.path.relpath(filepath, FILE_STORE_ROOT)
    response: dict = {
        "success": True,
        "name": filename,
        "path": rel,
        "size": total_size,
    }
    if auto_seed_result:
        response["auto_seed"] = auto_seed_result
    return response


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
