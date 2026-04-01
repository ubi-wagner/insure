"""
Seed script - inserts 4 real Pinellas County beachfront condo properties
with realistic financial documents (Sunbiz, Audit, I&E reports).

Usage: DATABASE_URL=... python -m scripts.seed
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from database.models import (
    ActionType,
    BrokerProfile,
    Contact,
    DocType,
    Entity,
    EntityAsset,
    LeadLedger,
    Policy,
)


SEED_PROPERTIES = [
    {
        "name": "Ultimar Condominium Association, Inc.",
        "address": "1340 Gulf Blvd, Clearwater Beach, FL 33767",
        "county": "Pinellas",
        "latitude": 27.9560,
        "longitude": -82.8340,
        "contacts": [
            {"name": "Richard A. Hartley", "title": "President, Board of Directors"},
            {"name": "Diane M. Kowalski", "title": "Treasurer"},
            {"name": "Frank J. Pellegrino", "title": "Secretary"},
        ],
        "sunbiz": """STATE OF FLORIDA - DIVISION OF CORPORATIONS
2024 ANNUAL REPORT

Document Number: N85000003291
FEI/EIN Number: 59-2487103
Date Filed: 02/08/2024
Status: ACTIVE

Entity Name: ULTIMAR CONDOMINIUM ASSOCIATION, INC.

Principal Address: 1340 Gulf Blvd, Clearwater Beach, FL 33767

Registered Agent: Becker & Poliakoff, P.A.
1 East Broward Blvd, Suite 1800, Fort Lauderdale, FL 33301

Officer/Director Detail:
  President:   Richard A. Hartley    1340 Gulf Blvd #T1-1402, Clearwater Beach FL 33767
  Treasurer:   Diane M. Kowalski     1340 Gulf Blvd #T2-807, Clearwater Beach FL 33767
  Secretary:   Frank J. Pellegrino   1340 Gulf Blvd #T1-1103, Clearwater Beach FL 33767
  Director:    Susan B. Chang        1340 Gulf Blvd #T2-1201, Clearwater Beach FL 33767
  Director:    George M. Andretti    1340 Gulf Blvd #T1-PH2, Clearwater Beach FL 33767
""",
        "audit": """ULTIMAR CONDOMINIUM ASSOCIATION, INC.
AUDITED FINANCIAL STATEMENTS - Year Ended December 31, 2024

INDEPENDENT AUDITORS' REPORT
Rivero, Gordimer & Company, P.A., Tampa, Florida

BALANCE SHEET - December 31, 2024

ASSETS
  Operating Cash & Equivalents         $ 1,456,230
  Assessments Receivable               $   234,800
  Prepaid Insurance                    $   412,500
  Reserve Fund - Investments           $ 3,890,120
  Other Assets                         $    89,400
  TOTAL ASSETS                         $ 6,083,050

LIABILITIES & FUND BALANCES
  Accounts Payable                     $   145,600
  Accrued Expenses                     $   198,300
  Prepaid Assessments                  $   134,700
  Total Liabilities                    $   478,600
  Operating Fund Balance               $ 1,714,330
  Reserve Fund Balance                 $ 3,890,120
  TOTAL LIABILITIES & FUND BALANCES    $ 6,083,050

NOTES TO FINANCIAL STATEMENTS

Note 1 - Organization
Twin 14-story towers, 200 units, gulf-front on Sand Key/South Clearwater
Beach. Built 1985, extensively renovated 2019-2020.

Note 4 - Insurance Coverage
  Property Insurance (Wind/Flood):
    Carrier:          Citizens Property Insurance Corporation
    Policy Number:    CIT-FL-2024-0112847
    Total Insured Value (TIV): $87,000,000
    Annual Premium:   $2,610,000
    Expiration Date:  August 15, 2025
    Deductible:       5% Named Storm / $50,000 AOP

  General Liability:
    Carrier:          Zurich Insurance Group
    Coverage:         $5,000,000 per occurrence
    Annual Premium:   $78,400

Note 5 - Reserve Study
Reserves are 54% funded per 2024 SIRS study. The Board approved a
$2.4M special assessment over 24 months to comply with SB 4-D.
""",
        "ie_report": """ULTIMAR CONDOMINIUM ASSOCIATION, INC.
INCOME & EXPENSE STATEMENT
Years Ended December 31, 2023 and December 31, 2024

                                    2024 Actual    2023 Actual    Variance
