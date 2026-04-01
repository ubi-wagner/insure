"use client";

import { useEffect, useState } from "react";

interface ServiceStatus {
  name: string;
  status: string;
  last_heartbeat: string;
  age_seconds: number;
  capabilities: Record<string, unknown>;
  detail: string;
}

interface SystemStatus {
  overall: string;
  services: ServiceStatus[];
}

const STATUS_COLORS: Record<string, string> = {
  healthy: "bg-green-500",
  degraded: "bg-yellow-500",
  down: "bg-red-500",
  stale: "bg-orange-500",
  error: "bg-red-500",
  unknown: "bg-gray-500",
  starting: "bg-blue-500",
};

const STATUS_TEXT: Record<string, string> = {
  healthy: "text-green-400",
  degraded: "text-yellow-400",
  down: "text-red-400",
  stale: "text-orange-400",
  error: "text-red-400",
  unknown: "text-gray-400",
  starting: "text-blue-400",
};

export default function StatusBar() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 15000);
    return () => clearInterval(interval);
  }, []);

  async function fetchStatus() {
    try {
      const res = await fetch("/api/proxy/status");
      if (res.ok) {
        setStatus(await res.json());
        setError(false);
      } else {
        setError(true);
      }
    } catch {
      setError(true);
    }
  }

  if (error) {
    return (
      <div className="bg-red-950 border-b border-red-800 px-6 py-1.5 flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
        <span className="text-red-400 text-xs">API unreachable</span>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="bg-gray-900/50 border-b border-gray-800 px-6 py-1.5 flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-gray-500 animate-pulse" />
        <span className="text-gray-500 text-xs">Connecting...</span>
      </div>
    );
  }

  return (
    <div className="bg-gray-900/50 border-b border-gray-800 px-6 py-1.5 flex items-center gap-4 text-xs">
      {/* Overall */}
      <div className="flex items-center gap-1.5">
        <span className={`w-2 h-2 rounded-full ${STATUS_COLORS[status.overall] || STATUS_COLORS.unknown}`} />
        <span className={`font-medium ${STATUS_TEXT[status.overall] || STATUS_TEXT.unknown}`}>
          System {status.overall}
        </span>
      </div>

      <span className="text-gray-700">|</span>

      {/* Per-service */}
      {status.services.map((svc) => (
        <div key={svc.name} className="flex items-center gap-1.5" title={`${svc.detail}\nLast heartbeat: ${svc.age_seconds}s ago`}>
          <span className={`w-1.5 h-1.5 rounded-full ${STATUS_COLORS[svc.status] || STATUS_COLORS.unknown}`} />
          <span className="text-gray-400 capitalize">{svc.name}</span>
          <span className={`${STATUS_TEXT[svc.status] || STATUS_TEXT.unknown}`}>
            {svc.detail.length > 30 ? svc.detail.slice(0, 30) + "..." : svc.detail}
          </span>
        </div>
      ))}
    </div>
  );
}
