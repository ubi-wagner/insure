"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import UserMenu from "@/components/UserMenu";

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

  // Bulk compare state
  const [pasteText, setPasteText] = useState<string>("");
  const [parsed, setParsed] = useState<ParsedItem[] | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [parsing, setParsing] = useState(false);

  async function handleParse() {
    setParsing(true);
    setParseError(null);
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
                <p className="text-[10px] text-gray-600 mt-2">
                  Comparison cards (green / yellow / red) ship in the next build.
                </p>
              </div>
            )}

            {parsed && parsed.length === 0 && (
              <p className="text-amber-400 text-xs">
                No properties parsed from input.
              </p>
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
