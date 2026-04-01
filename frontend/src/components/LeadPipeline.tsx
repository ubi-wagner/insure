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

interface Filters {
  search: string;
  county: string;
  carrier: string;
  status_filter: string;
  heat: string;
  min_tiv: string;
  max_tiv: string;
  min_premium: string;
  max_premium: string;
}

const EMPTY_FILTERS: Filters = {
  search: "", county: "", carrier: "", status_filter: "",
  heat: "", min_tiv: "", max_tiv: "", min_premium: "", max_premium: "",
};

type SortBy = "date" | "coast_distance" | "wind_ratio" | "premium" | "tiv";

const HEAT_COLORS: Record<string, string> = {
  hot: "bg-red-600 text-white",
  warm: "bg-orange-600 text-white",
  cool: "bg-blue-600 text-white",
  none: "bg-gray-700 text-gray-400",
};

interface PipelineProps {
  refreshKey: number;
  onLeadsLoaded?: (leads: { id: number; name: string; latitude: number; longitude: number; heat_score: string; status: string }[]) => void;
  onLeadHover?: (id: number | null) => void;
  onFlyTo?: (lat: number, lng: number) => void;
}

export default function LeadPipeline({ refreshKey, onLeadsLoaded, onLeadHover, onFlyTo }: PipelineProps) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [sortBy, setSortBy] = useState<SortBy>("date");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [votingId, setVotingId] = useState<number | null>(null);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [showFilters, setShowFilters] = useState(false);

  useEffect(() => {
    fetchLeads();
  }, [refreshKey, sortBy]);

  function buildQueryString(): string {
    const params = new URLSearchParams({ sort_by: sortBy });
    if (filters.search) params.set("search", filters.search);
    if (filters.county) params.set("county", filters.county);
    if (filters.carrier) params.set("carrier", filters.carrier);
    if (filters.status_filter) params.set("status_filter", filters.status_filter);
    if (filters.heat) params.set("heat", filters.heat);
    if (filters.min_tiv) params.set("min_tiv", filters.min_tiv);
    if (filters.max_tiv) params.set("max_tiv", filters.max_tiv);
    if (filters.min_premium) params.set("min_premium", filters.min_premium);
    if (filters.max_premium) params.set("max_premium", filters.max_premium);
    return params.toString();
  }

  async function fetchLeads() {
    setFetchError(null);
    try {
      const res = await fetch(`/api/proxy/leads?${buildQueryString()}`);
      if (res.ok) {
        const data = await res.json();
        setLeads(data);
        onLeadsLoaded?.(data.map((l: Lead) => ({
          id: l.id, name: l.name, latitude: l.latitude,
          longitude: l.longitude, heat_score: l.heat_score, status: l.status,
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
    // fetchLeads will be called by the useEffect when state settles
    setTimeout(fetchLeads, 0);
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
      fetchLeads();
    } catch (err) {
      console.error("Vote failed:", err);
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
    setTimeout(fetchLeads, 50);
  }

  function getStatusBadge(status: string) {
    switch (status) {
      case "CANDIDATE":
        return <span className="bg-green-700 text-green-100 text-xs px-2 py-0.5 rounded-full">Candidate</span>;
      case "REJECTED":
        return <span className="bg-red-900 text-red-200 text-xs px-2 py-0.5 rounded-full">Rejected</span>;
      default:
        return <span className="bg-gray-700 text-gray-300 text-xs px-2 py-0.5 rounded-full">New</span>;
    }
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
            <input
              type="text"
              placeholder="County"
              value={filters.county}
              onChange={(e) => setFilters({ ...filters, county: e.target.value })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white"
            />
            <input
              type="text"
              placeholder="Carrier"
              value={filters.carrier}
              onChange={(e) => setFilters({ ...filters, carrier: e.target.value })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white"
            />
          </div>
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
          <div className="flex gap-2">
            <select value={filters.status_filter}
              onChange={(e) => setFilters({ ...filters, status_filter: e.target.value })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white flex-1">
              <option value="">All Status</option>
              <option value="NEW">New</option>
              <option value="CANDIDATE">Candidate</option>
              <option value="REJECTED">Rejected</option>
            </select>
            <select value={filters.heat}
              onChange={(e) => setFilters({ ...filters, heat: e.target.value })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white flex-1">
              <option value="">All Heat</option>
              <option value="hot">Hot</option>
              <option value="warm">Warm</option>
              <option value="cool">Cool</option>
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

      {/* Count */}
      {leads.length > 0 && (
        <p className="text-gray-600 text-xs mb-2">{leads.length} lead{leads.length !== 1 ? "s" : ""}</p>
      )}

      {/* Empty state */}
      {!fetchError && leads.length === 0 && (
        <div className="text-gray-500 text-center py-12 text-sm">
          No leads found. Draw a region on the map to start hunting.
        </div>
      )}

      {/* Lead cards */}
      <div className="space-y-3">
        {leads.map((lead) => (
          <div
            key={lead.id}
            onClick={() => setSelectedLead(lead)}
            onMouseEnter={() => onLeadHover?.(lead.id)}
            onMouseLeave={() => onLeadHover?.(null)}
            className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden cursor-pointer hover:border-gray-600 transition-colors"
          >
            <div className="p-3">
              <div className="flex items-start justify-between mb-1.5">
                <h3 className="font-semibold text-sm leading-tight flex-1 mr-2">{lead.name}</h3>
                <div className="flex gap-1 shrink-0">
                  {getHeatBadge(lead.heat_score, lead.wind_ratio)}
                  {getStatusBadge(lead.status)}
                </div>
              </div>
              <p className="text-gray-400 text-xs">{lead.address}</p>
              <p className="text-gray-600 text-xs mb-2">{lead.county} County</p>

              {/* Key metrics row */}
              {(lead.tiv_parsed || lead.premium_parsed || lead.wind_ratio !== null) && (
                <div className="flex gap-3 text-xs mb-2 bg-gray-800/50 rounded px-2 py-1.5">
                  {lead.tiv_parsed && (
                    <div>
                      <span className="text-gray-500">TIV </span>
                      <span className="text-white">{formatDollar(lead.tiv_parsed)}</span>
                    </div>
                  )}
                  {lead.premium_parsed && (
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

              {!!lead.characteristics?.carrier && (
                <p className="text-xs text-gray-500 mb-2">
                  {String(lead.characteristics.carrier)}
                  {!!lead.characteristics.expiration && <> · Exp {String(lead.characteristics.expiration)}</>}
                </p>
              )}

              <div className="flex gap-1.5">
                <button
                  onClick={(e) => { e.stopPropagation(); handleVote(lead.id, "USER_THUMB_UP"); }}
                  disabled={votingId === lead.id || lead.status === "CANDIDATE"}
                  className="flex-1 bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white text-xs py-1.5 rounded"
                >
                  Hunt
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); handleVote(lead.id, "USER_THUMB_DOWN"); }}
                  disabled={votingId === lead.id || lead.status === "REJECTED"}
                  className="flex-1 bg-red-900 hover:bg-red-800 disabled:opacity-50 text-white text-xs py-1.5 rounded"
                >
                  Reject
                </button>
                {lead.latitude && lead.longitude && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onFlyTo?.(lead.latitude, lead.longitude); }}
                    className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs py-1.5 px-2 rounded"
                    title="Show on map"
                  >
                    Map
                  </button>
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); handleFindSimilar(lead); }}
                  className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs py-1.5 px-2 rounded"
                  title="Find similar properties"
                >
                  Similar
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Detail modal */}
      {selectedLead && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" onClick={() => setSelectedLead(null)}>
          <div className="bg-gray-900 rounded-xl border border-gray-700 max-w-2xl w-full max-h-[80vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-4">
              <div>
                <h2 className="text-xl font-bold">{selectedLead.name}</h2>
                <div className="flex gap-2 mt-1">
                  {getHeatBadge(selectedLead.heat_score, selectedLead.wind_ratio)}
                  {getStatusBadge(selectedLead.status)}
                </div>
              </div>
              <button onClick={() => setSelectedLead(null)} className="text-gray-400 hover:text-white text-xl">&times;</button>
            </div>
            <p className="text-gray-400 text-sm mb-1">{selectedLead.address}</p>
            <p className="text-gray-500 text-sm mb-4">{selectedLead.county} County</p>

            {/* Key metrics */}
            {(selectedLead.tiv_parsed || selectedLead.premium_parsed) && (
              <div className="grid grid-cols-3 gap-3 mb-4">
                <div className="bg-gray-800 rounded-lg p-3 text-center">
                  <p className="text-gray-500 text-xs">TIV</p>
                  <p className="text-white font-semibold">{formatDollar(selectedLead.tiv_parsed)}</p>
                </div>
                <div className="bg-gray-800 rounded-lg p-3 text-center">
                  <p className="text-gray-500 text-xs">Premium</p>
                  <p className="text-white font-semibold">{formatDollar(selectedLead.premium_parsed)}</p>
                </div>
                <div className="bg-gray-800 rounded-lg p-3 text-center">
                  <p className="text-gray-500 text-xs">Wind Ratio</p>
                  <p className={`font-semibold ${selectedLead.heat_score === "hot" ? "text-red-400" : "text-white"}`}>
                    {selectedLead.wind_ratio !== null ? `${selectedLead.wind_ratio.toFixed(2)}%` : "—"}
                  </p>
                </div>
              </div>
            )}

            {selectedLead.characteristics && Object.keys(selectedLead.characteristics).length > 0 && (
              <div className="mb-4">
                <h3 className="text-sm font-semibold text-gray-300 mb-2">Insurance Intelligence</h3>
                <pre className="bg-gray-800 rounded p-3 text-xs text-gray-300 overflow-x-auto">
                  {JSON.stringify(selectedLead.characteristics, null, 2)}
                </pre>
              </div>
            )}

            {!!selectedLead.emails && (
              <div>
                <h3 className="text-sm font-semibold text-gray-300 mb-2">Generated Emails</h3>
                {Object.entries(selectedLead.emails).map(([style, email]) => (
                  <div key={style} className="mb-3 bg-gray-800 rounded p-3">
                    <p className="text-blue-400 text-xs font-semibold uppercase mb-1">{style}</p>
                    <pre className="text-xs text-gray-300 whitespace-pre-wrap">{typeof email === "object" ? JSON.stringify(email, null, 2) : String(email)}</pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
