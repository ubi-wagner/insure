"""
DBPR Building Report Enricher

As of July 2025, FL requires condo associations to file building reports
with DBPR containing structural and financial details:
- Contact information (association manager/board)
- Total number of buildings
- Number of buildings by story count
- Units per building
- Current assessment amounts (monthly/quarterly)

Data source: DBPR Building Report Portal
https://www2.myfloridalicense.com/condos-timeshares-mobile-homes/building-report/

Insurance relevance:
- Story count determines SIRS applicability (3+ stories = mandatory)
- Unit count and assessment amounts help estimate TIV and premium
- Contact info from the report is a direct lead (board member or manager)
- Building count helps validate property data from other sources

Requires: dbpr_bulk (needs dbpr_project_number or dbpr_condo_name for lookup).
"""

import logging
import re
from urllib.parse import quote_plus

import httpx
from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Contact, Entity

logger = logging.getLogger(__name__)

BUILDING_REPORT_URL = (
    "https://www2.myfloridalicense.com/condos-timeshares-mobile-homes/"
    "building-report/"
)

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _build_report_lookup_url(
    project_number: str = "", association_name: str = ""
) -> str:
    """Build a direct lookup URL for the DBPR building report portal."""
    if project_number:
        return f"{BUILDING_REPORT_URL}?project={quote_plus(project_number)}"
    if association_name:
        return f"{BUILDING_REPORT_URL}?name={quote_plus(association_name)}"
    return BUILDING_REPORT_URL


