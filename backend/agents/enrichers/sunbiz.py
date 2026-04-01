"""
Florida Sunbiz (Division of Corporations) Enricher

Searches search.sunbiz.org for the condo/HOA association to find:
- Corporation/association name and filing number
- Registered agent (often the property management company)
- Officers (board president, secretary, treasurer = decision makers)
- Annual report filing status

No public API — generates search URLs for manual/future scrape access.
When the search URL pattern is known, we can extract structured data.

Sunbiz search URL: https://search.sunbiz.org/Inquiry/CorporationSearch/ByName
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

SUNBIZ_SEARCH_URL = "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchByName"
SUNBIZ_DETAIL_BASE = "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResultDetail"


def _build_search_name(entity_name: str) -> str:
    """Extract the association name suitable for Sunbiz search.

    Strips common suffixes and prefixes that would pollute the search.
    e.g., "Ultimar Condominium Association, Inc." → "Ultimar"
    """
    name = entity_name
    # Remove common suffixes
    for suffix in [
        "condominium association", "condo association", "condo assoc",
        "homeowners association", "hoa", "owners association",
        "property owners", "inc.", "inc", "llc", "corp",
        "association", "assoc", "of", "the",
    ]:
        name = re.sub(rf"\b{re.escape(suffix)}\b", "", name, flags=re.IGNORECASE)

    name = re.sub(r"[,.\-]+", " ", name).strip()
    # Use first 2-3 significant words for search
    words = [w for w in name.split() if len(w) > 2]
    return " ".join(words[:3]) if words else entity_name


def _search_sunbiz(search_name: str) -> list[dict]:
    """Search Sunbiz for corporation by name.

    Returns list of matching corporations with basic info.
    Note: Sunbiz may block automated requests; this is best-effort.
    """
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(SUNBIZ_SEARCH_URL, params={
                "searchNameOrder": search_name,
                "searchTypeOrder": "STARTS",
            }, headers={
                "User-Agent": "Mozilla/5.0 (compatible; InsureLeadGen/1.0)",
            })
            resp.raise_for_status()

            # Parse basic results from HTML
            # Look for corporation names and document numbers
            results = []
            text = resp.text

            # Find corporation links: /Inquiry/CorporationSearch/SearchResultDetail?inquirytype=EntityName&directionType=Initial&searchNameOrder=...&...&...documentNumber=...
            pattern = r'SearchResultDetail[^"]*documentNumber=([A-Z0-9]+)[^"]*"[^>]*>([^<]+)</a>'
            matches = re.findall(pattern, text)

            for doc_num, corp_name in matches[:5]:  # Top 5 matches
                results.append({
                    "document_number": doc_num.strip(),
                    "name": corp_name.strip(),
                    "url": f"https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResultDetail?inquirytype=EntityName&directionType=Initial&searchNameOrder={quote_plus(search_name)}&searchTerm={quote_plus(search_name)}&listNameOrder={quote_plus(corp_name.strip())}&documentNumber={doc_num.strip()}",
                })

            return results
    except Exception as e:
        logger.warning(f"Sunbiz search failed for '{search_name}': {e}")
        return []


def _get_corporation_detail(detail_url: str) -> dict:
    """Fetch corporation detail page and extract officers and registered agent."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(detail_url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; InsureLeadGen/1.0)",
            })
            resp.raise_for_status()
            text = resp.text

            result = {"officers": [], "registered_agent": None, "status": None}

            # Extract filing status
            status_match = re.search(r'Status[^<]*<[^>]*>([^<]+)', text)
            if status_match:
                result["status"] = status_match.group(1).strip()

            # Extract registered agent (often the management company)
            agent_section = re.search(r'Registered Agent.*?<div[^>]*>(.*?)</div>', text, re.DOTALL)
            if agent_section:
                agent_text = re.sub(r'<[^>]+>', '\n', agent_section.group(1)).strip()
                lines = [l.strip() for l in agent_text.split('\n') if l.strip()]
                if lines:
                    result["registered_agent"] = lines[0]

            # Extract officers (President, Secretary, Treasurer, etc.)
            officer_pattern = r'<span[^>]*>([^<]*(?:President|Secretary|Treasurer|Director|VP|Vice President)[^<]*)</span>[^<]*<[^>]*>([^<]+)'
            officer_matches = re.findall(officer_pattern, text, re.IGNORECASE)
            for title, name in officer_matches:
                result["officers"].append({
                    "title": title.strip(),
                    "name": name.strip(),
                })

            return result
    except Exception as e:
        logger.warning(f"Sunbiz detail fetch failed: {e}")
        return {}


@register_enricher("CANDIDATE", "sunbiz", requires=[])
def enrich_sunbiz(entity: Entity, db: Session) -> bool:
    """Search Florida Sunbiz for condo/HOA association information."""
    if not entity.name:
        return False

    search_name = _build_search_name(entity.name)
    search_url = f"https://search.sunbiz.org/Inquiry/CorporationSearch/ByName?searchNameOrder={quote_plus(search_name)}&searchTypeOrder=STARTS"

    # Attempt search
    results = _search_sunbiz(search_name)

    updates: dict = {
        "sunbiz_search_url": search_url,
        "sunbiz_search_name": search_name,
    }
    contacts_added = []

    if results:
        # Use best match (first result)
        best = results[0]
        updates["sunbiz_corp_name"] = best["name"]
        updates["sunbiz_doc_number"] = best["document_number"]
        updates["sunbiz_detail_url"] = best["url"]

        # Try to get detailed info (officers, registered agent)
        detail = _get_corporation_detail(best["url"])
        if detail:
            if detail.get("status"):
                updates["sunbiz_filing_status"] = detail["status"]
            if detail.get("registered_agent"):
                updates["sunbiz_registered_agent"] = detail["registered_agent"]
                # Registered agent is often the property management company
                updates["property_manager"] = detail["registered_agent"]

            # Create contacts from officers
            for officer in detail.get("officers", []):
                # Check if contact already exists
                existing = db.query(Contact).filter(
                    Contact.entity_id == entity.id,
                    Contact.name == officer["name"],
                ).first()
                if not existing:
                    is_president = "president" in officer["title"].lower()
                    contact = Contact(
                        entity_id=entity.id,
                        name=officer["name"],
                        title=officer["title"],
                        is_primary=1 if is_president else 0,
                        source="sunbiz",
                        source_url=best["url"],
                    )
                    db.add(contact)
                    contacts_added.append(officer["name"])

        if contacts_added:
            db.flush()

    update_characteristics(entity, updates, "sunbiz")

    fields = [k for k, v in updates.items() if v is not None]
    detail_msg = f"Sunbiz: {len(fields)} fields"
    if contacts_added:
        detail_msg += f", {len(contacts_added)} contacts added"
    if updates.get("sunbiz_corp_name"):
        detail_msg += f" — {updates['sunbiz_corp_name']}"

    record_enrichment(
        entity, db,
        source_id="sunbiz",
        fields_updated=fields + [f"contact:{n}" for n in contacts_added],
        source_url=updates.get("sunbiz_detail_url") or search_url,
        detail=detail_msg,
    )

    return True