REVENUES
  Unit Owner Assessments           $4,800,000     $3,600,000     $1,200,000
  Special Assessments              $1,200,000     $        0     $1,200,000
  Interest & Investment Income     $  145,600     $   87,200     $   58,400
  Other Income                     $   67,800     $   52,300     $   15,500
  TOTAL REVENUES                   $6,213,400     $3,739,500     $2,473,900

EXPENSES
  Insurance - Property (Wind)      $2,610,000     $1,080,000     $1,530,000
  Insurance - Liability/D&O        $  112,400     $   89,200     $   23,200
  Insurance - Total                $2,722,400     $1,169,200     $1,553,200

  Management Fees                  $  264,000     $  240,000     $   24,000
  Payroll & Benefits               $  534,200     $  489,700     $   44,500
  Repairs & Maintenance            $  423,800     $  378,100     $   45,700
  Elevator Maintenance (4 units)   $  134,800     $  118,400     $   16,400
  Utilities                        $  678,900     $  612,300     $   66,600
  Reserve Contributions            $  960,000     $  480,000     $  480,000
  Other Expenses                   $  312,400     $  267,800     $   44,600
  TOTAL EXPENSES                   $6,030,500     $3,755,500     $2,275,000

NET EXCESS (DEFICIT)               $  182,900     $  (16,000)    $  198,900

NOTES:
Wind insurance increased 141.7% YoY. Citizens is sole carrier willing
to write the risk at this exposure level. Premium is 3.0% of TIV.
""",
    },
    {
        "name": "Aqualea Condominium Association, Inc.",
        "address": "280 S Gulfview Blvd, Clearwater Beach, FL 33767",
        "county": "Pinellas",
        "latitude": 27.9710,
        "longitude": -82.8260,
        "contacts": [
            {"name": "Victoria L. Brennan", "title": "President, Board of Directors"},
            {"name": "David S. Nakamura", "title": "Treasurer"},
        ],
        "sunbiz": """STATE OF FLORIDA - DIVISION OF CORPORATIONS
2024 ANNUAL REPORT

Document Number: N07000004523
FEI/EIN Number: 20-8834512
Date Filed: 03/01/2024
Status: ACTIVE

Entity Name: AQUALEA CONDOMINIUM ASSOCIATION, INC.

Principal Address: 280 S Gulfview Blvd, Clearwater Beach, FL 33767

Registered Agent: Straley Robin Vericker
1510 W Cleveland St, Tampa, FL 33606

Officer/Director Detail:
  President:   Victoria L. Brennan   280 S Gulfview Blvd #1601, Clearwater Beach FL 33767
  Treasurer:   David S. Nakamura     280 S Gulfview Blvd #PH3, Clearwater Beach FL 33767
  Secretary:   Margaret A. Collins   280 S Gulfview Blvd #1204, Clearwater Beach FL 33767
""",
        "audit": """AQUALEA CONDOMINIUM ASSOCIATION, INC.
AUDITED FINANCIAL STATEMENTS - Year Ended December 31, 2024

Tuscan & Company, P.A., Clearwater, Florida

BALANCE SHEET - December 31, 2024

ASSETS
  Operating Cash & Equivalents         $   678,340
  Assessments Receivable               $    89,100
  Prepaid Insurance                    $   198,000
  Reserve Fund - Investments           $ 2,345,670
  TOTAL ASSETS                         $ 3,311,110

Note 1 - Organization
16-story luxury beachfront high-rise, 89 units, built 2007.
Directly on Clearwater Beach. Units range $1.2M to $4.5M.

Note 4 - Insurance Coverage
  Property Insurance (Wind/Flood):
    Carrier:          Heritage Insurance Holdings (primary)
                      Lloyds of London (excess)
    Total Insured Value (TIV): $62,000,000
    Annual Premium:   $1,488,000
    Expiration Date:  November 1, 2025
    Deductible:       3% Named Storm / $25,000 AOP

  General Liability:
    Carrier:          Ironshore Insurance
    Coverage:         $3,000,000 per occurrence
    Annual Premium:   $45,200

Note 5 - Concrete Restoration
Phase 1 SIRS milestone inspection completed June 2024. Phase 2
identified $1.8M in concrete spalling repairs. Work scheduled 2025.
""",
        "ie_report": """AQUALEA CONDOMINIUM ASSOCIATION, INC.
