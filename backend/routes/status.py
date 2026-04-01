from fastapi import APIRouter

from services.registry import get_all_statuses

router = APIRouter()


@router.get("/api/status")
def system_status():
    """Return status of all registered services."""
    services = get_all_statuses()
    # Overall system health
    statuses = [s["status"] for s in services]
    if not statuses:
        overall = "unknown"
    elif all(s == "healthy" for s in statuses):
        overall = "healthy"
    elif any(s in ("down", "error") for s in statuses):
        overall = "degraded"
    else:
        overall = "partial"

    return {
        "overall": overall,
        "services": services,
    }
