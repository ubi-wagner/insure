"""
Timebomb Event System

Scheduled events that sit in a queue until their trigger time passes,
then fire an action. Each timebomb:
- Has a trigger datetime
- Has a payload (action function + args)
- Posts a START event when triggered
- Posts a COMPLETE or ERROR event when finished
- Stales out if not completed within a timeout

Usage:
    from services.timebomb import schedule, cancel, list_pending

    # Schedule a data refresh for tomorrow at 3am
    schedule(
        name="weekly_data_refresh",
        trigger_at=datetime(2026, 4, 4, 3, 0),
        action="refresh_all",
        repeat_hours=168,  # Repeat weekly
    )

    # Schedule DBPR refresh every 24 hours
    schedule(
        name="daily_dbpr_refresh",
        trigger_at=datetime.now() + timedelta(hours=24),
        action="refresh_dbpr",
        repeat_hours=24,
    )
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)

# Registry of available actions
ACTIONS: dict[str, Callable] = {}

# Active timebombs
_timebombs: list[dict] = []
_lock = threading.Lock()
_running = False


def register_action(name: str, func: Callable):
    """Register an action that timebombs can trigger."""
    ACTIONS[name] = func
    logger.info(f"Timebomb action registered: {name}")


def schedule(
    name: str,
    trigger_at: datetime,
    action: str,
    repeat_hours: float | None = None,
    timeout_minutes: int = 60,
    detail: str = "",
) -> dict:
    """Schedule a timebomb event.

    Args:
        name: Unique identifier for this timebomb
        trigger_at: When to fire (UTC)
        action: Name of registered action to call
        repeat_hours: If set, reschedule after completion
        timeout_minutes: Max time for action to run before stale-out
        detail: Human-readable description
    """
    if action not in ACTIONS:
        available = list(ACTIONS.keys())
        raise ValueError(f"Unknown action '{action}'. Available: {available}")

    bomb = {
        "name": name,
        "trigger_at": trigger_at,
        "action": action,
        "repeat_hours": repeat_hours,
        "timeout_minutes": timeout_minutes,
        "detail": detail or f"{action} scheduled for {trigger_at.isoformat()}",
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "last_run": None,
        "run_count": 0,
    }

    with _lock:
        # Replace existing bomb with same name
        _timebombs[:] = [b for b in _timebombs if b["name"] != name]
        _timebombs.append(bomb)

    emit(EventType.SYSTEM, "timebomb_scheduled", EventStatus.PENDING,
         detail=f"'{name}' → {action} at {trigger_at.strftime('%Y-%m-%d %H:%M UTC')}"
                + (f" (repeat every {repeat_hours}h)" if repeat_hours else ""))

    logger.info(f"Timebomb scheduled: {name} → {action} at {trigger_at}")
    return bomb


def cancel(name: str) -> bool:
    """Cancel a pending timebomb."""
    with _lock:
        before = len(_timebombs)
        _timebombs[:] = [b for b in _timebombs if b["name"] != name]
        removed = len(_timebombs) < before

    if removed:
        emit(EventType.SYSTEM, "timebomb_cancelled", EventStatus.SUCCESS,
             detail=f"'{name}' cancelled")
        logger.info(f"Timebomb cancelled: {name}")
    return removed


def list_pending() -> list[dict]:
    """List all pending timebombs."""
    with _lock:
        return [
            {
                "name": b["name"],
                "action": b["action"],
                "trigger_at": b["trigger_at"].isoformat(),
                "repeat_hours": b["repeat_hours"],
                "status": b["status"],
                "detail": b["detail"],
                "run_count": b["run_count"],
                "last_run": b["last_run"].isoformat() if b["last_run"] else None,
            }
            for b in _timebombs
        ]


def _fire_bomb(bomb: dict):
    """Execute a timebomb's action."""
    name = bomb["name"]
    action_name = bomb["action"]
    action_func = ACTIONS.get(action_name)

    if not action_func:
        logger.error(f"Timebomb '{name}' has unknown action: {action_name}")
        bomb["status"] = "error"
        return

    bomb["status"] = "running"
    start_time = datetime.now(timezone.utc)
    bomb["last_run"] = start_time

    emit(EventType.SYSTEM, "timebomb_fired", EventStatus.PENDING,
         detail=f"'{name}' → {action_name} starting")

    try:
        result = action_func()
        bomb["status"] = "complete"
        bomb["run_count"] += 1
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        emit(EventType.SYSTEM, "timebomb_complete", EventStatus.SUCCESS,
             detail=f"'{name}' → {action_name} completed in {elapsed:.0f}s",
             duration_ms=elapsed * 1000)

        logger.info(f"Timebomb '{name}' completed in {elapsed:.0f}s: {result}")

    except Exception as e:
        bomb["status"] = "error"
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        emit(EventType.SYSTEM, "timebomb_error", EventStatus.ERROR,
             detail=f"'{name}' → {action_name} failed after {elapsed:.0f}s: {str(e)[:150]}",
             duration_ms=elapsed * 1000)

        logger.error(f"Timebomb '{name}' failed: {e}")

    # Reschedule if repeating
    if bomb.get("repeat_hours") and bomb["status"] in ("complete", "error"):
        next_trigger = datetime.now(timezone.utc) + timedelta(hours=bomb["repeat_hours"])
        bomb["trigger_at"] = next_trigger
        bomb["status"] = "pending"
        emit(EventType.SYSTEM, "timebomb_rescheduled", EventStatus.PENDING,
             detail=f"'{name}' → next run at {next_trigger.strftime('%Y-%m-%d %H:%M UTC')}")
        logger.info(f"Timebomb '{name}' rescheduled for {next_trigger}")


