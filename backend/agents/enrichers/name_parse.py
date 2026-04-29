"""
Name-Parse Enricher

Pulls structural hints out of an entity's name field. Many FL condo
associations encode useful facts directly into the legal name, e.g.

  "ECHO BRICKELL CONDOMINIUM ASSOCIATION INC"
  "TOWER 1 AT BRICKELL POINT 47-STORY"
  "OCEAN ONE 24 STORY CONDO"
  "PARK PLACE PHASE II 12 STORIES"

This is our first-line fallback for `stories` because the DBPR Building
portal frequently returns 403 from cloud egress and the structured
DOR NAL doesn't carry a story count. Without a fallback the cream
score's "wind exposure" tier is unreachable for every entity, capping
scores around 50.

Writes (when found):
  - stories                  unified key consumed by cream_score and validation
  - stories_source           "name_parse" (so it's overwritable by DBPR)
  - units_from_name          unit count parsed from name (defensive — only
                             written when DOR num_units is missing)

Runs with no requires so it executes immediately after seed; later
enrichers (dbpr_building, sirs) can overwrite when they have better
data, because update_characteristics() respects existing values but
we mark these fields as low-confidence via the source attribution.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)


# "56-story", "56 story", "56-stories", "56 STORIES"
_STORIES_RE = re.compile(
    r"\b(\d{1,2})\s*[-]?\s*stor(?:y|ies|ey|eys)\b",
    re.IGNORECASE,
)
# Trailing numeric suffix that is *probably* a story count (only when there's
# no other story signal in the string and the number lands in 3-80).
# Skipped if it looks like a phase/unit identifier ("PHASE 2", "UNIT 4").
_TRAILING_NUM_RE = re.compile(r"(?:\b)(\d{1,3})$")
# Unit count: "171 UNITS", "171 UNIT"
_UNITS_RE = re.compile(r"\b(\d{2,4})\s*units?\b", re.IGNORECASE)
# Year built: "BUILT 2017", "(2017)"
_YEAR_RE = re.compile(r"\b(?:built\s+|completed\s+)?((?:19|20)\d{2})\b", re.IGNORECASE)


def _parse_stories(name: str) -> int | None:
    m = _STORIES_RE.search(name)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 110 else None
    return None


def _parse_units(name: str) -> int | None:
    m = _UNITS_RE.search(name)
    if m:
        n = int(m.group(1))
        return n if 2 <= n <= 5000 else None
    return None


def _parse_year(name: str) -> int | None:
    # Use last year-shaped substring — names sometimes have an old phase
    # number that looks like a year ("PHASE 1985" stays unaffected since
    # we constrain via the (19|20) prefix anyway).
    matches = _YEAR_RE.findall(name)
    if not matches:
        return None
    try:
        y = int(matches[-1])
    except ValueError:
        return None
    return y if 1900 <= y <= 2026 else None


@register_enricher("name_parse", requires=[])
def enrich_name_parse(entity: Entity, db: Session) -> bool:
    """Extract stories / units / year hints from the entity name."""
    name = (entity.name or "").strip()
    if not name:
        return False

    chars = entity.characteristics or {}
    updates: dict = {}

    # Only write `stories` if nothing has populated it yet — DBPR or
    # SIRS scrapes are higher quality.
    if not chars.get("stories"):
        s = _parse_stories(name)
        if s is not None:
            updates["stories"] = s
            updates["stories_source"] = "name_parse"

    # Same logic for units — only fill the gap, never override DOR / DBPR.
    if not chars.get("dor_num_units") and not chars.get("units_estimate"):
        u = _parse_units(name)
        if u is not None:
            updates["units_from_name"] = u
            updates["units_estimate"] = u

    # Year built — only fill if neither the DOR row nor any earlier
    # enricher provided one.
    if not chars.get("year_built") and not chars.get("dor_year_built"):
        y = _parse_year(name)
        if y is not None:
            updates["year_built"] = str(y)
            updates["year_built_source"] = "name_parse"

    if not updates:
        return False

    update_characteristics(entity, updates, "name_parse")
    record_enrichment(
        entity,
        db,
        source_id="name_parse",
        fields_updated=list(updates.keys()),
        detail=(
            "Parsed from name: "
            + ", ".join(f"{k}={v}" for k, v in updates.items() if not k.endswith("_source"))
        ),
    )
    return True
