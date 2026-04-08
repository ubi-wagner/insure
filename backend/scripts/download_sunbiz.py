"""
Florida Sunbiz Bulk Corporate Data Downloader

Downloads quarterly bulk data files from the FL Division of Corporations,
parses the fixed-length ASCII format (1440 chars/record), and filters for
condo/HOA/association-type corporations.

Data source:
  https://dos.fl.gov/sunbiz/other-services/data-downloads/quarterly-data/

File format reference:
  https://dos.fl.gov/sunbiz/other-services/data-downloads/corporate-data-file/

Output: backend/data/sunbiz_corps.csv + filestore/System Data/Sunbiz/

Usage:
  python -m scripts.download_sunbiz
  python -m scripts.download_sunbiz --dry-run
  # Or from admin API: POST /api/admin/download-sunbiz
"""

import argparse
import csv
import io
import logging
import os
import re
import sys
import zipfile
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

# ─── Configuration ───

SUNBIZ_QUARTERLY_URL = "https://dos.fl.gov/sunbiz/other-services/data-downloads/quarterly-data/"

# Record is 1440 characters fixed-width ASCII.
# Field positions from FL DoS Corporate File Definitions (official spec).
# Positions in the spec are 1-indexed; Python slices are 0-indexed.
RECORD_LENGTH = 1440

FIELD_MAP = {
    # Core identification (fields 1-3)
    "document_number":    (0, 12),       # Field 1: Corporation Number, len 12
    "corp_name":          (12, 204),     # Field 2: Corporation Name, len 192
    "status_code":        (204, 205),    # Field 3: Status, 1 char "A"/"I"
    # Filing type (field 4)
    "filing_type":        (205, 220),    # Field 4: Filing Type, len 15 (DOMP, DOMNP, etc.)
    # Principal address (fields 5-10)
    "principal_address1": (220, 262),    # Field 5: Address 1, len 42
    "principal_address2": (262, 304),    # Field 6: Address 2, len 42
    "principal_city":     (304, 332),    # Field 7: City, len 28
    "principal_state":    (332, 334),    # Field 8: State, len 2
    "principal_zip":      (334, 344),    # Field 9: Zip, len 10
    "principal_country":  (344, 346),    # Field 10: Country, len 2
    # Mailing address (fields 11-16)
    "mailing_address1":   (346, 388),    # Field 11: Mail Address 1, len 42
    "mailing_address2":   (388, 430),    # Field 12: Mail Address 2, len 42
    "mailing_city":       (430, 458),    # Field 13: Mail City, len 28
    "mailing_state":      (458, 460),    # Field 14: Mail State, len 2
    "mailing_zip":        (460, 470),    # Field 15: Mail Zip, len 10
    "mailing_country":    (470, 472),    # Field 16: Mail Country, len 2
    # Filing dates and FEI (fields 17-20)
    "file_date":          (472, 480),    # Field 17: File Date, len 8 (formation date)
    "fei_number":         (480, 494),    # Field 18: FEI Number, len 14
    "more_than_six_off":  (494, 495),    # Field 19: More-than-6-officers flag, 1 char Y/blank
    "last_txn_date":      (495, 503),    # Field 20: Last Transaction Date, len 8
    "state_country":      (503, 505),    # Field 21: State Country, len 2
    # Annual report history (fields 22-30)
    "report_year_1":      (505, 509),    # Field 22, len 4
    # Field 23 filler (509, 510) skipped
    "report_date_1":      (510, 518),    # Field 24, len 8
    "report_year_2":      (518, 522),    # Field 25, len 4
    # Field 26 filler (522, 523) skipped
    "report_date_2":      (523, 531),    # Field 27, len 8
    "report_year_3":      (531, 535),    # Field 28, len 4
    # Field 29 filler (535, 536) skipped
    "report_date_3":      (536, 544),    # Field 30, len 8
    # Registered agent (fields 31-36)
    "registered_agent":   (544, 586),    # Field 31: RA Name, len 42
    "ra_type":            (586, 587),    # Field 32: RA Type, 1 char P/C
    "ra_street":          (587, 629),    # Field 33: RA Address, len 42
    "ra_city":            (629, 657),    # Field 34: RA City, len 28
    "ra_state":           (657, 659),    # Field 35: RA State, len 2
    "ra_zip":             (659, 668),    # Field 36: RA Zip+4, len 9
}

