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
  const [mobileView, setMobileView] = useState<"map" | "pipeline">("pipeline");
  const huntPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const router = useRouter();

  const handleLeadsLoaded = useCallback((loadedLeads: LeadLocation[]) => {
    setLeads(loadedLeads);
  }, []);

  function handleMarkerClick(id: number) {
    setSelectedLeadId(id);
    const lead = leads.find((l: LeadLocation) => l.id === id);
    if (lead?.latitude && lead?.longitude) {
      setFlyToTarget({ lat: lead.latitude, lng: lead.longitude });
    }
  }

  function startHuntPolling(regionId: number) {
    setHuntingStatus("Discovering properties...");
    setMobileView("pipeline");
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
            : "No matching buildings in this area"
          );
          setRefreshKey((k: number) => k + 1);
          if (huntPollRef.current) clearInterval(huntPollRef.current);
          setTimeout(() => setHuntingStatus(null), 6000);
        } else {
          setHuntingStatus(`Discovering${data.lead_count > 0 ? ` (${data.lead_count})` : "..."}`);
          if (polls % 2 === 0) setRefreshKey((k: number) => k + 1);
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
      <header className="bg-gray-900 border-b border-gray-800 px-3 md:px-4 py-2 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <h1 className="text-base font-bold tracking-tight">Insure</h1>
          <span className="text-gray-600 text-xs hidden sm:inline">Pipeline</span>
        </div>
        <div className="flex items-center gap-2">
          {huntingStatus && (
            <div className="flex items-center gap-1.5 bg-blue-900/30 border border-blue-800/50 rounded-full px-2.5 py-1">
              <div className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" />
              <span className="text-blue-300 text-[11px]">{huntingStatus}</span>
            </div>
          )}
          <Link href="/files" className="text-gray-500 hover:text-white text-xs">Files</Link>
          <Link href="/ops" className="text-gray-500 hover:text-white text-xs">Ops</Link>
        </div>
      </header>

      {/* Mobile tab toggle */}
      <div className="md:hidden flex border-b border-gray-800">
        <button onClick={() => setMobileView("pipeline")}
          className={`flex-1 py-2.5 text-sm font-medium text-center ${mobileView === "pipeline" ? "text-white border-b-2 border-blue-500" : "text-gray-500"}`}>
          Pipeline ({leads.length})
        </button>
        <button onClick={() => setMobileView("map")}
          className={`flex-1 py-2.5 text-sm font-medium text-center ${mobileView === "map" ? "text-white border-b-2 border-blue-500" : "text-gray-500"}`}>
          Map
        </button>
      </div>

      {/* Split layout — side by side on desktop, tabbed on mobile */}
      <main className="flex-1 flex overflow-hidden">
        {/* Map — hidden on mobile when pipeline is active */}
        <div className={`flex-1 relative ${mobileView === "pipeline" ? "hidden md:block" : ""}`}>
          <MapView
            onRegionCreated={(regionId: number) => startHuntPolling(regionId)}
            leads={leads}
            hoveredLeadId={hoveredLeadId}
            selectedLeadId={selectedLeadId}
            flyToTarget={flyToTarget}
            onMarkerClick={handleMarkerClick}
          />
        </div>

        {/* Pipeline — full width on mobile, fixed width on desktop */}
        <div className={`w-full md:w-[380px] md:border-l border-gray-800 bg-gray-950 flex flex-col shrink-0 ${mobileView === "map" ? "hidden md:flex" : "flex"}`}>
          <div className="p-3 flex-1 overflow-hidden flex flex-col">
            <LeadPipeline
              refreshKey={refreshKey}
              onLeadsLoaded={handleLeadsLoaded}
              onLeadHover={setHoveredLeadId}
              selectedLeadId={selectedLeadId}
              onFlyTo={(lat: number, lng: number, id: number) => {
                setFlyToTarget({ lat, lng });
                setSelectedLeadId(id);
                setMobileView("map");
              }}
              onOpenDetails={(id: number) => router.push(`/lead/${id}`)}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
