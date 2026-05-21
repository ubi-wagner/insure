"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import UserMenu from "@/components/UserMenu";
import EntityDetailModal from "@/components/EntityDetailModal";

const MAX_MODALS = 10;

type TabName = "compare" | "events";

interface ParsedItem {
  name: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  zip: string | null;
  year_built: number | null;
  stories: number | null;
  units: number | null;
  tiv: number | null;
  iso_class: number | null;
  raw: string | null;
}

type FieldStatus = "match" | "conflict" | "no_input" | "no_data";

interface FieldDiff {
  input: number | string | null;
  db: number | string | null;
  db_raw?: string | null;
  status: FieldStatus;
}

interface MatchEntity {
  id: number;
  name: string;
  address: string | null;
  county: string | null;
  pipeline_stage: string;
  latitude: number | null;
  longitude: number | null;
  heat_score: string | null;
  cream_score: number | null;
  cream_tier: string | null;
  is_aggregation_master?: boolean;
  is_condo_unit_parcel?: boolean;
  sibling_count?: number;
  tiv_estimate_master?: number | null;
  num_units_master?: number | null;
}

type OverallStatus = "match" | "conflict" | "missing" | "no_data";

interface MatchDebug {
  parsed_canon?: string | null;
  parsed_number?: string | null;
  parsed_zip?: string | null;
  parsed_city?: string | null;
  match_phase?: string | null;
  candidates_by_zip_number?: number;
  candidates_by_city_number?: number;
  candidates_by_canon?: number;
  nearby_canons?: string[];
}

interface CompareResult {
  input: ParsedItem;
  match: MatchEntity | null;
  fields: Record<string, FieldDiff>;
  status: OverallStatus;
  match_score?: number;
  match_debug?: MatchDebug;
}

interface CompareResponse {
  results: CompareResult[];
  counts: Record<string, number>;
  total: number;
}

interface SavedRunMeta {
  id: string;
  name: string;
  created_at: string;
  input_count: number;
  summary: { match?: number; conflict?: number; missing?: number; no_data?: number; total?: number };
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

function fmtTime(ts: number | string) {
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  return d.toLocaleTimeString();
}

const SAMPLE_TEXT = `Harborview Grande 530 Gulfview Blvd, Clearwater, FL 33767, ISO 5, 2006 built, TIV $23,600,000, 55 units, 8 stories
Echo Brickell 1451 Brickell Ave, Miami FL 33131, ISO 6, 2017 built, TIV $101,700,000, 56 stories, 171 units
Saltaire 301 1st Street S, St. Petersburg FL 33701, ISO 6, TIV $180,000,000, built 2023, 34 stories, 192 units`;

export default function ValidationPage() {
  const [tab, setTab] = useState<TabName>("compare");

  // Modal stack — clicking a matched entity (or one of its linked
  // parcels) opens an EntityDetailModal here instead of navigating
  // away. Mirrors the dashboard's max-10 stack so closing a sibling
  // falls back to the master, not "the previous browser page".
  const [openModals, setOpenModals] = useState<number[]>([]);
  const [activeModal, setActiveModal] = useState<number | null>(null);

  const openEntityModal = useCallback((id: number) => {
    setOpenModals((prev) => {
      if (prev.includes(id)) {
        setActiveModal(id);
        return prev;
      }
      let next = [...prev, id];
      if (next.length > MAX_MODALS) next = next.slice(1);
      setActiveModal(id);
      return next;
    });
  }, []);

  const closeEntityModal = useCallback((id: number) => {
    setOpenModals((prev) => {
      const next = prev.filter((m) => m !== id);
      setActiveModal((cur) => (cur === id ? (next[next.length - 1] ?? null) : cur));
      return next;
    });
  }, []);

  // Bulk compare state
  const [pasteText, setPasteText] = useState<string>("");
  const [parsed, setParsed] = useState<ParsedItem[] | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [parsing, setParsing] = useState(false);
  const [compareResults, setCompareResults] = useState<CompareResponse | null>(null);
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);

  // Saved-runs library
  const [savedRuns, setSavedRuns] = useState<SavedRunMeta[]>([]);
  const [savedExpanded, setSavedExpanded] = useState(false);
  const [savedSelected, setSavedSelected] = useState<Set<string>>(new Set());
  const [saveName, setSaveName] = useState<string>("");
  const [savingRun, setSavingRun] = useState(false);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  const fetchSavedRuns = useCallback(async () => {
    try {
      const res = await fetch("/api/proxy/validation/saved");
      if (!res.ok) return;
      const d = await res.json().catch(() => ({ runs: [] }));
      setSavedRuns(d.runs ?? []);
    } catch {}
  }, []);

  useEffect(() => { fetchSavedRuns(); }, [fetchSavedRuns]);