# Filing type codes (Field 4) — useful for filtering condo associations
FILING_TYPE_CODES = {
    "DOMP":  "Domestic Profit",
    "DOMNP": "Domestic Non-Profit",      # Most condo associations
    "FORP":  "Foreign Profit",
    "FORNP": "Foreign Non-Profit",
    "DOMLP": "Domestic Limited Partnership",
    "FORLP": "Foreign Limited Partnership",
    "FLAL":  "Florida LLC",
    "FORL":  "Foreign LLC",
    "NPREG": "Non-Profit Registration",
    "TRUST": "Declaration of Trust",
    "AGENT": "Designation of Registered Agent",
}

# Officer title codes (Officer Title field, fields 37/44/51/58/65/72)
OFFICER_TITLE_CODES = {
    "P": "President",
    "T": "Treasurer",
    "C": "Chairman",
    "V": "Vice President",
    "S": "Secretary",
    "D": "Director",
}

# Officers (fields 37-78): 6 officer blocks each 128 chars wide
# Officer 1 starts at position 669 (Python index 668), ends at 796.
# Officer 2 starts at 797, etc. (797 - 669 = 128 chars per block)
OFFICER_START = 668
OFFICER_BLOCK_SIZE = 128
OFFICER_FIELDS = {
    "title":   (0, 4),       # Officer N Title, 4 chars
    "type":    (4, 5),       # Officer N Type, 1 char (P=Person, C=Corp)
    "name":    (5, 47),      # Officer N Name, 42 chars
    "address": (47, 89),     # Officer N Address, 42 chars
    "city":    (89, 117),    # Officer N City, 28 chars
    "state":   (117, 119),   # Officer N State, 2 chars
    "zip":     (119, 128),   # Officer N Zip+4, 9 chars
}
MAX_OFFICERS = 6

# Keywords that identify relevant associations (condo, HOA, etc.)
ASSOCIATION_KEYWORDS = [
    "CONDO", "CONDOMINIUM", "COOPERATIVE", "CO-OP", "COOP",
    "HOA", "HOMEOWNER", "HOME OWNER", "HOMEOWNERS",
    "ASSOCIATION", "ASSOC", "ASSN",
    "VILLAS", "TOWERS", "ESTATES", "CLUB", "MANOR",
    "TERRACE", "PLAZA", "GARDENS", "LANDING", "POINTE",
    "SHORES", "BEACH", "BAY", "HARBOUR", "HARBOR",
    "LAKE", "ISLE", "RETREAT", "PRESERVE", "COMMONS",
    "CROSSING", "RIDGE", "VILLAGE", "RESIDENCES",
    "APARTMENTS", "PROPERTY OWNERS",
]

# Status codes — Corporate File spec confirms field 3 is 1 char: "A" or "I"
STATUS_CODES = {
    "A": "Active",
    "I": "Inactive",
    # Older 2-char codes left in for backward compat with previously-parsed files
    "AA": "Active",
    "IA": "Inactive",
    "AD": "Admin Dissolved",
    "VD": "Voluntarily Dissolved",
    "RS": "Revoked",
    "WD": "Withdrawn",
}

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
FILESTORE_DIR = os.path.join(BASE_DIR, "filestore", "System Data", "Sunbiz")


# ─── Parsing ───

def _clean(value: str) -> str:
    """Strip whitespace and null characters from a fixed-width field."""
    return value.strip().strip("\x00").strip()