INCOME & EXPENSE STATEMENT
Years Ended December 31, 2023 and December 31, 2024

                                    2024 Actual    2023 Actual    Variance
REVENUES
  Unit Owner Assessments           $2,670,000     $2,136,000     $ 534,000
  Special Assessments              $  445,000     $        0     $ 445,000
  Interest & Investment Income     $   89,400     $   52,100     $  37,300
  TOTAL REVENUES                   $3,204,400     $2,188,100     $1,016,300

EXPENSES
  Insurance - Property (Wind)      $1,488,000     $  623,000     $ 865,000
  Insurance - Liability/D&O        $   72,600     $   58,900     $  13,700
  Insurance - Total                $1,560,600     $  681,900     $ 878,700

  Management Fees                  $  144,000     $  132,000     $  12,000
  Payroll & Benefits               $  312,400     $  289,500     $  22,900
  Repairs & Maintenance            $  234,100     $  198,400     $  35,700
  Utilities                        $  378,200     $  345,600     $  32,600
  Reserve Contributions            $  534,000     $  356,000     $ 178,000
  Other Expenses                   $  156,800     $  134,700     $  22,100
  TOTAL EXPENSES                   $3,320,100     $2,138,100     $1,182,000

NET EXCESS (DEFICIT)               $ (115,700)    $   50,000     $(165,700)

NOTES:
Wind premium increased 138.8% YoY. Premium to TIV ratio is 2.4%.
The association ran a deficit in 2024 due to insurance cost spike.
Board approved special assessment to cover shortfall and fund reserves.
""",
    },
    {
        "name": "Sand Key Club Condominium Association, Inc.",
        "address": "1621 Gulf Blvd, Clearwater Beach, FL 33767",
        "county": "Pinellas",
        "latitude": 27.9490,
        "longitude": -82.8370,
        "contacts": [
            {"name": "Paul R. Henderson", "title": "President, Board of Directors"},
            {"name": "Janet K. Morales", "title": "Treasurer"},
            {"name": "Alan W. Fitzgerald", "title": "Secretary"},
        ],
        "sunbiz": """STATE OF FLORIDA - DIVISION OF CORPORATIONS
2024 ANNUAL REPORT

Document Number: N81000006734
FEI/EIN Number: 59-2103478
Date Filed: 01/22/2024
Status: ACTIVE

Entity Name: SAND KEY CLUB CONDOMINIUM ASSOCIATION, INC.

Principal Address: 1621 Gulf Blvd, Clearwater Beach, FL 33767

Registered Agent: Katzman Chandler
115 S Rosemary Ave, Suite 500, West Palm Beach, FL 33401

Officer/Director Detail:
  President:   Paul R. Henderson     1621 Gulf Blvd #1704, Clearwater Beach FL 33767
  Treasurer:   Janet K. Morales      1621 Gulf Blvd #803, Clearwater Beach FL 33767
  Secretary:   Alan W. Fitzgerald    1621 Gulf Blvd #1201, Clearwater Beach FL 33767
  Director:    Barbara J. Ostrowski  1621 Gulf Blvd #1502, Clearwater Beach FL 33767
""",
        "audit": """SAND KEY CLUB CONDOMINIUM ASSOCIATION, INC.
AUDITED FINANCIAL STATEMENTS - Year Ended December 31, 2024

Cherry Bekaert LLP, Tampa, Florida

BALANCE SHEET - December 31, 2024

ASSETS
  Operating Cash & Equivalents         $   934,560
  Assessments Receivable               $   156,200
  Prepaid Insurance                    $   267,000
  Reserve Fund - Investments           $ 2,678,900
  TOTAL ASSETS                         $ 4,036,660

Note 1 - Organization
17-story gulf-front high-rise, 144 units, built 1981, on Sand Key.
Major renovation completed 2021 (new windows, roof, exterior coating).

Note 4 - Insurance Coverage
  Property Insurance (Wind/Flood):
    Carrier:          Citizens Property Insurance Corporation
    Total Insured Value (TIV): $54,000,000
    Annual Premium:   $1,890,000
    Expiration Date:  May 1, 2025
    Deductible:       5% Named Storm / $25,000 AOP

  General Liability:
    Carrier:          Auto-Owners Insurance
    Coverage:         $3,000,000 per occurrence
    Annual Premium:   $52,800

