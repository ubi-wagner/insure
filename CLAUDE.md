# CLAUDE.md — Insure CRM System Guide

## What This Project Is

**Insure** is a commercial property insurance lead generation CRM built for a Florida insurance broker (Jason). It discovers, enriches, scores, and manages leads from FL condominium associations and multi-tenant commercial properties across 11 target coastal counties.

The system seeds from FL DOR NAL tax roll files (ground truth for every FL property parcel), geocodes via US Census batch API, then continuously enriches with data from 13 automated enrichers pulling from FEMA, DBPR, Sunbiz, Citizens Insurance, FL OIR, and county property appraisers.

**Target properties:** $10M+ market value condos, apartments, multi-family (10+ units), and independent hotels in Broward, Charlotte, Collier, Hillsborough, Lee, Manatee, Miami-Dade, Palm Beach, Pasco, Pinellas, and Sarasota counties.

---

## Architecture

### Stack
- **Backend:** Python 3.11, FastAPI, SQLAlchemy, PostgreSQL, Alembic migrations
- **Frontend:** Next.js 15 (App Router), React, TypeScript, Tailwind CSS, Leaflet maps
- **Deployment:** Railway (backend + frontend as separate services), S3 bucket for file persistence
- **Background Workers:** Daemon threads for geocoding, enrichment, and scheduled data refresh

### Repository Structure
```
insure/
├── backend/
│   ├── main.py                    # FastAPI app, worker startup, lifespan
│   ├── database/
│   │   ├── __init__.py            # Engine, SessionLocal, pool config
│   │   └── models.py             # Entity, Contact, Policy, Engagement, etc.
│   ├── routes/
│   │   ├── leads.py              # /api/leads — list, detail, stage, contacts, upload
│   │   ├── admin.py              # /api/admin/* — seed, reset, download, files, query
│   │   ├── events.py             # /api/events — event stream (SSE + REST)
│   │   └── status.py             # /api/status — service registry
│   ├── agents/
│   │   ├── seeder.py             # NAL file parser, entity creation
│   │   ├── associator.py         # Census batch geocoding, TARGET→LEAD promotion
│   │   ├── enrichment_worker.py  # Continuous LEAD enrichment loop
│   │   └── enrichers/            # 13 enricher modules (see below)
│   ├── services/
│   │   ├── event_bus.py          # In-memory event ring buffer + SSE
│   │   ├── registry.py           # Service health registry + heartbeats
│   │   └── timebomb.py           # Scheduled event system (data refresh triggers)
│   ├── scripts/
│   │   ├── download_cadastral.py # ArcGIS parcel geometry downloader
│   │   ├── download_sunbiz.py    # Sunbiz quarterly corporate extract downloader
│   │   └── data_refresh.py       # Unified data refresh (DOR, DBPR, Sunbiz, ArcGIS)
│   └── filestore/                # Local file storage (synced to/from S3)
│       └── System Data/
│           ├── DOR/              # NAL + SDF tax roll files per county
│           ├── DBPR/             # Condo registry + payment CSVs
│           ├── Sunbiz/           # Quarterly corporate extracts
│           └── ArcGIS/           # Cadastral parcel downloads
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx          # Dashboard — map + pipeline + modal manager
│       │   ├── lead/[id]/page.tsx # Full lead detail page (standalone)
│       │   ├── ops/page.tsx      # Ops center — pipeline, counties, services, query, events
│       │   ├── ref/page.tsx      # Reference links — data sources, PA sites, statutes
│       │   ├── files/page.tsx    # File manager
│       │   └── login/page.tsx    # Authentication
│       └── components/
│           ├── LeadPipeline.tsx   # Pipeline card list with filters, bulk actions
│           ├── EntityDetailModal.tsx # Slide-in detail panel (max 5 open)
│           ├── MapView.tsx        # Leaflet map wrapper (SSR-safe)
│           └── MapViewInner.tsx   # Leaflet implementation (markers, search, legend)
```

---

## 5-Stage Pipeline

```
TARGET → LEAD → OPPORTUNITY → CUSTOMER → ARCHIVED
```

