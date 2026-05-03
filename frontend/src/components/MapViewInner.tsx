"use client";

import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

type BaseLayerKey = "street" | "satellite" | "hybrid";

const BASE_LAYER_LABELS: Record<BaseLayerKey, string> = {
  street: "Street",
  satellite: "Satellite",
  hybrid: "Hybrid",
};

const STORAGE_KEY_LAYER = "insure_map_layer";

// Fallback center — Pinellas Park, FL
const FALLBACK_CENTER: [number, number] = [27.8428, -82.6993];
const FALLBACK_ZOOM = 12;
const STORAGE_KEY = "insure_map_view";

// Pipeline stage → border color
const STAGE_STYLES: Record<string, { border: string }> = {
  TARGET:      { border: "#6b7280" }, // gray
  LEAD:        { border: "#06b6d4" }, // cyan
  VETTED:      { border: "#14b8a6" }, // teal
  ANALYZED:    { border: "#6366f1" }, // indigo
  VALIDATED:   { border: "#a855f7" }, // purple
  OPPORTUNITY: { border: "#f59e0b" }, // amber
  CUSTOMER:    { border: "#22c55e" }, // green
  ARCHIVED:    { border: "#450a0a" }, // dark red
};

// Heat score → fill color override for ranking
const HEAT_FILL: Record<string, string> = {
  hot:  "#ef4444",  // red
  warm: "#f97316",  // orange
  cold: "#3b82f6",  // blue (also matches "cool")
  cool: "#3b82f6",  // alias
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

interface Props {
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
  leads = [], hoveredLeadId, selectedLeadId, flyToTarget, onMarkerClick,
}: Props) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<L.Map | null>(null);
  const markersRef = useRef<Map<number, L.Marker>>(new Map());
  const baseLayersRef = useRef<Record<BaseLayerKey, L.Layer> | null>(null);
  const activeBaseLayerRef = useRef<L.Layer | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [activeLayer, setActiveLayer] = useState<BaseLayerKey>(() => {
    if (typeof window === "undefined") return "street";
    const saved = localStorage.getItem(STORAGE_KEY_LAYER) as BaseLayerKey | null;
    return saved && saved in BASE_LAYER_LABELS ? saved : "street";
  });

  // ─── Init map with saved position ───
  useEffect(() => {
    if (!mapRef.current || mapInstance.current) return;

    const { center, zoom } = getSavedView();

    const map = L.map(mapRef.current, {
      center,
      zoom,
      maxZoom: 21,
      zoomSnap: 1,
      zoomAnimation: false,
      fadeAnimation: false,
      markerZoomAnimation: false,
      inertia: false,
      zoomControl: false, // We use custom controls
    });

    // ─── Base layers ───
    const osmStreets = L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
        maxZoom: 21,
        maxNativeZoom: 19,
      },
    );

    const esriSatellite = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: '&copy; Esri, Maxar, Earthstar Geographics',
        maxZoom: 21,
        maxNativeZoom: 19,
      },
    );

    const esriHybrid = L.layerGroup([
      esriSatellite,
      L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}",
        { maxZoom: 21, maxNativeZoom: 19, pane: "overlayPane" },
      ),
      L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        { maxZoom: 21, maxNativeZoom: 19, pane: "overlayPane" },
      ),
    ]);

    const layers: Record<BaseLayerKey, L.Layer> = {
      street: osmStreets,
      satellite: esriSatellite,
      hybrid: esriHybrid,
    };
    baseLayersRef.current = layers;

    // Add the user's previously-chosen base layer (or street by default).
    const initial = layers[activeLayer] ?? layers.street;
    initial.addTo(map);
    activeBaseLayerRef.current = initial;

    // Save position on every move/zoom
    map.on("moveend", () => {
      const c = map.getCenter();
      saveView([c.lat, c.lng], map.getZoom());
    });

    mapInstance.current = map;

    return () => {
      map.remove();
      mapInstance.current = null;
    };
  }, []);

  // ─── Swap base layer when the user clicks Street/Satellite/Hybrid ───
  useEffect(() => {
    const map = mapInstance.current;
    const layers = baseLayersRef.current;
    if (!map || !layers) return;

    const next = layers[activeLayer];
    if (!next || next === activeBaseLayerRef.current) return;

    if (activeBaseLayerRef.current) {
      map.removeLayer(activeBaseLayerRef.current);
    }
    next.addTo(map);
    // Send tile layer to the back so markers / popups stay above it.
    if ("bringToBack" in next && typeof (next as L.TileLayer).bringToBack === "function") {
      (next as L.TileLayer).bringToBack();
    }
    activeBaseLayerRef.current = next;

    try {
      localStorage.setItem(STORAGE_KEY_LAYER, activeLayer);
    } catch {}
  }, [activeLayer]);

  // ─── Lead markers (numbered, typed, colored) ───
  useEffect(() => {
    const map = mapInstance.current;
    if (!map) return;

    markersRef.current.forEach((m) => map.removeLayer(m));
    markersRef.current.clear();

    for (const lead of leads) {
      if (lead.latitude == null || lead.longitude == null) continue;

      const fill = HEAT_FILL[lead.heat_score] || HEAT_FILL.none;
      const stage = STAGE_STYLES[lead.status] || STAGE_STYLES.TARGET;
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
      const stage = STAGE_STYLES[lead.status] || STAGE_STYLES.TARGET;
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
      if (!res.ok) return;
      const data = await res.json();
      if (data.length > 0) {
        mapInstance.current.setView([parseFloat(data[0].lat), parseFloat(data[0].lon)], 14);
      }
    } catch (err) { console.error("Search failed:", err); }
  }

  return (
    <div className="relative w-full h-full">
      {/* Search bar */}
      <form onSubmit={handleSearch} className="absolute top-3 left-3 z-[1000] flex gap-2">
        <input type="text" placeholder="Search zip or address..."
          value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
          className="bg-gray-900/90 border border-gray-700 rounded px-3 py-2 text-white text-sm w-40 sm:w-56 focus:outline-none focus:border-blue-500" />
        <button type="submit" className="bg-blue-600 hover:bg-blue-700 text-white px-3 py-2 rounded text-sm font-medium">Go</button>
      </form>

      {/* Map tools */}
      <div className="absolute top-3 right-3 z-[1000] flex flex-col gap-1.5 items-end">
        <button onClick={() => mapInstance.current?.zoomIn()}
          className="bg-gray-900/90 border border-gray-700 text-gray-300 hover:bg-gray-800 px-3 py-1.5 rounded text-sm shadow-lg">+</button>
        <button onClick={() => mapInstance.current?.zoomOut()}
          className="bg-gray-900/90 border border-gray-700 text-gray-300 hover:bg-gray-800 px-3 py-1.5 rounded text-sm shadow-lg">&minus;</button>

        {/* Base-layer toggle — Street / Satellite / Hybrid. We use a custom
            React control rather than Leaflet's built-in L.control.layers
            because the latter rendered invisible against this dark theme
            in some viewport setups. */}
        <div className="bg-gray-900/90 border border-gray-700 rounded shadow-lg flex flex-col overflow-hidden">
          {(Object.keys(BASE_LAYER_LABELS) as BaseLayerKey[]).map((key) => (
            <button
              key={key}
              onClick={() => setActiveLayer(key)}
              className={`px-3 py-1.5 text-[11px] font-medium text-left whitespace-nowrap border-b border-gray-800 last:border-b-0 ${
                activeLayer === key
                  ? "bg-blue-700 text-white"
                  : "text-gray-300 hover:bg-gray-800"
              }`}
            >
              {BASE_LAYER_LABELS[key]}
            </button>
          ))}
        </div>
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
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full border-2 border-amber-500" /> Opportunity</div>
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full border-2 border-cyan-500" /> Lead</div>
        <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full border-2 border-gray-500" /> Target</div>
      </div>

      {/* Map */}
      <div ref={mapRef} className="w-full h-full" />
    </div>
  );
}
