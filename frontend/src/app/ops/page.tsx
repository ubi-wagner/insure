"use client";

import { Fragment, useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";

/* ================================================================
   Types
   ================================================================ */

interface CountyRow {
  county_no: string;
  county: string;
  nal_ready: boolean;
  nal_total: number | null;
  type_passed: number | null;
  value_filtered: number | null;
  last_seeded: string | null;
}

interface ServiceStatus {
  name: string;
  status: string;
  last_heartbeat: string;
  capabilities: Record<string, unknown>;
  detail: string;
}

interface QueueStats {
  total_jobs: number;
  status_counts: Record<string, number>;
  enricher_stats: Record<string, Record<string, number>>;
  enricher_by_county: Record<string, Record<string, Record<string, number>>>;
  recent_failures: {
    job_id: number;
    entity_id: number;
    enricher: string;
    error: string | null;
    attempts: number;
    entity_name: string | null;
  }[];
  worker_id: string;
}

interface DashboardData {
  counties: CountyRow[];
  stage_counts: Record<string, number>;
  total_active: number;
  services: ServiceStatus[];
  queue?: QueueStats;
}

interface EventItem {
  event_type: string;
  action: string;
  status: string;
  detail: string;
  timestamp: number;
  duration_ms?: number;
}

/* ================================================================
   Constants
   ================================================================ */

const ENRICHER_LABELS: Record<string, string> = {
  dor_nal: "DOR NAL",
  fema_flood: "FEMA Flood",
  property_appraiser: "Property Appraiser",
  dbpr_bulk: "DBPR Condo",
  dbpr_payments: "DBPR Payments",
  cam_license: "CAM License",
  sunbiz: "Sunbiz",
  sunbiz_bulk: "Sunbiz",
  dbpr_sirs: "DBPR SIRS",
  dbpr_building: "DBPR Building",
  citizens_insurance: "Citizens",
  fdot_parcels: "FDOT Parcels",
  oir_market: "OIR Market",
  cream_score: "Cream Score",
};

const SERVICE_DOT: Record<string, string> = {
  running: "bg-green-400",
  healthy: "bg-green-400",
  degraded: "bg-amber-400",
  stale: "bg-red-400",
  starting: "bg-blue-400",
};

/* ================================================================
   Main Component
   ================================================================ */

export default function OpsCenter() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Actions
  const [seeding, setSeeding] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [seedMinValue, setSeedMinValue] = useState("2000000");
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);

  // Events
  const [events, setEvents] = useState<EventItem[]>([]);
  const [eventFilter, setEventFilter] = useState<string | null>(null);
  const [eventsLive, setEventsLive] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Query
  const [showQuery, setShowQuery] = useState(false);
  const [queryText, setQueryText] = useState("");
  const [queryResult, setQueryResult] = useState<{ table: string; total: number; results: Record<string, unknown>[] } | null>(null);

  // Queue per-enricher expansion
  const [expandedEnrichers, setExpandedEnrichers] = useState<Set<string>>(new Set());
  function toggleEnricher(name: string) {
    setExpandedEnrichers((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  /* ── Data fetch ── */
  const fetchDashboard = useCallback(async () => {
    try {
      const res = await fetch("/api/proxy/admin/ops-dashboard");
      if (res.ok) {
        setData(await res.json());
        setError(null);
      } else {
        setError("Failed to load dashboard (" + res.status + ")");
      }
    } catch {
      setError("Unable to connect to backend");
    }
    setLoading(false);
  }, []);

  const fetchEvents = useCallback(async () => {
    try {
      const res = await fetch("/api/proxy/events?limit=100");
      if (res.ok) {
        const d = await res.json();
        setEvents(d.events ?? []);
      }
    } catch {}
  }, []);

  useEffect(() => {
    fetchDashboard();
    fetchEvents();
    const interval = setInterval(fetchDashboard, 30000);
    return () => clearInterval(interval);
  }, [fetchDashboard, fetchEvents]);

  /* ── Live events ── */
  function toggleLive() {
    if (eventsLive) {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      setEventsLive(false);
    } else {
      const es = new EventSource("/api/proxy/events/stream");
      es.onmessage = (e) => {
        try {
          const evt = JSON.parse(e.data);
          setEvents((prev) => [evt, ...prev].slice(0, 200));
        } catch {}
      };
      es.onerror = () => { es.close(); setEventsLive(false); };
      eventSourceRef.current = es;
      setEventsLive(true);
    }
  }

  useEffect(() => {
    return () => { eventSourceRef.current?.close(); };
  }, []);

  /* ── Actions ── */
  async function seedCounty(countyNo: string) {
    setSeeding(countyNo);
    setActionMsg(null);
    try {
      const params = seedMinValue ? `?min_value=${seedMinValue}` : "";
      const res = await fetch(`/api/proxy/admin/seed-county/${countyNo}${params}`, { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      if (d.error) setActionMsg(`Error: ${d.error}`);
      else setActionMsg(`${d.county}: ${d.created?.toLocaleString()} created from ${d.filtered?.toLocaleString()} filtered (${d.type_passed?.toLocaleString()} type-matched / ${d.total_parcels?.toLocaleString()} parcels)`);
      fetchDashboard();
    } catch (err) { setActionMsg(`Error: ${err}`); }
    setSeeding(null);
  }

  async function seedAll() {
    setSeeding("all");
    setActionMsg(null);
    try {
      const params = seedMinValue ? `?min_value=${seedMinValue}` : "";
      const res = await fetch(`/api/proxy/admin/seed-all${params}`, { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      if (d.error) setActionMsg(`Error: ${JSON.stringify(d.error)}`);
      else {
        const total = d.results?.reduce((s: number, r: { created?: number }) => s + (r.created ?? 0), 0) ?? 0;
        setActionMsg(`Seeded ${total.toLocaleString()} entities across ${d.results?.length ?? 0} counties`);
      }
      fetchDashboard();
    } catch (err) { setActionMsg(`Error: ${err}`); }
    setSeeding(null);
  }

  async function resetDatabase() {
    setResetting(true);
    setActionMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/reset", { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      setActionMsg(d.message ?? d.error ?? "Reset complete");
      fetchDashboard();
    } catch (err) { setActionMsg(`Error: ${err}`); }
    setResetting(false);
    setConfirmReset(false);
  }

  async function refreshData() {
    setActionMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/refresh-data", { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      setActionMsg(d.message ?? "Data refresh started");
    } catch (err) { setActionMsg(`Error: ${err}`); }
  }

  async function downloadSunbiz() {
    setActionMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/download-sunbiz", { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      setActionMsg(d.message ?? d.error ?? "Sunbiz download started");
    } catch (err) { setActionMsg(`Error: ${err}`); }
  }

  async function queueBackfill() {
    setActionMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/queue/backfill", { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      setActionMsg(d.error ? `Error: ${d.error}` : `Backfilled ${d.jobs_created} jobs`);
      fetchDashboard();
    } catch (err) { setActionMsg(`Error: ${err}`); }
  }

  async function queueRetryAll() {
    setActionMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/queue/retry-all", { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      setActionMsg(d.error ? `Error: ${d.error}` : `Retried ${d.retried} failed jobs`);
      fetchDashboard();
    } catch (err) { setActionMsg(`Error: ${err}`); }
  }

  async function queuePurgeRejected() {
    setActionMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/queue/purge-rejected", { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      setActionMsg(d.error ? `Error: ${d.error}` : `Purged ${d.purged} rejected jobs`);
      fetchDashboard();
    } catch (err) { setActionMsg(`Error: ${err}`); }
  }

  async function runQuery() {
    if (!queryText.trim()) return;
    try {
      const res = await fetch(`/api/proxy/admin/query?q=${encodeURIComponent(queryText)}&limit=50`);
      if (res.ok) setQueryResult(await res.json());
    } catch {}
  }

  /* ── Helpers ── */
  function fmtTime(ts: number | string) {
    const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
    return d.toLocaleTimeString();
  }

  function fmtNum(n: number | null | undefined): string {
    if (n == null) return "—";
    return n.toLocaleString();
  }

  function pipelineLink(county: string, stage?: string): string {
    const params = new URLSearchParams();
    if (county) params.set("county", county);
    if (stage) params.set("stage", stage);
    return `/?${params}`;
  }

  const filteredEvents = eventFilter
    ? events.filter((e) => e.event_type === eventFilter || e.action.includes(eventFilter))
    : events;

  /* ================================================================
     Render
     ================================================================ */

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* ── Header ── */}
      <header className="bg-gray-900 border-b border-gray-800 px-4 md:px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-blue-400 hover:text-blue-300 text-xs">&larr; Pipeline</Link>
          <h1 className="text-base font-bold tracking-tight">Ops Center</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/files" className="text-gray-500 hover:text-white text-xs">Files</Link>
          <Link href="/ref" className="text-gray-500 hover:text-white text-xs">Ref</Link>
        </div>
      </header>

      <div className="px-4 md:px-6 py-4 space-y-6">

        {/* ── Action bar ── */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 bg-gray-900 border border-gray-700 rounded px-2 py-1">
            <label className="text-[10px] text-gray-500 shrink-0">Min $</label>
            <select value={seedMinValue} onChange={(e) => setSeedMinValue(e.target.value)}
              className="bg-transparent text-white text-xs focus:outline-none">
              <option value="0">No min</option>
              <option value="1000000">$1M</option>
              <option value="2000000">$2M</option>
              <option value="3000000">$3M</option>
              <option value="5000000">$5M</option>
              <option value="10000000">$10M</option>
            </select>
          </div>
          <button onClick={seedAll} disabled={seeding !== null}
            className="bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-xs px-4 py-2 rounded font-medium">
            {seeding === "all" ? "Seeding..." : "Seed All Counties"}
          </button>
          <button onClick={refreshData}
            className="bg-emerald-700 hover:bg-emerald-600 text-white text-xs px-3 py-2 rounded font-medium">
            Refresh Data Sources
          </button>
          <button onClick={downloadSunbiz}
            className="bg-indigo-700 hover:bg-indigo-600 text-white text-xs px-3 py-2 rounded font-medium">
            Pull Sunbiz
          </button>
          {!confirmReset ? (
            <button onClick={() => setConfirmReset(true)}
              className="bg-red-900/50 hover:bg-red-900 border border-red-800 text-red-300 text-xs px-3 py-2 rounded ml-auto">
              Reset DB
            </button>
          ) : (
            <div className="flex items-center gap-1.5 bg-red-950 border border-red-700 rounded px-3 py-1.5 ml-auto">
              <span className="text-red-300 text-xs">Wipe all data?</span>
              <button onClick={resetDatabase} disabled={resetting}
                className="bg-red-600 hover:bg-red-500 text-white text-[11px] px-2.5 py-1 rounded font-medium">
                {resetting ? "..." : "Yes"}
              </button>
              <button onClick={() => setConfirmReset(false)} className="text-gray-400 text-[11px] px-2 py-1">No</button>
            </div>
          )}
        </div>

        {actionMsg && (
          <div className={`text-xs px-4 py-2 rounded ${
            actionMsg.startsWith("Error") ? "bg-red-900/50 text-red-300 border border-red-800" : "bg-green-900/50 text-green-300 border border-green-800"
          }`}>{actionMsg}</div>
        )}

        {error && <div className="text-red-400 text-xs bg-red-900/20 rounded px-4 py-2">{error}</div>}

        {loading && !data && <div className="text-gray-500 text-center py-12">Loading dashboard...</div>}

        {data && (
          <>
            {/* ════════════════════════════════════════════════════════
                STAGE TOTALS + SERVICES (compact bar)
               ════════════════════════════════════════════════════════ */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Stage totals */}
              <div className="lg:col-span-1">
                <h2 className="text-sm font-semibold text-gray-300 mb-2">Pipeline Totals</h2>
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 space-y-1.5">
                  {(["TARGET", "LEAD", "OPPORTUNITY", "CUSTOMER", "ARCHIVED"] as const).map((stage) => (
                    <div key={stage} className="flex items-center justify-between text-xs">
                      <span className={`${
                        stage === "LEAD" ? "text-cyan-400" :
                        stage === "OPPORTUNITY" ? "text-amber-400" :
                        stage === "CUSTOMER" ? "text-green-400" :
                        stage === "ARCHIVED" ? "text-red-400" : "text-gray-400"
                      }`}>{stage}</span>
                      <Link href={pipelineLink("", stage === "ARCHIVED" ? "" : stage)}
                        className="font-mono text-white hover:text-blue-300">
                        {fmtNum(data.stage_counts[stage] ?? 0)}
                      </Link>
                    </div>
                  ))}
                </div>

                {/* Seed county quick-launch (compact) */}
                <h3 className="text-[10px] uppercase tracking-wider text-gray-600 mt-3 mb-1">Seed Counties</h3>
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-2 space-y-1 max-h-[180px] overflow-y-auto">
                  {data.counties.map((c) => (
                    <div key={c.county_no} className="flex items-center justify-between text-[11px] py-0.5">
                      <span className="text-gray-400">{c.county}</span>
                      <div className="flex items-center gap-1.5">
                        {c.value_filtered != null && (
                          <span className="text-gray-600 font-mono">{fmtNum(c.value_filtered)}</span>
                        )}
                        <button onClick={() => seedCounty(c.county_no)} disabled={seeding !== null || !c.nal_ready}
                          className="bg-gray-800 hover:bg-gray-700 disabled:opacity-30 text-gray-500 text-[9px] px-1.5 py-0.5 rounded">
                          {seeding === c.county_no ? "..." : "Seed"}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Services */}
              <div className="lg:col-span-2">
                <h2 className="text-sm font-semibold text-gray-300 mb-2">Services</h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {data.services.map((svc) => (
                    <button key={svc.name}
                      onClick={() => setEventFilter(eventFilter === svc.name ? null : svc.name)}
                      className={`text-left bg-gray-900 border rounded-lg p-2 transition-colors ${
                        eventFilter === svc.name
                          ? "border-blue-600 ring-1 ring-blue-500/30"
                          : "border-gray-800 hover:border-gray-700"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-0.5">
                        <div className="flex items-center gap-1.5">
                          <span className={`w-1.5 h-1.5 rounded-full ${SERVICE_DOT[svc.status] ?? "bg-gray-600"}`} />
                          <span className="text-white text-[11px] font-medium">{svc.name}</span>
                        </div>
                        <span className="text-gray-600 text-[9px]">{svc.status}</span>
                      </div>
                      <p className="text-gray-500 text-[10px] truncate">{svc.detail}</p>
                    </button>
                  ))}
                  {data.services.length === 0 && (
                    <p className="text-gray-600 text-xs col-span-2">No services registered.</p>
                  )}
                </div>
              </div>
            </div>
          </>
        )}

        {/* ════════════════════════════════════════════════════════
            JOB QUEUE
           ════════════════════════════════════════════════════════ */}
        {data?.queue && data.queue.total_jobs > 0 && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-gray-300">
                Job Queue
                <span className="text-gray-600 font-normal ml-2">
                  ({fmtNum(data.queue.total_jobs)} total)
                </span>
              </h2>
              <div className="flex gap-2">
                <button onClick={queueBackfill}
                  className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-[10px] px-2.5 py-1.5 rounded">
                  Backfill
                </button>
                <button onClick={queueRetryAll}
                  className="bg-amber-900/50 hover:bg-amber-900 text-amber-300 text-[10px] px-2.5 py-1.5 rounded border border-amber-800">
                  Retry Failed
                </button>
                <button onClick={queuePurgeRejected}
                  className="bg-red-900/50 hover:bg-red-900 text-red-300 text-[10px] px-2.5 py-1.5 rounded border border-red-800">
                  Purge Rejected
                </button>
              </div>
            </div>

            {/* Status summary bar */}
            <div className="flex gap-3 mb-3">
              {[
                { key: "PENDING", color: "text-blue-400", bg: "bg-blue-900/30" },
                { key: "RUNNING", color: "text-cyan-400", bg: "bg-cyan-900/30" },
                { key: "SUCCESS", color: "text-green-400", bg: "bg-green-900/30" },
                { key: "FAILED", color: "text-amber-400", bg: "bg-amber-900/30" },
                { key: "REJECTED", color: "text-red-400", bg: "bg-red-900/30" },
              ].map(({ key, color, bg }) => {
                const count = data.queue?.status_counts[key] ?? 0;
                return (
                  <div key={key} className={`${bg} rounded-lg px-3 py-2 text-center flex-1`}>
                    <div className={`text-sm font-bold font-mono ${color}`}>{fmtNum(count)}</div>
                    <div className="text-[9px] text-gray-500 uppercase tracking-wider">{key}</div>
                  </div>
                );
              })}
            </div>

            {/* Per-enricher breakdown — click row to expand county detail */}
            <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-500">
                    <th className="text-left px-3 py-2 w-6"></th>
                    <th className="text-left px-2 py-2">Enricher</th>
                    <th className="text-right px-2 py-2 text-blue-500">Pending</th>
                    <th className="text-right px-2 py-2 text-cyan-500">Running</th>
                    <th className="text-right px-2 py-2 text-green-500">Success</th>
                    <th className="text-right px-2 py-2 text-amber-500">Failed</th>
                    <th className="text-right px-2 py-2 text-red-500">Rejected</th>
                    <th className="text-right px-2 py-2">Progress</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.queue.enricher_stats).map(([enricher, statuses]) => {
                    const total = Object.values(statuses).reduce((s, n) => s + n, 0);
                    const done = (statuses.SUCCESS ?? 0) + (statuses.REJECTED ?? 0);
                    const pct = total > 0 ? Math.round(done / total * 100) : 0;
                    const isOpen = expandedEnrichers.has(enricher);
                    const counties = data.queue?.enricher_by_county[enricher] ?? {};
                    const countyEntries = Object.entries(counties).sort(
                      ([a], [b]) => a.localeCompare(b)
                    );

                    return (
                      <Fragment key={enricher}>
                        <tr
                          onClick={() => toggleEnricher(enricher)}
                          className="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer"
                        >
                          <td className="px-3 py-1.5 text-gray-500 text-[10px]">
                            {isOpen ? "▼" : "▶"}
                          </td>
                          <td className="px-2 py-1.5 font-medium text-gray-300">
                            {ENRICHER_LABELS[enricher] ?? enricher}
                          </td>
                          <td className="text-right px-2 py-1.5 font-mono text-blue-400">{statuses.PENDING ?? 0}</td>
                          <td className="text-right px-2 py-1.5 font-mono text-cyan-400">{statuses.RUNNING ?? 0}</td>
                          <td className="text-right px-2 py-1.5 font-mono text-green-400">{statuses.SUCCESS ?? 0}</td>
                          <td className="text-right px-2 py-1.5 font-mono text-amber-400">{statuses.FAILED ?? 0}</td>
                          <td className="text-right px-2 py-1.5 font-mono text-red-400">{statuses.REJECTED ?? 0}</td>
                          <td className="text-right px-2 py-1.5">
                            <div className="flex items-center justify-end gap-1.5">
                              <div className="w-14 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                                <div className="h-full bg-green-500 rounded-full" style={{ width: `${pct}%` }} />
                              </div>
                              <span className="text-gray-500 text-[10px] w-7 text-right">{pct}%</span>
                            </div>
                          </td>
                        </tr>

                        {isOpen && countyEntries.length > 0 && countyEntries.map(([county, cstats]) => {
                          const ctotal = Object.values(cstats).reduce((s, n) => s + n, 0);
                          const cdone = (cstats.SUCCESS ?? 0) + (cstats.REJECTED ?? 0);
                          const cpct = ctotal > 0 ? Math.round(cdone / ctotal * 100) : 0;
                          return (
                            <tr key={`${enricher}-${county}`} className="border-b border-gray-800/30 bg-gray-950/40">
                              <td className="px-3 py-1"></td>
                              <td className="px-2 py-1 pl-6 text-gray-500 text-[11px]">
                                <Link href={pipelineLink(county)} className="hover:text-blue-300">
                                  {county}
                                </Link>
                              </td>
                              <td className="text-right px-2 py-1 font-mono text-blue-400/80">{cstats.PENDING ?? 0}</td>
                              <td className="text-right px-2 py-1 font-mono text-cyan-400/80">{cstats.RUNNING ?? 0}</td>
                              <td className="text-right px-2 py-1 font-mono text-green-400/80">{cstats.SUCCESS ?? 0}</td>
                              <td className="text-right px-2 py-1 font-mono text-amber-400/80">{cstats.FAILED ?? 0}</td>
                              <td className="text-right px-2 py-1 font-mono text-red-400/80">{cstats.REJECTED ?? 0}</td>
                              <td className="text-right px-2 py-1">
                                <div className="flex items-center justify-end gap-1.5">
                                  <div className="w-12 h-1 bg-gray-800 rounded-full overflow-hidden">
                                    <div className="h-full bg-green-500/70 rounded-full" style={{ width: `${cpct}%` }} />
                                  </div>
                                  <span className="text-gray-600 text-[9px] w-7 text-right">{cpct}%</span>
                                </div>
                              </td>
                            </tr>
                          );
                        })}

                        {isOpen && countyEntries.length === 0 && (
                          <tr className="border-b border-gray-800/30 bg-gray-950/40">
                            <td colSpan={8} className="px-2 py-2 pl-9 text-gray-600 text-[10px] italic">
                              No county data yet for this enricher.
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Recent failures */}
            {data.queue.recent_failures.length > 0 && (
              <div className="mt-3">
                <h3 className="text-xs text-gray-500 mb-1">Recent Failures</h3>
                <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-auto max-h-[20vh]">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-gray-900">
                      <tr className="border-b border-gray-800">
                        <th className="text-left px-3 py-1.5 text-gray-500">Entity</th>
                        <th className="text-left px-2 py-1.5 text-gray-500">Enricher</th>
                        <th className="text-right px-2 py-1.5 text-gray-500">#</th>
                        <th className="text-left px-3 py-1.5 text-gray-500">Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.queue.recent_failures.map((f) => (
                        <tr key={f.job_id} className="border-b border-gray-800/50">
                          <td className="px-3 py-1 text-gray-400 truncate max-w-[150px]">
                            {f.entity_name ?? `#${f.entity_id}`}
                          </td>
                          <td className="px-2 py-1 text-gray-500">
                            {ENRICHER_LABELS[f.enricher] ?? f.enricher}
                          </td>
                          <td className="text-right px-2 py-1 text-amber-500 font-mono">{f.attempts}</td>
                          <td className="px-3 py-1 text-red-400/80 truncate max-w-[300px]">{f.error ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ════════════════════════════════════════════════════════
            EVENT STREAM
           ════════════════════════════════════════════════════════ */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-gray-300">
                Events
                {eventsLive && <span className="ml-2 text-green-400 text-[10px] animate-pulse">LIVE</span>}
              </h2>
              {eventFilter && (
                <button onClick={() => setEventFilter(null)}
                  className="text-[10px] px-2 py-0.5 rounded bg-blue-900/50 text-blue-300 border border-blue-700">
                  {eventFilter} &times;
                </button>
              )}
            </div>
            <div className="flex gap-2">
              <button onClick={toggleLive}
                className={`text-xs px-3 py-1.5 rounded font-medium ${
                  eventsLive ? "bg-red-900 hover:bg-red-800 text-red-300 border border-red-700" : "bg-green-600 hover:bg-green-700 text-white"
                }`}>
                {eventsLive ? "Stop" : "Go Live"}
              </button>
              <button onClick={fetchEvents} className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-1.5 rounded">
                Refresh
              </button>
            </div>
          </div>

          {filteredEvents.length === 0 ? (
            <p className="text-gray-600 text-xs">No events{eventFilter ? ` matching "${eventFilter}"` : ""}.</p>
          ) : (
            <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-auto max-h-[40vh]">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-gray-900 z-10">
                  <tr className="border-b border-gray-800">
                    <th className="text-left px-3 py-2 text-gray-500 w-20">Time</th>
                    <th className="text-left px-3 py-2 text-gray-500 w-14">Status</th>
                    <th className="text-left px-3 py-2 text-gray-500 w-24">Source</th>
                    <th className="text-left px-3 py-2 text-gray-500">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEvents.map((evt, i) => (
                    <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/20">
                      <td className="px-3 py-1.5 text-gray-600 font-mono whitespace-nowrap">{fmtTime(evt.timestamp)}</td>
                      <td className="px-3 py-1.5">
                        <span className={`text-[10px] px-1 py-0.5 rounded ${
                          evt.status === "success" ? "bg-green-900/60 text-green-300" :
                          evt.status === "error" ? "bg-red-900/60 text-red-300" :
                          "bg-blue-900/60 text-blue-300"
                        }`}>{evt.status}</span>
                      </td>
                      <td className="px-3 py-1.5 text-gray-500">
                        <button onClick={() => setEventFilter(evt.event_type)} className="hover:text-blue-400">
                          {evt.event_type}
                        </button>
                      </td>
                      <td className="px-3 py-1.5 text-gray-400 truncate max-w-[400px]">{evt.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ════════════════════════════════════════════════════════
            QUERY (collapsible)
           ════════════════════════════════════════════════════════ */}
        <div>
          <button onClick={() => setShowQuery(!showQuery)}
            className="text-sm font-semibold text-gray-500 hover:text-gray-300 flex items-center gap-1">
            <span className={`text-[10px] transition-transform ${showQuery ? "rotate-90" : ""}`}>&#9654;</span>
            Data Explorer
          </button>
          {showQuery && (
            <div className="mt-2 bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
              <div className="flex gap-2">
                <input type="text" value={queryText} onChange={(e) => setQueryText(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && runQuery()}
                  placeholder="SQL-like query or preset: condos, citizens, hot_leads, platinum..."
                  className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-600" />
                <button onClick={runQuery}
                  className="bg-blue-600 hover:bg-blue-700 text-white text-xs px-4 py-2 rounded font-medium">
                  Run
                </button>
              </div>
              {queryResult && (
                <div className="overflow-auto max-h-[35vh]">
                  <p className="text-[10px] text-gray-600 mb-1">{queryResult.total} results from {queryResult.table}</p>
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-gray-900">
                      <tr className="border-b border-gray-800">
                        {queryResult.results.length > 0 && Object.keys(queryResult.results[0]).map((col) => (
                          <th key={col} className="text-left px-2 py-1.5 text-gray-500 whitespace-nowrap">{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {queryResult.results.map((row, i) => (
                        <tr key={i} className="border-b border-gray-800/50">
                          {Object.values(row).map((val, j) => (
                            <td key={j} className="px-2 py-1 text-gray-400 truncate max-w-[200px]">
                              {val != null ? String(val) : "—"}
                            </td>
                          ))}
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
    </div>
  );
}
