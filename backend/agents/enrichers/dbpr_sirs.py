"""
DBPR Structural Integrity Reserve Study (SIRS) Enricher

After the Surfside collapse (2021), Florida SB 4-D / HB 1 now requires condo
associations with buildings of 3+ stories to complete a Structural Integrity
Reserve Study (milestone inspection + reserve study) by Dec 31, 2025.

Data source: DBPR SIRS Reporting Portal
https://www2.myfloridalicense.com/condos-timeshares-mobile-homes/condominiums-and-cooperatives-sirs-reporting/

Insurance relevance:
- Associations that HAVE filed SIRS: stable, proactive boards. Good prospects.
- Associations that HAVE NOT filed: HIGH compliance risk. Special assessments
  incoming. These properties are actively shopping for new coverage because
  carriers are non-renewing non-compliant associations.
- Both states contribute meaningfully to heat scoring.

Requires: dbpr_bulk (needs dbpr_project_number or dbpr_condo_name for lookup).
"""

import logging
import re
from urllib.parse import quote_plus

import httpx
from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)

SIRS_PORTAL_URL = (
    "https://www2.myfloridalicense.com/condos-timeshares-mobile-homes/"
    "condominiums-and-cooperatives-sirs-reporting/"
)

# SIRS compliance deadline per FL statute 718.112(2)(g)
SIRS_DEADLINE = "2025-12-31"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _build_sirs_lookup_url(project_number: str = "", association_name: str = "") -> str:
    """Build a direct lookup URL for the SIRS reporting portal.

    The portal may support query parameters for searching. If not, we link
    to the base portal page so users can search manually.
    """
    if project_number:
        return f"{SIRS_PORTAL_URL}?project={quote_plus(project_number)}"
    if association_name:
        return f"{SIRS_PORTAL_URL}?name={quote_plus(association_name)}"
    return SIRS_PORTAL_URL


def _try_scrape_sirs(project_number: str = "", association_name: str = "") -> dict | None:
    """Attempt to retrieve SIRS filing data from the DBPR portal.

    The portal may serve HTML tables, JSON, or a search form. We try
    common patterns and parse what we can. Returns None if scraping fails
    (403, JS-only rendering, etc.).
    """
    search_url = _build_sirs_lookup_url(project_number, association_name)

    try:
        with httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers=HTTP_HEADERS,
        ) as client:
            resp = client.get(search_url)

            # Many state portals block automated access
            if resp.status_code in (403, 429, 503):
                logger.info(
                    f"SIRS portal returned {resp.status_code} — "
                    "automated access may be blocked"
                )
                return None

            resp.raise_for_status()
            text = resp.text

            # Guard against JS-only SPA pages with no useful content
            if len(text) < 500 or "<noscript>" in text.lower():
                return None

            result: dict = {}

            # Try to find SIRS completion status in HTML
            # Pattern: look for project number or name near status indicators
            search_term = project_number or association_name
            if not search_term:
                return None

            # Look for the search term in the page content
            if search_term.lower() not in text.lower():
                return None

            # Try to extract completion status
            completed_patterns = [
                r"(?:SIRS|study)\s*(?:status|completed?)[:\s]*(?:<[^>]*>)?\s*(yes|no|completed?|pending|received)",
                r"(?:status|filing)[:\s]*(?:<[^>]*>)?\s*(completed?|received|filed|pending|not\s*filed)",
            ]
            for pattern in completed_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    status_text = match.group(1).strip().lower()
                    result["sirs_completed"] = status_text in (
                        "yes", "complete", "completed", "received", "filed",
                    )
                    break

            # Try to extract completion date
            date_patterns = [
                r"(?:completion|filed?|received?|submitted?)\s*(?:date)?[:\s]*(?:<[^>]*>)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})\s*(?:completion|filed|received)",
            ]
            for pattern in date_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    result["sirs_completion_date"] = match.group(1).strip()
                    break

            # Try to extract engineer/firm name
            engineer_patterns = [
                r"(?:engineer|firm|inspector|licensed\s*professional)[:\s]*(?:<[^>]*>)?\s*([A-Z][A-Za-z\s.,'&-]{3,60})",
                r"(?:prepared\s*by|conducted\s*by)[:\s]*(?:<[^>]*>)?\s*([A-Z][A-Za-z\s.,'&-]{3,60})",
            ]
            for pattern in engineer_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    engineer = match.group(1).strip().rstrip(",.")
                    if len(engineer) > 3:
                        result["sirs_engineer"] = engineer
                    break

            # Try to extract building condition
            condition_patterns = [
                r"(?:building\s*)?condition[:\s]*(?:<[^>]*>)?\s*([A-Za-z][A-Za-z\s/-]{2,40})",
                r"(?:structural\s*)?(?:rating|assessment)[:\s]*(?:<[^>]*>)?\s*([A-Za-z][A-Za-z\s/-]{2,40})",
            ]
            for pattern in condition_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    result["sirs_building_condition"] = match.group(1).strip()
                    break

            # Try to extract reserve items (often in a table or list)
            reserve_items = []
            item_patterns = [
                r"<(?:tr|li)[^>]*>\s*(?:<td[^>]*>)?\s*([A-Za-z][^<]{3,60})\s*(?:</td>)?\s*(?:<td[^>]*>)?\s*\$?([\d,]+(?:\.\d{2})?)\s*(?:</td>)?",
            ]
            for pattern in item_patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    item_name = match.group(1).strip()
                    item_amount = match.group(2).strip()
                    # Filter out navigation/header items
                    if len(item_name) > 3 and not re.match(
                        r"(?:home|search|contact|about|menu|nav)", item_name, re.IGNORECASE
                    ):
                        reserve_items.append({
                            "item": item_name,
                            "amount": item_amount,
                        })
                    if len(reserve_items) >= 20:
                        break
                if reserve_items:
                    break

            if reserve_items:
                result["sirs_reserve_items"] = reserve_items

            return result if result else None

    except httpx.HTTPStatusError as e:
        logger.info(f"SIRS portal HTTP error: {e.response.status_code}")
        return None
    except Exception as e:
        logger.warning(f"SIRS portal scrape failed: {e}")
        return None


