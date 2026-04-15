"""
User-scoped endpoints.

Identity comes from the X-User-Name header injected by the Next.js proxy
from the auth cookie. The backend doesn't re-authenticate — the proxy is
trusted. For now, any request reaching these endpoints with a valid
X-User-Name header is treated as authenticated as that user.

Future: move auth fully to backend with JWT + proper session tokens.
"""

import logging
import uuid as uuid_lib
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from database.models import User, UserSavedFilter

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Helpers ─────────────────────────────────────────────────────────

def get_current_user(
    x_user_name: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the current user from the X-User-Name header.

    The Next.js proxy sets this header based on the auth cookie. If missing
    or invalid, return 401.
    """
    if not x_user_name:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = db.query(User).filter(User.username == x_user_name.lower()).first()
    if not user:
        # Try by display name as fallback (older cookies stored displayName)
        user = db.query(User).filter(User.display_name == x_user_name).first()
    if not user:
        raise HTTPException(status_code=401, detail=f"Unknown user: {x_user_name}")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is inactive")

    return user


# ─── /api/user/me ─────────────────────────────────────────────────────

@router.get("/api/user/me")
def get_me(user: User = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return {
        "uuid": user.uuid,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "email": user.email,
    }


# ─── Saved Filters CRUD ───────────────────────────────────────────────

class SavedFilterCreate(BaseModel):
    name: str
    filter_json: dict
    is_shared: bool = False


class SavedFilterUpdate(BaseModel):
    name: str | None = None
    filter_json: dict | None = None
    is_shared: bool | None = None


@router.get("/api/user/filters")
def list_saved_filters(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List saved filters visible to the current user.

    Returns the user's own filters + any filters marked is_shared=true
    from other users. Own filters come first.
    """
    own = db.query(UserSavedFilter).filter(
        UserSavedFilter.user_uuid == user.uuid,
    ).order_by(UserSavedFilter.name).all()

    shared = db.query(UserSavedFilter, User).join(
        User, UserSavedFilter.user_uuid == User.uuid
    ).filter(
        UserSavedFilter.is_shared.is_(True),
        UserSavedFilter.user_uuid != user.uuid,
    ).order_by(UserSavedFilter.name).all()

    def _serialize(f: UserSavedFilter, owner: User | None = None) -> dict:
        return {
            "id": f.id,
            "name": f.name,
            "filter_json": f.filter_json,
            "is_shared": bool(f.is_shared),
            "is_own": owner is None,
            "owner_display": owner.display_name if owner else user.display_name,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        }

    return {
        "filters": [_serialize(f) for f in own]
                   + [_serialize(f, owner) for f, owner in shared],
    }


@router.post("/api/user/filters")
def create_saved_filter(
    body: SavedFilterCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new saved filter (or overwrite if the name already exists for this user)."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    existing = db.query(UserSavedFilter).filter(
        UserSavedFilter.user_uuid == user.uuid,
        UserSavedFilter.name == name,
    ).first()

    if existing:
        existing.filter_json = body.filter_json
        existing.is_shared = bool(body.is_shared)
        existing.updated_at = datetime.utcnow()
        db.commit()
        return {"success": True, "id": existing.id, "action": "updated"}

    row = UserSavedFilter(
        user_uuid=user.uuid,
        name=name,
        filter_json=body.filter_json,
        is_shared=bool(body.is_shared),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"success": True, "id": row.id, "action": "created"}


@router.put("/api/user/filters/{filter_id}")
def update_saved_filter(
    filter_id: int,
    body: SavedFilterUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a saved filter — only the owner can modify."""
    row = db.query(UserSavedFilter).filter(UserSavedFilter.id == filter_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Filter not found")
    if row.user_uuid != user.uuid:
        raise HTTPException(status_code=403, detail="Not your filter")

    if body.name is not None:
        row.name = body.name.strip()
    if body.filter_json is not None:
        row.filter_json = body.filter_json
    if body.is_shared is not None:
        row.is_shared = bool(body.is_shared)
    row.updated_at = datetime.utcnow()

    db.commit()
    return {"success": True, "id": row.id}


@router.delete("/api/user/filters/{filter_id}")
def delete_saved_filter(
    filter_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a saved filter — only the owner can delete."""
    row = db.query(UserSavedFilter).filter(UserSavedFilter.id == filter_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Filter not found")
    if row.user_uuid != user.uuid:
        raise HTTPException(status_code=403, detail="Not your filter")

    db.delete(row)
    db.commit()
    return {"success": True}


# ─── User seeding (called from app startup) ──────────────────────────

# Reserved UUID for the System pseudo-user that owns canned filter presets.
# Using a fixed UUID ensures system filters survive across reseeds and that
# we can reliably identify them in queries.
SYSTEM_USER_UUID = "00000000-0000-0000-0000-000000000001"


def ensure_default_users(db: Session):
    """Create eric (admin), jason (user), and the System pseudo-user if they
    don't exist yet. Also seeds the canned shared filter presets.

    Called from the startup lifespan. Idempotent — safe to run on every boot.
    """
    defaults = [
        {"username": "eric",  "display_name": "Eric",  "role": "admin",
         "uuid": str(uuid_lib.uuid4())},
        {"username": "jason", "display_name": "Jason", "role": "user",
         "uuid": str(uuid_lib.uuid4())},
        {"username": "__system__", "display_name": "System", "role": "admin",
         "uuid": SYSTEM_USER_UUID},
    ]
    for spec in defaults:
        existing = db.query(User).filter(User.username == spec["username"]).first()
        if existing:
            continue
        user = User(
            uuid=spec["uuid"],
            username=spec["username"],
            display_name=spec["display_name"],
            role=spec["role"],
            is_active=True,
        )
        db.add(user)
        logger.info(f"Seeded default user: {spec['username']} ({spec['role']})")
    db.commit()

    # Seed canned system filter presets — appear as shared filters in every
    # user's saved-filter list with owner_display="System".
    _seed_canned_system_filters(db)


# Canned filter presets visible to all users.
# Each preset is a complete SavedFilterData payload — empty strings mean
# "no filter on that field". Field shapes match the frontend SavedFilterData.
_CANNED_FILTERS: list[dict] = [
    {
        "name": "Coastal Luxury — Any Type",
        "filter_json": {
            "county": "",
            "sortKey": "value-desc",
            "minValue": "20000000",
            "maxValue": "",
            "minUnits": "",
            "minStories": "",
            "useCode": "",
            "heatFilter": "",
            "citizensOnly": False,
            "creamTier": "",
            "minYear": "1980",
            "maxYear": "",
            "maxDistance": "5",
            "construction": "fire_resistive",
        },
    },
    {
        "name": "Coastal Luxury — Condos Only",
        "filter_json": {
            "county": "",
            "sortKey": "value-desc",
            "minValue": "20000000",
            "maxValue": "",
            "minUnits": "",
            "minStories": "",
            "useCode": "004",
            "heatFilter": "",
            "citizensOnly": False,
            "creamTier": "",
            "minYear": "1980",
            "maxYear": "",
            "maxDistance": "5",
            "construction": "fire_resistive",
        },
    },
    {
        "name": "Citizens Swap Targets",
        "filter_json": {
            "county": "",
            "sortKey": "cream-desc",
            "minValue": "10000000",
            "maxValue": "",
            "minUnits": "",
            "minStories": "",
            "useCode": "",
            "heatFilter": "",
            "citizensOnly": True,
            "creamTier": "",
            "minYear": "",
            "maxYear": "",
            "maxDistance": "10",
            "construction": "",
        },
    },
    {
        "name": "Pre-FBC Beach Risk",
        "filter_json": {
            "county": "",
            "sortKey": "value-desc",
            "minValue": "5000000",
            "maxValue": "",
            "minUnits": "",
            "minStories": "",
            "useCode": "",
            "heatFilter": "",
            "citizensOnly": False,
            "creamTier": "",
            "minYear": "",
            "maxYear": "1992",
            "maxDistance": "1",
            "construction": "",
        },
    },
    {
        "name": "High-Rise Platinum",
        "filter_json": {
            "county": "",
            "sortKey": "cream-desc",
            "minValue": "20000000",
            "maxValue": "",
            "minUnits": "",
            "minStories": "7",
            "useCode": "",
            "heatFilter": "",
            "citizensOnly": False,
            "creamTier": "platinum",
            "minYear": "",
            "maxYear": "",
            "maxDistance": "2",
            "construction": "",
        },
    },
]


def _seed_canned_system_filters(db: Session):
    """Insert any canned filter presets that don't already exist for the
    System user. Existing presets with the same name are NOT overwritten so
    admins can edit them after seeding if they want different defaults."""
    for preset in _CANNED_FILTERS:
        existing = db.query(UserSavedFilter).filter(
            UserSavedFilter.user_uuid == SYSTEM_USER_UUID,
            UserSavedFilter.name == preset["name"],
        ).first()
        if existing:
            continue
        row = UserSavedFilter(
            user_uuid=SYSTEM_USER_UUID,
            name=preset["name"],
            filter_json=preset["filter_json"],
            is_shared=True,
        )
        db.add(row)
        logger.info(f"Seeded canned system filter: {preset['name']}")
    db.commit()
