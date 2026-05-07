"use client";

import { Fragment, useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import UserMenu from "@/components/UserMenu";

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

/* ================================================================
   Constants
   ================================================================ */

// Active enricher labels — must match the chain in
// backend/agents/enrichers/pipeline.py:_load_enrichers. Deprecated
// enrichers (dor_nal, fdot_parcels, dbpr_condo) intentionally omitted
// so they don't show up as "missing" rows on the queue dashboard.
const ENRICHER_LABELS: Record<string, string> = {
  name_parse: "Name Parse",
  fema_flood: "FEMA Flood",
  property_appraiser: "Property Appraiser",
  dbpr_bulk: "DBPR Condo",
  dbpr_payments: "DBPR Payments",
  dbpr_kfi: "DBPR Financial",
  dbpr_sirs: "DBPR SIRS",
  dbpr_building: "DBPR Building",
  dbpr_noic: "DBPR NOIC",
  cam_license: "CAM License",
  sunbiz_bulk: "Sunbiz",
  citizens_insurance: "Citizens",
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
  const { isAdmin } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Actions
  const [seeding, setSeeding] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [qualifierRunning, setQualifierRunning] = useState(false);
  const [aggregatorRunning, setAggregatorRunning] = useState(false);
  const [indexBuilding, setIndexBuilding] = useState(false);
  const [indexStatus, setIndexStatus] = useState<{
    indexes: { name: string; exists: boolean }[];
    all_present: boolean;
  } | null>(null);

  // Pipeline run-state — polled while any stage is running so the user
  // sees per-county progress instead of a frozen "Seeding..." button.
  interface StageState {
    running: boolean;
    started_at: string | null;
    finished_at: string | null;
    duration_sec: number | null;
    summary: string | null;
    current: string | null;
    last_finished_at?: string | null;
    last_summary?: string | null;
    details?: { total_targets_created?: number; completed_counties?: unknown[] } | null;
  }
  interface PipelineStatus {
    stage_counts: Record<string, number>;
    stages: { seed: StageState; qualifier: StageState; aggregator: StageState };
    any_running: boolean;
  }
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null);

  const fetchPipelineStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/proxy/admin/pipeline/status");
      if (res.ok) setPipeline(await res.json().catch(() => null));
    } catch {}
  }, []);

  useEffect(() => {
    fetchPipelineStatus();
  }, [fetchPipelineStatus]);

  useEffect(() => {
    // Tight 2s poll while anything is running, slow 30s poll otherwise.
    const interval = pipeline?.any_running ? 2000 : 30000;
    const id = setInterval(fetchPipelineStatus, interval);
    return () => clearInterval(id);
  }, [pipeline?.any_running, fetchPipelineStatus]);

  // Query (moved to /admin/query page)

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

  useEffect(() => {
    fetchDashboard();
    const interval = setInterval(fetchDashboard, 30000);
    return () => clearInterval(interval);
  }, [fetchDashboard]);

  /* ── Actions ── */
  async function seedCounty(countyNo: string) {
    setSeeding(countyNo);
    setActionMsg(null);
    try {
      const res = await fetch(`/api/proxy/admin/seed-county/${countyNo}`, { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      if (d.error) setActionMsg(`Error: ${d.error}`);
      else setActionMsg(`${d.county}: ${d.created?.toLocaleString() ?? 0} TARGETs created from ${d.total_parcels?.toLocaleString() ?? 0} NAL rows`);
      fetchDashboard();
    } catch (err) { setActionMsg(`Error: ${err}`); }
    setSeeding(null);
  }

  async function seedAll() {
    setSeeding("all");
    setActionMsg(null);
    try {
      const res = await fetch(`/api/proxy/admin/seed-all`, { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      if (d.error) {
        setActionMsg(`Error: ${typeof d.error === "string" ? d.error : JSON.stringify(d.error)}`);
      } else if (d.started) {
        setActionMsg(`Seed running in background — ${d.counties_queued} counties queued. Watch the panel below for progress.`);
      } else {
        setActionMsg("Seed kicked off.");
      }
      fetchPipelineStatus();
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

  async function runQualifier() {
    setQualifierRunning(true);
    setActionMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/qualifier/run", { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      if (d.error) {
        setActionMsg(`Error: ${d.error}`);
      } else {
        setActionMsg(
          `Qualifier: ${d.promoted?.toLocaleString() ?? 0} TARGETs → LEAD ` +
          `(${d.scanned?.toLocaleString() ?? 0} scanned, ${d.duration_sec ?? 0}s)`
        );
      }
      fetchDashboard();
      fetchPipelineStatus();
    } catch (err) { setActionMsg(`Error: ${err}`); }
    setQualifierRunning(false);
  }

  async function runAggregator() {
    setAggregatorRunning(true);
    setActionMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/aggregator/run", { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      if (d.error) {
        setActionMsg(`Error: ${d.error}`);
      } else {
        setActionMsg(
          `Aggregator: ${d.masters_promoted?.toLocaleString() ?? 0} masters, ` +
          `${d.siblings_linked?.toLocaleString() ?? 0} siblings linked, ` +
          `${d.singletons?.toLocaleString() ?? 0} singletons (${d.duration_sec ?? 0}s)`
        );
      }
      fetchDashboard();
      fetchPipelineStatus();
    } catch (err) { setActionMsg(`Error: ${err}`); }
    setAggregatorRunning(false);
  }

  const fetchIndexStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/proxy/admin/indexes/status");
      const d = await res.json().catch(() => null);
      if (d?.indexes) setIndexStatus(d);
    } catch {}
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    fetchIndexStatus();
    // Re-poll while a build is in progress so the pill updates as
    // CONCURRENTLY indexes finish one by one.
    const id = indexBuilding ? setInterval(fetchIndexStatus, 3000) : null;
    return () => { if (id) clearInterval(id); };
  }, [isAdmin, fetchIndexStatus, indexBuilding]);

  async function buildIndexes() {
    setIndexBuilding(true);
    setActionMsg(null);
    try {
      const res = await fetch("/api/proxy/admin/indexes/build", { method: "POST" });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      if (d.error) {
        setActionMsg(`Error: ${d.error}`);
        setIndexBuilding(false);
      } else {
        setActionMsg(
          `Building ${d.indexes?.length ?? 0} JSONB indexes in the background — ` +
          `safe to keep using the app. Pill below shows progress.`
        );
        // Stop the polling spinner once all indexes are present.
        const watch = setInterval(async () => {
          const r = await fetch("/api/proxy/admin/indexes/status");
          const s = await r.json().catch(() => null);
          if (s) {
            setIndexStatus(s);
            if (s.all_present) {
              clearInterval(watch);
              setIndexBuilding(false);
              setActionMsg("All JSONB indexes built. Validation and lead-list queries should now be fast.");
            }
          }
        }, 3000);
      }
    } catch (err) {
      setActionMsg(`Error: ${err}`);
      setIndexBuilding(false);
    }
  }

  /* ── Helpers ── */
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
          <Link href="/help" className="text-blue-400 hover:text-blue-300 text-xs font-medium">? Help</Link>
          <UserMenu />
        </div>
      </header>

      <div className="px-4 md:px-6 py-4 space-y-6">

        {/* ── Pipeline run panel (admin only) ──
            Three deterministic gated transitions stacked vertically.
            Each row has live status + last-run summary. Downstream
            buttons are disabled while upstream is running, and
            soft-warn when there's nothing to consume. */}
        {isAdmin && (
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-300">Pipeline Run</h2>
              <div className="flex items-center gap-2">
                {indexStatus && (
                  <button
                    onClick={buildIndexes}
                    disabled={indexBuilding || indexStatus.all_present}
                    title={
                      indexStatus.all_present
                        ? "All JSONB lookup indexes are present."
                        : "Create the JSONB lookup indexes the matcher and lead list need. Runs CONCURRENTLY — safe while aggregator is running."
                    }
                    className={`text-[11px] px-3 py-1 rounded border ${
                      indexStatus.all_present
                        ? "bg-green-900/30 text-green-400 border-green-900 cursor-default"
                        : indexBuilding
                          ? "bg-blue-900/40 text-blue-300 border-blue-800"
                          : "bg-blue-900/40 hover:bg-blue-900 text-blue-300 border-blue-800"
                    }`}
                  >
                    {indexStatus.all_present
                      ? `Indexes ✓ (${indexStatus.indexes.length}/${indexStatus.indexes.length})`
                      : indexBuilding
                        ? `Building… ${indexStatus.indexes.filter(i => i.exists).length}/${indexStatus.indexes.length}`
                        : `Build Indexes (${indexStatus.indexes.filter(i => i.exists).length}/${indexStatus.indexes.length})`}
                  </button>
                )}
                {!confirmReset ? (
                  <button onClick={() => setConfirmReset(true)}
                    className="bg-red-900/50 hover:bg-red-900 border border-red-800 text-red-300 text-[11px] px-3 py-1 rounded">
                    Reset DB
                  </button>
                ) : (
                <div className="flex items-center gap-1.5 bg-red-950 border border-red-700 rounded px-3 py-1">
                  <span className="text-red-300 text-[11px]">Wipe all data?</span>
                  <button onClick={resetDatabase} disabled={resetting}
                    className="bg-red-600 hover:bg-red-500 text-white text-[11px] px-2.5 py-0.5 rounded font-medium">
                    {resetting ? "..." : "Yes"}
                  </button>
                  <button onClick={() => setConfirmReset(false)} className="text-gray-400 text-[11px] px-2">No</button>
                </div>
              )}
              </div>
            </div>

            <PipelineStageRow
              step={1}
              label="Seed"
              transition="NAL → TARGET"
              accent="green"
              state={pipeline?.stages?.seed}
              busy={seeding !== null || pipeline?.stages?.seed?.running}
              upstreamBusy={false}
              onRun={seedAll}
              produced={pipeline?.stage_counts?.TARGET ?? 0}
              producedLabel="TARGETs"
            />

            <PipelineStageRow
              step={2}
              label="Qualify"
              transition="TARGET → LEAD"
              accent="cyan"
              state={pipeline?.stages?.qualifier}
              busy={qualifierRunning || pipeline?.stages?.qualifier?.running}
              upstreamBusy={!!pipeline?.stages?.seed?.running}
              upstreamWarning={
                (pipeline?.stage_counts?.TARGET ?? 0) === 0
                  ? "No TARGETs yet — seed first"
                  : null
              }
              onRun={runQualifier}
              produced={pipeline?.stage_counts?.LEAD ?? 0}
              producedLabel="LEADs"
            />

            <PipelineStageRow
              step={3}
              label="Aggregate"
              transition="LEAD → VETTED"
              accent="teal"
              state={pipeline?.stages?.aggregator}
              busy={aggregatorRunning || pipeline?.stages?.aggregator?.running}
              upstreamBusy={
                !!pipeline?.stages?.seed?.running ||
                !!pipeline?.stages?.qualifier?.running
              }
              upstreamWarning={
                (pipeline?.stage_counts?.LEAD ?? 0) === 0
                  ? "No LEADs yet — qualify first"
                  : null
              }
              onRun={runAggregator}
              produced={pipeline?.stage_counts?.VETTED ?? 0}
              producedLabel="VETTED masters"
            />

            {actionMsg && (
              <div className={`text-[11px] px-3 py-1.5 rounded ${
                actionMsg.startsWith("Error")
                  ? "bg-red-900/50 text-red-300 border border-red-800"
                  : "bg-green-900/30 text-green-300 border border-green-900"
              }`}>{actionMsg}</div>
            )}
          </div>
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
                  {([
                    "TARGET", "LEAD", "VETTED", "ANALYZED", "VALIDATED",
                    "OPPORTUNITY", "CUSTOMER", "ARCHIVED",
                  ] as const).map((stage) => (
                    <div key={stage} className="flex items-center justify-between text-xs">
                      <span className={`${
                        stage === "LEAD"        ? "text-cyan-400"   :
                        stage === "VETTED"      ? "text-teal-400"   :
                        stage === "ANALYZED"    ? "text-indigo-400" :
                        stage === "VALIDATED"   ? "text-purple-400" :
                        stage === "OPPORTUNITY" ? "text-amber-400"  :
                        stage === "CUSTOMER"    ? "text-green-400"  :
                        stage === "ARCHIVED"    ? "text-red-400"    :
                        "text-gray-400"
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
                    <div key={svc.name}
                      className="bg-gray-900 border border-gray-800 rounded-lg p-2"
                    >
                      <div className="flex items-center justify-between mb-0.5">
                        <div className="flex items-center gap-1.5">
                          <span className={`w-1.5 h-1.5 rounded-full ${SERVICE_DOT[svc.status] ?? "bg-gray-600"}`} />
                          <span className="text-white text-[11px] font-medium">{svc.name}</span>
                        </div>
                        <span className="text-gray-600 text-[9px]">{svc.status}</span>
                      </div>
                      <p className="text-gray-500 text-[10px] truncate">{svc.detail}</p>
                    </div>
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

        {/* Event stream lives on the Validation page now. */}
        <div className="flex items-center gap-2">
          <Link href="/validation"
            className="text-sm font-semibold text-blue-400 hover:text-blue-300 flex items-center gap-1">
            &#9654; Event Stream &amp; Validation
          </Link>
          <span className="text-xs text-gray-600">
            Live events + bulk property compare
          </span>
        </div>

        {/* Query tool link (admin only — full page at /admin/query) */}
        {isAdmin && (
          <div className="flex items-center gap-2">
            <Link href="/admin/query"
              className="text-sm font-semibold text-blue-400 hover:text-blue-300 flex items-center gap-1">
              &#9654; SQL Query Tool
            </Link>
            <Link href={`${typeof window !== "undefined" ? window.location.origin.replace(/:\d+$/, ":8000") : ""}/api/admin/dataset-diagnostics`}
              className="text-xs text-gray-500 hover:text-gray-300"
              target="_blank">
              Dataset Diagnostics (JSON)
            </Link>
          </div>
        )}

      </div>
    </div>
  );
}


/* ────────────────────────────────────────────────────────────────────
 * PipelineStageRow
 *
 * One row of the admin Pipeline Run panel. Owns its own ticking
 * "elapsed" counter when the stage is running so users see live
 * proof that something is happening, plus shows the most recent
 * progress message ("Seeding (12/35) Pinellas...") and the last-
 * completed summary.
 * ──────────────────────────────────────────────────────────────── */

interface StageStateLite {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  duration_sec: number | null;
  summary: string | null;
  current: string | null;
  last_finished_at?: string | null;
  last_summary?: string | null;
  details?: { total_targets_created?: number; completed_counties?: unknown[] } | null;
}

const ACCENT_BTN: Record<string, string> = {
  green: "bg-green-600 hover:bg-green-700",
  cyan:  "bg-cyan-700  hover:bg-cyan-600",
  teal:  "bg-teal-700  hover:bg-teal-600",
};

const ACCENT_DOT: Record<string, string> = {
  green: "bg-green-500",
  cyan:  "bg-cyan-500",
  teal:  "bg-teal-500",
};

function fmtAge(iso: string | null | undefined): string {
  if (!iso) return "never";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "never";
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
}

function PipelineStageRow({
  step, label, transition, accent, state, busy, upstreamBusy, upstreamWarning,
  onRun, produced, producedLabel,
}: {
  step: number;
  label: string;
  transition: string;
  accent: "green" | "cyan" | "teal";
  state: StageStateLite | undefined;
  busy: boolean | undefined;
  upstreamBusy: boolean;
  upstreamWarning?: string | null;
  onRun: () => void;
  produced: number;
  producedLabel: string;
}) {
  const isRunning = state?.running || busy;
  const blockedReason = upstreamBusy
    ? "Waiting for upstream stage"
    : upstreamWarning ?? null;
  const disabled = !!busy || upstreamBusy;

  // Tick a clock so the elapsed time updates without polling overhead.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [isRunning]);

  const elapsedSec = state?.started_at && isRunning
    ? Math.max(0, Math.round((now - new Date(state.started_at).getTime()) / 1000))
    : null;

  return (
    <div className={`border rounded p-3 ${
      isRunning ? "border-blue-700 bg-blue-950/20" : "border-gray-800 bg-gray-950/40"
    }`}>
      <div className="flex items-start gap-3">
        <div className="shrink-0 w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-[10px] text-gray-400 font-bold">
          {step}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-white">{label}</span>
            <span className="text-[10px] text-gray-500">{transition}</span>

            {isRunning ? (
              <span className="inline-flex items-center gap-1 text-[10px] text-blue-300 font-medium">
                <span className={`w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse`} />
                running {elapsedSec !== null ? `${elapsedSec}s` : ""}
              </span>
            ) : state?.last_finished_at || state?.finished_at ? (
              <span className="inline-flex items-center gap-1 text-[10px] text-gray-500">
                <span className={`w-1.5 h-1.5 rounded-full ${ACCENT_DOT[accent]}`} />
                last run {fmtAge(state.finished_at ?? state.last_finished_at)}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-[10px] text-gray-600">
                <span className="w-1.5 h-1.5 rounded-full bg-gray-700" />
                never run
              </span>
            )}

            <span className="ml-auto text-[10px] text-gray-500">
              {produced.toLocaleString()} {producedLabel}
            </span>
          </div>

          <div className="mt-1.5">
            {isRunning && state?.current && (
              <p className="text-[11px] text-blue-200 truncate">{state.current}</p>
            )}
            {!isRunning && (state?.summary || state?.last_summary) && (
              <p className="text-[11px] text-gray-400 truncate">
                {state.summary ?? state.last_summary}
              </p>
            )}
            {!isRunning && blockedReason && (
              <p className="text-[11px] text-amber-400 mt-0.5">{blockedReason}</p>
            )}
          </div>

          {/* Live per-county tally — only the seed stage emits this */}
          {isRunning && state?.details?.total_targets_created != null && (
            <p className="text-[10px] text-blue-300 mt-1 font-mono">
              {Number(state.details.total_targets_created).toLocaleString()} TARGETs created so far across{" "}
              {(state.details.completed_counties as unknown[] | undefined)?.length ?? 0} counties
            </p>
          )}
        </div>

        <button
          onClick={onRun}
          disabled={disabled}
          title={disabled ? (blockedReason ?? "Already running") : `Run ${label}`}
          className={`shrink-0 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs px-4 py-2 rounded font-medium ${ACCENT_BTN[accent]}`}
        >
          {isRunning ? "Running..." : "Run"}
        </button>
      </div>
    </div>
  );
}
