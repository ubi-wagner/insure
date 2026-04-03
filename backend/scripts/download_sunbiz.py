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
# Field positions (0-indexed, inclusive start, exclusive end).
# These are approximate — the script logs sample records for verification.
RECORD_LENGTH = 1440

FIELD_MAP = {
    "document_number":    (0, 12),
    "filing_type_code":   (12, 16),
    "filing_date":        (16, 20),     # MMYY
    "status_code":        (20, 22),     # AA=Active, IA=Inactive, etc.
    "corp_name":          (22, 182),    # 160 chars
    "principal_street":   (182, 302),   # 120 chars
    "principal_city":     (302, 362),   # 60 chars
    "principal_state":    (362, 364),   # 2 chars
    "principal_zip":      (364, 374),   # 10 chars
    "principal_country":  (374, 376),   # 2 chars (US, etc.)
    "mailing_street":     (376, 496),   # 120 chars
    "mailing_city":       (496, 556),   # 60 chars
    "mailing_state":      (556, 558),   # 2 chars
    "mailing_zip":        (558, 568),   # 10 chars
    "mailing_country":    (568, 570),   # 2 chars
    "registered_agent":   (570, 630),   # 60 chars (name)
    "ra_street":          (630, 690),   # 60 chars
    "ra_city":            (690, 730),   # 40 chars
    "ra_state":           (730, 732),   # 2 chars
    "ra_zip":             (732, 742),   # 10 chars
}

# Officers start at position 742, up to 6 officers.
# Each officer block: title(4) + name(50) + street(50) + city(40) + state(2) + zip(10) = ~156 chars
# But record length only allows (1440 - 742) / 6 ≈ 116 chars per officer.
OFFICER_START = 742
OFFICER_BLOCK_SIZE = 116
OFFICER_FIELDS = {
    "title":  (0, 4),
    "name":   (4, 54),
    "street": (54, 94),
    "city":   (94, 109),     # truncated to fit
    "state":  (109, 111),
    "zip":    (111, 116),
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

# Status codes
STATUS_CODES = {
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

    # Build composite fields
    addr_parts = [record["principal_street"], record["principal_city"],
                  record["principal_state"], record["principal_zip"]]
    record["principal_address"] = ", ".join(p for p in addr_parts if p)

    ra_parts = [record["ra_street"], record["ra_city"],
                record["ra_state"], record["ra_zip"]]
    record["ra_address"] = ", ".join(p for p in ra_parts if p)

    # Decode status
    record["status"] = STATUS_CODES.get(record["status_code"], record["status_code"])

    # Format filing date from MMYY to MM/YY
    fd = record["filing_date"]
    if len(fd) == 4 and fd.isdigit():
        record["filing_date_formatted"] = f"{fd[:2]}/{fd[2:]}"
    else:
        record["filing_date_formatted"] = fd

    return record


def is_relevant_corp(corp_name: str) -> bool:
    """Check if a corporation name matches our association/condo keywords."""
    upper = corp_name.upper()
    return any(kw in upper for kw in ASSOCIATION_KEYWORDS)


# ─── Download ───

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

    logger.info("=== Sample Record (field position debugging) ===")
    logger.info(f"  Document #:    [{record['document_number']}]")
    logger.info(f"  Filing Type:   [{record['filing_type_code']}]")
    logger.info(f"  Filing Date:   [{record['filing_date']}]")
    logger.info(f"  Status:        [{record['status_code']}] = {record['status']}")
    logger.info(f"  Corp Name:     [{record['corp_name'][:80]}]")
    logger.info(f"  Principal Addr:[{record['principal_address'][:80]}]")
    logger.info(f"  Reg Agent:     [{record['registered_agent']}]")
    logger.info(f"  RA Address:    [{record['ra_address'][:60]}]")
    for i, officer in enumerate(record.get("officers", [])[:3]):
        logger.info(f"  Officer {i+1}:     [{officer['title']}] {officer['name']}")
    logger.info("=== End Sample ===")


# ─── CSV Output ───

CSV_HEADERS = [
    "document_number", "filing_type_code", "filing_date", "filing_date_formatted",
    "status_code", "status", "corp_name",
    "principal_street", "principal_city", "principal_state", "principal_zip",
    "principal_address",
    "registered_agent", "ra_street", "ra_city", "ra_state", "ra_zip", "ra_address",
    "officer_1_title", "officer_1_name",
    "officer_2_title", "officer_2_name",
    "officer_3_title", "officer_3_name",
    "officer_4_title", "officer_4_name",
    "officer_5_title", "officer_5_name",
    "officer_6_title", "officer_6_name",
]


def _flatten_record(record: dict) -> dict:
    """Flatten a parsed record (with nested officers) into a flat CSV row."""
    row = {k: record.get(k, "") for k in CSV_HEADERS if not k.startswith("officer_")}

    for i in range(MAX_OFFICERS):
        prefix = f"officer_{i+1}"
        if i < len(record.get("officers", [])):
            officer = record["officers"][i]
            row[f"{prefix}_title"] = officer.get("title", "")
            row[f"{prefix}_name"] = officer.get("name", "")
        else:
            row[f"{prefix}_title"] = ""
            row[f"{prefix}_name"] = ""

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

    # Step 1: Find or use provided URL
    url = url_override
    if not url:
        logger.info("Scanning Sunbiz quarterly data page for download link...")
        url = _find_download_url()

    if not url:
        return {
            "success": False,
            "error": "Could not find Sunbiz quarterly download URL. "
                     "Visit https://dos.fl.gov/sunbiz/other-services/data-downloads/quarterly-data/ "
                     "and provide the URL manually via --url flag.",
        }

    # Step 2: Download
    raw_dir = os.path.join(DATA_DIR, "sunbiz_raw")
    data_path = download_file(url, raw_dir)
    if not data_path:
        return {"success": False, "error": "Download failed"}

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
