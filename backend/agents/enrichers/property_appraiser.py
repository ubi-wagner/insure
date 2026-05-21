"""
FL County Property Appraiser Enricher

Each Florida county has a Property Appraiser office with public parcel data.
Many expose GIS REST services we can query by coordinates or address.

Data available: owner name, assessed value, year built, land use code,
building sqft, lot size, tax district, sale history.

Counties with known GIS REST endpoints (ArcGIS MapServer):
- Pinellas (PCPAO): GIS services at gis.pcpao.org
- Hillsborough (HCPA): GIS at maps.hcpafl.org
- Lee (LEEPA): GIS at gis.leepa.org
- Miami-Dade: GIS at gisweb.miamidade.gov
- Broward (BCPA): GIS at bcpa.net
- Palm Beach: GIS at maps.co.palm-beach.fl.us

Counties requiring web scraping (deferred):
- Pasco, Manatee, Sarasota, Charlotte, Collier
"""

import logging

import httpx
from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)


# Per-county owner-name search URL templates. Used to deep-link from
# a board-member name → that county's PA "search by owner" results.
# The placeholder is {owner}, already URL-quoted by the caller.
#
# Counties with a None value (or absent from this dict) fall back via
# build_pa_owner_search_url() to the static info_url from
# COUNTY_GIS_ENDPOINTS — the portal's homepage — so the user lands
# somewhere reasonable even without a deep-link. Paste a working URL
# pattern and we'll lock it in.
PA_OWNER_SEARCH_TEMPLATES: dict[str, str | None] = {
    # ── Original 11 target coastal counties ──
    "Pinellas":     "https://www.pcpao.gov/quick-search?search-type=name&search={owner}",
    "Hillsborough": "https://www.hcpafl.org/Property-Info/Property-Search#/search/name/{owner}",
    "Lee":          "https://www.leepa.org/Search/PropertySearch.aspx?type=owner&name={owner}",
    "Miami-Dade":   "https://apps.miamidadepa.gov/PropertySearch/#/?owner={owner}",
    "Broward":      "https://bcpa.net/RecAddr.asp?URL_Search=Owner&Search={owner}",
    "Palm Beach":   "https://pbcpao.gov/Property/Search?ownerName={owner}",
    "Pasco":        "https://search.pascopa.com/#/owner/{owner}",
    "Manatee":      "https://www.manateepao.gov/search/?searchType=owner&searchString={owner}",
    "Sarasota":     "https://www.sc-pa.com/propertysearch?owner={owner}",
    "Charlotte":    "https://www.ccappraiser.com/Search.aspx?owner={owner}",
    "Collier":      "https://www.collierappraiser.com/main_search/RecordSearch.html?Owner={owner}",
    # ── Panhandle Gulf Coast ──
    "Bay":          "https://www.baypa.net/search.aspx?owner={owner}",
    "Escambia":     "https://www.escpa.org/CAMA/Search.aspx?searchType=name&searchValue={owner}",
    "Franklin":     "https://www.franklincountypa.com/search?owner={owner}",
    "Gulf":         "https://www.gulfpa.com/search?owner={owner}",
    "Okaloosa":     "https://www.okaloosapa.com/Search?ownerName={owner}",
    "Santa Rosa":   "https://www.srcpa.org/Search?searchType=owner&searchValue={owner}",
    "Walton":       "https://qpublic.schneidercorp.com/Application.aspx?AppID=931&LayerID=18247&PageTypeID=2&SearchType=N&KeyValue={owner}",
    # ── Big Bend / Nature Coast Gulf ──
    "Citrus":       "https://qpublic.schneidercorp.com/Application.aspx?AppID=931&LayerID=18247&PageTypeID=2&SearchType=N&KeyValue={owner}",
    "Dixie":        "https://qpublic.schneidercorp.com/Application.aspx?AppID=941&PageTypeID=2&SearchType=N&KeyValue={owner}",
    "Hernando":     "https://www.hernandopa-fl.us/search?owner={owner}",
    "Jefferson":    "https://qpublic.schneidercorp.com/Application.aspx?AppID=910&PageTypeID=2&SearchType=N&KeyValue={owner}",
    "Levy":         "https://qpublic.schneidercorp.com/Application.aspx?AppID=920&PageTypeID=2&SearchType=N&KeyValue={owner}",
    "Taylor":       "https://qpublic.schneidercorp.com/Application.aspx?AppID=945&PageTypeID=2&SearchType=N&KeyValue={owner}",
    "Wakulla":      "https://qpublic.schneidercorp.com/Application.aspx?AppID=948&PageTypeID=2&SearchType=N&KeyValue={owner}",
    # ── NE Atlantic Coast ──
    "Duval":        "https://paopropertysearch.coj.net/Basic/Search.aspx?ownerName={owner}",
    "Flagler":      "https://www.flaglerpa.com/search?owner={owner}",
    "Nassau":       "https://www.ncpafl.com/search?owner={owner}",
    "St. Johns":    "https://www.sjcpa.us/Search?searchType=owner&searchValue={owner}",
    # ── Central / South Atlantic ──
    "Brevard":      "https://www.bcpao.us/PropertySearch/Search?ownerName={owner}",
    "Indian River": "https://www.ircpa.org/Search?owner={owner}",
    "Martin":       "https://www.pa.martin.fl.us/Search?owner={owner}",
    "St. Lucie":    "https://www.paslc.gov/Search?owner={owner}",
    "Volusia":      "https://vcpa.vcgov.org/search?owner={owner}",
    # ── Florida Keys ──
    "Monroe":       "https://www.mcpafl.org/PropertySearch?owner={owner}",
}


