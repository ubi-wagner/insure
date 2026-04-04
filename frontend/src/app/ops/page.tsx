"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";

interface ServiceStatus {
  name: string;
  status: string;
  last_heartbeat: string;
  capabilities: Record<string, unknown>;
  detail: string;
}

interface EnrichStatus {
  total_leads: number;
  no_enrichment: number;
  stage_counts?: Record<string, number>;
  coverage: Record<string, number>;
}

interface QueryResult {
  table: string;
  total: number;
  showing: number;
  results: Record<string, unknown>[];
}

interface EventItem {
  event_type: string;
  action: string;
  status: string;
  detail: string;
  timestamp: number;
  duration_ms?: number;
  metadata?: Record<string, unknown>;
}

type ActiveTab = "pipeline" | "counties" | "services" | "query" | "events" | "email";

const COUNTIES = [
  "Pasco", "Pinellas", "Hillsborough", "Manatee", "Sarasota",
  "Charlotte", "Lee", "Collier", "Palm Beach", "Miami-Dade", "Broward",
];

const PIPELINE_STAGES = ["TARGET", "LEAD", "OPPORTUNITY", "CUSTOMER", "ARCHIVED"] as const;

const STAGE_COLORS: Record<string, string> = {
  TARGET: "border-gray-600 text-gray-300",
  LEAD: "border-blue-600 text-blue-300",
  OPPORTUNITY: "border-amber-600 text-amber-300",
  CUSTOMER: "border-green-600 text-green-300",
  ARCHIVED: "border-gray-700 text-gray-500",
};

const STAGE_BG: Record<string, string> = {
  TARGET: "bg-gray-800",
  LEAD: "bg-blue-950",
  OPPORTUNITY: "bg-amber-950",
  CUSTOMER: "bg-green-950",
  ARCHIVED: "bg-gray-900",
};

const STATUS_COLORS: Record<string, string> = {
  running: "text-green-400", healthy: "text-green-400",
  degraded: "text-amber-400", stale: "text-red-400",
  starting: "text-blue-400",
};

const STATUS_DOT: Record<string, string> = {
  running: "bg-green-400", healthy: "bg-green-400",
  degraded: "bg-amber-400", stale: "bg-red-400",
  starting: "bg-blue-400",
};

