"""
Florida Statewide Cadastral Parcel Downloader

Downloads commercial multi-tenant parcels from the ArcGIS Florida Statewide
Cadastral FeatureServer (DOR + NAL joined data with geometry).

Filters:
  - DOR_UC in (004, 005, 006, 008, 039) — condos, co-ops, retirement, multi-family, hotels
  - JV >= 10,000,000 ($10M+ market value)
  - Within 10 miles of Florida coastline (using county-based coastal filter)

Output: CSV saved to backend/data/fl_coastal_commercial_parcels.csv
        Also uploads to filestore/System Data/ArcGIS/ for the file manager

Usage:
  python -m scripts.download_cadastral
  # Or from the admin API: POST /api/admin/download-cadastral
"""

import csv
import io
import json
import logging
import os
import time
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

# ArcGIS REST endpoint — Florida Statewide Cadastral (2025)
# Source: https://www.arcgis.com/home/item.html?id=efa909d6b1c841d298b0a649e7f71cf2
ARCGIS_URL = "https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/Florida_Statewide_Cadastral/FeatureServer/0/query"

# Max records per request (ArcGIS limit)
PAGE_SIZE = 2000

# Our 11 target counties (DOR county numbers) — all coastal
TARGET_COUNTIES = {
    "16": "Broward",
    "18": "Charlotte",
    "21": "Collier",
    "23": "Miami-Dade",
    "39": "Hillsborough",
    "46": "Lee",
    "51": "Manatee",
    "60": "Palm Beach",
    "61": "Pasco",
    "62": "Pinellas",
    "68": "Sarasota",
}

# DOR use codes for commercial multi-tenant
TARGET_USE_CODES = ["004", "005", "006", "008", "039"]

# Minimum market value
MIN_JV = 10_000_000

# Fields to request from ArcGIS
OUT_FIELDS = [
    "CO_NO", "PARCEL_ID", "DOR_UC", "PA_UC",
    "JV", "AV_SD", "TV_SD",
    "OWN_NAME", "OWN_ADDR1", "OWN_ADDR2", "OWN_CITY", "OWN_STATE", "OWN_ZIPCD",
    "PHY_ADDR1", "PHY_ADDR2", "PHY_CITY", "PHY_ZIPCD",
    "NO_RES_UNTS", "NO_BULDNG", "TOT_LVG_AREA", "LND_SQFOOT",
    "ACT_YR_BLT", "EFF_YR_BLT",
    "CONST_CLASS", "IMP_QUAL",
    "SALE_PRC1", "SALE_YR1", "SALE_MO1",
    "SPEC_FEAT_VAL", "LND_VAL",
]


def _build_where_clause(county_no: str) -> str:
    """Build SQL WHERE clause for ArcGIS query."""
    use_codes = ",".join(f"'{c}'" for c in TARGET_USE_CODES)
    return (
        f"CO_NO = '{county_no}' "
        f"AND DOR_UC IN ({use_codes}) "
        f"AND JV >= {MIN_JV}"
    )


def _query_arcgis(where: str, offset: int = 0) -> dict:
    """Execute one paged query against the ArcGIS Feature Service."""
    params = {
        "where": where,
        "outFields": ",".join(OUT_FIELDS),
        "returnGeometry": "true",
        "geometryPrecision": 6,
        "outSR": "4326",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
        "f": "json",
    }

    for attempt in range(3):
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.get(ARCGIS_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

                if "error" in data:
                    logger.error(f"ArcGIS error: {data['error']}")
                    return {"features": []}

                return data
        except Exception as e:
            logger.warning(f"ArcGIS query attempt {attempt + 1}/3 failed: {e}")
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))

    return {"features": []}


def _extract_centroid(geometry: dict) -> tuple[float | None, float | None]:
    """Extract centroid from ArcGIS polygon geometry (rings)."""
    rings = geometry.get("rings", [])
    if not rings:
        return None, None

    # Use the first ring's average point as centroid
    ring = rings[0]
    if not ring:
        return None, None

    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return round(sum(lats) / len(lats), 6), round(sum(lons) / len(lons), 6)


def download_county(county_no: str) -> list[dict]:
    """Download all matching parcels for one county."""
    county_name = TARGET_COUNTIES.get(county_no, f"County {county_no}")
    where = _build_where_clause(county_no)
    all_features = []
    offset = 0

    logger.info(f"Downloading {county_name} (CO_NO={county_no})...")

    while True:
        data = _query_arcgis(where, offset)
        features = data.get("features", [])

        if not features:
            break

        all_features.extend(features)
        logger.info(f"  {county_name}: {len(all_features)} parcels so far...")

        if len(features) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        time.sleep(0.5)  # Rate limit

    logger.info(f"  {county_name}: {len(all_features)} total parcels >= $10M")
    return all_features


def download_all_counties() -> str:
    """Download parcels from all target counties and save as CSV.

    Returns path to the saved CSV file.
    """
    all_rows = []

    for county_no, county_name in TARGET_COUNTIES.items():
        try:
            features = download_county(county_no)
            for feat in features:
                attrs = feat.get("attributes", {})
                geom = feat.get("geometry", {})
                lat, lon = _extract_centroid(geom)

                row = {
                    "county_name": county_name,
                    "latitude": lat,
                    "longitude": lon,
                }
                for field in OUT_FIELDS:
                    row[field.lower()] = attrs.get(field)

                # Compute TIV estimate
                jv = attrs.get("JV")
                if jv and isinstance(jv, (int, float)) and jv > 0:
                    row["tiv_estimate"] = round(jv * 1.3, -3)

                all_rows.append(row)
        except Exception as e:
            logger.error(f"Failed to download {county_name}: {e}")

    logger.info(f"Total: {len(all_rows)} parcels across {len(TARGET_COUNTIES)} counties")

    if not all_rows:
        logger.warning("No parcels downloaded!")
        return ""

    # Save to CSV
    base_dir = os.path.dirname(os.path.dirname(__file__))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"fl_coastal_commercial_{timestamp}.csv"
    csv_path = os.path.join(data_dir, filename)

    fieldnames = list(all_rows[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info(f"Saved {len(all_rows)} parcels to {csv_path}")

    # Also save to filestore for file manager access
    filestore_dir = os.path.join(base_dir, "filestore", "System Data", "ArcGIS")
    os.makedirs(filestore_dir, exist_ok=True)
    filestore_path = os.path.join(filestore_dir, filename)

    import shutil
    shutil.copy2(csv_path, filestore_path)
    logger.info(f"Copied to filestore: {filestore_path}")

    return csv_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    path = download_all_counties()
    if path:
        print(f"\nDone! CSV saved to: {path}")

        # Quick stats
        with open(path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        print(f"Total parcels: {len(rows)}")
        for county in sorted(set(r["county_name"] for r in rows)):
            count = sum(1 for r in rows if r["county_name"] == county)
            print(f"  {county}: {count}")
    else:
        print("No parcels downloaded.")
