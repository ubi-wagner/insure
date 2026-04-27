"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import UserMenu from "@/components/UserMenu";

type TabName = "compare" | "events";

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

export default function ValidationPage() {
  const [tab, setTab] = useState<TabName>("compare");

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
          <div className="text-gray-500 text-sm py-12 text-center border border-dashed border-gray-800 rounded-lg">
            Bulk Compare — coming next build
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