def parse_record(line: str) -> dict | None:
    """Parse a single 1440-char fixed-width record into a dict."""
    if len(line) < RECORD_LENGTH:
        return None

    record = {}
    for field, (start, end) in FIELD_MAP.items():
        record[field] = _clean(line[start:end])

    # Parse officers
    officers = []
    for i in range(MAX_OFFICERS):
        offset = OFFICER_START + (i * OFFICER_BLOCK_SIZE)
        if offset + OFFICER_BLOCK_SIZE > len(line):
            break
        block = line[offset:offset + OFFICER_BLOCK_SIZE]
        officer = {}
        for field, (start, end) in OFFICER_FIELDS.items():
            officer[field] = _clean(block[start:end])
        # Only include if officer has a name
        if officer["name"]:
            officers.append(officer)
    record["officers"] = officers

    # Build composite address strings
    addr_parts = [
        record.get("principal_address1", ""),
        record.get("principal_address2", ""),
        record.get("principal_city", ""),
        record.get("principal_state", ""),
        record.get("principal_zip", ""),
    ]
    record["principal_address"] = ", ".join(p for p in addr_parts if p)

    mail_parts = [
        record.get("mailing_address1", ""),
        record.get("mailing_address2", ""),
        record.get("mailing_city", ""),
        record.get("mailing_state", ""),
        record.get("mailing_zip", ""),
    ]
    record["mailing_address"] = ", ".join(p for p in mail_parts if p)

    ra_parts = [
        record.get("ra_street", ""),
        record.get("ra_city", ""),
        record.get("ra_state", ""),
        record.get("ra_zip", ""),
    ]
    record["ra_address"] = ", ".join(p for p in ra_parts if p)

    # Decode filing type
    filing_type_code = record.get("filing_type", "").strip()
    record["filing_type_label"] = FILING_TYPE_CODES.get(filing_type_code, filing_type_code)

    # Decode officer titles
    for officer in record.get("officers", []):
        title_code = officer.get("title", "").strip()
        officer["title_label"] = OFFICER_TITLE_CODES.get(title_code, title_code)

    # Decode status
    record["status"] = STATUS_CODES.get(record["status_code"], record["status_code"])

    # Format file date from MMDDYYYY (per spec field 17) into MM/DD/YYYY display
    fd = record.get("file_date", "")
    if len(fd) == 8 and fd.isdigit():
        record["filing_date_formatted"] = f"{fd[:2]}/{fd[2:4]}/{fd[4:]}"
    else:
        record["filing_date_formatted"] = fd

    return record


def is_relevant_corp(corp_name: str) -> bool:
    """Check if a corporation name matches our association/condo keywords."""
    upper = corp_name.upper()
    return any(kw in upper for kw in ASSOCIATION_KEYWORDS)


# ─── SFTP Download (primary method — FL DoS blocks HTTP scraping) ───

SFTP_HOST = "sftp.floridados.gov"
SFTP_USER = "Public"
SFTP_PASS = "PubAccess1845!"
SFTP_DIR = "/Quarterly"  # Adjust based on actual directory structure


def download_via_sftp(dest_dir: str) -> str | None:
    """Download the latest quarterly corporate data file via SFTP.

    The FL Division of Corporations provides public SFTP access at
    sftp.floridados.gov (user: Public, pass: PubAccess1845!).
    """
    try:
        import paramiko
    except ImportError:
        logger.warning("paramiko not installed — cannot use SFTP. pip install paramiko")
        return None

    os.makedirs(dest_dir, exist_ok=True)

    try:
        transport = paramiko.Transport((SFTP_HOST, 22))
        transport.connect(username=SFTP_USER, password=SFTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)

        # List directories to find the data
        logger.info(f"Connected to SFTP {SFTP_HOST}, listing directories...")
        root_items = sftp.listdir("/")
        logger.info(f"Root directories: {root_items[:20]}")

        # Search for quarterly corporate data files
        # Try common paths: /Quarterly, /Corp, /Data, root level
        search_dirs = ["/", "/Quarterly", "/Corp", "/Data", "/Corporate"]
        data_file = None
        data_path = None

        for search_dir in search_dirs:
            try:
                items = sftp.listdir(search_dir)
                logger.info(f"  {search_dir}: {items[:15]}")

                # Look for corporate data files — typically named corp*.dat, corp*.txt, or *.zip
                candidates = [f for f in items
                              if any(f.lower().startswith(p) for p in ["corp", "quarterly"])
                              or f.lower().endswith((".dat", ".zip", ".txt", ".Z"))]

                if candidates:
                    # Pick the newest / largest file
                    best = None
                    best_size = 0
                    for c in candidates:
                        try:
                            full_path = f"{search_dir.rstrip('/')}/{c}"
                            stat = sftp.stat(full_path)
                            if stat.st_size and stat.st_size > best_size:
                                best = full_path
                                best_size = stat.st_size
                        except Exception:
                            continue

                    if best:
                        data_file = best
                        data_path = os.path.join(dest_dir, os.path.basename(best))
                        break
            except IOError:
                continue

        if not data_file:
            logger.warning("Could not find corporate data file on SFTP server")
            sftp.close()
            transport.close()
            return None

        logger.info(f"Downloading via SFTP: {data_file} ...")
        sftp.get(data_file, data_path)
        file_size = os.path.getsize(data_path)
        logger.info(f"Downloaded {file_size:,} bytes to {data_path}")

        sftp.close()
        transport.close()

        # Extract if zip
        if data_path.lower().endswith(".zip"):
            logger.info("Extracting zip file...")
            with zipfile.ZipFile(data_path, "r") as zf:
                data_files = [n for n in zf.namelist()
                              if not n.startswith("__") and not n.startswith(".")]
                if data_files:
                    largest = max(data_files, key=lambda n: zf.getinfo(n).file_size)
                    extract_path = os.path.join(dest_dir, largest)
                    zf.extract(largest, dest_dir)
                    logger.info(f"Extracted: {largest}")
                    return extract_path

        return data_path

    except Exception as e:
        logger.error(f"SFTP download failed: {e}")
        return None


