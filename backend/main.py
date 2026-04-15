import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import SessionLocal
from routes.leads import router as leads_router
from routes.admin import router as admin_router
from routes.events import router as events_router, EventLoggingMiddleware
from routes.status import router as status_router
from routes.email import router as email_router
from routes.user import router as user_router, ensure_default_users
from services.event_bus import EventStatus, EventType, emit, event_bus

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Give the event bus access to the running event loop for thread-safe fan-out
    event_bus.set_loop(asyncio.get_running_loop())

    emit(EventType.SYSTEM, "startup", EventStatus.PENDING, detail="Application starting")

    # Run migrations at startup
    migration_ok = False
    try:
        from alembic.config import Config
        from alembic import command
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed")
        emit(EventType.DB_OPERATION, "alembic upgrade head", EventStatus.SUCCESS)
        migration_ok = True
    except Exception as e:
        logger.error(f"Migration failed (app will continue): {e}")
        emit(EventType.DB_OPERATION, "alembic upgrade head", EventStatus.ERROR, detail=str(e)[:300])

    # Register services in the registry (only if migrations ran)
    if migration_ok:
        try:
            from services.registry import register, prune_legacy_services

            # Remove ghost rows from retired architectures so the Ops page
            # doesn't show permanently-stale services (enrichment_worker
            # was replaced by job_consumer + queue_manager; hunter is an
            # older legacy worker).
            prune_legacy_services()

            # Seed default users (eric=admin, jason=user) if missing
            try:
                _seed_db = SessionLocal()
                try:
                    ensure_default_users(_seed_db)
                finally:
                    _seed_db.close()
            except Exception as _e:
                logger.warning(f"User seeding failed: {_e}")

            has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
            register("api", capabilities={
                "version": "0.1.0",
                "migrations": "current",
            }, detail="FastAPI server running")
            register("database", capabilities={
                "migration_head": "f6a7b8c9d0e1",
            }, detail="Connected, migrations applied")
            register("ai_analyzer", capabilities={
                "anthropic_key": has_anthropic,
                "model": "claude-sonnet-4-20250514" if has_anthropic else None,
            }, detail="Ready" if has_anthropic else "Disabled (no API key)")
        except Exception as e:
            logger.error(f"Service registration failed: {e}")

    # Start Census geocode association worker (TARGET → LEAD)
    try:
        from agents.associator import start_association_worker
        start_association_worker()
        logger.info("Association worker started")
        emit(EventType.HUNTER, "associator_start", EventStatus.SUCCESS)
    except Exception as e:
        logger.error(f"Failed to start association worker: {e}")

    # Start job queue consumer + manager (replaces old enrichment worker)
    try:
        from services.job_queue import start_job_consumer, start_queue_manager, produce_jobs_for_all_leads
        start_job_consumer()
        start_queue_manager()
        logger.info("Job consumer + queue manager started")
        emit(EventType.HUNTER, "job_queue_start", EventStatus.SUCCESS,
             detail="Job consumer and queue manager running")

        # Backfill: create jobs for any LEADs that don't have queue entries yet
        # Also extract any DOR zips restored from S3 that haven't been unzipped
        def _backfill():
            import time as _t
            _t.sleep(10)  # Wait for migrations to settle

            # Extract DOR zips first (S3 sync restores zips, not CSVs)
            try:
                from routes.admin import _extract_dor_zips, FILE_STORE_ROOT
                import os as _os
                dor_dir = _os.path.join(FILE_STORE_ROOT, "System Data", "DOR")
                extracted = _extract_dor_zips(dor_dir)
                if extracted:
                    logger.info(f"Startup: extracted {len(extracted)} DOR zips")
            except Exception as _e:
                logger.warning(f"Startup DOR zip extraction failed: {_e}")

            _db = SessionLocal()
            try:
                created = produce_jobs_for_all_leads(_db)
                if created > 0:
                    logger.info(f"Backfilled {created} enrichment jobs on startup")
            except Exception as _e:
                logger.warning(f"Backfill failed: {_e}")
            finally:
                _db.close()

        threading.Thread(target=_backfill, daemon=True).start()

    except Exception as e:
        logger.error(f"Failed to start job queue: {e}")
        # Fallback to old enrichment worker
        try:
            from agents.enrichment_worker import start_enrichment_worker
            start_enrichment_worker()
            logger.info("Fell back to old enrichment worker")
        except Exception as e2:
            logger.error(f"Failed to start enrichment worker fallback: {e2}")

    # Start heartbeat thread for api/database/ai_analyzer services
    def _heartbeat_loop():
        import time
        from services.registry import heartbeat
        while True:
            time.sleep(30)
            try:
                heartbeat("api", detail="FastAPI server running")
                heartbeat("database", detail="Connected, migrations applied")
                has_ai = bool(os.getenv("ANTHROPIC_API_KEY"))
                heartbeat("ai_analyzer", detail="Ready" if has_ai else "Disabled (no API key)")
            except Exception:
                pass

    hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    hb_thread.start()

    # Start timebomb scheduler (data refresh triggers)
    try:
        from services.timebomb import start_timebomb_checker, setup_default_schedules
        setup_default_schedules()
        start_timebomb_checker()
        logger.info("Timebomb scheduler started")
        emit(EventType.SYSTEM, "timebomb_start", EventStatus.SUCCESS,
             detail="Data refresh schedules configured")
    except Exception as e:
        logger.error(f"Failed to start timebomb scheduler: {e}")

    emit(EventType.SYSTEM, "startup", EventStatus.SUCCESS, detail="Application ready")
    yield
    emit(EventType.SYSTEM, "shutdown", EventStatus.SUCCESS, detail="Application shutting down")


app = FastAPI(title="Insure Lead Generation API", lifespan=lifespan)

frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
allowed_origins = [origin.strip() for origin in frontend_url.split(",") if origin.strip()]
if "http://localhost:3000" not in allowed_origins:
    allowed_origins.append("http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTP logging middleware (must be added after CORS)
app.add_middleware(EventLoggingMiddleware)

app.include_router(leads_router)
app.include_router(admin_router)
app.include_router(events_router)
app.include_router(status_router)
app.include_router(email_router)
app.include_router(user_router)


@app.get("/")
def root():
    """Friendly root response so hitting the backend URL directly doesn't
    just return a confusing 404. The real UI is served by the frontend
    service; this is an API-only endpoint."""
    return {
        "service": "insure-api",
        "status": "ok",
        "description": "FL commercial property insurance lead generation API",
        "endpoints": {
            "health": "/health",
            "api_docs": "/docs",
            "leads": "/api/leads",
            "ops_dashboard": "/api/admin/ops-dashboard",
            "queue_status": "/api/admin/queue",
        },
        "note": "The user interface lives on the frontend Railway service.",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
