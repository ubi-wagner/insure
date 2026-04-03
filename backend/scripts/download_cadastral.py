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

    base_dir = os.path.dirname(os.path.dirname(__file__))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d")
    fieldnames = list(all_rows[0].keys())

    # Save combined CSV
    combined_filename = f"fl_coastal_commercial_{timestamp}.csv"
    csv_path = os.path.join(data_dir, combined_filename)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    logger.info(f"Saved combined CSV: {csv_path} ({len(all_rows)} parcels)")

    # Save per-county CSVs in filestore/System Data/DOR/ alongside NAL files
    dor_dir = os.path.join(base_dir, "filestore", "System Data", "DOR")
    os.makedirs(dor_dir, exist_ok=True)
    for county_no, county_name in TARGET_COUNTIES.items():
        county_rows = [r for r in all_rows if str(r.get("co_no")) == county_no]
        if not county_rows:
            continue
        county_file = f"CADASTRAL{county_no}_{timestamp}.csv"
        county_path = os.path.join(dor_dir, county_file)
        with open(county_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(county_rows)
        logger.info(f"  {county_name}: {len(county_rows)} parcels → {county_file}")

    # Also save combined to filestore/System Data/ArcGIS/
    arcgis_dir = os.path.join(base_dir, "filestore", "System Data", "ArcGIS")
    os.makedirs(arcgis_dir, exist_ok=True)
    import shutil
    shutil.copy2(csv_path, os.path.join(arcgis_dir, combined_filename))

    # Upload to S3 for persistence across deploys
    _upload_to_s3(csv_path, f"files/System Data/ArcGIS/{combined_filename}")
    for county_no in TARGET_COUNTIES:
        county_file = f"CADASTRAL{county_no}_{timestamp}.csv"
        county_path = os.path.join(dor_dir, county_file)
        if os.path.exists(county_path):
            _upload_to_s3(county_path, f"files/System Data/DOR/{county_file}")

    return csv_path


def _upload_to_s3(local_path: str, s3_key: str):
    """Upload a file to S3 bucket for persistence."""
    try:
        import boto3
        endpoint = os.getenv("AWS_ENDPOINT_URL_S3") or os.getenv("AWS_ENDPOINT_URL")
        access_key = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        bucket = os.getenv("AWS_S3_BUCKET_NAME") or os.getenv("AWS_BUCKET_NAME") or "default"

        if not all([endpoint, access_key, secret_key]):
            return

        client = boto3.client("s3", endpoint_url=endpoint,
                              aws_access_key_id=access_key,
                              aws_secret_access_key=secret_key,
                              region_name="auto")
        client.upload_file(local_path, bucket, s3_key)
        logger.info(f"Uploaded to S3: {s3_key}")
    except Exception as e:
        logger.warning(f"S3 upload failed for {s3_key}: {e}")


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
