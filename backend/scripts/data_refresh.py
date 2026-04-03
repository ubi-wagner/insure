"""
Automated Data Refresh System

Periodically downloads fresh data from FL state sources:
1. Sunbiz quarterly corporate extract (SFTP — public access)
2. DBPR condo registry CSVs (direct HTTP download)
3. DBPR payment history CSVs (direct HTTP download)
4. ArcGIS Cadastral parcels (REST API query)

Can be triggered manually via POST /api/admin/refresh-data
or scheduled to run weekly/monthly.

All downloaded files are:
- Saved to backend/data/ for enricher access
- Copied to filestore/System Data/{source}/ for file manager visibility
- Uploaded to S3 for persistence across deploys
"""

import csv
import io
import logging
import os
import shutil
import time
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
FILESTORE_DIR = os.path.join(BASE_DIR, "filestore", "System Data")


def _ensure_dirs():
    for sub in ["Sunbiz", "DBPR", "DOR", "ArcGIS"]:
        os.makedirs(os.path.join(FILESTORE_DIR, sub), exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)


def _upload_to_s3(local_path: str, s3_key: str):
    """Upload to S3 for persistence across Railway deploys."""
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
        logger.info(f"S3 upload: {s3_key}")
    except Exception as e:
        logger.warning(f"S3 upload failed for {s3_key}: {e}")


def _download_file(url: str, dest: str, description: str = "") -> bool:
    """Download a file with retry logic. Returns True on success."""
    for attempt in range(3):
        try:
            with httpx.Client(timeout=120, follow_redirects=True) as client:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=1024 * 64):
                            f.write(chunk)
            size = os.path.getsize(dest)
            logger.info(f"Downloaded {description or url}: {size:,} bytes → {os.path.basename(dest)}")
            return True
        except Exception as e:
            logger.warning(f"Download attempt {attempt + 1}/3 failed for {description or url}: {e}")
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    return False


# ─────────────────────────────────────────────────────────
# 1. Sunbiz Quarterly Corporate Extract
# ─────────────────────────────────────────────────────────

# Public SFTP: sftp.floridados.gov  user: Public  pass: PubAccess1845!
# Files are also accessible via HTTPS for the quarterly dumps
SUNBIZ_SFTP_HOST = "sftp.floridados.gov"
SUNBIZ_SFTP_USER = "Public"
SUNBIZ_SFTP_PASS = "PubAccess1845!"


def refresh_sunbiz() -> dict:
    """Download latest Sunbiz quarterly corporate file via SFTP."""
    _ensure_dirs()
    result = {"source": "sunbiz", "status": "pending", "files": []}

    try:
        import paramiko
    except ImportError:
        # Fallback: try the download_sunbiz script which may scrape the page
        logger.warning("paramiko not installed — trying fallback download method")
        try:
            from scripts.download_sunbiz import download_and_process
            path = download_and_process()
            if path:
                result["status"] = "success"
                result["files"].append(os.path.basename(path))
            else:
                result["status"] = "error"
                result["detail"] = "No data downloaded"
        except Exception as e:
            result["status"] = "error"
            result["detail"] = str(e)[:200]
        return result

    try:
        transport = paramiko.Transport((SUNBIZ_SFTP_HOST, 22))
        transport.connect(username=SUNBIZ_SFTP_USER, password=SUNBIZ_SFTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)

        # List available files to find the latest corporate quarterly
        files = sftp.listdir(".")
        logger.info(f"Sunbiz SFTP files: {files[:20]}")

        # Look for quarterly corporate files (typically named like corp_qYYYYQ.txt)
        corp_files = [f for f in files if "corp" in f.lower() and f.lower().endswith((".txt", ".dat", ".zip"))]
        if not corp_files:
            # Try navigating to a subdirectory
            for d in files:
                try:
                    subfiles = sftp.listdir(d)
                    corp_sub = [f"{d}/{f}" for f in subfiles if "corp" in f.lower()]
                    corp_files.extend(corp_sub)
                except Exception:
                    pass

        if not corp_files:
            result["status"] = "error"
            result["detail"] = f"No corporate files found. Available: {files[:10]}"
            sftp.close()
            transport.close()
            return result

        # Download the latest/largest file
        latest = sorted(corp_files)[-1]
        local_path = os.path.join(DATA_DIR, f"sunbiz_quarterly_{datetime.now().strftime('%Y%m%d')}.txt")
        sftp.get(latest, local_path)
        size = os.path.getsize(local_path)
        logger.info(f"Downloaded Sunbiz {latest}: {size:,} bytes")

        sftp.close()
        transport.close()

        # Copy to filestore + S3
        dest = os.path.join(FILESTORE_DIR, "Sunbiz", os.path.basename(local_path))
        shutil.copy2(local_path, dest)
        _upload_to_s3(local_path, f"files/System Data/Sunbiz/{os.path.basename(local_path)}")

        # Now filter and parse using the download_sunbiz script
        try:
            from scripts.download_sunbiz import parse_and_filter_file
            csv_path = parse_and_filter_file(local_path)
            if csv_path:
                result["files"].append(os.path.basename(csv_path))
        except Exception as e:
            logger.warning(f"Sunbiz parsing failed: {e}")

        result["status"] = "success"
        result["files"].append(os.path.basename(local_path))
        result["size"] = size

    except Exception as e:
        logger.error(f"Sunbiz SFTP download failed: {e}")
        result["status"] = "error"
        result["detail"] = str(e)[:200]

    return result


