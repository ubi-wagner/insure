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
    "004": "Condominium",
    "005": "Cooperatives",
    "006": "Retirement Homes",
    "008": "Multi-Family (10+)",
    "039": "Hotels/Motels",
}

# Also include if they have enough units
MIN_UNITS_FOR_OTHER = 10


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


def seed_county(county_no: str, db: Session) -> dict:
    """Seed leads from a NAL file for one county.

    Returns stats: {total_parcels, filtered, created, skipped_dupe, county_name}
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
    filtered = 0
    created = 0
    skipped_dupe = 0

    try:
        with open(nal_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                total += 1

                # Filter by DOR use code
                dor_uc = (row.get("DOR_UC") or "").strip().zfill(3)
                num_units = _safe_int(row.get("NO_RES_UNTS"))

                if dor_uc not in TARGET_USE_CODES:
                    # Include other codes if they have enough units
                    if not num_units or num_units < MIN_UNITS_FOR_OTHER:
                        continue

                filtered += 1

                # Get physical address
                phy_addr = (row.get("PHY_ADDR1") or "").strip()
                parcel_id = (row.get("PARCEL_ID") or "").strip()
                owner = (row.get("OWN_NAME") or "").strip()

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
                jv = _safe_int(row.get("JV"))
                tiv_estimate = round(jv * 1.3, -3) if jv and jv > 0 else None

                characteristics = {
                    "dor_parcel_id": parcel_id,
                    "dor_owner": owner,
                    "dor_use_code": dor_uc,
                    "dor_use_description": TARGET_USE_CODES.get(dor_uc, f"Code {dor_uc}"),
                    "dor_market_value": jv if jv and jv > 0 else None,
                    "dor_land_value": _safe_int(row.get("LND_VAL")),
                    "dor_construction_class": (row.get("CONST_CLASS") or "").strip() or None,
                    "year_built": str(_safe_int(row.get("ACT_YR_BLT"))) if _safe_int(row.get("ACT_YR_BLT")) else None,
                    "dor_year_built": _safe_int(row.get("ACT_YR_BLT")),
                    "dor_effective_year_built": _safe_int(row.get("EFF_YR_BLT")),
                    "dor_living_sqft": _safe_int(row.get("TOT_LVG_AREA")),
                    "dor_num_buildings": _safe_int(row.get("NO_BULDNG")),
                    "dor_num_units": num_units,
                    "units_estimate": num_units,
                    "dor_land_sqft": _safe_int(row.get("LND_SQFOOT")),
                    "dor_special_features_value": _safe_int(row.get("SPEC_FEAT_VAL")),
                    "tiv_estimate": tiv_estimate,
                    "tiv": f"${tiv_estimate:,.0f}" if tiv_estimate else None,
                    "construction_class": (row.get("CONST_CLASS") or "").strip() or None,
                    "imp_qual": (row.get("IMP_QUAL") or "").strip() or None,
                }

                # Owner address
                owner_parts = [
                    (row.get("OWN_ADDR1") or "").strip(),
                    (row.get("OWN_ADDR2") or "").strip(),
                    (row.get("OWN_CITY") or "").strip(),
                    (row.get("OWN_STATE") or "").strip(),
                    (row.get("OWN_ZIPCD") or "").strip(),
                ]
                owner_addr = ", ".join(p for p in owner_parts if p)
                if owner_addr:
                    characteristics["dor_owner_address"] = owner_addr

                # Sale history from NAL
                sale_prc = _safe_int(row.get("SALE_PRC1"))
                sale_yr = _safe_int(row.get("SALE_YR1"))
                sale_mo = _safe_int(row.get("SALE_MO1"))
                if sale_prc and sale_prc > 0:
                    characteristics["dor_last_sale_price"] = sale_prc
                if sale_yr:
                    characteristics["dor_last_sale_year"] = sale_yr
                    if sale_mo:
                        characteristics["dor_last_sale_date"] = f"{sale_mo}/{sale_yr}"

                # SDF enrichment (latest sale)
                state_parcel = (row.get("CENSUS_BK") or "").strip()  # Sometimes STATE_PARCEL_ID maps here
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
                    address=phy_addr,
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

    result = {
        "county": county_name,
        "county_no": county_no,
        "total_parcels": total,
        "filtered": filtered,
        "created": created,
        "skipped_dupe": skipped_dupe,
        "nal_file": os.path.basename(nal_path),
        "sdf_records": len(sdf_data),
    }

    emit(EventType.HUNTER, "seed_county", EventStatus.SUCCESS,
         detail=f"{county_name}: {created} leads from {filtered} condos/multi-family ({total} parcels)")
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
