"""
Automated Data Refresh System

Periodically downloads fresh data from FL state sources:
1. DOR NAL tax roll files (direct HTTP from data portal)
2. DOR SDF sale files (direct HTTP from data portal)
3. DBPR condo registry CSVs (direct HTTP download)
4. DBPR payment history CSVs (direct HTTP download)
5. Sunbiz quarterly corporate extract (SFTP — public access)
6. ArcGIS Cadastral parcels (REST API query)

Can be triggered manually via POST /api/admin/refresh-data
or automatically via timebomb events (scheduled triggers).

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


# ─────────────────────────────────────────────────────────
# 0. DOR NAL + SDF Tax Roll Files
# ─────────────────────────────────────────────────────────

# Direct download URLs from FL DOR Data Portal
# Pattern: floridarevenue.com/property/dataportal/Documents/PTO Data Portal/
#          Tax Roll Data Files/NAL/{year}F/{CountyName} {code} Final NAL {year}.zip
DOR_BASE = "https://floridarevenue.com/property/dataportal/Documents/PTO%20Data%20Portal/Tax%20Roll%20Data%20Files"

# County list now lives in agents.seeder.DOR_COUNTIES (35 coastal counties)
# and is imported lazily inside refresh_dor_nal() to avoid a circular import.

# Current tax roll year
DOR_YEAR = "2025"


def _try_nal_url(county_name: str, county_no: str, year: str, roll_type: str = "NAL") -> str | None:
    """Try multiple URL patterns for DOR data files.

    FL DOR uses inconsistent naming: sometimes spaces, sometimes %20,
    sometimes 'Final', sometimes 'Prelim', sometimes just the county name.
    """
    encoded_name = county_name.replace(" ", "%20").replace("-", "-")
    # URL patterns to try (most common first)
    patterns = [
        f"{DOR_BASE}/{roll_type}/{year}F/{encoded_name}%20{county_no}%20Final%20{roll_type}%20{year}.zip",
        f"{DOR_BASE}/{roll_type}/{year}F/{encoded_name}+{county_no}+Final+{roll_type}+{year}.zip",
        f"{DOR_BASE}/{roll_type}/{year}P/{encoded_name}%20{county_no}%20Prelim%20{roll_type}%20{year}.zip",
    ]

    for url in patterns:
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.head(url)
                if resp.status_code == 200:
                    return url
        except Exception:
            pass
    return None


def refresh_dor_nal() -> dict:
    """Download DOR NAL + SDF files for all configured coastal counties.

    Pulls the county list from seeder.DOR_COUNTIES so this stays in sync
    with the rest of the pipeline (35 coastal counties as of expansion).
    After download, triggers the auto-seed scanner so any newly complete
    NAL+SDF pairs immediately start seeding.
    """
    import zipfile
    from agents.seeder import DOR_COUNTIES, scan_dor_dir_and_auto_seed

    _ensure_dirs()
    result = {"source": "dor_nal", "status": "pending", "files": [], "failed": []}
    dor_dir = os.path.join(FILESTORE_DIR, "DOR")

    for county_no, county_name in DOR_COUNTIES.items():
        for roll_type in ["NAL", "SDF"]:
            # Check if we already have this file
            existing = [f for f in os.listdir(dor_dir)
                        if f.upper().startswith(f"{roll_type}{county_no}") and f.endswith(".csv")]
            if existing:
                logger.debug(f"Already have {roll_type} for {county_name}: {existing[0]}")
                continue

            url = _try_nal_url(county_name, county_no, DOR_YEAR, roll_type)
            if not url:
                logger.info(f"No {roll_type} URL found for {county_name} ({county_no})")
                result["failed"].append(f"{roll_type}{county_no}")
                continue

            # Download zip
            zip_path = os.path.join(DATA_DIR, f"{roll_type}{county_no}_{DOR_YEAR}.zip")
            if _download_file(url, zip_path, f"DOR {roll_type} {county_name}"):
                # Extract CSV from zip
                try:
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        csv_files = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                        if csv_files:
                            extracted = zf.extract(csv_files[0], DATA_DIR)
                            # Rename to standard format
                            standard_name = f"{roll_type}{county_no}F{DOR_YEAR}01.csv"
                            final_path = os.path.join(DATA_DIR, standard_name)
                            if os.path.exists(final_path):
                                os.remove(final_path)
                            os.rename(extracted, final_path)

                            # Copy to filestore + S3
                            shutil.copy2(final_path, os.path.join(dor_dir, standard_name))
                            _upload_to_s3(final_path, f"files/System Data/DOR/{standard_name}")
                            result["files"].append(standard_name)
                            logger.info(f"  Extracted {standard_name} ({os.path.getsize(final_path):,} bytes)")
                        else:
                            logger.warning(f"No CSV in zip for {roll_type} {county_name}")
                            result["failed"].append(f"{roll_type}{county_no}")
                except zipfile.BadZipFile:
                    logger.error(f"Bad zip file for {roll_type} {county_name}")
                    result["failed"].append(f"{roll_type}{county_no}")
                finally:
                    # Clean up zip
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
            else:
                result["failed"].append(f"{roll_type}{county_no}")

            time.sleep(1)  # Rate limit

    result["status"] = "success" if result["files"] else ("partial" if result["failed"] else "success")

    # Auto-seed any county that now has both NAL and SDF.
    # The scanner is idempotent — counties already seeded with the same
    # file mtime are skipped.
    if result["files"]:
        try:
            seed_result = scan_dor_dir_and_auto_seed()
            result["auto_seed"] = seed_result
            if seed_result.get("triggered"):
                triggered_names = ", ".join(t["county"] for t in seed_result["triggered"])
                logger.info(f"Auto-seed triggered after DOR refresh: {triggered_names}")
        except Exception as e:
            logger.warning(f"Auto-seed scan failed after DOR refresh: {e}")
            result["auto_seed_error"] = str(e)[:200]

    return result


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

    # DOR NAL + SDF files
    logger.info("Refreshing DOR NAL/SDF data...")
    results["dor_nal"] = refresh_dor_nal()

    # DBPR (fastest, most reliable)
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
