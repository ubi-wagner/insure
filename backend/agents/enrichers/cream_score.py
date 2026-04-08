"""
Cream Score — Identifies the highest-value conversion opportunities.

Unlike heat_score (data completeness), cream_score specifically targets:
- Large coastal condos ($10M+ TIV)
- High-rise (7+ stories = severe wind exposure)
- Known governance (board contacts, management company)
- Insurance pain (high premiums, Citizens insured, hard market county)
- Compliance pressure (SIRS deadlines, delinquent payments)

Score: 0-100, broken into tiers:
  90-100: "platinum" — call today
  70-89:  "gold"     — high priority outreach
  50-69:  "silver"   — worth pursuing
  30-49:  "bronze"   — nurture / monitor
  0-29:   "prospect" — data-only, not ready

This runs AFTER all other enrichers as a final scoring pass.
"""

import logging
from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)


def _safe_float(val) -> float:
    """Safely convert a JSONB value to float."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val) -> int:
    """Safely convert a JSONB value to int."""
    if val is None:
        return 0
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


# Counties with highest wind insurance costs (coastal exposure)
PREMIUM_COUNTIES = {"Broward", "Palm Beach", "Miami-Dade", "Pinellas", "Lee", "Collier"}
HIGH_WIND_COUNTIES = {"Broward", "Palm Beach", "Miami-Dade", "Lee", "Charlotte", "Collier"}
IAN_IMPACT_COUNTIES = {"Lee", "Charlotte", "Collier", "Sarasota"}


@register_enricher("cream_score", requires=[])
def compute_cream_score(entity: Entity, db: Session) -> bool:
    """Compute cream score — conversion opportunity rating (0-100)."""
    chars = entity.characteristics or {}
    sources = entity.enrichment_sources or {}
    county = entity.county or ""

    score = 0
    factors = []

    # ═══════════════════════════════════════════
    # PROPERTY SIZE & VALUE (max 25 points)
    # ═══════════════════════════════════════════

    market_value = _safe_float(chars.get("dor_market_value"))
    tiv = _safe_float(chars.get("tiv_estimate"))
    value = max(market_value, tiv)

    if value >= 100_000_000:
        score += 25
        factors.append(f"$100M+ value")
    elif value >= 50_000_000:
        score += 20
        factors.append(f"$50M+ value")
    elif value >= 25_000_000:
        score += 15
        factors.append(f"$25M+ value")
    elif value >= 10_000_000:
        score += 10
        factors.append(f"$10M+ value")
    elif value >= 5_000_000:
        score += 5

    units = _safe_int(chars.get("dor_num_units") or chars.get("units_estimate"))
    if units >= 200:
        score += 5
        factors.append(f"{units} units")
    elif units >= 50:
        score += 3

    # ═══════════════════════════════════════════
    # WIND EXPOSURE (max 20 points)
    # ═══════════════════════════════════════════

    stories = _safe_int(chars.get("stories") or chars.get("dbpr_max_stories"))
    year_built = _safe_int(chars.get("year_built") or chars.get("dor_year_built"))

    if stories >= 10:
        score += 15
        factors.append(f"{stories}-story high-rise")
    elif stories >= 7:
        score += 12
        factors.append(f"{stories} stories")
    elif stories >= 4:
        score += 5

    if county in HIGH_WIND_COUNTIES:
        score += 5
        factors.append(f"high-wind county ({county})")

    # ═══════════════════════════════════════════
    # INSURANCE PAIN (max 20 points)
    # ═══════════════════════════════════════════

    if chars.get("on_citizens"):
        score += 15
        factors.append("Citizens insured — swap opportunity")
    elif _safe_float(chars.get("citizens_likelihood")) >= 50:
        score += 8
        factors.append("likely Citizens")

    market_hardness = chars.get("oir_market_hardness", "")
    if market_hardness == "hard":
        score += 5
        factors.append("hard market")

    if county in IAN_IMPACT_COUNTIES:
        score += 3
        factors.append("Hurricane Ian impact zone")

    # Premium estimate available → quantified opportunity
    if chars.get("oir_estimated_premium_range"):
        score += 2

    # ═══════════════════════════════════════════
    # CONTACT & GOVERNANCE DATA (max 20 points)
    # ═══════════════════════════════════════════

    has_decision_maker = bool(chars.get("decision_maker"))
    has_management = bool(chars.get("property_manager") or chars.get("sunbiz_registered_agent") or chars.get("dbpr_managing_entity"))
    has_contacts = False
    try:
        contacts = entity.contacts or []
        has_email = any(c.email for c in contacts)
        has_contacts = len(contacts) > 0
    except Exception:
        has_email = False

    if has_email:
        score += 10
        factors.append("email contact available")
    elif has_decision_maker:
        score += 7
        factors.append(f"decision maker: {chars.get('decision_maker')}")
    elif has_contacts:
        score += 4

    if has_management:
        score += 5
        mgr = chars.get("dbpr_managing_entity") or chars.get("property_manager") or chars.get("sunbiz_registered_agent")
        factors.append(f"managed by {mgr}")

    if chars.get("sunbiz_corp_name"):
        score += 3
    if chars.get("dbpr_condo_name"):
        score += 2

    # ═══════════════════════════════════════════
    # COMPLIANCE PRESSURE (max 15 points)
    # ═══════════════════════════════════════════

    if chars.get("sirs_compliance_risk") == "HIGH":
        score += 10
        factors.append("SIRS non-compliant — special assessment risk")
    elif chars.get("sirs_completed") is False:
        score += 7
        factors.append("SIRS not filed")

    if chars.get("payment_is_delinquent"):
        score += 5
        factors.append("DBPR payment delinquent")

    # ═══════════════════════════════════════════
    # FINANCIAL DISTRESS — from DBPR Key Financial Indicators
    # The single strongest "actively shopping" signal
    # ═══════════════════════════════════════════

    distress = chars.get("dbpr_financial_distress")
    if distress == "negative_operating_fund":
        score += 12
        factors.append("negative operating fund balance")
    elif distress == "burning_cash":
        score += 10
        factors.append("operating expenses exceed revenue")
    elif distress == "thin_margin":
        score += 5
        factors.append("thin operating margin")

    if chars.get("dbpr_collections_issue"):
        score += 5
        factors.append("collections / bad debt issue")

    if chars.get("dbpr_reserve_underfunded"):
        score += 8
        factors.append("reserve fund underfunded — assessment risk")

    # Newly converted condos (NOIC) — fresh associations need master policies
    if chars.get("noic_match"):
        score += 4
        factors.append("recently converted condo (NOIC)")

    # Flood zone risk → higher insurance need
    flood_risk = chars.get("flood_risk", "")
    if flood_risk in ("extreme", "high"):
        score += 5
        factors.append(f"flood risk: {flood_risk}")
    elif flood_risk == "moderate_high":
        score += 2

    # Old building + pre-code construction = higher premiums
    if year_built and year_built < 2002:
        construction = str(chars.get("dor_construction_class") or chars.get("construction_class") or "").lower()
        if "frame" in construction:
            score += 5
            factors.append("pre-FBC frame construction")
        elif year_built < 1992:
            score += 3
            factors.append(f"pre-Andrew construction ({year_built})")

    # ═══════════════════════════════════════════
    # CLASSIFY
    # ═══════════════════════════════════════════

    score = min(score, 100)

    if score >= 90:
        tier = "platinum"
    elif score >= 70:
        tier = "gold"
    elif score >= 50:
        tier = "silver"
    elif score >= 30:
        tier = "bronze"
    else:
        tier = "prospect"

    updates = {
        "cream_score": score,
        "cream_tier": tier,
        "cream_factors": factors[:10],  # Top 10 factors
    }

    update_characteristics(entity, updates, "cream_score")
    record_enrichment(
        entity, db,
        source_id="cream_score",
        fields_updated=["cream_score", "cream_tier", "cream_factors"],
        detail=f"Score {score}/100 ({tier}) — {', '.join(factors[:3])}",
    )

    return True
