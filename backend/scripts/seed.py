"""
Comprehensive seed script - inserts 3 mock Florida condo properties
with realistic financial documents (Sunbiz, Audit, I&E reports).
Bypasses S3, saves extracted_text directly to EntityAsset.

Usage: DATABASE_URL=... python -m scripts.seed
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from database.models import (
    ActionType,
    Contact,
    DocType,
    Entity,
    EntityAsset,
    LeadLedger,
)


MOCK_PROPERTIES = [
    {
        "name": "Clearwater Towers Condominium Association, Inc.",
        "address": "450 Gulf Blvd, Clearwater Beach, FL 33767",
        "county": "Pinellas",
        "latitude": 27.9781,
        "longitude": -82.8270,
        "contacts": [
            {"name": "John R. Castellano", "title": "President, Board of Directors"},
            {"name": "Mary K. Sullivan", "title": "Treasurer"},
            {"name": "Robert A. Chen", "title": "Secretary"},
        ],
        "sunbiz": """STATE OF FLORIDA
DEPARTMENT OF STATE
DIVISION OF CORPORATIONS

2024 ANNUAL REPORT

Document Number: N04000012847
FEI/EIN Number: 59-3281456
Date Filed: 02/15/2024
State: FL
Status: ACTIVE

Entity Name: CLEARWATER TOWERS CONDOMINIUM ASSOCIATION, INC.

Principal Address:
450 Gulf Blvd
Clearwater Beach, FL 33767

Mailing Address:
450 Gulf Blvd, Unit MGR
Clearwater Beach, FL 33767

Registered Agent Name & Address:
Becker & Poliakoff, P.A.
1 East Broward Blvd, Suite 1800
Fort Lauderdale, FL 33301

Officer/Director Detail:
  President:   John R. Castellano     450 Gulf Blvd #1201, Clearwater Beach FL 33767
  Treasurer:   Mary K. Sullivan       450 Gulf Blvd #803, Clearwater Beach FL 33767
  Secretary:   Robert A. Chen         450 Gulf Blvd #1504, Clearwater Beach FL 33767
  Director:    Patricia M. Vasquez    450 Gulf Blvd #607, Clearwater Beach FL 33767
  Director:    William T. Nakamura    450 Gulf Blvd #1102, Clearwater Beach FL 33767

Annual Report Filed: 02/15/2024
""",
        "audit": """CLEARWATER TOWERS CONDOMINIUM ASSOCIATION, INC.
AUDITED FINANCIAL STATEMENTS
For the Year Ended December 31, 2024

INDEPENDENT AUDITORS' REPORT
Miller, Grossman & Katz, CPAs
Tampa, Florida

To the Board of Directors and Unit Owners of
Clearwater Towers Condominium Association, Inc.

Opinion
We have audited the accompanying financial statements of Clearwater Towers
Condominium Association, Inc. (the "Association"), which comprise the balance
sheet as of December 31, 2024, and the related statements of revenues and
expenses, changes in fund balances, and cash flows for the year then ended.

In our opinion, the financial statements present fairly, in all material respects,
the financial position of the Association as of December 31, 2024.

BALANCE SHEET - December 31, 2024

ASSETS
  Operating Cash & Equivalents         $   847,231
  Assessments Receivable               $   124,560
  Prepaid Insurance                    $   187,500
  Reserve Fund - Money Market          $ 1,234,890
  Reserve Fund - CD Investments        $   890,000
  Other Assets                         $    45,200
                                       -----------
  TOTAL ASSETS                         $ 3,329,381

LIABILITIES & FUND BALANCES
  Accounts Payable                     $    67,430
  Accrued Expenses                     $   112,890
  Prepaid Assessments                  $    89,200
  Deferred Revenue                     $    34,100
                                       -----------
  Total Liabilities                    $   303,620
  Operating Fund Balance               $   891,871
  Reserve Fund Balance                 $ 2,133,890
                                       -----------
  TOTAL LIABILITIES & FUND BALANCES    $ 3,329,381

NOTES TO FINANCIAL STATEMENTS

Note 1 - Organization
The Association was organized in 1987 to manage and maintain common elements
of a 156-unit, 16-story oceanfront condominium in Clearwater Beach, Florida.

