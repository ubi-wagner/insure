import Link from "next/link";

/**
 * Public marketing/landing page for Insure Pipeline. Reachable without
 * authentication — describes the system to prospective users and shows a
 * big Login call-to-action.
 *
 * Screenshot images live in /public/screenshots/. Drop PNGs in there with
 * the filenames referenced below and they will appear automatically; until
 * then the framed wrappers render as styled placeholders.
 */

const SCREENSHOTS = [
  {
    src: "/screenshots/dashboard.png",
    alt: "Dashboard with map and pipeline cards",
    title: "Map + Pipeline",
    caption:
      "Every $10M+ commercial property in your target counties, plotted on the map and ranked in the pipeline.",
  },
  {
    src: "/screenshots/lead.png",
    alt: "Lead detail panel with tax roll, DBPR, Citizens, and OIR data",
    title: "Lead Detail",
    caption:
      "Tax roll, flood zone, condo registry, Citizens swap likelihood, and OIR market intel — all on one screen.",
  },
  {
    src: "/screenshots/ops.png",
    alt: "Ops Center showing pipeline funnel and worker health",
    title: "Ops Center",
    caption:
      "Live pipeline funnel, county seed status, and 13 enrichment workers reporting heartbeats.",
  },
];

const FEATURES = [
  {
    title: "Discover",
    body:
      "Seeded nightly from FL DOR tax rolls across 11 coastal counties. Every condo, co-op, multi-family, and hotel parcel — auto-filtered to $10M+, 10+ units.",
  },
  {
    title: "Enrich",
    body:
      "13 automated workers pull from FEMA, DBPR, Sunbiz, Citizens, FL OIR, and county property appraisers. Flood zone, structural reserves, officers, premium estimates.",
  },
  {
    title: "Rank",
    body:
      "Cream Score 0–100 surfaces the platinum opportunities — big coastal towers, Citizens-insured, SIRS non-compliant, with known board contacts.",
  },
  {
    title: "Engage",
    body:
      "5-stage pipeline from Target → Lead → Opportunity → Customer. Contacts, engagements, and uploaded docs all tracked per entity.",
  },
];

const COUNTIES = [
  "Broward", "Charlotte", "Collier", "Hillsborough", "Lee", "Manatee",
  "Miami-Dade", "Palm Beach", "Pasco", "Pinellas", "Sarasota",
];

const SOURCES = [
  "FL DOR", "FEMA NFHL", "DBPR", "Sunbiz", "Citizens", "FL OIR",
  "County PA", "FDOT", "Census", "ArcGIS",
];

