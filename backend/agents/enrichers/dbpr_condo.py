"""
DBPR Division of Condominiums, Timeshares & Mobile Homes Enricher

Searches the Florida DBPR condo registry to find:
- Managing entity (property management company)
- Condo association registration status
- Number of units (official count)
- Building reporting data (post-Surfside structural inspections)

Portal: https://condos.myfloridalicense.com
CAM License search: https://www.myfloridalicense.com/wl11.asp

Also generates lookup URLs for the DBPR CAM license search to find
the licensed Community Association Manager for the property.

This enricher runs on TARGET stage — after Sunbiz has found the
association name, we can search DBPR for the managing entity.
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

DBPR_CONDO_SEARCH = "https://www.myfloridalicense.com/wl11.asp"
DBPR_CONDO_PORTAL = "https://condos.myfloridalicense.com"
CAM_LICENSE_SEARCH = "https://www.myfloridalicense.com/wl11.asp?mode=0&SID=&session=&page=LicenseDetail"


def _search_dbpr_condo(search_name: str) -> list[dict]:
    """Search DBPR condo registry by association name.

    Returns list of matching registered condos.
    Note: DBPR may block automated requests; this is best-effort.
    """
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            # Search the condo portal
            resp = client.get(f"{DBPR_CONDO_PORTAL}/SearchCondos", params={
                "searchText": search_name,
                "searchType": "Name",
            }, headers={
                "User-Agent": "Mozilla/5.0 (compatible; InsureLeadGen/1.0)",
            })
            resp.raise_for_status()
            text = resp.text

            results = []
            # Look for condo association entries with managing entity info
            # Pattern varies but typically shows name, managing entity, unit count
            name_pattern = r'<td[^>]*>([^<]*(?:CONDO|CONDOMINIUM|ASSOCIATION)[^<]*)</td>'
            names = re.findall(name_pattern, text, re.IGNORECASE)

            # Look for managing entity references
            mgmt_pattern = r'(?:Managing|Management)\s*(?:Entity|Company)[^<]*<[^>]*>([^<]+)'
            mgmt_matches = re.findall(mgmt_pattern, text, re.IGNORECASE)

            # Look for unit counts
            unit_pattern = r'(\d+)\s*(?:units?|residential)'
            unit_matches = re.findall(unit_pattern, text, re.IGNORECASE)

            if names:
                result = {"name": names[0].strip()}
                if mgmt_matches:
                    result["managing_entity"] = mgmt_matches[0].strip()
                if unit_matches:
                    result["units"] = int(unit_matches[0])
                results.append(result)

            return results
    except Exception as e:
        logger.warning(f"DBPR condo search failed for '{search_name}': {e}")
        return []


@register_enricher("TARGET", "dbpr_condo", requires=[])
def enrich_dbpr_condo(entity: Entity, db: Session) -> bool:
    """Search DBPR for condo association registration and management info."""
    chars = entity.characteristics or {}

    # Use the sunbiz corp name if available, otherwise entity name
    search_name = str(chars.get("sunbiz_corp_name") or entity.name or "")
    if not search_name:
        return False

    # Clean the name for search
    clean_name = re.sub(r'\b(inc\.?|llc|corp\.?)\b', '', search_name, flags=re.IGNORECASE).strip()

    # Generate lookup URLs
    condo_search_url = f"{DBPR_CONDO_PORTAL}/SearchCondos?searchText={quote_plus(clean_name)}&searchType=Name"
    cam_search_url = f"{DBPR_CONDO_SEARCH}?mode=0&SID=&session=&page=LicenseSearch"

    updates: dict = {
        "dbpr_condo_search_url": condo_search_url,
        "dbpr_cam_search_url": cam_search_url,
    }

    # If we have the property manager from sunbiz, generate a CAM lookup URL
    property_manager = chars.get("property_manager") or chars.get("sunbiz_registered_agent")
    if property_manager:
        cam_lookup = f"{DBPR_CONDO_SEARCH}?mode=0&SID=&session=&page=LicenseSearch&searchType=Business&searchText={quote_plus(str(property_manager))}"
        updates["dbpr_cam_lookup_url"] = cam_lookup
        updates["dbpr_management_company"] = str(property_manager)

    # Attempt DBPR search
    results = _search_dbpr_condo(clean_name)
    if results:
        best = results[0]
        if best.get("managing_entity"):
            updates["dbpr_managing_entity"] = best["managing_entity"]
            # If different from sunbiz registered agent, this is the actual management co
            if not property_manager:
                updates["property_manager"] = best["managing_entity"]
        if best.get("units"):
            updates["dbpr_official_units"] = best["units"]
            # Official unit count is more authoritative
            updates["units_estimate"] = best["units"]

    update_characteristics(entity, updates, "dbpr_condo")

    fields = [k for k, v in updates.items() if v is not None]
    detail_parts = [f"DBPR: {len(fields)} fields"]
    if updates.get("dbpr_managing_entity"):
        detail_parts.append(f"mgmt={updates['dbpr_managing_entity']}")

    record_enrichment(
        entity, db,
        source_id="dbpr_condo",
        fields_updated=fields,
        source_url=condo_search_url,
        detail=", ".join(detail_parts),
    )

    return True
