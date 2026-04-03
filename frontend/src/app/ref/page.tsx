"use client";

import Link from "next/link";

/* ------------------------------------------------------------------ */
/*  Reference Data                                                     */
/* ------------------------------------------------------------------ */

const TARGET_COUNTIES = [
  { name: "Broward", code: "16", fips: "011", pa: "https://bcpa.net/", search: "https://web.bcpa.net/BcpaClient/#/Record-Search" },
  { name: "Charlotte", code: "18", fips: "015", pa: "https://www.ccappraiser.com/", search: "https://www.ccappraiser.com/search.asp" },
  { name: "Collier", code: "21", fips: "021", pa: "https://www.collierappraiser.com/", search: "https://www.collierappraiser.com/Main/Home.aspx" },
  { name: "Hillsborough", code: "39", fips: "057", pa: "https://www.hcpafl.org/", search: "https://www.hcpafl.org/Property-Info/Property-Search" },
  { name: "Lee", code: "46", fips: "071", pa: "https://www.leepa.org/", search: "https://www.leepa.org/search/propertySearch.aspx" },
  { name: "Manatee", code: "51", fips: "081", pa: "https://www.manateepao.gov/", search: "https://www.manateepao.gov/search/" },
  { name: "Miami-Dade", code: "23", fips: "086", pa: "https://www.miamidade.gov/pa/", search: "https://www.miamidade.gov/pa/property-search.asp" },
  { name: "Palm Beach", code: "60", fips: "099", pa: "https://www.pbcgov.org/papa/index.htm", search: "https://www.pbcgov.org/papa/" },
  { name: "Pasco", code: "61", fips: "101", pa: "https://pascopa.com/", search: "https://search.pascopa.com/" },
  { name: "Pinellas", code: "62", fips: "103", pa: "https://www.pcpao.org/", search: "https://www.pcpao.org/" },
  { name: "Sarasota", code: "68", fips: "115", pa: "https://www.sc-pa.com/", search: "https://www.sc-pa.com/" },
];

const DOR_USE_CODES = [
  { code: "004", label: "Condominium", desc: "Residential condominiums including co-operative apartments" },
  { code: "005", label: "Cooperatives", desc: "Cooperative apartments (co-ops)" },
  { code: "006", label: "Retirement Homes", desc: "Retirement homes, including congregate living facilities" },
  { code: "008", label: "Multi-Family (10+)", desc: "Multi-family with 10+ units (apartments, etc.)" },
  { code: "009", label: "Residential Common", desc: "Residential common elements or areas" },
  { code: "010", label: "Vacant Commercial", desc: "Vacant commercial land" },
  { code: "011", label: "Stores, One Story", desc: "Single-story retail stores" },
  { code: "012", label: "Mixed Use", desc: "Mixed use — store/office with residential above" },
  { code: "017", label: "Office, Multi-Story", desc: "Office buildings, multi-story" },
  { code: "021", label: "Restaurants/Cafeterias", desc: "Restaurants and cafeterias" },
  { code: "039", label: "Hotels/Motels", desc: "Hotels, motels, or tourist accommodations" },
  { code: "048", label: "Warehouses", desc: "Warehouse and distribution terminals" },
];

interface RefSection {
  title: string;
  description?: string;
  links: { label: string; url: string; note?: string }[];
}