| Stage | How entities enter | What happens |
|-------|-------------------|--------------|
| **TARGET** | NAL seeder creates from tax roll data | Raw parcel, no coordinates yet |
| **LEAD** | Associator geocodes via Census batch API | Auto-promoted, enrichers run continuously |
| **OPPORTUNITY** | User manually promotes from LEAD | CRM engagement begins |
| **CUSTOMER** | User converts from OPPORTUNITY | Deal closed |
| **ARCHIVED** | User dismisses at any stage | Data preserved for later |

**Auto-advance:** Only TARGET→LEAD (on successful geocoding). Everything else is manual.

---

## Enrichment Pipeline (13 Enrichers)

All enrichers run on LEAD-stage entities. Each writes to `entity.characteristics` (JSONB) and records itself in `entity.enrichment_sources`.

| # | Enricher | Source | What it provides |
|---|----------|--------|-----------------|
| 1 | `fema_flood` | FEMA NFHL REST API | Flood zone, SFHA, base elevation, risk level |
| 2 | `property_appraiser` | County PA GIS + links | Assessed value, parcel lookup, owner |
| 3 | `dbpr_bulk` | DBPR CSV extracts | Condo name, managing entity, project #, status |
| 4 | `dbpr_payments` | DBPR payment CSVs | Delinquency history, pending amounts |
| 5 | `dbpr_sirs` | DBPR SIRS portal | Structural reserve study compliance |
| 6 | `dbpr_building` | DBPR building portal | Building count, stories, units, assessments |
| 7 | `cam_license` | CAM CSV | License #, name, expiration, active status |
| 8 | `sunbiz_bulk` | Sunbiz quarterly extract | Officers, registered agent, filing status |
| 9 | `dor_nal` | DOR NAL files | Supplemental tax roll cross-reference |
| 10 | `citizens_insurance` | Heuristic scoring | Citizens likelihood, swap opportunity |
| 11 | `fdot_parcels` | FDOT GIS API | Alternate parcel data source |
| 12 | `oir_market` | OIR market intel | Premium estimates, carrier options, wind tier |
| 13 | `cream_score` | Final scoring (runs last) | 0-100 conversion opportunity rating |

### DBPR Matching Strategy
Address-first matching (street number + name overlap), county bonus, owner name cross-match. Threshold: 35 points. The DBPR CSVs contain ~9K FL condo associations.

### Cream Score (0-100)
Identifies the highest-value conversion opportunities:
- **Property size/value:** up to 25pts ($100M+=25, $50M+=20, $25M+=15, $10M+=10)
- **Wind exposure:** up to 20pts (10+ stories=15, high-wind county=5)
- **Insurance pain:** up to 20pts (Citizens=15, hard market=5, Ian zone=3)
- **Contact/governance:** up to 20pts (email=10, decision maker=7, management=5)
- **Compliance pressure:** up to 15pts (SIRS non-compliant=10, delinquent=5)
- **Tiers:** platinum (90+), gold (70-89), silver (50-69), bronze (30-49), prospect (0-29)

### Heat Score (cold/warm/hot)
Data completeness indicator (not conversion quality):
- hot >= 35 points, warm >= 18 points, cold < 18

---

## Data Sources

### Primary (seed data)
- **FL DOR NAL files** — Tab-delimited CSV, one per county, every real property parcel in FL. DOR county numbers are alphabetical (NOT FIPS): 16=Broward, 18=Charlotte, 21=Collier, 23=Miami-Dade, 39=Hillsborough, 46=Lee, 51=Manatee, 60=Palm Beach, 61=Pasco, 62=Pinellas, 68=Sarasota.
- **Target DOR use codes:** 004 (Condo), 005 (Co-op), 006 (Retirement), 008 (Multi-Family 10+), 039 (Hotels)

### Auto-downloadable
- **DBPR CSVs:** Direct HTTP from `myfloridalicense.com/sto/file_download/extracts/`
- **Sunbiz Corporate:** SFTP at `sftp.floridados.gov` (user: Public, pass: PubAccess1845!)
- **ArcGIS Cadastral:** REST API query per county
- **DOR NAL/SDF:** Direct HTTP from `floridarevenue.com/property/dataportal/`

### Scheduled Refresh (Timebomb system)
- **Daily 2am UTC:** DBPR condo registry + payment history
- **Weekly Sunday 3am UTC:** Full refresh (DOR + DBPR + Sunbiz + ArcGIS)

