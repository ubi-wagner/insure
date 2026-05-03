"""
Pipeline run-state tracking — used by the ops dashboard to show what's
currently running, what completed when, and what got produced.

Each of the three deterministic gated transitions (seed, qualifier,
aggregator) writes a small JSON file under filestore/System Data/
when it starts and when it finishes. The frontend polls
/api/admin/pipeline/status every couple of seconds while a job is
running and renders progress inline.

State file shape (per stage):
  {
    "running": bool,
    "started_at":  iso8601 or null,
    "finished_at": iso8601 or null,
    "duration_sec": float or null,
    "summary": "human-readable result",
    "details": { ...stage-specific... },
    "current": "what's in flight right now (e.g. county name)"
  }
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)


_STATS_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "filestore",
    "System Data",
)

_FILES = {
    "seed":       os.path.join(_STATS_DIR, "pipeline_state_seed.json"),
    "qualifier":  os.path.join(_STATS_DIR, "pipeline_state_qualifier.json"),
    "aggregator": os.path.join(_STATS_DIR, "pipeline_state_aggregator.json"),
}

_LOCK = RLock()


def _read(stage: str) -> dict[str, Any]:
    path = _FILES.get(stage)
    if not path or not os.path.exists(path):
        return {
            "running": False, "started_at": None, "finished_at": None,
            "duration_sec": None, "summary": None, "details": None,
            "current": None,
        }
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read pipeline state for {stage}: {e}")
        return {
            "running": False, "started_at": None, "finished_at": None,
            "duration_sec": None, "summary": None, "details": None,
            "current": None,
        }


def _write(stage: str, state: dict[str, Any]) -> None:
    path = _FILES.get(stage)
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Failed to write pipeline state for {stage}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def mark_started(stage: str, summary: str | None = None) -> None:
    """Record that a stage has just begun."""
    with _LOCK:
        existing = _read(stage)
        # Preserve the previous finished_at as last_finished_at so the UI can
        # still show "last completed at X" while the new run is in flight.
        last_finished = existing.get("finished_at")
        last_summary = existing.get("summary")
        last_details = existing.get("details")
        _write(stage, {
            "running": True,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "duration_sec": None,
            "summary": None,
            "details": None,
            "current": summary,
            "last_finished_at": last_finished,
            "last_summary": last_summary,
            "last_details": last_details,
        })


def mark_progress(stage: str, current: str, details: dict[str, Any] | None = None) -> None:
    """Update the in-flight indicator while the stage is running."""
    with _LOCK:
        state = _read(stage)
        state["current"] = current
        if details is not None:
            state["details"] = {**(state.get("details") or {}), **details}
        _write(stage, state)


def mark_finished(
    stage: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Record that a stage has completed and persist the result snapshot."""
    with _LOCK:
        state = _read(stage)
        started = state.get("started_at")
        try:
            duration = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(started)
            ).total_seconds() if started else None
        except Exception:
            duration = None

        finished_at = datetime.now(timezone.utc).isoformat()
        _write(stage, {
            "running": False,
            "started_at": started,
            "finished_at": finished_at,
            "duration_sec": round(duration, 1) if duration is not None else None,
            "summary": summary,
            "details": details,
            "current": None,
            "last_finished_at": finished_at,
            "last_summary": summary,
            "last_details": details,
        })


def mark_failed(stage: str, error: str) -> None:
    """Record that a stage crashed."""
    with _LOCK:
        state = _read(stage)
        started = state.get("started_at")
        try:
            duration = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(started)
            ).total_seconds() if started else None
        except Exception:
            duration = None

        _write(stage, {
            "running": False,
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "duration_sec": round(duration, 1) if duration is not None else None,
            "summary": f"Error: {error[:200]}",
            "details": {"error": error[:1000]},
            "current": None,
            "last_finished_at": state.get("last_finished_at"),
            "last_summary": state.get("last_summary"),
            "last_details": state.get("last_details"),
        })


def get_state(stage: str) -> dict[str, Any]:
    """Read the persisted state for one stage."""
    with _LOCK:
        return _read(stage)


def get_all_states() -> dict[str, dict[str, Any]]:
    """Read state for every tracked stage."""
    with _LOCK:
        return {stage: _read(stage) for stage in _FILES}


def is_running(stage: str) -> bool:
    return _read(stage).get("running", False)