Note 4 - Insurance Coverage
The Association maintains the following insurance policies:

  Property Insurance (Wind/Flood):
    Carrier:          Citizens Property Insurance Corporation
    Policy Number:    CIT-FL-2024-0087234
    Coverage Amount:  $52,000,000 (replacement cost)
    Total Insured Value (TIV): $52,000,000
    Annual Premium:   $485,000
    Expiration Date:  June 30, 2025
    Deductible:       3% Named Storm / $25,000 AOP

  General Liability:
    Carrier:          Zurich Insurance Group
    Coverage:         $2,000,000 per occurrence / $5,000,000 aggregate
    Annual Premium:   $38,400

  Directors & Officers:
    Carrier:          Travelers
    Coverage:         $1,000,000
    Annual Premium:   $12,200

Note 5 - Reserve Study
Per the most recent reserve study dated March 2024 by Reserve Advisors, LLC,
the Association's reserves are approximately 68% funded. The Board has adopted
a plan to reach 100% funding by 2033 through annual assessment increases.
""",
        "ie_report": """CLEARWATER TOWERS CONDOMINIUM ASSOCIATION, INC.
INCOME & EXPENSE STATEMENT
For the Years Ended December 31, 2023 and December 31, 2024

                                    2024 Actual    2023 Actual    Variance
REVENUES
  Unit Owner Assessments           $2,496,000     $2,184,000     $ 312,000
  Special Assessments              $  450,000     $        0     $ 450,000
  Interest & Investment Income     $   67,800     $   42,100     $  25,700
  Laundry & Vending Income        $   18,400     $   16,900     $   1,500
  Cable/Internet Bulk Contract     $   93,600     $   93,600     $       0
  Other Income                     $   12,300     $    9,800     $   2,500
                                   ----------     ----------     ---------
  TOTAL REVENUES                   $3,138,100     $2,346,400     $ 791,700

EXPENSES
  Insurance - Property (Wind)      $  485,000     $  210,000     $ 275,000
  Insurance - General Liability    $   38,400     $   32,100     $   6,300
  Insurance - D&O / Fidelity       $   12,200     $   10,800     $   1,400
  Insurance - Total                $  535,600     $  252,900     $ 282,700

  Management Fees                  $  168,000     $  156,000     $  12,000
  Payroll & Benefits               $  312,400     $  298,700     $  13,700
  Repairs & Maintenance            $  287,900     $  245,300     $  42,600
  Elevator Maintenance             $   67,200     $   58,400     $   8,800
  Landscaping & Pool               $   89,400     $   82,100     $   7,300
  Utilities - Electric             $  234,600     $  218,900     $  15,700
  Utilities - Water/Sewer          $  178,300     $  165,400     $  12,900
  Cable/Internet                   $   93,600     $   93,600     $       0
  Legal & Professional             $   78,900     $   45,200     $  33,700
  Reserve Contributions            $  780,000     $  520,000     $ 260,000
  Bad Debt Expense                 $   23,100     $   18,400     $   4,700
  Other Operating Expenses         $   56,800     $   48,200     $   8,600
                                   ----------     ----------     ---------
  TOTAL EXPENSES                   $2,905,800     $2,203,100     $ 702,700

NET EXCESS (DEFICIT)               $  232,300     $  143,300     $  89,000

NOTES:
Insurance premiums increased 112% year-over-year primarily due to Citizens
Property Insurance rate increases and the hardening Florida property insurance
market. The Board approved a $450,000 special assessment in Q1 2024 to offset
the premium increase and bolster reserves per SB 4-D compliance requirements.
""",
    },
    {
        "name": "Boca Inlet Condominium Association, Inc.",
        "address": "700 S Ocean Blvd, Boca Raton, FL 33432",
        "county": "Palm Beach",
        "latitude": 26.3387,
        "longitude": -80.0669,
        "contacts": [
            {"name": "Dr. Sandra L. Friedman", "title": "President, Board of Directors"},
            {"name": "Howard J. Berkowitz", "title": "Vice President & Treasurer"},
        ],
        "sunbiz": """STATE OF FLORIDA
DEPARTMENT OF STATE
DIVISION OF CORPORATIONS

2024 ANNUAL REPORT

Document Number: N82000004521
FEI/EIN Number: 65-0234891
Date Filed: 01/28/2024
State: FL
Status: ACTIVE

Entity Name: BOCA INLET CONDOMINIUM ASSOCIATION, INC.

Principal Address:
700 S Ocean Blvd
Boca Raton, FL 33432

Registered Agent Name & Address:
Siegfried, Rivera, Hyman, P.A.
201 Alhambra Circle, Suite 1100
Coral Gables, FL 33134

