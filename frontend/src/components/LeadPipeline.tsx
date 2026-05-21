"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useAuth } from "@/hooks/useAuth";

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
  { key: "TARGET",      label: "Targets",     color: "border-gray-600",   bg: "bg-gray-800",        textColor: "text-gray-300" },
  { key: "LEAD",        label: "Leads",       color: "border-cyan-600",   bg: "bg-cyan-950/30",     textColor: "text-cyan-300" },
  { key: "VETTED",      label: "Vetted",      color: "border-teal-600",   bg: "bg-teal-950/30",     textColor: "text-teal-300" },
  { key: "ANALYZED",    label: "Analyzed",    color: "border-indigo-600", bg: "bg-indigo-950/30",   textColor: "text-indigo-300" },
  { key: "VALIDATED",   label: "Validated",   color: "border-purple-600", bg: "bg-purple-950/30",   textColor: "text-purple-300" },
  { key: "OPPORTUNITY", label: "Opps",        color: "border-amber-600",  bg: "bg-amber-950/30",    textColor: "text-amber-300" },
  { key: "CUSTOMER",    label: "Customers",   color: "border-green-600",  bg: "bg-green-950/30",    textColor: "text-green-300" },
  { key: "ARCHIVED",    label: "Archived",    color: "border-gray-700",   bg: "bg-gray-900",        textColor: "text-gray-500" },
] as const;

// Forward-progression map: clicking the right-arrow advances by exactly one
// stage. Anything beyond VALIDATED requires a manual user decision and the
// progression button hides — the user picks Opportunity from the action menu.
const NEXT_STAGE: Record<string, string | null> = {
  TARGET:      "LEAD",
  LEAD:        "VETTED",
  VETTED:      "ANALYZED",
  ANALYZED:    "VALIDATED",
  VALIDATED:   "OPPORTUNITY",
  OPPORTUNITY: "CUSTOMER",
  CUSTOMER:    null,
  ARCHIVED:    null,
};

const HEAT_COLORS: Record<string, string> = {
  hot: "bg-red-600 text-white",
  warm: "bg-orange-600 text-white",
  cold: "bg-gray-700 text-gray-400",
};

