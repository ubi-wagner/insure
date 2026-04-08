"""
NAL County Seeder

Seeds leads from FL DOR NAL tax roll files. This is the PRIMARY
source of truth for property data — not Overpass.

Filters for target DOR use codes:
  004 = Condominium
  005 = Cooperatives
  006 = Retirement Homes
  008 = Multi-Family (10+ units)
  039 = Hotels/Motels

Creates Entity records with authoritative data already populated:
  - Owner name + mailing address
  - Market value (JV) → TIV at 1.3x
  - Construction class
  - Year built
  - Living area sqft
  - Number of buildings + residential units
  - Parcel ID
  - Physical address
  - County
  - DOR use code + description

Then enrichment pipeline adds:
  - FEMA flood zone
  - DBPR condo name + managing entity
  - Payment history / delinquency
  - Auto-advance to ENRICHED
"""

import csv
import logging
import os
import threading
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import Entity, LeadLedger
from services.event_bus import EventStatus, EventType, emit

logger = logging.getLogger(__name__)

# DOR county numbers (alphabetical, starting at 11)
DOR_COUNTIES = {
    "16": "Broward", "18": "Charlotte", "21": "Collier",
    "23": "Miami-Dade", "39": "Hillsborough", "46": "Lee",
    "51": "Manatee", "60": "Palm Beach", "61": "Pasco",
    "62": "Pinellas", "68": "Sarasota",
}

# Target DOR use codes for insurance leads
TARGET_USE_CODES = {
    "003": "Multi-Family (small)",
    "004": "Condominium",
    "005": "Cooperatives",
    "006": "Retirement Homes",
    "008": "Multi-Family (10+)",
    "039": "Hotels/Motels",
}

# DOR construction class numeric codes → readable labels
DOR_CONSTRUCTION_CLASSES = {
    "1": "Frame",
    "2": "Masonry",
    "3": "Non-Combustible",
    "4": "Fire Resistive",
    "5": "Fire Resistive (Premium)",
    "6": "Fire Resistive (Premium)",
}

# Also include if they have enough units (for non-target use codes)
MIN_UNITS_FOR_OTHER = 10

# Minimum thresholds — focused on commercial insurance opportunities
MIN_MARKET_VALUE = int(os.environ.get("MIN_MARKET_VALUE", 2_000_000))  # Default $2M, configurable
MIN_UNITS_TARGET = 10            # At least 10 units for condos/multi-family


SEED_STATS_PATH = os.path.join(os.path.dirname(__file__), "..", "filestore", "System Data", "seed_stats.json")