Officer/Director Detail:
  President:     Dr. Sandra L. Friedman   700 S Ocean Blvd #PH3, Boca Raton FL 33432
  VP/Treasurer:  Howard J. Berkowitz      700 S Ocean Blvd #1801, Boca Raton FL 33432
  Secretary:     Angela D. Rossini        700 S Ocean Blvd #902, Boca Raton FL 33432
  Director:      Michael P. Tanaka        700 S Ocean Blvd #1504, Boca Raton FL 33432

Annual Report Filed: 01/28/2024
""",
        "audit": """BOCA INLET CONDOMINIUM ASSOCIATION, INC.
AUDITED FINANCIAL STATEMENTS
For the Year Ended December 31, 2024

INDEPENDENT AUDITORS' REPORT
Keefe McCullough & Co., LLP
Fort Lauderdale, Florida

BALANCE SHEET - December 31, 2024

ASSETS
  Operating Cash & Equivalents         $ 1,245,670
  Assessments Receivable               $   189,340
  Prepaid Insurance                    $   312,500
  Reserve Fund - Investments           $ 3,456,780
  Fixed Assets (net)                   $   234,100
                                       -----------
  TOTAL ASSETS                         $ 5,438,390

LIABILITIES & FUND BALANCES
  Accounts Payable                     $   134,200
  Accrued Expenses                     $   189,700
  Line of Credit - Insurance           $   500,000
  Prepaid Assessments                  $   167,800
                                       -----------
  Total Liabilities                    $   991,700
  Operating Fund Balance               $ 1,289,910
  Reserve Fund Balance                 $ 3,156,780
                                       -----------
  TOTAL LIABILITIES & FUND BALANCES    $ 5,438,390

NOTES TO FINANCIAL STATEMENTS

Note 1 - Organization
The Association manages a 210-unit, 22-story luxury oceanfront condominium
located directly on the Boca Raton Inlet, completed in 1982.

Note 4 - Insurance Coverage

  Property Insurance (Wind/Flood):
    Carrier:          Heritage Insurance Holdings (primary layer)
                      Lloyds of London (excess layer)
    Policy Numbers:   HER-FL-2024-00341 / LLY-EX-2024-8821
    Coverage Amount:  $89,000,000 (replacement cost)
    Total Insured Value (TIV): $89,000,000
    Annual Premium:   $1,240,000
    Expiration Date:  September 1, 2025
    Deductible:       5% Named Storm / $50,000 AOP

  General Liability:
    Carrier:          Ironshore Insurance
    Coverage:         $5,000,000 per occurrence / $10,000,000 aggregate
    Annual Premium:   $67,800

  Umbrella Policy:
    Carrier:          AIG
    Coverage:         $25,000,000
    Annual Premium:   $89,200

Note 6 - Structural Integrity Reserve Study (SIRS)
The milestone inspection (per FL SB 4-D) was completed in August 2024 by
Morabito Consultants, Inc. Phase 2 identified $4.2M in necessary concrete
restoration work. A special assessment was approved in October 2024.
""",
        "ie_report": """BOCA INLET CONDOMINIUM ASSOCIATION, INC.
INCOME & EXPENSE STATEMENT
For the Years Ended December 31, 2023 and December 31, 2024

                                    2024 Actual    2023 Actual    Variance
REVENUES
  Unit Owner Assessments           $5,040,000     $3,780,000     $1,260,000
  Special Assessments              $2,100,000     $        0     $2,100,000
  Interest & Investment Income     $  156,800     $   89,400     $   67,400
  Parking Revenue                  $   72,000     $   72,000     $        0
  Marina Slip Fees                 $  144,000     $  132,000     $   12,000
  Other Income                     $   34,200     $   28,600     $    5,600
                                   ----------     ----------     ----------
  TOTAL REVENUES                   $7,547,000     $4,102,000     $3,445,000

EXPENSES
  Insurance - Property (Wind)      $1,240,000     $  520,000     $  720,000
  Insurance - General Liability    $   67,800     $   52,400     $   15,400
  Insurance - Umbrella             $   89,200     $   71,600     $   17,600
  Insurance - D&O / Fidelity       $   24,500     $   19,800     $    4,700
  Insurance - Total                $1,421,500     $  663,800     $  757,700

  Management Fees                  $  288,000     $  264,000     $   24,000
  Payroll & Benefits               $  567,800     $  523,400     $   44,400
  Repairs & Maintenance            $  456,700     $  389,200     $   67,500
  Concrete Restoration (SIRS)      $  890,000     $        0     $  890,000
  Elevator Maintenance (4 units)   $  134,400     $  112,800     $   21,600
  Landscaping & Pool               $  167,200     $  145,600     $   21,600
  Utilities - Electric             $  412,300     $  378,900     $   33,400
  Utilities - Water/Sewer          $  289,600     $  267,100     $   22,500
  Security                         $  198,000     $  186,000     $   12,000
  Legal & Professional             $  234,500     $   98,700     $  135,800
  Reserve Contributions            $1,200,000     $  780,000     $  420,000
  Bad Debt Expense                 $   45,600     $   32,100     $   13,500
  Other Operating Expenses         $   89,400     $   78,300     $   11,100
                                   ----------     ----------     ----------
  TOTAL EXPENSES                   $6,395,000     $3,920,000     $2,475,000