def _try_scrape_building_report(
    project_number: str = "", association_name: str = ""
) -> dict | None:
    """Attempt to retrieve building report data from the DBPR portal.

    The portal launched July 2025 and may serve HTML tables, a search form,
    or require JS rendering. We try common patterns and parse what we can.
    Returns None if scraping fails (403, JS-only, etc.).
    """
    search_url = _build_report_lookup_url(project_number, association_name)

    try:
        with httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers=HTTP_HEADERS,
        ) as client:
            resp = client.get(search_url)

            if resp.status_code in (403, 429, 503):
                logger.info(
                    f"Building report portal returned {resp.status_code} — "
                    "automated access may be blocked"
                )
                return None

            resp.raise_for_status()
            text = resp.text

            # Guard against JS-only SPA pages
            if len(text) < 500 or "<noscript>" in text.lower():
                return None

            # Verify the search term appears in the page
            search_term = project_number or association_name
            if not search_term or search_term.lower() not in text.lower():
                return None

            result: dict = {}

            # --- Building count ---
            bldg_count_patterns = [
                r"(?:total\s*)?(?:number\s*of\s*)?buildings?[:\s]*(?:<[^>]*>)?\s*(\d+)",
                r"(\d+)\s*(?:total\s*)?buildings?",
            ]
            for pattern in bldg_count_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    count = int(match.group(1))
                    if 1 <= count <= 500:  # sanity check
                        result["dbpr_building_count"] = count
                    break

            # --- Stories per building ---
            # May appear as "3-story buildings: 2, 7-story buildings: 1" or a table
            stories_patterns = [
                r"(\d+)\s*(?:-?\s*)?stor(?:y|ies)[:\s]*(?:<[^>]*>)?\s*(\d+)\s*(?:buildings?)?",
                r"(?:buildings?\s*(?:with|of)\s*)?(\d+)\s*(?:stories|floors)[:\s]*(?:<[^>]*>)?\s*(\d+)",
            ]
            stories_data = {}
            for pattern in stories_patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    stories = int(match.group(1))
                    count = int(match.group(2))
                    if 1 <= stories <= 60 and 1 <= count <= 200:
                        stories_data[stories] = count
                if stories_data:
                    break
            if stories_data:
                result["dbpr_building_stories"] = stories_data

            # --- Units per building ---
            units_patterns = [
                r"(?:total\s*)?units?[:\s]*(?:<[^>]*>)?\s*(\d+)",
                r"(\d+)\s*(?:total\s*)?(?:residential\s*)?units?",
            ]
            for pattern in units_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    units = int(match.group(1))
                    if 2 <= units <= 5000:  # sanity check
                        result["dbpr_building_units"] = units
                    break

            # --- Assessment amounts ---
            assessment_patterns = [
                r"(?:monthly|quarterly|annual)\s*assessment[:\s]*(?:<[^>]*>)?\s*\$?([\d,]+(?:\.\d{2})?)",
                r"assessment\s*(?:amount)?[:\s]*(?:<[^>]*>)?\s*\$?([\d,]+(?:\.\d{2})?)\s*(?:per\s*)?(month|quarter|year|annual)",
            ]
            for pattern in assessment_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    amount_str = match.group(1).replace(",", "")
                    try:
                        amount = float(amount_str)
                        if amount > 0:
                            result["dbpr_current_assessment"] = amount
                            # Capture frequency if available
                            if match.lastindex and match.lastindex >= 2:
                                result["dbpr_assessment_frequency"] = (
                                    match.group(2).strip().lower()
                                )
                            else:
                                # Try to infer from surrounding text
                                context = text[
                                    max(0, match.start() - 50) : match.end() + 50
                                ].lower()
                                if "monthly" in context:
                                    result["dbpr_assessment_frequency"] = "monthly"
                                elif "quarterly" in context:
                                    result["dbpr_assessment_frequency"] = "quarterly"
                                elif "annual" in context:
                                    result["dbpr_assessment_frequency"] = "annual"
                    except ValueError:
                        pass
                    break

            # --- Contact information ---
            contact_name_patterns = [
                r"(?:contact|manager|agent|representative)\s*(?:name)?[:\s]*(?:<[^>]*>)?\s*([A-Z][A-Za-z\s.'-]{2,50})",
                r"(?:submitted\s*by|filed\s*by|reported\s*by)[:\s]*(?:<[^>]*>)?\s*([A-Z][A-Za-z\s.'-]{2,50})",
            ]
            for pattern in contact_name_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    name = match.group(1).strip().rstrip(",.")
                    # Filter out HTML artifacts and common false positives
                    if (
                        len(name) > 3
                        and not re.match(
                            r"(?:home|search|contact us|about|menu|Florida)",
                            name,
                            re.IGNORECASE,
                        )
                    ):
                        result["dbpr_contact_name"] = name
                    break

            email_match = re.search(
                r"[\w.+-]+@[\w-]+\.[\w.-]+", text
            )
            if email_match:
                email = email_match.group(0).lower()
                # Filter out generic site emails
                if not re.match(
                    r".*@(?:myfloridalicense|state\.fl|dbpr)\.(?:com|gov)",
                    email,
                ):
                    result["dbpr_contact_email"] = email

            phone_match = re.search(
                r"(?:phone|tel|contact)[:\s]*(?:<[^>]*>)?\s*"
                r"\(?(\d{3})\)?[\s.-]*(\d{3})[\s.-]*(\d{4})",
                text,
                re.IGNORECASE,
            )
            if phone_match:
                phone = (
                    f"({phone_match.group(1)}) "
                    f"{phone_match.group(2)}-{phone_match.group(3)}"
                )
                result["dbpr_contact_phone"] = phone

            return result if result else None

    except httpx.HTTPStatusError as e:
        logger.info(f"Building report portal HTTP error: {e.response.status_code}")
        return None
    except Exception as e:
        logger.warning(f"Building report portal scrape failed: {e}")
        return None


def _create_contact_if_new(
    entity: Entity,
    db: Session,
    name: str,
    email: str | None,
    phone: str | None,
    source_url: str,
) -> bool:
    """Create a Contact record if one with the same name doesn't already exist."""
    existing = (
        db.query(Contact)
        .filter(
            Contact.entity_id == entity.id,
            Contact.name == name,
        )
        .first()
    )
    if existing:
        return False

    contact = Contact(
        entity_id=entity.id,
        name=name,
        title="Association Contact (DBPR Building Report)",
        email=email,
        phone=phone,
        is_primary=0,
        source="dbpr_building",
        source_url=source_url,
    )
    db.add(contact)
    return True


