"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface ServiceStatus {
  name: string;
  status: string;
  last_heartbeat: string;
  capabilities: Record<string, unknown>;
  detail: string;
}

interface HarvestArea {
  name: string;
  count: number;
  harvested_at: string;
}

interface HarvestStatus {
  total_buildings_cached: number;
  total_areas_harvested: number;
  buildings_promoted_to_leads: number;
  by_county: { county: string; count: number }[];
  areas: HarvestArea[];
}

interface QueryResult {
  table: string;
  total: number;
  showing: number;
  results: Record<string, unknown>[];
}

type ActiveTab = "counties" | "services" | "harvest" | "query" | "events";

export default function OpsPage() {
  const [tab, setTab] = useState<ActiveTab>("counties");
  const [counties, setCounties] = useState<{
    counties: { county_no: string; county_name: string; nal_file: string | null; sdf_file: string | null; nal_size: number; sdf_size: number; ready: boolean; lead_count: number }[];
    nal_download_url: string;
  } | null>(null);
  const [seeding, setSeeding] = useState<string | null>(null);
  const [services, setServices] = useState<ServiceStatus[]>([]);
  const [harvest, setHarvest] = useState<HarvestStatus | null>(null);
  const [harvesting, setHarvesting] = useState(false);
  const [harvestMsg, setHarvestMsg] = useState<string | null>(null);
  const [enriching, setEnriching] = useState(false);
  const [enrichMsg, setEnrichMsg] = useState<string | null>(null);
  const [enrichStatus, setEnrichStatus] = useState<{
    total_leads: number; no_enrichment: number;
    coverage: Record<string, number>;
  } | null>(null);

  // Query state
  const [queryTable, setQueryTable] = useState("entities");
  const [queryText, setQueryText] = useState("");
  const [queryCounty, setQueryCounty] = useState("");
  const [queryStage, setQueryStage] = useState("");
  const [queryResults, setQueryResults] = useState<QueryResult | null>(null);
  const [querying, setQuerying] = useState(false);

  // Events state
  const [events, setEvents] = useState<{ type: string; action: string; status: string; detail: string; timestamp: string }[]>([]);

  const COUNTIES = [
    "Pasco", "Pinellas", "Hillsborough", "Manatee", "Sarasota",
    "Charlotte", "Lee", "Collier", "Palm Beach", "Miami-Dade", "Broward",
  ];

  async function fetchCounties() {
    try {
      const res = await fetch("/api/proxy/admin/counties");
      if (res.ok) setCounties(await res.json());
    } catch {}
  }

  const [seedResult, setSeedResult] = useState<string | null>(null);

  async function seedCounty(countyNo: string) {
    setSeeding(countyNo);
    setSeedResult(null);
    try {
      const res = await fetch(`/api/proxy/admin/seed-county/${countyNo}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok || data.error) {
        setSeedResult(`Error: ${data.error || res.statusText}`);
      } else {
        setSeedResult(`${data.county}: ${data.created} leads from ${data.filtered} filtered (${data.total_parcels} parcels scanned)`);
      }
      fetchCounties();
    } catch (err) {
      setSeedResult(`Network error: ${err}`);
    }
    setSeeding(null);
  }

  async function seedAll() {
    setSeeding("all");
    setSeedResult(null);
    try {
      const res = await fetch("/api/proxy/admin/seed-all", { method: "POST" });
      const data = await res.json();
      if (!res.ok || data.error) {
        setSeedResult(`Error: ${data.error || res.statusText}`);
      } else {
        const total = data.results?.reduce((s: number, r: { created?: number }) => s + (r.created || 0), 0) || 0;
        setSeedResult(`Seeded ${total} total leads across ${data.results?.length || 0} counties`);
      }
      fetchCounties();
    } catch (err) {
      setSeedResult(`Network error: ${err}`);
    }
    setSeeding(null);
  }

  useEffect(() => {
    fetchServices();
    fetchHarvest();
    fetchEnrichStatus();
    fetchCounties();
    const interval = setInterval(() => { fetchServices(); fetchEnrichStatus(); }, 15000);
    return () => clearInterval(interval);
  }, []);

  async function fetchServices() {
    try {
      const res = await fetch("/api/proxy/status");
      if (res.ok) {
        const data = await res.json();
        setServices(Array.isArray(data) ? data : data.services || []);
      }
    } catch {}
  }

  async function fetchHarvest() {
    try {
      const res = await fetch("/api/proxy/admin/harvest/status");
      if (res.ok) setHarvest(await res.json());
    } catch {}
  }

  async function fetchEnrichStatus() {
    try {
      const res = await fetch("/api/proxy/admin/enrich/status");
      if (res.ok) setEnrichStatus(await res.json());
    } catch {}
  }

  async function triggerEnrich() {
    setEnriching(true);
    setEnrichMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/enrich", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setEnrichMsg(data.message);
        const poll = setInterval(fetchEnrichStatus, 10000);
        setTimeout(() => clearInterval(poll), 600000);
      }
    } catch (err) {
      console.error("Enrich trigger failed:", err);
    }
    setEnriching(false);
  }

  async function triggerHarvest() {
    setHarvesting(true);
    setHarvestMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/harvest", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setHarvestMsg(data.message);
        // Poll harvest status
        const poll = setInterval(async () => {
          await fetchHarvest();
        }, 10000);
        setTimeout(() => clearInterval(poll), 600000); // Stop after 10min
      }
    } catch (err) {
      console.error("Harvest trigger failed:", err);
    }
    setHarvesting(false);
  }

  async function runQuery() {
    setQuerying(true);
    try {
      const params = new URLSearchParams({ table: queryTable, limit: "100" });
      if (queryText) params.set("q", queryText);
      if (queryCounty) params.set("county", queryCounty);
      if (queryStage) params.set("stage", queryStage);
      const res = await fetch(`/api/proxy/admin/query?${params}`);
      if (res.ok) setQueryResults(await res.json());
    } catch (err) {
      console.error("Query failed:", err);
    }
    setQuerying(false);
  }

  async function fetchEvents() {
    try {
      const res = await fetch("/api/proxy/events?limit=100");
      if (res.ok) {
        const data = await res.json();
        setEvents(Array.isArray(data) ? data : []);
      }
    } catch {}
  }

  useEffect(() => {
    if (tab === "events") fetchEvents();
  }, [tab]);

  const STATUS_COLORS: Record<string, string> = {
    running: "text-green-400", healthy: "text-green-400",
    degraded: "text-amber-400", stale: "text-red-400",
    starting: "text-blue-400",
  };

  const tabs: { key: ActiveTab; label: string }[] = [
    { key: "counties", label: "Counties" },
    { key: "services", label: "Services" },
    { key: "harvest", label: "Data & Enrichment" },
    { key: "query", label: "Query" },
    { key: "events", label: "Events" },
  ];

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-gray-400 hover:text-white text-sm">&larr; Dashboard</Link>
          <span className="text-gray-700">|</span>
          <h1 className="text-lg font-bold">Ops Center</h1>
          <span className="text-gray-500 text-sm">Behind the curtain</span>
        </div>
        <div className="flex gap-2">
          <Link href="/events" className="text-gray-400 hover:text-white text-sm">Events (legacy)</Link>
        </div>
      </header>

      {/* Tabs */}
      <div className="border-b border-gray-800 px-6">
        <div className="flex gap-1 -mb-px">
          {tabs.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 ${
                tab === t.key ? "border-blue-500 text-white" : "border-transparent text-gray-500 hover:text-gray-300"
              }`}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="px-3 md:px-6 py-4 md:py-6 max-w-7xl">

        {/* ─── Services ─── */}
        {tab === "counties" && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-gray-300">County Management</h2>
                <p className="text-gray-600 text-xs mt-1">
                  Upload NAL + SDF files from{" "}
                  <a href="https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx"
                    target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">
                    FL DOR Data Portal
                  </a>
                  {" "}to System Data/DOR/ via{" "}
                  <a href="/files" className="text-blue-400 hover:underline">File Manager</a>
                </p>
              </div>
              <div className="flex gap-2 items-center">
                <button onClick={seedAll} disabled={seeding !== null}
                  className="bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-xs px-4 py-2 rounded font-medium">
                  {seeding === "all" ? "Seeding..." : "Seed All Counties"}
                </button>
                <button onClick={fetchCounties}
                  className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-2 rounded">
                  Refresh
                </button>
              </div>
            </div>
            {seedResult && (
              <div className={`text-xs px-4 py-2 rounded mb-3 ${seedResult.startsWith("Error") || seedResult.startsWith("Network") ? "bg-red-900/50 text-red-300 border border-red-800" : "bg-green-900/50 text-green-300 border border-green-800"}`}>
                {seedResult}
              </div>
            )}

            {counties && (
              <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-800 text-gray-500 text-xs">
                      <th className="text-left px-4 py-2.5">County</th>
                      <th className="text-left px-4 py-2.5">Code</th>
                      <th className="text-right px-4 py-2.5">NAL File</th>
                      <th className="text-right px-4 py-2.5">SDF File</th>
                      <th className="text-right px-4 py-2.5">Leads</th>
                      <th className="text-right px-4 py-2.5"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {counties.counties.map((c) => (
                      <tr key={c.county_no} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                        <td className="px-4 py-2.5 text-white font-medium">{c.county_name}</td>
                        <td className="px-4 py-2.5 text-gray-500 font-mono text-xs">{c.county_no}</td>
                        <td className="px-4 py-2.5 text-right">
                          {c.nal_file ? (
                            <span className="text-green-400 text-xs">{c.nal_file} ({(c.nal_size / 1024 / 1024).toFixed(0)}MB)</span>
                          ) : (
                            <span className="text-red-400 text-xs">Missing</span>
                          )}
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          {c.sdf_file ? (
                            <span className="text-green-400 text-xs">{(c.sdf_size / 1024 / 1024).toFixed(1)}MB</span>
                          ) : (
                            <span className="text-gray-600 text-xs">-</span>
                          )}
                        </td>
                        <td className="px-4 py-2.5 text-right text-white">{c.lead_count.toLocaleString()}</td>
                        <td className="px-4 py-2.5 text-right">
                          {c.ready && (
                            <button onClick={() => seedCounty(c.county_no)}
                              disabled={seeding !== null}
                              className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-[11px] px-3 py-1 rounded">
                              {seeding === c.county_no ? "Seeding..." : c.lead_count > 0 ? "Reseed" : "Seed"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {tab === "services" && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Registered Services</h2>
            {services.length === 0 ? (
              <p className="text-gray-600 text-sm">No services registered.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {services.map((svc) => (
                  <div key={svc.name} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="font-medium text-white">{svc.name}</h3>
                      <span className={`text-xs font-medium ${STATUS_COLORS[svc.status] || "text-gray-500"}`}>
                        {svc.status}
                      </span>
                    </div>
                    <p className="text-gray-500 text-xs mb-2">{svc.detail}</p>
                    <p className="text-gray-600 text-[10px]">
                      Last heartbeat: {new Date(svc.last_heartbeat).toLocaleTimeString()}
                    </p>
                    {svc.capabilities && Object.keys(svc.capabilities).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {Object.entries(svc.capabilities).map(([k, v]) => (
                          <span key={k} className="bg-gray-800 text-gray-500 text-[10px] px-1.5 py-0.5 rounded">
                            {k}: {String(v)}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ─── Harvest Cache ─── */}
        {tab === "harvest" && (
          <div className="space-y-6">
            {/* Enrichment Pipeline Status */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-gray-300">Lead Enrichment Pipeline</h2>
                <div className="flex gap-2 items-center">
                  {enrichMsg && <span className="text-green-300 text-xs">{enrichMsg}</span>}
                  <button onClick={triggerEnrich} disabled={enriching}
                    className="bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-xs px-4 py-1.5 rounded font-medium">
                    {enriching ? "Starting..." : "Enrich All Leads"}
                  </button>
                  <button onClick={fetchEnrichStatus}
                    className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-1.5 rounded">
                    Refresh
                  </button>
                </div>
              </div>
              {enrichStatus && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 text-center">
                    <p className="text-2xl font-bold text-white">{enrichStatus.total_leads.toLocaleString()}</p>
                    <p className="text-gray-500 text-[10px]">Total Leads</p>
                  </div>
                  <div className="bg-gray-900 border border-red-900 rounded-lg p-3 text-center">
                    <p className="text-2xl font-bold text-red-400">{enrichStatus.no_enrichment.toLocaleString()}</p>
                    <p className="text-gray-500 text-[10px]">No Enrichment</p>
                  </div>
                  {Object.entries(enrichStatus.coverage).map(([source, count]) => (
                    <div key={source} className="bg-gray-900 border border-gray-800 rounded-lg p-3 text-center">
                      <p className="text-xl font-bold text-green-400">{Number(count).toLocaleString()}</p>
                      <p className="text-gray-500 text-[10px]">{source.replace(/_/g, " ")}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="border-t border-gray-800" />

            {/* OSM Building Cache */}
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-300">OSM Building Cache</h2>
              <div className="flex gap-2 items-center">
                {harvestMsg && <span className="text-blue-300 text-xs">{harvestMsg}</span>}
                <button onClick={triggerHarvest} disabled={harvesting}
                  className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs px-4 py-1.5 rounded font-medium">
                  {harvesting ? "Starting..." : "Harvest All 11 Counties"}
                </button>
                <button onClick={fetchHarvest}
                  className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-1.5 rounded">
                  Refresh
                </button>
              </div>
            </div>

            {/* Data file upload */}
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-semibold text-gray-400">Data Files</h3>
                <label className="bg-blue-600 hover:bg-blue-700 text-white text-xs px-3 py-1.5 rounded font-medium cursor-pointer">
                  Upload CSV
                  <input type="file" accept=".csv" className="hidden" onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    try {
                      const formData = new FormData();
                      formData.append("file", file);
                      const res = await fetch("/api/proxy/admin/upload-data", { method: "POST", body: formData });
                      if (res.ok) {
                        const data = await res.json();
                        alert(`Uploaded ${data.filename} (${(data.size_bytes / 1024 / 1024).toFixed(1)} MB)`);
                      }
                    } catch (err) { console.error("Upload failed:", err); }
                    e.target.value = "";
                  }} />
                </label>
              </div>
              <p className="text-gray-600 text-[10px]">Upload DBPR CSVs, CAM licenses, payment history, or other data files. Files are saved locally + to S3 bucket.</p>
            </div>

            {harvest && (
              <>
                {/* Stats row */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-center">
                    <p className="text-3xl font-bold text-white">{harvest.total_buildings_cached.toLocaleString()}</p>
                    <p className="text-gray-500 text-xs mt-1">Buildings Cached</p>
                  </div>
                  <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-center">
                    <p className="text-3xl font-bold text-green-400">{harvest.buildings_promoted_to_leads.toLocaleString()}</p>
                    <p className="text-gray-500 text-xs mt-1">Promoted to Leads</p>
                  </div>
                  <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-center">
                    <p className="text-3xl font-bold text-blue-400">{harvest.total_areas_harvested}</p>
                    <p className="text-gray-500 text-xs mt-1">Areas Harvested</p>
                  </div>
                </div>

                {/* By county */}
                {(harvest.by_county || []).length > 0 && (
                  <div>
                    <h3 className="text-xs font-semibold text-gray-400 mb-2">Buildings by County</h3>
                    <div className="flex flex-wrap gap-2">
                      {(harvest.by_county || []).map((c) => (
                        <div key={c.county} className="bg-gray-900 border border-gray-800 rounded px-3 py-2 text-center">
                          <p className="text-white text-sm font-medium">{c.count.toLocaleString()}</p>
                          <p className="text-gray-500 text-[10px]">{c.county}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Harvest areas */}
                <div>
                  <h3 className="text-xs font-semibold text-gray-400 mb-2">Harvested Areas</h3>
                  <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-gray-800">
                          <th className="text-left px-3 py-2 text-gray-500">Area</th>
                          <th className="text-right px-3 py-2 text-gray-500">Buildings</th>
                          <th className="text-right px-3 py-2 text-gray-500">Harvested</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(harvest.areas || []).map((a, i) => (
                          <tr key={i} className="border-b border-gray-800/50">
                            <td className="px-3 py-1.5 text-white">{a.name}</td>
                            <td className="px-3 py-1.5 text-right text-gray-400">{a.count}</td>
                            <td className="px-3 py-1.5 text-right text-gray-600">{new Date(a.harvested_at).toLocaleDateString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ─── Query Data ─── */}
        {tab === "query" && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Data Explorer</h2>
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
                <select value={queryTable} onChange={(e) => setQueryTable(e.target.value)}
                  className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white">
                  <option value="entities">Leads / Entities</option>
                  <option value="osm_cache">OSM Building Cache</option>
                  <option value="contacts">Contacts</option>
                </select>
                <select value={queryCounty} onChange={(e) => setQueryCounty(e.target.value)}
                  className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white">
                  <option value="">All Counties</option>
                  {COUNTIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                {queryTable === "entities" && (
                  <select value={queryStage} onChange={(e) => setQueryStage(e.target.value)}
                    className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white">
                    <option value="">All Stages</option>
                    <option value="NEW">New</option>
                    <option value="CANDIDATE">Candidate</option>
                    <option value="TARGET">Target</option>
                    <option value="OPPORTUNITY">Opportunity</option>
                    <option value="CUSTOMER">Customer</option>
                  </select>
                )}
                <button onClick={runQuery} disabled={querying}
                  className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium rounded text-sm">
                  {querying ? "Querying..." : "Search"}
                </button>
              </div>
              <input type="text" value={queryText} onChange={(e) => setQueryText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runQuery()}
                placeholder={queryTable === "osm_cache"
                  ? 'Try: "7+ stories fire resistive" or "condos in clearwater"'
                  : 'Search by name or address...'}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white" />
            </div>

            {queryResults && Array.isArray(queryResults.results) && (
              <div>
                <p className="text-gray-500 text-xs mb-2">
                  Showing {queryResults.showing} of {queryResults.total} {queryResults.table} results
                </p>
                <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-auto max-h-[600px]">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-gray-900">
                      <tr className="border-b border-gray-800">
                        {queryResults.results.length > 0 &&
                          Object.keys(queryResults.results[0]).map((col) => (
                            <th key={col} className="text-left px-3 py-2 text-gray-500 whitespace-nowrap">{col}</th>
                          ))
                        }
                      </tr>
                    </thead>
                    <tbody>
                      {queryResults.results.map((row, i) => (
                        <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                          {Object.values(row).map((val, j) => (
                            <td key={j} className="px-3 py-1.5 text-gray-300 whitespace-nowrap max-w-[200px] truncate">
                              {val === null ? <span className="text-gray-700">null</span> :
                               typeof val === "boolean" ? (val ? "Yes" : "No") :
                               Array.isArray(val) ? val.join(", ") :
                               typeof val === "number" ? val.toLocaleString() :
                               String(val)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ─── Events ─── */}
        {tab === "events" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-300">Event Stream</h2>
              <button onClick={fetchEvents}
                className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-1.5 rounded">
                Refresh
              </button>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-auto max-h-[600px]">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-gray-900">
                  <tr className="border-b border-gray-800">
                    <th className="text-left px-3 py-2 text-gray-500">Time</th>
                    <th className="text-left px-3 py-2 text-gray-500">Type</th>
                    <th className="text-left px-3 py-2 text-gray-500">Action</th>
                    <th className="text-left px-3 py-2 text-gray-500">Status</th>
                    <th className="text-left px-3 py-2 text-gray-500">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((evt, i) => (
                    <tr key={i} className="border-b border-gray-800/50">
                      <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap">{new Date(evt.timestamp).toLocaleTimeString()}</td>
                      <td className="px-3 py-1.5 text-gray-400">{evt.type}</td>
                      <td className="px-3 py-1.5 text-white">{evt.action}</td>
                      <td className="px-3 py-1.5">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                          evt.status === "success" ? "bg-green-900 text-green-300" :
                          evt.status === "error" ? "bg-red-900 text-red-300" :
                          "bg-blue-900 text-blue-300"
                        }`}>{evt.status}</span>
                      </td>
                      <td className="px-3 py-1.5 text-gray-500 max-w-[400px] truncate">{evt.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