@register_enricher("dbpr_sirs", requires=["dbpr_bulk"])
def enrich_dbpr_sirs(entity: Entity, db: Session) -> bool:
    """Check DBPR SIRS reporting status for a condo association.

    Even if scraping fails, we generate a lookup URL and flag compliance
    risk — both outcomes are valuable for lead scoring.
    """
    chars = dict(entity.characteristics or {})

    project_number = str(chars.get("dbpr_project_number") or "")
    association_name = str(
        chars.get("dbpr_condo_name") or entity.name or ""
    )

    if not project_number and not association_name:
        return False

    # Build the lookup URL (always useful, even if scrape fails)
    lookup_url = _build_sirs_lookup_url(project_number, association_name)

    updates: dict = {
        "sirs_lookup_url": lookup_url,
        "sirs_deadline": SIRS_DEADLINE,
    }

    # Attempt to scrape SIRS data from the portal
    sirs_data = _try_scrape_sirs(project_number, association_name)

    if sirs_data:
        # Got real data from the portal
        if "sirs_completed" in sirs_data:
            updates["sirs_completed"] = sirs_data["sirs_completed"]
        if sirs_data.get("sirs_completion_date"):
            updates["sirs_completion_date"] = sirs_data["sirs_completion_date"]
        if sirs_data.get("sirs_engineer"):
            updates["sirs_engineer"] = sirs_data["sirs_engineer"]
        if sirs_data.get("sirs_building_condition"):
            updates["sirs_building_condition"] = sirs_data["sirs_building_condition"]
        if sirs_data.get("sirs_reserve_items"):
            updates["sirs_reserve_items"] = sirs_data["sirs_reserve_items"]

        # Assess compliance risk based on filing status
        if sirs_data.get("sirs_completed"):
            updates["sirs_compliance_risk"] = "LOW"
        else:
            updates["sirs_compliance_risk"] = "HIGH"

        updates["sirs_data_source"] = "dbpr_portal"
    else:
        # Scrape failed or returned no data. This is still valuable:
        # No SIRS on file likely means non-compliant (deadline was Dec 31, 2025).
        updates["sirs_completed"] = False
        updates["sirs_compliance_risk"] = "HIGH"
        updates["sirs_data_source"] = "lookup_url_only"
        updates["sirs_needs_manual_verification"] = True

        logger.info(
            f"SIRS data not found for '{association_name}' "
            f"(project={project_number}). Flagged as non-compliant "
            "pending manual verification."
        )

    update_characteristics(entity, updates, "dbpr_sirs")

    fields = [k for k, v in updates.items() if v is not None and k != "sirs_lookup_url"]

    detail_parts = []
    if updates.get("sirs_completed"):
        detail_parts.append("SIRS FILED")
        if updates.get("sirs_engineer"):
            detail_parts.append(f"engineer={updates['sirs_engineer']}")
    elif updates.get("sirs_completed") is False:
        detail_parts.append("NO SIRS ON FILE")
        detail_parts.append(f"compliance_risk={updates.get('sirs_compliance_risk', 'HIGH')}")
    if updates.get("sirs_needs_manual_verification"):
        detail_parts.append("needs manual verification")

    record_enrichment(
        entity, db,
        source_id="dbpr_sirs",
        fields_updated=fields,
        source_url=lookup_url,
        detail=", ".join(detail_parts) if detail_parts else "SIRS lookup URL generated",
    )

    # Always return True — the lookup URL alone is useful data, matching
    # the property_appraiser.py pattern for counties without GIS endpoints.
    return True
