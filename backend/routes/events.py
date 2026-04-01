import asyncio
import json
import logging
import time

from fastapi import APIRouter, Query, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse

from services.event_bus import EventBus, EventStatus, EventType, emit, event_bus

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTTP Request/Response Middleware
# ---------------------------------------------------------------------------

class EventLoggingMiddleware(BaseHTTPMiddleware):
    """Captures every HTTP request/response into the event bus."""

    async def dispatch(self, request: Request, call_next):
        # Skip SSE stream endpoint to avoid noise
        if request.url.path == "/api/events/stream":
            return await call_next(request)

        start = time.time()
        method = request.method
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""

        try:
            response = await call_next(request)
            duration_ms = round((time.time() - start) * 1000, 1)

            status = EventStatus.SUCCESS if response.status_code < 400 else EventStatus.ERROR
            emit(
                EventType.HTTP_REQUEST,
                action=f"{method} {path}",
                status=status,
                detail=f"{response.status_code}",
                duration_ms=duration_ms,
                query=query,
                status_code=response.status_code,
            )
            return response
        except Exception as e:
            duration_ms = round((time.time() - start) * 1000, 1)
            emit(
                EventType.HTTP_REQUEST,
                action=f"{method} {path}",
                status=EventStatus.ERROR,
                detail=str(e)[:200],
                duration_ms=duration_ms,
                query=query,
            )
            raise


# ---------------------------------------------------------------------------
# REST endpoint: recent events
# ---------------------------------------------------------------------------

@router.get("/api/events")
def get_events(
    limit: int = Query(100, ge=1, le=500),
    event_type: str | None = Query(None),
):
    """Return recent events from the ring buffer."""
    return event_bus.get_recent(limit=limit, event_type=event_type)


# ---------------------------------------------------------------------------
# SSE endpoint: stream events in real time
# ---------------------------------------------------------------------------

@router.get("/api/events/stream")
async def stream_events():
    """Server-Sent Events stream of all new events."""
    queue = await event_bus.subscribe()

    async def event_generator():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                data = json.dumps(event.to_dict())
                yield f"data: {data}\n\n"
        except asyncio.TimeoutError:
            # Send keepalive comment
            yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(queue)

    async def keep_alive_generator():
        """Wraps event_generator with reconnection logic."""
        while True:
            async for chunk in event_generator():
                yield chunk

    return StreamingResponse(
        keep_alive_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
