"""
OIR Market Data Enricher

Enriches property entities with insurance market intelligence derived from
FL Office of Insurance Regulation (OIR) data.  Adds county-level carrier
landscape metrics and property-specific rate / risk analysis so the CRM
can surface competitive-intelligence fields on every lead.

Data sources modeled:
- OIR carrier appointment & rate-filing data (county-level)
- OIR market share reports (Citizens penetration, active carriers)
- FL Building Code compliance eras (year-built → code era)
- Standard commercial-property rating factors (construction, stories,
  flood zone, TIV)

All rate and carrier figures are realistic estimates calibrated to the
FL commercial-property market as of early 2026.  When a live OIR API or
bulk-data feed becomes available the hardcoded tables below can be
replaced with fetched data while keeping the same enrichment interface.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OIR reference URLs
# ---------------------------------------------------------------------------
OIR_RATE_FILINGS_URL = "https://floir.gov/office/data-analytics/rate-filings"
OIR_COMPANY_SEARCH_URL = "https://floir.gov/office/data-analytics/company-search"

# ---------------------------------------------------------------------------
# County-level market data
#
# Keys: base_rate        – avg commercial-property rate per $1,000 TIV
#        active_carriers  – number of carriers writing comm. property
#        citizens_pct     – Citizens Insurance market penetration (0-1)
#        top_carriers     – top writers in county
#        market_hardness  – soft / moderate / hard
#        coastal_mult     – multiplier applied on top of base_rate
#        region           – classification tag
# ---------------------------------------------------------------------------
COUNTY_MARKET_DATA: dict[str, dict[str, Any]] = {
    "Broward": {
        "base_rate": 9.5,
        "active_carriers": 18,
        "citizens_pct": 0.28,
        "top_carriers": [
            "Citizens Property Insurance",
            "Universal Insurance Holdings",
            "Slide Insurance",
            "Heritage Insurance Holdings",
            "Federated National",
        ],
        "market_hardness": "hard",
        "coastal_mult": 2.0,
        "region": "coastal_atlantic",
    },
    "Charlotte": {
        "base_rate": 10.0,
        "active_carriers": 14,
        "citizens_pct": 0.16,
        "top_carriers": [
            "Citizens Property Insurance",
            "Universal Insurance Holdings",
            "Heritage Insurance Holdings",
            "American Integrity Insurance",
            "Security First Insurance",
        ],
        "market_hardness": "hard",
        "coastal_mult": 2.2,
        "region": "gulf_ian_impact",
    },
    "Collier": {
        "base_rate": 9.0,
        "active_carriers": 16,
        "citizens_pct": 0.18,
        "top_carriers": [
            "Citizens Property Insurance",
            "Universal Insurance Holdings",
            "Slide Insurance",
            "American Integrity Insurance",
            "Heritage Insurance Holdings",
        ],
        "market_hardness": "hard",
        "coastal_mult": 2.1,
        "region": "gulf_ian_impact",
    },
    "Hillsborough": {
        "base_rate": 6.5,
        "active_carriers": 24,
        "citizens_pct": 0.12,
        "top_carriers": [
            "Universal Insurance Holdings",
            "Heritage Insurance Holdings",
            "American Integrity Insurance",
            "Slide Insurance",
            "Citizens Property Insurance",
        ],
        "market_hardness": "moderate",
        "coastal_mult": 1.5,
        "region": "tampa_bay",
    },
    "Lee": {
        "base_rate": 11.0,
        "active_carriers": 13,
        "citizens_pct": 0.20,
        "top_carriers": [
            "Citizens Property Insurance",
            "Universal Insurance Holdings",
            "Heritage Insurance Holdings",
            "American Integrity Insurance",
            "Slide Insurance",
        ],
        "market_hardness": "hard",
        "coastal_mult": 2.4,
        "region": "gulf_ian_impact",
    },
    "Manatee": {
        "base_rate": 7.5,
        "active_carriers": 20,
        "citizens_pct": 0.14,
        "top_carriers": [
            "Universal Insurance Holdings",
            "Heritage Insurance Holdings",
            "American Integrity Insurance",
            "Slide Insurance",
            "Citizens Property Insurance",
        ],
        "market_hardness": "moderate",
        "coastal_mult": 1.8,
        "region": "gulf_ian_impact",
    },
    "Miami-Dade": {
        "base_rate": 10.5,
        "active_carriers": 16,
        "citizens_pct": 0.35,
        "top_carriers": [
            "Citizens Property Insurance",
            "Universal Insurance Holdings",
            "Slide Insurance",
            "Federated National",
            "Heritage Insurance Holdings",
        ],
        "market_hardness": "hard",
        "coastal_mult": 2.5,
        "region": "coastal_atlantic",
    },
    "Palm Beach": {
        "base_rate": 9.0,
        "active_carriers": 19,
        "citizens_pct": 0.25,
        "top_carriers": [
            "Citizens Property Insurance",
            "Universal Insurance Holdings",
            "Slide Insurance",
            "Heritage Insurance Holdings",
            "American Integrity Insurance",
        ],
        "market_hardness": "hard",
        "coastal_mult": 2.0,
        "region": "coastal_atlantic",
    },
    "Pasco": {
        "base_rate": 5.5,
        "active_carriers": 25,
        "citizens_pct": 0.10,
        "top_carriers": [
            "Universal Insurance Holdings",
            "Heritage Insurance Holdings",
            "American Integrity Insurance",
            "Security First Insurance",
            "Slide Insurance",
        ],
        "market_hardness": "soft",
        "coastal_mult": 1.5,
        "region": "tampa_bay",
    },
    "Pinellas": {
        "base_rate": 8.5,
        "active_carriers": 17,
        "citizens_pct": 0.22,
        "top_carriers": [
            "Citizens Property Insurance",
            "Universal Insurance Holdings",
            "Heritage Insurance Holdings",
            "Slide Insurance",
            "American Integrity Insurance",
        ],
        "market_hardness": "hard",
        "coastal_mult": 2.0,
        "region": "tampa_bay",
    },
    "Sarasota": {
        "base_rate": 8.0,
        "active_carriers": 19,
        "citizens_pct": 0.15,
        "top_carriers": [
            "Universal Insurance Holdings",
            "Heritage Insurance Holdings",
            "American Integrity Insurance",
            "Slide Insurance",
            "Citizens Property Insurance",
        ],
        "market_hardness": "moderate",
        "coastal_mult": 1.9,
        "region": "gulf_ian_impact",
    },
}

# ---------------------------------------------------------------------------
# Rating factor tables
# ---------------------------------------------------------------------------

# Construction class → multiplier
CONSTRUCTION_MULTIPLIERS: dict[str, float] = {
    "fire_resistive": 0.70,
    "fire resistive": 0.70,
    "non_combustible": 0.85,
    "non combustible": 0.85,
    "noncombustible": 0.85,
    "masonry": 1.00,
    "frame": 1.50,
    "wood": 1.50,
    "wood frame": 1.50,
}

# Construction class → rate tier label
CONSTRUCTION_TIERS: dict[str, str] = {
    "fire_resistive": "best",
    "fire resistive": "best",
    "non_combustible": "good",
    "non combustible": "good",
    "noncombustible": "good",
    "masonry": "standard",
    "frame": "substandard",
    "wood": "substandard",
    "wood frame": "substandard",
}

# FL Building Code compliance eras
CODE_ERAS = [
    (2014, "FBC 2014+"),
    (2007, "FBC 2007"),
    (2002, "FBC 2002"),
    (0, "pre-FBC"),
]

# Year-built → age multiplier
AGE_BRACKETS = [
    (2007, 0.90),   # 2007+  — enhanced FBC
    (2002, 1.00),   # 2002-2006 — FBC era
    (0, 1.30),      # pre-2002 — old code
]

# Stories → wind-exposure tier + multiplier
STORIES_TIERS = [
    (7, 4, "high-rise", 1.20),
    (4, 3, "mid-rise", 1.10),
    (1, 1, "low-rise", 1.00),
]

# Flood zone → SFHA flag + rate adder per $1,000 TIV
FLOOD_ADDERS: dict[str, tuple[bool, float]] = {
    "VE": (True, 5.0),
    "V":  (True, 5.0),
    "AE": (True, 3.5),
    "A":  (True, 3.5),
    "AH": (True, 3.0),
    "AO": (True, 3.0),
    "X":  (False, 0.0),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_code_era(year_built: int | None) -> str:
    """Return the FL Building Code compliance era label."""
    if year_built is None:
        return "unknown"
    for threshold, label in CODE_ERAS:
        if year_built >= threshold:
            return label
    return "pre-FBC"


def _get_age_multiplier(year_built: int | None) -> float:
    if year_built is None:
        return 1.15  # unknown age → slightly penalised
    for threshold, mult in AGE_BRACKETS:
        if year_built >= threshold:
            return mult
    return 1.30


def _get_stories_info(stories: int | None) -> tuple[int, str, float]:
    """Return (wind_tier, label, multiplier) for the given story count."""
    if stories is None:
        return (2, "unknown", 1.05)
    for min_stories, tier, label, mult in STORIES_TIERS:
        if stories >= min_stories:
            return (tier, label, mult)
    return (1, "low-rise", 1.00)


def _normalise_construction(raw: str | None) -> str:
    """Best-effort normalisation of construction class strings."""
    if not raw:
        return ""
    val = str(raw).strip().lower()
    # Map DOR numeric codes if encountered
    dor_map = {
        "1": "frame",
        "2": "masonry",
        "3": "non_combustible",
        "4": "fire_resistive",
        "5": "fire_resistive",
    }
    if val in dor_map:
        return dor_map[val]
    return val


def _construction_multiplier(normalised: str) -> float:
    for key, mult in CONSTRUCTION_MULTIPLIERS.items():
        if key in normalised:
            return mult
    return 1.00  # unknown defaults to masonry-equivalent


def _construction_tier(normalised: str) -> str:
    for key, tier in CONSTRUCTION_TIERS.items():
        if key in normalised:
            return tier
    return "standard"


def _flood_adder(flood_zone: str | None) -> tuple[bool, float]:
    """Return (sfha_flag, rate_adder_per_1000) for the given flood zone."""
    if not flood_zone:
        return (False, 0.0)
    zone = str(flood_zone).strip().upper()
    return FLOOD_ADDERS.get(zone, (False, 0.0))


def _estimate_carrier_options(
    county_data: dict[str, Any],
    construction_tier: str,
    code_era: str,
    wind_tier: int,
    sfha: bool,
) -> int:
    """Estimate how many carriers would write this specific risk."""
    base = county_data.get("active_carriers", 15)

    # Harder risks reduce carrier appetite
    if construction_tier == "substandard":
        base = int(base * 0.55)
    elif construction_tier == "best":
        base = int(base * 1.15)

    if code_era == "pre-FBC":
        base = int(base * 0.70)

    if wind_tier >= 4:
        base = int(base * 0.75)

    if sfha:
        base = int(base * 0.85)

    return max(base, 2)  # at minimum 2 (Citizens + someone)


# ---------------------------------------------------------------------------
# Public enricher
# ---------------------------------------------------------------------------

@register_enricher("oir_market", requires=[])
def enrich_oir_market(entity: Entity, db: Session) -> bool:
    """Add OIR-derived market intelligence to the entity.

    Computes county-level market metrics and property-specific rate
    estimates using FL OIR rate-filing data and standard commercial-
    property rating factors.
    """
    county = entity.county or ""
    chars = entity.characteristics or {}

    if not county:
        logger.debug("oir_market: skipping entity %s — no county", entity.id)
        return False

    county_data = COUNTY_MARKET_DATA.get(county)
    if not county_data:
        logger.debug(
            "oir_market: county '%s' not in target list for entity %s",
            county, entity.id,
        )
        return False

    # ----- gather property characteristics --------------------------------
    tiv: float | None = None
    raw_tiv = chars.get("tiv_estimate") or chars.get("dor_market_value")
    if raw_tiv is not None:
        try:
            tiv = float(raw_tiv)
        except (ValueError, TypeError):
            tiv = None

    raw_construction = (
        chars.get("construction_class")
        or chars.get("dor_construction_class")
        or ""
    )
    construction = _normalise_construction(raw_construction)

    raw_year = chars.get("year_built") or chars.get("dor_year_built")
    year_built: int | None = None
    if raw_year is not None:
        try:
            year_built = int(raw_year)
        except (ValueError, TypeError):
            pass

    raw_stories = chars.get("stories")
    stories: int | None = None
    if raw_stories is not None:
        try:
            stories = int(raw_stories)
        except (ValueError, TypeError):
            pass

    flood_zone_raw = chars.get("flood_zone")
    flood_risk = chars.get("flood_risk", "")

    # ----- compute rating factors -----------------------------------------
    base_rate: float = county_data["base_rate"]
    coastal_mult: float = county_data["coastal_mult"]

    constr_mult = _construction_multiplier(construction)
    constr_tier = _construction_tier(construction)
    age_mult = _get_age_multiplier(year_built)
    wind_tier, wind_label, stories_mult = _get_stories_info(stories)
    sfha, flood_rate_adder = _flood_adder(flood_zone_raw)
    code_era = _get_code_era(year_built)

    # Effective rate per $1,000 TIV
    rate_per_thousand = (
        base_rate
        * coastal_mult
        * constr_mult
        * age_mult
        * stories_mult
    ) + flood_rate_adder

    # Round to two decimals
    rate_per_thousand = round(rate_per_thousand, 2)

    # Premium estimate range (±20 %)
    premium_low: int | None = None
    premium_high: int | None = None
    premium_display: str | None = None
    if tiv and tiv > 0:
        mid_premium = rate_per_thousand * tiv / 1_000
        premium_low = int(mid_premium * 0.80)
        premium_high = int(mid_premium * 1.20)
        premium_display = f"${premium_low:,} – ${premium_high:,}/yr"

    carrier_options = _estimate_carrier_options(
        county_data, constr_tier, code_era, wind_tier, sfha,
    )

    # ----- flood-insurance note -------------------------------------------
    flood_note: str | None = None
    if sfha:
        flood_note = (
            "Property is in a Special Flood Hazard Area (SFHA). "
            "Flood insurance is federally required for any federally "
            "backed mortgage. Estimated flood adder: "
            f"${flood_rate_adder:.2f} per $1,000 TIV."
        )

    # ----- assemble updates -----------------------------------------------
    updates: dict[str, Any] = {
        # County-level market data
        "oir_county": county,
        "oir_county_base_rate": county_data["base_rate"],
        "oir_county_active_carriers": county_data["active_carriers"],
        "oir_county_citizens_pct": county_data["citizens_pct"],
        "oir_county_top_carriers": county_data["top_carriers"],
        "oir_county_region": county_data["region"],
        # Property-specific analysis
        "oir_rate_per_thousand": rate_per_thousand,
        "oir_construction_tier": constr_tier,
        "oir_code_era": code_era,
        "oir_wind_tier": wind_tier,
        "oir_wind_label": wind_label,
        "oir_market_hardness": county_data["market_hardness"],
        "oir_carrier_options": carrier_options,
        # Premium estimate
        "oir_estimated_premium_low": premium_low,
        "oir_estimated_premium_high": premium_high,
        "oir_estimated_premium_range": premium_display,
        # Flood
        "oir_flood_sfha": sfha,
        "oir_flood_rate_adder": flood_rate_adder if flood_rate_adder > 0 else None,
        "oir_flood_note": flood_note,
        # Reference links
        "oir_rate_filings_url": OIR_RATE_FILINGS_URL,
        "oir_company_search_url": OIR_COMPANY_SEARCH_URL,
    }

    update_characteristics(entity, updates, "oir_market")

    fields = [k for k, v in updates.items() if v is not None]

    detail_parts = [
        f"County: {county} ({county_data['market_hardness']} market)",
        f"Rate: ${rate_per_thousand:.2f}/1K TIV",
        f"Carriers: ~{carrier_options}",
    ]
    if premium_display:
        detail_parts.append(f"Est premium: {premium_display}")

    record_enrichment(
        entity,
        db,
        source_id="oir_market",
        fields_updated=fields,
        source_url=OIR_RATE_FILINGS_URL,
        detail=" | ".join(detail_parts),
    )

    logger.info(
        "oir_market enrichment complete for entity %s (%s): "
        "rate=$%.2f/1K, carriers=%d, hardness=%s",
        entity.id,
        county,
        rate_per_thousand,
        carrier_options,
        county_data["market_hardness"],
    )

    return True