def build_pa_owner_search_url(county: str | None, owner_name: str | None) -> str | None:
    """Deep-link to the county PA's "search by owner name" results.

    Falls back to the county's PA homepage (info_url from
    COUNTY_GIS_ENDPOINTS) when we don't have a confirmed deep-link
    template — the user lands on the right portal and types the name
    manually. Returns None only when we don't recognise the county at
    all.
    """
    if not county or not owner_name:
        return None
    template = PA_OWNER_SEARCH_TEMPLATES.get(county)
    if template:
        from urllib.parse import quote
        return template.format(owner=quote(owner_name.upper(), safe=""))
    # Fallback: homepage URL from the GIS config.
    cfg = COUNTY_GIS_ENDPOINTS.get(county)
    return cfg.get("info_url") if cfg else None


# Per-county parcel-detail deep-links. Pulled from each portal's
# property-details URL pattern, with the parcel ID substituted at
# {parcel}. These bypass the search step entirely — much faster than
# name-based lookup when we already know the parcel.
#
# Counties missing from this dict (or with patterns that turn out
# wrong) fall back via build_pa_parcel_url() to the static info_url
# from COUNTY_GIS_ENDPOINTS so the user still lands on the right
# portal — just with a search step instead of a deep-link.
PA_PARCEL_URL_TEMPLATES: dict[str, str] = {
    # ── Original 11 target coastal counties ──
    "Pinellas":     "https://www.pcpao.gov/property-details?parcel={parcel}",
    "Hillsborough": "https://www.hcpafl.org/Property-Info/Property-Search#/folio/{parcel}",
    "Lee":          "https://www.leepa.org/Display/DisplayParcel.aspx?FolioID={parcel}",
    "Miami-Dade":   "https://apps.miamidadepa.gov/PropertySearch/#/?folio={parcel}",
    "Broward":      "https://bcpa.net/RecInfo.asp?URL_Folio={parcel}",
    "Palm Beach":   "https://pbcpao.gov/Property/Detail?parcelId={parcel}",
    "Pasco":        "https://search.pascopa.com/#/parcel/{parcel}",
    "Manatee":      "https://www.manateepao.gov/search/?searchType=parcel&searchString={parcel}",
    "Sarasota":     "https://www.sc-pa.com/propertysearch?parcel={parcel}",
    "Charlotte":    "https://www.ccappraiser.com/Property/Details?strapn={parcel}",
    "Collier":      "https://www.collierappraiser.com/main_search/RecordDetail.html?Map=No&FolioNum={parcel}",
    # ── Panhandle Gulf Coast ──
    "Bay":          "https://www.baypa.net/property/{parcel}",
    "Escambia":     "https://www.escpa.org/CAMA/Detail_a.aspx?s={parcel}",
    "Franklin":     "https://www.franklincountypa.com/property/{parcel}",
    "Gulf":         "https://www.gulfpa.com/property/{parcel}",
    "Okaloosa":     "https://www.okaloosapa.com/Property.aspx?ParcelID={parcel}",
    "Santa Rosa":   "https://www.srcpa.org/Property?parcel={parcel}",
    "Walton":       "https://qpublic.schneidercorp.com/Application.aspx?AppID=931&LayerID=18247&PageTypeID=4&KeyValue={parcel}",
    # ── Big Bend / Nature Coast Gulf ──
    "Citrus":       "https://qpublic.schneidercorp.com/Application.aspx?AppID=894&PageTypeID=4&KeyValue={parcel}",
    "Dixie":        "https://qpublic.schneidercorp.com/Application.aspx?AppID=941&PageTypeID=4&KeyValue={parcel}",
    "Hernando":     "https://www.hernandopa-fl.us/property/{parcel}",
    "Jefferson":    "https://qpublic.schneidercorp.com/Application.aspx?AppID=910&PageTypeID=4&KeyValue={parcel}",
    "Levy":         "https://qpublic.schneidercorp.com/Application.aspx?AppID=920&PageTypeID=4&KeyValue={parcel}",
    "Taylor":       "https://qpublic.schneidercorp.com/Application.aspx?AppID=945&PageTypeID=4&KeyValue={parcel}",
    "Wakulla":      "https://qpublic.schneidercorp.com/Application.aspx?AppID=948&PageTypeID=4&KeyValue={parcel}",
    # ── NE Atlantic Coast ──
    "Duval":        "https://paopropertysearch.coj.net/Basic/Detail.aspx?RE={parcel}",
    "Flagler":      "https://www.flaglerpa.com/property/{parcel}",
    "Nassau":       "https://www.ncpafl.com/property/{parcel}",
    "St. Johns":    "https://www.sjcpa.us/Property?parcel={parcel}",
    # ── Central / South Atlantic ──
    "Brevard":      "https://www.bcpao.us/PropertySearch/Property?parcelNumber={parcel}",
    "Indian River": "https://www.ircpa.org/Property?parcel={parcel}",
    "Martin":       "https://www.pa.martin.fl.us/Property?parcel={parcel}",
    "St. Lucie":    "https://www.paslc.gov/Property?parcel={parcel}",
    "Volusia":      "https://vcpa.vcgov.org/property/{parcel}",
    # ── Florida Keys ──
    "Monroe":       "https://www.mcpafl.org/PropertySearch?parcel={parcel}",
}


