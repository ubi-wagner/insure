"use client";

import { useEffect, useState } from "react";

interface Lead {
  id: number;
  name: string;
  address: string;
  county: string;
  latitude: number;
  longitude: number;
  characteristics: Record<string, unknown> | null;
  created_at: string;
  status: string;
  pipeline_stage: string;
  wind_ratio: number | null;
  heat_score: string;
  premium_parsed: number | null;
  tiv_parsed: number | null;
  enrichment_status?: string;
}

interface Region {
  id: number;
  name: string;
  bounding_box: { north: number; south: number; east: number; west: number };
  target_county: string | null;
  status: string;
}

// 5-stage pipeline
const PIPELINE_STAGES = [
  { key: "TARGET", label: "Targets", color: "border-gray-600", bg: "bg-gray-800", badge: "bg-gray-700 text-gray-300", action: "", prev: "" },
  { key: "LEAD", label: "Leads", color: "border-cyan-600", bg: "bg-cyan-950/30", badge: "bg-cyan-900 text-cyan-200", action: "Promote", prev: "TARGET" },
  { key: "OPPORTUNITY", label: "Opportunities", color: "border-blue-600", bg: "bg-blue-950/30", badge: "bg-blue-900 text-blue-200", action: "Engage", prev: "LEAD" },
  { key: "CUSTOMER", label: "Customers", color: "border-green-600", bg: "bg-green-950/30", badge: "bg-green-800 text-green-200", action: "", prev: "OPPORTUNITY" },
  { key: "ARCHIVED", label: "Archived", color: "border-gray-700", bg: "bg-gray-900", badge: "bg-gray-800 text-gray-500", action: "", prev: "" },
];

const HEAT_COLORS: Record<string, string> = {
  hot: "bg-red-600 text-white",
  warm: "bg-orange-600 text-white",
  cold: "bg-gray-700 text-gray-400",
};

const TARGET_COUNTIES = [
  "Pasco", "Pinellas", "Hillsborough", "Manatee", "Sarasota",
  "Charlotte", "Lee", "Collier", "Palm Beach", "Miami-Dade", "Broward",
];

interface PipelineProps {
  refreshKey: number;
  onLeadsLoaded?: (leads: { id: number; name: string; latitude: number; longitude: number; heat_score: string; status: string; listIndex: number }[]) => void;
  onLeadHover?: (id: number | null) => void;
  selectedLeadId?: number | null;
  onFlyTo?: (lat: number, lng: number, id: number) => void;
  onOpenDetails?: (id: number) => void;
}