Note 5 - Reserve Study
SIRS milestone inspection completed April 2024. Building rated
satisfactory with $890K in recommended maintenance over 5 years.
Reserves 71% funded. Board targeting 100% by 2030.
""",
        "ie_report": """SAND KEY CLUB CONDOMINIUM ASSOCIATION, INC.
INCOME & EXPENSE STATEMENT
Years Ended December 31, 2023 and December 31, 2024

                                    2024 Actual    2023 Actual    Variance
REVENUES
  Unit Owner Assessments           $3,456,000     $2,592,000     $ 864,000
  Special Assessments              $  720,000     $        0     $ 720,000
  Interest & Investment Income     $  112,300     $   67,800     $  44,500
  Other Income                     $   45,600     $   38,200     $   7,400
  TOTAL REVENUES                   $4,333,900     $2,698,000     $1,635,900

EXPENSES
  Insurance - Property (Wind)      $1,890,000     $  756,000     $1,134,000
  Insurance - Liability/D&O        $   82,400     $   67,200     $   15,200
  Insurance - Total                $1,972,400     $  823,200     $1,149,200

  Management Fees                  $  192,000     $  180,000     $   12,000
  Payroll & Benefits               $  423,600     $  398,700     $   24,900
  Repairs & Maintenance            $  312,500     $  278,400     $   34,100
  Elevator Maintenance (3 units)   $   89,400     $   78,600     $   10,800
  Utilities                        $  534,200     $  489,300     $   44,900
  Reserve Contributions            $  691,200     $  518,400     $  172,800
  Other Expenses                   $  189,600     $  156,400     $   33,200
  TOTAL EXPENSES                   $4,404,900     $2,923,000     $1,481,900

NET EXCESS (DEFICIT)               $  (71,000)    $ (225,000)    $ 154,000

NOTES:
Wind insurance surged 150% YoY. Premium to TIV ratio is 3.5% — one of
the highest in Pinellas County. Citizens is only market option at this
exposure. Board exploring captive insurance alternatives for 2025.
""",
    },
    {
        "name": "Sirata Beach Resort Condominium Association, Inc.",
        "address": "5300 Gulf Blvd, St Pete Beach, FL 33706",
        "county": "Pinellas",
        "latitude": 27.7250,
        "longitude": -82.7390,
        "contacts": [
            {"name": "Christine M. Aldridge", "title": "President, Board of Directors"},
            {"name": "Robert T. Vasquez", "title": "Treasurer"},
            {"name": "William H. Park", "title": "Secretary"},
        ],
        "sunbiz": """STATE OF FLORIDA - DIVISION OF CORPORATIONS
2024 ANNUAL REPORT

Document Number: N90000008956
FEI/EIN Number: 59-3012567
Date Filed: 02/14/2024
Status: ACTIVE

Entity Name: SIRATA BEACH RESORT CONDOMINIUM ASSOCIATION, INC.

Principal Address: 5300 Gulf Blvd, St Pete Beach, FL 33706

Registered Agent: Becker & Poliakoff, P.A.
1 East Broward Blvd, Suite 1800, Fort Lauderdale, FL 33301

Officer/Director Detail:
  President:   Christine M. Aldridge  5300 Gulf Blvd #T3-1302, St Pete Beach FL 33706
  Treasurer:   Robert T. Vasquez      5300 Gulf Blvd #T1-804, St Pete Beach FL 33706
  Secretary:   William H. Park        5300 Gulf Blvd #T2-1106, St Pete Beach FL 33706
  Director:    Lisa A. Drummond       5300 Gulf Blvd #T1-PH1, St Pete Beach FL 33706
  Director:    Michael C. Reeves      5300 Gulf Blvd #T3-607, St Pete Beach FL 33706
""",
        "audit": """SIRATA BEACH RESORT CONDOMINIUM ASSOCIATION, INC.
AUDITED FINANCIAL STATEMENTS - Year Ended December 31, 2024

Thomas Howell Ferguson P.A., Tampa, Florida

BALANCE SHEET - December 31, 2024

ASSETS
  Operating Cash & Equivalents         $ 2,134,560
  Assessments Receivable               $   378,900
  Prepaid Insurance                    $   534,000
  Reserve Fund - Investments           $ 4,567,890
  Fixed Assets (net)                   $   289,400
  TOTAL ASSETS                         $ 7,904,750