def build_pa_parcel_url(county: str | None, parcel_id: str | None) -> str | None:
    """Deep-link to a specific parcel's detail page on the county PA.

    Faster than the name-search URL when the parcel ID is known —
    lands directly on the property-details view (PCPAO format:
    https://www.pcpao.gov/property-details?parcel=09-31-17-95093-000-7040).
    Falls back to the county's PA homepage when we don't have a
    confirmed parcel-URL template.
    """
    if not county or not parcel_id:
        return None
    template = PA_PARCEL_URL_TEMPLATES.get(county)
    if template:
        # Most portals accept the raw parcel ID with or without dashes;
        # preserve whatever shape we got from NAL.
        return template.format(parcel=str(parcel_id).strip().replace(" ", "+"))
    # Fallback: homepage URL — better than nothing.
    cfg = COUNTY_GIS_ENDPOINTS.get(county)
    return cfg.get("info_url") if cfg else None


def find_master_parcel_in_db(db, master_entity_id: int) -> dict | None:
    """Find the condo association's master parcel row in our own DB.

    By PCPAO convention (and most FL counties) the association's
    common-elements parcel has a parcel_id ending in "0001". For any
    VETTED master we hold, this scans the sibling chain for a parcel
    with that suffix and returns its identifying info — name, parcel
    id, owner. The "real" association name lives on that row even
    when the aggregator's master pick was a unit parcel that just
    happened to have the lowest entity id.

    Returns ``{"id", "name", "parcel_id", "address", "pa_parcel_url"}``
    when found, else None.
    """
    from database.models import Entity
    from agents.seeder import MASTER_PARCEL_SUFFIXES
    from sqlalchemy import or_

    master = db.query(Entity).filter(Entity.id == master_entity_id).first()
    if not master:
        return None

    # Pool: the master itself + all siblings (parent_id = master).
    pool = [master] + (
        db.query(Entity).filter(Entity.parent_id == master_entity_id).all()
    )
    candidates = [
        e for e in pool
        if (e.characteristics or {}).get("dor_parcel_id", "").endswith(MASTER_PARCEL_SUFFIXES)
    ]
    if not candidates:
        return None
    # Prefer 0001 over 0000/9999.
    candidates.sort(key=lambda e: (
        0 if (e.characteristics or {}).get("dor_parcel_id", "").endswith("0001") else 1,
        e.id,
    ))
    pick = candidates[0]
    parcel_id = (pick.characteristics or {}).get("dor_parcel_id")
    return {
        "id": pick.id,
        "name": pick.name,
        "owner_name": pick.name,
        "address": pick.address,
        "parcel_id": parcel_id,
        "pa_parcel_url": build_pa_parcel_url(master.county, parcel_id),
        "is_aggregation_master": (pick.id == master.id),
    }


