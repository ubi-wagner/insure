"""
Event Bus - Central event capture and streaming for observability.

Captures HTTP requests, DB operations, API calls, hunter agent activity,
and AI analyzer events. Stores recent events in memory and streams
new events to connected SSE clients.
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    HTTP_REQUEST = "HTTP"
    DB_OPERATION = "DB"
    API_CALL = "API"
    HUNTER = "HUNTER"
    AI_ANALYZER = "AI"
    AUTH = "AUTH"
    SYSTEM = "SYSTEM"


class EventStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    PENDING = "pending"


@dataclass
class Event:
    event_type: EventType
    action: str
    status: EventStatus
    detail: str = ""
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["status"] = self.status.value
        return d


class EventBus:
    """Thread-safe event bus with in-memory ring buffer and SSE fan-out."""

    def __init__(self, max_events: int = 500):
        self._events: deque[Event] = deque(maxlen=max_events)
        self._subscribers: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def emit(self, event: Event):
        """Emit an event (thread-safe — can be called from background threads)."""
        self._events.append(event)

        if self._loop and self._subscribers:
            for queue in self._subscribers:
                try:
                    self._loop.call_soon_threadsafe(queue.put_nowait, event)
                except Exception:
                    pass

    def get_recent(self, limit: int = 100, event_type: str | None = None) -> list[dict]:
        """Get recent events, optionally filtered by type."""
        events = list(self._events)
        if event_type:
            events = [e for e in events if e.event_type.value == event_type]
        return [e.to_dict() for e in events[-limit:]]

    async def subscribe(self) -> asyncio.Queue:
        """Subscribe to new events. Returns an asyncio.Queue."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        """Remove a subscriber."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)


# Singleton
event_bus = EventBus()


def emit(event_type: EventType, action: str, status: EventStatus,
         detail: str = "", duration_ms: float | None = None, **metadata):
    """Convenience function to emit an event."""
    event_bus.emit(Event(
        event_type=event_type,
        action=action,
        status=status,
        detail=detail,
        duration_ms=duration_ms,
        metadata=metadata,
    ))