---

## Database

### Key Tables
- **entities** — Main table. ~5-15K records (after $10M filter). JSONB `characteristics` holds all enrichment data. JSONB `enrichment_sources` tracks what enrichers ran.
- **contacts** — Officers, board members, management contacts. FK to entity.
- **policies** — Insurance policies (when known). FK to entity.
- **engagements** — Outreach history. FK to entity.
- **entity_assets** — Uploaded documents. FK to entity.
- **lead_ledger** — Audit trail of all actions.

### SQLAlchemy Notes
- **JSONB mutation detection:** Always shallow-copy before mutating: `chars = dict(entity.characteristics or {})`. Never mutate in-place.
- **Connection pool:** `pool_pre_ping=True`, `pool_recycle=1800`, `pool_size=5`, `max_overflow=10`
- **Nullable fields:** `latitude`, `longitude`, `heat_score`, `folder_path`, `enrichment_status` can all be NULL.

---

## Frontend

### Dashboard (page.tsx)
Split layout: Leaflet map (left) + pipeline card list (right). Mobile: tabbed.

### Entity Detail Modal (EntityDetailModal.tsx)
Max 5 modals open simultaneously. 6th auto-closes oldest. Tab bar at bottom. Sections auto-hide when data is empty. `DataRow` and `DataSection` helper components.

### Pipeline Filters
- DOR use code, min stories, heat score, cream tier, county, min/max value, Citizens-only checkbox
- "Best Opportunity" (cream score) as default sort
- Bulk actions: promote all filtered, archive all filtered

### Ops Center (ops/page.tsx)
- **Pipeline tab:** Stage funnel counts, enrichment coverage with progress bars, active workers, clickable drill-down
- **Counties tab:** NAL/SDF file status, seed/reseed buttons, Reset DB, Pull ArcGIS, Pull Sunbiz, Refresh All Data
- **Services tab:** Worker health cards with heartbeat times
- **Query tab:** Data explorer with canned queries (All Condos, Citizens Properties, Hot Leads, etc.)
- **Events tab:** Live SSE event stream

### Reference Page (ref/page.tsx)
Curated links to all FL data sources: DOR, ArcGIS, DBPR (SIRS, building reports, public records), Sunbiz (bulk downloads), FEMA, UF GeoPlan wind data, Citizens, FDOT, Census geocoder, OIR rate filings.

---

## API Endpoints

### Leads
- `GET /api/leads` — List with filters, sorting, pagination (max 1000)
- `GET /api/leads/{id}` — Full detail with policies, contacts, engagements, assets, readiness
- `POST /api/leads/{id}/stage` — Change pipeline stage
- `POST /api/leads/{id}/contacts` — Add contact
- `POST /api/leads/{id}/upload` — Upload document (max 50MB)
- `POST /api/leads/{id}/vote` — Record action
- `POST /api/leads/{id}/engagements` — Create outreach
- `POST /api/leads/bulk-stage` — Bulk stage change (max 1000 IDs, requires filter)

### Admin
- `POST /api/admin/reset` — TRUNCATE CASCADE all entity data
- `POST /api/admin/seed-county/{co_no}` — Seed one county from NAL
- `POST /api/admin/seed-all` — Seed all counties
- `POST /api/admin/download-cadastral` — Pull ArcGIS parcel data
- `POST /api/admin/download-sunbiz` — Pull Sunbiz corporate extract
- `POST /api/admin/refresh-data` — Refresh all data sources
- `POST /api/admin/refresh-dbpr` — Refresh DBPR CSVs only
- `POST /api/admin/refresh-dor` — Refresh DOR NAL/SDF files
- `GET /api/admin/counties` — County file status
- `GET /api/admin/enrich/status` — Enrichment coverage stats
- `GET /api/admin/timebombs` — List scheduled events
- `GET /api/admin/query` — Data explorer (max 500 results)

### Files
- `GET /api/files` — List folder contents
- `POST /api/files/upload` — Upload with chunked support
- `POST /api/files/folder` — Create folder
- `DELETE /api/files` — Delete file/folder

---

## Coding Standards