# ─── HTTP Download (fallback — FL DoS often blocks automated HTTP) ───

def _find_download_url() -> str | None:
    """Scrape the Sunbiz quarterly data page to find the latest download link."""
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(SUNBIZ_QUARTERLY_URL)
            resp.raise_for_status()
            text = resp.text

            # Look for links to .zip or .Z or direct data file links
            # Typical patterns: corpXXXX.zip, corp_data_YYYY_QN.zip, etc.
            patterns = [
                r'href="([^"]*corp[^"]*\.zip)"',
                r'href="([^"]*corp[^"]*\.Z)"',
                r'href="([^"]*quarterly[^"]*\.zip)"',
                r'href="([^"]*data[^"]*\.zip)"',
                r"href='([^']*corp[^']*\.zip)'",
            ]

            urls = []
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                urls.extend(matches)

            if not urls:
                # Try any download link on the page
                all_links = re.findall(r'href="([^"]+\.(?:zip|Z|txt|dat))"', text, re.IGNORECASE)
                urls = [u for u in all_links if "corp" in u.lower() or "data" in u.lower()]

            if urls:
                url = urls[0]
                # Make absolute if relative
                if url.startswith("/"):
                    url = f"https://dos.fl.gov{url}"
                elif not url.startswith("http"):
                    url = f"https://dos.fl.gov/sunbiz/other-services/data-downloads/quarterly-data/{url}"
                logger.info(f"Found Sunbiz quarterly download URL: {url}")
                return url

            logger.warning("Could not find download URL on Sunbiz quarterly page. "
                           "Page may have changed layout. Check manually: %s", SUNBIZ_QUARTERLY_URL)
            return None

    except Exception as e:
        logger.error(f"Failed to scrape Sunbiz quarterly page: {e}")
        return None


