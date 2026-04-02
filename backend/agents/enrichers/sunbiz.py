"""
Florida Sunbiz (Division of Corporations) Enricher

Searches search.sunbiz.org for the condo/HOA association to find:
- Corporation/association name and filing number
- Registered agent (often the property management company)
- Officers (board president, secretary, treasurer = decision makers)
- Annual report filing status

Sunbiz search: https://search.sunbiz.org/Inquiry/CorporationSearch/SearchByName
Detail page: https://search.sunbiz.org/Inquiry/CorporationSearch/ConvertTiffToPDF?storagePath=COR\\...
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
SUNBIZ_BASE = "https://search.sunbiz.org"
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _build_search_name(entity_name: str) -> str:
    """Extract the association name suitable for Sunbiz search."""
    name = entity_name
    for suffix in [
        "condominium association", "condo association", "condo assoc",
        "homeowners association", "hoa", "owners association",
        "property owners", "inc.", "inc", "llc", "corp",
        "association", "assoc", "of", "the",
    ]:
        name = re.sub(rf"\b{re.escape(suffix)}\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[,.\-]+", " ", name).strip()
    words = [w for w in name.split() if len(w) > 2]
    return " ".join(words[:3]) if words else entity_name


def _search_sunbiz(search_name: str) -> list[dict]:
    """Search Sunbiz and return matching corporation results."""
    try:
        with httpx.Client(timeout=20, follow_redirects=True, headers=HTTP_HEADERS) as client:
            resp = client.get(SUNBIZ_SEARCH_URL, params={
                "searchNameOrder": search_name,
                "searchTypeOrder": "STARTS",
            })
            resp.raise_for_status()
            text = resp.text
            results = []

            # Parse search result links — they contain document numbers
            # Pattern: /Inquiry/CorporationSearch/SearchResultDetail?...documentNumber=XXXXX
            rows = re.findall(
                r'<a href="(/Inquiry/CorporationSearch/SearchResultDetail[^"]*)"[^>]*>([^<]+)</a>',
                text
            )
            for url_path, corp_name in rows[:5]:
                doc_match = re.search(r'[&?]documentNumber=([A-Z0-9]+)', url_path)
                if doc_match:
                    results.append({
                        "document_number": doc_match.group(1),
                        "name": corp_name.strip(),
                        "detail_url": f"{SUNBIZ_BASE}{url_path}",
                    })
            return results
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            logger.debug(f"Sunbiz 403 (blocked from cloud IP) for '{search_name}'")
        else:
            logger.warning(f"Sunbiz search failed for '{search_name}': {e}")
        return []
    except Exception as e:
        logger.warning(f"Sunbiz search failed for '{search_name}': {e}")
        return []


def _get_corporation_detail(detail_url: str) -> dict:
    """Fetch corporation detail page and extract officers and registered agent."""
    try:
        with httpx.Client(timeout=20, follow_redirects=True, headers=HTTP_HEADERS) as client:
            resp = client.get(detail_url)
            resp.raise_for_status()
            text = resp.text
            result = {"officers": [], "registered_agent": None, "status": None, "filing_date": None, "address": None}

            # Filing status — look for "Status" label followed by value
            status_match = re.search(r'Status\s*</label>\s*<span[^>]*>([^<]+)', text)
            if status_match:
                result["status"] = status_match.group(1).strip()

            # Filing date
            date_match = re.search(r'(?:Date Filed|Filed Date)\s*</label>\s*<span[^>]*>([^<]+)', text)
            if date_match:
                result["filing_date"] = date_match.group(1).strip()

            # Principal address
            addr_section = re.search(r'Principal Address.*?<div[^>]*class="[^"]*detailSection[^"]*"[^>]*>(.*?)</div>', text, re.DOTALL)
            if addr_section:
                addr_text = re.sub(r'<br\s*/?>', '\n', addr_section.group(1))
                addr_text = re.sub(r'<[^>]+>', '', addr_text).strip()
                lines = [l.strip() for l in addr_text.split('\n') if l.strip()]
                if lines:
                    result["address"] = ", ".join(lines[:3])

            # Registered agent — in its own section
            agent_section = re.search(
                r'Registered Agent.*?<div[^>]*class="[^"]*detailSection[^"]*"[^>]*>(.*?)</div>',
                text, re.DOTALL
            )
            if agent_section:
                agent_html = agent_section.group(1)
                agent_text = re.sub(r'<br\s*/?>', '\n', agent_html)
                agent_text = re.sub(r'<[^>]+>', '', agent_text).strip()
                lines = [l.strip() for l in agent_text.split('\n') if l.strip()]
                if lines:
                    result["registered_agent"] = lines[0]

            # Officers — in the Officer/Director Detail section
            # Each officer block: Title followed by Name
            officer_section = re.search(
                r'Officer/Director Detail(.*?)(?:Annual Report|$)',
                text, re.DOTALL
            )
            if officer_section:
                block = officer_section.group(1)
                # Title lines followed by name lines
                title_pattern = r'<span[^>]*>\s*((?:President|Vice President|Secretary|Treasurer|Director|VP|Chairman|Manager|Member|Registered Agent)[^<]*)</span>'
                titles = re.findall(title_pattern, block, re.IGNORECASE)

                # Get all names (typically in spans after titles)
                name_spans = re.findall(r'<span[^>]*>([A-Z][A-Z\s,.\'-]+)</span>', block)
                # Filter out titles from names
                title_set = {t.strip().upper() for t in titles}
                names = [n.strip() for n in name_spans if n.strip().upper() not in title_set and len(n.strip()) > 3]

                # Pair them up
                for idx, title in enumerate(titles):
                    name = names[idx] if idx < len(names) else None
                    if name:
                        result["officers"].append({
                            "title": title.strip(),
                            "name": name.strip().title(),  # Normalize case
                        })

            return result
    except Exception as e:
        logger.warning(f"Sunbiz detail fetch failed: {e}")
        return {}


def _is_association_name(name: str) -> bool:
    """Check if name looks like a condo/HOA association vs an individual person."""
    name_upper = name.upper()
    # Association indicators
    assoc_keywords = [
        "CONDO", "CONDOMINIUM", "HOA", "HOMEOWNER", "ASSOCIATION", "ASSOC",
        "VILLAS", "TOWERS", "ESTATES", "VILLAGE", "CLUB", "MANOR",
        "TERRACE", "PLAZA", "GARDENS", "LANDING", "POINTE", "POINT",
        "SHORES", "BEACH", "BAY", "HARBOUR", "HARBOR", "LAKE", "ISLE",
        "RETREAT", "PRESERVE", "COMMONS", "CROSSING", "RIDGE", "PALM",
        "SUNSET", "SUNRISE", "OCEAN", "GULF", "PARK", "PLACE",
        "RESIDENCES", "APARTMENTS", "COOPERATIVE", "CO-OP",
        "INC", "LLC", "CORP", "LTD", "TRUST", "MANAGEMENT",
    ]
    if any(kw in name_upper for kw in assoc_keywords):
        return True

    # Person names: typically "LASTNAME FIRSTNAME" or "LASTNAME, FIRSTNAME"
    # Short names (1-3 words, no keywords) are likely people
    words = [w for w in name_upper.split() if len(w) > 1]
    if len(words) <= 3 and not any(kw in name_upper for kw in assoc_keywords):
        return False

    return len(words) > 3


@register_enricher("sunbiz")
def enrich_sunbiz(entity: Entity, db: Session) -> bool:
    """Search Florida Sunbiz for condo/HOA association information."""
    if not entity.name:
        return False

    # Determine what to search: prefer DBPR condo name, fall back to entity name
    chars = entity.characteristics or {}
    search_source = None

    # Best: DBPR already matched a condo name
    dbpr_name = chars.get("dbpr_condo_name")
    if dbpr_name:
        search_source = dbpr_name

    # Next: entity name if it looks like an association
    if not search_source and _is_association_name(entity.name):
        search_source = entity.name

    # Next: owner name if it looks like an association
    if not search_source:
        owner = chars.get("dor_owner", "")
        if owner and _is_association_name(owner):
            search_source = owner

    # Skip if we only have a person's name — not searchable on Sunbiz
    if not search_source:
        return False

    search_name = _build_search_name(search_source)
    search_url = f"{SUNBIZ_SEARCH_URL}?searchNameOrder={quote_plus(search_name)}&searchTypeOrder=STARTS"

    # Try to search — may get 403 from cloud servers
    results = _search_sunbiz(search_name)

    updates: dict = {
        "sunbiz_search_url": search_url,
        "sunbiz_search_name": search_name,
    }
    # Even if scraping fails, we still have the search URL for manual lookup
    contacts_added = []

    if results:
        best = results[0]
        updates["sunbiz_corp_name"] = best["name"]
        updates["sunbiz_doc_number"] = best["document_number"]
        updates["sunbiz_detail_url"] = best["detail_url"]

        # Fetch the actual detail page to get officers and registered agent
        detail = _get_corporation_detail(best["detail_url"])
        if detail:
            if detail.get("status"):
                updates["sunbiz_filing_status"] = detail["status"]
            if detail.get("filing_date"):
                updates["sunbiz_filing_date"] = detail["filing_date"]
            if detail.get("address"):
                updates["sunbiz_principal_address"] = detail["address"]
            if detail.get("registered_agent"):
                updates["sunbiz_registered_agent"] = detail["registered_agent"]
                updates["property_manager"] = detail["registered_agent"]

            # Create contacts from officers — these are the decision makers
            for officer in detail.get("officers", []):
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
                        source_url=best["detail_url"],
                    )
                    db.add(contact)
                    contacts_added.append(f"{officer['name']} ({officer['title']})")

                    # If this is the president, also store as decision maker
                    if is_president:
                        updates["decision_maker"] = officer["name"]
                        updates["decision_maker_title"] = officer["title"]

            if contacts_added:
                db.flush()

    update_characteristics(entity, updates, "sunbiz")

    fields = [k for k, v in updates.items() if v is not None]
    detail_msg = f"Sunbiz: {len(fields)} fields"
    if contacts_added:
        detail_msg += f", {len(contacts_added)} contacts ({', '.join(contacts_added[:3])})"
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
