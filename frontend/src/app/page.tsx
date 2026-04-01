"use client";

import { useCallback, useState } from "react";
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
  const router = useRouter();

  const handleLeadsLoaded = useCallback((loadedLeads: LeadLocation[]) => {
    setLeads(loadedLeads);
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
            onRegionCreated={() => setRefreshKey((k) => k + 1)}
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
