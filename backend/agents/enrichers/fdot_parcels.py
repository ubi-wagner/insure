"""
FDOT Statewide Parcel Enricher

Uses the Florida DOT statewide parcel ArcGIS FeatureServer — a single
API covering ALL 67 Florida counties. No key required.

Endpoint: https://gis.fdot.gov/arcgis/rest/services/Parcels/FeatureServer/0/query

This is more reliable than per-county PA GIS queries because:
- Single endpoint for all counties (no county-specific URL mapping)
- Standardized field names from FL DOR
- Updated regularly from county tax rolls

Fields available: parcel ID, owner, address, DOR use code, assessed/market
value, year built, living area sqft, total area, acreage, number of units,
number of buildings, sale date, sale price.
"""

import logging

import httpx
from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)

FDOT_URL = "https://gis.fdot.gov/arcgis/rest/services/Parcels/FeatureServer/0/query"

# FL DOR use codes relevant to commercial property / condo associations
# 04 = Condominiums, 08 = Multi-family (10+ units), 09 = Residential common area
# 10-39 = Commercial/industrial, 04 is our primary target
CONDO_USE_CODES = {"04", "08", "09"}


def _query_fdot_parcel(lat: float, lon: float) -> dict | None:
    """Query FDOT statewide parcel layer by point."""
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": (
            "PARCELNO,OWN_NAME,OWN_ADDR1,OWN_ADDR2,OWN_CITY,OWN_STATE,OWN_ZIPCD,"
            "PHY_ADDR1,PHY_ADDR2,PHY_CITY,PHY_ZIPCD,DOR_UC,JV,AV_LAND,AV_BLDG,AV_SD,"
            "TV_SD,YR_BLT,EFF_YR_BLT,TOT_LVG_AR,LND_SQFOOT,NO_BULDNG,NO_RES_UNT,"
            "SALEDT1,SALEVAL1,CO_NO,GRP_NAME"
        ),
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": "insure-lead-gen/1.0"}) as client:
            resp = client.get(FDOT_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            features = data.get("features", [])
            if features:
                return features[0].get("attributes", {})
    except Exception as e:
        logger.warning(f"FDOT parcel query failed for {lat},{lon}: {e}")
    return None


# FL county number to name mapping (for the 11 target counties)
# DOR county numbers (alphabetical starting at 11, NOT FIPS codes)
COUNTY_NUMBERS = {
    "16": "Broward", "18": "Charlotte", "21": "Collier",
    "23": "Miami-Dade", "39": "Hillsborough", "46": "Lee",
    "51": "Manatee", "60": "Palm Beach", "61": "Pasco",
    "62": "Pinellas", "68": "Sarasota",
}


@register_enricher("fdot_parcels")
def enrich_fdot_parcels(entity: Entity, db: Session) -> bool:
    """Look up statewide parcel data from FDOT/DOR via ArcGIS."""
    if not entity.latitude or not entity.longitude:
        return False

    raw = _query_fdot_parcel(entity.latitude, entity.longitude)
    if not raw:
        return False

    # Extract and normalize fields
    updates: dict = {}

    # Owner
    owner = raw.get("OWN_NAME")
    if owner and isinstance(owner, str) and len(owner) > 2:
        updates["dor_owner"] = owner.strip()
        owner_addr_parts = [
            raw.get("OWN_ADDR1", ""),
            raw.get("OWN_ADDR2", ""),
            raw.get("OWN_CITY", ""),
            raw.get("OWN_STATE", ""),
            raw.get("OWN_ZIPCD", ""),
        ]
        updates["dor_owner_address"] = ", ".join(p.strip() for p in owner_addr_parts if p and p.strip())

    # Parcel ID
    parcel = raw.get("PARCELNO")
    if parcel:
        updates["dor_parcel_id"] = str(parcel).strip()

    # DOR use code
    use_code = raw.get("DOR_UC")
    if use_code:
        updates["dor_use_code"] = str(use_code).strip()

    # Values
    jv = raw.get("JV")  # Just/market value
    if jv and isinstance(jv, (int, float)) and jv > 0:
        updates["dor_market_value"] = int(jv)
        # Replacement cost estimate: 1.3x market value for FL condos
        replacement = round(jv * 1.3, -3)
        # Only update TIV if we don't have one yet or current is less specific
        chars = entity.characteristics or {}
        if not chars.get("tiv_estimate") or not chars.get("pa_assessed_value"):
            updates["tiv_estimate"] = replacement
            updates["tiv"] = f"${replacement:,.0f}"

    av_bldg = raw.get("AV_BLDG")
    if av_bldg and isinstance(av_bldg, (int, float)):
        updates["dor_building_value"] = int(av_bldg)

    av_land = raw.get("AV_LAND")
    if av_land and isinstance(av_land, (int, float)):
        updates["dor_land_value"] = int(av_land)

    # Year built
    yr = raw.get("YR_BLT")
    if yr and isinstance(yr, (int, float)) and 1900 <= yr <= 2026:
        updates["year_built"] = str(int(yr))
    eff_yr = raw.get("EFF_YR_BLT")
    if eff_yr and isinstance(eff_yr, (int, float)) and 1900 <= eff_yr <= 2026:
        updates["dor_effective_year_built"] = int(eff_yr)

    # Building details
    sqft = raw.get("TOT_LVG_AR")
    if sqft and isinstance(sqft, (int, float)) and sqft > 0:
        updates["dor_living_sqft"] = int(sqft)

    num_buildings = raw.get("NO_BULDNG")
    if num_buildings and isinstance(num_buildings, (int, float)) and num_buildings > 0:
        updates["dor_num_buildings"] = int(num_buildings)

    num_units = raw.get("NO_RES_UNT")
    if num_units and isinstance(num_units, (int, float)) and num_units > 0:
        updates["dor_num_units"] = int(num_units)
        # More authoritative than our estimate
        updates["units_estimate"] = int(num_units)

    # Sale history
    sale_dt = raw.get("SALEDT1")
    if sale_dt:
        updates["dor_last_sale_date"] = str(sale_dt)
    sale_val = raw.get("SALEVAL1")
    if sale_val and isinstance(sale_val, (int, float)) and sale_val > 0:
        updates["dor_last_sale_price"] = int(sale_val)

    # County verification
    co_no = raw.get("CO_NO")
    if co_no:
        county_name = COUNTY_NUMBERS.get(str(co_no).zfill(2))
        if county_name:
            updates["dor_county"] = county_name

    if not updates:
        return False

    update_characteristics(entity, updates, "fdot_parcels")

    fields = [k for k, v in updates.items() if v is not None]
    detail_parts = [f"FDOT/DOR: {len(fields)} fields"]
    if updates.get("dor_market_value"):
        detail_parts.append(f"market=${updates['dor_market_value']:,}")
    if updates.get("dor_num_units"):
        detail_parts.append(f"{updates['dor_num_units']} units")

    record_enrichment(
        entity, db,
        source_id="fdot_parcels",
        fields_updated=fields,
        source_url="https://gis.fdot.gov/arcgis/rest/services/Parcels/FeatureServer",
        detail=", ".join(detail_parts),
    )

    return True
