"use client";

import { Suspense, useCallback, useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import MapView from "@/components/MapView";
import LeadPipeline from "@/components/LeadPipeline";
import EntityDetailModal from "@/components/EntityDetailModal";

interface LeadLocation {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  heat_score: string;
  status: string;
  listIndex: number;
}

const MAX_MODALS = 5;

export default function DashboardPage() {
  return (
    <Suspense fallback={<div className="h-screen bg-gray-950" />}>
      <Dashboard />
    </Suspense>
  );
}

function Dashboard() {
  const searchParams = useSearchParams();
  const [refreshKey, setRefreshKey] = useState(0);
  const [leads, setLeads] = useState<LeadLocation[]>([]);
  const [hoveredLeadId, setHoveredLeadId] = useState<number | null>(null);
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [switchToStage, setSwitchToStage] = useState<string | null>(null);
  const [initialCounty] = useState<string | null>(searchParams.get("county"));
  const [flyToTarget, setFlyToTarget] = useState<{ lat: number; lng: number } | null>(null);
  const [mobileView, setMobileView] = useState<"map" | "pipeline">("pipeline");

  // Apply stage from URL query params on mount
  useEffect(() => {
    const stage = searchParams.get("stage");
    if (stage) setSwitchToStage(stage);
  }, [searchParams]);

  // Modal system: max 5 open, ordered by open time
  const [openModals, setOpenModals] = useState<number[]>([]);
  const [activeModal, setActiveModal] = useState<number | null>(null);

  function openEntityModal(id: number) {
    setOpenModals((prev) => {
      // Don't duplicate
      if (prev.includes(id)) {
        setActiveModal(id);
        return prev;
      }
      let next = [...prev, id];
      // If over limit, close the oldest
      if (next.length > MAX_MODALS) {
        next = next.slice(1);
      }
      setActiveModal(id);
      return next;
    });
  }

  function closeModal(id: number) {
    setOpenModals((prev) => {
      const next = prev.filter((m) => m !== id);
      if (activeModal === id) {
        setActiveModal(next.length > 0 ? next[next.length - 1] : null);
      }
      return next;
    });
  }

  const handleLeadsLoaded = useCallback((loadedLeads: LeadLocation[]) => {
    setLeads(loadedLeads);
  }, []);

  function handleMarkerClick(id: number) {
    setSelectedLeadId(id);
    const lead = leads.find((l: LeadLocation) => l.id === id);
    if (lead) {
      if (lead.latitude != null && lead.longitude != null) {
        setFlyToTarget({ lat: lead.latitude, lng: lead.longitude });
      }
      if (lead.status) {
        setSwitchToStage(lead.status);
      }
      openEntityModal(id);
    }
  }

  return (
    <div className="h-screen flex flex-col bg-gray-950 text-white">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-3 md:px-4 py-2 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <h1 className="text-base font-bold tracking-tight">Insure</h1>
          <span className="text-gray-600 text-xs hidden sm:inline">Pipeline</span>
        </div>
        <div className="flex items-center gap-2">
          {openModals.length > 0 && (
            <span className="text-gray-600 text-[10px]">{openModals.length}/{MAX_MODALS} open</span>
          )}
          <Link href="/files" className="text-gray-500 hover:text-white text-xs">Files</Link>
          <Link href="/ref" className="text-gray-500 hover:text-white text-xs">Ref</Link>
          <Link href="/ops" className="text-gray-500 hover:text-white text-xs">Ops</Link>
          <Link href="/help" className="text-blue-400 hover:text-blue-300 text-xs font-medium">? Help</Link>
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
        <div className={`flex-1 relative pr-[30px] ${mobileView === "pipeline" ? "hidden md:block" : ""}`}>
          <MapView
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
              switchToStage={switchToStage}
              initialCounty={initialCounty}
              onFlyTo={(lat: number, lng: number, id: number) => {
                setFlyToTarget({ lat, lng });
                setSelectedLeadId(id);
                setMobileView("map");
              }}
              onOpenDetails={(id: number) => openEntityModal(id)}
            />
          </div>
        </div>
      </main>

      {/* Backdrop overlay — dims background when modals are open */}
      {openModals.length > 0 && (
        <div
          className="fixed inset-0 bg-black/40 z-40 transition-opacity duration-300"
          onClick={() => { if (activeModal != null) closeModal(activeModal); }}
        />
      )}

      {/* Entity Detail Modals — stacked with visual offset, max 5 */}
      {openModals.map((id, idx) => (
        <EntityDetailModal
          key={id}
          entityId={id}
          isActive={activeModal === id}
          stackIndex={idx}
          totalOpen={openModals.length}
          onActivate={() => setActiveModal(id)}
          onClose={() => closeModal(id)}
          onFlyTo={(lat, lng) => {
            setFlyToTarget({ lat, lng });
            setSelectedLeadId(id);
            setMobileView("map");
          }}
        />
      ))}

      {/* Modal tab bar — fixed at bottom, positioned to the left of modals */}
      {openModals.length > 0 && (
        <div className="fixed bottom-0 left-0 right-0 sm:right-[430px] bg-gray-900/95 backdrop-blur-sm border-t border-gray-800 flex items-center px-2 py-1.5 z-[60] gap-1 overflow-x-auto">
          {openModals.map((id) => {
            const lead = leads.find((l) => l.id === id);
            return (
              <button key={id} onClick={() => setActiveModal(id)}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] shrink-0 max-w-[180px] transition-colors ${
                  activeModal === id
                    ? "bg-blue-900/60 text-blue-300 border border-blue-600 shadow-sm shadow-blue-900/30"
                    : "bg-gray-800/80 text-gray-500 border border-gray-700 hover:text-gray-300 hover:border-gray-600"
                }`}>
                <span className="truncate">{lead?.name ?? `#${id}`}</span>
                <span onClick={(e) => { e.stopPropagation(); closeModal(id); }}
                  className="text-gray-600 hover:text-red-400 ml-0.5 text-sm leading-none">&times;</span>
              </button>
            );
          })}
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