function StageDrillDown({ stage, onClose }: { stage: string; onClose: () => void }) {
  const [items, setItems] = useState<{ id: number; name: string; address: string; county: string; heat_score: string }[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/proxy/leads?status_filter=${stage}&limit=20&sort_by=value&sort_dir=desc`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data) {
          setItems(data.results || []);
          setTotal(data.total || 0);
        }
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [stage]);

  const heatDot: Record<string, string> = { hot: "bg-red-500", warm: "bg-orange-500", cold: "bg-blue-500" };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg mt-3 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
        <span className="text-xs font-medium text-gray-300">Top {stage}s by Value ({total.toLocaleString()} total)</span>
        <button onClick={onClose} className="text-gray-500 hover:text-white text-sm">&times;</button>
      </div>
      {loading ? (
        <p className="text-gray-600 text-xs px-3 py-2">Loading...</p>
      ) : (
        <div className="max-h-[300px] overflow-y-auto">
          {items.map((item) => (
            <div key={item.id} className="flex items-center gap-2 px-3 py-1.5 border-b border-gray-800/50 hover:bg-gray-800/30 text-xs">
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${heatDot[item.heat_score] || "bg-gray-600"}`} />
              <span className="text-white font-medium truncate flex-1">{item.name}</span>
              <span className="text-gray-500 truncate max-w-[120px]">{item.county}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function OpsPage() {
  const [tab, setTab] = useState<ActiveTab>("pipeline");
  const [counties, setCounties] = useState<{
    counties: { county_no: string; county_name: string; nal_file: string | null; sdf_file: string | null; nal_size: number; sdf_size: number; ready: boolean; lead_count: number }[];
    nal_download_url: string;
  } | null>(null);
  const [seeding, setSeeding] = useState<string | null>(null);
  const [seedResult, setSeedResult] = useState<string | null>(null);
  const [seedMinValue, setSeedMinValue] = useState("5000000");
  const [resetting, setResetting] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [services, setServices] = useState<ServiceStatus[]>([]);
  const [enrichStatus, setEnrichStatus] = useState<EnrichStatus | null>(null);
  const [enriching, setEnriching] = useState(false);
  const [enrichMsg, setEnrichMsg] = useState<string | null>(null);

  // Query state
  const [queryTable, setQueryTable] = useState("entities");
  const [queryText, setQueryText] = useState("");
  const [queryCounty, setQueryCounty] = useState("");
  const [queryStage, setQueryStage] = useState("");
  const [queryResults, setQueryResults] = useState<QueryResult | null>(null);
  const [querying, setQuerying] = useState(false);
  const [expandedStage, setExpandedStage] = useState<string | null>(null);

  // Events state
  const [events, setEvents] = useState<EventItem[]>([]);
  const [eventsLive, setEventsLive] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  // ─── Fetchers ───

  const fetchCounties = useCallback(async () => {
    try {
      const res = await fetch("/api/proxy/admin/counties");
      if (res.ok) setCounties(await res.json());
    } catch {}
  }, []);

  const fetchServices = useCallback(async () => {
    try {
      const res = await fetch("/api/proxy/status");
      if (res.ok) {
        const data = await res.json();
        setServices(Array.isArray(data) ? data : data.services || []);
      }
    } catch {}
  }, []);

  const fetchEnrichStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/proxy/admin/enrich/status");
      if (res.ok) setEnrichStatus(await res.json());
    } catch {}
  }, []);

  const fetchEvents = useCallback(async () => {
    try {
      const res = await fetch("/api/proxy/events?limit=200");
      if (res.ok) {
        const data = await res.json();
        setEvents(Array.isArray(data) ? data : []);
      }
    } catch {}
  }, []);

  // ─── Actions ───

  async function seedCounty(countyNo: string) {
    setSeeding(countyNo);
    setSeedResult(null);
    try {
      const params = seedMinValue ? `?min_value=${seedMinValue}` : "";
      const res = await fetch(`/api/proxy/admin/seed-county/${countyNo}${params}`, { method: "POST" });
      const data = await res.json().catch(() => ({ error: res.statusText }));
      if (!res.ok || data.error) {
        setSeedResult(`Error: ${data.error || res.statusText}`);
      } else {
        setSeedResult(`${data.county}: ${data.created?.toLocaleString()} targets from ${data.filtered?.toLocaleString()} filtered (${data.total_parcels?.toLocaleString()} parcels)`);
      }
      fetchCounties();
      fetchEnrichStatus();
    } catch (err) {
      setSeedResult(`Network error: ${err}`);
    }
    setSeeding(null);
  }

  async function seedAll() {
    setSeeding("all");
    setSeedResult(null);
    try {
      const params = seedMinValue ? `?min_value=${seedMinValue}` : "";
      const res = await fetch(`/api/proxy/admin/seed-all${params}`, { method: "POST" });
      const data = await res.json().catch(() => ({ error: res.statusText }));
      if (!res.ok || data.error) {
        setSeedResult(`Error: ${data.error || res.statusText}`);
      } else {
        const total = data.results?.reduce((s: number, r: { created?: number }) => s + (r.created || 0), 0) || 0;
        setSeedResult(`Seeded ${total.toLocaleString()} targets across ${data.results?.length || 0} counties`);
      }
      fetchCounties();
      fetchEnrichStatus();
    } catch (err) {
      setSeedResult(`Network error: ${err}`);
    }
    setSeeding(null);
  }

  async function resetDatabase() {
    setResetting(true);
    setSeedResult(null);
    try {
      const res = await fetch("/api/proxy/admin/reset", { method: "POST" });
      const data = await res.json().catch(() => ({ error: res.statusText }));
      if (res.ok) {
        setSeedResult(`Database reset complete. ${data.message || "Ready for seeding."}`);
      } else {
        setSeedResult(`Error: ${data.detail || data.error || res.statusText}`);
      }
      fetchCounties();
      fetchEnrichStatus();
    } catch (err) {
      setSeedResult(`Network error: ${err}`);
    }
    setResetting(false);
    setConfirmReset(false);
  }

  async function triggerEnrich() {
    setEnriching(true);
    setEnrichMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/enrich", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setEnrichMsg(data.message);
      } else {
        setEnrichMsg("Failed to start enrichment");
      }
    } catch (err) {
      setEnrichMsg(`Error: ${err}`);
    }
    setEnriching(false);
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
    } catch {}
    setQuerying(false);
  }

  // SSE for live events
  function toggleLiveEvents() {
    if (eventsLive && eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      setEventsLive(false);
      return;
    }
    try {
      const es = new EventSource("/api/proxy/events/stream");
      es.onmessage = (e) => {
        try {
          const evt = JSON.parse(e.data);
          setEvents((prev) => [evt, ...prev].slice(0, 500));
        } catch {}
      };
      es.onerror = () => {
        es.close();
        setEventsLive(false);
        eventSourceRef.current = null;
      };
      eventSourceRef.current = es;
      setEventsLive(true);
    } catch {
      setEventsLive(false);
    }
  }

  // ─── Effects ───

  useEffect(() => {
    fetchServices();
    fetchEnrichStatus();
    fetchCounties();
    const interval = setInterval(() => {
      fetchServices();
      fetchEnrichStatus();
    }, 15000);
    return () => {
      clearInterval(interval);
      eventSourceRef.current?.close();
    };
  }, [fetchServices, fetchEnrichStatus, fetchCounties]);

  useEffect(() => {
    if (tab === "events") fetchEvents();
  }, [tab, fetchEvents]);

  // ─── Helpers ───

  const totalEntities = enrichStatus?.stage_counts
    ? Object.values(enrichStatus.stage_counts).reduce((a, b) => a + b, 0)
    : enrichStatus?.total_leads || 0;

  const tabs: { key: ActiveTab; label: string; badge?: number }[] = [
    { key: "pipeline", label: "Pipeline", badge: totalEntities },
    { key: "counties", label: "Counties" },
    { key: "services", label: "Services", badge: services.length },
    { key: "query", label: "Query" },
    { key: "events", label: "Events" },
    { key: "email", label: "Email" },
  ];

  function fmtTime(ts: number | string) {
    const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
    return d.toLocaleTimeString();
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="bg-gray-900 border-b border-gray-800 px-4 md:px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-gray-400 hover:text-white text-sm">&larr; Dashboard</Link>
          <span className="text-gray-700">|</span>
          <h1 className="text-lg font-bold">Ops Center</h1>
        </div>
        <div className="flex gap-2 text-xs">
          <Link href="/files" className="text-gray-400 hover:text-white">File Manager</Link>
        </div>
      </header>

      {/* Tabs */}
      <div className="border-b border-gray-800 px-4 md:px-6 overflow-x-auto">
        <div className="flex gap-1 -mb-px min-w-max">
          {tabs.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 flex items-center gap-1.5 ${
                tab === t.key ? "border-blue-500 text-white" : "border-transparent text-gray-500 hover:text-gray-300"
              }`}>
              {t.label}
              {t.badge !== undefined && t.badge > 0 && (
                <span className="bg-gray-800 text-gray-400 text-[10px] px-1.5 py-0.5 rounded-full">{t.badge.toLocaleString()}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="px-3 md:px-6 py-4 md:py-6 max-w-7xl">

        {/* ═══ PIPELINE TAB ═══ */}
        {tab === "pipeline" && (
          <div className="space-y-6">
            {/* Stage funnel */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-gray-300">Pipeline Stages</h2>
                <button onClick={fetchEnrichStatus}
                  className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-1.5 rounded">
                  Refresh
                </button>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                {PIPELINE_STAGES.map((stage) => {
                  const count = enrichStatus?.stage_counts?.[stage] ?? 0;
                  const isExpanded = expandedStage === stage;
                  return (
                    <button key={stage} onClick={() => setExpandedStage(isExpanded ? null : stage)}
                      className={`${STAGE_BG[stage]} border ${STAGE_COLORS[stage].split(" ")[0]} rounded-lg p-4 text-center hover:ring-1 hover:ring-white/20 transition-all ${isExpanded ? "ring-2 ring-white/30" : ""}`}>
                      <p className="text-2xl md:text-3xl font-bold text-white">{count.toLocaleString()}</p>
                      <p className={`text-xs mt-1 font-medium ${STAGE_COLORS[stage].split(" ")[1]}`}>
                        {stage === "TARGET" ? "Targets" :
                         stage === "LEAD" ? "Leads" :
                         stage === "OPPORTUNITY" ? "Opportunities" :
                         stage === "CUSTOMER" ? "Customers" : "Archived"}
                      </p>
                    </button>
                  );
                })}
              </div>
              {/* Drill-down list for clicked stage */}
              {expandedStage && (
                <StageDrillDown stage={expandedStage} onClose={() => setExpandedStage(null)} />
              )}
              {/* Flow arrows (desktop) */}
              <div className="hidden sm:flex items-center justify-between px-8 mt-1 text-gray-600 text-[10px]">
                <span>NAL Seed</span>
                <span>&rarr; Geocode &rarr;</span>
                <span>&rarr; Enrich &rarr;</span>
                <span>&rarr; Manual &rarr;</span>
                <span></span>
              </div>
            </div>

            {/* Enrichment Coverage */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-gray-300">Enrichment Coverage</h2>
                <div className="flex gap-2 items-center">
                  {enrichMsg && (
                    <span className={`text-xs ${enrichMsg.startsWith("Error") || enrichMsg.startsWith("Failed") ? "text-red-300" : "text-green-300"}`}>
                      {enrichMsg}
                    </span>
                  )}
                  <button onClick={triggerEnrich} disabled={enriching}
                    className="bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-xs px-4 py-1.5 rounded font-medium">
                    {enriching ? "Starting..." : "Enrich All Leads"}
                  </button>
                </div>
              </div>
              {enrichStatus && (
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-3">
                  {Object.entries(enrichStatus.coverage || {}).map(([source, rawCount]) => {
                    const count = Number(rawCount) || 0;
                    const pct = enrichStatus.total_leads > 0
                      ? Math.round((count / enrichStatus.total_leads) * 100) : 0;
                    return (
                      <div key={source} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                        <div className="flex items-center justify-between mb-1">
                          <p className="text-gray-500 text-[10px] uppercase tracking-wider">
                            {source.replace(/_/g, " ")}
                          </p>
                          <span className={`text-[10px] font-medium ${pct > 50 ? "text-green-400" : pct > 0 ? "text-amber-400" : "text-gray-600"}`}>
                            {pct}%
                          </span>
                        </div>
                        <p className="text-lg font-bold text-white">{Number(count).toLocaleString()}</p>
                        {/* Progress bar */}
                        <div className="h-1 bg-gray-800 rounded-full mt-2 overflow-hidden">
                          <div className={`h-full rounded-full ${pct > 50 ? "bg-green-500" : pct > 0 ? "bg-amber-500" : "bg-gray-700"}`}
                            style={{ width: `${Math.max(pct, 2)}%` }} />
                        </div>
                      </div>
                    );
                  })}
                  <div className="bg-gray-900 border border-red-900/50 rounded-lg p-3">
                    <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-1">No Enrichment</p>
                    <p className="text-lg font-bold text-red-400">{(enrichStatus.no_enrichment ?? 0).toLocaleString()}</p>
                    <div className="h-1 bg-gray-800 rounded-full mt-2 overflow-hidden">
                      <div className="h-full rounded-full bg-red-500"
                        style={{ width: `${enrichStatus.total_leads > 0 ? Math.max(Math.round((enrichStatus.no_enrichment / enrichStatus.total_leads) * 100), 2) : 0}%` }} />
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Active Workers */}
            <div>
              <h2 className="text-sm font-semibold text-gray-300 mb-3">Active Workers</h2>
              {services.length === 0 ? (
                <p className="text-gray-600 text-sm">No workers registered.</p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {services.map((svc) => (
                    <div key={svc.name} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className={`w-2 h-2 rounded-full ${STATUS_DOT[svc.status] || "bg-gray-600"}`} />
                        <h3 className="font-medium text-white text-sm">{svc.name}</h3>
                        <span className={`text-[10px] ml-auto ${STATUS_COLORS[svc.status] || "text-gray-500"}`}>
                          {svc.status}
                        </span>
                      </div>
                      <p className="text-gray-500 text-xs truncate">{svc.detail}</p>
                      <p className="text-gray-700 text-[10px] mt-1">
                        {fmtTime(svc.last_heartbeat)}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Quick Actions */}
            <div className="border-t border-gray-800 pt-4">
              <h2 className="text-sm font-semibold text-gray-300 mb-3">Actions</h2>
              <div className="flex flex-wrap gap-2">
                <button onClick={resetDatabase}
                  className="bg-red-900/50 hover:bg-red-900 border border-red-800 text-red-300 text-xs px-4 py-2 rounded font-medium">
                  Reset Database
                </button>
                <button onClick={seedAll} disabled={seeding !== null}
                  className="bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-xs px-4 py-2 rounded font-medium">
                  {seeding === "all" ? "Seeding..." : "Seed All Counties"}
                </button>
                <button onClick={triggerEnrich} disabled={enriching}
                  className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs px-4 py-2 rounded font-medium">
                  Enrich All Leads
                </button>
              </div>
              {seedResult && (
                <div className={`text-xs px-4 py-2 rounded mt-3 ${seedResult.startsWith("Error") || seedResult.startsWith("Network") || seedResult.startsWith("Reset error") ? "bg-red-900/50 text-red-300 border border-red-800" : "bg-green-900/50 text-green-300 border border-green-800"}`}>
                  {seedResult}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ═══ COUNTIES TAB ═══ */}
        {tab === "counties" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-gray-300">County Data Sources</h2>
                <p className="text-gray-600 text-xs mt-1">
                  Upload NAL + SDF from{" "}
                  <a href="https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx"
                    target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">
                    FL DOR Data Portal
                  </a>
                  {" "}to System Data/DOR/ via{" "}
                  <Link href="/files" className="text-blue-400 hover:underline">File Manager</Link>
                </p>
              </div>
              <div className="flex gap-2 items-center flex-wrap">
                <div className="flex items-center gap-1.5 bg-gray-900 border border-gray-700 rounded px-2 py-1">
                  <label className="text-[10px] text-gray-500 shrink-0">Min $</label>
                  <select value={seedMinValue} onChange={(e) => setSeedMinValue(e.target.value)}
                    className="bg-transparent text-white text-xs focus:outline-none">
                    <option value="0">No min</option>
                    <option value="1000000">$1M</option>
                    <option value="3000000">$3M</option>
                    <option value="5000000">$5M</option>
                    <option value="10000000">$10M</option>
                    <option value="25000000">$25M</option>
                  </select>
                </div>
                <button onClick={seedAll} disabled={seeding !== null || resetting}
                  className="bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-xs px-4 py-2 rounded font-medium">
                  {seeding === "all" ? "Seeding..." : "Seed All"}
                </button>
                {!confirmReset ? (
                  <button onClick={() => setConfirmReset(true)} disabled={resetting || seeding !== null}
                    className="bg-red-900/60 hover:bg-red-800 disabled:opacity-50 text-red-300 text-xs px-3 py-2 rounded border border-red-800">
                    Reset DB
                  </button>
                ) : (
                  <div className="flex items-center gap-1.5 bg-red-950 border border-red-700 rounded px-3 py-1.5">
                    <span className="text-red-300 text-xs">Wipe all leads?</span>
                    <button onClick={resetDatabase} disabled={resetting}
                      className="bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white text-[11px] px-2.5 py-1 rounded font-medium">
                      {resetting ? "Resetting..." : "Yes, wipe"}
                    </button>
                    <button onClick={() => setConfirmReset(false)}
                      className="text-gray-400 hover:text-white text-[11px] px-2 py-1">
                      Cancel
                    </button>
                  </div>
                )}
                <button onClick={fetchCounties}
                  className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-2 rounded">
                  Refresh
                </button>
                <button onClick={async () => {
                  setSeedResult(null);
                  try {
                    const res = await fetch("/api/proxy/admin/download-cadastral", { method: "POST" });
                    const data = await res.json().catch(() => ({ error: res.statusText }));
                    setSeedResult(data.message || "Cadastral download started");
                  } catch (err) {
                    setSeedResult(`Error: ${err}`);
                  }
                }}
                  className="bg-purple-600 hover:bg-purple-700 text-white text-xs px-3 py-2 rounded font-medium">
                  Pull ArcGIS
                </button>
                <button onClick={async () => {
                  setSeedResult(null);
                  try {
                    const res = await fetch("/api/proxy/admin/download-sunbiz", { method: "POST" });
                    const data = await res.json().catch(() => ({ error: res.statusText }));
                    setSeedResult(data.message || "Sunbiz download started");
                  } catch (err) {
                    setSeedResult(`Error: ${err}`);
                  }
                }}
                  className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-2 rounded font-medium">
                  Pull Sunbiz
                </button>
                <button onClick={async () => {
                  setSeedResult(null);
                  try {
                    const res = await fetch("/api/proxy/admin/refresh-data", { method: "POST" });
                    const data = await res.json().catch(() => ({ error: res.statusText }));
                    setSeedResult(data.message || "Data refresh started");
                  } catch (err) {
                    setSeedResult(`Error: ${err}`);
                  }
                }}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs px-3 py-2 rounded font-medium">
                  Refresh All Data
                </button>
              </div>
            </div>

            {seedResult && (
              <div className={`text-xs px-4 py-2 rounded ${seedResult.startsWith("Error") || seedResult.startsWith("Network") ? "bg-red-900/50 text-red-300 border border-red-800" : "bg-green-900/50 text-green-300 border border-green-800"}`}>
                {seedResult}
              </div>
            )}

            {counties && (
              <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-800 text-gray-500 text-xs">
                        <th className="text-left px-4 py-2.5">County</th>
                        <th className="text-left px-4 py-2.5 hidden sm:table-cell">Code</th>
                        <th className="text-right px-4 py-2.5">NAL</th>
                        <th className="text-right px-4 py-2.5 hidden sm:table-cell">SDF</th>
                        <th className="text-right px-4 py-2.5">Entities</th>
                        <th className="text-right px-4 py-2.5"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {(counties.counties || []).map((c) => (
                        <tr key={c.county_no} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                          <td className="px-4 py-2.5 text-white font-medium">{c.county_name}</td>
                          <td className="px-4 py-2.5 text-gray-500 font-mono text-xs hidden sm:table-cell">{c.county_no}</td>
                          <td className="px-4 py-2.5 text-right">
                            {c.nal_file ? (
                              <span className="text-green-400 text-xs">{(c.nal_size / 1024 / 1024).toFixed(0)}MB</span>
                            ) : (
                              <span className="text-red-400 text-xs">Missing</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-right hidden sm:table-cell">
                            {c.sdf_file ? (
                              <span className="text-green-400 text-xs">{(c.sdf_size / 1024 / 1024).toFixed(1)}MB</span>
                            ) : (
                              <span className="text-gray-600 text-xs">-</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-right text-white font-medium">{(c.lead_count ?? 0).toLocaleString()}</td>
                          <td className="px-4 py-2.5 text-right">
                            {c.ready && (
                              <button onClick={() => seedCounty(c.county_no)}
                                disabled={seeding !== null}
                                className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-[11px] px-3 py-1 rounded">
                                {seeding === c.county_no ? "..." : c.lead_count > 0 ? "Reseed" : "Seed"}
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t border-gray-700 bg-gray-900/50">
                        <td className="px-4 py-2 text-gray-400 text-xs font-medium">Total</td>
                        <td className="hidden sm:table-cell"></td>
                        <td className="px-4 py-2 text-right text-gray-400 text-xs">
                          {counties.counties.filter(c => c.nal_file).length}/{counties.counties.length}
                        </td>
                        <td className="hidden sm:table-cell"></td>
                        <td className="px-4 py-2 text-right text-white font-medium text-sm">
                          {counties.counties.reduce((s, c) => s + c.lead_count, 0).toLocaleString()}
                        </td>
                        <td></td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ═══ SERVICES TAB ═══ */}
        {tab === "services" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-300">Registered Services</h2>
              <button onClick={fetchServices}
                className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-1.5 rounded">
                Refresh
              </button>
            </div>
            {services.length === 0 ? (
              <p className="text-gray-600 text-sm">No services registered.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {services.map((svc) => (
                  <div key={svc.name} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`w-2.5 h-2.5 rounded-full ${STATUS_DOT[svc.status] || "bg-gray-600"}`} />
                      <h3 className="font-medium text-white">{svc.name}</h3>
                      <span className={`text-xs font-medium ml-auto ${STATUS_COLORS[svc.status] || "text-gray-500"}`}>
                        {svc.status}
                      </span>
                    </div>
                    <p className="text-gray-400 text-sm mb-2">{svc.detail}</p>
                    <p className="text-gray-600 text-[10px]">
                      Last heartbeat: {fmtTime(svc.last_heartbeat)}
                    </p>
                    {svc.capabilities && Object.keys(svc.capabilities).length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1">
                        {Object.entries(svc.capabilities).map(([k, v]) => (
                          <span key={k} className="bg-gray-800 text-gray-400 text-[10px] px-2 py-0.5 rounded">
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

        {/* ═══ QUERY TAB ═══ */}
        {tab === "query" && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Data Explorer</h2>

            {/* Canned queries */}
            <div className="flex flex-wrap gap-1.5">
              {[
                { label: "All Condos (004)", table: "entities", q: "", county: "", stage: "TARGET", extra: "&use_code=004" },
                { label: "LEADs by Value", table: "entities", q: "", county: "", stage: "LEAD", extra: "&sort_by=value&sort_dir=desc" },
                { label: "Citizens Properties", table: "entities", q: "", county: "", stage: "", extra: "&on_citizens=true" },
                { label: "7+ Stories", table: "entities", q: "7+ stories", county: "", stage: "", extra: "" },
                { label: "Pasco Condos", table: "entities", q: "", county: "Pasco", stage: "", extra: "&use_code=004" },
                { label: "All Contacts", table: "contacts", q: "", county: "", stage: "", extra: "" },
                { label: "Hot Leads", table: "entities", q: "", county: "", stage: "LEAD", extra: "&heat=hot" },
              ].map((cq) => (
                <button key={cq.label} onClick={() => {
                  setQueryTable(cq.table);
                  setQueryText(cq.q);
                  setQueryCounty(cq.county);
                  setQueryStage(cq.stage);
                  // Trigger query after state settles
                  setTimeout(() => {
                    const params = new URLSearchParams({ table: cq.table, limit: "100" });
                    if (cq.q) params.set("q", cq.q);
                    if (cq.county) params.set("county", cq.county);
                    if (cq.stage) params.set("stage", cq.stage);
                    const url = `/api/proxy/admin/query?${params}${cq.extra}`;
                    fetch(url).then(r => r.ok ? r.json() : null).then(d => d && setQueryResults(d));
                  }, 50);
                }}
                  className="bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-400 hover:text-white text-[11px] px-2.5 py-1.5 rounded">
                  {cq.label}
                </button>
              ))}
            </div>

            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <select value={queryTable} onChange={(e) => setQueryTable(e.target.value)}
                  className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white">
                  <option value="entities">Entities</option>
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
                    {PIPELINE_STAGES.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                )}
                <button onClick={runQuery} disabled={querying}
                  className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium rounded text-sm py-2">
                  {querying ? "..." : "Search"}
                </button>
              </div>
              <input type="text" value={queryText} onChange={(e) => setQueryText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runQuery()}
                placeholder="Search by name, address, or owner..."
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600" />
            </div>

            {queryResults && Array.isArray(queryResults.results) && (
              <div>
                <p className="text-gray-500 text-xs mb-2">
                  {queryResults.showing} of {queryResults.total.toLocaleString()} results
                </p>
                <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-auto max-h-[60vh]">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-gray-900 z-10">
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
                              {val === null ? <span className="text-gray-700">-</span> :
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

        {/* ═══ EVENTS TAB ═══ */}
        {tab === "events" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-300">
                Event Stream
                {eventsLive && <span className="ml-2 text-green-400 text-[10px] animate-pulse">LIVE</span>}
              </h2>
              <div className="flex gap-2">
                <button onClick={toggleLiveEvents}
                  className={`text-xs px-3 py-1.5 rounded font-medium ${
                    eventsLive
                      ? "bg-red-900 hover:bg-red-800 text-red-300 border border-red-700"
                      : "bg-green-600 hover:bg-green-700 text-white"
                  }`}>
                  {eventsLive ? "Stop Live" : "Go Live"}
                </button>
                <button onClick={fetchEvents}
                  className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-1.5 rounded">
                  Refresh
                </button>
              </div>
            </div>

            {events.length === 0 ? (
              <p className="text-gray-600 text-sm">No events recorded yet.</p>
            ) : (
              <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-auto max-h-[70vh]">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-900 z-10">
                    <tr className="border-b border-gray-800">
                      <th className="text-left px-3 py-2 text-gray-500 w-20">Time</th>
                      <th className="text-left px-3 py-2 text-gray-500 w-16">Status</th>
                      <th className="text-left px-3 py-2 text-gray-500 w-20">Source</th>
                      <th className="text-left px-3 py-2 text-gray-500 w-32">Action</th>
                      <th className="text-left px-3 py-2 text-gray-500">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((evt, i) => (
                      <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/20">
                        <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap font-mono">
                          {fmtTime(evt.timestamp)}
                        </td>
                        <td className="px-3 py-1.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                            evt.status === "success" ? "bg-green-900/60 text-green-300" :
                            evt.status === "error" ? "bg-red-900/60 text-red-300" :
                            "bg-blue-900/60 text-blue-300"
                          }`}>{evt.status}</span>
                        </td>
                        <td className="px-3 py-1.5 text-gray-400 whitespace-nowrap">
                          {evt.event_type?.toLowerCase?.() || evt.event_type}
                        </td>
                        <td className="px-3 py-1.5 text-white whitespace-nowrap">{evt.action}</td>
                        <td className="px-3 py-1.5 text-gray-500 truncate max-w-[400px]">
                          {evt.detail}
                          {evt.duration_ms ? <span className="text-gray-700 ml-1">({evt.duration_ms.toFixed(0)}ms)</span> : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ═══ EMAIL TAB ═══ */}
        {tab === "email" && <EmailTab />}
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════
   EMAIL TAB — generate, preview, export, and ingest emails
   ═══════════════════════════════════════════════════════════════════ */

interface EmailPreviewItem {
  engagement_id: number;
  entity_id: number;
  entity_name: string;
  county: string;
  pipeline_stage: string;
  subject: string;
  style: string;
  to_email: string | null;
  contact_name: string | null;
  has_email: boolean;
}

interface IngestResult {
  matched: number;
  unmatched: number;
  duplicates: number;
  matched_details: { filename: string; entity_id: number; from: string; subject: string }[];
  unmatched_details: { filename: string; from?: string; to?: string; subject?: string; error: string }[];
}

function EmailTab() {
  const [preview, setPreview] = useState<{ total: number; ready_to_send: number; missing_email: number; items: EmailPreviewItem[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [genLoading, setGenLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [ingestResult, setIngestResult] = useState<IngestResult | null>(null);
  const [ingestLoading, setIngestLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [genStyle, setGenStyle] = useState("formal");
  const [genStage, setGenStage] = useState("LEAD");
  const [genCounty, setGenCounty] = useState("");
  const [genTier, setGenTier] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const STYLES = ["formal", "informal", "cost_effective", "risk_averse"];

  async function loadPreview() {
    setLoading(true);
    setMsg(null);
    try {
      const res = await fetch("/api/proxy/email/export/preview?limit=100");
      if (res.ok) {
        setPreview(await res.json());
      } else {
        setMsg("Failed to load preview (" + res.status + ")");
      }
    } catch {
      setMsg("Unable to connect");
    }
    setLoading(false);
  }

  async function generateBulk() {
    setGenLoading(true);
    setMsg(null);
    try {
      const body: Record<string, string> = { style: genStyle, stage: genStage };
      if (genCounty) body.county = genCounty;
      if (genTier) body.cream_tier = genTier;
      const res = await fetch("/api/proxy/email/generate-bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const data = await res.json();
        setMsg(`Generated ${data.created} engagements (${data.skipped} skipped — no email template)`);
        loadPreview();
      } else {
        const err = await res.json().catch(() => ({ detail: res.status }));
        setMsg("Generate failed: " + (err.detail ?? res.status));
      }
    } catch {
      setMsg("Generate failed — unable to connect");
    }
    setGenLoading(false);
  }

  async function exportEmails() {
    setExportLoading(true);
    setMsg(null);
    try {
      const res = await fetch("/api/proxy/email/export");
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `insure_emails_${new Date().toISOString().slice(0, 10)}.zip`;
        a.click();
        URL.revokeObjectURL(url);
        setMsg("Exported! Import the .zip into Outlook Drafts.");
        loadPreview();
      } else if (res.status === 404) {
        setMsg("No queued emails to export. Generate some first.");
      } else {
        setMsg("Export failed (" + res.status + ")");
      }
    } catch {
      setMsg("Export failed — unable to connect");
    }
    setExportLoading(false);
  }

  async function handleIngest(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setIngestLoading(true);
    setMsg(null);
    setIngestResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/proxy/email/ingest", { method: "POST", body: form });
      if (res.ok) {
        const data: IngestResult = await res.json();
        setIngestResult(data);
        setMsg(`Ingested: ${data.matched} matched, ${data.unmatched} unmatched, ${data.duplicates} duplicates`);
      } else {
        const err = await res.json().catch(() => ({ detail: res.status }));
        setMsg("Ingest failed: " + (err.detail ?? res.status));
      }
    } catch {
      setMsg("Ingest failed — unable to connect");
    }
    setIngestLoading(false);
    if (fileRef.current) fileRef.current.value = "";
  }

  useEffect(() => { loadPreview(); }, []);

  return (
    <div className="space-y-6">
      {msg && (
        <div className={`text-xs px-3 py-2 rounded border ${
          msg.includes("failed") || msg.includes("Failed")
            ? "bg-red-900/30 text-red-300 border-red-800"
            : "bg-green-900/30 text-green-300 border-green-800"
        }`}>
          {msg}
        </div>
      )}

      {/* ── OUTBOUND: Generate + Export ── */}
      <div>
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Outbound — Generate & Export to Outlook</h2>

        {/* Generate controls */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
          <p className="text-xs text-gray-500">
            Step 1: Generate email engagements from AI templates. Step 2: Export as .eml zip. Step 3: Import into Outlook Drafts and send.
          </p>
          <div className="flex gap-2 flex-wrap">
            <select value={genStyle} onChange={(e) => setGenStyle(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white">
              {STYLES.map(s => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
            </select>
            <select value={genStage} onChange={(e) => setGenStage(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white">
              <option value="LEAD">LEAD</option>
              <option value="OPPORTUNITY">OPPORTUNITY</option>
            </select>
            <select value={genCounty} onChange={(e) => setGenCounty(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white">
              <option value="">All Counties</option>
              {COUNTIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={genTier} onChange={(e) => setGenTier(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white">
              <option value="">All Tiers</option>
              <option value="platinum">Platinum</option>
              <option value="gold">Gold</option>
              <option value="silver">Silver</option>
            </select>
            <button onClick={generateBulk} disabled={genLoading}
              className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs px-4 py-1.5 rounded font-medium">
              {genLoading ? "Generating..." : "Generate Emails"}
            </button>
          </div>

          {/* Export button + preview summary */}
          <div className="flex items-center gap-3 pt-2 border-t border-gray-800">
            <button onClick={exportEmails} disabled={exportLoading || !preview || preview.ready_to_send === 0}
              className="bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white text-xs px-4 py-1.5 rounded font-medium">
              {exportLoading ? "Exporting..." : "Export .eml Zip"}
            </button>
            <button onClick={loadPreview} disabled={loading}
              className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-1.5 rounded">
              Refresh
            </button>
            {preview && (
              <span className="text-xs text-gray-500">
                {preview.ready_to_send} ready to export, {preview.missing_email} missing contact email
              </span>
            )}
          </div>
        </div>

        {/* Preview table */}
        {preview && preview.items.length > 0 && (
          <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-auto max-h-[40vh] mt-3">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-gray-900 z-10">
                <tr className="border-b border-gray-800">
                  <th className="text-left px-3 py-2 text-gray-500">Entity</th>
                  <th className="text-left px-3 py-2 text-gray-500">County</th>
                  <th className="text-left px-3 py-2 text-gray-500">Subject</th>
                  <th className="text-left px-3 py-2 text-gray-500">To</th>
                  <th className="text-left px-3 py-2 text-gray-500">Style</th>
                </tr>
              </thead>
              <tbody>
                {preview.items.map((item) => (
                  <tr key={item.engagement_id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
                    <td className="px-3 py-1.5 text-white truncate max-w-[200px]">{item.entity_name}</td>
                    <td className="px-3 py-1.5 text-gray-500">{item.county}</td>
                    <td className="px-3 py-1.5 text-gray-400 truncate max-w-[250px]">{item.subject}</td>
                    <td className={`px-3 py-1.5 ${item.has_email ? "text-green-400" : "text-red-400"}`}>
                      {item.to_email ?? "No contact email"}
                    </td>
                    <td className="px-3 py-1.5 text-gray-600">{item.style}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── INBOUND: Ingest from Outlook ── */}
      <div>
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Inbound — Ingest Outlook Replies</h2>
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
          <p className="text-xs text-gray-500">
            Export emails from Outlook as .eml files (or zip them together). Upload here to auto-match replies to entities and create engagement records.
          </p>
          <div className="flex items-center gap-3">
            <input ref={fileRef} type="file" accept=".eml,.zip" onChange={handleIngest}
              className="text-xs text-gray-400 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-xs file:font-medium file:bg-blue-600 file:text-white hover:file:bg-blue-700" />
            {ingestLoading && <span className="text-xs text-gray-500">Processing...</span>}
          </div>
        </div>

        {/* Ingest results */}
        {ingestResult && (
          <div className="mt-3 space-y-3">
            <div className="flex gap-4 text-xs">
              <span className="text-green-400">{ingestResult.matched} matched</span>
              <span className="text-amber-400">{ingestResult.unmatched} unmatched</span>
              <span className="text-gray-500">{ingestResult.duplicates} duplicates skipped</span>
            </div>

            {ingestResult.matched_details.length > 0 && (
              <div className="bg-gray-900 border border-green-900 rounded-lg overflow-auto max-h-[25vh]">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-900">
                    <tr className="border-b border-gray-800">
                      <th className="text-left px-3 py-2 text-gray-500">Entity</th>
                      <th className="text-left px-3 py-2 text-gray-500">From</th>
                      <th className="text-left px-3 py-2 text-gray-500">Subject</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ingestResult.matched_details.map((m, i) => (
                      <tr key={i} className="border-b border-gray-800/50">
                        <td className="px-3 py-1.5 text-green-400">#{m.entity_id}</td>
                        <td className="px-3 py-1.5 text-gray-400 truncate max-w-[200px]">{m.from}</td>
                        <td className="px-3 py-1.5 text-white truncate max-w-[250px]">{m.subject}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {ingestResult.unmatched_details.length > 0 && (
              <div className="bg-gray-900 border border-amber-900 rounded-lg overflow-auto max-h-[25vh]">
                <p className="px-3 py-2 text-xs text-amber-400 border-b border-gray-800">Unmatched — link manually via API</p>
                <table className="w-full text-xs">
                  <tbody>
                    {ingestResult.unmatched_details.map((u, i) => (
                      <tr key={i} className="border-b border-gray-800/50">
                        <td className="px-3 py-1.5 text-gray-400 truncate max-w-[200px]">{u.from ?? ""}</td>
                        <td className="px-3 py-1.5 text-gray-400 truncate max-w-[200px]">{u.subject ?? ""}</td>
                        <td className="px-3 py-1.5 text-amber-500 text-[10px]">{u.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