def _check_loop():
    """Background loop that checks for timebombs ready to fire."""
    global _running
    _running = True

    while _running:
        now = datetime.now(timezone.utc)

        with _lock:
            ready = [b for b in _timebombs if b["status"] == "pending" and b["trigger_at"] <= now]

        for bomb in ready:
            # Fire in a separate thread so we don't block the check loop
            thread = threading.Thread(
                target=_fire_bomb, args=(bomb,), daemon=True,
                name=f"timebomb-{bomb['name']}")
            thread.start()

        # Also check for stale-outs
        with _lock:
            for bomb in _timebombs:
                if bomb["status"] == "running" and bomb.get("last_run"):
                    elapsed = (now - bomb["last_run"]).total_seconds() / 60
                    if elapsed > bomb.get("timeout_minutes", 60):
                        bomb["status"] = "stale"
                        emit(EventType.SYSTEM, "timebomb_stale", EventStatus.ERROR,
                             detail=f"'{bomb['name']}' timed out after {elapsed:.0f}min")
                        logger.warning(f"Timebomb '{bomb['name']}' staled out after {elapsed:.0f}min")

        time.sleep(30)  # Check every 30 seconds


def start_timebomb_checker():
    """Start the background timebomb checker thread."""
    thread = threading.Thread(target=_check_loop, daemon=True, name="timebomb-checker")
    thread.start()
    logger.info("Timebomb checker started (30s interval)")
    return thread


def setup_default_schedules():
    """Set up default data refresh schedules."""
    from scripts.data_refresh import refresh_all, refresh_dbpr, refresh_dor_nal

    register_action("refresh_all", refresh_all)
    register_action("refresh_dbpr", refresh_dbpr)
    register_action("refresh_dor_nal", refresh_dor_nal)

    try:
        from scripts.data_refresh import refresh_sunbiz, refresh_cadastral
        register_action("refresh_sunbiz", refresh_sunbiz)
        register_action("refresh_cadastral", refresh_cadastral)
    except Exception:
        pass

    # Weekly full data refresh — Sundays at 3am UTC
    now = datetime.now(timezone.utc)
    next_sunday = now + timedelta(days=(6 - now.weekday()) % 7 or 7)
    next_sunday = next_sunday.replace(hour=3, minute=0, second=0, microsecond=0)

    schedule(
        name="weekly_full_refresh",
        trigger_at=next_sunday,
        action="refresh_all",
        repeat_hours=168,  # 7 days
        detail="Weekly full data refresh (DOR + DBPR + Sunbiz + ArcGIS)",
    )

    # Daily DBPR refresh — every day at 2am UTC
    tomorrow_2am = (now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
    schedule(
        name="daily_dbpr_refresh",
        trigger_at=tomorrow_2am,
        action="refresh_dbpr",
        repeat_hours=24,
        detail="Daily DBPR condo registry + payment history refresh",
    )

    logger.info("Default timebomb schedules configured")
