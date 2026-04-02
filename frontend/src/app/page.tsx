"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import MapView from "@/components/MapView";
import LeadPipeline from "@/components/LeadPipeline";
import StatusBar from "@/components/StatusBar";

interface LeadLocation {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  heat_score: string;
  status: string;
  listIndex: number;
}

export default function Dashboard() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [leads, setLeads] = useState<LeadLocation[]>([]);
  const [hoveredLeadId, setHoveredLeadId] = useState<number | null>(null);
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [flyToTarget, setFlyToTarget] = useState<{ lat: number; lng: number } | null>(null);
  const [detailIds, setDetailIds] = useState<number[]>([]);
  const [huntingStatus, setHuntingStatus] = useState<string | null>(null);
  const huntPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const router = useRouter();

  const handleLeadsLoaded = useCallback((loadedLeads: LeadLocation[]) => {
    setLeads(loadedLeads);
  }, []);

  // Poll for region completion after hunt starts
  function startHuntPolling(regionId: number) {
    setHuntingStatus("Hunting...");
    if (huntPollRef.current) clearInterval(huntPollRef.current);
    let polls = 0;
    huntPollRef.current = setInterval(async () => {
      polls++;
      try {
        const res = await fetch(`/api/proxy/regions/${regionId}`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.status === "COMPLETED") {
          setHuntingStatus(`Found ${data.lead_count} properties`);
          setRefreshKey((k) => k + 1);
          if (huntPollRef.current) clearInterval(huntPollRef.current);
          setTimeout(() => setHuntingStatus(null), 5000);
        } else {
          setHuntingStatus(`Hunting... ${data.lead_count > 0 ? `(${data.lead_count} found)` : ""}`);
          // Also refresh leads periodically so results appear as they're found
          if (polls % 2 === 0) setRefreshKey((k) => k + 1);
        }
      } catch {}
    }, 3000);
  }

  // Cleanup polling on unmount
  useEffect(() => {
    return () => { if (huntPollRef.current) clearInterval(huntPollRef.current); };
  }, []);

  function handleMarkerClick(id: number) {
    setSelectedLeadId(id);
    // Find the lead and zoom to it
    const lead = leads.find(l => l.id === id);
    if (lead?.latitude && lead?.longitude) {
      setFlyToTarget({ lat: lead.latitude, lng: lead.longitude });
    }
  }

  function handleOpenDetails(id: number) {
    setDetailIds(prev => {
      if (prev.includes(id)) return prev;
      const next = [...prev, id];
      return next.length > 5 ? next.slice(-5) : next; // max 5 open
    });
    router.push(`/lead/${id}`);
  }

  async function handleLogout() {
    await fetch("/api/auth", { method: "DELETE" });
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="h-screen flex flex-col">
      {/* Top Bar */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-2 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-bold">Insure</h1>
          <span className="text-gray-500 text-sm">Hunt · Kill · Cook</span>
        </div>
        <div className="flex items-center gap-4">
          {detailIds.length > 0 && (
            <div className="flex gap-1">
              {detailIds.map((id) => (
                <Link key={id} href={`/lead/${id}`}
                  className="bg-gray-800 text-gray-400 hover:text-white text-xs px-2 py-1 rounded">
                  #{id}
                </Link>
              ))}
            </div>
          )}
          <Link href="/ops" className="text-gray-400 hover:text-white text-sm">
            Ops
          </Link>
          <Link href="/events" className="text-gray-400 hover:text-white text-sm">
            Events
          </Link>
          <button onClick={handleLogout} className="text-gray-400 hover:text-white text-sm">
            Logout
          </button>
        </div>
      </header>

      <StatusBar />

      {/* Split layout: map left, cards right */}
      <main className="flex-1 flex overflow-hidden">
        {/* Map panel */}
        <div className="flex-1 relative">
          <MapView
            onRegionCreated={(regionId) => startHuntPolling(regionId)}
            leads={leads}
            hoveredLeadId={hoveredLeadId}
            selectedLeadId={selectedLeadId}
            flyToTarget={flyToTarget}
            onMarkerClick={handleMarkerClick}
          />
        </div>

        {/* Lead panel */}
        <div className="w-[420px] border-l border-gray-800 bg-gray-950 flex flex-col shrink-0">
          <div className="p-4 overflow-y-auto flex-1">
            {huntingStatus && (
              <div className="bg-blue-900/30 border border-blue-800 rounded-lg px-3 py-2 mb-3 flex items-center gap-2">
                <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
                <span className="text-blue-300 text-xs font-medium">{huntingStatus}</span>
              </div>
            )}
            <LeadPipeline
              refreshKey={refreshKey}
              onLeadsLoaded={handleLeadsLoaded}
              onLeadHover={setHoveredLeadId}
              selectedLeadId={selectedLeadId}
              onFlyTo={(lat, lng, id) => { setFlyToTarget({ lat, lng }); setSelectedLeadId(id); }}
              onOpenDetails={handleOpenDetails}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