### Python (Backend)
- SQLAlchemy JSONB: Always `dict(entity.characteristics or {})` before mutation
- All `db.commit()` wrapped in try/except with `db.rollback()`
- `.isoformat()` always guarded: `x.isoformat() if x else None`
- External API calls: always explicit `timeout`, retry with exponential backoff
- File paths: always `os.path.basename()` on user-supplied filenames
- Query limits: always bounded (`ge=1, le=N`)
- Enrichers: return `True` if any data was written (even just a lookup URL)

### TypeScript (Frontend)
- Nullable DB fields typed as `T | null` (latitude, longitude, heat_score, etc.)
- `.filter()` with type predicates for narrowing: `(l): l is Type => l.x != null`
- Non-null assertions `!` only after explicit null guard on same line
- All `.json()` calls guarded with `.catch(() => ({ error: ... }))`
- All user-facing mutations surface errors (not just console.log)
- `??` for value coalescing (never `||` — 0 is valid for TIV, units, etc.)

### Data Flow
```
NAL File → Seeder → Entity (TARGET)
              ↓
Census Geocoder → Entity (LEAD) + folder_path created
              ↓
Enrichers (13) → characteristics JSONB populated
              ↓
Cream Score → cream_score + cream_tier computed
              ↓
Frontend → filters by tier → Jason calls the platinum leads
```

---

## Current State (as of April 2026)

### Working
- NAL seeding from all 11 counties ($10M+ filter, 10+ units)
- Census batch geocoding (1000/cycle, ~16% match rate)
- 13 enrichers registered and running continuously
- Cream score with platinum/gold/silver/bronze tiers
- Entity detail modals (max 5), pipeline filters, map interaction
- Automated data refresh (daily DBPR, weekly full)
- Timebomb event scheduler
- Per-entity UUID folder structure on LEAD promotion
- S3 persistence across Railway deploys

### To Complete
- **Admin authentication** — all /api/admin/* endpoints are currently unprotected
- **Sunbiz SFTP download** — needs `paramiko` in requirements.txt, falls back to HTTP
- **SIRS database scraping** — portal likely returns 403 from cloud, generates lookup URL as fallback
- **DBPR building reports** — same portal scraping limitation
- **Enrichment re-run** — enrichers currently skip if source already recorded; need a "force re-enrich" option for data refresh
- **Parcel geometry on map** — ArcGIS cadastral provides polygons but we only use centroid currently
- **Email outreach automation** — engagement creation exists but no actual email sending
- **User accounts / multi-tenant** — single broker currently, no auth beyond login cookie
- **Mobile push notifications** — for new platinum leads discovered
- **Export to CSV/Excel** — filtered lead lists for offline analysis

---

## For Claude (AI Assistant Instructions)

### When working on this codebase:
1. **Never use `||` for numeric/boolean coalescing** — use `??`. Values like `0`, `""`, `false` are meaningful.
2. **Always null-guard JSONB access** — `entity.characteristics` can be `None`/`null`. Always `dict(x or {})` in Python, `x || {}` in TS.
3. **SQLAlchemy JSONB mutation** — shallow copy before mutating, or SQLAlchemy won't detect the change.
4. **Latitude/longitude are nullable** — entities start as TARGETs without coordinates. Guard every `.toFixed()`, `setView()`, etc.
5. **DOR county numbers are NOT FIPS codes** — they're alphabetical starting at 11. The mapping is in `seeder.py:DOR_COUNTIES`.
6. **Enrichers must be idempotent** — check `if source_id in existing_sources` before running. Return `True` if data was written.
7. **The cream score is the primary lead ranking** — not heat_score. Heat is data completeness; cream is conversion opportunity.
8. **File uploads must sanitize filenames** — `os.path.basename()` always.
9. **External API calls need timeouts and retries** — Census, FEMA, FDOT, PA GIS all need explicit `timeout` and retry loops.
10. **Events are in-memory** — 500 max ring buffer, lost on restart. Not for critical audit trail (use lead_ledger for that).
11. **The target customer is a FL insurance broker** — every feature should help Jason identify, evaluate, and contact high-value commercial property insurance opportunities along the FL coast.
12. **Cream of the crop = big coastal condos with known contacts and insurance pain** — $10M+ TIV, 7+ stories, Citizens insured, SIRS non-compliant, with board/management contact info.