NET EXCESS (DEFICIT)               $1,152,000     $  182,000     $  970,000

NOTES:
Property insurance premiums increased 138.5% YoY. The Association secured a
$500,000 line of credit from Valley National Bank specifically to finance
the insurance premium increase while collecting the special assessment.
""",
    },
    {
        "name": "Pelican Bay North Tower Owners Association, Inc.",
        "address": "6361 Pelican Bay Blvd, Naples, FL 34108",
        "county": "Collier",
        "latitude": 26.2400,
        "longitude": -81.8076,
        "contacts": [
            {"name": "Thomas W. Richardson III", "title": "President, Board of Directors"},
            {"name": "Carol A. Donovan", "title": "Treasurer"},
            {"name": "James M. Petrov", "title": "Secretary"},
        ],
        "sunbiz": """STATE OF FLORIDA
DEPARTMENT OF STATE
DIVISION OF CORPORATIONS

2024 ANNUAL REPORT

Document Number: N98000007892
FEI/EIN Number: 65-0891234
Date Filed: 03/12/2024
State: FL
Status: ACTIVE

Entity Name: PELICAN BAY NORTH TOWER OWNERS ASSOCIATION, INC.

Principal Address:
6361 Pelican Bay Blvd
Naples, FL 34108

Registered Agent Name & Address:
Pavese Law Firm
1833 Hendry Street
Fort Myers, FL 33901

Officer/Director Detail:
  President:   Thomas W. Richardson III   6361 Pelican Bay Blvd #PH1, Naples FL 34108
  Treasurer:   Carol A. Donovan           6361 Pelican Bay Blvd #1603, Naples FL 34108
  Secretary:   James M. Petrov            6361 Pelican Bay Blvd #901, Naples FL 34108
  Director:    Katherine S. O'Brien       6361 Pelican Bay Blvd #1204, Naples FL 34108

Annual Report Filed: 03/12/2024
""",
        "audit": """PELICAN BAY NORTH TOWER OWNERS ASSOCIATION, INC.
AUDITED FINANCIAL STATEMENTS
For the Year Ended December 31, 2024

INDEPENDENT AUDITORS' REPORT
Markham Norton Mosteller Wright & Co., P.A.
Fort Myers, Florida

BALANCE SHEET - December 31, 2024

ASSETS
  Operating Cash & Equivalents         $   567,890
  Assessments Receivable               $    78,200
  Prepaid Insurance                    $   145,000
  Reserve Fund - Investments           $ 1,890,450
  Other Assets                         $    34,500
                                       -----------
  TOTAL ASSETS                         $ 2,716,040

LIABILITIES & FUND BALANCES
  Accounts Payable                     $    56,300
  Accrued Expenses                     $    89,100
  Prepaid Assessments                  $    67,400
                                       -----------
  Total Liabilities                    $   212,800
  Operating Fund Balance               $   612,790
  Reserve Fund Balance                 $ 1,890,450
                                       -----------
  TOTAL LIABILITIES & FUND BALANCES    $ 2,716,040

NOTES TO FINANCIAL STATEMENTS

Note 1 - Organization
The Association manages a 98-unit, 18-story Gulf-front condominium tower
in the Pelican Bay community of Naples, Florida, constructed in 1998.

Note 4 - Insurance Coverage

  Property Insurance (Wind/Flood):
    Carrier:          Slide Insurance Company (primary)
                      Florida Peninsula Insurance (excess)
    Policy Numbers:   SLD-2024-FL-00567 / FPI-EX-2024-2234
    Coverage Amount:  $38,000,000 (replacement cost)
    Total Insured Value (TIV): $38,000,000
    Annual Premium:   $412,000
    Expiration Date:  April 15, 2025
    Deductible:       3% Named Storm / $10,000 AOP

  General Liability:
    Carrier:          Auto-Owners Insurance
    Coverage:         $3,000,000 per occurrence / $5,000,000 aggregate
    Annual Premium:   $28,900

  Directors & Officers:
    Carrier:          Philadelphia Insurance Companies
    Coverage:         $2,000,000
    Annual Premium:   $15,600

