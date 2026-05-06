"""
Canonical street-address key — the single source of truth for matching
parcels to a building across the seeder, qualifier, aggregator, and
validation matcher.

Design goal: the user explicitly said "650 main", "650 S Main",
"650 South Main" at the same ZIP all belong to the same condo
association 99.9% of the time. Lean into that. Two records share a
key when they share:
    house number + street-name tokens + street suffix

Stripped:
    leading/trailing directional (N / S / E / W / NE / NW / SE / SW)
    unit / apt / suite / # / floor markers and everything after them
    bare numeric trailing tokens after a suffix has been seen
        ("1451 BRICKELL AVE 1702" → "1451 brickell ave")
    case, punctuation, "Avenue" vs "Ave" spelling

Preserved:
    house number (the strongest discriminator)
    street suffix when present ("Main St" ≠ "Main Ave")
    numeric route names ("Highway 1" stays as "hwy 1")

Examples (verified by tests):
    "650 S MAIN ST # 504, ST PETERSBURG, FL 33701"  →  "650 main st"
    "650 South Main Street, Saint Petersburg FL"    →  "650 main st"
    "650 Main St"                                    →  "650 main st"
    "5955 30TH AVE S APT 12"                         →  "5955 30th ave"
    "5955 30TH AVE N"                                →  "5955 30th ave"
    "1451 BRICKELL AVE 1702"                         →  "1451 brickell ave"
    "1120 NORTH SHORE DR"                            →  "1120 shore dr"
    "100 N HIGHWAY 1"                                →  "100 hwy 1"
    "100 1st Ave"                                    →  "100 1st ave"
    "100 1st St"                                     →  "100 1st st"   (different)
"""

from __future__ import annotations

import re
from typing import Optional


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

_SUFFIXES = {
    "ave", "blvd", "st", "rd", "dr", "ln", "pl", "ct", "ter",
    "pkwy", "hwy", "cir", "way", "mile",
}
_DIRECTIONALS = {"n", "s", "e", "w", "ne", "nw", "se", "sw"}
_UNIT_MARKERS = {
    "unit", "apt", "apartment", "ste", "suite", "bldg", "building",
    "lot", "fl", "floor", "rm", "room", "ph",
}

_NUMERIC_RE = re.compile(r"^\d+[A-Z]?$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[#.,\-/]")


def canonicalize_address(addr: Optional[str]) -> dict:
    """Parse a raw address line into structured + canonical pieces.

    Returns a dict::

        {
            'number':        '650',                # first numeric token
            'canon':         '650 main st',        # AGG/MATCH key — strips dirs
            'full':          '650 s main st',      # display form, keeps dirs
            'leading_dir':   's',                  # first dir if any
            'trailing_dir':  None,                 # post-suffix dir if any
            'street_only':   'main st',            # canon minus number
        }

    All values lowercased. Empty strings / None inputs return blanks.
    """
    blank = {
        "number": None, "canon": "", "full": "",
        "leading_dir": None, "trailing_dir": None, "street_only": "",
    }
    if not addr:
        return blank

    # Drop everything past the first comma (city / state / zip tail).
    street = addr.split(",", 1)[0].lower()
    # Replace common in-token punctuation with spaces so "AVE-S" splits.
    street = _PUNCT_RE.sub(" ", street)
    raw = [t for t in street.split() if t]
    if not raw:
        return blank

    tokens = [_SUFFIX_NORMALISE.get(t, t) for t in raw]

    # 1. House number
    number: Optional[str] = None
    i = 0
    if _NUMERIC_RE.match(tokens[0]):
        number = tokens[0]
        i = 1

    # 2. Optional leading directional (e.g., "S MAIN ST")
    leading_dir: Optional[str] = None
    if i < len(tokens) and tokens[i] in _DIRECTIONALS:
        leading_dir = tokens[i]
        i += 1

    rest = tokens[i:]

    # 3. Truncate at first explicit unit marker.
    for j, t in enumerate(rest):
        if t in _UNIT_MARKERS:
            rest = rest[:j]
            break

    # 4. Find the FIRST suffix token that has at least one name token
    #    before it. (Skipping j=0 prevents "Highway 1" from collapsing
    #    to just "hwy" — the route number IS the name.)
    suffix_pos: Optional[int] = None
    for j, t in enumerate(rest):
        if j == 0:
            continue
        if t in _SUFFIXES:
            suffix_pos = j
            break

    trailing_dir: Optional[str] = None
    if suffix_pos is not None:
        street_tokens = rest[: suffix_pos + 1]
        # Optional one trailing directional (5955 30TH AVE S)
        if suffix_pos + 1 < len(rest) and rest[suffix_pos + 1] in _DIRECTIONALS:
            trailing_dir = rest[suffix_pos + 1]
        # Anything past suffix + optional dir is unit junk — already cut
        # via the rest slicing.
    else:
        # No suffix found — keep every token as part of the street name.
        # This is the right behaviour for numeric route names like
        # "100 Highway 1" (suffix word at j=0 doesn't qualify, so we
        # land here and need to preserve the "1").
        street_tokens = list(rest)

    canon_parts: list[str] = []
    if number:
        canon_parts.append(number)
    canon_parts.extend(street_tokens)
    canon = " ".join(canon_parts)

    full_parts: list[str] = []
    if number:
        full_parts.append(number)
    if leading_dir:
        full_parts.append(leading_dir)
    full_parts.extend(street_tokens)
    if trailing_dir:
        full_parts.append(trailing_dir)
    full = " ".join(full_parts)

    return {
        "number": number,
        "canon": canon,
        "full": full,
        "leading_dir": leading_dir,
        "trailing_dir": trailing_dir,
        "street_only": " ".join(street_tokens),
    }


def canon_key(addr: Optional[str]) -> str:
    """Convenience: return just the canonical match key string."""
    return canonicalize_address(addr)["canon"]
