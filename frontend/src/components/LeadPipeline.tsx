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
  emails?: Record<string, string> | null;
  wind_ratio: number | null;
  heat_score: string;
  premium_parsed: number | null;
  tiv_parsed: number | null;
}

interface Region {
  id: number;
  name: string;
  bounding_box: { north: number; south: number; east: number; west: number };
  target_county: string | null;
  status: string;
}

interface Filters {
  search: string;
  county: string;
  region: string;
  carrier: string;
  status_filter: string;
  heat: string;
  construction: string;
  min_tiv: string;
  max_tiv: string;
  min_premium: string;
  max_premium: string;
}

const EMPTY_FILTERS: Filters = {
  search: "", county: "", region: "", carrier: "", status_filter: "active",
  heat: "", construction: "", min_tiv: "", max_tiv: "", min_premium: "", max_premium: "",
};

const TARGET_COUNTIES = [
  "Pasco", "Pinellas", "Hillsborough", "Manatee", "Sarasota",
  "Charlotte", "Lee", "Collier", "Palm Beach", "Miami-Dade", "Broward",
];

type SortBy = "date" | "coast_distance" | "wind_ratio" | "premium" | "tiv";

const HEAT_COLORS: Record<string, string> = {
  hot: "bg-red-600 text-white",
  warm: "bg-orange-600 text-white",
  cool: "bg-blue-600 text-white",
  none: "bg-gray-700 text-gray-400",
};

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
  const [totalFetched, setTotalFetched] = useState(0);
  const [sortBy, setSortBy] = useState<SortBy>("date");
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [votingId, setVotingId] = useState<number | null>(null);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [showFilters, setShowFilters] = useState(false);
  const [regions, setRegions] = useState<Region[]>([]);

  useEffect(() => {
    fetchLeads();
    fetchRegions();
  }, [refreshKey, sortBy]);

  async function fetchRegions() {
    try {
      const res = await fetch("/api/proxy/regions");
      if (res.ok) setRegions(await res.json());
    } catch {}
  }

  function buildQueryString(): string {
    const params = new URLSearchParams({ sort_by: sortBy });
    if (filters.search) params.set("search", filters.search);
    if (filters.county) params.set("county", filters.county);
    if (filters.carrier) params.set("carrier", filters.carrier);
    // "active" is client-side — don't send to API
    if (filters.status_filter && filters.status_filter !== "active") params.set("status_filter", filters.status_filter);
    if (filters.heat) params.set("heat", filters.heat);
    if (filters.min_tiv) params.set("min_tiv", filters.min_tiv);
    if (filters.max_tiv) params.set("max_tiv", filters.max_tiv);
    if (filters.min_premium) params.set("min_premium", filters.min_premium);
    if (filters.max_premium) params.set("max_premium", filters.max_premium);
    if (filters.construction) params.set("construction", filters.construction);
    return params.toString();
  }

  async function fetchLeads() {
    setFetchError(null);
    try {
      const res = await fetch(`/api/proxy/leads?${buildQueryString()}`);
      if (res.ok) {
        const allData: Lead[] = await res.json();
        setTotalFetched(allData.length);
        let data = [...allData];

        // Client-side: filter out archived/churned when "active" is selected
        if (filters.status_filter === "active") {
          data = data.filter((l) => !["ARCHIVED", "CHURNED", "REJECTED"].includes(l.status));
        }

        // Client-side filter by region bounding box
        if (filters.region) {
          const region = regions.find((r) => String(r.id) === filters.region);
          if (region?.bounding_box) {
            const bb = region.bounding_box;
            data = data.filter((l) =>
              l.latitude >= bb.south && l.latitude <= bb.north &&
              l.longitude >= bb.west && l.longitude <= bb.east
            );
          }
        }

        setLeads(data);
        onLeadsLoaded?.(data.map((l: Lead, i: number) => ({
          id: l.id, name: l.name, latitude: l.latitude,
          longitude: l.longitude, heat_score: l.heat_score, status: l.status,
          listIndex: i + 1,
        })));
      } else {
        setFetchError(`Failed to load leads (${res.status})`);
      }
    } catch (err) {
      console.error("Failed to fetch leads:", err);
      setFetchError("Unable to connect to API");
    }
  }

  function applyFilters() {
    fetchLeads();
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
    setTimeout(() => { fetchLeads().catch(console.error); }, 0);
  }

  async function handleVote(entityId: number, action: "USER_THUMB_UP" | "USER_THUMB_DOWN") {
    setVotingId(entityId);
    try {
      const res = await fetch(`/api/proxy/leads/${entityId}/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_type: action }),
      });
      if (!res.ok) {
        console.error("Vote failed:", await res.json().catch(() => ({})));
      }
      await fetchLeads();
    } catch (err) {
      console.error("Vote failed:", err);
    }
    setVotingId(null);
  }

  async function handleAdvanceStage(entityId: number, newStage: string) {
    setVotingId(entityId);
    try {
      const res = await fetch(`/api/proxy/leads/${entityId}/stage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: newStage, force: false }),
      });
      if (!res.ok && res.status === 422) {
        // Force advance if readiness fails
        await fetch(`/api/proxy/leads/${entityId}/stage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ stage: newStage, force: true }),
        });
      }
      await fetchLeads();
    } catch (err) {
      console.error("Stage change failed:", err);
    }
    setVotingId(null);
  }

  function handleFindSimilar(lead: Lead) {
    const chars = lead.characteristics || {};
    setFilters({
      ...EMPTY_FILTERS,
      county: lead.county || "",
      carrier: chars.carrier ? String(chars.carrier) : "",
    });
    setShowFilters(true);
    setTimeout(() => { fetchLeads().catch(console.error); }, 50);
  }

  const STAGE_BADGE: Record<string, string> = {
    NEW: "bg-gray-700 text-gray-300",
    CANDIDATE: "bg-purple-900 text-purple-200",
    TARGET: "bg-amber-900 text-amber-200",
    OPPORTUNITY: "bg-blue-900 text-blue-200",
    CUSTOMER: "bg-green-800 text-green-200",
    CHURNED: "bg-gray-800 text-gray-400",
    ARCHIVED: "bg-red-900 text-red-300",
  };

  function getStatusBadge(status: string) {
    const cls = STAGE_BADGE[status] || STAGE_BADGE.NEW;
    return <span className={`${cls} text-[10px] px-1.5 py-0.5 rounded-full`}>{status}</span>;
  }

  function getHeatBadge(score: string, ratio: number | null) {
    const label = ratio !== null ? `${score} ${ratio.toFixed(2)}%` : score;
    return (
      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase ${HEAT_COLORS[score] || HEAT_COLORS.none}`}>
        {label}
      </span>
    );
  }

  function formatDollar(val: number | null): string {
    if (val === null) return "—";
    return "$" + val.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }

  const activeFilterCount = Object.values(filters).filter(Boolean).length;

  return (
    <div>
      {/* Sort + Filter controls */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="text-gray-500 text-xs">Sort:</span>
        {(["date", "coast_distance", "wind_ratio", "premium", "tiv"] as SortBy[]).map((s) => (
          <button
            key={s}
            onClick={() => setSortBy(s)}
            className={`text-xs px-2 py-1 rounded ${sortBy === s ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-500"}`}
          >
            {s === "wind_ratio" ? "Wind %" : s === "coast_distance" ? "Coast" : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`text-xs px-2 py-1 rounded ml-auto ${showFilters ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400"}`}
        >
          Filters {activeFilterCount > 0 && `(${activeFilterCount})`}
        </button>
      </div>

      {/* Filter panel */}
      {showFilters && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 mb-3 space-y-2">
          <input
            type="text"
            placeholder="Search name or address..."
            value={filters.search}
            onChange={(e) => setFilters({ ...filters, search: e.target.value })}
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white"
          />
          <div className="grid grid-cols-2 gap-2">
            <select value={filters.region}
              onChange={(e) => setFilters({ ...filters, region: e.target.value })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white">
              <option value="">All Regions</option>
              {regions.map((r) => (
                <option key={r.id} value={String(r.id)}>
                  {r.name}{r.target_county ? ` (${r.target_county})` : ""}
                </option>
              ))}
            </select>
            <select value={filters.county}
              onChange={(e) => setFilters({ ...filters, county: e.target.value })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white">
              <option value="">All Counties</option>
              {TARGET_COUNTIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <input
            type="text"
            placeholder="Carrier"
            value={filters.carrier}
            onChange={(e) => setFilters({ ...filters, carrier: e.target.value })}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white"
          />
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-gray-600 text-[10px]">TIV Range</label>
              <div className="flex gap-1">
                <input type="number" placeholder="Min" value={filters.min_tiv}
                  onChange={(e) => setFilters({ ...filters, min_tiv: e.target.value })}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white" />
                <input type="number" placeholder="Max" value={filters.max_tiv}
                  onChange={(e) => setFilters({ ...filters, max_tiv: e.target.value })}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white" />
              </div>
            </div>
            <div>
              <label className="text-gray-600 text-[10px]">Premium Range</label>
              <div className="flex gap-1">
                <input type="number" placeholder="Min" value={filters.min_premium}
                  onChange={(e) => setFilters({ ...filters, min_premium: e.target.value })}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white" />
                <input type="number" placeholder="Max" value={filters.max_premium}
                  onChange={(e) => setFilters({ ...filters, max_premium: e.target.value })}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white" />
              </div>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <select value={filters.status_filter}
              onChange={(e) => setFilters({ ...filters, status_filter: e.target.value })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white">
              <option value="active">Active Pipeline</option>
              <option value="">All (incl. archived)</option>
              <option value="NEW">New</option>
              <option value="CANDIDATE">Candidate</option>
              <option value="TARGET">Target</option>
              <option value="OPPORTUNITY">Opportunity</option>
              <option value="CUSTOMER">Customer</option>
            </select>
            <select value={filters.heat}
              onChange={(e) => setFilters({ ...filters, heat: e.target.value })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white">
              <option value="">All Heat</option>
              <option value="hot">Hot</option>
              <option value="warm">Warm</option>
              <option value="cool">Cool</option>
            </select>
            <select value={filters.construction}
              onChange={(e) => setFilters({ ...filters, construction: e.target.value })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white">
              <option value="">All Construction</option>
              <option value="fire_resistive">Fire Resistive</option>
              <option value="non_combustible">Non-Combustible+</option>
              <option value="masonry">Masonry+</option>
              <option value="frame">Frame</option>
            </select>
          </div>
          <div className="flex gap-2">
            <button onClick={applyFilters}
              className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-xs py-1.5 rounded font-medium">
              Apply
            </button>
            <button onClick={clearFilters}
              className="flex-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs py-1.5 rounded">
              Clear
            </button>
          </div>
        </div>
      )}

      {/* Error state */}
      {fetchError && (
        <div className="text-red-400 text-center py-4 bg-red-900/20 rounded-lg mb-3 text-xs">
          {fetchError}
          <button onClick={fetchLeads} className="ml-2 underline text-red-300">Retry</button>
        </div>
      )}

      {/* Count + stage summary */}
      {totalFetched > 0 && (
        <div className="mb-2">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-gray-500">
              {leads.length === totalFetched
                ? `${leads.length} lead${leads.length !== 1 ? "s" : ""}`
                : `${leads.length} of ${totalFetched} leads (filtered)`
              }
            </span>
            {leads.length > 0 && (
              <div className="flex gap-1 ml-auto">
                {Object.entries(
                  leads.reduce((acc, l) => { acc[l.status] = (acc[l.status] || 0) + 1; return acc; }, {} as Record<string, number>)
                ).map(([stage, count]) => (
                  <span key={stage} className={`px-1.5 py-0.5 rounded text-[10px] ${STAGE_BADGE[stage] || STAGE_BADGE.NEW}`}>
                    {count} {stage.toLowerCase()}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!fetchError && leads.length === 0 && (
        <div className="text-gray-500 text-center py-12 text-sm">
          No leads found. Draw a region on the map to start hunting.
        </div>
      )}

      {/* Lead cards */}
      <div className="space-y-3">
        {leads.map((lead, idx) => {
          const num = idx + 1;
          const isSelected = lead.id === selectedLeadId;
          return (
          <div
            key={lead.id}
            id={`lead-card-${lead.id}`}
            onMouseEnter={() => onLeadHover?.(lead.id)}
            onMouseLeave={() => onLeadHover?.(null)}
            className={`bg-gray-900 rounded-lg border overflow-hidden transition-colors ${
              isSelected ? "border-blue-500 ring-1 ring-blue-500/50" : "border-gray-800 hover:border-gray-600"
            }`}
          >
            <div className="p-3">
              <div className="flex items-start justify-between mb-1.5">
                <div className="flex items-start gap-2 flex-1 mr-2">
                  <span className="bg-gray-800 text-gray-400 text-[10px] font-bold w-5 h-5 rounded flex items-center justify-center shrink-0 mt-0.5">
                    {num}
                  </span>
                  <h3 className="font-semibold text-sm leading-tight">{lead.name}</h3>
                </div>
                <div className="flex gap-1 shrink-0">
                  {getHeatBadge(lead.heat_score, lead.wind_ratio)}
                  {getStatusBadge(lead.status)}
                </div>
              </div>
              <p className="text-gray-400 text-xs">{lead.address}</p>
              <p className="text-gray-600 text-xs mb-2">{lead.county} County</p>

              {/* Key metrics row */}
              {(lead.tiv_parsed != null || lead.premium_parsed != null || lead.wind_ratio !== null) && (
                <div className="flex gap-3 text-xs mb-2 bg-gray-800/50 rounded px-2 py-1.5">
                  {lead.tiv_parsed != null && (
                    <div>
                      <span className="text-gray-500">TIV </span>
                      <span className="text-white">{formatDollar(lead.tiv_parsed)}</span>
                    </div>
                  )}
                  {lead.premium_parsed != null && (
                    <div>
                      <span className="text-gray-500">Prem </span>
                      <span className="text-white">{formatDollar(lead.premium_parsed)}</span>
                    </div>
                  )}
                  {lead.wind_ratio !== null && (
                    <div>
                      <span className="text-gray-500">Wind </span>
                      <span className={lead.heat_score === "hot" ? "text-red-400 font-medium" : "text-white"}>
                        {lead.wind_ratio.toFixed(2)}%
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* Construction & building info */}
              {!!(lead.characteristics?.construction_class || lead.characteristics?.stories) && (
                <div className="flex gap-2 text-xs mb-2 flex-wrap">
                  {!!lead.characteristics?.construction_class && (
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      String(lead.characteristics.construction_class).includes("Fire Resistive") ? "bg-emerald-900 text-emerald-300" :
                      String(lead.characteristics.construction_class).includes("Non-Combustible") ? "bg-sky-900 text-sky-300" :
                      String(lead.characteristics.construction_class).includes("Masonry") ? "bg-amber-900 text-amber-300" :
                      String(lead.characteristics.construction_class).includes("Frame") ? "bg-red-900 text-red-300" :
                      "bg-gray-800 text-gray-400"
                    }`}>
                      {String(lead.characteristics.construction_class)}
                    </span>
                  )}
                  {!!lead.characteristics?.stories && (
                    <span className="text-gray-500">{String(lead.characteristics.stories)} stories</span>
                  )}
                  {!!lead.characteristics?.units_estimate && (
                    <span className="text-gray-500">~{String(lead.characteristics.units_estimate)} units</span>
                  )}
                  {!!lead.characteristics?.flood_zone && (
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      String(lead.characteristics.flood_risk) === "extreme" ? "bg-red-900 text-red-300" :
                      String(lead.characteristics.flood_risk) === "high" ? "bg-orange-900 text-orange-300" :
                      String(lead.characteristics.flood_risk) === "moderate_high" ? "bg-amber-900 text-amber-300" :
                      "bg-green-900 text-green-300"
                    }`}>
                      {String(lead.characteristics.flood_zone)}
                    </span>
                  )}
                </div>
              )}

              {!!lead.characteristics?.carrier && (
                <p className="text-xs text-gray-500 mb-2">
                  {String(lead.characteristics.carrier)}
                  {!!lead.characteristics.expiration && <> · Exp {String(lead.characteristics.expiration)}</>}
                </p>
              )}

              {/* Stage-aware actions */}
              <div className="flex gap-1.5">
                {/* Primary action — stage-dependent */}
                {lead.status === "NEW" && (
                  <button
                    onClick={(e) => { e.stopPropagation(); handleVote(lead.id, "USER_THUMB_UP"); }}
                    disabled={votingId === lead.id}
                    className="flex-1 bg-purple-700 hover:bg-purple-600 disabled:opacity-50 text-white text-xs py-1.5 rounded"
                  >
                    Investigate
                  </button>
                )}
                {lead.status === "CANDIDATE" && (
                  <button
                    onClick={(e) => { e.stopPropagation(); handleAdvanceStage(lead.id, "TARGET"); }}
                    disabled={votingId === lead.id}
                    className="flex-1 bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-xs py-1.5 rounded"
                  >
                    Target
                  </button>
                )}
                {lead.status === "TARGET" && (
                  <button
                    onClick={(e) => { e.stopPropagation(); handleAdvanceStage(lead.id, "OPPORTUNITY"); }}
                    disabled={votingId === lead.id}
                    className="flex-1 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white text-xs py-1.5 rounded"
                  >
                    Opportunity
                  </button>
                )}
                {lead.status === "OPPORTUNITY" && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onOpenDetails?.(lead.id); }}
                    className="flex-1 bg-green-700 hover:bg-green-600 text-white text-xs py-1.5 rounded"
                  >
                    Engage
                  </button>
                )}

                {/* Archive — only for non-customer pre-opportunity stages */}
                {["NEW", "CANDIDATE", "TARGET"].includes(lead.status) && (
                  <button
                    onClick={(e) => { e.stopPropagation(); handleAdvanceStage(lead.id, "ARCHIVED"); }}
                    disabled={votingId === lead.id}
                    className="bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-gray-500 text-xs py-1.5 px-2 rounded"
                    title="Archive"
                  >
                    &times;
                  </button>
                )}

                {/* Map — always available */}
                {lead.latitude != null && lead.longitude != null && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onFlyTo?.(lead.latitude, lead.longitude, lead.id); }}
                    className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs py-1.5 px-2 rounded"
                    title="Show on map"
                  >
                    Map
                  </button>
                )}

                {/* Details — always available */}
                <button
                  onClick={(e) => { e.stopPropagation(); onOpenDetails?.(lead.id); }}
                  className="bg-blue-900 hover:bg-blue-800 text-blue-300 text-xs py-1.5 px-2 rounded"
                  title="View details"
                >
                  View
                </button>
              </div>
            </div>
          </div>
          );
        })}
      </div>

    </div>
  );
}