# County Property Appraiser GIS endpoints
# These are ArcGIS REST services that support spatial queries
COUNTY_GIS_ENDPOINTS: dict[str, dict] = {
    "Pinellas": {
        "name": "Pinellas County Property Appraiser",
        "url": "https://egis.pinellascounty.org/arcgis/rest/services/PropertyInfo/PropertyInformation/MapServer/0/query",
        "info_url": "https://www.pcpao.org/",
        "spatial_ref": 4326,
    },
    "Hillsborough": {
        "name": "Hillsborough County Property Appraiser",
        "url": "https://maps.hcpafl.org/arcgis/rest/services/Public/PropertySearch/MapServer/0/query",
        "info_url": "https://www.hcpafl.org/Property-Info/Property-Search#/search/address/{address}",
        "spatial_ref": 4326,
    },
    "Lee": {
        "name": "Lee County Property Appraiser",
        "url": "https://gis.leepa.org/arcgis/rest/services/Public/Parcels/MapServer/0/query",
        "info_url": "https://www.leepa.org/search/propertySearch.aspx",
        "spatial_ref": 4326,
    },
    "Miami-Dade": {
        "name": "Miami-Dade County Property Appraiser",
        "url": "https://gisweb.miamidade.gov/arcgis/rest/services/MD_PropertySearch/MapServer/0/query",
        "info_url": "https://apps.miamidadepa.gov/PropertySearch/",
        "spatial_ref": 4326,
    },
    "Broward": {
        "name": "Broward County Property Appraiser",
        "url": "https://gis.bcpa.net/arcgis/rest/services/Public/Parcels/MapServer/0/query",
        "info_url": "https://bcpa.net/",
        "spatial_ref": 4326,
    },
    "Palm Beach": {
        "name": "Palm Beach County Property Appraiser",
        "url": "https://maps.co.palm-beach.fl.us/arcgis/rest/services/Parcels/MapServer/0/query",
        "info_url": "https://www.pbcgov.org/papa/index.htm",
        "spatial_ref": 4326,
    },
    # Counties without GIS REST — generate direct parcel/address lookup URLs
    "Pasco": {
        "name": "Pasco County Property Appraiser",
        "url": None,
        "info_url": "https://pascopa.com/",
        "parcel_url": "https://search.pascopa.com/#/parcel/{parcel}",
    },
    "Manatee": {
        "name": "Manatee County Property Appraiser",
        "url": None,
        "info_url": "https://www.manateepao.gov/search/",
        "parcel_url": "https://www.manateepao.gov/search/?searchType=parcel&searchString={parcel}",
    },
    "Sarasota": {
        "name": "Sarasota County Property Appraiser",
        "url": None,
        "info_url": "https://www.sc-pa.com/",
        "parcel_url": "https://www.sc-pa.com/propertysearch?parcel={parcel}",
    },
    "Charlotte": {
        "name": "Charlotte County Property Appraiser",
        "url": None,
        "info_url": "https://www.ccappraiser.com/",
    },
    "Collier": {
        "name": "Collier County Property Appraiser",
        "url": None,
        "info_url": "https://www.collierappraiser.com/",
    },
    # ── Newly added coastal counties (URL-only fallbacks) ──
    "Monroe": {
        "name": "Monroe County Property Appraiser",
        "url": None,
        "info_url": "https://www.mcpafl.org/",
    },
    "Bay": {
        "name": "Bay County Property Appraiser",
        "url": None,
        "info_url": "https://baypa.net/",
    },
    "Walton": {
        "name": "Walton County Property Appraiser",
        "url": None,
        "info_url": "https://www.waltonpa.com/",
    },
    "Okaloosa": {
        "name": "Okaloosa County Property Appraiser",
        "url": None,
        "info_url": "https://www.okaloosapa.com/",
    },
    "Santa Rosa": {
        "name": "Santa Rosa County Property Appraiser",
        "url": None,
        "info_url": "https://www.srcpa.gov/",
    },
    "Escambia": {
        "name": "Escambia County Property Appraiser",
        "url": None,
        "info_url": "https://www.escpa.org/",
    },
    "Gulf": {
        "name": "Gulf County Property Appraiser",
        "url": None,
        "info_url": "https://www.gulfpa.com/",
    },
    "Franklin": {
        "name": "Franklin County Property Appraiser",
        "url": None,
        "info_url": "https://www.franklincountypa.net/",
    },
    "Wakulla": {
        "name": "Wakulla County Property Appraiser",
        "url": None,
        "info_url": "https://www.mywakullapa.com/",
    },
    "Jefferson": {
        "name": "Jefferson County Property Appraiser",
        "url": None,
        "info_url": "https://www.jeffersonpa.net/",
    },
    "Taylor": {
        "name": "Taylor County Property Appraiser",
        "url": None,
        "info_url": "https://www.taylorcountypa.com/",
    },
    "Dixie": {
        "name": "Dixie County Property Appraiser",
        "url": None,
        "info_url": "https://www.dixiepa.com/",
    },
    "Levy": {
        "name": "Levy County Property Appraiser",
        "url": None,
        "info_url": "https://www.levypa.com/",
    },
    "Citrus": {
        "name": "Citrus County Property Appraiser",
        "url": None,
        "info_url": "https://www.citruspa.org/",
    },
    "Hernando": {
        "name": "Hernando County Property Appraiser",
        "url": None,
        "info_url": "https://www.hernandopa-fl.us/",
    },
    "Nassau": {
        "name": "Nassau County Property Appraiser",
        "url": None,
        "info_url": "https://www.nassauflpa.com/",
    },
    "Duval": {
        "name": "Duval County Property Appraiser",
        "url": None,
        "info_url": "https://paopropertysearch.coj.net/",
    },
    "St. Johns": {
        "name": "St. Johns County Property Appraiser",
        "url": None,
        "info_url": "https://www.sjcpa.us/",
    },
    "Flagler": {
        "name": "Flagler County Property Appraiser",
        "url": None,
        "info_url": "https://www.flaglerpa.com/",
    },
    "Volusia": {
        "name": "Volusia County Property Appraiser",
        "url": None,
        "info_url": "https://vcpa.vcgov.org/",
    },
    "Brevard": {
        "name": "Brevard County Property Appraiser",
        "url": None,
        "info_url": "https://www.bcpao.us/",
    },
    "Indian River": {
        "name": "Indian River County Property Appraiser",
        "url": None,
        "info_url": "https://www.ircpa.org/",
    },
    "St. Lucie": {
        "name": "St. Lucie County Property Appraiser",
        "url": None,
        "info_url": "https://www.paslc.gov/",
    },
    "Martin": {
        "name": "Martin County Property Appraiser",
        "url": None,
        "info_url": "https://www.pa.martin.fl.us/",
    },
}