Note 1 - Organization
Multi-building beachfront resort complex, 3 towers (13 stories each),
382 units total. Built 1990, major renovation 2018. Gulf-front on
St. Pete Beach. Mix of owner-occupied and rental pool units.

Note 4 - Insurance Coverage
  Property Insurance (Wind/Flood):
    Carrier:          Citizens Property Insurance Corporation (primary)
                      Florida Specialty Insurance (excess)
    Total Insured Value (TIV): $142,000,000
    Annual Premium:   $4,970,000
    Expiration Date:  July 1, 2025
    Deductible:       5% Named Storm / $100,000 AOP

  General Liability:
    Carrier:          Zurich Insurance Group
    Coverage:         $5,000,000 per occurrence / $10,000,000 aggregate
    Annual Premium:   $134,200

  Umbrella:
    Carrier:          AIG
    Coverage:         $25,000,000
    Annual Premium:   $112,800

Note 5 - Hurricane Idalia Impact
Minor damage from Hurricane Idalia (2023) — $340K in claims paid.
Post-storm inspection satisfactory. SIRS Phase 1 completed Oct 2024.
""",
        "ie_report": """SIRATA BEACH RESORT CONDOMINIUM ASSOCIATION, INC.
INCOME & EXPENSE STATEMENT
Years Ended December 31, 2023 and December 31, 2024

                                    2024 Actual    2023 Actual    Variance
REVENUES
  Unit Owner Assessments           $9,168,000     $6,876,000     $2,292,000
  Special Assessments              $1,910,000     $        0     $1,910,000
  Interest & Investment Income     $  234,500     $  145,600     $   88,900
  Rental Pool Revenue Share        $  456,000     $  412,000     $   44,000
  Other Income                     $  123,400     $   98,700     $   24,700
  TOTAL REVENUES                   $11,891,900    $7,532,300     $4,359,600

EXPENSES
  Insurance - Property (Wind)      $4,970,000     $1,987,000     $2,983,000
  Insurance - Liability/Umbrella   $  312,400     $  245,600     $   66,800
  Insurance - D&O / Fidelity       $   45,600     $   38,200     $    7,400
  Insurance - Total                $5,328,000     $2,270,800     $3,057,200

  Management Fees                  $  456,000     $  420,000     $   36,000
  Payroll & Benefits               $  978,400     $  912,300     $   66,100
  Repairs & Maintenance            $  756,800     $  689,400     $   67,400
  Elevator Maintenance (6 units)   $  198,400     $  178,200     $   20,200
  Utilities                        $1,234,500     $1,123,400     $  111,100
  Security & Fire Watch            $  267,800     $  234,500     $   33,300
  Reserve Contributions            $1,833,600     $  917,000     $  916,600
  Other Expenses                   $  478,900     $  412,300     $   66,600
  TOTAL EXPENSES                   $11,532,400    $7,157,900     $4,374,500

NET EXCESS (DEFICIT)               $  359,500     $  374,400     $  (14,900)

