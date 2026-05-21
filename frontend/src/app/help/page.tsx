"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import UserMenu from "@/components/UserMenu";

interface Section {
  id: string;
  label: string;
}

const SECTIONS: Section[] = [
  { id: "welcome", label: "Welcome" },
  { id: "login", label: "Logging In" },
  { id: "pipeline-map", label: "Pipeline + Map Walkthrough" },
  { id: "dashboard", label: "The Dashboard" },
  { id: "finding-leads", label: "Finding the Best Leads" },
  { id: "lead-card", label: "Reading a Lead Card" },
  { id: "data-tags", label: "Data Quality Tags" },
  { id: "validating", label: "Validating a Lead" },
  { id: "fixing-data", label: "Fixing Wrong Data" },
  { id: "contacts", label: "Adding Contacts" },
  { id: "pipeline", label: "Moving Through the Pipeline" },
  { id: "outreach", label: "Recording Outreach" },
  { id: "uploads", label: "Uploading Documents" },
  { id: "cream-score", label: "Cream Score Explained" },
  { id: "ops", label: "The Ops Page" },
  { id: "faq", label: "Common Questions" },
  { id: "glossary", label: "Glossary" },
  { id: "troubleshooting", label: "Troubleshooting" },
];

export default function HelpPage() {
  const [activeId, setActiveId] = useState<string>("welcome");

  useEffect(() => {
    const handler = () => {
      for (const s of SECTIONS) {
        const el = document.getElementById(s.id);
        if (!el) continue;
        const rect = el.getBoundingClientRect();
        if (rect.top >= 0 && rect.top < 300) {
          setActiveId(s.id);
          return;
        }
      }
    };
    window.addEventListener("scroll", handler, { passive: true });
    handler();
    return () => window.removeEventListener("scroll", handler);
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="bg-gray-900 border-b border-gray-800 px-4 md:px-6 py-3 flex items-center justify-between sticky top-0 z-20">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-blue-400 hover:text-blue-300 text-xs">&larr; Dashboard</Link>
          <h1 className="text-base font-bold tracking-tight">User Guide</h1>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/ops" className="text-gray-500 hover:text-white text-xs">Ops</Link>
          <button onClick={() => window.print()} className="text-gray-500 hover:text-white text-xs">Print</button>
          <UserMenu />
        </div>
      </header>

      <div className="flex max-w-6xl mx-auto">
        <nav className="hidden md:block w-60 shrink-0 border-r border-gray-800 px-4 py-6 sticky top-[57px] h-[calc(100vh-57px)] overflow-y-auto print:hidden">
          <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-2">Contents</p>
          <ul className="space-y-0.5">
            {SECTIONS.map((s, i) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className={`block text-xs py-1 px-2 rounded transition-colors ${
                    activeId === s.id
                      ? "bg-blue-900/40 text-blue-300 border-l-2 border-blue-500"
                      : "text-gray-500 hover:text-gray-300"
                  }`}
                >
                  <span className="text-gray-600 mr-2">{i + 1}.</span>
                  {s.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <main className="flex-1 px-4 md:px-8 py-8 max-w-3xl text-sm leading-relaxed">
          <HelpContent />
        </main>
      </div>
    </div>
  );
}

function HelpContent() {
  return (
    <article className="space-y-10 text-gray-300">
      <SectionShell />
    </article>
  );
}

function SectionShell() {
  return (
    <>
      <WelcomeSection />
      <LoginSection />
      <PipelineMapWalkthroughSection />
      <DashboardSection />
      <FindingLeadsSection />
      <LeadCardSection />
      <DataTagsSection />
      <ValidatingSection />
      <FixingDataSection />
      <ContactsSection />
      <PipelineSection />
      <OutreachSection />
      <UploadsSection />
      <CreamScoreSection />
      <OpsSection />
      <FaqSection />
      <GlossarySection />
      <TroubleshootingSection />
    </>
  );
}

function H({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="scroll-mt-20 text-lg font-bold text-white mb-3 pb-2 border-b border-gray-800">
      {children}
    </h2>
  );
}

function H3({ children }: { children: React.ReactNode }) {
  return <h3 className="text-sm font-semibold text-white mt-5 mb-2">{children}</h3>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="mb-3">{children}</p>;
}

function UL({ children }: { children: React.ReactNode }) {
  return <ul className="list-disc list-outside ml-5 mb-3 space-y-1">{children}</ul>;
}

function OL({ children }: { children: React.ReactNode }) {
  return <ol className="list-decimal list-outside ml-5 mb-3 space-y-1">{children}</ol>;
}

function Callout({ kind = "info", children }: { kind?: "info" | "warn" | "tip"; children: React.ReactNode }) {
  const styles = {
    info: "bg-blue-900/20 border-blue-800 text-blue-200",
    warn: "bg-amber-900/20 border-amber-800 text-amber-200",
    tip: "bg-green-900/20 border-green-800 text-green-200",
  };
  const icons = { info: "i", warn: "!", tip: "*" };
  return (
    <div className={`rounded-lg border-l-2 px-3 py-2 mb-3 text-xs ${styles[kind]}`}>
      <span className="font-bold mr-2">{icons[kind]}</span>
      {children}
    </div>
  );
}

function Tag({ kind, label }: { kind: "data" | "est" | "verif"; label: string }) {
  const styles = {
    data: "bg-green-900/40 text-green-400 border-green-800/60",
    est: "bg-amber-900/40 text-amber-400 border-amber-800/60",
    verif: "bg-blue-900/40 text-blue-400 border-blue-800/60",
  };
  return (
    <span className={`text-[9px] uppercase tracking-wider px-1 py-px rounded border ${styles[kind]}`}>
      {label}
    </span>
  );
}

/* ===================================================================
   SECTIONS
   =================================================================== */

function WelcomeSection() {
  return (
    <section>
      <H id="welcome">1. Welcome</H>
      <P>
        This tool is your lead engine for Florida commercial property insurance.
        Every day it scans tax roll data from all 35 Florida coastal counties,
        finds buildings that match your target profile (condos, co-ops, multi-family,
        hotels), pulls in data from a dozen public sources, scores each property,
        and shows you the best opportunities to call first.
      </P>
      <P>Your job as a user is simple:</P>
      <OL>
        <li>Look at the leads the system ranks highest</li>
        <li>Read the lead card and sanity-check what you see against what you know</li>
        <li>Decide whether to pursue, pass, or park it for later</li>
        <li>Record what happened so the next person isn't starting from zero</li>
      </OL>
      <Callout kind="tip">
        You don&apos;t need to understand how the data gets here to use this tool well.
        But you DO need to know which fields to trust and which to verify. That&apos;s what
        this guide is for.
      </Callout>
    </section>
  );
}

function LoginSection() {
  return (
    <section>
      <H id="login">2. Logging In</H>
      <OL>
        <li>Open the URL your admin sent you</li>
        <li>Enter your username and password</li>
        <li>If you see &ldquo;Invalid credentials&rdquo; twice, stop and contact your admin &mdash; don&apos;t keep trying</li>
      </OL>
      <P>Once you&apos;re in, you&apos;ll land on the Dashboard (map + pipeline list).</P>
    </section>
  );
}

function Ascii({ children }: { children: React.ReactNode }) {
  return (
    <pre className="bg-gray-900 border border-gray-800 rounded p-3 text-[10px] leading-snug text-gray-400 overflow-x-auto font-mono whitespace-pre">
      {children}
    </pre>
  );
}

function HelpTable({ headers, rows }: { headers: string[]; rows: (React.ReactNode[])[] }) {
  return (
    <div className="overflow-x-auto my-3">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-gray-700">
            {headers.map((h, i) => (
              <th key={i} className="text-left px-2 py-1 text-gray-400 font-semibold">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-gray-800/60">
              {r.map((cell, j) => (
                <td key={j} className="px-2 py-1 align-top text-gray-300">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PipelineMapWalkthroughSection() {
  return (
    <section>
      <H id="pipeline-map">3. Pipeline + Map Walkthrough</H>
      <P>
        A click-by-click guide for everything on the main dashboard. If
        you only read one section of this guide, read this one.
      </P>

      <H3>3.1 The dashboard at a glance</H3>
      <P>Two halves. Left: Leaflet map. Right: pipeline list.</P>
      <Ascii>
{` ┌──────────────────────────────────────────────────────────────────┐
 │  Insure   Pipeline              Files  Ref  Ops  Validation  ?  │
 ├──────────────────────────────────────────────────────────────────┤
 │                                                                   │
 │           MAP                  │           PIPELINE LIST          │
 │        (left half)             │           (right side)           │
 │                                │                                  │
 │       ★    ★    ★              │  [Saved filter chips]            │
 │           ★                    │  [Stage tabs]                    │
 │      ★                         │  [Search · Sort · County]        │
 │              ★    ★            │  ─────────────────────           │
 │                                │  ┌─ Card                          │
 │       ★                        │  │  building name                 │
 │   ★                            │  │  address                       │
 │         ★                      │  │  Owner: …                      │
 │              ★                 │  │  ◎ MAP                         │
 │                                │  └─ tags…                         │
 └──────────────────────────────────────────────────────────────────┘`}
      </Ascii>
      <P>
        On mobile, the <strong>Pipeline / Map</strong> tabs (top) toggle
        between the two views.
      </P>

      <H3>3.2 The saved filter bar (very top)</H3>
      <P>
        First row you see. Carries every named filter set &mdash; yours
        AND the OG / shared ones an admin set up.
      </P>
      <Ascii>
{` ┌─────────────────────────────────────────────────────────────────┐
 │ [Big Coastal · OG ×] [Citizens Hot · OG ×] [My Pinellas · May ×] │
 │ [+ Add existing (3)]                                              │
 └─────────────────────────────────────────────────────────────────┘`}
      </Ascii>
      <UL>
        <li><strong>Click a chip</strong> &mdash; applies that saved filter set. The chip turns blue. A 2-line preview drops in below showing exactly what&apos;s active.</li>
        <li><strong>× on a chip</strong> &mdash; hides it from the top bar. Doesn&apos;t delete. Survives refreshes (stored locally).</li>
        <li><strong>+ Add existing (N)</strong> &mdash; popover of every hidden filter. Click name to bring it back. Trash icon (only on your own) deletes forever.</li>
        <li><strong>OG badge (amber)</strong> &mdash; canned filter the admin team shared. Never goes away unless you hide it.</li>
        <li>Your own filters show a month/year (e.g. <code className="bg-gray-900 px-1 rounded">May 26</code>).</li>
      </UL>
      <P>The 2-line preview when a chip is active:</P>
      <Ascii>
{` County     | Use     | Min $ | Stories ≥ | Heat
 Pinellas+2 | 004,008 | $10M  | ≥7        | hot`}
      </Ascii>
      <P>
        Field names on top, values below, separated by <code className="bg-gray-900 px-1 rounded">|</code>. No grid math &mdash; visual proximity is enough.
      </P>

      <H3>3.3 Search, Sort, Counties</H3>
      <UL>
        <li><strong>Search</strong> &mdash; matches name, address, and owner string.</li>
        <li><strong>County picker</strong> &mdash; opens a chip grid of all 35 counties with <strong>All</strong> / <strong>None</strong> buttons. Click chips to toggle, Done to close. Closed pill reads <code className="bg-gray-900 px-1 rounded">Pinellas +3</code> when multi-selected.</li>
        <li><strong>Sort</strong> &mdash; value, TIV, units, year built, cream score, etc.</li>
        <li><strong>Filters (N)</strong> &mdash; count badge of active filters. Click to expand the full panel.</li>
      </UL>

      <H3>3.4 The filter panel (collapsed by default)</H3>
      <P>
        Click <strong>Filters</strong> to open. This is the workspace for
        building a new filter set. Once you have it dialed in,{" "}
        <strong>+ Save current</strong> at the top creates a new chip in
        the top bar.
      </P>
      <UL>
        <li><strong>Use Code chips</strong> &mdash; multi-select with <code className="bg-gray-900 px-1 rounded">all</code> / <code className="bg-gray-900 px-1 rounded">none</code>.</li>
        <li><strong>Numeric ranges</strong> &mdash; blank = any. <code className="bg-gray-900 px-1 rounded">Coast ≤ miles</code> means within X miles of the FL coastline.</li>
        <li><strong>Citizens Only</strong> &mdash; narrow to properties heuristically flagged as on Citizens Insurance (high-value swap targets).</li>
      </UL>

      <H3>3.5 Stage tabs</H3>
      <Ascii>
{` ┌──────────────────────────────────────────────────────────────┐
 │ 5,966,570 987,365 1,176,723  0   0     0      0    0          │
 │  TARGET    LEAD   VETTED  ANAL VAL OPP  CUST  ARCH            │
 └──────────────────────────────────────────────────────────────┘`}
      </Ascii>
      <HelpTable
        headers={["Stage", "Meaning"]}
        rows={[
          [<strong key="t">TARGET</strong>, "Every raw parcel from the FL tax roll, no filtering."],
          [<strong key="l">LEAD</strong>, "Promoted by the qualifier — actionable property type + geocoded."],
          [<strong key="v" className="text-teal-300">VETTED</strong>, "Aggregator-built building master. Each master ties N unit parcels together with rolled-up TIV, units, etc. This is where you live."],
          [<strong key="a">ANALYZED</strong>, "Cream score + Sunbiz enrichment complete."],
          [<strong key="vd">VALIDATED</strong>, "Zillow / VRBO cross-check complete."],
          [<strong key="o">OPPORTUNITY</strong>, "You promoted it manually — active outreach."],
          [<strong key="c">CUSTOMER</strong>, "Deal closed."],
          [<strong key="ar">ARCHIVED</strong>, "Passed on / not interested. Each card has a Restore button."],
        ]}
      />
      <P>Default tab is <strong>VETTED</strong> — that&apos;s the actionable building list.</P>

      <H3>3.6 Reading a lead card</H3>
      <Ascii>
{` ┌─────────────────────────────────────────────────────────────┐
 │ Echo Brickell Condominium Assoc          $44M       [hot]   │
 │                                                              │
 │ 1451 Brickell Ave, Miami, FL 33131                          │
 │ Owner: 1451 BRICKELL CONDOMINIUM ASSOC INC                  │
 │                                                              │
 │ ┌──────────────────────────────────────────────────────────┐│
 │ │                    ◎ MAP                                  ││
 │ └──────────────────────────────────────────────────────────┘│
 │                                                              │
 │ [172 parcels] [Condo] [171 units] [Built 1980] [Pinellas]   │
 │                                                              │
 │ [Open]  [ → ANALYZED ]                                       │
 └─────────────────────────────────────────────────────────────┘`}
      </Ascii>
      <P><strong>Color meanings &mdash; trust indicators:</strong></P>
      <HelpTable
        headers={["Element", "Green", "Orange", "Why it matters"]}
        rows={[
          ["Name",
            "Auditor-confirmed (PA enricher OR DOR owner reads like an association)",
            "Aggregator synthesized OR raw person name",
            "Orange = verify the building name"],
          ["Owner",
            "County PA provided this string",
            "DOR tax roll only — no auditor confirmation",
            "Orange = DOR may show a trustee instead of decision-maker"],
          ["Address", "Always neon cyan", "—", "Tax roll is authoritative for street addresses"],
          ["Units count", "Always neon green", "—", "Building's total physical unit count after roll-up"],
          ["TIV",
            <span key="tiv">A <code className="bg-gray-900 px-1 rounded">*</code> means aggregator estimate; Zillow/VRBO firms it up at VALIDATED</span>,
            "—", "Don't quote the * value as final"],
        ]}
      />
      <P>
        <strong>Heat pill (top-right):</strong> hot (≥35 pts) / warm (≥18) / cold (&lt;18).
        This is data completeness, not conversion quality.
      </P>
      <P><strong>Actions row:</strong></P>
      <UL>
        <li><strong>Open</strong> &mdash; opens the slide-in detail modal.</li>
        <li><strong>→ ANALYZED</strong> (or whatever&apos;s next) &mdash; promotes one stage forward. Button colour matches destination.</li>
      </UL>

      <H3>3.7 The map</H3>
      <UL>
        <li>Shows up to 1,000 markers for the current filter &mdash; not just the visible 50 cards.</li>
        <li><strong>Click a card</strong> &rarr; map flies to it.</li>
        <li><strong>Click the bold <code className="bg-gray-900 px-1 rounded">◎ MAP</code> line</strong> on a card &rarr; same thing, more deliberate.</li>
        <li><strong>Click a marker</strong> &rarr; opens detail modal AND scrolls card into view.</li>
        <li><strong>Hover a card</strong> &rarr; marker pulses on the map.</li>
        <li><strong>Top-right of map</strong> &rarr; Street / Satellite / Hybrid toggle.</li>
      </UL>

      <H3>3.8 Opening a card (the detail modal)</H3>
      <P>Click <strong>Open</strong> or a map marker. A panel slides in from the right. You can have up to 10 open at once &mdash; a tab bar at the bottom-left of the screen tracks them. Closing one falls back to the previously active one.</P>
      <UL>
        <li><strong>Stage dropdown</strong> below the name &mdash; set to any stage. Use this for one-off archiving.</li>
        <li><strong>Pipeline stage chip</strong> reads green when ≥VETTED, gray earlier.</li>
        <li><strong>Tabs across the section bar</strong> &mdash; Overview / Contacts / Engagements / Files / Provenance / Notes.</li>
      </UL>

      <H3>3.9 Linked parcels &amp; board members (the call list)</H3>
      <P>
        Inside the modal, the teal banner near the top says{" "}
        <strong>VETTED master · N linked unit parcels</strong>. Click{" "}
        <strong>▶</strong> to expand it.
      </P>
      <Ascii>
{` ┌───────────────────────────────────────────────────────────────┐
 │ VETTED master · 171 linked unit parcels · sum $343M           │
 │ ★ 5 on board  (1451 BRICKELL CONDOMINIUM ASSOC INC)           │
 │                                                                │
 │ Unit  Owner                          Sqft   JV     TIV   PA    │
 │ ─────────────────────────────────────────────────────────────  │
 │ 102   ★ President  ANDERS, ROBERT   1890  $1.4M  $2.1M  PA↗   │
 │ 405   ★ Treasurer  WALSH, MICHAEL   1890  $1.5M  $2.2M  PA↗   │
 │ 502    MILLER, SARAH                1200  $980K  $1.4M  PA↗   │
 │ 1001  ★ Vice Pres  TANG, LISA       2400  $2.3M  $3.3M  PA↗   │
 └───────────────────────────────────────────────────────────────┘`}
      </Ascii>
      <UL>
        <li><strong>Amber ★ row</strong> &mdash; this unit owner is on the association board. Title (President, Treasurer, etc.) comes from Sunbiz officers. <strong>These are the calls.</strong></li>
        <li><strong>Unit number</strong> &mdash; click to open that unit&apos;s detail as another modal in the same stack.</li>
        <li><strong>PA ↗</strong> &mdash; direct deep-link to the county PA&apos;s parcel page. No search step.</li>
        <li><strong>other ↗</strong> (amber, only on board members) &mdash; opens the PA&apos;s search-by-owner-name results &mdash; every property that board member owns in the county.</li>
      </UL>
      <P>Below the linked-parcels table:</P>
      <UL>
        <li><strong>Master parcel (0001) banner</strong> &mdash; the association&apos;s actual common-elements parcel + a one-click PA deep-link.</li>
        <li><strong>Sunbiz entities at this address</strong> &mdash; expandable list of every FL corporation registered at the building, with corp name + status + direct Sunbiz detail links.</li>
      </UL>

      <H3>3.10 Bulk actions</H3>
      <P>
        Click <strong>Select</strong> above the cards to enter select mode.
        Tick individual cards, or use <strong>All (12,847)</strong> to
        select every match across all pages.
      </P>
      <UL>
        <li><strong>All (N)</strong> &mdash; if N ≤ 1000 the explicit IDs are selected; beyond that a sentinel routes the bulk action through the server&apos;s filter endpoint so the SQL UPDATE moves every match in one shot.</li>
        <li><strong>→ ANALYZED (N)</strong> &mdash; promote everyone selected to the next stage. Colour matches destination.</li>
        <li><strong>Archive (N)</strong> &mdash; hide them from normal views. Restorable from the ARCHIVED tab.</li>
        <li>Manually un-tick any card &mdash; drops out of &ldquo;all selected&rdquo; mode.</li>
      </UL>

      <H3>3.11 Trust cheat sheet</H3>
      <HelpTable
        headers={["What you see", "What it tells you"]}
        rows={[
          [<span key="gg"><span className="text-green-300">Green name</span> + <span className="text-green-300">green owner</span></span>, "Both from county auditor. Highest confidence."],
          [<span key="go"><span className="text-green-300">Green name</span> + <span className="text-orange-300">orange owner</span></span>, "Building name confirmed; owner string from DOR (may be trustee/LLC). Still high confidence on the building."],
          [<span key="oo"><span className="text-orange-300">Orange name</span> + <span className="text-orange-300">orange owner</span></span>, "Aggregator-synthesized label, no auditor confirmation. Verify before calling."],
          [<code key="star" className="bg-gray-900 px-1 rounded">*</code>, "TIV is an aggregator estimate. Firms up at VALIDATED."],
          [<span key="amber" className="text-amber-300">★ President</span>, "Unit owner is on the board. Priority call."],
          [<span key="tt" className="text-teal-300">rollup ×N</span>, "Card shows building total (TIV/units summed across N parcels)."],
          [<span key="uo" className="text-amber-300">unit parcel only</span>, "Matched a single unit, not the building. Year/ISO trustworthy; TIV/units not."],
          ["Heat = hot", "≥35 data-completeness points."],
          [<strong key="plat" className="text-purple-300">Cream tier = platinum (90+)</strong>, "High-value conversion opportunity. Call first."],
        ]}
      />

      <H3>3.12 Typical daily flow</H3>
      <OL>
        <li>Log in &rarr; lands on VETTED.</li>
        <li>Click your &ldquo;Platinum Coastal&rdquo; chip in the top bar.</li>
        <li>Sort by Cream score: high.</li>
        <li>Look at the map &mdash; where are the dots clustered?</li>
        <li>Open the top card. Expand linked parcels. Find the amber ★ rows.</li>
        <li>Click <code className="bg-gray-900 px-1 rounded">other ↗</code> on the President &mdash; see what else she owns in the county.</li>
        <li>Click <code className="bg-gray-900 px-1 rounded">open on county PA ↗</code> on the master parcel for building data.</li>
        <li>Click <strong>Sunbiz entities at this address</strong> &mdash; get the association corp name.</li>
        <li>Add a contact, log an engagement, promote to OPPORTUNITY.</li>
        <li>Next card.</li>
      </OL>

      <H3>3.13 If something looks wrong</H3>
      <HelpTable
        headers={["Symptom", "Likely cause", "Fix"]}
        rows={[
          ["\"Miles from coast\" filter returns nothing", "Distance not backfilled on legacy rows", "Ask Eric to run Backfill ocean dist in Ops"],
          ["Master shows synthesized name", "0001 relabel hasn't run since aggregation", "Ask Eric to run Relabel 0001 names in Ops"],
          ["Map shows no markers", "Filter is narrow / zero matches", "Look at the green X total counter"],
          ["Card list slow to load", "Indexes still building", "Wait 30 min after deploy, or ask Eric to click Build Indexes"],
        ]}
      />
    </section>
  );
}

function DashboardSection() {
  return (
    <section>
      <H id="dashboard">4. The Dashboard</H>
      <P>The main screen has two halves:</P>
      <H3>Left side: the map</H3>
      <UL>
        <li>Every lead shows up as a colored dot at its actual location</li>
        <li>Dot color matches its <strong>heat score</strong> (red=hot, orange=warm, gray=cold)</li>
        <li>Click a dot to open the lead card</li>
        <li>Zoom and pan like Google Maps</li>
        <li>Use the search box in the map&apos;s top-left to jump to an address</li>
      </UL>
      <H3>Right side: the pipeline list</H3>
      <UL>
        <li>Each card shows the lead&apos;s name, county, stage, and key stats</li>
        <li>Cards are color-coded by pipeline stage (LEAD=cyan, VETTED=teal, ANALYZED=indigo, VALIDATED=purple, OPPORTUNITY=amber, CUSTOMER=green)</li>
        <li>Click a card to open its detail panel on the right edge of the screen</li>
        <li>Use filters at the top to narrow the list</li>
        <li>Use the Sort dropdown to change the order</li>
      </UL>
      <Callout kind="info">
        On a phone or small tablet, the map and list stack into tabs. Tap the tab
        at the top of the screen to switch between them.
      </Callout>
    </section>
  );
}

function FindingLeadsSection() {
  return (
    <section>
      <H id="finding-leads">5. Finding the Best Leads</H>
      <P>
        The default sort is <strong>&ldquo;Best Opportunity&rdquo;</strong> &mdash; it puts
        the highest-value leads at the top based on the cream score (explained
        later). Start there.
      </P>
      <H3>Filters you&apos;ll use most</H3>
      <UL>
        <li><strong>County</strong> &mdash; narrow to one county (e.g. Miami-Dade) or leave blank for all</li>
        <li><strong>Stage</strong> &mdash; usually LEAD (fully enriched, ready to review)</li>
        <li><strong>Min value</strong> &mdash; set a floor like $10M to skip small properties</li>
        <li><strong>Min stories</strong> &mdash; set to 7 to focus on mid-rise and above (best wind exposure opportunities)</li>
        <li><strong>Cream tier</strong> &mdash; Platinum for highest priority, Gold for solid leads</li>
        <li><strong>Citizens only</strong> &mdash; only show buildings likely insured by Citizens (swap opportunities)</li>
      </UL>
      <H3>Other sort options</H3>
      <UL>
        <li><strong>Value (High-Low)</strong> &mdash; biggest dollar amounts first</li>
        <li><strong>Stories (Most)</strong> &mdash; tallest buildings first</li>
        <li><strong>Units (Most)</strong> &mdash; largest associations first</li>
        <li><strong>Newest Added</strong> &mdash; recently discovered leads</li>
      </UL>
      <Callout kind="tip">
        Don&apos;t sort by &ldquo;Oldest&rdquo; just to find overlooked deals &mdash;
        the cream score already surfaces neglected high-value leads.
      </Callout>
    </section>
  );
}

function LeadCardSection() {
  return (
    <section>
      <H id="lead-card">6. Reading a Lead Card</H>
      <P>
        When you click a lead, a detail panel slides out from the right edge of the
        screen. It has three tabs at the top:
      </P>
      <UL>
        <li><strong>Overview</strong> &mdash; everything we know about the property (main tab)</li>
        <li><strong>Contacts</strong> &mdash; people associated with this association</li>
        <li><strong>Sources</strong> &mdash; which data feeds contributed which fields</li>
      </UL>
      <P>
        At the top of the card you&apos;ll see the building name, address, county,
        heat score badge (hot/warm/cold), pipeline stage badge, TIV estimate,
        market value, and a stage dropdown for moving it forward.
      </P>

      <H3>What the sections mean</H3>
      <P>Sections only appear if they have data. Here&apos;s what each one shows:</P>
      <UL>
        <li><strong>Building Profile</strong> &mdash; Construction type, stories, year built, unit count, living area, estimated Total Insured Value</li>
        <li><strong>Flood &amp; Risk</strong> &mdash; FEMA flood zone, SFHA requirement, base flood elevation, link to the official FEMA map</li>
        <li><strong>Property Appraiser</strong> &mdash; Link to the county PA website, parcel ID, assessed value, year built per PA records</li>
        <li><strong>DOR Tax Roll</strong> &mdash; Official owner, market value, land value, last sale price, parcel ID</li>
        <li><strong>DBPR Condo Registry</strong> &mdash; Official condo name, managing entity, project number, unit count per DBPR</li>
        <li><strong>Financial Health (DBPR KFI)</strong> &mdash; Operating revenue/expenses, reserve fund balance, bad debt, distress signals</li>
        <li><strong>CAM License</strong> &mdash; Community Association Manager license number, active status, expiration</li>
        <li><strong>Association (Sunbiz)</strong> &mdash; FL corporate filing, registered agent, document number</li>
        <li><strong>Citizens Insurance</strong> &mdash; Likelihood this building is on Citizens, estimated premium, risk factors</li>
        <li><strong>OIR Market Intelligence</strong> &mdash; County market hardness, rate per $1K TIV, estimated premium range, top carriers</li>
        <li><strong>SIRS Compliance</strong> &mdash; Structural Integrity Reserve Study status, deadline, compliance risk</li>
        <li><strong>DBPR Building Report</strong> &mdash; Payment status (current or delinquent)</li>
        <li><strong>Condo Conversion (NOIC)</strong> &mdash; If the building was recently converted from apartment/hotel/office to condo</li>
      </UL>
    </section>
  );
}

function DataTagsSection() {
  return (
    <section>
      <H id="data-tags">7. Data Quality Tags</H>
      <P>
        Every field on a lead card has a small colored badge next to it. This tells you
        where the data came from and how much to trust it:
      </P>
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3 mb-3">
        <div className="flex items-start gap-3">
          <Tag kind="data" label="data" />
          <div>
            <p className="text-white font-medium">Data (green)</p>
            <p className="text-gray-400 text-xs">
              Pulled directly from an official source (DOR tax roll, FEMA flood API,
              county property appraiser, DBPR registry, Sunbiz corporate filings).
              High confidence &mdash; trust it unless you have direct contradicting
              evidence.
            </p>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <Tag kind="est" label="est" />
          <div>
            <p className="text-white font-medium">Estimate (amber)</p>
            <p className="text-gray-400 text-xs">
              Calculated or heuristic &mdash; TIV estimates, Citizens premium projections,
              OIR market rate tables, cream score. These are informed guesses based on real
              data, but they are NOT authoritative. <strong>Always verify estimates
              before quoting a number to a customer.</strong>
            </p>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <Tag kind="verif" label="verif" />
          <div>
            <p className="text-white font-medium">Verified (blue)</p>
            <p className="text-gray-400 text-xs">
              Manually confirmed by a human OR sourced from a policy declaration page
              you uploaded. Highest confidence. Today only one field qualifies:
              &ldquo;On Citizens? Yes &mdash; confirmed policy&rdquo; after a dec page
              upload.
            </p>
          </div>
        </div>
      </div>
      <Callout kind="warn">
        If you&apos;re about to quote a premium, make sure you&apos;re looking at a
        number with a <strong>data</strong> or <strong>verif</strong> tag, not
        <strong> est</strong>. The cream score is an <strong>est</strong> &mdash;
        it&apos;s great for ranking but you should never tell a customer
        &ldquo;we scored you 85/100.&rdquo;
      </Callout>
    </section>
  );
}

function ValidatingSection() {
  return (
    <section>
      <H id="validating">8. Validating a Lead</H>
      <P>
        Before you call an association, spend 30 seconds walking through the card
        to sanity-check the data. Here&apos;s a quick validation checklist:
      </P>
      <H3>Validation checklist</H3>
      <OL>
        <li>
          <strong>Address &amp; name match.</strong> Does the building name look right?
          Is the physical address where you think it is? Use the &ldquo;Fly to&rdquo;
          link in the header to jump the map there.
        </li>
        <li>
          <strong>Owner is the association, not a person.</strong> The DOR Owner field
          should read something like &ldquo;OCEAN TOWERS CONDO ASSN INC&rdquo; &mdash;
          NOT an individual person&apos;s name. A person means it&apos;s single-owner
          condo unit, not the master policy holder.
        </li>
        <li>
          <strong>DBPR condo name matches the building name.</strong> If the building is
          &ldquo;Ocean Towers&rdquo; but DBPR section shows &ldquo;Fernwood Park Townhomes,&rdquo;
          the match is wrong. Flag it and don&apos;t trust that row&apos;s data.
        </li>
        <li>
          <strong>Unit count is reasonable.</strong> DOR units, DBPR units, and what you
          know about the building should all roughly agree. A huge mismatch (DOR says 24,
          DBPR says 2) means either DOR is counting wrong or DBPR matched the wrong
          building.
        </li>
        <li>
          <strong>Managing entity is plausible.</strong> If it&apos;s &ldquo;SELF
          MANAGED&rdquo; on a 200-unit building, verify &mdash; large associations
          almost always hire a CAM.
        </li>
        <li>
          <strong>Financial distress signal matches reality.</strong> If KFI says
          &ldquo;negative operating fund&rdquo; but you know this association just
          did a successful $2M assessment, the KFI data is stale. The distress signal
          is useful but not gospel.
        </li>
        <li>
          <strong>Citizens estimate is in range.</strong> Remember Citizens runs
          30-45% above standard market. If the estimate is wildly off from what you
          know the building pays, double-check the TIV number it&apos;s using.
        </li>
      </OL>
      <Callout kind="tip">
        The <strong>Sources</strong> tab tells you when each data source ran and what
        fields it populated. If something looks wrong, check the timestamp &mdash;
        stale data (over a month old) is more likely to be wrong.
      </Callout>
    </section>
  );
}

function FixingDataSection() {
  return (
    <section>
      <H id="fixing-data">9. Fixing Wrong Data</H>
      <P>
        If you spot wrong data on a card, here&apos;s what to do depending on the
        type of error:
      </P>
      <H3>Wrong match (DBPR, Sunbiz, CAM)</H3>
      <P>
        If the system matched the wrong building/company/manager, the right fix is:
      </P>
      <OL>
        <li>Open the Contacts tab and add the CORRECT contact info manually</li>
        <li>Add a note in the engagement section explaining the mismatch</li>
        <li>Ask your admin to force-rerun that enricher for this entity</li>
      </OL>
      <H3>Outdated premium or valuation</H3>
      <P>
        Upload a policy declaration page or recent audit report. This is the highest
        authority and will override any automatic estimate.
      </P>
      <H3>Wrong owner or address</H3>
      <P>
        This usually means the underlying DOR tax roll is wrong or out of date. The
        DOR publishes an updated file every quarter &mdash; ask your admin when the
        last refresh was.
      </P>
      <H3>Missing enrichment data entirely</H3>
      <P>
        If a section like &ldquo;DBPR Condo Registry&rdquo; is empty, it usually means no match
        was found. This is normal for cooperatives and non-condo multifamily.
        Check the Sources tab &mdash; if the enricher ran but found nothing, the
        building isn&apos;t registered with DBPR.
      </P>
      <Callout kind="info">
        You can&apos;t currently edit field values directly in the UI. All corrections
        go through uploading documents (which auto-enrich) or through the admin.
        This will be added in a later update.
      </Callout>
    </section>
  );
}

function ContactsSection() {
  return (
    <section>
      <H id="contacts">10. Adding Contacts</H>
      <P>Contacts are the humans you actually call or email at an association.</P>
      <H3>To add a contact manually:</H3>
      <OL>
        <li>Open the lead card</li>
        <li>Click the <strong>Contacts</strong> tab</li>
        <li>Click <strong>+ Add Contact</strong> at the bottom</li>
        <li>Fill in name (required), title, email, phone</li>
        <li>Check <strong>Primary contact</strong> if this is the decision maker (board president, board chair, or whoever actually signs contracts)</li>
        <li>Click <strong>Save</strong></li>
      </OL>
      <P>
        Contacts pulled in automatically from Sunbiz (corporate officers) will already
        be there when you open a new lead. You can add additional contacts on top of
        those &mdash; no limit.
      </P>
      <Callout kind="tip">
        Set the <strong>Primary</strong> flag as soon as you know who to actually talk to.
        The cream score gives bonus points for having a named decision maker, so
        marking primary contacts improves lead ranking over time.
      </Callout>
    </section>
  );
}

function PipelineSection() {
  return (
    <section>
      <H id="pipeline">11. Moving Through the Pipeline</H>
      <P>Every lead sits in exactly one of eight stages. The first five are
      deterministic gated transitions driven by background workers; the
      last three are user-driven CRM:</P>
      <UL>
        <li><strong className="text-gray-300">TARGET</strong> &mdash; Raw NAL parcel ingestion. Every non-residential parcel from the FL tax roll. No filtering except single-family / mobile homes.</li>
        <li><strong className="text-cyan-400">LEAD</strong> &mdash; Passed the qualifier&apos;s admin-configurable use-code allowlist (condos, multi-family, hotels, commercial, etc.).</li>
        <li><strong className="text-teal-400">VETTED</strong> &mdash; Aggregated. The aggregator groups parcels by (county, ZIP, normalized street) and picks one master per building, with the unit-parcel rows linked as siblings via parent_id. TIV / unit count / stories roll up to the master.</li>
        <li><strong className="text-indigo-400">ANALYZED</strong> &mdash; Cream score, Sunbiz governance, DBPR financial health, FEMA flood, OIR market intelligence have all run on the master.</li>
        <li><strong className="text-purple-400">VALIDATED</strong> &mdash; Zillow / VRBO / county property appraiser cross-checks complete. Numbers are now Jason-grade truth.</li>
        <li><strong className="text-amber-400">OPPORTUNITY</strong> &mdash; You&apos;ve decided to actively pursue this one. Outreach has started.</li>
        <li><strong className="text-green-400">CUSTOMER</strong> &mdash; Deal closed. Policy written.</li>
        <li><strong className="text-red-400">ARCHIVED</strong> &mdash; Passed on, mistake, or not interested. Data is preserved but hidden from normal views.</li>
      </UL>
      <H3>How transitions actually fire</H3>
      <OL>
        <li>Admin clicks <strong>Seed All Counties</strong> &rarr; NAL files become TARGETs.</li>
        <li>Admin clicks <strong>Qualify (TARGET → LEAD)</strong> &rarr; matching use codes get promoted.</li>
        <li>Admin clicks <strong>Aggregate (LEAD → VETTED)</strong> &rarr; siblings link, master roll-ups computed, enrichers auto-queued.</li>
        <li>Enrichment workers move masters VETTED &rarr; ANALYZED automatically as each enricher completes.</li>
        <li>Validator (Zillow/VRBO &mdash; coming soon) moves masters ANALYZED &rarr; VALIDATED.</li>
        <li>Jason picks <strong>OPPORTUNITY</strong> manually from the lead card or detail page.</li>
      </OL>
      <Callout kind="warn">
        Only move a lead to <strong>OPPORTUNITY</strong> when you&apos;ve actually
        started working it &mdash; a call scheduled, an email sent, a meeting booked.
        Don&apos;t use OPPORTUNITY as a &ldquo;maybe later&rdquo; bucket. That&apos;s
        what filters and the cream tier are for.
      </Callout>
    </section>
  );
}

function OutreachSection() {
  return (
    <section>
      <H id="outreach">12. Recording Outreach</H>
      <P>
        Every time you email, call, or meet with an association, record it as an
        engagement. This keeps the team (including yourself two weeks from now)
        aware of who&apos;s been contacted and what was said.
      </P>
      <H3>Bulk email workflow</H3>
      <P>
        The system can generate outreach emails in bulk. Here&apos;s how:
      </P>
      <OL>
        <li>Filter the pipeline down to the leads you want to contact (e.g. platinum tier, Broward county, Citizens-likely)</li>
        <li>Use the bulk action menu to generate QUEUED engagements from a template</li>
        <li>Review each generated email in the engagement tab of each lead</li>
        <li>Export all queued engagements as a .zip of .eml files via <code className="text-blue-400">/api/email/export</code></li>
        <li>Double-click the zip to extract, then drag the .eml files into Outlook to send</li>
        <li>When you receive replies, save them as .eml and upload them via <code className="text-blue-400">/api/email/ingest</code> &mdash; the system will match them back to the right lead</li>
      </OL>
      <Callout kind="info">
        All generated emails are marked with a provenance tag so you can tell
        AI-drafted text from hand-written replies in the engagement history.
      </Callout>
    </section>
  );
}

function UploadsSection() {
  return (
    <section>
      <H id="uploads">13. Uploading Documents</H>
      <P>
        When you have a policy dec page, a broker report, an inspection, or any
        other document about a lead, upload it so the system can extract the
        useful data and mark fields as <Tag kind="verif" label="verif" />.
      </P>
      <H3>Per-lead uploads</H3>
      <OL>
        <li>Open the lead card</li>
        <li>Scroll down to the Documents section (or open the Assets tab)</li>
        <li>Drag and drop the file into the upload area, or click to browse</li>
        <li>The system stores it in a folder named after the lead&apos;s UUID</li>
      </OL>
      <H3>System-wide data uploads (admin only)</H3>
      <P>
        If you have a new NAL or SDF file from DOR, or a fresh DBPR CSV:
      </P>
      <OL>
        <li>Go to the File Manager (link in the header)</li>
        <li>Navigate to <strong>System Data/DOR/</strong> or <strong>System Data/DBPR/</strong></li>
        <li>Drag the file in</li>
        <li>
          For DOR: the system detects when a NAL+SDF pair is complete and
          auto-seeds that county in the background
        </li>
      </OL>
      <Callout kind="warn">
        Uploaded files are saved to S3 and restored on every deploy &mdash; you won&apos;t
        lose them even when the app restarts. But NEVER upload something containing
        an SSN, DOB, or bank account number. Those don&apos;t belong in this system.
      </Callout>
    </section>
  );
}

function CreamScoreSection() {
  return (
    <section>
      <H id="cream-score">14. Cream Score Explained</H>
      <P>
        The cream score (0-100) ranks how good a lead is for commercial property
        insurance conversion. It is <strong>not</strong> the same as the heat
        score &mdash; heat score measures data completeness, cream score measures
        how valuable the lead actually is.
      </P>
      <H3>Tiers</H3>
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 mb-3 text-xs space-y-1">
        <div className="flex justify-between"><span className="text-gray-200 font-bold">Platinum (90-100)</span><span className="text-gray-500">Call today. Top of your list.</span></div>
        <div className="flex justify-between"><span className="text-yellow-400 font-bold">Gold (70-89)</span><span className="text-gray-500">High priority outreach this week.</span></div>
        <div className="flex justify-between"><span className="text-gray-300 font-bold">Silver (50-69)</span><span className="text-gray-500">Worth pursuing when you have time.</span></div>
        <div className="flex justify-between"><span className="text-amber-600 font-bold">Bronze (30-49)</span><span className="text-gray-500">Nurture and monitor.</span></div>
        <div className="flex justify-between"><span className="text-gray-600 font-bold">Prospect (0-29)</span><span className="text-gray-500">Data only. Not ready for outreach.</span></div>
      </div>

      <H3>What drives the score</H3>
      <UL>
        <li><strong>Property size &amp; value</strong> (up to 25 points) &mdash; $100M+ buildings get max points</li>
        <li><strong>Wind exposure</strong> (up to 20 points) &mdash; 10+ story high-rises in coastal counties</li>
        <li><strong>Insurance pain</strong> (up to 20 points) &mdash; Citizens insured, hard market county, hurricane impact zone</li>
        <li><strong>Contact &amp; governance</strong> (up to 20 points) &mdash; known decision maker, email, management company</li>
        <li><strong>Compliance pressure</strong> (up to 15 points) &mdash; SIRS non-compliant, payment delinquent, pre-FBC construction</li>
        <li><strong>Financial distress</strong> (up to 35 points) &mdash; negative operating fund, underfunded reserves, collections issues, NOIC recent conversion</li>
      </UL>

      <Callout kind="tip">
        The single strongest &ldquo;actively shopping for cheaper insurance&rdquo;
        signal is the financial distress bucket. An association with a negative
        operating fund balance <strong>must</strong> cut costs to survive &mdash;
        switching insurance carriers is usually the fastest way to do that. Prioritize
        those leads even over larger, healthier ones.
      </Callout>

      <Callout kind="warn">
        Cream score is an <strong>estimate</strong>. It&apos;s a ranking tool, not a
        commitment. Never share a cream score with a customer &mdash; they wouldn&apos;t
        understand it and the number moves as new data comes in.
      </Callout>
    </section>
  );
}

function OpsSection() {
  return (
    <section>
      <H id="ops">15. The Ops Page</H>
      <P>
        The Ops page (link in the header) is the behind-the-scenes view for
        admins and power users. You usually won&apos;t need it, but here&apos;s
        what it shows:
      </P>
      <UL>
        <li><strong>Pipeline Totals</strong> &mdash; global counts of entities in each stage</li>
        <li><strong>Seed Counties</strong> &mdash; per-county NAL/SDF upload status and a button to seed each one</li>
        <li><strong>Services</strong> &mdash; health of each background worker (consumer, queue manager, etc.)</li>
        <li><strong>Job Queue</strong> &mdash; per-enricher breakdown of pending/running/success/failed/rejected jobs, expandable to show per-county progress</li>
        <li><strong>Events</strong> &mdash; live stream of system activity</li>
        <li><strong>Data Explorer</strong> &mdash; search entities/contacts directly</li>
      </UL>
      <H3>Admin actions you might use</H3>
      <UL>
        <li><strong>Seed All Counties</strong> &mdash; Re-runs the seed for every county that has NAL+SDF available</li>
        <li><strong>Refresh Data Sources</strong> &mdash; Downloads fresh DBPR, Sunbiz, and ArcGIS data</li>
        <li><strong>Recalibrate All</strong> &mdash; After a bug fix or enricher update, this re-runs all enrichers on existing leads without losing any data</li>
        <li><strong>Retry Failed</strong> &mdash; Resets failed jobs back to PENDING so the consumer tries them again</li>
        <li><strong>Backfill</strong> &mdash; Creates missing enrichment jobs for leads that somehow slipped through</li>
      </UL>
      <Callout kind="warn">
        <strong>Reset DB</strong> wipes every entity, contact, policy, and engagement.
        It does NOT wipe uploaded files. Only use it if you want to start the entire
        pipeline over from scratch. 99% of the time, &ldquo;Recalibrate All&rdquo; is
        what you want instead.
      </Callout>
    </section>
  );
}

function FaqSection() {
  return (
    <section>
      <H id="faq">16. Common Questions</H>

      <H3>&ldquo;Why does this lead show use type &lsquo;Code 003&rsquo;?&rdquo;</H3>
      <P>
        003 means &ldquo;multi-family (small)&rdquo; &mdash; typically a building with
        fewer than 10 units. If it&apos;s in your pipeline anyway, it usually means
        the county classified it oddly. Click into the card and check the unit count.
      </P>

      <H3>&ldquo;Why is the Citizens estimate tagged &lsquo;fallback table&rsquo;?&rdquo;</H3>
      <P>
        Citizens normally calculates its estimate as market rate &times; 1.35 markup.
        But if the OIR market enricher hasn&apos;t run yet for that entity, Citizens
        falls back to a simpler per-$1K-TIV table. The number is still in the right
        ballpark but less precise. Wait for the next enrichment cycle and it will
        refresh.
      </P>

      <H3>&ldquo;Why is the DBPR Condo Registry section empty?&rdquo;</H3>
      <P>
        Either (a) no match was found in the DBPR file &mdash; common for cooperatives
        and newer buildings, or (b) the building is registered under a different
        address than what&apos;s in DOR. Check the Sources tab to see if dbpr_bulk
        ran at all.
      </P>

      <H3>&ldquo;Why is the financial distress signal missing?&rdquo;</H3>
      <P>
        The Key Financial Indicators (KFI) data only covers associations that actually
        file financial reports with DBPR. Many don&apos;t. No KFI = no distress signal
        in the cream score for that lead, which is why some platinum leads are missing
        the financial distress bonus.
      </P>

      <H3>&ldquo;Why does the stories field sometimes show as an estimate?&rdquo;</H3>
      <P>
        DOR tax roll doesn&apos;t always include an exact stories field. When
        it&apos;s missing, we estimate it from building height, square footage, and
        unit count. That&apos;s why it&apos;s tagged <Tag kind="est" label="est" />
        in some cards and <Tag kind="data" label="data" /> in others.
      </P>

      <H3>&ldquo;What does the &lsquo;auto-seed&rsquo; event mean?&rdquo;</H3>
      <P>
        When you upload both a NAL and an SDF file for a county, the system
        automatically starts ingesting it in the background. The auto-seed event is
        the log entry showing that kicked off.
      </P>

      <H3>&ldquo;Why does the lead card feel slow to open?&rdquo;</H3>
      <P>
        The first time you open a lead after a deploy, the server compiles its
        enrichment data. Subsequent opens are instant. If you consistently wait
        more than 3 seconds, tell your admin &mdash; something is wrong.
      </P>
    </section>
  );
}

function GlossarySection() {
  return (
    <section>
      <H id="glossary">17. Glossary</H>
      <dl className="space-y-2 text-xs">
        <div><dt className="text-white font-semibold">TIV</dt><dd className="text-gray-400 ml-4">Total Insured Value &mdash; the full replacement cost of the building. Usually 1.2-1.5x the DOR market value.</dd></div>
        <div><dt className="text-white font-semibold">SFHA</dt><dd className="text-gray-400 ml-4">Special Flood Hazard Area &mdash; a FEMA-designated zone where flood insurance is federally required for any mortgaged property.</dd></div>
        <div><dt className="text-white font-semibold">SIRS</dt><dd className="text-gray-400 ml-4">Structural Integrity Reserve Study &mdash; Florida&apos;s mandatory engineering reserve study for condo buildings 3+ stories, required since the Surfside collapse. Deadline was Dec 31, 2025. Buildings that haven&apos;t filed are usually shopping for new insurance because their current carrier is non-renewing.</dd></div>
        <div><dt className="text-white font-semibold">DBPR</dt><dd className="text-gray-400 ml-4">Florida Department of Business and Professional Regulation &mdash; the state agency that regulates condos, co-ops, and community association managers.</dd></div>
        <div><dt className="text-white font-semibold">DOR</dt><dd className="text-gray-400 ml-4">Florida Department of Revenue &mdash; publishes the tax roll (NAL) and sales data (SDF) for every parcel in the state, per county, per year.</dd></div>
        <div><dt className="text-white font-semibold">NAL</dt><dd className="text-gray-400 ml-4">Name, Address, Legal &mdash; the tax roll file from DOR. One per county, released annually.</dd></div>
        <div><dt className="text-white font-semibold">SDF</dt><dd className="text-gray-400 ml-4">Sales Data File &mdash; the sales history file from DOR. Used to cross-reference last sale prices.</dd></div>
        <div><dt className="text-white font-semibold">CAM</dt><dd className="text-gray-400 ml-4">Community Association Manager &mdash; a licensed professional who manages condo/HOA associations.</dd></div>
        <div><dt className="text-white font-semibold">Sunbiz</dt><dd className="text-gray-400 ml-4">Florida Division of Corporations &mdash; the state database of corporate filings, officers, and registered agents.</dd></div>
        <div><dt className="text-white font-semibold">Citizens</dt><dd className="text-gray-400 ml-4">Citizens Property Insurance Corporation &mdash; Florida&apos;s state-created insurer of last resort. Statutorily required to charge above competitive market rates, so any building on Citizens is a swap opportunity.</dd></div>
        <div><dt className="text-white font-semibold">FEMA NFHL</dt><dd className="text-gray-400 ml-4">FEMA National Flood Hazard Layer &mdash; the authoritative flood zone map.</dd></div>
        <div><dt className="text-white font-semibold">OIR</dt><dd className="text-gray-400 ml-4">Florida Office of Insurance Regulation &mdash; publishes carrier rate filings and market data used to estimate premiums.</dd></div>
        <div><dt className="text-white font-semibold">KFI</dt><dd className="text-gray-400 ml-4">Key Financial Indicators &mdash; DBPR&apos;s financial disclosure report that shows each association&apos;s operating revenue, expenses, and fund balances.</dd></div>
        <div><dt className="text-white font-semibold">NOIC</dt><dd className="text-gray-400 ml-4">Notice of Intended Conversion &mdash; a DBPR filing indicating a building is being converted from apartments/hotel/office into a condo association.</dd></div>
        <div><dt className="text-white font-semibold">Cream Score</dt><dd className="text-gray-400 ml-4">0-100 conversion opportunity rating combining property size, wind exposure, insurance pain, contact quality, compliance risk, and financial distress.</dd></div>
        <div><dt className="text-white font-semibold">Heat Score</dt><dd className="text-gray-400 ml-4">Cold/warm/hot indicator of data completeness. Different from cream score &mdash; a hot heat doesn&apos;t mean good lead, just that we have complete data on it.</dd></div>
        <div><dt className="text-white font-semibold">Enricher</dt><dd className="text-gray-400 ml-4">A background job that pulls data from a specific source (e.g. fema_flood, dbpr_bulk, sunbiz) and attaches it to a lead. 15 enrichers run per lead.</dd></div>
        <div><dt className="text-white font-semibold">Pipeline stage</dt><dd className="text-gray-400 ml-4">One of TARGET, LEAD, VETTED, ANALYZED, VALIDATED, OPPORTUNITY, CUSTOMER, ARCHIVED &mdash; the current workflow state of a lead.</dd></div>
      </dl>
    </section>
  );
}

function TroubleshootingSection() {
  return (
    <section>
      <H id="troubleshooting">18. Troubleshooting</H>

      <H3>&ldquo;I can&apos;t log in&rdquo;</H3>
      <OL>
        <li>Check you&apos;re at the correct URL</li>
        <li>Make sure caps lock is off</li>
        <li>Contact your admin &mdash; don&apos;t repeatedly retry</li>
      </OL>

      <H3>&ldquo;The lead card is empty&rdquo;</H3>
      <P>
        Either the lead hasn&apos;t finished enriching yet (wait 5 minutes) or the
        enrichers ran but found no matching data. Check the Sources tab &mdash; if
        it shows 0 sources, enrichment hasn&apos;t run; if it shows sources but no
        data, the enrichers ran but came up empty.
      </P>

      <H3>&ldquo;The map is blank&rdquo;</H3>
      <OL>
        <li>Refresh the page</li>
        <li>Make sure no filters are excluding everything (set stage to LEAD, county to blank)</li>
        <li>Check the browser console for errors and send a screenshot to your admin</li>
      </OL>

      <H3>&ldquo;Two leads show different data for the same building&rdquo;</H3>
      <P>
        DOR sometimes lists the same physical building as multiple parcels (e.g. one
        per tower). This is usually correct &mdash; each tower is its own legal parcel.
        Look at the parcel IDs to confirm they&apos;re actually different.
      </P>

      <H3>&ldquo;The cream score went down after an update&rdquo;</H3>
      <P>
        Cream score moves as new data arrives. A score dropping usually means the
        system learned something new (e.g. SIRS filed on time after all, fund balance
        improved). A score going up usually means new distress signals were detected.
        Both are good &mdash; it means the system is keeping up.
      </P>

      <H3>&ldquo;I uploaded a file but don&apos;t see it&rdquo;</H3>
      <P>
        Uploads to the File Manager go to <strong>filestore/</strong> and sync to S3
        in the background. Refresh the file manager after a few seconds. Per-lead
        uploads appear in the Documents section of the lead card immediately.
      </P>

      <H3>&ldquo;When to call IT&rdquo;</H3>
      <UL>
        <li>Repeated login failures</li>
        <li>Entire counties missing from the map</li>
        <li>Lead cards fail to open with an error banner</li>
        <li>The Ops page shows services stuck in &ldquo;degraded&rdquo; for more than 10 minutes</li>
        <li>You see data that&apos;s clearly a bug (e.g. $10M/year premium on a $2M building &mdash; that&apos;s the Citizens math bug we fixed, but if it comes back, it&apos;s back)</li>
      </UL>
    </section>
  );
}