def _query_arcgis_by_point(endpoint_url: str, lat: float, lon: float, sr: int = 4326) -> dict | None:
    """Query an ArcGIS MapServer by point geometry."""
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": sr,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        with httpx.Client(timeout=10, headers={"User-Agent": "insure-lead-gen/1.0"}) as client:
            resp = client.get(endpoint_url, params=params)
            resp.raise_for_status()
            # Guard against HTML error pages
            content_type = resp.headers.get("content-type", "")
            if "json" not in content_type and "text/plain" not in content_type:
                return None
            data = resp.json()
            features = data.get("features", [])
            if features:
                return features[0].get("attributes", {})
    except Exception as e:
        logger.debug(f"ArcGIS query failed for {lat},{lon}: {e}")
    return None


def _normalize_parcel_data(raw: dict) -> dict:
    """Normalize ArcGIS attribute names to our standard fields.

    Different counties use different field names — this handles common patterns.
    """
    # Common field name patterns across FL county GIS
    field_map = {
        # Owner
        "OWNER": "pa_owner", "OWN_NAME": "pa_owner", "OWNER1": "pa_owner",
        "OWNERNAME": "pa_owner", "owner_name": "pa_owner",
        # Assessed value
        "ASSESSED": "pa_assessed_value", "ASMNT_YR": "pa_assessed_value",
        "JUST_VALUE": "pa_assessed_value", "TOTAL_JUST": "pa_assessed_value",
        "JV": "pa_assessed_value", "ASSD_VAL": "pa_assessed_value",
        # Year built
        "YR_BLT": "pa_year_built", "YEAR_BUILT": "pa_year_built",
        "YR_BUILT": "pa_year_built", "YRBUILT": "pa_year_built",
        "ACT_YR_BLT": "pa_year_built",
        # Building sqft
        "BLDG_SQFT": "pa_building_sqft", "LIVING_AREA": "pa_building_sqft",
        "TOT_LVG_AR": "pa_building_sqft", "SQFT": "pa_building_sqft",
        "HEAT_AREA": "pa_building_sqft",
        # Land use
        "USE_CODE": "pa_use_code", "DOR_CODE": "pa_use_code",
        "LAND_USE": "pa_use_code", "USE_CD": "pa_use_code",
        # Parcel ID
        "PARCEL_ID": "pa_parcel_id", "PARCEL": "pa_parcel_id",
        "FOLIO": "pa_parcel_id", "PIN": "pa_parcel_id",
        "STRAP": "pa_parcel_id",
        # Lot/land size
        "LOT_SIZE": "pa_lot_sqft", "LAND_SQFT": "pa_lot_sqft",
        "ACRES": "pa_acres",
        # Sale info
        "SALE_DATE": "pa_last_sale_date", "LAST_SALE": "pa_last_sale_date",
        "SALE_PRICE": "pa_last_sale_price", "SALE_AMT": "pa_last_sale_price",
    }

    normalized = {}
    for raw_key, raw_val in raw.items():
        upper_key = raw_key.upper()
        if upper_key in field_map and raw_val is not None:
            target = field_map[upper_key]
            # Don't overwrite if already set (first match wins)
            if target not in normalized:
                normalized[target] = raw_val

    return normalized