const SECTIONS: RefSection[] = [
  {
    title: "FL Department of Revenue — Property Tax (NAL)",
    description: "Primary source for NAL tax roll data, DOR use codes, and county attribution. This is our seed data.",
    links: [
      { label: "DOR Property Tax Oversight Home", url: "https://floridarevenue.com/property/Pages/Home.aspx" },
      { label: "NAL + SDF Data Portal (download tax rolls)", url: "https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx", note: "Annual NAL files per county — our primary seed data" },
      { label: "DOR Reference — FIPS codes + field definitions", url: "https://fgio.maps.arcgis.com/home/item.html?id=55e830fd6c8948baae1601fbfc33a3b2", note: "County codes, DOR_UC definitions, NAL column reference" },
      { label: "DOR Use Code Descriptions (PDF)", url: "https://floridarevenue.com/property/Documents/dorlookupcodes.pdf" },
      { label: "Tangible Personal Property (DR-405)", url: "https://floridarevenue.com/property/Pages/Taxpayers_TangiblePersonalProperty.aspx", note: "TPP filings — confidential under FL 193.074, not public" },
    ],
  },
  {
    title: "ArcGIS — FL Statewide Cadastral (Parcels + Geometry)",
    description: "10.8M parcels with NAL data joined to polygon geometry. Same data as NAL but with parcel boundaries. Updated August 2025.",
    links: [
      { label: "FL Statewide Parcels (Overview)", url: "https://www.arcgis.com/home/item.html?id=efa909d6b1c841d298b0a649e7f71cf2" },
      { label: "FeatureServer REST Endpoint (Layer 0)", url: "https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/Florida_Statewide_Cadastral/FeatureServer/0", note: "Query API — our cadastral downloader uses this" },
      { label: "FL Geospatial Open Data Portal", url: "https://geodata.floridagio.gov/", note: "Hub for all FL GIS data" },
      { label: "FL Statewide Parcel Map (simplified)", url: "https://geodata.floridagio.gov/datasets/FGIO::florida-statewide-parcel-map" },
    ],
  },
  {
    title: "Sunbiz — Division of Corporations (Ownership & Officers)",
    description: "Every FL condo association, HOA, and LLC must file annual reports. Officers, registered agents (often the management company), principal address, and filing status are public record. BULK DATA AVAILABLE.",
    links: [
      { label: "Sunbiz Corporation Search", url: "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchByName", note: "Search by association name → officers + registered agent" },
      { label: "Sunbiz BULK DATA Downloads", url: "https://dos.fl.gov/sunbiz/other-services/data-downloads/", note: "QUARTERLY full extracts + daily updates — ASCII fixed-length files" },
      { label: "Quarterly Data Files", url: "https://dos.fl.gov/sunbiz/other-services/data-downloads/quarterly-data/", note: "Generated Jan/Apr/Jul/Oct — all active corps. Large files (1GB+)" },
      { label: "Daily Data Files", url: "https://dos.fl.gov/sunbiz/other-services/data-downloads/daily-data/", note: "Daily incremental changes — new filings, amendments, dissolutions" },
      { label: "Corporate File Format Definitions", url: "https://dos.fl.gov/sunbiz/other-services/data-downloads/corporate-data-file/", note: "Fixed-length 1440 chars, up to 6 officers per record" },
      { label: "Data Usage Guide", url: "https://dos.fl.gov/sunbiz/other-services/data-downloads/data-usage-guide/" },
      { label: "Annual Report Filing (reference)", url: "https://dos.fl.gov/sunbiz/manage-business/efile/annual-report/", note: "LLCs: $138.75/yr, due Jan 1 - May 1, late fee $400 after May 1" },
    ],
  },
  {
    title: "DBPR — Condo Registry, SIRS & Building Reports",
    description: "Division of Condominiums, Timeshares & Mobile Homes. SIRS database (structural integrity reserve studies), milestone inspections, building reports, and financial filing status. New online portal as of July 2025.",
    links: [
      { label: "DBPR Condo Information Hub", url: "https://condos.myfloridalicense.com/", note: "New portal — inspections, SIRS, timeline, FAQs" },
      { label: "SIRS Reporting Database", url: "https://www2.myfloridalicense.com/condos-timeshares-mobile-homes/condominiums-and-cooperatives-sirs-reporting/", note: "Searchable list of associations that completed SIRS — structural reserve data" },
      { label: "Building Reports Portal", url: "https://www2.myfloridalicense.com/condos-timeshares-mobile-homes/building-report/", note: "Per-building reporting — stories, units, association contacts" },
      { label: "Milestone Inspection Info", url: "https://condos.myfloridalicense.com/inspections/", note: "Buildings 3+ stories, 25+ years old — mandatory structural inspection" },
      { label: "Timeline of Compliance Deadlines", url: "https://condos.myfloridalicense.com/timeline/", note: "SIRS due Dec 31, 2025. Milestone inspections due Dec 31, 2026" },
      { label: "FAQs", url: "https://condos.myfloridalicense.com/faqs/" },
      { label: "Public Records Request", url: "https://www2.myfloridalicense.com/condos-timeshares-mobile-homes/public-records/", note: "Request specific condo association records" },
      { label: "CSV Data Extracts", url: "https://www.myfloridalicense.com/dataextract.asp?SID=&strt=", note: "Condo_CW, Condo_MD, condo_CE, Condo_NF, condo_conv, coopmailing" },
      { label: "Payment History Extracts", url: "https://www2.myfloridalicense.com/sto/file_download/extracts/", note: "paymenthist_8002A-S — delinquency data by project number" },
    ],
  },
  {
    title: "FL Statutes — Condo Association Requirements",
    description: "Legal requirements that create the data we harvest. Every condo/co-op must comply — this is why the data exists.",
    links: [
      { label: "Ch. 718 — Condominiums (full chapter)", url: "https://www.leg.state.fl.us/statutes/index.cfm?App_mode=display_statute&URL=0700-0799/0718/0718.html" },
      { label: "§718.111 — Association duties, insurance, records", url: "https://m.flsenate.gov/statutes/718.111", note: "Insurance: must carry 100% replacement cost. Financial reports by revenue tier. Records must be available to owners." },
      { label: "§718.112 — Budgets, reserves, assessments", url: "https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0700-0799/0718/Sections/0718.112.html", note: "Reserve fund requirements, SIRS items cannot be waived" },
      { label: "Ch. 719 — Cooperatives", url: "https://www.leg.state.fl.us/statutes/index.cfm?App_mode=display_statute&URL=0700-0799/0719/0719.html" },
      { label: "Ch. 720 — HOAs", url: "https://www.leg.state.fl.us/statutes/index.cfm?App_mode=display_statute&URL=0700-0799/0720/0720.html" },
    ],
  },
  {
    title: "Financial Reporting Thresholds (§718.111(13))",
    description: "Associations MUST file financial reports. The tier determines the level of scrutiny — larger associations = audited financials.",
    links: [
      { label: "< $150K revenue: Cash receipts/expenditures report", url: "http://www.flcondoassociationadvisor.com/florida-statute-718-11113-everything-need-know-florida-condominium-association-year-end-financial-reporting-requirement/", note: "Basic cash report only" },
      { label: "$150K-$300K: Compiled financial statements", url: "https://www.stroemercpa.com/reporting_requirements.php", note: "CPA-compiled but not audited" },
      { label: "$300K-$500K: Reviewed financial statements", url: "https://www.add.cpa/post/year-end-financial-reporting-requirements-for-condos-and-hoas-in-florida", note: "CPA review — limited assurance" },
      { label: "$500K+ revenue: FULL AUDIT required", url: "https://beckerlawyers.com/changes-to-condominium-laws-regarding-financial-reports-and-official-records-news-press/", note: "Independent CPA audit — our $10M+ targets are all here" },
    ],
  },
  {
    title: "FEMA — Flood Data",
    description: "National Flood Hazard Layer — flood zones, SFHA status, base flood elevations.",
    links: [
      { label: "FEMA NFHL API (ArcGIS REST)", url: "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer", note: "Our FEMA enricher queries this" },
      { label: "FEMA Flood Map Service Center", url: "https://msc.fema.gov/portal/home", note: "Manual lookup by address" },
      { label: "FEMA NFHL Data Viewers", url: "https://www.fema.gov/flood-maps/national-flood-hazard-layer" },
    ],
  },
  {
    title: "Wind Data — UF GeoPlan + OIR",
    description: "Wind speed design maps, wind-borne debris regions, and wind mitigation inspection standards. Critical for wind insurance rating.",
    links: [
      { label: "UF GeoPlan Wind Speed Project", url: "https://www.geoplan.ufl.edu/portfolio/wind-speed/", note: "Wind design speed maps for FL Building Code" },
      { label: "FL Wind Speed GIS Data History (PDF)", url: "https://fgdl.org/content/pdfs/Florida_Wind_Speed_FGDL_GIS_Data_History_20240722.pdf" },
      { label: "ASCE 7 Hazard Tool", url: "https://asce7hazardtool.online/", note: "Official wind speed lookup by coordinates" },
      { label: "OIR Wind Mitigation Resources", url: "https://floir.gov/consumers/wind-mitigation-resources", note: "FL Office of Insurance Regulation — mitigation discount info" },
      { label: "Uniform Mitigation Verification Form (OIR-B1-1802)", url: "https://www.citizensfla.com/documents/20702/31330/Uniform+Mitigation+Verification+Inspection+Form+OIR-B1-1802/3ff6a375-1088-482b-8496-5b325ed6453b", note: "Standard form — valid 5 years. Roof, openings, wall construction, etc." },
      { label: "CFO Wind Mitigation Info", url: "https://myfloridacfo.com/division/consumers/storm/mitigation-notices-inspections-and-forms" },
    ],
  },
  {
    title: "Citizens Property Insurance",
    description: "FL insurer of last resort. Properties on Citizens = swap opportunities for private market. Exposure data is public.",
    links: [
      { label: "Citizens Homepage", url: "https://www.citizensfla.com/" },
      { label: "Citizens Data Portal (exposure, rates, depop)", url: "https://www.citizensfla.com/data", note: "County exposure data, rate filings, depopulation reports" },
      { label: "Wind Mitigation Inspection Info", url: "https://www.citizensfla.com/your-wind-inspection", note: "Required for Citizens policyholders — discount opportunity" },
    ],
  },
  {
    title: "FDOT — Parcel Data (Alternate GIS Source)",
    description: "FL DOT maintains separate parcel data per county with additional fields.",
    links: [
      { label: "FDOT Parcels FeatureServer", url: "https://gis.fdot.gov/arcgis/rest/services/Parcels/FeatureServer", note: "Per-county layers — our FDOT enricher uses this" },
      { label: "FDOT Parcels MapServer", url: "https://gis.fdot.gov/arcgis/rest/services/Parcels/MapServer" },
    ],
  },
  {
    title: "US Census Geocoder",
    description: "Batch geocoding — converts addresses to coordinates. 10K addresses per batch request.",
    links: [
      { label: "Census Geocoder (batch)", url: "https://geocoding.geo.census.gov/geocoder/locations/addressbatch", note: "Our associator uses this for TARGET→LEAD geocoding" },
      { label: "Census Geocoder (single address)", url: "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress" },
    ],
  },
  {
    title: "Insurance Regulatory — OIR & FLOIR",
    description: "FL Office of Insurance Regulation — rate filings, company data, market reports.",
    links: [
      { label: "OIR Rate Filings Search", url: "https://floir.gov/office/data-analytics/rate-filings", note: "Search carrier rate filings — shows premium trends by line" },
      { label: "OIR Company Search", url: "https://floir.gov/office/data-analytics/company-search", note: "Lookup carrier license status, financial data, complaints" },
      { label: "OIR Annual Reports & Data", url: "https://floir.gov/office/data-analytics", note: "Market share reports, loss ratios, exposure data" },
    ],
  },
];

