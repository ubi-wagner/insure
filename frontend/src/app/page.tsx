"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import MapView from "@/components/MapView";
import LeadPipeline from "@/components/LeadPipeline";

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
  const [huntingStatus, setHuntingStatus] = useState<string | null>(null);
  const huntPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const router = useRouter();

  const handleLeadsLoaded = useCallback((loadedLeads: LeadLocation[]) => {
    setLeads(loadedLeads);
  }, []);

  function handleMarkerClick(id: number) {
    setSelectedLeadId(id);
    const lead = leads.find(l => l.id === id);
    if (lead?.latitude && lead?.longitude) {
      setFlyToTarget({ lat: lead.latitude, lng: lead.longitude });
    }
  }

  function startHuntPolling(regionId: number) {
    setHuntingStatus("Discovering properties...");
    if (huntPollRef.current) clearInterval(huntPollRef.current);
    let polls = 0;
    huntPollRef.current = setInterval(async () => {
      polls++;
      try {
        const res = await fetch(`/api/proxy/regions/${regionId}`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.status === "COMPLETED") {
          setHuntingStatus(data.lead_count > 0
            ? `Found ${data.lead_count} properties`
            : "No matching buildings found in this area"
          );
          setRefreshKey((k) => k + 1);
          if (huntPollRef.current) clearInterval(huntPollRef.current);
          setTimeout(() => setHuntingStatus(null), 6000);
        } else {
          setHuntingStatus(`Discovering properties${data.lead_count > 0 ? ` (${data.lead_count} so far)` : "..."}`);
          if (polls % 2 === 0) setRefreshKey((k) => k + 1);
        }
      } catch {}
    }, 3000);
  }

  useEffect(() => {
    return () => { if (huntPollRef.current) clearInterval(huntPollRef.current); };
  }, []);

  return (
    <div className="h-screen flex flex-col bg-gray-950 text-white">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-4 py-2 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-bold tracking-tight">Insure</h1>
          <span className="text-gray-600 text-xs">Pipeline</span>
        </div>
        <div className="flex items-center gap-3">
          {huntingStatus && (
            <div className="flex items-center gap-2 bg-blue-900/30 border border-blue-800/50 rounded-full px-3 py-1">
              <div className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" />
              <span className="text-blue-300 text-xs">{huntingStatus}</span>
            </div>
          )}
          <Link href="/ops" className="text-gray-500 hover:text-white text-xs">Ops</Link>
          <Link href="/events" className="text-gray-500 hover:text-white text-xs">Events</Link>
        </div>
      </header>

      {/* Split layout */}
      <main className="flex-1 flex overflow-hidden">
        {/* Map */}
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

        {/* Pipeline */}
        <div className="w-[380px] border-l border-gray-800 bg-gray-950 flex flex-col shrink-0">
          <div className="p-3 flex-1 overflow-hidden flex flex-col">
            <LeadPipeline
              refreshKey={refreshKey}
              onLeadsLoaded={handleLeadsLoaded}
              onLeadHover={setHoveredLeadId}
              selectedLeadId={selectedLeadId}
              onFlyTo={(lat, lng, id) => { setFlyToTarget({ lat, lng }); setSelectedLeadId(id); }}
              onOpenDetails={(id) => router.push(`/lead/${id}`)}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
