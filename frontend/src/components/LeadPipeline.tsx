"use client";

import { useEffect, useState, useCallback, useRef } from "react";

interface Lead {
  id: number;
  name: string;
  address: string;
  county: string;
  latitude: number | null;
  longitude: number | null;
  characteristics: Record<string, unknown> | null;
  created_at: string | null;
  status: string;
  pipeline_stage: string;
  wind_ratio: number | null;
  heat_score: string | null;
  premium_parsed: number | null;
  tiv_parsed: number | null;
  enrichment_status?: string;
}

interface ApiResponse {
  results: Lead[];
  total: number;
  limit: number;
  offset: number;
}

const PIPELINE_STAGES = [
  { key: "TARGET", label: "Targets", color: "border-gray-600", bg: "bg-gray-800", textColor: "text-gray-300" },
  { key: "LEAD", label: "Leads", color: "border-cyan-600", bg: "bg-cyan-950/30", textColor: "text-cyan-300" },
  { key: "OPPORTUNITY", label: "Opps", color: "border-amber-600", bg: "bg-amber-950/30", textColor: "text-amber-300" },
  { key: "CUSTOMER", label: "Customers", color: "border-green-600", bg: "bg-green-950/30", textColor: "text-green-300" },
  { key: "ARCHIVED", label: "Archived", color: "border-gray-700", bg: "bg-gray-900", textColor: "text-gray-500" },
] as const;

const HEAT_COLORS: Record<string, string> = {
  hot: "bg-red-600 text-white",
  warm: "bg-orange-600 text-white",
  cold: "bg-gray-700 text-gray-400",
};

const TARGET_COUNTIES = [
  "Pasco", "Pinellas", "Hillsborough", "Manatee", "Sarasota",
  "Charlotte", "Lee", "Collier", "Palm Beach", "Miami-Dade", "Broward",
];

const SORT_OPTIONS = [
  { value: "cream-desc", label: "Best Opportunity" },
  { value: "value-desc", label: "Value (High-Low)" },
  { value: "value-asc", label: "Value (Low-High)" },
  { value: "stories-desc", label: "Stories (Most)" },
  { value: "units-desc", label: "Units (Most)" },
  { value: "year_built-desc", label: "Newest Built" },
  { value: "year_built-asc", label: "Oldest Built" },
  { value: "name-asc", label: "Name A-Z" },
  { value: "date-desc", label: "Newest Added" },
];

const CREAM_TIERS = [
  { value: "", label: "All Tiers" },
  { value: "platinum", label: "Platinum (90+)" },
  { value: "gold", label: "Gold (70-89)" },
  { value: "silver", label: "Silver (50-69)" },
  { value: "bronze", label: "Bronze (30-49)" },
];

const USE_CODE_OPTIONS = [
  { value: "", label: "All Types" },
  { value: "004", label: "004 - Condominium" },
  { value: "005", label: "005 - Co-op" },
  { value: "006", label: "006 - Retirement Home" },
  { value: "008", label: "008 - Multi-Family 10+" },
  { value: "039", label: "039 - Hotel/Motel" },
];

interface PipelineProps {
  refreshKey: number;
  onLeadsLoaded?: (leads: { id: number; name: string; latitude: number; longitude: number; heat_score: string; status: string; listIndex: number }[]) => void;
  onLeadHover?: (id: number | null) => void;
  selectedLeadId?: number | null;
  switchToStage?: string | null;
  onFlyTo?: (lat: number, lng: number, id: number) => void;
  onOpenDetails?: (id: number) => void;
  initialCounty?: string | null;
}