# ─────────────────────────────────────────────────────────
# 2. DBPR Condo Registry CSVs
# ─────────────────────────────────────────────────────────

DBPR_CSV_URLS = {
    "Condo_CW.csv": "https://www2.myfloridalicense.com/sto/file_download/extracts/Condo_CW.csv",
    "Condo_MD.csv": "https://www2.myfloridalicense.com/sto/file_download/extracts/Condo_MD.csv",
    "condo_CE.csv": "https://www2.myfloridalicense.com/sto/file_download/extracts/condo_CE.csv",
    "Condo_NF.csv": "https://www2.myfloridalicense.com/sto/file_download/extracts/Condo_NF.csv",
    "condo_conv.csv": "https://www2.myfloridalicense.com/sto/file_download/extracts/condo_conv.csv",
    "coopmailing.csv": "https://www2.myfloridalicense.com/sto/file_download/extracts/coopmailing.csv",
}

DBPR_PAYMENT_URLS = {
    "paymenthist_8002A.csv": "https://www2.myfloridalicense.com/sto/file_download/extracts/paymenthist_8002A.csv",
    "paymenthist_8002D.csv": "https://www2.myfloridalicense.com/sto/file_download/extracts/paymenthist_8002D.csv",
    "paymenthist_8002J.csv": "https://www2.myfloridalicense.com/sto/file_download/extracts/paymenthist_8002J.csv",
    "paymenthist_8002P.csv": "https://www2.myfloridalicense.com/sto/file_download/extracts/paymenthist_8002P.csv",
    "paymenthist_8002S.csv": "https://www2.myfloridalicense.com/sto/file_download/extracts/paymenthist_8002S.csv",
}


def refresh_dbpr() -> dict:
    """Download latest DBPR condo registry and payment history CSVs."""
    _ensure_dirs()
    result = {"source": "dbpr", "status": "pending", "files": [], "failed": []}

    # Condo registry files
    for filename, url in DBPR_CSV_URLS.items():
        dest = os.path.join(DATA_DIR, filename)
        if _download_file(url, dest, f"DBPR {filename}"):
            # Copy to filestore
            shutil.copy2(dest, os.path.join(FILESTORE_DIR, "DBPR", filename))
            _upload_to_s3(dest, f"files/System Data/DBPR/{filename}")
            result["files"].append(filename)
        else:
            result["failed"].append(filename)
        time.sleep(1)  # Rate limit

    # Payment history files
    for filename, url in DBPR_PAYMENT_URLS.items():
        dest = os.path.join(DATA_DIR, filename)
        if _download_file(url, dest, f"DBPR {filename}"):
            shutil.copy2(dest, os.path.join(FILESTORE_DIR, "DBPR", filename))
            _upload_to_s3(dest, f"files/System Data/DBPR/{filename}")
            result["files"].append(filename)
        else:
            result["failed"].append(filename)
        time.sleep(1)

    result["status"] = "success" if result["files"] else "error"
    if result["failed"]:
        result["detail"] = f"{len(result['failed'])} files failed: {', '.join(result['failed'])}"
    return result


# ─────────────────────────────────────────────────────────
# 3. ArcGIS Cadastral Parcels
# ─────────────────────────────────────────────────────────

def refresh_cadastral() -> dict:
    """Download commercial parcels from ArcGIS Cadastral FeatureServer."""
    try:
        from scripts.download_cadastral import download_all_counties
        path = download_all_counties()
        if path:
            return {"source": "cadastral", "status": "success", "files": [os.path.basename(path)]}
        return {"source": "cadastral", "status": "error", "detail": "No parcels downloaded"}
    except Exception as e:
        return {"source": "cadastral", "status": "error", "detail": str(e)[:200]}


# ─────────────────────────────────────────────────────────
# Master Refresh
# ─────────────────────────────────────────────────────────

def refresh_all() -> dict:
    """Run all data refreshes. Returns summary of results."""
    logger.info("Starting full data refresh...")
    results = {}

    # DBPR first (fastest, most reliable)
    logger.info("Refreshing DBPR data...")
    results["dbpr"] = refresh_dbpr()

    # Sunbiz (may need paramiko)
    logger.info("Refreshing Sunbiz data...")
    results["sunbiz"] = refresh_sunbiz()

    # Cadastral (slowest — queries ArcGIS for each county)
    logger.info("Refreshing ArcGIS Cadastral data...")
    results["cadastral"] = refresh_cadastral()

    total_files = sum(len(r.get("files", [])) for r in results.values())
    total_failed = sum(len(r.get("failed", [])) for r in results.values())

    logger.info(f"Data refresh complete: {total_files} files downloaded, {total_failed} failed")
    return {
        "timestamp": datetime.now().isoformat(),
        "total_files": total_files,
        "total_failed": total_failed,
        "sources": results,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    results = refresh_all()
    print(f"\nData Refresh Complete")
    print(f"  Files downloaded: {results['total_files']}")
    print(f"  Files failed: {results['total_failed']}")
    for src, r in results["sources"].items():
        status = r["status"]
        files = ", ".join(r.get("files", []))
        print(f"  {src}: {status} — {files or r.get('detail', 'no files')}")
