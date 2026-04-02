"""
DBPR Division of Condominiums, Timeshares & Mobile Homes Enricher

Searches the DBPR condo portal and CAM license system for:
- Managing entity (property management company)
- Licensed Community Association Manager (CAM) name
- Condo association registration status
- Number of units (official count from DBPR)

Portal: https://www.myfloridalicense.com
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

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# DBPR license search
DBPR_LICENSE_URL = "https://www.myfloridalicense.com/wl11.asp"


def _search_dbpr_cam(search_name: str) -> dict | None:
    """Search DBPR for a Community Association Manager or firm by name."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True, headers=HTTP_HEADERS) as client:
            # Search for CAM firm by business name
            resp = client.post(DBPR_LICENSE_URL, data={
                "SID": "",
                "bession": "",  # yes this is DBPR's actual param name
                "page": "ProfessionalSearch",
                "searchType": "Business",
                "LicenseType": "6100",  # CAM license type
                "searchText": search_name,
                "submit": "Search",
            })
            resp.raise_for_status()
            text = resp.text

            result = {}

            # Look for license details in the response
            # DBPR returns HTML tables with license info
            name_match = re.search(r'(?:Business|Licensee)\s*Name[^<]*<[^>]*>([^<]+)', text, re.IGNORECASE)
            if name_match:
                result["cam_name"] = name_match.group(1).strip()

            license_match = re.search(r'License\s*(?:Number|#|No)[^<]*<[^>]*>([^<]+)', text, re.IGNORECASE)
            if license_match:
                result["cam_license"] = license_match.group(1).strip()

            status_match = re.search(r'(?:License\s*)?Status[^<]*<[^>]*>([^<]+)', text, re.IGNORECASE)
            if status_match:
                result["cam_status"] = status_match.group(1).strip()

            address_match = re.search(r'(?:Business\s*)?Address[^<]*<[^>]*>([^<]+)', text, re.IGNORECASE)
            if address_match:
                result["cam_address"] = address_match.group(1).strip()

            return result if result else None
    except Exception as e:
        logger.warning(f"DBPR CAM search failed for '{search_name}': {e}")
        return None


@register_enricher("TARGETED", "dbpr_condo", requires=[])
def enrich_dbpr_condo(entity: Entity, db: Session) -> bool:
    """Search DBPR for condo association registration and CAM info."""
    chars = entity.characteristics or {}

    # Use the property manager name if we have it from Sunbiz
    property_manager = str(chars.get("property_manager") or chars.get("sunbiz_registered_agent") or "")
    search_name = str(chars.get("sunbiz_corp_name") or entity.name or "")
    if not search_name:
        return False

    clean_name = re.sub(r'\b(inc\.?|llc|corp\.?)\b', '', search_name, flags=re.IGNORECASE).strip()

    # Generate lookup URLs
    condo_search_url = f"{DBPR_LICENSE_URL}?mode=0&SID=&page=ProfessionalSearch&searchType=Business&searchText={quote_plus(clean_name)}"

    updates: dict = {
        "dbpr_search_url": condo_search_url,
    }

    # Search for the property manager as a CAM licensee
    if property_manager and len(property_manager) > 3:
        cam_result = _search_dbpr_cam(property_manager)
        if cam_result:
            if cam_result.get("cam_name"):
                updates["dbpr_cam_name"] = cam_result["cam_name"]
            if cam_result.get("cam_license"):
                updates["dbpr_cam_license"] = cam_result["cam_license"]
            if cam_result.get("cam_status"):
                updates["dbpr_cam_status"] = cam_result["cam_status"]
            if cam_result.get("cam_address"):
                updates["dbpr_cam_address"] = cam_result["cam_address"]
            updates["dbpr_management_company"] = property_manager

    # Also try searching for the association itself
    assoc_result = _search_dbpr_cam(clean_name)
    if assoc_result:
        if assoc_result.get("cam_name") and not updates.get("dbpr_cam_name"):
            updates["dbpr_cam_name"] = assoc_result["cam_name"]

    update_characteristics(entity, updates, "dbpr_condo")

    fields = [k for k, v in updates.items() if v is not None and k != "dbpr_search_url"]
    detail_parts = [f"DBPR: {len(fields)} fields"]
    if updates.get("dbpr_cam_name"):
        detail_parts.append(f"CAM={updates['dbpr_cam_name']}")
    if updates.get("dbpr_management_company"):
        detail_parts.append(f"mgmt={updates['dbpr_management_company']}")

    record_enrichment(
        entity, db,
        source_id="dbpr_condo",
        fields_updated=fields,
        source_url=condo_search_url,
        detail=", ".join(detail_parts),
    )

    return True