def _save_seed_stats(county_no: str, result: dict):
    """Persist seed stats per county to JSON for the ops dashboard."""
    import json
    stats = {}
    try:
        if os.path.exists(SEED_STATS_PATH):
            with open(SEED_STATS_PATH, "r") as f:
                stats = json.load(f)
    except Exception:
        pass
    stats[county_no] = {
        **result,
        "seeded_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        os.makedirs(os.path.dirname(SEED_STATS_PATH), exist_ok=True)
        with open(SEED_STATS_PATH, "w") as f:
            json.dump(stats, f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Failed to save seed stats: {e}")


def get_seed_stats() -> dict:
    """Read persisted seed stats for all counties."""
    import json
    try:
        if os.path.exists(SEED_STATS_PATH):
            with open(SEED_STATS_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _find_nal_file(county_no: str) -> str | None:
    """Find the NAL file for a county."""
    search_dirs = [
        os.path.join(os.path.dirname(__file__), "..", "filestore", "System Data", "DOR"),
        os.path.join(os.path.dirname(__file__), "..", "data"),
    ]
    for d in search_dirs:
        resolved = os.path.abspath(d)
        if not os.path.exists(resolved):
            continue
        for f in os.listdir(resolved):
            if f.upper().startswith(f"NAL{county_no}") and f.lower().endswith(".csv"):
                return os.path.join(resolved, f)
    return None


def _find_sdf_file(county_no: str) -> str | None:
    """Find the SDF (sale data) file for a county."""
    search_dirs = [
        os.path.join(os.path.dirname(__file__), "..", "filestore", "System Data", "DOR"),
        os.path.join(os.path.dirname(__file__), "..", "data"),
    ]
    for d in search_dirs:
        resolved = os.path.abspath(d)
        if not os.path.exists(resolved):
            continue
        for f in os.listdir(resolved):
            if f.upper().startswith(f"SDF{county_no}") and f.lower().endswith(".csv"):
                return os.path.join(resolved, f)
    return None


def _safe_int(val) -> int | None:
    if not val:
        return None
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


def _normalize_columns(fieldnames: list[str]) -> dict[str, str]:
    """Build a mapping from normalized column names to actual column names.

    Handles BOM, whitespace, case differences, and underscore/space variants.
    Returns dict like {"DOR_UC": "actual_column_name_in_file"}.
    """
    mapping = {}
    for name in fieldnames:
        # Strip BOM, whitespace, and null bytes
        clean = name.strip().strip("\ufeff\x00").strip()
        # Normalize: uppercase, replace spaces with underscores
        normalized = clean.upper().replace(" ", "_")
        mapping[normalized] = name
    return mapping


def _get_col(row: dict, col_map: dict[str, str], *names: str) -> str:
    """Get a column value trying multiple normalized names."""
    for name in names:
        actual = col_map.get(name.upper().replace(" ", "_"))
        if actual and row.get(actual):
            return row[actual]
    return ""


def seed_county(county_no: str, db: Session, min_value: int | None = None) -> dict:
    """Seed leads from a NAL file for one county.

    Args:
        min_value: Override MIN_MARKET_VALUE threshold. Pass 0 to disable.

    Returns stats: {total_parcels, filtered, created, skipped_dupe, county_name, min_value}
    """
    county_name = DOR_COUNTIES.get(county_no, f"County {county_no}")
    nal_path = _find_nal_file(county_no)
    if not nal_path:
        return {"error": f"NAL file not found for county {county_no} ({county_name})"}

    emit(EventType.HUNTER, "seed_county_start", EventStatus.PENDING,
         detail=f"Seeding {county_name} from {os.path.basename(nal_path)}")

    # Load SDF for sale history enrichment
    sdf_data: dict[str, dict] = {}
    sdf_path = _find_sdf_file(county_no)
    if sdf_path:
        try:
            with open(sdf_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    # Index by STATE_PARCEL_ID for latest sale
                    sp_id = row.get("STATE_PARCEL_ID", "").strip()
                    if sp_id:
                        existing = sdf_data.get(sp_id)
                        if not existing or _safe_int(row.get("SALE_YR", 0)) > _safe_int(existing.get("SALE_YR", 0)):
                            sdf_data[sp_id] = row
            logger.info(f"SDF loaded: {len(sdf_data)} sale records for {county_name}")
        except Exception as e:
            logger.warning(f"Failed to load SDF for {county_name}: {e}")

    total = 0
    type_passed = 0
    filtered = 0
    created = 0
    skipped_dupe = 0

    # Debug: sample first row to check column names
    sample_row = None
    columns = []
    col_map = {}

    try:
        # Detect delimiter: read first line and check
        with open(nal_path, "r", encoding="utf-8-sig", errors="replace") as probe:
            first_line = probe.readline()
        delimiter = "\t" if "\t" in first_line else ","

        with open(nal_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            columns = reader.fieldnames or []
            col_map = _normalize_columns(columns)
            for row in reader:
                total += 1
                if sample_row is None:
                    sample_row = {k: v for k, v in list(row.items())[:10]}

                # Filter by DOR use code using normalized column lookup
                dor_uc = _get_col(row, col_map, "DOR_UC").strip()

                # Normalize: could be "4", "04", "004", "4.0"
                try:
                    dor_uc = str(int(float(dor_uc))).zfill(3) if dor_uc else ""
                except (ValueError, TypeError):
                    dor_uc = dor_uc.zfill(3) if dor_uc else ""

                num_units = _safe_int(_get_col(row, col_map, "NO_RES_UNTS", "NO_RES_UNITS"))

                if dor_uc not in TARGET_USE_CODES:
                    # Include other codes if they have enough units
                    if not num_units or num_units < MIN_UNITS_FOR_OTHER:
                        continue

                type_passed += 1

                # Weed out non-starters: too small or too low value
                jv_raw = _safe_int(_get_col(row, col_map, "JV"))
                threshold = min_value if min_value is not None else MIN_MARKET_VALUE
                if threshold > 0 and jv_raw is not None and 0 < jv_raw < threshold:
                    continue
                if dor_uc in ("004", "005", "008") and num_units and num_units < MIN_UNITS_TARGET:
                    continue

                filtered += 1

                # Get physical address
                phy_addr = _get_col(row, col_map, "PHY_ADDR1").strip()
                phy_city = _get_col(row, col_map, "PHY_CITY").strip()
                phy_zip = _get_col(row, col_map, "PHY_ZIPCD").strip()
                parcel_id = _get_col(row, col_map, "PARCEL_ID").strip()
                owner = _get_col(row, col_map, "OWN_NAME").strip()

                # Build full address for geocoding
                full_addr = phy_addr
                if phy_city:
                    full_addr += f", {phy_city}"
                if phy_zip:
                    full_addr += f", FL {phy_zip}"
                elif phy_city:
                    full_addr += ", FL"

                if not phy_addr and not owner:
                    continue

                # Dedupe by parcel ID
                if parcel_id:
                    existing = db.query(Entity).filter(
                        Entity.characteristics.op("->>")(  "dor_parcel_id") == parcel_id
                    ).first()
                    if existing:
                        skipped_dupe += 1
                        continue

                # Build characteristics from NAL data
                jv = jv_raw  # Already extracted above for filtering
                tiv_estimate = round(jv * 1.3, -3) if jv and jv > 0 else None
                const_class_raw = _get_col(row, col_map, "CONST_CLASS").strip() or None
                # Map numeric DOR construction code to readable label
                const_class = DOR_CONSTRUCTION_CLASSES.get(const_class_raw, const_class_raw)
                act_yr_blt = _safe_int(_get_col(row, col_map, "ACT_YR_BLT"))

                characteristics = {
                    "dor_parcel_id": parcel_id,
                    "dor_owner": owner,
                    "dor_use_code": dor_uc,
                    "dor_use_description": TARGET_USE_CODES.get(dor_uc, f"Code {dor_uc}"),
                    "dor_market_value": jv if jv and jv > 0 else None,
                    "dor_land_value": _safe_int(_get_col(row, col_map, "LND_VAL")),
                    "dor_construction_class": const_class,
                    "dor_construction_class_raw": const_class_raw,
                    "year_built": str(act_yr_blt) if act_yr_blt else None,
                    "dor_year_built": act_yr_blt,
                    "dor_effective_year_built": _safe_int(_get_col(row, col_map, "EFF_YR_BLT")),
                    "dor_living_sqft": _safe_int(_get_col(row, col_map, "TOT_LVG_AREA")),
                    "dor_num_buildings": _safe_int(_get_col(row, col_map, "NO_BULDNG")),
                    "dor_num_units": num_units,
                    "units_estimate": num_units,
                    "dor_land_sqft": _safe_int(_get_col(row, col_map, "LND_SQFOOT")),
                    "dor_special_features_value": _safe_int(_get_col(row, col_map, "SPEC_FEAT_VAL")),
                    "tiv_estimate": tiv_estimate,
                    "tiv": f"${tiv_estimate:,.0f}" if tiv_estimate else None,
                    "construction_class": const_class,
                    "imp_qual": _get_col(row, col_map, "IMP_QUAL").strip() or None,
                    "phy_city": phy_city or None,
                    "phy_zip": phy_zip or None,
                }

                # Owner address
                owner_parts = [
                    _get_col(row, col_map, "OWN_ADDR1").strip(),
                    _get_col(row, col_map, "OWN_ADDR2").strip(),
                    _get_col(row, col_map, "OWN_CITY").strip(),
                    _get_col(row, col_map, "OWN_STATE").strip(),
                    _get_col(row, col_map, "OWN_ZIPCD").strip(),
                ]
                owner_addr = ", ".join(p for p in owner_parts if p)
                if owner_addr:
                    characteristics["dor_owner_address"] = owner_addr

                # Sale history from NAL
                sale_prc = _safe_int(_get_col(row, col_map, "SALE_PRC1"))
                sale_yr = _safe_int(_get_col(row, col_map, "SALE_YR1"))
                sale_mo = _safe_int(_get_col(row, col_map, "SALE_MO1"))
                if sale_prc and sale_prc > 0:
                    characteristics["dor_last_sale_price"] = sale_prc
                if sale_yr:
                    characteristics["dor_last_sale_year"] = sale_yr
                    if sale_mo:
                        characteristics["dor_last_sale_date"] = f"{sale_mo}/{sale_yr}"

                # SDF enrichment (latest sale)
                state_parcel = _get_col(row, col_map, "CENSUS_BK").strip()
                # Try parcel-based SDF lookup
                for sdf_key in [parcel_id, state_parcel]:
                    if sdf_key and sdf_key in sdf_data:
                        sdf_row = sdf_data[sdf_key]
                        sdf_price = _safe_int(sdf_row.get("SALE_PRC"))
                        sdf_yr = _safe_int(sdf_row.get("SALE_YR"))
                        if sdf_price and sdf_price > 100:  # Filter out $100 nominal sales
                            characteristics["sdf_sale_price"] = sdf_price
                            characteristics["sdf_sale_year"] = sdf_yr
                        break

                # Build entity name from owner or address
                name = owner or phy_addr or f"Parcel {parcel_id}"
                # Clean up name — strip "INC", "LLC" etc for display
                if len(name) > 60:
                    name = name[:57] + "..."

                # Remove None values
                characteristics = {k: v for k, v in characteristics.items() if v is not None}

                # Mark source
                enrichment_sources = {
                    "dor_nal": {
                        "source": "dor_nal",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "fields_updated": list(characteristics.keys()),
                        "url": "https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx",
                    }
                }

                entity = Entity(
                    name=name,
                    address=full_addr if full_addr != phy_addr else phy_addr,
                    county=county_name,
                    characteristics=characteristics,
                    enrichment_sources=enrichment_sources,
                    pipeline_stage="TARGET",
                )
                db.add(entity)

                ledger = LeadLedger(
                    entity_id=0,  # Will be set after flush
                    action_type="SEED_FROM_NAL",
                    detail=f"Seeded from DOR NAL ({county_name}), parcel {parcel_id}",
                    source="dor_nal",
                )

                # Batch commit every 100
                if filtered % 100 == 0:
                    db.flush()
                    # Fix ledger entity_id
                    if entity.id:
                        ledger.entity_id = entity.id
                        db.add(ledger)

                    if filtered % 1000 == 0:
                        db.commit()
                        emit(EventType.HUNTER, "seed_county_progress", EventStatus.PENDING,
                             detail=f"{county_name}: {created} created from {filtered} filtered ({total} scanned)")

                created += 1

        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"Seeding failed for {county_name}: {e}")
        emit(EventType.HUNTER, "seed_county", EventStatus.ERROR,
             detail=f"{county_name}: {str(e)[:200]}")
        return {"error": str(e), "county": county_name, "total": total, "filtered": filtered, "created": created}

    threshold_used = min_value if min_value is not None else MIN_MARKET_VALUE

    result = {
        "county": county_name,
        "county_no": county_no,
        "total_parcels": total,
        "type_passed": type_passed,
        "filtered": filtered,
        "created": created,
        "skipped_dupe": skipped_dupe,
        "min_value_used": threshold_used,
        "nal_file": os.path.basename(nal_path),
        "sdf_records": len(sdf_data),
    }

    # Persist seed stats for ops dashboard
    _save_seed_stats(county_no, result)

    emit(EventType.HUNTER, "seed_county", EventStatus.SUCCESS,
         detail=f"{county_name}: {created} from {filtered} value-filtered / {type_passed} type-matched / {total} parcels")
    logger.info(f"Seed complete: {result}")

    return result


def seed_county_background(county_no: str):
    """Run county seeding in a background thread."""
    db = SessionLocal()
    try:
        return seed_county(county_no, db)
    except Exception as e:
        logger.error(f"Background seed failed: {e}")
        return {"error": str(e)}
    finally:
        db.close()


def get_available_counties() -> list[dict]:
    """List which counties have NAL files available for seeding."""
    available = []
    for county_no, county_name in sorted(DOR_COUNTIES.items(), key=lambda x: x[1]):
        nal_path = _find_nal_file(county_no)
        sdf_path = _find_sdf_file(county_no)
        available.append({
            "county_no": county_no,
            "county_name": county_name,
            "nal_file": os.path.basename(nal_path) if nal_path else None,
            "nal_size": os.path.getsize(nal_path) if nal_path else 0,
            "sdf_file": os.path.basename(sdf_path) if sdf_path else None,
            "sdf_size": os.path.getsize(sdf_path) if sdf_path else 0,
            "ready": nal_path is not None,
        })
    return available
