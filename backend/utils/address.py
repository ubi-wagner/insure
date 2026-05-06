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
    # Avenue
    "avenue": "ave", "ave": "ave", "av": "ave", "aven": "ave",
    # Boulevard
    "boulevard": "blvd", "blvd": "blvd", "blv": "blvd", "boul": "blvd",
    "boulvd": "blvd",
    # Street
    "street": "st", "st": "st", "str": "st", "stre": "st",
    # Road
    "road": "rd", "rd": "rd",
    # Drive
    "drive": "dr", "dr": "dr", "drv": "dr",
    # Lane
    "lane": "ln", "ln": "ln",
    # Place
    "place": "pl", "pl": "pl",
    # Court
    "court": "ct", "ct": "ct",
    # Terrace
    "terrace": "ter", "ter": "ter", "terr": "ter",
    # Parkway
    "parkway": "pkwy", "pkwy": "pkwy", "pky": "pkwy",
    # Highway
    "highway": "hwy", "hwy": "hwy", "hway": "hwy",
    # Circle
    "circle": "cir", "cir": "cir", "circ": "cir",
    # Way
    "way": "way", "wy": "way",
    # Mile
    "mile": "mile",
    # Trail
    "trail": "trl", "trl": "trl",
    # Plaza
    "plaza": "plz", "plz": "plz",
    # Crossing
    "crossing": "xing", "xing": "xing",
    # Other commonly seen suffixes that we keep as-is
    "loop": "loop", "run": "run", "bend": "bend", "park": "park",
    "row": "row", "ridge": "ridge", "rdg": "ridge",
    "alley": "aly", "aly": "aly",
    "extension": "ext", "ext": "ext", "extn": "ext",
    # Directionals — full names normalise to single-letter abbreviations
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
    "unit",  "units",
    "apt",   "apartment", "apartments", "apts",
    "ste",   "suite",     "suites",
    "bldg",  "building",  "bld",
    "lot",
    "fl",    "floor",     "flr",
    "rm",    "room",
    "ph",    "penthouse",
    "number",  # "650 Main St Number 5" → strip
    # NB: "no" is intentionally not here — collides with "N"/"NORTH"
    # in inputs like "650 No Main St".
    "trlr",  "trailer",
    "spc",   "space",
}

_NUMERIC_RE = re.compile(r"^\d+[A-Z]?$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[#.,\-/]")
_ORDINAL_TOKEN_RE = re.compile(r"^(\d+)(st|nd|rd|th)$", re.IGNORECASE)


def _strip_ordinal_suffix(token: str) -> str:
    """Strip the ordinal suffix from a numeric street token.

    "14th" → "14", "1st" → "1", "23rd" → "23", "104th" → "104".
    Non-ordinal tokens are returned unchanged.
    """
    m = _ORDINAL_TOKEN_RE.match(token)
    return m.group(1) if m else token


def _add_ordinal_suffix(n: int) -> str:
    """Add the English ordinal suffix to an integer: 1→1st, 2→2nd,
    3→3rd, 4→4th, 11→11th, 12→12th, 13→13th, 21→21st, etc."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th").join([str(n), ""])


def canon_variants(canon: str) -> set[str]:
    """Generate equivalent canon strings for matcher queries.

    Returns the original canon plus an ordinal-inserted version. The
    canonicaliser strips ordinal suffixes by default ("14th ave" stores
    as "14 ave"), but existing seeded data may still contain either
    form depending on what the NAL file said. The matcher queries
    against this set so it works on both old and new data without a
    full reseed.
    """
    if not canon:
        return set()

    parts = canon.split()
    if len(parts) < 2:
        return {canon}

    out = {canon}

    # Build the ordinal-inserted variant for every all-digit name token
    # AFTER the leading house number.
    rebuilt: list[str] = [parts[0]]
    changed = False
    for p in parts[1:]:
        if p.isdigit():
            rebuilt.append(_add_ordinal_suffix(int(p)))
            changed = True
        else:
            rebuilt.append(p)
    if changed:
        out.add(" ".join(rebuilt))

    return out


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

    # Strip ordinal suffixes from numeric name tokens — "14th" / "14TH"
    # / "14 TH" / "14 AVE" all need to canonicalise the same way because
    # NAL files vary by county on whether they spell out the ordinal.
    # Only applied to street-name tokens, NOT to the leading house number.
    canon_street = [_strip_ordinal_suffix(t) for t in street_tokens]

    canon_parts: list[str] = []
    if number:
        canon_parts.append(number)
    canon_parts.extend(canon_street)
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