// All 35 Florida coastal counties (sorted Atlantic → Keys → Gulf → Panhandle)
const TARGET_COUNTIES = [
  // Atlantic NE → SE
  "Nassau", "Duval", "St. Johns", "Flagler", "Volusia", "Brevard",
  "Indian River", "St. Lucie", "Martin", "Palm Beach", "Broward", "Miami-Dade",
  // Florida Keys
  "Monroe",
  // Gulf SW → NW
  "Collier", "Lee", "Charlotte", "Sarasota", "Manatee", "Hillsborough",
  "Pinellas", "Pasco", "Hernando", "Citrus", "Levy", "Dixie", "Taylor",
  "Jefferson", "Wakulla", "Franklin", "Gulf", "Bay", "Walton",
  "Okaloosa", "Santa Rosa", "Escambia",
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

/* Multi-select county chip dropdown. Closed: "All Counties" or
 * "Pinellas +3 more". Open: full chip grid with All / None toggles.
 * Each chip is a click → toggle. Backend accepts comma-separated. */
function CountyMultiSelect({
  counties,
  setCounties,
}: {
  counties: string[];
  setCounties: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const label = counties.length === 0
    ? "All Counties"
    : counties.length === 1
      ? counties[0]
      : `${counties[0]} +${counties.length - 1}`;
  return (
    <div className="flex-1 relative">
      <button
        type="button"
        onClick={() => setOpen((x) => !x)}
        className={`w-full text-left bg-gray-900 border rounded px-2 py-1.5 text-xs ${
          counties.length > 0
            ? "border-blue-700 text-blue-200"
            : "border-gray-800 text-white"
        }`}
      >
        {label} <span className="text-gray-600 float-right">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-72 max-h-80 overflow-y-auto bg-gray-950 border border-gray-700 rounded shadow-xl p-2">
          <div className="flex items-center gap-2 mb-1.5 pb-1.5 border-b border-gray-800">
            <button
              type="button"
              onClick={() => setCounties([...TARGET_COUNTIES])}
              className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-300 hover:bg-gray-700"
            >
              All
            </button>
            <button
              type="button"
              onClick={() => setCounties([])}
              className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-300 hover:bg-gray-700"
            >
              None
            </button>
            <span className="text-[10px] text-gray-500 ml-auto">
              {counties.length} of {TARGET_COUNTIES.length}
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {TARGET_COUNTIES.map((c) => {
              const on = counties.includes(c);
              return (
                <button
                  type="button"
                  key={c}
                  onClick={() => setCounties(
                    on ? counties.filter(x => x !== c) : [...counties, c]
                  )}
                  className={`text-[10px] px-1.5 py-0.5 rounded border ${
                    on
                      ? "bg-blue-900/60 text-blue-200 border-blue-600"
                      : "bg-gray-900 text-gray-400 border-gray-800 hover:border-gray-600"
                  }`}
                >
                  {c}
                </button>
              );
            })}
          </div>
          <div className="flex justify-end mt-2 pt-1.5 border-t border-gray-800">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-[10px] px-2 py-0.5 rounded bg-gray-800 text-gray-300 hover:bg-gray-700"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

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
  const { canEdit } = useAuth();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Stage counts (fetched separately for all stages)
  const [stageCounts, setStageCounts] = useState<Record<string, number>>({});

  // Filters
  // Default to VETTED — that's the building-master stage Jason actually
  // works against. Landing on TARGET (5.9M unfiltered parcels) made
  // login take 10-30 seconds because the count query has to scan the
  // whole table. VETTED is ~150K rows = sub-second with the indexes.
  const [activeStage, setActiveStage] = useState("VETTED");
  const [search, setSearch] = useState("");
  // County + use-code now multi-select. Empty array means "all" — the
  // backend treats no filter and "everything checked" the same. Comma-
  // joined into the legacy query param when the request goes out.
  const [counties, setCounties] = useState<string[]>(
    initialCounty ? [initialCounty] : []
  );
  const [useCodes, setUseCodes] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState("value-desc");
  const [minValue, setMinValue] = useState("");
  const [maxValue, setMaxValue] = useState("");
  const [minUnits, setMinUnits] = useState("");
  const [minStories, setMinStories] = useState("");
  const [heatFilter, setHeatFilter] = useState("");
  const [citizensOnly, setCitizensOnly] = useState(false);
  const [creamTier, setCreamTier] = useState("");
  const [minYear, setMinYear] = useState("");
  const [maxYear, setMaxYear] = useState("");
  const [maxDistance, setMaxDistance] = useState("");
  const [construction, setConstruction] = useState("");
  const [showFilters, setShowFilters] = useState(false);

  // Saved filter presets — persisted server-side via /api/user/filters.
  // Each user has their own filters; is_shared=true filters are visible
  // to the whole team but only editable by the owner.
  interface SavedFilterData {
    // Multi-value as of this build; legacy single-string filters
    // saved before this change still load (the getters below
    // accept either shape).
    counties?: string[];
    county?: string;             // legacy single value, still loads
    useCodes?: string[];
    useCode?: string;            // legacy single value
    sortKey: string;
    minValue: string;
    maxValue: string;
    minUnits: string;
    minStories: string;
    heatFilter: string;
    citizensOnly: boolean;
    creamTier: string;
    minYear: string;
    maxYear: string;
    maxDistance: string;
    construction: string;
  }
  interface SavedFilterRow {
    id: number;
    name: string;
    filter_json: SavedFilterData;
    is_shared: boolean;
    is_own: boolean;
    owner_display: string;
  }
  const [savedFilters, setSavedFilters] = useState<SavedFilterRow[]>([]);

  async function refreshSavedFilters() {
    try {
      const res = await fetch("/api/proxy/user/filters");
      if (res.ok) {
        const d = await res.json();
        setSavedFilters(d.filters ?? []);
      }
    } catch {}
  }

  // Load saved filters on mount
  useEffect(() => { refreshSavedFilters(); }, []);

  async function saveCurrentFilter() {
    const name = window.prompt("Name this filter set:");
    if (!name?.trim()) return;
    const shared = window.confirm(
      `Share "${name}" with the whole team?\n\n` +
      `OK = Shared (visible to everyone, editable by you)\n` +
      `Cancel = Private (only visible to you)`
    );
    const snapshot: SavedFilterData = {
      counties, useCodes,
      sortKey, minValue, maxValue, minUnits, minStories,
      heatFilter, citizensOnly, creamTier,
      minYear, maxYear, maxDistance, construction,
    };
    try {
      await fetch("/api/proxy/user/filters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), filter_json: snapshot, is_shared: shared }),
      });
      await refreshSavedFilters();
    } catch {}
  }

  function loadSavedFilter(f: SavedFilterRow) {
    const d = f.filter_json || ({} as SavedFilterData);
    // Multi-value with single-value legacy fallback.
    setCounties(d.counties ?? (d.county ? [d.county] : []));
    setUseCodes(d.useCodes ?? (d.useCode ? [d.useCode] : []));
    setSortKey(d.sortKey ?? "value-desc");
    setMinValue(d.minValue ?? "");
    setMaxValue(d.maxValue ?? "");
    setMinUnits(d.minUnits ?? "");
    setMinStories(d.minStories ?? "");
    setHeatFilter(d.heatFilter ?? "");
    setCitizensOnly(!!d.citizensOnly);
    setCreamTier(d.creamTier ?? "");
    setMinYear(d.minYear ?? "");
    setMaxYear(d.maxYear ?? "");
    setMaxDistance(d.maxDistance ?? "");
    setConstruction(d.construction ?? "");
  }

  async function deleteSavedFilter(f: SavedFilterRow) {
    if (!f.is_own) return; // Can only delete your own
    if (!window.confirm(`Delete saved filter "${f.name}"?`)) return;
    try {
      await fetch(`/api/proxy/user/filters/${f.id}`, { method: "DELETE" });
      await refreshSavedFilters();
    } catch {}
  }

  // Pagination
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 50;

  // Bulk select
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // "Select all" sentinel — true means every entity that matches the
  // current filter is selected (count = total), without us having to
  // materialise 150K ids in a Set. handleBulkAction routes through
  // the filter-based bulk endpoint when this flag is true.
  const [selectedAllFiltered, setSelectedAllFiltered] = useState(false);
  const [selectingAll, setSelectingAll] = useState(false);
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
      if (counties.length > 0) params.set("county", counties.join(","));
      if (minValue) params.set("min_value", minValue);
      if (maxValue) params.set("max_value", maxValue);
      if (minUnits) params.set("min_units", minUnits);
      if (minStories) params.set("min_stories", minStories);
      if (useCodes.length > 0) params.set("use_code", useCodes.join(","));
      if (heatFilter) params.set("heat", heatFilter);
      if (citizensOnly) params.set("on_citizens", "true");
      if (creamTier) params.set("cream_tier", creamTier);
      if (minYear) params.set("min_year", minYear);
      if (maxYear) params.set("max_year", maxYear);
      if (maxDistance) params.set("max_distance_miles", maxDistance);
      if (construction) params.set("construction", construction);

      const res = await fetch(`/api/proxy/leads?${params}`);
      if (res.ok) {
        const data: ApiResponse = await res.json();
        setLeads(data.results ?? []);
        setTotal(data.total ?? 0);

        // ── Map markers ──
        // Card list is paginated 50 at a time, but the user wants
        // the map to show EVERY unit matching the current filter as
        // a marker — not just the visible page. Fire a second wider
        // query (capped at 1000 to keep the payload sane on
        // 150K-row VETTED views) and push that to the map. Filters
        // and sort are identical so markers stay aligned with the
        // list view.
        const mapParams = new URLSearchParams(params);
        mapParams.set("limit", "1000");
        mapParams.set("offset", "0");
        fetch(`/api/proxy/leads?${mapParams}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((d: ApiResponse | null) => {
            if (!d?.results) return;
            onLeadsLoaded?.(d.results
              .filter((l): l is Lead & { latitude: number; longitude: number } => l.latitude != null && l.longitude != null)
              .map((l, i) => ({
                id: l.id, name: l.name, latitude: l.latitude,
                longitude: l.longitude, heat_score: l.heat_score || "cold",
                status: l.status, listIndex: i + 1,
              })));
          })
          .catch(() => {/* non-critical; cards still render */});
      } else {
        setFetchError(`Failed (${res.status})`);
      }
    } catch (err) {
      setFetchError("Unable to connect");
    }
    setLoading(false);
  }, [activeStage, search, counties, sortKey, page, minValue, maxValue, minUnits, minStories, useCodes, heatFilter, citizensOnly, creamTier, minYear, maxYear, maxDistance, construction, onLeadsLoaded]);

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
  useEffect(() => { setPage(0); }, [activeStage, search, counties, sortKey, minValue, maxValue, minUnits, minStories, useCodes, heatFilter, citizensOnly, creamTier, minYear, maxYear, maxDistance, construction]);

  // Clear selection when stage changes
  useEffect(() => {
    setSelected(new Set());
    setSelectedAllFiltered(false);
    setSelectMode(false);
    setBulkMsg(null);
  }, [activeStage]);

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
    // "Select all" sentinel: route through the filter-based bulk
    // endpoint so every matching row (not just the page-1 50) gets
    // moved in one SQL UPDATE. Same path as "Archive All Filtered".
    if (selectedAllFiltered) {
      await handleBulkFilterAction(targetStage);
      setSelected(new Set());
      setSelectedAllFiltered(false);
      setSelectMode(false);
      return;
    }
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
        setSelectedAllFiltered(false);
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
      if (counties.length > 0) body.filter_county = counties.join(",");
      if (minValue) body.filter_min_value = parseFloat(minValue);
      if (maxValue) body.filter_max_value = parseFloat(maxValue);
      if (minUnits) body.filter_min_units = parseInt(minUnits, 10);
      if (minStories) body.filter_min_stories = parseInt(minStories, 10);
      if (useCodes.length > 0) body.filter_use_code = useCodes.join(",");
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
    // Manually unchecking any row drops out of the "all filtered"
    // sentinel — the user is now curating a subset.
    if (selectedAllFiltered) setSelectedAllFiltered(false);
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  /** Select every entity matching the current filters, not just the
   *  visible page. For small result sets (≤ 1000) we fetch the
   *  explicit ids; above that we set a sentinel and route the bulk
   *  action through the filter-based endpoint so PostgreSQL handles
   *  the full set in a single UPDATE.
   */
  async function selectAll() {
    if (selectingAll) return;
    setSelectingAll(true);
    setBulkMsg(null);
    try {
      // Cheap path: result set fits in one page-1000 request.
      if (total > 0 && total <= 1000) {
        const params = new URLSearchParams({
          status_filter: activeStage,
          sort_by: sortKey.split("-")[0],
          sort_dir: sortKey.split("-")[1] || "desc",
          limit: "1000",
          offset: "0",
        });
        if (search) params.set("search", search);
        if (counties.length > 0) params.set("county", counties.join(","));
        if (minValue) params.set("min_value", minValue);
        if (maxValue) params.set("max_value", maxValue);
        if (minUnits) params.set("min_units", minUnits);
        if (minStories) params.set("min_stories", minStories);
        if (useCodes.length > 0) params.set("use_code", useCodes.join(","));
        if (heatFilter) params.set("heat", heatFilter);
        if (citizensOnly) params.set("on_citizens", "true");
        if (creamTier) params.set("cream_tier", creamTier);
        if (minYear) params.set("min_year", minYear);
        if (maxYear) params.set("max_year", maxYear);
        if (maxDistance) params.set("max_distance_miles", maxDistance);
        if (construction) params.set("construction", construction);
        const res = await fetch(`/api/proxy/leads?${params}`);
        if (res.ok) {
          const data = await res.json();
          const ids = new Set<number>(
            (data.results ?? []).map((l: { id: number }) => l.id)
          );
          setSelected(ids);
          setSelectedAllFiltered(false);
        }
      } else {
        // Big set — don't materialise 150K ids in the browser. Flag
        // sentinel; handleBulkAction will route through the
        // filter-based bulk endpoint instead.
        setSelected(new Set());
        setSelectedAllFiltered(true);
      }
    } finally {
      setSelectingAll(false);
    }
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
            className={`px-2.5 py-1.5 rounded text-xs border ${showFilters || useCodes.length || heatFilter || minStories || citizensOnly ? "border-blue-600 bg-blue-950 text-blue-300" : "border-gray-800 bg-gray-900 text-gray-500"}`}>
            Filters{(useCodes.length || heatFilter || minStories || citizensOnly || minValue || maxValue || minUnits) ? ` (${[useCodes.length > 0 && `${useCodes.length} use-code`, heatFilter, minStories, citizensOnly && "Citizens", minValue && "min$", maxValue && "max$", minUnits && "units"].filter(Boolean).length})` : ""}
          </button>
        </div>

        <div className="flex gap-1.5 items-start">
          <CountyMultiSelect
            counties={counties}
            setCounties={setCounties}
          />
          <select value={sortKey} onChange={(e) => setSortKey(e.target.value)}
            className="flex-1 bg-gray-900 border border-gray-800 rounded px-2 py-1.5 text-xs text-white">
            {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        {/* Expandable filter panel */}
        {showFilters && (
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-2.5 space-y-2">
            {/* Saved filter presets (server-side) */}
            <div className="flex items-start gap-1.5 pb-2 border-b border-gray-800/60">
              <span className="text-[10px] text-gray-500 pt-1 shrink-0">Saved:</span>
              <div className="flex-1 flex flex-wrap gap-1">
                {savedFilters.length === 0 ? (
                  <span className="text-[10px] text-gray-600 italic pt-1">none yet</span>
                ) : (
                  savedFilters.map((f) => {
                    const styleOwn = "bg-blue-950/50 border-blue-800 text-blue-300";
                    const styleShared = "bg-purple-950/50 border-purple-800 text-purple-300";
                    const wrap = f.is_own ? styleOwn : styleShared;
                    return (
                      <span key={f.id}
                        className={`inline-flex items-center gap-0.5 ${wrap} border rounded overflow-hidden text-[10px]`}>
                        <button onClick={() => loadSavedFilter(f)}
                          className="px-2 py-0.5 hover:bg-black/30"
                          title={
                            f.is_own
                              ? `Load "${f.name}"${f.is_shared ? " (shared)" : ""}`
                              : `Load "${f.name}" (shared by ${f.owner_display})`
                          }>
                          {f.name}{!f.is_own && <span className="ml-1 opacity-60">·{f.owner_display}</span>}
                        </button>
                        {f.is_own && (
                          <button onClick={() => deleteSavedFilter(f)}
                            className="px-1 py-0.5 opacity-60 hover:opacity-100 hover:bg-red-900/30 hover:text-red-400"
                            title={`Delete "${f.name}"`}>
                            ×
                          </button>
                        )}
                      </span>
                    );
                  })
                )}
              </div>
              <button onClick={saveCurrentFilter}
                className="shrink-0 px-2 py-0.5 text-[10px] rounded bg-green-900/50 border border-green-800 text-green-300 hover:bg-green-900">
                + Save
              </button>
            </div>
            <div className="flex gap-2">
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">
                  Use Code
                  <button
                    type="button"
                    onClick={() => setUseCodes(USE_CODE_OPTIONS.filter(o => o.value).map(o => o.value))}
                    className="ml-2 text-[9px] text-gray-500 hover:text-gray-300"
                  >all</button>
                  <button
                    type="button"
                    onClick={() => setUseCodes([])}
                    className="ml-1 text-[9px] text-gray-500 hover:text-gray-300"
                  >none</button>
                </label>
                <div className="flex flex-wrap gap-1">
                  {USE_CODE_OPTIONS.filter(o => o.value).map((o) => {
                    const on = useCodes.includes(o.value);
                    return (
                      <button
                        type="button"
                        key={o.value}
                        onClick={() => setUseCodes(prev =>
                          prev.includes(o.value)
                            ? prev.filter(v => v !== o.value)
                            : [...prev, o.value]
                        )}
                        className={`text-[10px] px-1.5 py-0.5 rounded border ${
                          on
                            ? "bg-blue-900/60 text-blue-200 border-blue-600"
                            : "bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-600"
                        }`}
                      >
                        {o.label}
                      </button>
                    );
                  })}
                </div>
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
            {/* Year built range + distance to ocean */}
            <div className="flex gap-2">
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">Year Built (Min)</label>
                <input type="number" value={minYear} onChange={(e) => setMinYear(e.target.value)}
                  placeholder="1900"
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white" />
              </div>
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">Year Built (Max)</label>
                <input type="number" value={maxYear} onChange={(e) => setMaxYear(e.target.value)}
                  placeholder={`${new Date().getFullYear()}`}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white" />
              </div>
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">Max Distance (mi)</label>
                <input type="number" step="0.25" value={maxDistance} onChange={(e) => setMaxDistance(e.target.value)}
                  placeholder="e.g. 1"
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white" />
              </div>
            </div>
            <div className="flex gap-2">
              <div className="flex-1">
                <label className="text-[10px] text-gray-500 block mb-0.5">Construction</label>
                <select value={construction} onChange={(e) => setConstruction(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white">
                  <option value="">Any</option>
                  <option value="fire_resistive">Fire Resistive</option>
                  <option value="non_combustible">Non-Combustible</option>
                  <option value="masonry">Masonry</option>
                  <option value="frame">Frame</option>
                </select>
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
              <button onClick={() => { setMinValue(""); setMaxValue(""); setMinUnits(""); setMinStories(""); setUseCodes([]); setCounties([]); setHeatFilter(""); setCitizensOnly(false); setCreamTier(""); setMinYear(""); setMaxYear(""); setMaxDistance(""); setConstruction(""); }}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-400 hover:text-white">
                Clear All
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Bulk actions bar */}
      <div className="flex items-center gap-1.5 mb-2">
        {canEdit && (
          <button onClick={() => {
              setSelectMode(!selectMode);
              setSelected(new Set());
              setSelectedAllFiltered(false);
            }}
            className={`text-[10px] px-2 py-1 rounded border ${selectMode ? "border-blue-600 bg-blue-950 text-blue-300" : "border-gray-800 bg-gray-900 text-gray-500"}`}>
            {selectMode
              ? (selectedAllFiltered
                  ? `all ${total.toLocaleString()} selected`
                  : `${selected.size} selected`)
              : "Select"}
          </button>
        )}
        {canEdit && selectMode && (
          <>
            <button onClick={selectAll}
              disabled={selectingAll || total === 0}
              title={`Select every ${activeStage.toLowerCase()} matching the current filters (${total.toLocaleString()})`}
              className="text-[10px] px-2 py-1 rounded border border-gray-800 bg-gray-900 text-gray-400 disabled:opacity-40">
              {selectingAll ? "…" : `All (${total.toLocaleString()})`}
            </button>
            {(selected.size > 0 || selectedAllFiltered) && NEXT_STAGE[activeStage] && (
              <button onClick={() => handleBulkAction(NEXT_STAGE[activeStage]!)}
                className="text-[10px] px-2 py-1 rounded bg-cyan-700 text-white font-medium">
                &rarr; {NEXT_STAGE[activeStage]} ({selectedAllFiltered ? total.toLocaleString() : selected.size})
              </button>
            )}
            {(selected.size > 0 || selectedAllFiltered) && activeStage !== "ARCHIVED" && (
              <button onClick={() => handleBulkAction("ARCHIVED")}
                className="text-[10px] px-2 py-1 rounded bg-gray-700 text-gray-300 font-medium">
                Archive ({selectedAllFiltered ? total.toLocaleString() : selected.size})
              </button>
            )}
          </>
        )}
        {canEdit && !selectMode && (minValue || maxValue || minUnits) && NEXT_STAGE[activeStage] && (
          <>
            <button onClick={() => handleBulkFilterAction(NEXT_STAGE[activeStage]!)}
              className="text-[10px] px-2 py-1 rounded bg-cyan-700 text-white font-medium">
              Promote All Filtered &rarr; {NEXT_STAGE[activeStage]}
            </button>
            <button onClick={() => handleBulkFilterAction("ARCHIVED")}
              className="text-[10px] px-2 py-1 rounded bg-gray-700 text-gray-300 font-medium">
              Archive All Filtered
            </button>
          </>
        )}
        <span className="text-[11px] font-mono font-semibold text-green-400 ml-auto" title="Total matching the current filter">
          {total.toLocaleString()} total
        </span>
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
                {(() => {
                  // Provenance: is the building name "auditor-confirmed"?
                  // The PA enricher writes pa_owner; the aggregator writes
                  // dor_owner_personal whenever it had to SYNTHESIZE the
                  // master name because the DOR owner was a person, not
                  // an association. So:
                  //   green  = pa_owner set, or DOR owner already reads
                  //            like an association (CONDO / ASSN / etc.)
                  //   orange = aggregator-synthesized OR raw person name
                  const _pa_owner = (chars.pa_owner ?? "") as string;
                  const _sunbiz_corp = (chars.sunbiz_corp_name ?? "") as string;
                  const _personal_override = (chars.dor_owner_personal ?? "") as string;
                  const _name_str = lead.name || "";
                  const _looks_assn = /\b(CONDO|CONDOMINIUM|ASSOCIATION|ASSN|ASSOC|HOA|HOMEOWNERS|MASTER|OWNERS)\b/i.test(_name_str);
                  const nameFromAuditor = !!_pa_owner || !!_sunbiz_corp || (
                    !_personal_override && _looks_assn
                  );
                  const ownerStr = _pa_owner || (chars.dor_owner as string) || _personal_override || "";
                  const ownerFromAuditor = !!_pa_owner;
                  return (
                <>
                {/* Header: name + value pill + heat */}
                <div className="flex items-center gap-2 mb-1">
                  {canEdit && selectMode && (
                    <input type="checkbox" checked={isChecked}
                      onChange={() => toggleSelect(lead.id)}
                      className="w-3.5 h-3.5 rounded border-gray-600 bg-gray-800 shrink-0" />
                  )}
                  <h3
                    className={`font-semibold text-sm truncate flex-1 ${
                      nameFromAuditor ? "text-green-300" : "text-orange-300"
                    }`}
                    title={
                      nameFromAuditor
                        ? "Name confirmed from PA / Sunbiz auditor data"
                        : "Name synthesized by aggregator or pulled from raw DOR owner (no auditor confirmation)"
                    }
                  >
                    {lead.name}
                  </h3>
                  {marketValue && marketValue > 0 && (
                    <span
                      className="text-xs text-gray-300 font-medium shrink-0"
                      title={chars.tiv_is_estimate ? "Aggregated estimate — Zillow / VRBO will refine in VALIDATED stage" : undefined}
                    >
                      {fmt(marketValue)}
                      {chars.tiv_is_estimate ? "*" : ""}
                    </span>
                  )}
                  {activeStage !== "TARGET" && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${HEAT_COLORS[heat] || HEAT_COLORS.cold}`}>
                      {heat}
                    </span>
                  )}
                </div>

                {/* Address — neon blue */}
                <p
                  className="text-cyan-300 text-[12px] font-medium truncate"
                  title={lead.address}
                >
                  {lead.address}
                </p>

                {/* Owner — green if from PA, orange if just DOR */}
                {ownerStr && (
                  <p
                    className={`text-[10px] truncate mt-0.5 ${
                      ownerFromAuditor ? "text-green-400" : "text-orange-400"
                    }`}
                    title={
                      ownerFromAuditor
                        ? `Owner from county PA: ${ownerStr}`
                        : `Owner from DOR (no PA confirmation): ${ownerStr}`
                    }
                  >
                    <span className="text-gray-600">Owner: </span>
                    {ownerStr}
                  </p>
                )}

                {/* Click-to-MAP line — bold neon, dedicated trigger */}
                {lead.latitude != null && lead.longitude != null && (
                  <button
                    onClick={() => onFlyTo?.(lead.latitude!, lead.longitude!, lead.id)}
                    title="Fly the map to this property"
                    className="mt-1.5 w-full text-center bg-gradient-to-r from-cyan-900/40 via-cyan-700/40 to-cyan-900/40 hover:from-cyan-700/60 hover:via-cyan-500/60 hover:to-cyan-700/60 border border-cyan-700/40 hover:border-cyan-400 rounded text-cyan-200 hover:text-cyan-100 text-[11px] font-bold tracking-widest py-0.5 transition-colors"
                  >
                    ◎ MAP
                  </button>
                )}

                {/* Tags */}
                <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                  {!!chars.is_aggregation_master && Number(chars.sibling_count) > 0 && (
                    <span
                      className="text-[10px] px-1.5 rounded bg-teal-900/60 text-teal-300 font-medium"
                      title="VETTED master — N unit parcels rolled up under this record"
                    >
                      {Number(chars.sibling_count) + 1} parcels
                    </span>
                  )}
                  {!!chars.dor_use_description && (
                    <span className="text-[10px] px-1 rounded bg-gray-800 text-gray-400">{String(chars.dor_use_description)}</span>
                  )}
                  {!!chars.dor_num_units && Number(chars.dor_num_units) > 0 && (
                    <span
                      className="text-[10px] px-1.5 rounded bg-green-900/50 text-green-300 font-semibold"
                      title={`${chars.dor_num_units} units`}
                    >
                      {String(chars.dor_num_units)} units
                    </span>
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
                </>
                );})()}

                {/* Enrichment status — visible on every stage that runs
                    enrichers (VETTED through CUSTOMER). LEAD/TARGET don't
                    enrich so we hide the dot there. */}
                {(activeStage === "VETTED" || activeStage === "ANALYZED" ||
                  activeStage === "VALIDATED" || activeStage === "OPPORTUNITY" ||
                  activeStage === "CUSTOMER") && lead.enrichment_status && (
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

                  {/* Single forward-promotion button — always advances by
                      exactly one stage. Hidden when there's no next stage
                      (CUSTOMER or ARCHIVED). Colour matches destination. */}
                  {canEdit && NEXT_STAGE[activeStage] && (
                    <button onClick={() => handleAction(lead.id, NEXT_STAGE[activeStage]!)}
                      disabled={actionId === lead.id}
                      className={`flex-1 disabled:opacity-50 text-white text-xs py-1.5 rounded font-medium ${
                        NEXT_STAGE[activeStage] === "LEAD"        ? "bg-cyan-700 hover:bg-cyan-600"
                      : NEXT_STAGE[activeStage] === "VETTED"      ? "bg-teal-700 hover:bg-teal-600"
                      : NEXT_STAGE[activeStage] === "ANALYZED"    ? "bg-indigo-700 hover:bg-indigo-600"
                      : NEXT_STAGE[activeStage] === "VALIDATED"   ? "bg-purple-700 hover:bg-purple-600"
                      : NEXT_STAGE[activeStage] === "OPPORTUNITY" ? "bg-amber-700 hover:bg-amber-600"
                      : NEXT_STAGE[activeStage] === "CUSTOMER"    ? "bg-green-700 hover:bg-green-600"
                      : "bg-gray-700 hover:bg-gray-600"
                      }`}>
                      {actionId === lead.id ? "..." : `→ ${NEXT_STAGE[activeStage]}`}
                    </button>
                  )}

                  {/* Map button removed — replaced by the bold "◎ MAP"
                      line at the top of the card body. Same handler,
                      more prominent click target. */}

                  {/* Per-card archive removed — too easy to click by
                      accident. Archive still available via bulk
                      action (select cards → "Archive (N)") or via the
                      Stage dropdown inside the entity detail modal. */}

                  {/* Restore from archive — only shown on the ARCHIVED
                      tab. Moves the entity back to TARGET so the
                      qualifier/aggregator can re-evaluate it from
                      scratch. */}
                  {canEdit && activeStage === "ARCHIVED" && (
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
            {search || counties.length || minValue || maxValue || minUnits
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
