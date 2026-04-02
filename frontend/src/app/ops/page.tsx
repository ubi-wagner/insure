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

type ActiveTab = "services" | "harvest" | "query" | "events";

export default function OpsPage() {
  const [tab, setTab] = useState<ActiveTab>("services");
  const [services, setServices] = useState<ServiceStatus[]>([]);
  const [harvest, setHarvest] = useState<HarvestStatus | null>(null);
  const [harvesting, setHarvesting] = useState(false);
  const [harvestMsg, setHarvestMsg] = useState<string | null>(null);

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

  useEffect(() => {
    fetchServices();
    fetchHarvest();
    const interval = setInterval(fetchServices, 15000);
    return () => clearInterval(interval);
  }, []);

  async function fetchServices() {
    try {
      const res = await fetch("/api/proxy/status");
      if (res.ok) setServices(await res.json());
    } catch {}
  }

  async function fetchHarvest() {
    try {
      const res = await fetch("/api/proxy/admin/harvest/status");
      if (res.ok) setHarvest(await res.json());
    } catch {}
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
      if (res.ok) setEvents(await res.json());
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
    { key: "services", label: "Services" },
    { key: "harvest", label: "Harvest Cache" },
    { key: "query", label: "Query Data" },
    { key: "events", label: "Event Stream" },
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

      <div className="px-6 py-6 max-w-7xl">

        {/* ─── Services ─── */}
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

            {harvest && (
              <>
                {/* Stats row */}
                <div className="grid grid-cols-3 gap-4">
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
                {harvest.by_county.length > 0 && (
                  <div>
                    <h3 className="text-xs font-semibold text-gray-400 mb-2">Buildings by County</h3>
                    <div className="flex flex-wrap gap-2">
                      {harvest.by_county.map((c) => (
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
                        {harvest.areas.map((a, i) => (
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
              <div className="grid grid-cols-4 gap-3">
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

            {queryResults && (
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