NOTES:
Wind premium surged 150.1% YoY. At $4.97M annual premium on $142M TIV,
the wind ratio is 3.5% — highest in the association's history. Citizens
is primary carrier with Florida Specialty on excess layer. Board
authorized $1.91M special assessment to cover the premium increase.
The association is actively seeking alternative market quotes for 2025.
""",
    },
]


# Jason's actual customers — already converted, full pipeline
CUSTOMER_PROPERTIES = [
    {
        "name": "Clearwater Point Condominiums",
        "address": "500 N Osceola Ave, Clearwater, FL 33755",
        "county": "Pinellas",
        "latitude": 27.9720,
        "longitude": -82.7990,
        "pipeline_stage": "CUSTOMER",
        "characteristics": {
            "stories": 11,
            "construction": "Fire Resistive",
            "year_built": 1975,
            "tiv": "$24,000,000",
            "carrier": "Citizens Property Insurance Corporation",
            "premium": "$720,000",
            "expiration": "March 1, 2026",
            "deductible": "3% Named Storm",
            "decision_maker": "Board President",
            "key_risks": ["Aging structure", "Coastal wind exposure", "SIRS compliance"],
            "notes": "Long-term customer. Renewed 2024. Good loss history.",
        },
        "contacts": [
            {"name": "Property Manager", "title": "Community Association Manager"},
        ],
    },
    {
        "name": "Gulfview Condominiums",
        "address": "530 Gulfview Blvd, Clearwater, FL 33767",
        "county": "Pinellas",
        "latitude": 27.9700,
        "longitude": -82.8250,
        "pipeline_stage": "CUSTOMER",
        "characteristics": {
            "stories": 8,
            "construction": "Fire Resistive",
            "tiv": "$26,000,000",
            "carrier": "Heritage Insurance Holdings",
            "premium": "$780,000",
            "expiration": "June 15, 2026",
            "deductible": "5% Named Storm",
            "decision_maker": "Board President",
            "key_risks": ["Direct beachfront exposure", "Hurricane surge zone"],
            "notes": "Clearwater Beach location. Competitive market — watch for poaching.",
        },
        "contacts": [
            {"name": "Property Manager", "title": "Community Association Manager"},
        ],
    },
    {
        "name": "Boca Bayou Condominiums",
        "address": "5500 NW 2nd Ave, Boca Raton, FL 33487",
        "county": "Palm Beach",
        "latitude": 26.3780,
        "longitude": -80.0870,
        "pipeline_stage": "CUSTOMER",
        "characteristics": {
            "stories": 7,
            "construction": "Fire Resistive",
            "year_built": 1970,
            "tiv": "$19,000,000",
            "carrier": "Slide Insurance Company",
            "premium": "$475,000",
            "expiration": "September 1, 2026",
            "deductible": "3% Named Storm",
            "decision_maker": "Board President",
            "key_risks": ["Aging 1970s structure", "SB 4-D milestone inspection due"],
            "notes": "Boca Raton expansion account. Stable board, good reserves.",
        },
        "contacts": [
            {"name": "Property Manager", "title": "Community Association Manager"},
        ],
    },
    {
        "name": "1451 Brickell Condominiums",
        "address": "1451 Brickell Ave, Miami, FL 33131",
        "county": "Miami-Dade",
        "latitude": 25.7550,
        "longitude": -80.1900,
        "pipeline_stage": "CUSTOMER",
        "characteristics": {
            "stories": 56,
            "construction": "Fire Resistive",
            "year_built": 2017,
            "tiv": "$105,000,000",
            "carrier": "Lloyds of London",
            "premium": "$3,150,000",
            "expiration": "December 1, 2025",
            "deductible": "5% Named Storm / $100,000 AOP",
            "decision_maker": "Board President",
            "key_risks": ["High-rise wind exposure", "Brickell flood zone", "Large TIV concentration"],
            "notes": "Flagship account. Newer construction, impact glass throughout. Multi-layered program.",
        },
        "contacts": [
            {"name": "Property Manager", "title": "Community Association Manager"},
        ],
    },
    {
        "name": "Saltaire St. Petersburg",
        "address": "301 1st St S, Saint Petersburg, FL 33701",
        "county": "Pinellas",
        "latitude": 27.7700,
        "longitude": -82.6350,
        "pipeline_stage": "CUSTOMER",
        "characteristics": {
            "stories": 34,
            "construction": "Fire Resistive",
            "year_built": 2023,
            "tiv": "$180,000,000",
            "opening_protection": "Impact rated",
            "carrier": "Zurich Insurance Group",
            "premium": "$3,600,000",
            "expiration": "April 1, 2026",
            "deductible": "3% Named Storm / $50,000 AOP",
            "decision_maker": "Board President",
            "key_risks": ["New construction premium adjustment", "Waterfront exposure", "Large TIV"],
            "notes": "Newest and largest account. Brand new building, excellent construction credits. Premium account.",
        },
        "contacts": [
            {"name": "Property Manager", "title": "Community Association Manager"},
        ],
    },
    {
        "name": "Isla Del Sol Condominiums",
        "address": "400 64th Ave, St. Petersburg, FL 33706",
        "county": "Pinellas",
        "latitude": 27.7280,
        "longitude": -82.7340,
        "pipeline_stage": "CUSTOMER",
        "characteristics": {
            "stories": 13,
            "construction": "Fire Resistive",
            "year_built": 1973,
            "tiv": "$26,000,000",
            "carrier": "Citizens Property Insurance Corporation",
            "premium": "$910,000",
            "expiration": "August 1, 2026",
            "deductible": "5% Named Storm",
            "decision_maker": "Board President",
            "key_risks": ["1973 construction", "Wind mitigation credits limited", "Isla Del Sol flood zone"],
            "notes": "Solid renewal account. Near Sirata Beach. Good referral source for nearby properties.",
        },
        "contacts": [
            {"name": "Property Manager", "title": "Community Association Manager"},
        ],
    },
]


# Jason's broker profile
BROKER_PROFILE = {
    "name": "Jason L. Dillon",
    "title": "Commercial Insurance Advisor",
    "company": "The Hilb Group",
    "email": "Jdillon@hilbgroup.com",
    "phone_office": "(727) 450-7934",
    "phone_cell": "(814) 659-5491",
    "address": "28100 US Hwy. 19 N Suite 201, Clearwater, FL 33761",
    "signature_block": """Jason L. Dillon
