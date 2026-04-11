"""
Citizens Property Insurance Enricher

Citizens is Florida's state-created insurer of last resort. Any
building on Citizens is:
1. Paying higher-than-market rates
2. Being actively depopulated by the state
3. A warm/hot lead for policy swap

This enricher estimates likelihood a property COULD be on Citizens
based on county penetration, flood risk, TIV, construction, and age.

IMPORTANT: This is heuristic scoring only. `on_citizens` is NEVER
set True by this enricher — only by actual policy evidence (e.g.
declaration page upload or confirmed carrier data). The heuristic
produces `citizens_candidate` (bool) and `citizens_likelihood` (0-100).

Citizens data sources:
- Rate filings: https://www.citizensfla.com
- Market share reports (PDF)
- Policy count by county (public records)
"""

import logging

from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)

# Citizens market penetration by county (estimated 2025-2026 data).
# Coverage: all 35 Florida coastal counties + Florida Keys.
HIGH_CITIZENS_COUNTIES = {
    # Original 11 + Monroe
    "Monroe": 0.45,         # Florida Keys — highest in state
    "Miami-Dade": 0.35,
    "Broward": 0.28,
    "Palm Beach": 0.25,
    "Pinellas": 0.22,
    "Lee": 0.20,
    "Collier": 0.18,
    "Charlotte": 0.16,
    "Sarasota": 0.15,
    "Manatee": 0.14,
    "Hillsborough": 0.12,
    "Pasco": 0.10,
    # Panhandle (post-Sally / post-Michael — elevated but moderating)
    "Bay": 0.18,            # Panama City (post-Michael)
    "Gulf": 0.14,           # Port St. Joe
    "Walton": 0.14,
    "Okaloosa": 0.13,
    "Santa Rosa": 0.13,
    "Escambia": 0.14,       # Pensacola
    "Franklin": 0.10,
    # Big Bend / Nature Coast (low density, lower penetration)
    "Wakulla": 0.07,
    "Jefferson": 0.06,
    "Taylor": 0.07,
    "Dixie": 0.07,
    "Levy": 0.07,
    "Citrus": 0.07,
    "Hernando": 0.08,
    # NE Atlantic
    "Nassau": 0.09,
    "Duval": 0.08,
    "St. Johns": 0.10,
    "Flagler": 0.11,
    # Central Atlantic
    "Volusia": 0.12,
    "Brevard": 0.13,
    "Indian River": 0.13,
    "St. Lucie": 0.14,
    "Martin": 0.16,
}

# Citizens 2026 commercial property rates per $1,000 of TIV.
# These are FALLBACK rates used only when OIR market data is unavailable.
# When OIR has run, Citizens uses oir_estimated_premium * CITIZENS_MARKUP
# (statutorily required to be higher than market — FL Statute 627.351(6)).
CITIZENS_RATE_PER_1000 = {
    "coastal_masonry": 9.5,
    "coastal_frame": 14.0,
    "coastal_fire_resistive": 7.5,
    "inland_masonry": 5.0,
    "inland_frame": 7.5,
    "inland_fire_resistive": 4.0,
}

# Citizens is the insurer of last resort. By FL Statute 627.351(6), Citizens
# rates must be non-competitive — meaning at least as high as the highest
# market rate. In practice, Citizens runs ~30-50% above the standard market.
CITIZENS_MARKUP = 1.35