export default function LeadPipeline({ refreshKey, onLeadsLoaded, onLeadHover, selectedLeadId, switchToStage, onFlyTo, onOpenDetails, initialCounty }: PipelineProps) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Stage counts (fetched separately for all stages)
  const [stageCounts, setStageCounts] = useState<Record<string, number>>({});

  // Filters
  const [activeStage, setActiveStage] = useState("TARGET");
  const [search, setSearch] = useState("");
  const [county, setCounty] = useState(initialCounty ?? "");
  const [sortKey, setSortKey] = useState("value-desc");
  const [minValue, setMinValue] = useState("");
  const [maxValue, setMaxValue] = useState("");
  const [minUnits, setMinUnits] = useState("");
  const [minStories, setMinStories] = useState("");
  const [useCode, setUseCode] = useState("");
  const [heatFilter, setHeatFilter] = useState("");
  const [citizensOnly, setCitizensOnly] = useState(false);
  const [creamTier, setCreamTier] = useState("");
  const [showFilters, setShowFilters] = useState(false);

  // Pagination
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 50;

  // Bulk select
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [selectMode, setSelectMode] = useState(false);
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);

  // Action state
  const [actionId, setActionId] = useState<number | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-switch stage tab when map marker is clicked on a different stage
  useEffect(() => {
    if (switchToStage && switchToStage !== activeStage) {
      setActiveStage(switchToStage);
    }
  }, [switchToStage]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to selected card when map marker is clicked
  useEffect(() => {
    if (selectedLeadId) {
      // Small delay to allow stage switch + data fetch to render the card
      const timer = setTimeout(() => {
        const el = document.getElementById(`lead-card-${selectedLeadId}`);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [selectedLeadId]);

  const fetchLeads = useCallback(async () => {
    setFetchError(null);
    setLoading(true);
    try {
      const [sortBy, sortDir] = sortKey.split("-");
      const params = new URLSearchParams({
        status_filter: activeStage,
        sort_by: sortBy,
        sort_dir: sortDir || "desc",
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
      });
      if (search) params.set("search", search);
      if (county) params.set("county", county);
      if (minValue) params.set("min_value", minValue);
      if (maxValue) params.set("max_value", maxValue);
      if (minUnits) params.set("min_units", minUnits);
      if (minStories) params.set("min_stories", minStories);
      if (useCode) params.set("use_code", useCode);
      if (heatFilter) params.set("heat", heatFilter);
      if (citizensOnly) params.set("on_citizens", "true");
      if (creamTier) params.set("cream_tier", creamTier);

      const res = await fetch(`/api/proxy/leads?${params}`);
      if (res.ok) {
        const data: ApiResponse = await res.json();
        setLeads(data.results ?? []);
        setTotal(data.total ?? 0);

        // Send map data
        onLeadsLoaded?.(data.results
          .filter((l): l is Lead & { latitude: number; longitude: number } => l.latitude != null && l.longitude != null)
          .map((l, i) => ({
            id: l.id, name: l.name, latitude: l.latitude,
            longitude: l.longitude, heat_score: l.heat_score || "cold",
            status: l.status, listIndex: i + 1,
          })));
      } else {
        setFetchError(`Failed (${res.status})`);
      }
    } catch (err) {
      setFetchError("Unable to connect");
    }
    setLoading(false);
  }, [activeStage, search, county, sortKey, page, minValue, maxValue, minUnits, minStories, useCode, heatFilter, citizensOnly, creamTier, onLeadsLoaded]);

  // Fetch stage counts for the tab badges
  const fetchStageCounts = useCallback(async () => {
    try {
      const res = await fetch("/api/proxy/admin/enrich/status");
      if (res.ok) {
        const data = await res.json();
        if (data.stage_counts) setStageCounts(data.stage_counts);
      }
    } catch {}
  }, []);

  useEffect(() => {
    fetchLeads();
  }, [fetchLeads, refreshKey]);

  useEffect(() => {
    fetchStageCounts();
  }, [fetchStageCounts, refreshKey]);

  // Reset page when filters change
  useEffect(() => { setPage(0); }, [activeStage, search, county, sortKey, minValue, maxValue, minUnits, minStories, useCode, heatFilter, citizensOnly, creamTier]);

  // Clear selection when stage changes
  useEffect(() => { setSelected(new Set()); setSelectMode(false); setBulkMsg(null); }, [activeStage]);

  async function handleAction(entityId: number, targetStage: string) {
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
      fetchStageCounts();
    } catch {
      setFetchError("Action failed — try again");
    }
    setActionId(null);
  }

  async function handleBulkAction(targetStage: string) {
    setBulkMsg(null);
    const ids = Array.from(selected);
    if (ids.length === 0) return;

    try {
      const res = await fetch("/api/proxy/leads/bulk-stage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_ids: ids, stage: targetStage }),
      });
      if (res.ok) {
        const data = await res.json();
        setBulkMsg(`${data.changed ?? 0} moved to ${targetStage}`);
        setSelected(new Set());
        setSelectMode(false);
        await fetchLeads();
        fetchStageCounts();
      } else {
        setBulkMsg("Action failed — " + res.status);
      }
    } catch {
      setBulkMsg("Bulk action failed");
    }
  }

  async function handleBulkFilterAction(targetStage: string) {
    setBulkMsg(null);
    try {
      const body: Record<string, unknown> = { stage: targetStage, filter_stage: activeStage };
      if (county) body.filter_county = county;
      if (minValue) body.filter_min_value = parseFloat(minValue);
      if (maxValue) body.filter_max_value = parseFloat(maxValue);
      if (minUnits) body.filter_min_units = parseInt(minUnits, 10);
      if (minStories) body.filter_min_stories = parseInt(minStories, 10);
      if (useCode) body.filter_use_code = useCode;
      if (heatFilter) body.filter_heat = heatFilter;
      if (citizensOnly) body.filter_on_citizens = true;

      const res = await fetch("/api/proxy/leads/bulk-stage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const data = await res.json();
        setBulkMsg(`${data.changed ?? 0} moved to ${targetStage}`);
        await fetchLeads();
        fetchStageCounts();
      } else {
        setBulkMsg("Action failed — " + res.status);
      }
    } catch {
      setBulkMsg("Bulk action failed");
    }
  }

  function toggleSelect(id: number) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function selectAll() {
    setSelected(new Set(leads.map(l => l.id)));
  }

  function fmt(val: number | null | unknown): string {
    const n = typeof val === "number" ? val : parseFloat(String(val ?? ""));
    if (isNaN(n)) return "";
    if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
    return `$${n}`;
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="flex flex-col h-full">
      {/* Stage tabs */}
      <div className="flex gap-0.5 mb-2">
        {PIPELINE_STAGES.map((stage) => {
          const count = stageCounts[stage.key] ?? 0;
          const isActive = activeStage === stage.key;
          return (
            <button key={stage.key}
              onClick={() => setActiveStage(stage.key)}
              className={`flex-1 text-center py-1.5 rounded text-[10px] font-medium border transition-all ${
                isActive ? `${stage.color} ${stage.bg} ring-1 ring-white/20 ${stage.textColor}` :
                count > 0 ? `border-gray-800 bg-gray-900/50 text-gray-500 hover:text-gray-300` :
                "border-gray-800/50 bg-gray-950 text-gray-700"
              }`}>
              <span className="block text-sm font-bold">{count > 0 ? count.toLocaleString() : "0"}</span>
              <span className="block">{stage.label}</span>
            </button>
          );
        })}
      </div>

      {/* Search + Sort bar */}
      <div className="space-y-2 mb-2">
        <div className="flex gap-1.5">
          <input
            type="text" placeholder="Search name, address, owner..."
            value={search} onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && fetchLeads()}
            className="flex-1 bg-gray-900 border border-gray-800 rounded px-2.5 py-1.5 text-sm text-white placeholder-gray-600 focus:border-blue-600 focus:outline-none"
          />
          <button onClick={() => setShowFilters(!showFilters)}
            className={`px-2.5 py-1.5 rounded text-xs border ${showFilters || useCode || heatFilter || minStories || citizensOnly ? "border-blue-600 bg-blue-950 text-blue-300" : "border-gray-800 bg-gray-900 text-gray-500"}`}>
            Filters{(useCode || heatFilter || minStories || citizensOnly || minValue || maxValue || minUnits) ? ` (${[useCode, heatFilter, minStories, citizensOnly && "Citizens", minValue && "min$", maxValue && "max$", minUnits && "units"].filter(Boolean).length})` : ""}
          </button>
        </div>

        <div className="flex gap-1.5">
          <select value={county} onChange={(e) => setCounty(e.target.value)}
            className="flex-1 bg-gray-900 border border-gray-800 rounded px-2 py-1.5 text-xs text-white">
            <option value="">All Counties</option>
            {TARGET_COUNTIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={sortKey} onChange={(e) => setSortKey(e.target.value)}
            className="flex-1 bg-gray-900 border border-gray-800 rounded px-2 py-1.5 text-xs text-white">
            {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        {/* Expandable filter panel */}
        {showFilters && (
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-2.5 space-y-2">
            <div className="flex gap-2">
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">Use Code</label>
                <select value={useCode} onChange={(e) => setUseCode(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white">
                  {USE_CODE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">Heat Score</label>
                <select value={heatFilter} onChange={(e) => setHeatFilter(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white">
                  <option value="">All</option>
                  <option value="hot">Hot</option>
                  <option value="warm">Warm</option>
                  <option value="cold">Cold</option>
                </select>
              </div>
            </div>
            <div className="flex gap-2">
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">Min Value ($)</label>
                <input type="number" value={minValue} onChange={(e) => setMinValue(e.target.value)}
                  placeholder="e.g. 15000000"
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white" />
              </div>
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">Max Value ($)</label>
                <input type="number" value={maxValue} onChange={(e) => setMaxValue(e.target.value)}
                  placeholder="e.g. 50000000"
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white" />
              </div>
            </div>
            <div className="flex gap-2">
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">Min Stories</label>
                <input type="number" value={minStories} onChange={(e) => setMinStories(e.target.value)}
                  placeholder="e.g. 7"
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white" />
              </div>
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">Min Units</label>
                <input type="number" value={minUnits} onChange={(e) => setMinUnits(e.target.value)}
                  placeholder="e.g. 10"
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white" />
              </div>
            </div>
            <div className="flex gap-2 items-center">
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">Opportunity Tier</label>
                <select value={creamTier} onChange={(e) => setCreamTier(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white">
                  {CREAM_TIERS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">&nbsp;</label>
                <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer py-1">
                  <input type="checkbox" checked={citizensOnly} onChange={(e) => setCitizensOnly(e.target.checked)}
                    className="rounded bg-gray-800 border-gray-600 text-blue-600" />
                  Citizens Only
                </label>
              </div>
            </div>
            <div className="flex gap-2 items-center">
              <div className="flex-1" />
              <button onClick={() => { setMinValue(""); setMaxValue(""); setMinUnits(""); setMinStories(""); setUseCode(""); setHeatFilter(""); setCitizensOnly(false); setCreamTier(""); }}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-400 hover:text-white">
                Clear All
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Bulk actions bar */}
      <div className="flex items-center gap-1.5 mb-2">
        <button onClick={() => { setSelectMode(!selectMode); setSelected(new Set()); }}
          className={`text-[10px] px-2 py-1 rounded border ${selectMode ? "border-blue-600 bg-blue-950 text-blue-300" : "border-gray-800 bg-gray-900 text-gray-500"}`}>
          {selectMode ? `${selected.size} selected` : "Select"}
        </button>
        {selectMode && (
          <>
            <button onClick={selectAll} className="text-[10px] px-2 py-1 rounded border border-gray-800 bg-gray-900 text-gray-400">
              All
            </button>
            {selected.size > 0 && activeStage === "TARGET" && (
              <button onClick={() => handleBulkAction("LEAD")}
                className="text-[10px] px-2 py-1 rounded bg-cyan-700 text-white font-medium">
                &rarr; Lead ({selected.size})
              </button>
            )}
            {selected.size > 0 && activeStage === "LEAD" && (
              <button onClick={() => handleBulkAction("OPPORTUNITY")}
                className="text-[10px] px-2 py-1 rounded bg-amber-700 text-white font-medium">
                &rarr; Opp ({selected.size})
              </button>
            )}
            {selected.size > 0 && activeStage !== "ARCHIVED" && (
              <button onClick={() => handleBulkAction("ARCHIVED")}
                className="text-[10px] px-2 py-1 rounded bg-gray-700 text-gray-300 font-medium">
                Archive ({selected.size})
              </button>
            )}
          </>
        )}
        {!selectMode && (minValue || maxValue || minUnits) && activeStage === "TARGET" && (
          <>
            <button onClick={() => handleBulkFilterAction("LEAD")}
              className="text-[10px] px-2 py-1 rounded bg-cyan-700 text-white font-medium">
              Promote All Filtered &rarr; Lead
            </button>
            <button onClick={() => handleBulkFilterAction("ARCHIVED")}
              className="text-[10px] px-2 py-1 rounded bg-gray-700 text-gray-300 font-medium">
              Archive All Filtered
            </button>
          </>
        )}
        <span className="text-[10px] text-gray-600 ml-auto">{total.toLocaleString()} total</span>
      </div>

      {bulkMsg && (
        <div className="text-xs px-3 py-1.5 rounded mb-2 bg-green-900/50 text-green-300 border border-green-800">
          {bulkMsg}
        </div>
      )}

      {fetchError && (
        <div className="text-red-400 text-center py-2 bg-red-900/20 rounded mb-2 text-xs">
          {fetchError} <button onClick={fetchLeads} className="underline ml-1">Retry</button>
        </div>
      )}

      {loading && leads.length === 0 && (
        <div className="text-gray-500 text-center py-8 text-sm">Loading...</div>
      )}

      {/* Cards */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-1">
        {leads.map((lead) => {
          const isSelected = lead.id === selectedLeadId;
          const isChecked = selected.has(lead.id);
          const chars = lead.characteristics || {};
          const heat = lead.heat_score || "cold";
          const marketValue = chars.dor_market_value as number | undefined;

          return (
            <div key={lead.id} id={`lead-card-${lead.id}`}
              onMouseEnter={() => onLeadHover?.(lead.id)}
              onMouseLeave={() => onLeadHover?.(null)}
              className={`rounded-lg border overflow-hidden transition-colors ${
                isSelected ? "border-blue-500 bg-gray-900 ring-1 ring-blue-500/30" :
                isChecked ? "border-cyan-700 bg-gray-900" :
                "border-gray-800/50 bg-gray-900/60 hover:border-gray-700"
              }`}>
              <div className="px-3 py-2">
                {/* Header row */}
                <div className="flex items-center gap-2 mb-0.5">
                  {selectMode && (
                    <input type="checkbox" checked={isChecked}
                      onChange={() => toggleSelect(lead.id)}
                      className="w-3.5 h-3.5 rounded border-gray-600 bg-gray-800 shrink-0" />
                  )}
                  <h3
                    className="font-medium text-sm text-white truncate flex-1 cursor-pointer hover:text-blue-300"
                    onClick={() => {
                      if (lead.latitude != null && lead.longitude != null) {
                        onFlyTo?.(lead.latitude, lead.longitude, lead.id);
                      }
                    }}>
                    {lead.name}
                  </h3>
                  {marketValue && marketValue > 0 && (
                    <span className="text-xs text-gray-300 font-medium shrink-0">{fmt(marketValue)}</span>
                  )}
                  {activeStage !== "TARGET" && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${HEAT_COLORS[heat] || HEAT_COLORS.cold}`}>
                      {heat}
                    </span>
                  )}
                </div>

                {/* Address */}
                <p className="text-gray-500 text-[11px] truncate">{lead.address}</p>

                {/* Tags */}
                <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                  {!!chars.dor_use_description && (
                    <span className="text-[10px] px-1 rounded bg-gray-800 text-gray-400">{String(chars.dor_use_description)}</span>
                  )}
                  {!!chars.dor_num_units && Number(chars.dor_num_units) > 0 && (
                    <span className="text-[10px] px-1 rounded bg-gray-800 text-gray-500">{String(chars.dor_num_units)} units</span>
                  )}
                  {!!chars.dor_year_built && (
                    <span className="text-[10px] px-1 rounded bg-gray-800 text-gray-600">Built {String(chars.dor_year_built)}</span>
                  )}
                  {!!chars.dor_construction_class && (
                    <span className="text-[10px] px-1 rounded bg-gray-800 text-gray-600">{String(chars.dor_construction_class)}</span>
                  )}
                  {!!chars.flood_zone && (
                    <span className={`text-[10px] px-1 rounded ${
                      String(chars.flood_risk) === "extreme" || String(chars.flood_risk) === "high"
                        ? "bg-red-900/50 text-red-400" : "bg-gray-800 text-gray-500"
                    }`}>{String(chars.flood_zone)}</span>
                  )}
                  {!!chars.citizens_candidate && (
                    <span className="text-[10px] px-1 rounded bg-amber-900/50 text-amber-400">Citizens?</span>
                  )}
                  <span className="text-gray-700 text-[10px] ml-auto">{lead.county}</span>
                </div>

                {/* Enrichment for LEADs */}
                {activeStage === "LEAD" && lead.enrichment_status && (
                  <div className="flex items-center gap-1 mt-1 text-[10px]">
                    <span className={`w-1.5 h-1.5 rounded-full ${
                      lead.enrichment_status === "complete" ? "bg-green-500" :
                      lead.enrichment_status === "running" ? "bg-blue-500 animate-pulse" :
                      lead.enrichment_status === "error" ? "bg-red-500" : "bg-gray-600"
                    }`} />
                    <span className="text-gray-600">{lead.enrichment_status}</span>
                  </div>
                )}

                {/* Actions */}
                <div className="flex gap-1 mt-2">
                  {/* Open detail page */}
                  <button onClick={() => onOpenDetails?.(lead.id)}
                    className="bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs py-1.5 px-2.5 rounded font-medium">
                    Open
                  </button>

                  {/* Stage-specific promote */}
                  {activeStage === "TARGET" && (
                    <button onClick={() => handleAction(lead.id, "LEAD")}
                      disabled={actionId === lead.id}
                      className="flex-1 disabled:opacity-50 text-white text-xs py-1.5 rounded font-medium bg-cyan-700 hover:bg-cyan-600">
                      {actionId === lead.id ? "..." : "→ Lead"}
                    </button>
                  )}
                  {activeStage === "LEAD" && (
                    <button onClick={() => handleAction(lead.id, "OPPORTUNITY")}
                      disabled={actionId === lead.id}
                      className="flex-1 disabled:opacity-50 text-white text-xs py-1.5 rounded font-medium bg-amber-700 hover:bg-amber-600">
                      {actionId === lead.id ? "..." : "→ Opportunity"}
                    </button>
                  )}
                  {activeStage === "OPPORTUNITY" && (
                    <button onClick={() => handleAction(lead.id, "CUSTOMER")}
                      disabled={actionId === lead.id}
                      className="flex-1 disabled:opacity-50 text-white text-xs py-1.5 rounded font-medium bg-green-700 hover:bg-green-600">
                      {actionId === lead.id ? "..." : "→ Customer"}
                    </button>
                  )}

                  {/* Map button */}
                  {lead.latitude != null && lead.longitude != null && (
                    <button onClick={() => onFlyTo?.(lead.latitude!, lead.longitude!, lead.id)}
                      className="bg-gray-800 hover:bg-gray-700 text-gray-500 text-xs py-1.5 px-2 rounded" title="Fly to on map">
                      Map
                    </button>
                  )}

                  {/* Archive */}
                  {activeStage !== "CUSTOMER" && activeStage !== "ARCHIVED" && (
                    <button onClick={() => handleAction(lead.id, "ARCHIVED")}
                      disabled={actionId === lead.id}
                      className="bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-gray-600 text-xs py-1.5 px-2 rounded"
                      title="Archive">&times;</button>
                  )}

                  {/* Restore from archive */}
                  {activeStage === "ARCHIVED" && (
                    <button onClick={() => handleAction(lead.id, "TARGET")}
                      disabled={actionId === lead.id}
                      className="flex-1 disabled:opacity-50 text-white text-xs py-1.5 rounded font-medium bg-gray-700 hover:bg-gray-600">
                      Restore
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {leads.length === 0 && !loading && (
          <div className="text-gray-600 text-center py-8 text-sm">
            {search || county || minValue || maxValue || minUnits
              ? "No results match your filters"
              : `No ${activeStage.toLowerCase()}s yet`}
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-800">
          <button onClick={() => { setPage(p => Math.max(0, p - 1)); scrollRef.current?.scrollTo(0, 0); }}
            disabled={page === 0}
            className="text-xs text-gray-400 hover:text-white disabled:text-gray-700 px-2 py-1">
            &larr; Prev
          </button>
          <span className="text-[10px] text-gray-600">
            {page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, total)} of {total.toLocaleString()}
          </span>
          <button onClick={() => { setPage(p => Math.min(totalPages - 1, p + 1)); scrollRef.current?.scrollTo(0, 0); }}
            disabled={page >= totalPages - 1}
            className="text-xs text-gray-400 hover:text-white disabled:text-gray-700 px-2 py-1">
            Next &rarr;
          </button>
        </div>
      )}
    </div>
  );
}