@register_enricher("dbpr_building", requires=["dbpr_bulk"])
def enrich_dbpr_building(entity: Entity, db: Session) -> bool:
    """Pull building report data from DBPR's building reporting portal.

    Even if scraping fails, we generate a lookup URL for manual verification.
    """
    chars = dict(entity.characteristics or {})

    project_number = str(chars.get("dbpr_project_number") or "")
    association_name = str(
        chars.get("dbpr_condo_name") or entity.name or ""
    )

    if not project_number and not association_name:
        return False

    lookup_url = _build_report_lookup_url(project_number, association_name)

    updates: dict = {
        "dbpr_building_report_url": lookup_url,
    }

    report_data = _try_scrape_building_report(project_number, association_name)
    contact_created = False

    if report_data:
        # Building structure data
        if report_data.get("dbpr_building_count"):
            updates["dbpr_building_count"] = report_data["dbpr_building_count"]

        if report_data.get("dbpr_building_stories"):
            updates["dbpr_building_stories"] = report_data["dbpr_building_stories"]
            # Determine max stories — relevant for SIRS applicability
            max_stories = max(report_data["dbpr_building_stories"].keys())
            updates["dbpr_max_stories"] = max_stories
            if max_stories >= 3:
                updates["dbpr_sirs_applicable"] = True

        if report_data.get("dbpr_building_units"):
            updates["dbpr_building_units"] = report_data["dbpr_building_units"]
            # Cross-reference with existing unit count
            existing_units = chars.get("dbpr_official_units") or chars.get(
                "units_estimate"
            )
            if not existing_units:
                updates["units_estimate"] = report_data["dbpr_building_units"]

        # Financial data
        if report_data.get("dbpr_current_assessment"):
            updates["dbpr_current_assessment"] = report_data[
                "dbpr_current_assessment"
            ]
        if report_data.get("dbpr_assessment_frequency"):
            updates["dbpr_assessment_frequency"] = report_data[
                "dbpr_assessment_frequency"
            ]

        # Contact information
        if report_data.get("dbpr_contact_name"):
            updates["dbpr_contact_name"] = report_data["dbpr_contact_name"]
        if report_data.get("dbpr_contact_email"):
            updates["dbpr_contact_email"] = report_data["dbpr_contact_email"]
        if report_data.get("dbpr_contact_phone"):
            updates["dbpr_contact_phone"] = report_data["dbpr_contact_phone"]

        # Create a Contact record if we have a name
        contact_name = report_data.get("dbpr_contact_name")
        if contact_name:
            contact_created = _create_contact_if_new(
                entity,
                db,
                name=contact_name,
                email=report_data.get("dbpr_contact_email"),
                phone=report_data.get("dbpr_contact_phone"),
                source_url=lookup_url,
            )

        updates["dbpr_building_report_source"] = "dbpr_portal"
    else:
        # Scrape failed — still record the lookup URL for manual use
        updates["dbpr_building_report_source"] = "lookup_url_only"
        updates["dbpr_building_report_needs_verification"] = True

        logger.info(
            f"Building report not found for '{association_name}' "
            f"(project={project_number}). Lookup URL saved for "
            "manual verification."
        )

    update_characteristics(entity, updates, "dbpr_building")

    fields = [
        k
        for k, v in updates.items()
        if v is not None and k != "dbpr_building_report_url"
    ]

    detail_parts = []
    if updates.get("dbpr_building_count"):
        detail_parts.append(
            f"{updates['dbpr_building_count']} building(s)"
        )
    if updates.get("dbpr_max_stories"):
        detail_parts.append(f"max {updates['dbpr_max_stories']} stories")
    if updates.get("dbpr_building_units"):
        detail_parts.append(f"{updates['dbpr_building_units']} units")
    if updates.get("dbpr_current_assessment"):
        freq = updates.get("dbpr_assessment_frequency", "")
        detail_parts.append(
            f"assessment=${updates['dbpr_current_assessment']:,.2f}"
            + (f"/{freq}" if freq else "")
        )
    if contact_created:
        detail_parts.append(
            f"contact: {updates.get('dbpr_contact_name', 'created')}"
        )
    if updates.get("dbpr_building_report_needs_verification"):
        detail_parts.append("needs manual verification")
    if not detail_parts:
        detail_parts.append("lookup URL generated")

    record_enrichment(
        entity,
        db,
        source_id="dbpr_building",
        fields_updated=fields,
        source_url=lookup_url,
        detail=", ".join(detail_parts),
    )

    # Always return True — the lookup URL alone is useful, matching the
    # property_appraiser.py pattern for counties without GIS endpoints.
    return True