Note 5 - Hurricane Ian Impact
The Association received $2.1M in insurance proceeds from Hurricane Ian (2022)
damage claims. Restoration work was completed in Q2 2024. The post-Ian
insurance market significantly impacted renewal premiums.
""",
        "ie_report": """PELICAN BAY NORTH TOWER OWNERS ASSOCIATION, INC.
INCOME & EXPENSE STATEMENT
For the Years Ended December 31, 2023 and December 31, 2024

                                    2024 Actual    2023 Actual    Variance
REVENUES
  Unit Owner Assessments           $1,764,000     $1,411,200     $ 352,800
  Special Assessments              $  280,000     $  650,000     $(370,000)
  Interest & Investment Income     $   78,900     $   45,600     $  33,300
  Guest Suite Revenue              $   24,600     $   21,800     $   2,800
  Other Income                     $    8,900     $    7,200     $   1,700
                                   ----------     ----------     ---------
  TOTAL REVENUES                   $2,156,400     $2,135,800     $  20,600

EXPENSES
  Insurance - Property (Wind)      $  412,000     $  180,000     $ 232,000
  Insurance - General Liability    $   28,900     $   24,300     $   4,600
  Insurance - D&O / Fidelity       $   15,600     $   12,800     $   2,800
  Insurance - Total                $  456,500     $  217,100     $ 239,400

  Management Fees                  $  108,000     $   96,000     $  12,000
  Payroll & Benefits               $  234,500     $  218,900     $  15,600
  Repairs & Maintenance            $  198,700     $  567,800     $(369,100)
  Elevator Maintenance (2 units)   $   56,400     $   48,200     $   8,200
  Landscaping & Pool               $  112,300     $   98,700     $  13,600
  Utilities - Electric             $  189,400     $  176,300     $  13,100
  Utilities - Water/Sewer          $  134,200     $  123,800     $  10,400
  Security (gate/lobby)            $  112,000     $  108,000     $   4,000
  Legal & Professional             $   56,700     $  123,400     $ (66,700)
  Reserve Contributions            $  420,000     $  280,000     $ 140,000
  Bad Debt Expense                 $   12,300     $    8,900     $   3,400
  Other Operating Expenses         $   34,500     $   29,800     $   4,700
                                   ----------     ----------     ---------
  TOTAL EXPENSES                   $2,125,500     $2,096,900     $  28,600

NET EXCESS (DEFICIT)               $   30,900     $   38,900     $  (8,000)

NOTES:
Property insurance increased 128.9% YoY following Hurricane Ian. Post-storm
market hardening has made coastal Collier County one of the most expensive
markets in the state. The Board is exploring alternative risk transfer options
including parametric insurance for the 2025 renewal cycle.
""",
    },
]


def seed():
    db = SessionLocal()
    try:
        for prop in MOCK_PROPERTIES:
            # Check if already seeded
            existing = db.query(Entity).filter(Entity.name == prop["name"]).first()
            if existing:
                print(f"  Skipping (exists): {prop['name']}")
                continue

            # Create Entity
            entity = Entity(
                name=prop["name"],
                address=prop["address"],
                county=prop["county"],
                latitude=prop["latitude"],
                longitude=prop["longitude"],
                characteristics={},
            )
            db.add(entity)
            db.commit()
            db.refresh(entity)
            print(f"  Created entity: {prop['name']} (id={entity.id})")

            # Create Contacts
            for contact in prop["contacts"]:
                c = Contact(
                    entity_id=entity.id,
                    name=contact["name"],
                    title=contact["title"],
                )
                db.add(c)

            # Create Assets (Sunbiz, Audit, I&E)
            for doc_type, field in [
                (DocType.SUNBIZ, "sunbiz"),
                (DocType.AUDIT, "audit"),
                (DocType.IE_REPORT, "ie_report"),
            ]:
                asset = EntityAsset(
                    entity_id=entity.id,
                    doc_type=doc_type,
                    extracted_text=prop[field],
                )
                db.add(asset)

            # Write HUNT_FOUND ledger event
            ledger = LeadLedger(
                entity_id=entity.id,
                action_type=ActionType.HUNT_FOUND,
            )
            db.add(ledger)

            db.commit()
            print(f"  Seeded 3 docs + {len(prop['contacts'])} contacts for {prop['name']}")

        print("\nSeed complete!")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