def _estimate_citizens_likelihood(entity: Entity) -> dict:
    """Estimate likelihood this property could be on Citizens.

    Returns dict with: likelihood (0-100), estimated_premium, factors, tier
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

    # Flood zone
    flood_risk = chars.get("flood_risk", "")
    if flood_risk in ("extreme", "high"):
        score += 25
        factors.append(f"High flood risk ({chars.get('flood_zone', 'unknown')})")
    elif flood_risk == "moderate_high":
        score += 10

    # TIV
    tiv = chars.get("tiv_estimate")
    if tiv and isinstance(tiv, (int, float)):
        if tiv >= 5_000_000:
            score += 20
            factors.append(f"High TIV (${tiv:,.0f})")
        elif tiv >= 1_000_000:
            score += 10

    # Construction
    const_class = str(chars.get("dor_construction_class") or chars.get("construction_class") or "").lower()
    if "frame" in const_class or "wood" in const_class:
        score += 15
        factors.append("Frame construction (limited private market options)")
    elif "masonry" in const_class:
        score += 5

    # Age
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

    # Multi-unit
    units = chars.get("dor_num_units") or chars.get("units_estimate")
    if units and isinstance(units, (int, float)) and units >= 50:
        score += 10
        factors.append(f"Large association ({int(units)} units)")

    # Estimate premium if on Citizens.
    # PREFERRED: market premium (from OIR enricher) × Citizens statutory markup.
    # FALLBACK: simple rate-per-$1000-TIV table when OIR hasn't run yet.
    estimated_premium = None
    estimate_source = None

    oir_low = chars.get("oir_estimated_premium_low")
    oir_high = chars.get("oir_estimated_premium_high")
    if oir_low and oir_high and isinstance(oir_low, (int, float)) and isinstance(oir_high, (int, float)):
        # Use OIR midpoint × markup
        market_mid = (float(oir_low) + float(oir_high)) / 2
        estimated_premium = int(market_mid * CITIZENS_MARKUP)
        estimate_source = "oir_market+markup"
    elif tiv and isinstance(tiv, (int, float)) and tiv > 0:
        # Fallback to simple rate-per-$1000 table
        is_coastal = flood_risk in ("extreme", "high", "moderate_high")
        location = "coastal" if is_coastal else "inland"
        if "frame" in const_class:
            rate_key = f"{location}_frame"
        elif "fire" in const_class or "resistive" in const_class:
            rate_key = f"{location}_fire_resistive"
        else:
            rate_key = f"{location}_masonry"
        rate_per_1000 = CITIZENS_RATE_PER_1000.get(rate_key, 6.0)
        estimated_premium = int(tiv * rate_per_1000 / 1000)
        estimate_source = "fallback_table"

    # Tier based on score — descriptive, not asserting actual status
    likelihood = min(score, 100)
    if likelihood >= 70:
        tier = "likely_candidate"
    elif likelihood >= 50:
        tier = "possible_candidate"
    elif likelihood >= 30:
        tier = "low_candidate"
    else:
        tier = "unlikely"

    return {
        "likelihood": likelihood,
        "tier": tier,
        "estimated_premium": estimated_premium,
        "estimate_source": estimate_source,
        "factors": factors,
        "county_penetration": penetration,
    }


@register_enricher("citizens_insurance", requires=["oir_market"])
def enrich_citizens_insurance(entity: Entity, db: Session) -> bool:
    """Analyze whether this property could be a Citizens candidate.

    DOES NOT set on_citizens=True — that requires actual policy evidence.
    Sets citizens_candidate and citizens_likelihood for screening.
    """
    # Refresh from DB so we pick up the latest characteristics (especially
    # oir_estimated_premium_low/high written by the OIR enricher worker).
    # Without this, parallel worker threads can read stale entity objects
    # and fall back to the Citizens rate table instead of applying the
    # OIR market × 1.35 markup.
    try:
        db.refresh(entity)
    except Exception:
        pass  # If refresh fails (e.g. detached instance), use loaded data

    chars = entity.characteristics or {}

    if not entity.county:
        return False
    if not chars.get("dor_market_value") and not chars.get("tiv_estimate"):
        return False

    analysis = _estimate_citizens_likelihood(entity)

    updates: dict = {
        "citizens_likelihood": analysis["likelihood"],
        "citizens_likelihood_tier": analysis["tier"],
        "citizens_county_penetration": analysis["county_penetration"],
    }

    if analysis["estimated_premium"]:
        updates["citizens_estimated_premium"] = analysis["estimated_premium"]
        # Show as a range (±15%) and tag the source
        low = int(analysis["estimated_premium"] * 0.85)
        high = int(analysis["estimated_premium"] * 1.15)
        src_tag = "+35% over market" if analysis["estimate_source"] == "oir_market+markup" else "fallback rate table"
        updates["citizens_premium_display"] = f"${low:,} – ${high:,}/yr ({src_tag})"
        updates["citizens_estimate_source"] = analysis["estimate_source"]

    if analysis["factors"]:
        updates["citizens_risk_factors"] = analysis["factors"]

    # Mark as candidate for investigation, NOT as confirmed Citizens
    updates["citizens_candidate"] = analysis["likelihood"] >= 50
    updates["citizens_swap_opportunity"] = analysis["likelihood"] >= 70

    # Explicitly do NOT set on_citizens — only real policy evidence does that
    # If a previous heuristic run set it, clear it
    if chars.get("on_citizens") is True and not chars.get("citizens_policy_confirmed"):
        updates["on_citizens"] = False

    update_characteristics(entity, updates, "citizens_insurance")

    fields = [k for k, v in updates.items() if v is not None]
    detail = f"Citizens: {analysis['likelihood']}% ({analysis['tier']})"
    if analysis["estimated_premium"]:
        detail += f", est ${analysis['estimated_premium']:,}/yr"

    record_enrichment(
        entity, db,
        source_id="citizens_insurance",
        fields_updated=fields,
        source_url="https://www.citizensfla.com",
        detail=detail,
    )

    return True
