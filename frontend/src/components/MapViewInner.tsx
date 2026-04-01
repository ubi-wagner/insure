"use client";

import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Fallback center — Pinellas Park, FL
const FALLBACK_CENTER: [number, number] = [27.8428, -82.6993];
const FALLBACK_ZOOM = 12;
const STORAGE_KEY = "insure_map_view";

// Pipeline stage → border color
const STAGE_STYLES: Record<string, { border: string }> = {
  NEW:         { border: "#6b7280" }, // gray
  CANDIDATE:   { border: "#a855f7" }, // purple
  TARGET:      { border: "#f59e0b" }, // amber
  OPPORTUNITY: { border: "#3b82f6" }, // blue
  CUSTOMER:    { border: "#22c55e" }, // green
  CHURNED:     { border: "#9ca3af" }, // light gray
  ARCHIVED:    { border: "#450a0a" }, // dark red
};

// Heat score → fill color override for ranking
const HEAT_FILL: Record<string, string> = {
  hot:  "#ef4444",  // red
  warm: "#f97316",  // orange
  cool: "#3b82f6",  // blue
  none: "#6b7280",  // gray
};

interface LeadLocation {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  heat_score: string;
  status: string;
  listIndex: number;
}

interface RegionFormData {
  name: string;
  stories: number;
  coastDistance: number;
}

interface Props {
  onRegionCreated: () => void;
  leads?: LeadLocation[];
  hoveredLeadId?: number | null;
  selectedLeadId?: number | null;
  flyToTarget?: { lat: number; lng: number } | null;
  onMarkerClick?: (id: number) => void;
}

function getSavedView(): { center: [number, number]; zoom: number } {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return JSON.parse(saved);
  } catch {}
  return { center: FALLBACK_CENTER, zoom: FALLBACK_ZOOM };
}

function saveView(center: [number, number], zoom: number) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ center, zoom }));
  } catch {}
}

function createNumberedIcon(num: number, fillColor: string, borderColor: string, isSelected: boolean): L.DivIcon {
  const size = isSelected ? 32 : 24;
  const fontSize = isSelected ? 13 : 11;
  const borderWidth = isSelected ? 3 : 2;
  return L.divIcon({
    className: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div style="
      width:${size}px;height:${size}px;
      border-radius:50%;
      background:${fillColor};
      border:${borderWidth}px solid ${borderColor};
      display:flex;align-items:center;justify-content:center;
      color:#fff;font-size:${fontSize}px;font-weight:700;
      box-shadow:0 2px 6px rgba(0,0,0,0.4);
      cursor:pointer;
      ${isSelected ? 'transform:scale(1.1);z-index:9999;' : ''}
    ">${num}</div>`,
  });
}