Commercial Insurance Advisor
The Hilb Group
28100 US Hwy. 19 N Suite 201
Clearwater, FL 33761
(727) 450-7934 office | (814) 659-5491 cell
Jdillon@hilbgroup.com""",
    "preferences": {
        "default_tone": "informal",
        "follow_up_days": 14,
        "max_auto_emails_per_day": 5,
        "target_counties": [
            "Pasco", "Pinellas", "Hillsborough", "Manatee", "Sarasota",
            "Charlotte", "Lee", "Collier", "Palm Beach", "Miami-Dade", "Broward",
        ],
        "min_tiv_target": 15000000,
        "min_stories": 3,
    },
}


def seed():
    db = SessionLocal()
    try:
        # --- Seed broker profile ---
        existing_broker = db.query(BrokerProfile).filter(BrokerProfile.email == BROKER_PROFILE["email"]).first()
        if existing_broker:
            print(f"  Broker exists: {BROKER_PROFILE['name']}")
        else:
            broker = BrokerProfile(**BROKER_PROFILE)
            db.add(broker)
            db.commit()
            print(f"  Created broker profile: {BROKER_PROFILE['name']}")

        # --- Seed prospect leads (with full docs) ---
        for prop in SEED_PROPERTIES:
            existing = db.query(Entity).filter(Entity.name == prop["name"]).first()
            if existing:
                print(f"  Skipping (exists): {prop['name']}")
                continue

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

            for contact in prop["contacts"]:
                c = Contact(
                    entity_id=entity.id,
                    name=contact["name"],
                    title=contact["title"],
                )
                db.add(c)

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

            ledger = LeadLedger(
                entity_id=entity.id,
                action_type=ActionType.HUNT_FOUND,
            )
            db.add(ledger)

            db.commit()
            print(f"  Seeded 3 docs + {len(prop['contacts'])} contacts for {prop['name']}")

        # --- Seed customer properties (already converted) ---
        for cust in CUSTOMER_PROPERTIES:
            existing = db.query(Entity).filter(Entity.name == cust["name"]).first()
            if existing:
                print(f"  Skipping (exists): {cust['name']}")
                continue

            entity = Entity(
                name=cust["name"],
                address=cust["address"],
                county=cust["county"],
                latitude=cust["latitude"],
                longitude=cust["longitude"],
                characteristics=cust["characteristics"],
                pipeline_stage=cust["pipeline_stage"],
            )
            db.add(entity)
            db.commit()
            db.refresh(entity)
            print(f"  Created customer: {cust['name']} (id={entity.id})")

            for contact in cust.get("contacts", []):
                c = Contact(entity_id=entity.id, name=contact["name"], title=contact["title"])
                db.add(c)

            # Customers get the full ledger trail
            for action in [ActionType.HUNT_FOUND, ActionType.USER_THUMB_UP]:
                db.add(LeadLedger(entity_id=entity.id, action_type=action))

            # Create Policy record from characteristics
            chars = cust["characteristics"]
            premium_str = chars.get("premium", "")
            tiv_str = chars.get("tiv", "")
            premium_val = float(re.sub(r'[^\d.]', '', str(premium_str))) if premium_str else None
            tiv_val = float(re.sub(r'[^\d.]', '', str(tiv_str))) if tiv_str else None

            policy = Policy(
                entity_id=entity.id,
                coverage_type="WIND",
                carrier=chars.get("carrier"),
                premium=premium_val,
                tiv=tiv_val,
                deductible=chars.get("deductible"),
                expiration=chars.get("expiration"),
                is_active=1,
                notes=chars.get("notes", ""),
            )
            db.add(policy)

            db.commit()
            print(f"  Seeded customer + policy: {cust['name']} ({cust['pipeline_stage']})")

        print("\nSeed complete!")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
