"use client";

import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Pinellas Park, FL — default home base
const DEFAULT_CENTER: [number, number] = [27.8428, -82.6993];
const DEFAULT_ZOOM = 12;

// Heat score → marker color
const HEAT_COLORS: Record<string, string> = {
  hot: "#ef4444",
  warm: "#f97316",
  cool: "#3b82f6",
  none: "#6b7280",
};

const STATUS_BORDER: Record<string, string> = {
  CANDIDATE: "#22c55e",
  REJECTED: "#991b1b",
  NEW: "#ffffff",
};

interface LeadLocation {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  heat_score: string;
  status: string;
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
  flyToTarget?: { lat: number; lng: number } | null;
}

export default function MapViewInner({ onRegionCreated, leads = [], hoveredLeadId, flyToTarget }: Props) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<L.Map | null>(null);
  const markersRef = useRef<Map<number, L.CircleMarker>>(new Map());
  const regionsLayerRef = useRef<L.FeatureGroup | null>(null);

  // Two-click rectangle state
  const [drawMode, setDrawMode] = useState(false);
  const firstCornerRef = useRef<L.LatLng | null>(null);
  const previewRectRef = useRef<L.Rectangle | null>(null);

  const [pendingBounds, setPendingBounds] = useState<{ north: number; south: number; east: number; west: number } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState<RegionFormData>({ name: "", stories: 3, coastDistance: 5 });
  const [searchQuery, setSearchQuery] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // ─── Init map ───
  useEffect(() => {
    if (!mapRef.current || mapInstance.current) return;

    const map = L.map(mapRef.current, {
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      zoomSnap: 1,           // Discrete zoom steps
      zoomAnimation: false,   // No smooth zoom
      fadeAnimation: false,    // No tile fade
      markerZoomAnimation: false,
      inertia: false,         // No pan momentum
    });

    // OSM tiles
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
      maxZoom: 19,
    }).addTo(map);

    // Home marker
    L.circleMarker(DEFAULT_CENTER, {
      radius: 10,
      fillColor: "#3b82f6",
      fillOpacity: 1,
      color: "#1e40af",
      weight: 3,
    })
      .bindTooltip("Home — Pinellas Park, FL", { permanent: false })
      .addTo(map);

    // Layer for drawn regions
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
        // First click — set first corner
        firstCornerRef.current = e.latlng;
        // Show crosshair cursor
        map!.getContainer().style.cursor = "crosshair";
      } else {
        // Second click — complete rectangle
        const corner1 = firstCornerRef.current;
        const corner2 = e.latlng;

        const bounds = L.latLngBounds(corner1, corner2);

        // Remove preview
        if (previewRectRef.current) {
          map!.removeLayer(previewRectRef.current);
          previewRectRef.current = null;
        }

        // Draw final rectangle
        const rect = L.rectangle(bounds, {
          color: "#3b82f6",
          weight: 2,
          fillOpacity: 0.15,
        });
        regionsLayerRef.current?.addLayer(rect);

        setPendingBounds({
          north: bounds.getNorth(),
          south: bounds.getSouth(),
          east: bounds.getEast(),
          west: bounds.getWest(),
        });

        // Reset
        firstCornerRef.current = null;
        map!.getContainer().style.cursor = "";
        setDrawMode(false);
        setShowForm(true);
      }
    }

    function handleMouseMove(e: L.LeafletMouseEvent) {
      if (!firstCornerRef.current) return;
      // Update preview rectangle
      const bounds = L.latLngBounds(firstCornerRef.current, e.latlng);
      if (previewRectRef.current) {
        previewRectRef.current.setBounds(bounds);
      } else {
        previewRectRef.current = L.rectangle(bounds, {
          color: "#3b82f6",
          weight: 1,
          fillOpacity: 0.1,
          dashArray: "5,5",
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
      // Clean up preview if draw cancelled
      if (previewRectRef.current) {
        map.removeLayer(previewRectRef.current);
        previewRectRef.current = null;
      }
      firstCornerRef.current = null;
    }

    return () => {
      map.off("click", handleClick);
      map.off("mousemove", handleMouseMove);
    };
  }, [drawMode]);

  // ─── Lead markers ───
  useEffect(() => {
    const map = mapInstance.current;
    if (!map) return;

    // Remove old markers
    markersRef.current.forEach((marker) => map.removeLayer(marker));
    markersRef.current.clear();

    // Add markers for leads with coordinates
    for (const lead of leads) {
      if (!lead.latitude || !lead.longitude) continue;

      const fill = HEAT_COLORS[lead.heat_score] || HEAT_COLORS.none;
      const border = STATUS_BORDER[lead.status] || STATUS_BORDER.NEW;

      const marker = L.circleMarker([lead.latitude, lead.longitude], {
        radius: 7,
        fillColor: fill,
        fillOpacity: 0.9,
        color: border,
        weight: 2,
      });

      marker.bindTooltip(lead.name, { permanent: false, direction: "top", offset: [0, -8] });
      marker.addTo(map);
      markersRef.current.set(lead.id, marker);
    }
  }, [leads]);

  // ─── Highlight hovered lead ───
  useEffect(() => {
    markersRef.current.forEach((marker, id) => {
      if (id === hoveredLeadId) {
        marker.setRadius(12);
        marker.setStyle({ weight: 3 });
        marker.openTooltip();
      } else {
        marker.setRadius(7);
        marker.setStyle({ weight: 2 });
        marker.closeTooltip();
      }
    });
  }, [hoveredLeadId]);

  // ─── Fly to target ───
  useEffect(() => {
    if (flyToTarget && mapInstance.current) {
      mapInstance.current.setView([flyToTarget.lat, flyToTarget.lng], 15);
    }
  }, [flyToTarget]);

  // ─── Search (Nominatim) ───
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
        const { lat, lon } = data[0];
        mapInstance.current.setView([parseFloat(lat), parseFloat(lon)], 14);
      }
    } catch (err) {
      console.error("Search failed:", err);
    }
  }

  // ─── Region submission ───
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
          name: formData.name,
          bounding_box: pendingBounds,
          parameters: {
            stories: formData.stories,
            coast_distance: formData.coastDistance,
          },
        }),
      });

      if (res.ok) {
        setShowForm(false);
        setFormData({ name: "", stories: 3, coastDistance: 5 });
        setPendingBounds(null);
        onRegionCreated();
      } else {
        const errData = await res.json().catch(() => ({}));
        setSubmitError(errData.detail || `Failed to create region (${res.status})`);
      }
    } catch (err) {
      console.error("Failed to create region:", err);
      setSubmitError("Unable to connect to API");
    }
    setSubmitting(false);
  }

  function handleCancelRegion() {
    // Remove last drawn rectangle
    if (regionsLayerRef.current) {
      const layers = regionsLayerRef.current.getLayers();
      if (layers.length > 0) {
        regionsLayerRef.current.removeLayer(layers[layers.length - 1]);
      }
    }
    setPendingBounds(null);
    setShowForm(false);
  }

  function handleGoHome() {
    mapInstance.current?.setView(DEFAULT_CENTER, DEFAULT_ZOOM);
  }

  return (
    <div className="relative w-full h-full">
      {/* Top-left: Search bar */}
      <form onSubmit={handleSearch} className="absolute top-3 left-3 z-[1000] flex gap-2">
        <input
          type="text"
          placeholder="Search zip or address..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="bg-gray-900/90 border border-gray-700 rounded px-3 py-2 text-white text-sm w-56 focus:outline-none focus:border-blue-500"
        />
        <button type="submit" className="bg-blue-600 hover:bg-blue-700 text-white px-3 py-2 rounded text-sm font-medium">
          Go
        </button>
      </form>

      {/* Top-right: Map tools */}
      <div className="absolute top-3 right-3 z-[1000] flex flex-col gap-1.5">
        <button
          onClick={() => setDrawMode(!drawMode)}
          className={`px-3 py-2 rounded text-sm font-medium shadow-lg ${
            drawMode
              ? "bg-blue-600 text-white ring-2 ring-blue-400"
              : "bg-gray-900/90 text-gray-300 hover:bg-gray-800 border border-gray-700"
          }`}
          title="Draw hunt region (click two corners)"
        >
          {drawMode ? "Drawing... (click 2 corners)" : "Draw Region"}
        </button>
        <button
          onClick={handleGoHome}
          className="bg-gray-900/90 border border-gray-700 text-gray-300 hover:bg-gray-800 px-3 py-2 rounded text-sm shadow-lg"
          title="Return to Pinellas Park"
        >
          Home
        </button>
        <button
          onClick={() => mapInstance.current?.zoomIn()}
          className="bg-gray-900/90 border border-gray-700 text-gray-300 hover:bg-gray-800 px-3 py-1.5 rounded text-sm shadow-lg"
        >
          +
        </button>
        <button
          onClick={() => mapInstance.current?.zoomOut()}
          className="bg-gray-900/90 border border-gray-700 text-gray-300 hover:bg-gray-800 px-3 py-1.5 rounded text-sm shadow-lg"
        >
          −
        </button>
      </div>

      {/* Bottom-left: Legend */}
      <div className="absolute bottom-6 left-3 z-[1000] bg-gray-900/90 border border-gray-700 rounded px-3 py-2 text-xs space-y-1">
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-red-500 inline-block" /> Hot</div>
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-orange-500 inline-block" /> Warm</div>
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-blue-500 inline-block" /> Cool</div>
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-gray-500 inline-block" /> New</div>
      </div>

      {/* Map container */}
      <div ref={mapRef} className="w-full h-full" />

      {/* Region form modal */}
      {showForm && (
        <div className="absolute inset-0 bg-black/50 flex items-center justify-center z-[1001]">
          <form
            onSubmit={handleSubmitRegion}
            className="bg-gray-900 p-6 rounded-xl border border-gray-700 w-80"
          >
            <h3 className="text-lg font-bold mb-4">New Hunt Region</h3>

            {pendingBounds && (
              <p className="text-gray-500 text-xs mb-3">
                {pendingBounds.south.toFixed(4)}°N to {pendingBounds.north.toFixed(4)}°N,{" "}
                {Math.abs(pendingBounds.west).toFixed(4)}°W to {Math.abs(pendingBounds.east).toFixed(4)}°W
              </p>
            )}

            <div className="mb-3">
              <label className="block text-gray-400 text-sm mb-1">Region Name</label>
              <input
                type="text"
                required
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                placeholder="e.g. Clearwater Beach Condos"
              />
            </div>

            <div className="mb-3">
              <label className="block text-gray-400 text-sm mb-1">Min Stories</label>
              <input
                type="number"
                min={1}
                value={formData.stories}
                onChange={(e) => setFormData({ ...formData, stories: parseInt(e.target.value) })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
              />
            </div>

            <div className="mb-4">
              <label className="block text-gray-400 text-sm mb-1">Max Coast Distance (mi)</label>
              <input
                type="number"
                min={0}
                step={0.1}
                value={formData.coastDistance}
                onChange={(e) => setFormData({ ...formData, coastDistance: parseFloat(e.target.value) })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
              />
            </div>

            {submitError && (
              <p className="text-red-400 text-xs mb-3">{submitError}</p>
            )}

            <div className="flex gap-2">
              <button
                type="submit"
                disabled={submitting}
                className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold py-2 rounded text-sm"
              >
                {submitting ? "Creating..." : "Start Hunt"}
              </button>
              <button
                type="button"
                onClick={handleCancelRegion}
                className="flex-1 bg-gray-700 hover:bg-gray-600 text-white font-semibold py-2 rounded text-sm"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
