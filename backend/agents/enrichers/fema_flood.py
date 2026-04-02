"""
FEMA Flood Zone Enricher

Uses the FEMA National Flood Hazard Layer (NFHL) REST API to determine
the flood zone for a property based on its coordinates.

API: https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer
- Free, no API key required
- Layer 28 = Flood Hazard Zones (S_FLD_HAZ_AR)
- Returns flood zone designation (A, AE, V, VE, X, etc.)

Flood zones relevant for FL coastal insurance:
- V/VE: Coastal high hazard (velocity wave action) — highest risk
- A/AE: 100-year floodplain — high risk, flood insurance required
- AH/AO: Shallow flooding — moderate-high risk
- X (shaded): 500-year floodplain — moderate risk
- X (unshaded): Minimal flood hazard — low risk
"""

import logging

import httpx
from sqlalchemy.orm import Session

from agents.enrichers import record_enrichment, update_characteristics
from agents.enrichers.pipeline import register_enricher
from database.models import Entity

logger = logging.getLogger(__name__)

NFHL_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"

# Risk classification for insurance scoring
FLOOD_RISK_LEVELS = {
    "VE": {"risk": "extreme", "label": "Coastal High Hazard (VE)", "score_impact": 30},
    "V":  {"risk": "extreme", "label": "Coastal High Hazard (V)", "score_impact": 30},
    "AE": {"risk": "high", "label": "100-Year Floodplain (AE)", "score_impact": 20},
    "A":  {"risk": "high", "label": "100-Year Floodplain (A)", "score_impact": 20},
    "AH": {"risk": "moderate_high", "label": "Shallow Flooding (AH)", "score_impact": 15},
    "AO": {"risk": "moderate_high", "label": "Shallow Flooding (AO)", "score_impact": 15},
    "X":  {"risk": "low", "label": "Minimal Flood Hazard (X)", "score_impact": 0},
}


def _query_nfhl(lat: float, lon: float) -> dict | None:
    """Query FEMA NFHL for flood zone at a given coordinate."""
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,DEPTH,SOURCE_CIT",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": "insure-lead-gen/1.0"}) as client:
            resp = client.get(NFHL_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            features = data.get("features", [])
            if features:
                return features[0].get("attributes", {})
    except Exception as e:
        logger.warning(f"FEMA NFHL query failed for {lat},{lon}: {e}")
    return None


@register_enricher("NEW", "fema_flood")
def enrich_fema_flood(entity: Entity, db: Session) -> bool:
    """Look up FEMA flood zone designation for the property."""
    if not entity.latitude or not entity.longitude:
        return False

    raw = _query_nfhl(entity.latitude, entity.longitude)
    if not raw:
        return False

    flood_zone = raw.get("FLD_ZONE", "")
    zone_subtype = raw.get("ZONE_SUBTY", "")
    is_sfha = raw.get("SFHA_TF", "")  # Special Flood Hazard Area (T/F)
    base_flood_elev = raw.get("STATIC_BFE")
    source_citation = raw.get("SOURCE_CIT", "")

    # Classify risk level
    risk_info = FLOOD_RISK_LEVELS.get(flood_zone, {
        "risk": "unknown",
        "label": f"Zone {flood_zone}" if flood_zone else "Unknown",
        "score_impact": 5,
    })

    # FEMA Flood Map URL for this location
    fema_map_url = (
        f"https://msc.fema.gov/portal/search?AddressQuery="
        f"{entity.latitude}%2C{entity.longitude}"
    )

    updates = {
        "flood_zone": flood_zone,
        "flood_zone_label": risk_info["label"],
        "flood_zone_subtype": zone_subtype if zone_subtype else None,
        "flood_risk": risk_info["risk"],
        "flood_sfha": is_sfha == "T",  # In Special Flood Hazard Area
        "flood_base_elev_ft": base_flood_elev if base_flood_elev and base_flood_elev > 0 else None,
        "flood_score_impact": risk_info["score_impact"],
        "fema_map_url": fema_map_url,
    }

    update_characteristics(entity, updates, "fema_flood")

    fields = [k for k, v in updates.items() if v is not None]
    record_enrichment(
        entity, db,
        source_id="fema_flood",
        fields_updated=fields,
        source_url=fema_map_url,
        detail=f"FEMA NFHL: {risk_info['label']}, SFHA={'Yes' if is_sfha == 'T' else 'No'}",
    )

    return True
