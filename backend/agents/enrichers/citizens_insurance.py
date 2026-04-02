"""
Citizens Property Insurance Enricher

Citizens is Florida's state-created insurer of last resort. Any
building on Citizens is:
1. Paying higher-than-market rates
2. Being actively depopulated by the state
3. A warm/hot lead for policy swap

This enricher identifies leads that are likely on Citizens by:
- Cross-referencing against Citizens rate data
- Checking DOR use code + location + TIV against Citizens eligibility
- Flagging properties in high-Citizens-density areas

Citizens data sources:
- Rate filings: https://www.citizensfla.com
- Market share reports (PDF)
- Policy count by county (public records)

For now, we use heuristic scoring based on known Citizens patterns:
- Coastal properties in wind-borne debris regions
- High TIV with coastal exposure
- Properties in counties with high Citizens penetration
- Condos without wind coverage from private market

When Citizens bulk data becomes available (CSV/API), this enricher
will cross-reference directly.
"""

import logging

from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)

# Counties with highest Citizens penetration (as of 2025 data)
# Source: Citizens Property Insurance Corporation market share reports
HIGH_CITIZENS_COUNTIES = {
    "Miami-Dade": 0.35,    # 35% of residential policies
    "Broward": 0.28,
    "Palm Beach": 0.25,
    "Monroe": 0.45,
    "Pinellas": 0.22,
    "Lee": 0.20,
    "Collier": 0.18,
    "Sarasota": 0.15,
    "Manatee": 0.14,
    "Hillsborough": 0.12,
    "Charlotte": 0.16,
    "Pasco": 0.10,
}

# Citizens 2026 average premium by construction/location
# These are rough estimates from rate filing data
CITIZENS_RATE_ESTIMATES = {
    "coastal_masonry": 8500,      # per $100K TIV
    "coastal_frame": 12000,
    "coastal_fire_resistive": 6500,
    "inland_masonry": 4500,
    "inland_frame": 6500,
    "inland_fire_resistive": 3500,
}


def _estimate_citizens_likelihood(entity: Entity) -> dict:
    """Estimate likelihood that this property is on Citizens.

    Returns dict with: likelihood (0-100), estimated_premium, factors
    """
    chars = entity.characteristics or {}
    county = entity.county or ""
    score = 0
    factors = []

    # County penetration
    penetration = HIGH_CITIZENS_COUNTIES.get(county, 0.05)
    if penetration >= 0.25:
        score += 30
        factors.append(f"High Citizens county ({county}: {penetration:.0%})")
    elif penetration >= 0.15:
        score += 15
        factors.append(f"Moderate Citizens county ({county}: {penetration:.0%})")

    # Flood zone — coastal high hazard
    flood_risk = chars.get("flood_risk", "")
    if flood_risk in ("extreme", "high"):
        score += 25
        factors.append(f"High flood risk ({chars.get('flood_zone', 'unknown')})")
    elif flood_risk == "moderate_high":
        score += 10

    # TIV — Citizens handles many high-TIV coastal properties
    tiv = chars.get("tiv_estimate")
    if tiv and isinstance(tiv, (int, float)):
        if tiv >= 5_000_000:
            score += 20
            factors.append(f"High TIV (${tiv:,.0f})")
        elif tiv >= 1_000_000:
            score += 10

    # Construction — frame buildings have hardest time in private market
    const_class = str(chars.get("dor_construction_class") or chars.get("construction_class") or "").lower()
    if "frame" in const_class or "wood" in const_class:
        score += 15
        factors.append("Frame construction (limited private market options)")
    elif "masonry" in const_class:
        score += 5

    # Age — older buildings harder to insure privately
    year_built = chars.get("dor_year_built") or chars.get("year_built")
    if year_built:
        try:
            age = 2026 - int(year_built)
            if age >= 40:
                score += 15
                factors.append(f"Aging structure ({year_built}, {age}+ years)")
            elif age >= 25:
                score += 5
        except (ValueError, TypeError):
            pass

    # Multi-unit — Citizens has many condo associations
    units = chars.get("dor_num_units") or chars.get("units_estimate")
    if units and isinstance(units, (int, float)) and units >= 50:
        score += 10
        factors.append(f"Large association ({int(units)} units)")

    # Estimate premium if on Citizens
    is_coastal = flood_risk in ("extreme", "high", "moderate_high")
    location = "coastal" if is_coastal else "inland"
    if "frame" in const_class:
        rate_key = f"{location}_frame"
    elif "fire" in const_class or "resistive" in const_class:
        rate_key = f"{location}_fire_resistive"
    else:
        rate_key = f"{location}_masonry"

    rate_per_100k = CITIZENS_RATE_ESTIMATES.get(rate_key, 5000)
    estimated_premium = None
    if tiv and isinstance(tiv, (int, float)) and tiv > 0:
        estimated_premium = int(tiv / 100_000 * rate_per_100k)

    return {
        "likelihood": min(score, 100),
        "estimated_premium": estimated_premium,
        "factors": factors,
        "county_penetration": penetration,
    }


@register_enricher("citizens_insurance")
def enrich_citizens_insurance(entity: Entity, db: Session) -> bool:
    """Analyze whether this property is likely on Citizens insurance."""
    chars = entity.characteristics or {}

    # Need at least county + some property data
    if not entity.county:
        return False
    if not chars.get("dor_market_value") and not chars.get("tiv_estimate"):
        return False

    analysis = _estimate_citizens_likelihood(entity)

    updates: dict = {
        "citizens_likelihood": analysis["likelihood"],
        "citizens_county_penetration": analysis["county_penetration"],
    }

    if analysis["estimated_premium"]:
        updates["citizens_estimated_premium"] = analysis["estimated_premium"]
        updates["citizens_premium_display"] = f"${analysis['estimated_premium']:,}/yr (est)"

    if analysis["factors"]:
        updates["citizens_risk_factors"] = analysis["factors"]

    # Flag as likely on Citizens if score is high enough
    if analysis["likelihood"] >= 50:
        updates["on_citizens"] = True
        updates["citizens_swap_opportunity"] = True

    update_characteristics(entity, updates, "citizens_insurance")

    fields = [k for k, v in updates.items() if v is not None]
    detail = f"Citizens: {analysis['likelihood']}% likelihood"
    if analysis["estimated_premium"]:
        detail += f", est premium ${analysis['estimated_premium']:,}"
    if analysis["likelihood"] >= 50:
        detail += " — SWAP OPPORTUNITY"

    record_enrichment(
        entity, db,
        source_id="citizens_insurance",
        fields_updated=fields,
        source_url="https://www.citizensfla.com",
        detail=detail,
    )

    return True