  async function saveCurrentRun() {
    if (!parsed || parsed.length === 0) return;
    setSavingRun(true);
    setSavedMsg(null);
    try {
      const res = await fetch("/api/proxy/validation/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: saveName.trim() || null,
          input_text: pasteText,
          items: parsed,
          summary: compareResults
            ? { ...compareResults.counts, total: compareResults.total }
            : null,
        }),
      });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      if (!res.ok || d.error) {
        setSavedMsg(`Error: ${d.error ?? res.statusText}`);
      } else {
        setSavedMsg(`Saved as "${d.name}"`);
        setSaveName("");
        fetchSavedRuns();
      }
    } catch (err) {
      setSavedMsg(`Error: ${err}`);
    }
    setSavingRun(false);
  }

  async function loadSelectedRuns() {
    if (savedSelected.size === 0) return;
    setSavedMsg(null);
    try {
      const res = await fetch("/api/proxy/validation/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: Array.from(savedSelected) }),
      });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      if (!res.ok || d.error) {
        setSavedMsg(`Error: ${d.error ?? res.statusText}`);
        return;
      }
      // Drop merged items into the textarea (so the user can edit
      // before parsing) AND auto-parse so they can hit Compare
      // immediately on a small/big test.
      const txt: string = d.raw_text ?? "";
      setPasteText(txt);
      setParsed(d.items ?? []);
      setCompareResults(null);
      setSavedSelected(new Set());
      setSavedMsg(`Loaded ${d.item_count} items from ${d.loaded_ids?.length ?? 0} sets`);
    } catch (err) {
      setSavedMsg(`Error: ${err}`);
    }
  }

  async function deleteSavedRun(id: string) {
    if (!confirm("Delete this saved run?")) return;
    try {
      const res = await fetch(`/api/proxy/validation/saved/${id}`, { method: "DELETE" });
      if (res.ok) {
        setSavedRuns((prev) => prev.filter((r) => r.id !== id));
        setSavedSelected((prev) => {
          const next = new Set(prev); next.delete(id); return next;
        });
      }
    } catch {}
  }

  async function handleCompare(items: ParsedItem[]) {
    setComparing(true);
    setCompareError(null);
    try {
      const res = await fetch("/api/proxy/validation/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      if (!res.ok || d.error) {
        setCompareError(d.error ?? `Compare failed (${res.status})`);
        setCompareResults(null);
      } else {
        setCompareResults(d);
      }
    } catch (err) {
      setCompareError(`Network error: ${err}`);
      setCompareResults(null);
    }
    setComparing(false);
  }

  async function handleParse() {
    setParsing(true);
    setParseError(null);
    setCompareResults(null);
    try {
      const res = await fetch("/api/proxy/validation/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: pasteText }),
      });
      const d = await res.json().catch(() => ({ error: res.statusText }));
      if (!res.ok || d.error) {
        setParseError(d.error ?? `Parse failed (${res.status})`);
        setParsed(null);
      } else {
        setParsed(d.items ?? []);
      }
    } catch (err) {
      setParseError(`Network error: ${err}`);
      setParsed(null);
    }
    setParsing(false);
  }

  function fmtMoney(n: number | null): string {
    if (n == null) return "—";
    if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
    return `$${n.toLocaleString()}`;
  }

  const [events, setEvents] = useState<EventItem[]>([]);
  const [eventFilter, setEventFilter] = useState<string | null>(null);
  const [eventsLive, setEventsLive] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const fetchEvents = useCallback(async () => {
    try {
      const res = await fetch("/api/proxy/events?limit=200");
      if (res.ok) {
        const d = await res.json().catch(() => ({ events: [] }));
        setEvents(d.events ?? []);
      }
    } catch {}
  }, []);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

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
          setEvents((prev) => [evt, ...prev].slice(0, 500));
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

  const filteredEvents = eventFilter
    ? events.filter((e) => e.event_type === eventFilter || e.action.includes(eventFilter))
    : events;

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="bg-gray-900 border-b border-gray-800 px-4 md:px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-blue-400 hover:text-blue-300 text-xs">&larr; Pipeline</Link>
          <h1 className="text-base font-bold tracking-tight">Validation</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/ops" className="text-gray-500 hover:text-white text-xs">Ops</Link>
          <Link href="/files" className="text-gray-500 hover:text-white text-xs">Files</Link>
          <Link href="/ref" className="text-gray-500 hover:text-white text-xs">Ref</Link>
          <UserMenu />
        </div>
      </header>

      <div className="px-4 md:px-6 py-4">
        <div className="flex items-center gap-1 border-b border-gray-800 mb-4">
          <TabButton active={tab === "compare"} onClick={() => setTab("compare")}>
            Bulk Compare
          </TabButton>
          <TabButton active={tab === "events"} onClick={() => setTab("events")}>
            Events
          </TabButton>
        </div>

        {tab === "compare" && (
          <div className="space-y-4">
            {/* Saved Test Sets — small/big test fixture library. Each entry
                is the items+summary from a previous parse+compare run.
                Multi-select + Load merges them into the textarea so a
                small subset can be promoted into a bigger regression run. */}
            <div className="bg-gray-900/60 border border-gray-800 rounded-lg">
              <button
                onClick={() => setSavedExpanded((x) => !x)}
                className="w-full flex items-center justify-between px-3 py-2 text-xs text-gray-300 hover:bg-gray-900"
              >
                <span className="flex items-center gap-2">
                  <span className="text-gray-500">{savedExpanded ? "▼" : "▶"}</span>
                  <span className="font-semibold">Saved Test Sets</span>
                  <span className="text-gray-500">({savedRuns.length})</span>
                  {savedSelected.size > 0 && (
                    <span className="text-blue-400">· {savedSelected.size} selected</span>
                  )}
                </span>
                {savedExpanded && savedSelected.size > 0 && (
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => { e.stopPropagation(); loadSelectedRuns(); }}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); loadSelectedRuns(); } }}
                    className="bg-blue-600 hover:bg-blue-500 text-white text-[11px] px-3 py-1 rounded font-medium cursor-pointer"
                  >
                    Load {savedSelected.size} into textarea
                  </span>
                )}
              </button>
              {savedExpanded && (
                <div className="border-t border-gray-800 px-3 py-2">
                  {savedRuns.length === 0 ? (
                    <p className="text-[11px] text-gray-500">
                      No saved sets yet. Run a parse + compare, then click "Save run" below.
                    </p>
                  ) : (
                    <ul className="space-y-1">
                      {savedRuns.map((r) => {
                        const summary = r.summary || {};
                        const checked = savedSelected.has(r.id);
                        return (
                          <li
                            key={r.id}
                            className={`flex items-center gap-2 text-[11px] px-2 py-1 rounded ${
                              checked ? "bg-blue-950/50 border border-blue-900" : "hover:bg-gray-900"
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(e) => {
                                setSavedSelected((prev) => {
                                  const next = new Set(prev);
                                  if (e.target.checked) next.add(r.id); else next.delete(r.id);
                                  return next;
                                });
                              }}
                              className="cursor-pointer"
                            />
                            <span className="flex-1 truncate text-gray-200" title={r.name}>{r.name}</span>
                            <span className="text-gray-500 font-mono shrink-0">
                              {r.input_count} item{r.input_count === 1 ? "" : "s"}
                            </span>
                            {summary.total != null && (
                              <span className="text-[10px] font-mono shrink-0">
                                <span className="text-green-400">{summary.match ?? 0}m</span>
                                <span className="text-gray-700">/</span>
                                <span className="text-yellow-400">{summary.conflict ?? 0}c</span>
                                <span className="text-gray-700">/</span>
                                <span className="text-red-400">{summary.missing ?? 0}x</span>
                              </span>
                            )}
                            <button
                              onClick={() => deleteSavedRun(r.id)}
                              className="text-gray-600 hover:text-red-400 text-[10px] shrink-0"
                              title="Delete"
                            >
                              ✕
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                  {savedMsg && (
                    <p className={`text-[11px] mt-2 ${savedMsg.startsWith("Error") ? "text-red-400" : "text-green-400"}`}>
                      {savedMsg}
                    </p>
                  )}
                </div>
              )}
            </div>

            <div>
              <h2 className="text-sm font-semibold text-gray-300 mb-1">Paste a property list</h2>
              <p className="text-[11px] text-gray-500 mb-2">
                One property per line. Free-form is fine — the parser pulls
                name, address, ZIP, year built, ISO class, stories, units,
                and TIV. The next build wires these to the matcher.
              </p>
              <textarea
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
                placeholder={SAMPLE_TEXT}
                rows={10}
                className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-blue-700 placeholder:text-gray-700"
              />
              <div className="flex items-center gap-2 mt-2">
                <button onClick={handleParse} disabled={parsing || !pasteText.trim()}
                  className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-xs px-4 py-1.5 rounded font-medium">
                  {parsing ? "Parsing..." : "Parse"}
                </button>
                <button onClick={() => setPasteText(SAMPLE_TEXT)}
                  className="text-xs text-gray-500 hover:text-gray-300 px-2 py-1.5">
                  Load sample
                </button>
                {pasteText && (
                  <button onClick={() => { setPasteText(""); setParsed(null); setParseError(null); }}
                    className="text-xs text-gray-600 hover:text-gray-400 px-2 py-1.5">
                    Clear
                  </button>
                )}
              </div>
              {parseError && (
                <p className="text-red-400 text-xs mt-2">{parseError}</p>
              )}
            </div>

            {parsed && parsed.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-gray-400 mb-2">
                  Parsed {parsed.length} {parsed.length === 1 ? "property" : "properties"}
                </h3>
                <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-gray-800 text-gray-500">
                        <th className="text-left px-2 py-2">Name</th>
                        <th className="text-left px-2 py-2">Address</th>
                        <th className="text-left px-2 py-2">City</th>
                        <th className="text-left px-2 py-2">ZIP</th>
                        <th className="text-right px-2 py-2">Year</th>
                        <th className="text-right px-2 py-2">ISO</th>
                        <th className="text-right px-2 py-2">Stories</th>
                        <th className="text-right px-2 py-2">Units</th>
                        <th className="text-right px-2 py-2">TIV</th>
                      </tr>
                    </thead>
                    <tbody>
                      {parsed.map((p, i) => (
                        <tr key={i} className="border-b border-gray-800/50">
                          <td className="px-2 py-1 text-white">{p.name ?? "—"}</td>
                          <td className="px-2 py-1 text-gray-300">{p.address ?? "—"}</td>
                          <td className="px-2 py-1 text-gray-400">{p.city ?? "—"}</td>
                          <td className="px-2 py-1 text-gray-500 font-mono">{p.zip ?? "—"}</td>
                          <td className="px-2 py-1 text-right font-mono text-gray-300">{p.year_built ?? "—"}</td>
                          <td className="px-2 py-1 text-right font-mono text-gray-300">{p.iso_class ?? "—"}</td>
                          <td className="px-2 py-1 text-right font-mono text-gray-300">{p.stories ?? "—"}</td>
                          <td className="px-2 py-1 text-right font-mono text-gray-300">{p.units ?? "—"}</td>
                          <td className="px-2 py-1 text-right font-mono text-gray-300">{fmtMoney(p.tiv)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="flex items-center gap-2 mt-2">
                  <button onClick={() => handleCompare(parsed)} disabled={comparing}
                    className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-xs px-4 py-1.5 rounded font-medium">
                    {comparing ? "Comparing..." : `Compare ${parsed.length} against our DB`}
                  </button>
                  {compareError && (
                    <span className="text-red-400 text-xs">{compareError}</span>
                  )}
                </div>
              </div>
            )}

            {parsed && parsed.length === 0 && (
              <p className="text-amber-400 text-xs">
                No properties parsed from input.
              </p>
            )}

            {compareResults && (
              <>
                <div className="bg-gray-900/60 border border-gray-800 rounded-lg p-3 flex items-center gap-2 flex-wrap">
                  <span className="text-[11px] text-gray-400 mr-1">
                    Save this run as a reusable test set:
                  </span>
                  <input
                    type="text"
                    value={saveName}
                    onChange={(e) => setSaveName(e.target.value)}
                    placeholder={`e.g. "Pinellas condos · ${parsed?.length ?? 0} props"`}
                    className="flex-1 min-w-[180px] bg-gray-950 border border-gray-800 rounded px-2 py-1 text-[11px] text-gray-200 focus:outline-none focus:border-blue-700 placeholder:text-gray-700"
                  />
                  <button
                    onClick={saveCurrentRun}
                    disabled={savingRun || !parsed || parsed.length === 0}
                    className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 text-white text-[11px] px-3 py-1 rounded font-medium"
                  >
                    {savingRun ? "Saving..." : "Save run"}
                  </button>
                  {savedMsg && (
                    <span className={`text-[11px] ${savedMsg.startsWith("Error") ? "text-red-400" : "text-green-400"}`}>
                      {savedMsg}
                    </span>
                  )}
                </div>
                <CompareResultsView results={compareResults} onOpenEntity={openEntityModal} />
              </>
            )}
          </div>
        )}

        {tab === "events" && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-gray-300">
                  Event Stream
                  {eventsLive && <span className="ml-2 text-green-400 text-[10px] animate-pulse">LIVE</span>}
                </h2>
                {eventFilter && (
                  <button onClick={() => setEventFilter(null)}
                    className="text-[10px] px-2 py-0.5 rounded bg-blue-900/50 text-blue-300 border border-blue-700">
                    {eventFilter} &times;
                  </button>
                )}
                <span className="text-gray-600 text-[10px]">
                  showing {filteredEvents.length} / {events.length}
                </span>
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
              <p className="text-gray-600 text-xs">
                No events{eventFilter ? ` matching "${eventFilter}"` : ""}.
              </p>
            ) : (
              <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-auto max-h-[70vh]">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-900 z-10">
                    <tr className="border-b border-gray-800">
                      <th className="text-left px-3 py-2 text-gray-500 w-20">Time</th>
                      <th className="text-left px-3 py-2 text-gray-500 w-14">Status</th>
                      <th className="text-left px-3 py-2 text-gray-500 w-24">Source</th>
                      <th className="text-left px-3 py-2 text-gray-500 w-32">Action</th>
                      <th className="text-left px-3 py-2 text-gray-500">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredEvents.map((evt, i) => {
                      const entityId = evt.metadata?.entity_id as number | undefined;
                      return (
                        <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/20">
                          <td className="px-3 py-1.5 text-gray-600 font-mono whitespace-nowrap">
                            {fmtTime(evt.timestamp)}
                          </td>
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
                          <td className="px-3 py-1.5 text-gray-500 text-[11px] truncate max-w-[200px]">
                            {evt.action}
                          </td>
                          <td className="px-3 py-1.5 text-gray-400 text-[11px]">
                            <span className="truncate max-w-[400px] inline-block align-middle">{evt.detail}</span>
                            {entityId && (
                              <Link
                                href={`/lead/${entityId}`}
                                className="ml-2 text-blue-400 hover:underline text-[10px] shrink-0"
                                target="_blank"
                              >
                                #{String(entityId)}
                              </Link>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Modal stack — drilling into a matched entity or a linked
          parcel opens a frame here instead of a new browser tab.
          Closing falls back to the previously active frame. */}
      {openModals.length > 0 && (
        <div
          className="fixed inset-0 bg-black/40 z-40 transition-opacity duration-300"
          onClick={() => { if (activeModal != null) closeEntityModal(activeModal); }}
        />
      )}
      {openModals.map((id, idx) => (
        <EntityDetailModal
          key={id}
          entityId={id}
          isActive={activeModal === id}
          stackIndex={idx}
          totalOpen={openModals.length}
          onActivate={() => setActiveModal(id)}
          onClose={() => closeEntityModal(id)}
          onOpenEntity={openEntityModal}
        />
      ))}
      {openModals.length > 0 && (
        <div className="fixed bottom-0 left-0 right-0 bg-gray-900/95 backdrop-blur-sm border-t border-gray-800 flex items-center px-2 py-1.5 z-[60] gap-1 overflow-x-auto">
          {openModals.map((id) => (
            <button
              key={id}
              onClick={() => setActiveModal(id)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] shrink-0 max-w-[180px] transition-colors ${
                activeModal === id
                  ? "bg-blue-900/60 text-blue-300 border border-blue-600 shadow-sm shadow-blue-900/30"
                  : "bg-gray-800/80 text-gray-500 border border-gray-700 hover:text-gray-300 hover:border-gray-600"
              }`}
            >
              <span className="truncate">#{id}</span>
              <span
                onClick={(e) => { e.stopPropagation(); closeEntityModal(id); }}
                className="text-gray-600 hover:text-red-400 ml-0.5 text-sm leading-none"
              >&times;</span>
            </button>
          ))}
          {openModals.length > 1 && (
            <button
              onClick={() => { setOpenModals([]); setActiveModal(null); }}
              className="text-gray-600 hover:text-red-400 text-[10px] px-2 py-1 shrink-0 ml-auto"
            >
              Close all
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
        active
          ? "border-blue-500 text-blue-400"
          : "border-transparent text-gray-500 hover:text-gray-300"
      }`}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Compare results                                                    */
/* ------------------------------------------------------------------ */

const FIELD_LABELS: Record<string, string> = {
  year_built: "Year built",
  stories: "Stories",
  units: "Units",
  tiv: "TIV",
  iso_class: "ISO class",
};

const STATUS_BORDER: Record<OverallStatus, string> = {
  match: "border-green-700 bg-green-950/30",
  // "No data" still means we found the entity — treat as a softer green
  no_data: "border-green-800/60 bg-green-950/10",
  conflict: "border-yellow-600 bg-yellow-950/30",
  missing: "border-red-700 bg-red-950/30",
};

const STATUS_LABEL: Record<OverallStatus, string> = {
  match: "All match",
  no_data: "Found, no comparable fields",
  conflict: "Conflicts found",
  missing: "Not in our DB",
};

const STATUS_PILL: Record<OverallStatus, string> = {
  match: "bg-green-700 text-green-100",
  no_data: "bg-green-900 text-green-300",
  conflict: "bg-yellow-700 text-yellow-100",
  missing: "bg-red-700 text-red-100",
};

function fmtField(v: number | string | null | undefined, key: string): string {
  if (v == null || v === "") return "—";
  if (key === "tiv" && typeof v === "number") {
    return v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(1)}M` : `$${v.toLocaleString()}`;
  }
  return String(v);
}

interface BoardMatch {
  title: string | null;
  role: string | null;
  corp_name: string | null;
  matched_name: string | null;
  pa_owner_search_url: string | null;
}

interface SiblingRow {
  id: number;
  address: string | null;
  owner_name: string | null;
  unit_suffix: string | null;
  dor_use_code: string | null;
  dor_num_units: number | null;
  living_sqft: number | null;
  tiv_estimate: number | null;
  dor_market_value: number | null;
  is_condo_unit_parcel: boolean;
  is_condo_master: boolean;
  board_match: BoardMatch | null;
  pa_owner_search_url: string | null;
}

interface SiblingsResponse {
  master_id: number;
  master_name: string;
  is_aggregation_master: boolean;
  sibling_count: number;
  board_member_count?: number;
  board_associations?: string[];
  siblings: SiblingRow[];
}

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${Math.round(n / 1_000)}k`;
  return `$${n.toLocaleString()}`;
}

function unitSuffixFromAddress(addr: string | null): string {
  if (!addr) return "";
  // Most NAL rows look like "1451 BRICKELL AVE 1702" or "445 HAMDEN DR
  // # 406". Pull just the unit/apt portion so the table doesn't repeat
  // the building street number on every row.
  const m = addr.match(/(?:#\s*|\bUNIT\s+|\bAPT\s+|\bSTE\s+|\s)([A-Z0-9-]+)\s*(?:BLD|BLDG|BUILDING)?/i);
  if (m && m[1] && /[0-9]/.test(m[1])) return m[1];
  return "";
}

function SiblingsPanel({
  masterId,
  expectedCount,
  onOpenEntity,
}: {
  masterId: number;
  expectedCount: number;
  onOpenEntity?: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<SiblingsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || data || loading) return;
    setLoading(true);
    fetch(`/api/proxy/leads/${masterId}/siblings`)
      .then(async (r) => {
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j?.detail ?? `HTTP ${r.status}`);
        return j as SiblingsResponse;
      })
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [open, data, loading, masterId]);

  return (
    <details
      className="mt-1.5"
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary className="text-[10px] text-teal-300 cursor-pointer hover:text-teal-200 select-none">
        {open ? "▼" : "▶"} {expectedCount} linked parcels
        {data ? ` · sum ${fmtMoney(
          data.siblings.reduce((s, x) => s + (x.tiv_estimate ?? x.dor_market_value ?? 0), 0)
        )}` : ""}
        {data && (data.board_member_count ?? 0) > 0 && (
          <span
            className="ml-2 px-1.5 py-0.5 rounded bg-amber-900/60 text-amber-200 font-mono"
            title={
              (data.board_associations ?? []).join(" · ") ||
              "Unit owners on the association board"
            }
          >
            ★ {data.board_member_count} on board
          </span>
        )}
      </summary>
      {open && (
        <div className="mt-1 max-h-64 overflow-auto rounded border border-gray-800 bg-gray-950">
          {loading && <div className="p-2 text-[10px] text-gray-500">Loading…</div>}
          {error && <div className="p-2 text-[10px] text-red-400">{error}</div>}
          {data && data.siblings.length === 0 && (
            <div className="p-2 text-[10px] text-gray-500">No linked parcels recorded.</div>
          )}
          {data && data.siblings.length > 0 && (
            <table className="w-full text-[10px] font-mono">
              <thead className="bg-gray-900 text-gray-400 sticky top-0">
                <tr>
                  <th className="text-left px-2 py-1 font-normal">Unit</th>
                  <th className="text-left px-2 py-1 font-normal">Owner</th>
                  <th className="text-right px-2 py-1 font-normal">Sqft</th>
                  <th className="text-right px-2 py-1 font-normal">JV</th>
                  <th className="text-right px-2 py-1 font-normal">TIV est.</th>
                </tr>
              </thead>
              <tbody>
                {data.siblings.map((s) => (
                  <tr
                    key={s.id}
                    className={`border-t border-gray-900 hover:bg-gray-900 ${
                      s.board_match ? "bg-amber-950/30" : ""
                    }`}
                  >
                    <td className="px-2 py-0.5">
                      {onOpenEntity ? (
                        <button
                          onClick={() => onOpenEntity(s.id)}
                          className="text-blue-400 hover:text-blue-300 underline"
                          title={s.address ?? `#${s.id}`}
                        >
                          {unitSuffixFromAddress(s.address) || `#${s.id}`}
                        </button>
                      ) : (
                        <Link
                          href={`/lead/${s.id}`}
                          target="_blank"
                          className="text-blue-400 hover:text-blue-300"
                          title={s.address ?? `#${s.id}`}
                        >
                          {unitSuffixFromAddress(s.address) || `#${s.id}`}
                        </Link>
                      )}
                    </td>
                    <td
                      className="px-2 py-0.5 text-gray-300 max-w-[220px]"
                      title={
                        s.board_match
                          ? `${s.owner_name ?? ""}\nBoard match: ${s.board_match.matched_name ?? ""}\n${s.board_match.corp_name ?? ""}`
                          : (s.owner_name ?? "")
                      }
                    >
                      <div className="flex items-center gap-1 min-w-0">
                        {s.board_match && (
                          <span
                            className="text-amber-300 shrink-0"
                            title={`${s.board_match.title ?? "Officer"} of ${s.board_match.corp_name ?? "association"}`}
                          >
                            ★ {s.board_match.title}
                          </span>
                        )}
                        <span className="truncate">{s.owner_name ?? "—"}</span>
                        {s.pa_owner_search_url && s.owner_name && (
                          <a
                            href={s.pa_owner_search_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-400 hover:text-blue-300 text-[9px] shrink-0 ml-1"
                            title="Search this owner in the county Property Appraiser"
                          >
                            PA ↗
                          </a>
                        )}
                      </div>
                    </td>
                    <td className="px-2 py-0.5 text-right text-gray-400">
                      {s.living_sqft ? s.living_sqft.toLocaleString() : "—"}
                    </td>
                    <td className="px-2 py-0.5 text-right text-gray-400">
                      {fmtMoney(s.dor_market_value)}
                    </td>
                    <td className="px-2 py-0.5 text-right text-gray-300">
                      {fmtMoney(s.tiv_estimate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </details>
  );
}

function CompareResultsView({
  results,
  onOpenEntity,
}: {
  results: CompareResponse;
  onOpenEntity?: (id: number) => void;
}) {
  const counts = results.counts ?? {};
  return (
    <div>
      <div className="flex items-center gap-3 mb-3 flex-wrap">
        <h3 className="text-xs font-semibold text-gray-400">
          Comparison — {results.total} {results.total === 1 ? "result" : "results"}
        </h3>
        <CountPill label="match" count={counts.match ?? 0} status="match" />
        <CountPill label="conflict" count={counts.conflict ?? 0} status="conflict" />
        <CountPill label="missing" count={counts.missing ?? 0} status="missing" />
        {(counts.no_data ?? 0) > 0 && (
          <CountPill label="no data" count={counts.no_data ?? 0} status="no_data" />
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {results.results.map((r, i) => (
          <ResultCard key={i} r={r} onOpenEntity={onOpenEntity} />
        ))}
      </div>
    </div>
  );
}

function CountPill({ label, count, status }: { label: string; count: number; status: OverallStatus }) {
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded font-mono ${STATUS_PILL[status]}`}>
      {label}: {count}
    </span>
  );
}

function ResultCard({
  r,
  onOpenEntity,
}: {
  r: CompareResult;
  onOpenEntity?: (id: number) => void;
}) {
  const border = STATUS_BORDER[r.status];
  const pill = STATUS_PILL[r.status];
  const label = STATUS_LABEL[r.status];
  const inputName = r.input.name ?? r.input.address ?? "(unnamed)";
  const inputAddr = [r.input.address, r.input.city, r.input.state, r.input.zip]
    .filter(Boolean)
    .join(", ");

  return (
    <div className={`border rounded-lg p-3 ${border}`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white truncate">{inputName}</div>
          <div className="text-[11px] text-gray-400 truncate">{inputAddr || "—"}</div>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded shrink-0 font-medium ${pill}`}>
          {label}
        </span>
      </div>

      {r.match ? (
        <div className="mb-2 pb-2 border-b border-gray-800">
          <div className="flex items-center justify-between gap-2">
            {onOpenEntity ? (
              <button
                onClick={() => onOpenEntity(r.match!.id)}
                className="text-[12px] font-medium text-blue-400 hover:text-blue-300 truncate text-left underline"
                title="Open in modal (closing returns here)"
              >
                {r.match.name}
              </button>
            ) : (
              <Link href={`/lead/${r.match.id}`} target="_blank"
                className="text-[12px] font-medium text-blue-400 hover:text-blue-300 truncate">
                {r.match.name}
              </Link>
            )}
            <div className="flex items-center gap-1.5 shrink-0">
              {typeof r.match_score === "number" && (
                <span
                  className={`text-[9px] font-mono px-1 py-0.5 rounded ${
                    r.match_score >= 80
                      ? "bg-green-900/60 text-green-300"
                      : r.match_score >= 60
                      ? "bg-yellow-900/60 text-yellow-300"
                      : "bg-red-900/60 text-red-300"
                  }`}
                  title={`Match confidence — 100: zip+canon | 85: canon+city (zip mismatch) | 80: canon-only | 60: non-master`}
                >
                  m:{r.match_score}
                </span>
              )}
              <span className="text-[10px] text-gray-500">#{r.match.id}</span>
            </div>
          </div>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">
              {r.match.pipeline_stage}
            </span>
            {r.match.is_aggregation_master && (r.match.sibling_count ?? 0) > 0 && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded bg-teal-900/60 text-teal-200"
                title={
                  `Rolled-up master: TIV/units summed across ` +
                  `${(r.match.sibling_count ?? 0) + 1} linked parcels.`
                }
              >
                rollup ×{(r.match.sibling_count ?? 0) + 1}
              </span>
            )}
            {!r.match.is_aggregation_master && r.match.is_condo_unit_parcel && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/60 text-amber-200"
                title={
                  "Matched on a single unit parcel — building total not " +
                  "available. The aggregator hasn't grouped this address yet, " +
                  "so TIV / units comparison is suppressed. Year / ISO still apply."
                }
              >
                unit parcel only
              </span>
            )}
            {r.match.county && (
              <span className="text-[10px] text-gray-500">{r.match.county}</span>
            )}
            {r.match.cream_tier && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-900/60 text-purple-200">
                {r.match.cream_tier}
                {r.match.cream_score != null ? ` ${r.match.cream_score}` : ""}
              </span>
            )}
          </div>
          {r.match.address && (
            <div className="text-[10px] text-gray-500 mt-1 truncate">{r.match.address}</div>
          )}
          {r.match.is_aggregation_master && (r.match.sibling_count ?? 0) > 0 && (
            <SiblingsPanel
              masterId={r.match.id}
              expectedCount={r.match.sibling_count ?? 0}
              onOpenEntity={onOpenEntity}
            />
          )}
        </div>
      ) : (
        <div className="mb-2 pb-2 border-b border-gray-800 text-[11px] text-red-300 space-y-0.5">
          <div>No matching entity in our database.</div>
          {r.match_debug && (
            <div className="text-gray-500 text-[10px] font-mono mt-1 space-y-0.5">
              <div>
                <>num: <span className="text-gray-300">{r.match_debug.parsed_number ?? "—"}</span>{" · "}</>
                <>zip: <span className="text-gray-300">{r.match_debug.parsed_zip ?? "—"}</span>{" · "}</>
                <>city: <span className="text-gray-300">{r.match_debug.parsed_city ?? "—"}</span>{" · "}</>
                <>canon: <span className="text-gray-300">{r.match_debug.parsed_canon ?? "—"}</span></>
              </div>
              <div>
                <span className="text-gray-400">
                  zip+num: <span className="text-gray-300">{r.match_debug.candidates_by_zip_number ?? 0}</span>
                  {" · "}
                  city+num: <span className="text-gray-300">{r.match_debug.candidates_by_city_number ?? 0}</span>
                  {" · "}
                  canon: <span className="text-gray-300">{r.match_debug.candidates_by_canon ?? 0}</span>
                  {r.match_debug.match_phase
                    ? ` · phase: ${r.match_debug.match_phase.replace(/_/g, " ")}`
                    : ""}
                </span>
              </div>
              {r.match_debug.nearby_canons && r.match_debug.nearby_canons.length > 0 && (
                <div className="text-amber-400">
                  seeded canons at this number:{" "}
                  {r.match_debug.nearby_canons.slice(0, 8).map((c) => `"${c}"`).join(" · ")}
                  {r.match_debug.nearby_canons.length > 8 && ` (+${r.match_debug.nearby_canons.length - 8} more)`}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="space-y-0.5">
        {Object.entries(r.fields).map(([key, diff]) => (
          <FieldRow key={key} field={key} diff={diff} />
        ))}
        {Object.keys(r.fields).length === 0 && (
          <div className="text-[11px] text-gray-500 italic">
            No fields to compare.
          </div>
        )}
      </div>
    </div>
  );
}

function FieldRow({ field, diff }: { field: string; diff: FieldDiff }) {
  const label = FIELD_LABELS[field] ?? field;
  const inputStr = fmtField(diff.input, field);
  const dbStr = fmtField(diff.db, field);

  let dot = "bg-gray-700";
  let valueColor = "text-gray-400";
  if (diff.status === "match") {
    dot = "bg-green-500";
    valueColor = "text-gray-300";
  } else if (diff.status === "conflict") {
    dot = "bg-yellow-500";
    valueColor = "text-yellow-300";
  } else if (diff.status === "no_data") {
    dot = "bg-gray-600";
    valueColor = "text-gray-500";
  } else if (diff.status === "no_input") {
    dot = "bg-gray-700";
    valueColor = "text-gray-600";
  }

  // ISO is the only field where the user benefits from seeing the raw
  // DOR construction string — the derivation is heuristic, and "Masonry"
  // → 4 vs Jason's 2 (JM) is something the user wants to eyeball. For
  // every other field db_raw lives in the title tooltip.
  const showRaw = field === "iso_class" && diff.db_raw;

  return (
    <div className="text-[11px]">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
          <span className="text-gray-500 w-20 shrink-0">{label}</span>
        </div>
        <div className={`font-mono truncate ${valueColor}`} title={diff.db_raw ?? ""}>
          <span>{inputStr}</span>
          <span className="text-gray-600 mx-1">vs</span>
          <span>{dbStr}</span>
        </div>
      </div>
      {showRaw && (
        <div className="text-[9px] text-gray-600 ml-[14px] truncate" title={diff.db_raw ?? ""}>
          DOR class: <span className="text-gray-500">{diff.db_raw}</span>
        </div>
      )}
    </div>
  );
}
