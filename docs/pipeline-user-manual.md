# Insure — Pipeline & Map User Manual

A click-by-click guide for Jason. Covers everything on the main dashboard at `/`.

---

## 1. Logging In

1. Open the browser. Go to your Insure URL.
2. Enter your username (`jason`) and password.
3. You land on the dashboard.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Insure   Pipeline                  Files  Ref  Ops  Validation  ?   │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│           MAP                  │           PIPELINE LIST              │
│        (left half)             │           (right side)               │
│                                │                                       │
│       ★    ★    ★              │     [Saved filter chips]              │
│           ★                    │     [Stage tabs]                      │
│      ★                         │     [Search · Sort · County]          │
│              ★    ★            │     ─────────────────────             │
│                                │     ┌─ Card                          │
│       ★                        │     │  building name                 │
│   ★                            │     │  address                        │
│         ★                      │     │  Owner: …                       │
│              ★                 │     │  ◎ MAP                          │
│                                │     └─ tags…                          │
│                                │                                       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. The Dashboard at a Glance

Two halves:

- **Left** — Leaflet map. Shows up to 1,000 markers for whatever's in the right-side filter.
- **Right** — Pipeline list. Stage tabs at top, scrollable cards below.

On mobile, the **Pipeline / Map** tabs (top) toggle between the two.

---

## 3. The Saved Filter Bar

This is the first row you see. It carries your named filter sets.

```
┌────────────────────────────────────────────────────────────────────┐
│ [Big Coastal · OG ×] [Citizens Hot · OG ×] [Pinellas Custom · May ×]│
│ [+ Add existing (3)]                                                │
└────────────────────────────────────────────────────────────────────┘
```

- **Click a chip** — applies that saved filter set. The chip turns **blue**. A 2-line preview drops in below it showing exactly what's set:
  ```
  County     | Use     | Min $ | Stories ≥ | Heat
  Pinellas+2 | 004,008 | $10M  | ≥7        | hot
  ```