export default function WelcomePage() {
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* ---------------- Top bar ---------------- */}
      <header className="sticky top-0 z-30 bg-gray-950/85 backdrop-blur border-b border-gray-900">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xl">🏢</span>
            <span className="text-sm sm:text-base font-bold tracking-tight">
              Insure <span className="text-blue-400 font-medium">Pipeline</span>
            </span>
          </div>
          <Link
            href="/login"
            className="bg-blue-600 hover:bg-blue-500 text-white text-xs sm:text-sm font-semibold px-4 sm:px-5 py-2 rounded-lg transition-colors shadow-lg shadow-blue-900/40"
          >
            Login &rarr;
          </Link>
        </div>
      </header>

      {/* ---------------- Hero ---------------- */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-blue-950/40 via-gray-950 to-gray-950 pointer-events-none" />
        <div className="absolute inset-x-0 top-0 h-[480px] bg-[radial-gradient(ellipse_at_top,_rgba(37,99,235,0.18),_transparent_60%)] pointer-events-none" />

        <div className="relative max-w-4xl mx-auto px-4 sm:px-6 pt-14 sm:pt-24 pb-12 sm:pb-20 text-center">
          <span className="inline-block text-[10px] sm:text-xs uppercase tracking-[0.2em] text-blue-300/80 bg-blue-950/60 border border-blue-900 rounded-full px-3 py-1 mb-5">
            Florida coastal commercial property
          </span>
          <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight leading-tight">
            Insure Pipeline
          </h1>
          <p className="mt-4 sm:mt-5 text-base sm:text-xl text-gray-300 max-w-2xl mx-auto">
            Discover, enrich, score, and engage every $10M+ condo, co-op,
            multi-family, and hotel along the Florida coast — automatically.
          </p>
          <p className="mt-3 text-xs sm:text-sm text-gray-500 max-w-xl mx-auto">
            Tax roll seeding · 13 enrichment sources · Citizens swap targeting ·
            Cream Score ranking · 5-stage CRM pipeline
          </p>

          <div className="mt-8 flex flex-col sm:flex-row gap-3 items-center justify-center">
            <Link
              href="/login"
              className="w-full sm:w-auto bg-blue-600 hover:bg-blue-500 text-white text-base font-semibold px-8 py-3.5 rounded-xl transition-colors shadow-xl shadow-blue-900/40"
            >
              Login to Pipeline &rarr;
            </Link>
            <a
              href="#features"
              className="w-full sm:w-auto text-sm text-gray-400 hover:text-white px-4 py-3"
            >
              See what it does &darr;
            </a>
          </div>
        </div>
      </section>

      {/* ---------------- Screenshots ---------------- */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 pb-12 sm:pb-20">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 sm:gap-6">
          {SCREENSHOTS.map((s) => (
            <figure
              key={s.src}
              className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden shadow-xl shadow-black/50"
            >
              <div className="aspect-[16/10] bg-gradient-to-br from-gray-800 via-gray-900 to-blue-950/40 flex items-center justify-center relative overflow-hidden">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={s.src}
                  alt={s.alt}
                  loading="lazy"
                  className="w-full h-full object-cover object-top"
                />
              </div>
              <figcaption className="px-4 py-3 border-t border-gray-800">
                <p className="text-sm font-semibold text-white">{s.title}</p>
                <p className="text-xs text-gray-500 mt-0.5 leading-snug">{s.caption}</p>
              </figcaption>
            </figure>
          ))}
        </div>
      </section>

      {/* ---------------- Features ---------------- */}
      <section id="features" className="max-w-6xl mx-auto px-4 sm:px-6 pb-12 sm:pb-20">
        <div className="text-center mb-8 sm:mb-12">
          <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">
            From tax roll to platinum lead, automatically.
          </h2>
          <p className="mt-3 text-sm sm:text-base text-gray-400 max-w-2xl mx-auto">
            Hunt → Kill → Cook. The system finds the properties, pulls the
            data, ranks them, and tees up your outreach.
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {FEATURES.map((f, i) => (
            <div
              key={f.title}
              className="bg-gray-900/80 border border-gray-800 rounded-xl p-5 hover:border-blue-700/60 transition-colors"
            >
              <div className="text-[11px] uppercase tracking-wider text-blue-300/80 font-semibold mb-2">
                Step {i + 1}
              </div>
              <h3 className="text-lg font-bold text-white mb-2">{f.title}</h3>
              <p className="text-xs sm:text-sm text-gray-400 leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ---------------- Pipeline visual ---------------- */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 pb-12 sm:pb-20">
        <h2 className="text-center text-xl sm:text-2xl font-bold tracking-tight mb-6">
          The 5-stage pipeline
        </h2>
        <div className="flex flex-col sm:flex-row items-stretch gap-2 sm:gap-1.5">
          {[
            { name: "Target", color: "bg-gray-700", desc: "Raw parcel" },
            { name: "Lead", color: "bg-cyan-700", desc: "Geocoded + enriched" },
            { name: "Opportunity", color: "bg-amber-700", desc: "Engaged" },
            { name: "Customer", color: "bg-green-700", desc: "Closed" },
            { name: "Archived", color: "bg-gray-800", desc: "Parked" },
          ].map((s, i, arr) => (
            <div key={s.name} className="flex-1 flex items-center gap-2 sm:gap-1">
              <div className={`flex-1 ${s.color} rounded-lg px-3 py-3 text-center`}>
                <div className="text-xs uppercase tracking-wider font-bold">{s.name}</div>
                <div className="text-[10px] text-white/70 mt-0.5">{s.desc}</div>
              </div>
              {i < arr.length - 1 && (
                <span className="text-gray-700 text-base hidden sm:inline">&rarr;</span>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ---------------- Counties + Sources ---------------- */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 pb-12 sm:pb-20">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-5">
            <p className="text-[11px] uppercase tracking-wider text-blue-300/80 font-semibold mb-3">
              11 target counties
            </p>
            <div className="flex flex-wrap gap-1.5">
              {COUNTIES.map((c) => (
                <span
                  key={c}
                  className="text-xs bg-gray-800 text-gray-300 px-2 py-1 rounded"
                >
                  {c}
                </span>
              ))}
            </div>
          </div>
          <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-5">
            <p className="text-[11px] uppercase tracking-wider text-blue-300/80 font-semibold mb-3">
              Public + commercial data sources
            </p>
            <div className="flex flex-wrap gap-1.5">
              {SOURCES.map((s) => (
                <span
                  key={s}
                  className="text-xs bg-gray-800 text-gray-300 px-2 py-1 rounded"
                >
                  {s}
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ---------------- CTA ---------------- */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pb-16 sm:pb-24 text-center">
        <div className="bg-gradient-to-br from-blue-950/80 to-gray-900 border border-blue-900/60 rounded-2xl p-8 sm:p-12">
          <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">
            Ready to see your pipeline?
          </h2>
          <p className="mt-3 text-sm sm:text-base text-gray-400">
            Sign in to view the live dashboard, map, and lead pipeline.
          </p>
          <Link
            href="/login"
            className="mt-6 inline-block bg-blue-600 hover:bg-blue-500 text-white text-base font-semibold px-8 py-3.5 rounded-xl transition-colors shadow-xl shadow-blue-900/40"
          >
            Login &rarr;
          </Link>
        </div>
      </section>

      {/* ---------------- Footer ---------------- */}
      <footer className="border-t border-gray-900 px-4 sm:px-6 py-6">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2 text-[11px] text-gray-600">
          <span>Insure Pipeline · Florida coastal commercial property leads</span>
          <Link href="/login" className="text-gray-500 hover:text-white">
            Login
          </Link>
        </div>
      </footer>
    </div>
  );
}
