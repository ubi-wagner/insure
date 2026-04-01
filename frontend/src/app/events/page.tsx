"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

interface EventItem {
  event_type: string;
  action: string;
  status: string;
  detail: string;
  duration_ms: number | null;
  metadata: Record<string, unknown>;
  timestamp: number;
}

const TYPE_COLORS: Record<string, string> = {
  HTTP: "text-blue-400",
  DB: "text-yellow-400",
  API: "text-purple-400",
  HUNTER: "text-green-400",
  AI: "text-pink-400",
  AUTH: "text-orange-400",
  SYSTEM: "text-cyan-400",
};

const STATUS_BADGES: Record<string, string> = {
  success: "bg-green-900 text-green-300",
  error: "bg-red-900 text-red-300",
  pending: "bg-yellow-900 text-yellow-300",
};

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

export default function EventStreamPage() {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [connected, setConnected] = useState(false);
  const [filter, setFilter] = useState<string>("ALL");
  const [paused, setPaused] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(false);

  // Keep ref in sync so the SSE callback sees latest value
  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  // Load history on mount
  useEffect(() => {
    fetch(`/api/proxy/events?limit=200`, { credentials: "include" })
      .then((res) => res.ok ? res.json() : [])
      .then((data: EventItem[]) => setEvents(data))
      .catch(() => {});
  }, []);

  // SSE stream
  useEffect(() => {
    const es = new EventSource(`/api/proxy/events/stream`);

    es.onopen = () => setConnected(true);

    es.onmessage = (msg) => {
      if (pausedRef.current) return;
      try {
        const event: EventItem = JSON.parse(msg.data);
        setEvents((prev) => {
          const next = [...prev, event];
          // Keep last 500 events in memory
          return next.length > 500 ? next.slice(-500) : next;
        });
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      setConnected(false);
    };

    return () => es.close();
  }, []);

  // Auto-scroll
  useEffect(() => {
    if (!paused) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [events, paused]);

  const filteredEvents = filter === "ALL"
    ? events
    : events.filter((e) => e.event_type === filter);

  const eventTypes = ["ALL", "HTTP", "DB", "API", "HUNTER", "AI", "SYSTEM"];

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-lg font-bold hover:text-blue-400 transition-colors">
            Insure
          </Link>
          <span className="text-gray-600">/</span>
          <h1 className="text-lg font-bold">Event Stream</h1>
          <span className={`inline-block w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-red-500"}`} />
          <span className="text-gray-500 text-xs">{connected ? "Live" : "Disconnected"}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-gray-500 text-xs">{filteredEvents.length} events</span>
          <button
            onClick={() => setPaused(!paused)}
            className={`text-xs px-3 py-1 rounded ${paused ? "bg-yellow-700 text-yellow-100" : "bg-gray-700 text-gray-300"}`}
          >
            {paused ? "Paused" : "Pause"}
          </button>
          <button
            onClick={() => setEvents([])}
            className="text-xs px-3 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600"
          >
            Clear
          </button>
        </div>
      </header>

      {/* Filter bar */}
      <div className="bg-gray-900/50 border-b border-gray-800 px-6 py-2 flex gap-2">
        {eventTypes.map((type) => (
          <button
            key={type}
            onClick={() => setFilter(type)}
            className={`text-xs px-3 py-1 rounded transition-colors ${
              filter === type
                ? "bg-blue-600 text-white"
                : `bg-gray-800 hover:bg-gray-700 ${TYPE_COLORS[type] || "text-gray-400"}`
            }`}
          >
            {type}
          </button>
        ))}
      </div>

      {/* Event log */}
      <div className="flex-1 overflow-y-auto font-mono text-xs px-4 py-2 space-y-0.5">
        {filteredEvents.length === 0 && (
          <div className="text-gray-600 text-center py-12">
            {connected ? "Waiting for events..." : "Connecting to event stream..."}
          </div>
        )}

        {filteredEvents.map((event, i) => (
          <div
            key={`${event.timestamp}-${i}`}
            className="flex items-start gap-2 py-1 px-2 rounded hover:bg-gray-900/50 group"
          >
            {/* Timestamp */}
            <span className="text-gray-600 shrink-0 w-24">
              {formatTime(event.timestamp)}
            </span>

            {/* Type badge */}
            <span className={`shrink-0 w-16 font-bold ${TYPE_COLORS[event.event_type] || "text-gray-400"}`}>
              {event.event_type}
            </span>

            {/* Status */}
            <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium ${STATUS_BADGES[event.status] || "bg-gray-800 text-gray-400"}`}>
              {event.status}
            </span>

            {/* Action */}
            <span className="text-white shrink-0 max-w-48 truncate">
              {event.action}
            </span>

            {/* Detail */}
            <span className="text-gray-400 truncate flex-1">
              {event.detail}
            </span>

            {/* Duration */}
            {event.duration_ms !== null && (
              <span className="text-gray-600 shrink-0">
                {event.duration_ms}ms
              </span>
            )}
          </div>
        ))}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