def download_file(url: str, dest_dir: str) -> str | None:
    """Download a file from URL, handling zip extraction. Returns path to data file."""
    os.makedirs(dest_dir, exist_ok=True)
    filename = url.split("/")[-1].split("?")[0]
    download_path = os.path.join(dest_dir, filename)

    logger.info(f"Downloading Sunbiz data from {url} ...")

    try:
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0

                with open(download_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and downloaded % (50 * 1024 * 1024) == 0:
                            pct = downloaded / total * 100
                            logger.info(f"  Download progress: {pct:.0f}% ({downloaded:,} / {total:,} bytes)")

        logger.info(f"Downloaded {downloaded:,} bytes to {download_path}")

        # Extract if zip
        if download_path.lower().endswith(".zip"):
            logger.info("Extracting zip file...")
            with zipfile.ZipFile(download_path, "r") as zf:
                data_files = [n for n in zf.namelist()
                              if not n.startswith("__") and not n.startswith(".")]
                if not data_files:
                    logger.error("Zip file contains no data files")
                    return None
                # Extract the largest file (the actual data)
                largest = max(data_files, key=lambda n: zf.getinfo(n).file_size)
                extract_path = os.path.join(dest_dir, largest)
                zf.extract(largest, dest_dir)
                logger.info(f"Extracted: {largest} ({zf.getinfo(largest).file_size:,} bytes)")
                return extract_path

        return download_path

    except Exception as e:
        logger.error(f"Download failed: {e}")
        return None


def parse_and_filter(data_path: str, dry_run: bool = False) -> list[dict]:
    """Parse the fixed-width data file and filter for relevant associations.

    Returns list of parsed records matching our keywords.
    """
    matches = []
    total_records = 0
    skipped_short = 0

    logger.info(f"Parsing {data_path} ...")

    try:
        # Try multiple encodings — FL DoS files are typically ASCII or Latin-1
        for encoding in ["ascii", "latin-1", "utf-8", "cp1252"]:
            try:
                with open(data_path, "r", encoding=encoding, errors="replace") as f:
                    # Log first record for debugging field positions
                    first_line = f.readline()
                    if first_line:
                        logger.info(f"File encoding: {encoding}, first record length: {len(first_line.rstrip())}")
                        _log_sample_record(first_line.rstrip())
                        f.seek(0)
                    break
            except UnicodeDecodeError:
                continue

        with open(data_path, "r", encoding=encoding, errors="replace") as f:
            for line_no, raw_line in enumerate(f, 1):
                line = raw_line.rstrip("\n\r")

                if len(line) < 100:  # Skip blank/short lines
                    skipped_short += 1
                    continue

                total_records += 1

                record = parse_record(line)
                if not record:
                    skipped_short += 1
                    continue

                if is_relevant_corp(record["corp_name"]):
                    matches.append(record)

                    if dry_run and len(matches) >= 5:
                        break

                if total_records % 500_000 == 0:
                    logger.info(f"  Processed {total_records:,} records, {len(matches):,} matches so far")

    except Exception as e:
        logger.error(f"Parse failed at record ~{total_records}: {e}")

    logger.info(f"Parsing complete: {total_records:,} total records, "
                f"{len(matches):,} matching associations, {skipped_short} skipped (short/blank)")
    return matches


def _log_sample_record(line: str):
    """Log parsed fields from a sample record for debugging field positions."""
    record = parse_record(line)
    if not record:
        logger.debug(f"Sample record too short ({len(line)} chars)")
        return

    logger.info("=== Sample Record (field position verification) ===")
    logger.info(f"  Document #:    [{record.get('document_number', '')}]")
    logger.info(f"  Corp Name:     [{record.get('corp_name', '')[:80]}]")
    logger.info(f"  Status:        [{record.get('status_code', '')}] = {record.get('status', '')}")
    logger.info(f"  Filing Type:   [{record.get('filing_type', '')}] = {record.get('filing_type_label', '')}")
    logger.info(f"  File Date:     [{record.get('file_date', '')}]")
    logger.info(f"  FEI Number:    [{record.get('fei_number', '')}]")
    logger.info(f"  Principal:     [{record.get('principal_address', '')[:80]}]")
    logger.info(f"  Mailing:       [{record.get('mailing_address', '')[:80]}]")
    logger.info(f"  Reg Agent:     [{record.get('registered_agent', '')}]")
    logger.info(f"  RA Type:       [{record.get('ra_type', '')}]")
    logger.info(f"  RA Address:    [{record.get('ra_address', '')[:60]}]")
    for i, officer in enumerate(record.get("officers", [])[:3]):
        logger.info(
            f"  Officer {i+1}:     [{officer.get('title', '')}={officer.get('title_label', '')}] "
            f"{officer.get('name', '')}"
        )
    logger.info("=== End Sample ===")


# ─── CSV Output ───

CSV_HEADERS = [
    "document_number",
    "corp_name",
    "status_code", "status",
    "filing_type", "filing_type_label",
    "file_date", "filing_date_formatted", "last_txn_date",
    "fei_number",
    # Principal address
    "principal_address1", "principal_address2",
    "principal_city", "principal_state", "principal_zip", "principal_country",
    "principal_address",
    # Mailing address
    "mailing_address1", "mailing_address2",
    "mailing_city", "mailing_state", "mailing_zip", "mailing_country",
    "mailing_address",
    # Registered agent
    "registered_agent", "ra_type",
    "ra_street", "ra_city", "ra_state", "ra_zip", "ra_address",
    # Officers (each: title, type, name, address, city, state, zip)
    "officer_1_title", "officer_1_title_label", "officer_1_name", "officer_1_type",
    "officer_2_title", "officer_2_title_label", "officer_2_name", "officer_2_type",
    "officer_3_title", "officer_3_title_label", "officer_3_name", "officer_3_type",
    "officer_4_title", "officer_4_title_label", "officer_4_name", "officer_4_type",
    "officer_5_title", "officer_5_title_label", "officer_5_name", "officer_5_type",
    "officer_6_title", "officer_6_title_label", "officer_6_name", "officer_6_type",
    "more_than_six_off",
]


def _flatten_record(record: dict) -> dict:
    """Flatten a parsed record (with nested officers) into a flat CSV row."""
    row = {k: record.get(k, "") for k in CSV_HEADERS if not k.startswith("officer_")}

    for i in range(MAX_OFFICERS):
        prefix = f"officer_{i+1}"
        if i < len(record.get("officers", [])):
            officer = record["officers"][i]
            row[f"{prefix}_title"] = officer.get("title", "")
            row[f"{prefix}_title_label"] = officer.get("title_label", "")
            row[f"{prefix}_name"] = officer.get("name", "")
            row[f"{prefix}_type"] = officer.get("type", "")
        else:
            row[f"{prefix}_title"] = ""
            row[f"{prefix}_title_label"] = ""
            row[f"{prefix}_name"] = ""
            row[f"{prefix}_type"] = ""

    return row


def write_csv(records: list[dict], output_path: str) -> str:
    """Write filtered records to a CSV file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(_flatten_record(record))

    logger.info(f"Wrote {len(records):,} records to {output_path}")
    return output_path


# ─── S3 Upload ───

def _upload_to_s3(local_path: str, s3_key: str):
    """Upload a file to S3 bucket for persistence across deploys."""
    try:
        import boto3
        endpoint = os.getenv("AWS_ENDPOINT_URL_S3") or os.getenv("AWS_ENDPOINT_URL")
        access_key = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        bucket = os.getenv("AWS_S3_BUCKET_NAME") or os.getenv("AWS_BUCKET_NAME") or "default"

        if not all([endpoint, access_key, secret_key]):
            logger.debug("S3 not configured — skipping upload")
            return

        client = boto3.client("s3", endpoint_url=endpoint,
                              aws_access_key_id=access_key,
                              aws_secret_access_key=secret_key,
                              region_name="auto")
        client.upload_file(local_path, bucket, s3_key)
        logger.info(f"Uploaded to S3: {s3_key}")
    except Exception as e:
        logger.warning(f"S3 upload failed for {s3_key}: {e}")


# ─── Main Entry Points ───

def download_and_process(dry_run: bool = False, url_override: str | None = None) -> dict:
    """Full pipeline: download → parse → filter → save CSV → upload S3.

    Returns a summary dict with counts and file paths.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Step 1: Download — try SFTP first (more reliable), fall back to HTTP
    raw_dir = os.path.join(DATA_DIR, "sunbiz_raw")
    data_path = None
    url = url_override

    if not url:
        # Try SFTP first — FL DoS blocks HTTP scraping
        logger.info("Attempting SFTP download from sftp.floridados.gov ...")
        data_path = download_via_sftp(raw_dir)

    if not data_path and not url:
        # Fall back to HTTP scraping
        logger.info("SFTP failed, trying HTTP page scraping...")
        url = _find_download_url()

    if url and not data_path:
        data_path = download_file(url, raw_dir)

    if not data_path:
        return {
            "success": False,
            "error": "Could not download Sunbiz data via SFTP or HTTP. "
                     "FL DoS may be blocking automated access. "
                     "Try manually downloading from "
                     "https://dos.fl.gov/sunbiz/other-services/data-downloads/quarterly-data/ "
                     "and upload to System Data/Sunbiz/ via File Manager, "
                     "then run: python -m scripts.download_sunbiz --file <path>",
        }

    # Step 3: Parse and filter
    matches = parse_and_filter(data_path, dry_run=dry_run)

    if dry_run:
        logger.info("=== DRY RUN: First 5 matching records ===")
        for i, record in enumerate(matches[:5], 1):
            logger.info(f"\n--- Record {i} ---")
            logger.info(f"  Corp:   {record['corp_name']}")
            logger.info(f"  Doc#:   {record['document_number']}")
            logger.info(f"  Status: {record['status']} ({record['status_code']})")
            logger.info(f"  Filed:  {record['filing_date_formatted']}")
            logger.info(f"  Addr:   {record['principal_address']}")
            logger.info(f"  Agent:  {record['registered_agent']}")
            for j, off in enumerate(record.get("officers", [])[:3], 1):
                logger.info(f"  Officer {j}: [{off['title']}] {off['name']}")
        return {
            "success": True,
            "dry_run": True,
            "sample_count": len(matches),
            "records": [_flatten_record(r) for r in matches[:5]],
        }

    if not matches:
        return {"success": True, "total_matches": 0, "message": "No matching associations found"}

    # Step 4: Write CSV to data/ and filestore/
    csv_filename = f"sunbiz_corps_{timestamp}.csv"
    csv_path = os.path.join(DATA_DIR, "sunbiz_corps.csv")
    write_csv(matches, csv_path)

    # Also save timestamped copy to filestore
    os.makedirs(FILESTORE_DIR, exist_ok=True)
    filestore_path = os.path.join(FILESTORE_DIR, csv_filename)
    write_csv(matches, filestore_path)

    # Step 5: Upload to S3
    _upload_to_s3(csv_path, "data/sunbiz_corps.csv")
    _upload_to_s3(filestore_path, f"files/System Data/Sunbiz/{csv_filename}")

    # Summary stats
    active_count = sum(1 for r in matches if r["status_code"] == "AA")
    with_agent = sum(1 for r in matches if r["registered_agent"])
    with_officers = sum(1 for r in matches if r.get("officers"))

    summary = {
        "success": True,
        "source_url": url,
        "total_matches": len(matches),
        "active_corps": active_count,
        "with_registered_agent": with_agent,
        "with_officers": with_officers,
        "csv_path": csv_path,
        "filestore_path": filestore_path,
        "timestamp": timestamp,
    }
    logger.info(f"Sunbiz download complete: {summary}")
    return summary


# ─── CLI ───

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Download and filter FL Sunbiz bulk corporate data")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse first matching 5 records and display, don't save")
    parser.add_argument("--url", type=str, default=None,
                        help="Direct URL to the quarterly data file (skip page scraping)")
    parser.add_argument("--file", type=str, default=None,
                        help="Path to an already-downloaded data file (skip download)")
    args = parser.parse_args()

    if args.file:
        # Parse a local file directly
        logger.info(f"Parsing local file: {args.file}")
        matches = parse_and_filter(args.file, dry_run=args.dry_run)
        if args.dry_run:
            for i, record in enumerate(matches[:5], 1):
                print(f"\n--- Record {i} ---")
                print(f"  Corp:   {record['corp_name']}")
                print(f"  Doc#:   {record['document_number']}")
                print(f"  Status: {record['status']} ({record['status_code']})")
                print(f"  Filed:  {record['filing_date_formatted']}")
                print(f"  Addr:   {record['principal_address']}")
                print(f"  Agent:  {record['registered_agent']}")
                for j, off in enumerate(record.get("officers", [])[:3], 1):
                    print(f"  Officer {j}: [{off['title']}] {off['name']}")
        else:
            csv_path = os.path.join(DATA_DIR, "sunbiz_corps.csv")
            write_csv(matches, csv_path)
            print(f"Wrote {len(matches):,} records to {csv_path}")
    else:
        result = download_and_process(dry_run=args.dry_run, url_override=args.url)
        if result.get("success"):
            print(f"Success: {result.get('total_matches', 0):,} matching associations")
            if not args.dry_run and result.get("csv_path"):
                print(f"CSV: {result['csv_path']}")
        else:
            print(f"Failed: {result.get('error', 'Unknown error')}")
            sys.exit(1)


if __name__ == "__main__":
    main()
