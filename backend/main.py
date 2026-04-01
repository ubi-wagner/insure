import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.regions import router as regions_router
from routes.leads import router as leads_router
from routes.admin import router as admin_router
from routes.events import router as events_router, EventLoggingMiddleware
from services.event_bus import EventStatus, EventType, emit, event_bus

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Give the event bus access to the running event loop for thread-safe fan-out
    event_bus.set_loop(asyncio.get_running_loop())

    emit(EventType.SYSTEM, "startup", EventStatus.PENDING, detail="Application starting")

    # Run migrations at startup
    try:
        from alembic.config import Config
        from alembic import command
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed")
        emit(EventType.DB_OPERATION, "alembic upgrade head", EventStatus.SUCCESS)
    except Exception as e:
        logger.error(f"Migration failed (app will continue): {e}")
        emit(EventType.DB_OPERATION, "alembic upgrade head", EventStatus.ERROR, detail=str(e)[:300])

    # Start hunter agent
    try:
        from agents.hunter import run_hunter_loop
        thread = threading.Thread(target=run_hunter_loop, daemon=True)
        thread.start()
        logger.info("Hunter agent started")
        emit(EventType.HUNTER, "agent_start", EventStatus.SUCCESS)
    except Exception as e:
        logger.error(f"Failed to start hunter agent: {e}")
        emit(EventType.HUNTER, "agent_start", EventStatus.ERROR, detail=str(e)[:300])

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

app.include_router(regions_router)
app.include_router(leads_router)
app.include_router(admin_router)
app.include_router(events_router)


@app.get("/health")
def health():
    return {"status": "ok"}
