"""
Validation routes — compare a user-supplied list of properties against
the entities we have in our system. Used by the /validation page in the UI
to bulk-verify cards (TARGET / LEAD / OPPORTUNITY) against external truth.

POST /api/validation/compare
    Body: { items: [ { name, address, city, state, zip, year_built,
                       stories, units, tiv, iso_class, raw } ... ] }
    Returns: { results: [ { input, match, fields, status, score } ... ] }

POST /api/validation/parse
    Body: { text: "<free-form list, one property per line>" }
    Returns: { items: [ { ...parsed property... } ] }
"""

from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from database.models import Entity

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


class ValidationInput(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    year_built: Optional[int] = None
    stories: Optional[int] = None
    units: Optional[int] = None
    tiv: Optional[float] = None
    iso_class: Optional[int] = None
    raw: Optional[str] = None


class CompareRequest(BaseModel):
    items: list[ValidationInput]


class ParseRequest(BaseModel):
    text: str


# ─────────────────────────────────────────────────────────────────────────────
# Free-form text parser
# ─────────────────────────────────────────────────────────────────────────────

# Recognises blocks like:
#   Echo Brickell 1451 Brickell Ave, Miami FL 33131, ISO 6, 2017 built,
#   TIV $101,700,000, 56 stories, 171 units
#
# Strategy: split on newlines, then for each line pull a ZIP-anchored address
# slice and treat everything before it as the property name (and everything
# after as a comma-separated tail of features).

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_TIV_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(?:m|million)?", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_STORIES_RE = re.compile(r"(\d+)\s*stor(?:y|ies|ey|eys)", re.IGNORECASE)
_UNITS_RE = re.compile(r"(\d+)\s*units?", re.IGNORECASE)
_ISO_RE = re.compile(r"\bISO\s*(\d)\b", re.IGNORECASE)
# Florida cities are followed by ", FL <ZIP>" or " FL <ZIP>"
_CITY_STATE_ZIP_RE = re.compile(
    r"([A-Za-z][A-Za-z\.\s]{1,40}?),?\s+(FL|Fla\.?|Florida)\s+(\d{5})",
    re.IGNORECASE,
)
# Street suffixes we'll use as anchors when no ZIP exists.
_STREET_SUFFIX_RE = re.compile(
    r"\b(\d{1,6}[A-Z]?)\s+([NSEW]\.?\s+)?([\w\.\s]+?)\s+"
    r"(Ave|Avenue|Blvd|Boulevard|St|Street|Rd|Road|Dr|Drive|Way|Ln|Lane|"
    r"Pl|Place|Ct|Court|Ter|Terrace|Pkwy|Parkway|Hwy|Highway|Mile|Cir|Circle)\b",
    re.IGNORECASE,
)


def _norm_money(raw: str) -> Optional[float]:
    s = raw.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_freeform(text: str) -> list[ValidationInput]:
    items: list[ValidationInput] = []
    # split on blank lines OR newlines that look like a new property start
    blocks = [b.strip() for b in re.split(r"\n+", text) if b.strip()]

    for block in blocks:
        if not block:
            continue

        # Pull city/state/zip first
        city_match = _CITY_STATE_ZIP_RE.search(block)
        city = city_match.group(1).strip().rstrip(",") if city_match else None
        state = "FL" if city_match else None
        zip_code = city_match.group(3) if city_match else None

        # Address: from first street-suffix match through end of street
        street_match = _STREET_SUFFIX_RE.search(block)
        address: Optional[str] = None
        name: Optional[str] = None
        if street_match:
            street_start = street_match.start()
            street_end = street_match.end()
            address = block[street_start:street_end].strip().rstrip(",")
            name = block[:street_start].strip().rstrip(",").strip()
            if not name:
                name = None
        else:
            # No clear street — use everything before first comma as name
            comma_at = block.find(",")
            if comma_at > 0:
                name = block[:comma_at].strip()

        # TIV: prefer "$10M" / "$10 million" / "$10,000,000"
        tiv: Optional[float] = None
        tiv_match = _TIV_RE.search(block)
        if tiv_match:
            val = _norm_money(tiv_match.group(1))
            if val is not None:
                # If the original had "M" or "million", scale up
                tail = block[tiv_match.end(): tiv_match.end() + 12].lower()
                if val < 10000 and ("m" in tail[:2] or "million" in tail):
                    val *= 1_000_000
                tiv = val

        # Year built — prefer years preceded by "built" or near "built"
        year_built: Optional[int] = None
        year_match = _YEAR_RE.search(block)
        if year_match:
            year_built = int(year_match.group(0))

        # Stories / units / ISO
        stories_match = _STORIES_RE.search(block)
        stories = int(stories_match.group(1)) if stories_match else None

        units_match = _UNITS_RE.search(block)
        units = int(units_match.group(1)) if units_match else None

        iso_match = _ISO_RE.search(block)
        iso_class = int(iso_match.group(1)) if iso_match else None

        items.append(
            ValidationInput(
                name=name,
                address=address,
                city=city,
                state=state,
                zip=zip_code,
                year_built=year_built,
                stories=stories,
                units=units,
                tiv=tiv,
                iso_class=iso_class,
                raw=block,
            )
        )

    return items


# ─────────────────────────────────────────────────────────────────────────────
# Entity matcher
# ─────────────────────────────────────────────────────────────────────────────


def _street_number(addr: Optional[str]) -> Optional[str]:
    if not addr:
        return None
    m = re.match(r"\s*(\d{1,6}[A-Z]?)\b", addr)
    return m.group(1) if m else None


# Street-suffix and directional canonicalisation. We keep these tokens
# (they're the most discriminating part of an address — "Brickell Ave"
# and "Brickell Bay Dr" share the same number range) but normalise spelling
# so "Avenue" and "Ave" compare equal.
_SUFFIX_NORMALISE = {
    "avenue": "ave", "ave": "ave",
    "boulevard": "blvd", "blvd": "blvd",
    "street": "st", "st": "st",
    "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr",
    "lane": "ln", "ln": "ln",
    "place": "pl", "pl": "pl",
    "court": "ct", "ct": "ct",
    "terrace": "ter", "ter": "ter",
    "parkway": "pkwy", "pkwy": "pkwy",
    "highway": "hwy", "hwy": "hwy",
    "circle": "cir", "cir": "cir",
    "way": "way",
    "mile": "mile",
    "north": "n", "n": "n",
    "south": "s", "s": "s",
    "east": "e", "e": "e",
    "west": "w", "w": "w",
    "northeast": "ne", "ne": "ne",
    "northwest": "nw", "nw": "nw",
    "southeast": "se", "se": "se",
    "southwest": "sw", "sw": "sw",
}

# Words we drop entirely — pure noise that makes false matches.
_NOISE_TOKENS = {"the", "of", "at"}


def _street_tokens(addr: Optional[str]) -> list[str]:
    """Lowercase street tokens minus the leading number, with directional
    and street-suffix abbreviations normalised so "Avenue" matches "Ave".

    Restricts to the first comma-delimited segment of the address — the
    street line — so that the city/state/ZIP tail doesn't leak into the
    "name tokens" set and create false matches (e.g. "1451 Brickell Ave,
    Miami FL 33131" sharing "miami" with "1451 S Miami Ave, Miami FL").
    """
    if not addr:
        return []
    # Use only the first segment (street line). Both seeded addresses and
    # validation-page input follow the "<street>, <city>, FL <zip>" shape.
    street_part = addr.split(",", 1)[0]
    cleaned = re.sub(r"^\s*\d{1,6}[A-Z]?\s*", "", street_part).lower()
    cleaned = re.sub(r"[.,#]", " ", cleaned)
    out: list[str] = []
    for t in cleaned.split():
        if not t or t in _NOISE_TOKENS:
            continue
        out.append(_SUFFIX_NORMALISE.get(t, t))
    return out


def _classify_tokens(tokens: list[str]) -> tuple[set[str], set[str], set[str]]:
    """Return (name_tokens, directional_tokens, suffix_tokens) so the
    matcher can require *each* class to overlap when both sides have one.
    """
    suffixes = {"ave", "blvd", "st", "rd", "dr", "ln", "pl", "ct", "ter",
                "pkwy", "hwy", "cir", "way", "mile"}
    directionals = {"n", "s", "e", "w", "ne", "nw", "se", "sw"}
    name = {t for t in tokens if t not in suffixes and t not in directionals}
    return name, set(tokens) & directionals, set(tokens) & suffixes


# Match threshold — below this we don't consider a candidate a real match.
# Calibrated so that street-number alone scores below threshold (3 pts max
# for the number itself) but a number + 1 name token + matching suffix or
# city clears it (3 + 5 + 4 = 12).
MIN_MATCH_SCORE = 10


def find_match(
    db: Session,
    item: ValidationInput,
) -> tuple[Optional[Entity], int]:
    """Find the best entity matching the input. Returns ``(entity, score)``
    where ``entity`` is ``None`` when no candidate clears MIN_MATCH_SCORE.

    Algorithm:
      1. Filter Entity rows by street-number prefix (cheap discriminator).
      2. Score each candidate by:
         - overlap on street-name tokens (5 pts each, up to 4 tokens)
         - matching street suffix (4 pts)
         - matching directional (4 pts)
         - matching ZIP (4 pts) or city contained in either direction (3)
         - overlap on association-name tokens (2 pts each, up to 4)
      3. Require BOTH (a) at least one street-name token overlap AND
         (b) suffix-or-zip-or-name agreement, to rule out wrong-street
         collisions like "1451 Brickell Ave" vs "1451 S Miami Ave".
      4. Skip ARCHIVED entities — those are dismissals, not active leads.
    """
    num = _street_number(item.address)
    candidates: list[Entity] = []

    if num:
        candidates = (
            db.query(Entity)
            .filter(Entity.address.ilike(f"{num} %"))
            .filter(Entity.pipeline_stage != "ARCHIVED")
            .limit(200)
            .all()
        )

    if not candidates and item.address and item.name:
        candidates = (
            db.query(Entity)
            .filter(Entity.name.ilike(f"%{item.name}%"))
            .filter(Entity.pipeline_stage != "ARCHIVED")
            .limit(50)
            .all()
        )

    if not candidates:
        return None, 0

    target_tokens = _street_tokens(item.address)
    target_name_set, target_dirs, target_sufs = _classify_tokens(target_tokens)
    target_full_name = set(re.findall(r"\w+", (item.name or "").lower()))
    target_city = (item.city or "").lower().strip()
    target_zip = (item.zip or "").strip()[:5]

    best_entity: Optional[Entity] = None
    best_score = 0

    for c in candidates:
        cand_tokens = _street_tokens(c.address)
        cand_name_set, cand_dirs, cand_sufs = _classify_tokens(cand_tokens)
        cand_full_name = set(re.findall(r"\w+", (c.name or "").lower()))

        chars: dict[str, Any] = c.characteristics or {}
        cand_city = (
            chars.get("phy_city")
            or chars.get("dor_city")
            or chars.get("city")
            or ""
        ).lower().strip()
        cand_zip = str(
            chars.get("phy_zip")
            or chars.get("dor_zip_code")
            or chars.get("zip")
            or ""
        ).strip()[:5]

        # Street-name overlap — the strongest signal. No overlap = wrong street.
        name_overlap = target_name_set & cand_name_set
        if not name_overlap:
            continue

        score = 3  # baseline for street-number match
        score += min(len(name_overlap), 4) * 5

        # Directional and suffix only contribute when BOTH sides have one
        # (otherwise we can't tell agreement from "didn't know").
        if target_dirs and cand_dirs:
            if target_dirs & cand_dirs:
                score += 4
            else:
                # Real disagreement (e.g. our row is "30TH AVE S" but the
                # input said "30th Avenue N") — penalise hard.
                score -= 6

        if target_sufs and cand_sufs:
            if target_sufs & cand_sufs:
                score += 4
            else:
                score -= 6

        if target_zip and cand_zip and target_zip == cand_zip:
            score += 4
        if target_city and cand_city and (
            target_city in cand_city or cand_city in target_city
        ):
            score += 3

        # Association-name overlap — useful but secondary.
        full_overlap = target_full_name & cand_full_name
        if full_overlap:
            score += min(len(full_overlap), 4) * 2

        if score >= MIN_MATCH_SCORE and score > best_score:
            best_entity = c
            best_score = score

    return best_entity, best_score


# ─────────────────────────────────────────────────────────────────────────────
# Field comparison
# ─────────────────────────────────────────────────────────────────────────────


# DOR construction class → ISO class (ISO 1-6 fire-resistive scale).
# DOR uses descriptive strings; we collapse them onto the closest ISO
# bucket Jason quotes against.
def _dor_class_to_iso(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    low = s.lower()
    if "fire resistive" in low or "fire-resistive" in low:
        return 6
    if "non-combustible" in low or "non combustible" in low:
        return 5
    if "modified fire" in low:
        return 5
    if "masonry" in low and "veneer" in low:
        return 3
    if "masonry" in low:
        return 4
    if "frame" in low or "wood" in low:
        return 2
    return None


def _first_nonnull(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", "null"):
            return v
    return None


def _compare(input_val, db_val, *, tolerance: float = 0.0):
    """Per-field status: match / conflict / no_input / no_data."""
    if input_val is None or input_val == "":
        return "no_input"
    if db_val is None or db_val == "":
        return "no_data"
    try:
        a = float(input_val)
        b = float(db_val)
        if tolerance > 0:
            if a == 0 and b == 0:
                return "match"
            denom = max(abs(a), abs(b))
            return "match" if denom > 0 and abs(a - b) / denom <= tolerance else "conflict"
        return "match" if a == b else "conflict"
    except (TypeError, ValueError):
        return "match" if str(input_val).strip().lower() == str(db_val).strip().lower() else "conflict"


def compare_fields(item: ValidationInput, ent: Optional[Entity]) -> dict[str, Any]:
    if ent is None:
        return {
            "fields": {},
            "status": "missing",
            "found": False,
        }

    chars = ent.characteristics or {}

    db_year = _first_nonnull(
        chars, "dor_year_built", "dor_effective_year_built", "pa_year_built"
    )
    # Stories: prefer the unified `stories` key (set by dbpr_building when
    # the scrape works, name_parse otherwise), fall back through the legacy
    # DBPR/DOR keys for entities seeded before name_parse landed.
    db_stories = _first_nonnull(
        chars, "stories", "dbpr_max_stories", "dor_max_stories"
    )
    db_units = _first_nonnull(chars, "dor_num_units", "units_estimate", "units")
    db_tiv = _first_nonnull(chars, "tiv_estimate", "dor_market_value")
    db_iso = _dor_class_to_iso(chars.get("dor_construction_class"))

    fields = {
        "year_built": {
            "input": item.year_built,
            "db": _to_int(db_year),
            "status": _compare(item.year_built, db_year),
        },
        "stories": {
            "input": item.stories,
            "db": _to_int(db_stories),
            "status": _compare(item.stories, db_stories),
        },
        "units": {
            "input": item.units,
            "db": _to_int(db_units),
            # Units rarely match exactly because DOR counts can differ from
            # physical unit counts by ±1 (e.g. manager unit). Allow 5%.
            "status": _compare(item.units, db_units, tolerance=0.05),
        },
        "tiv": {
            "input": item.tiv,
            "db": _to_int(db_tiv),
            # TIV is a 20% replacement-cost estimate; treat ±25% as match.
            "status": _compare(item.tiv, db_tiv, tolerance=0.25),
        },
        "iso_class": {
            "input": item.iso_class,
            "db": db_iso,
            "db_raw": chars.get("dor_construction_class"),
            "status": _compare(item.iso_class, db_iso),
        },
    }

    statuses = [v["status"] for v in fields.values()]
    if any(s == "conflict" for s in statuses):
        overall = "conflict"
    elif any(s == "match" for s in statuses):
        overall = "match"
    else:
        # Found the entity but had no comparable field data on either side
        overall = "no_data"

    return {"fields": fields, "status": overall, "found": True}


def _to_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/validation/parse")
def parse_validation_text(req: ParseRequest):
    items = parse_freeform(req.text)
    return {"items": [i.model_dump() for i in items]}


@router.post("/api/validation/compare")
def compare_validation(req: CompareRequest, db: Session = Depends(get_db)):
    results: list[dict[str, Any]] = []
    counts = {"match": 0, "conflict": 0, "missing": 0, "no_data": 0}

    for item in req.items:
        ent, match_score = find_match(db, item)
        comparison = compare_fields(item, ent)
        status = comparison["status"]
        counts[status] = counts.get(status, 0) + 1

        results.append(
            {
                "input": item.model_dump(),
                "match": (
                    {
                        "id": ent.id,
                        "name": ent.name,
                        "address": ent.address,
                        "county": ent.county,
                        "pipeline_stage": ent.pipeline_stage,
                        "latitude": ent.latitude,
                        "longitude": ent.longitude,
                        "heat_score": ent.heat_score,
                        "cream_score": (ent.characteristics or {}).get("cream_score"),
                        "cream_tier": (ent.characteristics or {}).get("cream_tier"),
                    }
                    if ent
                    else None
                ),
                "fields": comparison["fields"],
                "status": status,
                "match_score": match_score,
            }
        )

    return {"results": results, "counts": counts, "total": len(results)}
