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

# County Property Appraiser GIS endpoints
# These are ArcGIS REST services that support spatial queries
COUNTY_GIS_ENDPOINTS: dict[str, dict] = {
    "Pinellas": {
        "name": "Pinellas County Property Appraiser",
        "url": "https://egis.pinellascounty.org/arcgis/rest/services/PropertyInfo/PropertyInformation/MapServer/0/query",
        "info_url": "https://www.pcpao.gov/search.php?q={address}",
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
        "info_url": "https://www.miamidade.gov/pa/property-search.asp",
        "spatial_ref": 4326,
    },
    "Broward": {
        "name": "Broward County Property Appraiser",
        "url": "https://gis.bcpa.net/arcgis/rest/services/Public/Parcels/MapServer/0/query",
        "info_url": "https://web.bcpa.net/BcpaClient/#/Record-Search",
        "spatial_ref": 4326,
    },
    "Palm Beach": {
        "name": "Palm Beach County Property Appraiser",
        "url": "https://maps.co.palm-beach.fl.us/arcgis/rest/services/Parcels/MapServer/0/query",
        "info_url": "https://www.pbcgov.org/papa/",
        "spatial_ref": 4326,
    },
    # Counties without known GIS REST — we still generate lookup URLs
    "Pasco": {
        "name": "Pasco County Property Appraiser",
        "url": None,
        "info_url": "https://search.pascopa.com/#/search/address/{address}",
    },
    "Manatee": {
        "name": "Manatee County Property Appraiser",
        "url": None,
        "info_url": "https://www.manateepao.com/search/?searchType=address&searchString={address}",
    },
    "Sarasota": {
        "name": "Sarasota County Property Appraiser",
        "url": None,
        "info_url": "https://www.sarasotapropappr.com/#/search/address/{address}",
    },
    "Charlotte": {
        "name": "Charlotte County Property Appraiser",
        "url": None,
        "info_url": "https://www.ccappraiser.com/search.asp",
    },
    "Collier": {
        "name": "Collier County Property Appraiser",
        "url": None,
        "info_url": "https://www.collierappraiser.com/Main/Home.aspx",
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


@register_enricher("NEW", "property_appraiser")
def enrich_property_appraiser(entity: Entity, db: Session) -> bool:
    """Look up parcel data from county property appraiser GIS."""
    county = entity.county
    if not county:
        return False

    config = COUNTY_GIS_ENDPOINTS.get(county)
    if not config:
        logger.debug(f"No PA config for county '{county}'")
        return False

    # Generate the lookup URL regardless of whether we can query GIS
    address_encoded = (entity.address or "").replace(" ", "+").replace(",", "")
    info_url = config["info_url"].format(address=address_encoded)

    parcel_data = {}

    # If GIS endpoint exists and we have coordinates, try spatial query
    if config.get("url") and entity.latitude and entity.longitude:
        raw = _query_arcgis_by_point(
            config["url"], entity.latitude, entity.longitude,
            config.get("spatial_ref", 4326),
        )
        if raw:
            parcel_data = _normalize_parcel_data(raw)

    # Even without GIS data, record the lookup URL as a source
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