export default function MapViewInner({
  onRegionCreated, leads = [], hoveredLeadId, selectedLeadId, flyToTarget, onMarkerClick,
}: Props) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<L.Map | null>(null);
  const markersRef = useRef<Map<number, L.Marker>>(new Map());
  const regionsLayerRef = useRef<L.FeatureGroup | null>(null);

  const [drawMode, setDrawMode] = useState(false);
  const firstCornerRef = useRef<L.LatLng | null>(null);
  const previewRectRef = useRef<L.Rectangle | null>(null);

  const [pendingBounds, setPendingBounds] = useState<{ north: number; south: number; east: number; west: number } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState<RegionFormData>({ name: "", stories: 3, coastDistance: 5 });
  const [searchQuery, setSearchQuery] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // ─── Init map with saved position ───
  useEffect(() => {
    if (!mapRef.current || mapInstance.current) return;

    const { center, zoom } = getSavedView();

    const map = L.map(mapRef.current, {
      center,
      zoom,
      zoomSnap: 1,
      zoomAnimation: false,
      fadeAnimation: false,
      markerZoomAnimation: false,
      inertia: false,
      zoomControl: false, // We use custom controls
    });

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
      maxZoom: 19,
    }).addTo(map);

    // Save position on every move/zoom
    map.on("moveend", () => {
      const c = map.getCenter();
      saveView([c.lat, c.lng], map.getZoom());
    });

    const regionsLayer = new L.FeatureGroup();
    map.addLayer(regionsLayer);
    regionsLayerRef.current = regionsLayer;

    mapInstance.current = map;

    return () => {
      map.remove();
      mapInstance.current = null;
    };
  }, []);

  // ─── Two-click rectangle drawing ───
  useEffect(() => {
    const map = mapInstance.current;
    if (!map) return;

    function handleClick(e: L.LeafletMouseEvent) {
      if (!firstCornerRef.current) {
        firstCornerRef.current = e.latlng;
        map!.getContainer().style.cursor = "crosshair";
      } else {
        const bounds = L.latLngBounds(firstCornerRef.current, e.latlng);
        if (previewRectRef.current) {
          map!.removeLayer(previewRectRef.current);
          previewRectRef.current = null;
        }
        const rect = L.rectangle(bounds, { color: "#3b82f6", weight: 2, fillOpacity: 0.15 });
        regionsLayerRef.current?.addLayer(rect);
        setPendingBounds({
          north: bounds.getNorth(), south: bounds.getSouth(),
          east: bounds.getEast(), west: bounds.getWest(),
        });
        firstCornerRef.current = null;
        map!.getContainer().style.cursor = "";
        setDrawMode(false);
        setShowForm(true);
      }
    }

    function handleMouseMove(e: L.LeafletMouseEvent) {
      if (!firstCornerRef.current) return;
      const bounds = L.latLngBounds(firstCornerRef.current, e.latlng);
      if (previewRectRef.current) {
        previewRectRef.current.setBounds(bounds);
      } else {
        previewRectRef.current = L.rectangle(bounds, {
          color: "#3b82f6", weight: 1, fillOpacity: 0.1, dashArray: "5,5",
        }).addTo(map!);
      }
    }

    if (drawMode) {
      map.getContainer().style.cursor = "crosshair";
      map.dragging.disable();
      map.on("click", handleClick);
      map.on("mousemove", handleMouseMove);
    } else {
      map.getContainer().style.cursor = "";
      map.dragging.enable();
      map.off("click", handleClick);
      map.off("mousemove", handleMouseMove);
      if (previewRectRef.current) { map.removeLayer(previewRectRef.current); previewRectRef.current = null; }
      firstCornerRef.current = null;
    }

    return () => { map.off("click", handleClick); map.off("mousemove", handleMouseMove); };
  }, [drawMode]);

  // ─── Lead markers (numbered, typed, colored) ───
  useEffect(() => {
    const map = mapInstance.current;
    if (!map) return;

    markersRef.current.forEach((m) => map.removeLayer(m));
    markersRef.current.clear();

    for (const lead of leads) {
      if (!lead.latitude || !lead.longitude) continue;

      const fill = HEAT_FILL[lead.heat_score] || HEAT_FILL.none;
      const stage = STAGE_STYLES[lead.status] || STAGE_STYLES.NEW;
      const isSelected = lead.id === selectedLeadId;

      const icon = createNumberedIcon(lead.listIndex, fill, stage.border, isSelected);
      const marker = L.marker([lead.latitude, lead.longitude], { icon });

      marker.bindTooltip(`#${lead.listIndex} ${lead.name}`, { permanent: false, direction: "top", offset: [0, -14] });
      marker.on("click", () => onMarkerClick?.(lead.id));
      marker.addTo(map);
      markersRef.current.set(lead.id, marker);
    }
  }, [leads, selectedLeadId, onMarkerClick]);

  // ─── Highlight hovered lead ───
  useEffect(() => {
    const map = mapInstance.current;
    if (!map) return;

    markersRef.current.forEach((marker, id) => {
      const lead = leads.find(l => l.id === id);
      if (!lead) return;
      const fill = HEAT_FILL[lead.heat_score] || HEAT_FILL.none;
      const stage = STAGE_STYLES[lead.status] || STAGE_STYLES.NEW;
      const isHovered = id === hoveredLeadId;
      const isSelected = id === selectedLeadId;

      marker.setIcon(createNumberedIcon(lead.listIndex, fill, stage.border, isHovered || isSelected));
      if (isHovered) marker.openTooltip();
      else if (!isSelected) marker.closeTooltip();
    });
  }, [hoveredLeadId, selectedLeadId, leads]);

  // ─── Fly to target ───
  useEffect(() => {
    if (flyToTarget && mapInstance.current) {
      mapInstance.current.setView([flyToTarget.lat, flyToTarget.lng], 16);
    }
  }, [flyToTarget]);

  // ─── Search ───
  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!mapInstance.current || !searchQuery) return;
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(searchQuery + ", Florida")}&limit=1`,
        { headers: { "User-Agent": "insure-lead-gen" } }
      );
      const data = await res.json();
      if (data.length > 0) {
        mapInstance.current.setView([parseFloat(data[0].lat), parseFloat(data[0].lon)], 14);
      }
    } catch (err) { console.error("Search failed:", err); }
  }

  // ─── Region submit ───
  async function handleSubmitRegion(e: React.FormEvent) {
    e.preventDefault();
    if (!pendingBounds) return;
    setSubmitError(null);
    setSubmitting(true);
    try {
      const res = await fetch(`/api/proxy/regions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: formData.name, bounding_box: pendingBounds,
          parameters: { stories: formData.stories, coast_distance: formData.coastDistance },
        }),
      });
      if (res.ok) {
        setShowForm(false);
        setFormData({ name: "", stories: 3, coastDistance: 5 });
        setPendingBounds(null);
        onRegionCreated();
      } else {
        const errData = await res.json().catch(() => ({}));
        setSubmitError(errData.detail || `Failed (${res.status})`);
      }
    } catch (err) { setSubmitError("Unable to connect to API"); }
    setSubmitting(false);
  }

  function handleCancelRegion() {
    if (regionsLayerRef.current) {
      const layers = regionsLayerRef.current.getLayers();
      if (layers.length > 0) regionsLayerRef.current.removeLayer(layers[layers.length - 1]);
    }
    setPendingBounds(null);
    setShowForm(false);
  }

  return (
    <div className="relative w-full h-full">
      {/* Search bar */}
      <form onSubmit={handleSearch} className="absolute top-3 left-3 z-[1000] flex gap-2">
        <input type="text" placeholder="Search zip or address..."
          value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
          className="bg-gray-900/90 border border-gray-700 rounded px-3 py-2 text-white text-sm w-56 focus:outline-none focus:border-blue-500" />
        <button type="submit" className="bg-blue-600 hover:bg-blue-700 text-white px-3 py-2 rounded text-sm font-medium">Go</button>
      </form>

      {/* Map tools */}
      <div className="absolute top-3 right-3 z-[1000] flex flex-col gap-1.5">
        <button onClick={() => setDrawMode(!drawMode)}
          className={`px-3 py-2 rounded text-sm font-medium shadow-lg ${drawMode ? "bg-blue-600 text-white ring-2 ring-blue-400" : "bg-gray-900/90 text-gray-300 hover:bg-gray-800 border border-gray-700"}`}>
          {drawMode ? "Click 2 corners..." : "Draw Region"}
        </button>
        <button onClick={() => mapInstance.current?.zoomIn()}
          className="bg-gray-900/90 border border-gray-700 text-gray-300 hover:bg-gray-800 px-3 py-1.5 rounded text-sm shadow-lg">+</button>
        <button onClick={() => mapInstance.current?.zoomOut()}
          className="bg-gray-900/90 border border-gray-700 text-gray-300 hover:bg-gray-800 px-3 py-1.5 rounded text-sm shadow-lg">&minus;</button>
      </div>

      {/* Legend */}
      <div className="absolute bottom-6 left-3 z-[1000] bg-gray-900/90 border border-gray-700 rounded px-3 py-2 text-[10px] space-y-1">
        <p className="text-gray-500 font-semibold mb-1">Rank Color</p>
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-red-500" /> Hot</div>
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-orange-500" /> Warm</div>
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-blue-500" /> Cool</div>
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-gray-500" /> New</div>
        <p className="text-gray-500 font-semibold mt-1.5 mb-1">Border = Stage</p>
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full border-2 border-green-500" /> Customer</div>
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full border-2 border-blue-500" /> Opportunity</div>
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full border-2 border-amber-500" /> Target</div>
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full border-2 border-purple-500" /> Candidate</div>
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full border-2 border-gray-500" /> New</div>
      </div>

      {/* Map */}
      <div ref={mapRef} className="w-full h-full" />

      {/* Region form */}
      {showForm && (
        <div className="absolute inset-0 bg-black/50 flex items-center justify-center z-[1001]">
          <form onSubmit={handleSubmitRegion} className="bg-gray-900 p-6 rounded-xl border border-gray-700 w-80">
            <h3 className="text-lg font-bold mb-4">New Hunt Region</h3>
            {pendingBounds && (
              <p className="text-gray-500 text-xs mb-3">
                {pendingBounds.south.toFixed(4)}°N – {pendingBounds.north.toFixed(4)}°N,{" "}
                {Math.abs(pendingBounds.west).toFixed(4)}°W – {Math.abs(pendingBounds.east).toFixed(4)}°W
              </p>
            )}
            <div className="mb-3">
              <label className="block text-gray-400 text-sm mb-1">Region Name</label>
              <input type="text" required value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm" placeholder="e.g. Clearwater Beach Condos" />
            </div>
            <div className="mb-3">
              <label className="block text-gray-400 text-sm mb-1">Min Stories</label>
              <input type="number" min={1} value={formData.stories}
                onChange={(e) => setFormData({ ...formData, stories: parseInt(e.target.value) })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm" />
            </div>
            <div className="mb-4">
              <label className="block text-gray-400 text-sm mb-1">Max Coast Distance (mi)</label>
              <input type="number" min={0} step={0.1} value={formData.coastDistance}
                onChange={(e) => setFormData({ ...formData, coastDistance: parseFloat(e.target.value) })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm" />
            </div>
            {submitError && <p className="text-red-400 text-xs mb-3">{submitError}</p>}
            <div className="flex gap-2">
              <button type="submit" disabled={submitting}
                className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold py-2 rounded text-sm">
                {submitting ? "Creating..." : "Start Hunt"}
              </button>
              <button type="button" onClick={handleCancelRegion}
                className="flex-1 bg-gray-700 hover:bg-gray-600 text-white font-semibold py-2 rounded text-sm">Cancel</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