export default function LeadPipeline({ refreshKey, onLeadsLoaded, onLeadHover, selectedLeadId, onFlyTo, onOpenDetails }: PipelineProps) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [county, setCounty] = useState("");
  const [region, setRegion] = useState("");
  const [regions, setRegions] = useState<Region[]>([]);
  const [collapsedStages, setCollapsedStages] = useState<Set<string>>(new Set(["ARCHIVED"]));
  const [activeStageFilter, setActiveStageFilter] = useState<string>("");

  useEffect(() => {
    fetchLeads();
    fetchRegions();
  }, [refreshKey]);

  async function fetchRegions() {
    try {
      const res = await fetch("/api/proxy/regions");
      if (res.ok) { const d = await res.json(); setRegions(Array.isArray(d) ? d : []); }
    } catch {}
  }

  async function fetchLeads() {
    setFetchError(null);
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (county) params.set("county", county);
      const res = await fetch(`/api/proxy/leads?${params}`);
      if (res.ok) {
        const raw = await res.json();
        let data: Lead[] = Array.isArray(raw) ? raw : [];

        // Filter by region bbox
        if (region) {
          const r = regions.find((r) => String(r.id) === region);
          if (r?.bounding_box) {
            const bb = r.bounding_box;
            data = data.filter((l) =>
              l.latitude >= bb.south && l.latitude <= bb.north &&
              l.longitude >= bb.west && l.longitude <= bb.east
            );
          }
        }

        setLeads(data);
        onLeadsLoaded?.(data.map((l, i) => ({
          id: l.id, name: l.name, latitude: l.latitude,
          longitude: l.longitude, heat_score: l.heat_score || "cold",
          status: l.status, listIndex: i + 1,
        })));
      } else {
        setFetchError(`Failed (${res.status})`);
      }
    } catch (err) {
      console.error("Fetch leads failed:", err);
      setFetchError("Unable to connect");
    }
  }

  async function handleAction(entityId: number, targetStage: string) {
    if (targetStage === "ENGAGE") {
      onOpenDetails?.(entityId);
      return;
    }
    setActionId(entityId);
    try {
      const res = await fetch(`/api/proxy/leads/${entityId}/stage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: targetStage, force: targetStage === "ARCHIVED" }),
      });
      if (!res.ok && res.status === 422) {
        await fetch(`/api/proxy/leads/${entityId}/stage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ stage: targetStage, force: true }),
        });
      }
      await fetchLeads();
    } catch (err) {
      console.error("Action failed:", err);
    }
    setActionId(null);
  }

  function toggleStage(stage: string) {
    setCollapsedStages(prev => {
      const next = new Set(prev);
      if (next.has(stage)) next.delete(stage); else next.add(stage);
      return next;
    });
  }

  function fmt(val: number | null): string {
    if (val == null) return "";
    if (val >= 1_000_000) return `$${(val / 1_000_000).toFixed(1)}M`;
    if (val >= 1_000) return `$${(val / 1_000).toFixed(0)}K`;
    return `$${val}`;
  }

  // Group leads by stage
  const grouped: Record<string, Lead[]> = {};
  for (const stage of PIPELINE_STAGES) grouped[stage.key] = [];
  for (const lead of leads) {
    const key = lead.status || lead.pipeline_stage || "TARGET";
    if (grouped[key]) grouped[key].push(lead);
    else if (grouped["TARGET"]) grouped["TARGET"].push(lead);
  }

  return (
    <div className="flex flex-col h-full">
      {/* Search + filter bar */}
      <div className="space-y-2 mb-3">
        <input
          type="text" placeholder="Search properties..."
          value={search} onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && fetchLeads()}
          className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-blue-600 focus:outline-none"
        />
        <div className="flex gap-2">
          <select value={region} onChange={(e) => { setRegion(e.target.value); setTimeout(() => fetchLeads(), 0); }}
            className="flex-1 bg-gray-900 border border-gray-800 rounded px-2 py-1.5 text-xs text-white">
            <option value="">All Regions</option>
            {regions.map((r) => (
              <option key={r.id} value={String(r.id)}>{r.name}{r.target_county ? ` · ${r.target_county}` : ""}</option>
            ))}
          </select>
          <select value={county} onChange={(e) => { setCounty(e.target.value); setTimeout(() => fetchLeads(), 0); }}
            className="flex-1 bg-gray-900 border border-gray-800 rounded px-2 py-1.5 text-xs text-white">
            <option value="">All Counties</option>
            {TARGET_COUNTIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>

      {fetchError && (
        <div className="text-red-400 text-center py-2 bg-red-900/20 rounded mb-2 text-xs">
          {fetchError} <button onClick={fetchLeads} className="underline ml-1">Retry</button>
        </div>
      )}

      {/* Pipeline summary — 5 stage chips */}
      <div className="flex gap-1 mb-3">
        {PIPELINE_STAGES.filter(s => s.key !== "ARCHIVED").map((stage) => {
          const count = grouped[stage.key]?.length || 0;
          const isActive = activeStageFilter === stage.key;
          return (
            <button key={stage.key}
              onClick={() => {
                setActiveStageFilter(isActive ? "" : stage.key);
                toggleStage(stage.key);
              }}
              className={`flex-1 text-center py-1.5 rounded text-[10px] font-medium border transition-colors ${
                isActive ? `${stage.color} ${stage.bg} text-white ring-1 ring-white/20` :
                count > 0 ? `${stage.color} ${stage.bg} text-white` :
                "border-gray-800 bg-gray-900 text-gray-600"
              }`}>
              {count > 0 ? count.toLocaleString() : "–"}
              <span className="block text-[9px] text-gray-500">{stage.label}</span>
            </button>
          );
        })}
      </div>

      {/* Stage groups */}
      <div className="flex-1 overflow-y-auto space-y-1">
        {PIPELINE_STAGES.map((stage) => {
          const stageLeads = grouped[stage.key] || [];
          if (stageLeads.length === 0 && stage.key === "ARCHIVED") return null;
          if (activeStageFilter && activeStageFilter !== stage.key) return null;
          const collapsed = collapsedStages.has(stage.key);

          return (
            <div key={stage.key}>
              <button onClick={() => toggleStage(stage.key)}
                className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs border-l-2 ${stage.color} ${collapsed ? "bg-gray-900/50" : stage.bg}`}>
                <span className={`w-5 h-5 rounded flex items-center justify-center text-[10px] font-bold ${stage.badge}`}>
                  {stageLeads.length}
                </span>
                <span className="font-medium text-gray-300">{stage.label}</span>
                {stage.key === "TARGET" && <span className="text-gray-600 text-[10px] ml-1">awaiting Overpass</span>}
                {stage.key === "LEAD" && <span className="text-gray-600 text-[10px] ml-1">enriching</span>}
                <span className="text-gray-600 ml-auto">{collapsed ? "+" : "–"}</span>
              </button>

              {!collapsed && stageLeads.length > 0 && (
                <div className="space-y-1 py-1">
                  {stageLeads.slice(0, 100).map((lead) => {
                    const isSelected = lead.id === selectedLeadId;
                    const chars = lead.characteristics || {};
                    const heat = lead.heat_score || "cold";
                    return (
                      <div key={lead.id}
                        onMouseEnter={() => onLeadHover?.(lead.id)}
                        onMouseLeave={() => onLeadHover?.(null)}
                        className={`rounded-lg border overflow-hidden transition-colors cursor-pointer ${
                          isSelected ? "border-blue-500 bg-gray-900" : "border-gray-800/50 bg-gray-900/60 hover:border-gray-700"
                        }`}
                        onClick={() => onOpenDetails?.(lead.id)}>
                        <div className="px-3 py-2">
                          <div className="flex items-center justify-between mb-0.5">
                            <h3 className="font-medium text-sm text-white truncate mr-2">{lead.name}</h3>
                            {stage.key !== "TARGET" && (
                              <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${HEAT_COLORS[heat] || HEAT_COLORS.cold}`}>
                                {heat}
                              </span>
                            )}
                          </div>
                          <p className="text-gray-500 text-[11px] truncate">{lead.address}</p>
                          <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                            {!!chars.dor_use_description && (
                              <span className="text-[10px] px-1 rounded bg-gray-800 text-gray-400">{String(chars.dor_use_description)}</span>
                            )}
                            {!!chars.dor_construction_class && (
                              <span className="text-[10px] px-1 rounded bg-gray-800 text-gray-500">{String(chars.dor_construction_class)}</span>
                            )}
                            {!!chars.dor_num_units && (
                              <span className="text-gray-600 text-[10px]">{String(chars.dor_num_units)} units</span>
                            )}
                            {lead.tiv_parsed != null && (
                              <span className="text-gray-500 text-[10px]">{fmt(lead.tiv_parsed)}</span>
                            )}
                            {!!chars.flood_zone && (
                              <span className={`text-[10px] px-1 rounded ${
                                String(chars.flood_risk) === "extreme" || String(chars.flood_risk) === "high"
                                  ? "bg-red-900/50 text-red-400" : "bg-gray-800 text-gray-500"
                              }`}>{String(chars.flood_zone)}</span>
                            )}
                            {!!chars.on_citizens && (
                              <span className="text-[10px] px-1 rounded bg-amber-900/50 text-amber-400">Citizens</span>
                            )}
                            <span className="text-gray-700 text-[10px]">{lead.county}</span>
                          </div>

                          {/* Enrichment status for LEADs */}
                          {stage.key === "LEAD" && lead.enrichment_status && (
                            <div className="mt-1">
                              <div className="flex items-center gap-1 text-[10px]">
                                <span className={`w-1.5 h-1.5 rounded-full ${
                                  lead.enrichment_status === "complete" ? "bg-green-500" :
                                  lead.enrichment_status === "running" ? "bg-blue-500 animate-pulse" :
                                  lead.enrichment_status === "error" ? "bg-red-500" : "bg-gray-600"
                                }`} />
                                <span className="text-gray-600">{lead.enrichment_status}</span>
                              </div>
                            </div>
                          )}

                          {/* Actions */}
                          <div className="flex gap-1 mt-2" onClick={(e) => e.stopPropagation()}>
                            {stage.key === "LEAD" && (
                              <button onClick={() => handleAction(lead.id, "OPPORTUNITY")}
                                disabled={actionId === lead.id}
                                className="flex-1 disabled:opacity-50 text-white text-xs py-2 md:py-1 rounded font-medium bg-blue-700 hover:bg-blue-600">
                                {actionId === lead.id ? "..." : "Promote"}
                              </button>
                            )}
                            {stage.key === "OPPORTUNITY" && (
                              <button onClick={() => onOpenDetails?.(lead.id)}
                                className="flex-1 text-white text-xs py-2 md:py-1 rounded font-medium bg-green-700 hover:bg-green-600">
                                Engage
                              </button>
                            )}

                            {/* Demote */}
                            {stage.prev && (
                              <button onClick={() => handleAction(lead.id, stage.prev)}
                                disabled={actionId === lead.id}
                                className="bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-gray-500 text-xs py-2 md:py-1 px-2 rounded"
                                title={`Back to ${stage.prev}`}>&larr;</button>
                            )}

                            {/* Map */}
                            {lead.latitude != null && (
                              <button onClick={() => onFlyTo?.(lead.latitude, lead.longitude, lead.id)}
                                className="bg-gray-800 hover:bg-gray-700 text-gray-500 text-xs py-2 md:py-1 px-2 rounded" title="Map">
                                Map
                              </button>
                            )}

                            {/* Archive */}
                            {stage.key !== "CUSTOMER" && stage.key !== "ARCHIVED" && (
                              <button onClick={() => handleAction(lead.id, "ARCHIVED")}
                                disabled={actionId === lead.id}
                                className="bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-gray-600 text-xs py-2 md:py-1 px-2 rounded"
                                title="Archive">&times;</button>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                  {stageLeads.length > 100 && (
                    <p className="text-gray-600 text-xs text-center py-2">
                      Showing 100 of {stageLeads.length.toLocaleString()} — use filters to narrow
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
