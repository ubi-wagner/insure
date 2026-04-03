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
    title: "FL Department of Revenue — Property Tax",
    description: "Primary source for NAL tax roll data, DOR use codes, and county attribution.",
    links: [
      { label: "DOR Property Tax Oversight Home", url: "https://floridarevenue.com/property/Pages/Home.aspx" },
      { label: "NAL + SDF Data Portal (download tax rolls)", url: "https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx", note: "Annual NAL files per county — our primary seed data" },
      { label: "DOR Reference — FIPS codes + field definitions", url: "https://fgio.maps.arcgis.com/home/item.html?id=55e830fd6c8948baae1601fbfc33a3b2", note: "County codes, DOR_UC definitions, NAL column reference" },
      { label: "DOR Use Code Descriptions", url: "https://floridarevenue.com/property/Documents/dorlookupcodes.pdf" },
    ],
  },
  {
    title: "ArcGIS — FL Statewide Cadastral (Parcels + Geometry)",
    description: "10.8M parcels with NAL data joined to polygon geometry. Updated August 2025.",
    links: [
      { label: "FL Statewide Parcels (Overview)", url: "https://www.arcgis.com/home/item.html?id=efa909d6b1c841d298b0a649e7f71cf2" },
      { label: "FeatureServer REST Endpoint", url: "https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/Florida_Statewide_Cadastral/FeatureServer/0", note: "Query API — our cadastral downloader uses this" },
      { label: "FL Geospatial Open Data Portal", url: "https://geodata.floridagio.gov/", note: "Hub for all FL GIS data" },
      { label: "FL Statewide Parcel Map (simplified)", url: "https://geodata.floridagio.gov/datasets/FGIO::florida-statewide-parcel-map" },
    ],
  },
  {
    title: "DBPR — Division of Condominiums",
    description: "Condo association registry, CAM licenses, financial filings, and payment history.",
    links: [
      { label: "DBPR Condo/Co-op Search", url: "https://www.myfloridalicense.com/dataextract.asp?SID=&strt=", note: "CSV extracts: Condo_CW, Condo_MD, condo_CE, Condo_NF, condo_conv, coopmailing" },
      { label: "DBPR License Verification", url: "https://www.myfloridalicense.com/wl11.asp", note: "CAM license lookup" },
      { label: "DBPR Payment History Extracts", url: "https://www2.myfloridalicense.com/sto/file_download/extracts/", note: "paymenthist_8002A-S files — delinquency data" },
    ],
  },
  {
    title: "Sunbiz — Division of Corporations",
    description: "Association/HOA corporate filings, officers, registered agents.",
    links: [
      { label: "Sunbiz Corporation Search", url: "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchByName", note: "Search by association name to find officers + registered agent" },
      { label: "Sunbiz Annual Reports", url: "https://dos.fl.gov/sunbiz/manage-business/efile/annual-report/" },
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
    title: "Wind Data — UF GeoPlan Center",
    description: "Wind speed design maps, wind-borne debris regions — critical for wind insurance rating.",
    links: [
      { label: "UF GeoPlan Wind Speed Project", url: "https://www.geoplan.ufl.edu/portfolio/wind-speed/", note: "Wind design speed maps for FL Building Code" },
      { label: "FL Wind Speed GIS Data History (PDF)", url: "https://fgdl.org/content/pdfs/Florida_Wind_Speed_FGDL_GIS_Data_History_20240722.pdf" },
      { label: "ASCE 7 Hazard Tool", url: "https://asce7hazardtool.online/", note: "Official wind speed lookup by coordinates" },
      { label: "FL Building Code Wind Maps (2007 reference)", url: "https://adhoc.geoplan.ufl.edu/downloads/kate/windspeed_2007/FBC_2007_Wind_Speed_Map_Book.pdf" },
    ],
  },
  {
    title: "Citizens Property Insurance",
    description: "Florida's insurer of last resort — properties on Citizens are swap opportunities.",
    links: [
      { label: "Citizens Policy Search", url: "https://www.citizensfla.com/", note: "Check if property is on Citizens" },
      { label: "Citizens Data (Rate Filings + Exposure)", url: "https://www.citizensfla.com/data", note: "County exposure data, depopulation reports" },
    ],
  },
  {
    title: "FDOT — Parcel Data (Alternate Source)",
    description: "FL DOT maintains its own parcel data with additional transportation-related fields.",
    links: [
      { label: "FDOT Parcels FeatureServer", url: "https://gis.fdot.gov/arcgis/rest/services/Parcels/FeatureServer", note: "Per-county layers — our FDOT enricher uses this" },
      { label: "FDOT Parcels MapServer", url: "https://gis.fdot.gov/arcgis/rest/services/Parcels/MapServer" },
    ],
  },
  {
    title: "US Census Geocoder",
    description: "Batch geocoding service — converts addresses to coordinates.",
    links: [
      { label: "Census Geocoder (batch)", url: "https://geocoding.geo.census.gov/geocoder/locations/addressbatch", note: "Our associator uses this for TARGET→LEAD geocoding" },
      { label: "Census Geocoder (single)", url: "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress" },
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