- **× on a chip** — hides it from the top bar (doesn't delete). Survives refreshes.
- **+ Add existing (N)** — popover of every hidden filter. Click name to restore. `🗑` (only on your own) deletes forever.
- **"OG" badge (amber)** — canned filters Eric or another admin shared with you. They never go away.
- Your own filters show a date (`May 26`).

> Flip between "Citizens platinum condos" and "Sea Towers cluster" in one click. No need to open the big filter panel.

---

## 4. Search, Sort, Counties

Right below the saved-filter bar:

```
┌────────────────────────────────────────┐
│ Search: [_________________________]    │
│ County: [All Counties ▼]  Sort: [Value ▼]│
│ [Filters (3)]                           │
└────────────────────────────────────────┘
```

- **Search** — typeahead across name, address, and owner string.
- **County picker** — click to open a chip grid of all 35 counties. **All** / **None** at the top, click any chip to toggle, **Done** to close. Closed state shows `Pinellas +3` if multiple selected.
- **Sort** — value, TIV, units, year built, cream score, etc.
- **Filters (N)** — count badge shows how many filters are active. Click to expand the full panel.

---

## 5. The Filter Panel (expanded)

Click **Filters** to open. This is the build-a-new-filter workspace.

- **Use Code chips** — multi-select. `all` selects every option, `none` clears.
- **Numeric ranges** — leave blank for "any". `Coast ≤ miles` means "within X miles of the FL coastline."
- **Citizens Only** — narrow to properties heuristically flagged as currently on Citizens Insurance.
- **+ Save current** — names this filter set and adds it to the top bar. Asks if you want to share with the team.

---

## 6. The Stage Tabs

Eight stages, each with a live count:

```
┌────────────────────────────────────────────────────────────────┐
│ 5,966,570 987,365 1,176,723  0   0     0      0    0           │
│ TARGET    LEAD   VETTED  ANAL VAL OPP  CUST  ARCH              │
└────────────────────────────────────────────────────────────────┘
```

| Stage | Meaning |
|---|---|
| **TARGET** | Every raw parcel from the FL tax roll, no filtering. |
| **LEAD** | Promoted by the qualifier — actionable property type + geocoded. |
| **VETTED** | Aggregator-built building **master**. Each master ties N unit parcels together with rolled-up TIV, units, etc. |
| **ANALYZED** | Cream score + Sunbiz enrichment complete. |
| **VALIDATED** | Zillow / VRBO cross-check complete. |
| **OPPORTUNITY** | You promoted it manually — active outreach. |
| **CUSTOMER** | Deal closed. |
| **ARCHIVED** | Passed on / not interested. Click this tab to see them; each has a **Restore** button. |

> **Default tab is VETTED** — that's the actionable building list.

---

## 7. Reading a Lead Card

Every card in the list looks like this:

```
┌──────────────────────────────────────────────────────────┐
│ Echo Brickell Condominium Assoc            $44M    [hot] │  ← name + value + heat
│                                                            │
│ 1451 Brickell Ave, Miami, FL 33131                        │  ← neon cyan address
│ Owner: 1451 BRICKELL CONDOMINIUM ASSOC INC                │  ← owner (green/orange)
│                                                            │
│ ┌────────────────────────────────────────────────────┐   │
│ │                  ◎ MAP                              │   │  ← bold neon, click to fly
│ └────────────────────────────────────────────────────┘   │
│                                                            │
│ [172 parcels] [Condo] [171 units] [Built 1980] [Pinellas] │  ← tags + county
│                                                            │
│ [Open]  [ → ANALYZED ]                                    │  ← actions
└──────────────────────────────────────────────────────────┘
```

**Color meanings — trust indicators:**

| Element | Green | Orange | Why it matters |
|---|---|---|---|
| **Name** | Auditor-confirmed (PA enricher OR DOR owner reads like an association) | Aggregator synthesized it OR raw person name | Orange = verify the building name |
| **Owner** | County PA provided this string | DOR tax roll only — no auditor confirmation | Orange = DOR may show a trustee instead of decision-maker |
| **Address** | Always neon cyan | — | — |
| **Units count** | Always neon green | — | Building's total physical unit count |
| **TIV** | `*` = aggregator estimate; Zillow/VRBO refines at VALIDATED | — | — |

**Heat pill:** `hot` 35+ pts · `warm` 18+ · `cold` <18 (data completeness, not conversion quality).

**Actions row:**
- **Open** — opens the slide-in detail modal.
- **→ ANALYZED** (or next stage) — promotes one stage forward.

---

## 8. The Map

Shows up to 1,000 markers for whatever's in your current filter — not just the page-50 you see.

- **Click a card** → map flies to it.
- **Click `◎ MAP` line** → same thing, more deliberate.
- **Click a marker** → opens detail modal AND scrolls the card into view.
- **Hover a card** → marker pulses.
- **Top-right of map** — Street / Satellite / Hybrid toggle.

---

## 9. Opening a Card (the detail modal)

Click **Open** or a map marker. A panel slides in from the right.

- **Stage dropdown** — set to any stage. Use to manually archive without bulk-action mode.
- **Tabs at the bottom-left** track every modal you have open (up to 10). Closing one falls back to the previous.
- **Pipeline stage** below the name reads green when ≥VETTED, gray earlier.

---

## 10. Linked Parcels & Board Members

The most important panel for outreach research. Inside the modal, click **▶ N linked unit parcels** in the teal banner.

```
┌─────────────────────────────────────────────────────────────────┐
│ VETTED master · 171 linked unit parcels · sum $343M             │
│ ★ 5 on board  (1451 BRICKELL CONDOMINIUM ASSOC INC)             │
│                                                                  │
│ Unit  Owner                              Sqft   JV       TIV est.│
│ ─────────────────────────────────────────────────────────────── │
│ 102   ★ President  ANDERS, ROBERT       1,890  $1.4M   $2.1M  PA↗│
│ 405   ★ Treasurer  WALSH, MICHAEL       1,890  $1.5M   $2.2M  PA↗│
│ 502    MILLER, SARAH                    1,200  $980K   $1.4M  PA↗│
│ 701    O'BRIEN TRUST                    2,400  $2.1M   $3.0M  PA↗│
│ 1001  ★ Vice Pres  TANG, LISA           2,400  $2.3M   $3.3M  PA↗│
└─────────────────────────────────────────────────────────────────┘
```

- **Amber ★ row** — this unit owner is on the association board. Title comes from Sunbiz officers. **These are the calls.**
- **Unit column** — click the number → opens that unit as another modal in the same stack.
- **PA ↗** — direct deep-link to the county Property Appraiser's parcel page.
- **`other ↗`** (small amber) — opens PA's search-by-owner-name results — every property that board member owns in the county.

---

## 11. Bulk Actions

Above the cards, an action bar. Click **Select** to enter select mode:

```
[ 3 selected ]  [ All (12,847) ]  [ → ANALYZED (3) ]  [ Archive (3) ]
```

- **All (12,847)** — selects every match across all pages. Beyond 1,000 items a sentinel ("all 12,847 selected") routes through the server's filter endpoint so the SQL UPDATE moves every match.
- **→ ANALYZED (N)** — promote selected to next stage.
- **Archive (N)** — hide them from normal views. Restorable from ARCHIVED tab.

---

## 12. Trust Cheat Sheet

| What you see | What it tells you |
|---|---|
| **Green name + green owner** | Both came from county auditor. Highest confidence. |
| **Green name + orange owner** | Building name confirmed; owner string from DOR (may be trustee/LLC). |
| **Orange name + orange owner** | Aggregator-synthesized label, no auditor confirmation. Verify. |
| **`*` after TIV** | Estimate, not a real policy value. Firms up at VALIDATED. |
| **`★ President` amber** | Unit owner on the board. Priority call. |
| **`rollup ×N` teal** | Card shows building total (TIV/units summed across N parcels). |
| **"unit parcel only" amber** | Matched a single unit, not the building. Year/ISO trustworthy; TIV/units aren't. |
| **Heat = hot** | ≥35 data-completeness points. |
| **Cream tier = platinum (90+)** | High-value conversion opportunity. **Call first.** |

---

## 13. Typical Daily Flow

1. Log in → lands on VETTED.
2. Top bar: click "Platinum Coastal" → preview row shows what's active.
3. Look at the map: where are the dots clustered?
4. Sort by "Cream score: high".
5. Open the top card. Expand linked parcels. Find the amber ★ rows.
6. Click `other ↗` on the President → see what else she owns in the county.
7. Click `open on county PA ↗` on the master parcel for building data.
8. Click `Sunbiz entities at this address` → get the association corp name.
9. Add a contact, log an engagement, promote to OPPORTUNITY.
10. Next card.

---

## If Something Looks Wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| "miles from coast" filter returns nothing | Distance not backfilled on legacy rows | Ask Eric to run **Backfill ocean dist** in Ops |
| Master shows synthesized name | 0001 relabel hasn't run since aggregation | Ask Eric to run **Relabel 0001 names** in Ops |
| Map shows no markers | Filter is narrow and zero matches | Look at the green "X total" number |
| Card list slow to load | Indexes still building | Wait 30 min after deploy or click **Build Indexes** |