@register_enricher("property_appraiser")
def enrich_property_appraiser(entity: Entity, db: Session) -> bool:
    """Look up parcel data from county property appraiser GIS."""
    county = entity.county
    if not county:
        return False

    config = COUNTY_GIS_ENDPOINTS.get(county)
    if not config:
        logger.debug(f"No PA config for county '{county}'")
        return False

    address_encoded = (entity.address or "").split(",")[0].replace(" ", "+")
    info_url = config["info_url"].format(address=address_encoded)

    # Try parcel-based URL if we have a parcel ID
    chars = dict(entity.characteristics or {})
    parcel_id = chars.get("dor_parcel_id", "")
    if parcel_id and config.get("parcel_url"):
        info_url = config["parcel_url"].format(parcel=parcel_id.replace(" ", "+"))

    # If no GIS endpoint, save lookup URL and record as enrichment (link is the value)
    if not config.get("url"):
        chars["pa_lookup_url"] = info_url
        chars["pa_county"] = county
        entity.characteristics = chars

        record_enrichment(
            entity, db,
            source_id="property_appraiser",
            fields_updated=["pa_lookup_url", "pa_county"],
            source_url=info_url,
            detail=f"PA lookup URL for {county}",
        )
        return True  # URL itself is useful data

    parcel_data = {}

    # GIS endpoint exists — try spatial query
    if entity.latitude and entity.longitude:
        raw = _query_arcgis_by_point(
            config["url"], entity.latitude, entity.longitude,
            config.get("spatial_ref", 4326),
        )
        if raw:
            parcel_data = _normalize_parcel_data(raw)

    if not parcel_data:
        # GIS query failed or returned nothing — save URL but don't claim enrichment
        chars = dict(entity.characteristics or {})
        chars["pa_lookup_url"] = info_url
        chars["pa_county"] = county
        entity.characteristics = chars
        return False

    # Got real data from GIS
    updates = {**parcel_data}
    updates["pa_county"] = county
    updates["pa_lookup_url"] = info_url

    # Update year_built from PA if we got it and it's more reliable than OSM
    if parcel_data.get("pa_year_built"):
        yr = parcel_data["pa_year_built"]
        if isinstance(yr, (int, float)) and 1900 <= yr <= 2026:
            updates["year_built"] = str(int(yr))

    # Update TIV estimate from assessed value if significantly different
    if parcel_data.get("pa_assessed_value"):
        assessed = parcel_data["pa_assessed_value"]
        if isinstance(assessed, (int, float)) and assessed > 100_000:
            updates["pa_assessed_value"] = assessed
            # Replacement cost is typically 1.2-1.5x assessed value for FL condos
            replacement_estimate = round(assessed * 1.3, -3)
            current_tiv = (entity.characteristics or {}).get("tiv_estimate")
            if not current_tiv:
                updates["tiv_estimate"] = replacement_estimate
                updates["tiv"] = f"${replacement_estimate:,.0f}"

    update_characteristics(entity, updates, "property_appraiser")

    fields = [k for k, v in updates.items() if v is not None and k != "pa_lookup_url"]
    record_enrichment(
        entity, db,
        source_id="property_appraiser",
        fields_updated=fields,
        source_url=info_url,
        detail=f"{config['name']}: {len(fields)} fields" + (
            f", assessed=${parcel_data.get('pa_assessed_value', 0):,.0f}"
            if parcel_data.get("pa_assessed_value") else ""
        ),
    )

    return True