/* ------------------------------------------------------------------ */
/*  Page Component                                                     */
/* ------------------------------------------------------------------ */

export default function RefPage() {
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="bg-gray-900 border-b border-gray-800 px-4 md:px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-gray-400 hover:text-white text-sm">&larr; Dashboard</Link>
          <span className="text-gray-700">|</span>
          <h1 className="text-lg font-bold">Reference</h1>
          <span className="text-gray-500 text-xs hidden sm:inline">Data Sources &amp; Lookups</span>
        </div>
        <div className="flex gap-2">
          <Link href="/ops" className="text-gray-500 hover:text-white text-xs">Ops</Link>
          <Link href="/files" className="text-gray-500 hover:text-white text-xs">Files</Link>
        </div>
      </header>

      <div className="px-4 md:px-6 py-6 max-w-5xl space-y-8">

        {/* Target Counties Quick Reference */}
        <div>
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Target Counties — Property Appraiser Sites</h2>
          <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-500">
                    <th className="text-left px-3 py-2">County</th>
                    <th className="text-left px-3 py-2">DOR#</th>
                    <th className="text-left px-3 py-2">FIPS</th>
                    <th className="text-left px-3 py-2">PA Website</th>
                    <th className="text-left px-3 py-2">Parcel Search</th>
                  </tr>
                </thead>
                <tbody>
                  {TARGET_COUNTIES.map((c) => (
                    <tr key={c.code} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="px-3 py-2 text-white font-medium">{c.name}</td>
                      <td className="px-3 py-2 text-gray-400 font-mono">{c.code}</td>
                      <td className="px-3 py-2 text-gray-500 font-mono">{c.fips}</td>
                      <td className="px-3 py-2">
                        <a href={c.pa} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">{new URL(c.pa).hostname}</a>
                      </td>
                      <td className="px-3 py-2">
                        <a href={c.search} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">Search</a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* DOR Use Codes */}
        <div>
          <h2 className="text-sm font-semibold text-gray-300 mb-3">DOR Use Codes (Target Property Types)</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
            {DOR_USE_CODES.map((uc) => (
              <div key={uc.code} className={`bg-gray-900 border rounded-lg p-3 ${
                ["004", "005", "006", "008", "039"].includes(uc.code)
                  ? "border-cyan-800/50" : "border-gray-800"
              }`}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-mono text-xs text-cyan-400 bg-cyan-950 px-1.5 py-0.5 rounded">{uc.code}</span>
                  {["004", "005", "006", "008", "039"].includes(uc.code) && (
                    <span className="text-[9px] bg-green-900 text-green-300 px-1 py-0.5 rounded">ACTIVE</span>
                  )}
                </div>
                <p className="text-white text-xs font-medium">{uc.label}</p>
                <p className="text-gray-500 text-[10px] mt-0.5">{uc.desc}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Data Source Sections */}
        {SECTIONS.map((section) => (
          <div key={section.title}>
            <h2 className="text-sm font-semibold text-gray-300 mb-1">{section.title}</h2>
            {section.description && (
              <p className="text-gray-600 text-xs mb-3">{section.description}</p>
            )}
            <div className="bg-gray-900 border border-gray-800 rounded-lg divide-y divide-gray-800">
              {section.links.map((link) => (
                <div key={link.url} className="px-4 py-2.5 flex items-start gap-3 hover:bg-gray-800/30">
                  <div className="flex-1 min-w-0">
                    <a href={link.url} target="_blank" rel="noopener noreferrer"
                      className="text-blue-400 hover:underline text-sm font-medium">
                      {link.label}
                    </a>
                    {link.note && (
                      <p className="text-gray-500 text-[11px] mt-0.5">{link.note}</p>
                    )}
                  </div>
                  <span className="text-gray-700 text-[10px] shrink-0 font-mono mt-0.5 max-w-[200px] truncate">
                    {new URL(link.url).hostname}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}

        {/* Disclaimer */}
        <div className="bg-amber-950/30 border border-amber-800/50 rounded-lg p-4">
          <p className="text-amber-300 text-xs font-medium mb-1">Data Usage Notice</p>
          <p className="text-amber-200/70 text-[11px] leading-relaxed">
            If you discover the inadvertent release of a confidential record exempt from disclosure pursuant to
            Chapter 119, Florida Statutes, public records laws, immediately notify the Department of Revenue
            at 850-717-6570 and your local Florida Property Appraiser&apos;s Office. Please contact the county
            property appraiser with any parcel-specific questions.
          </p>
        </div>
      </div>
    </div>
  );
}
