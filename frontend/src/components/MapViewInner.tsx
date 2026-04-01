"use client";

import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet-draw";
import "leaflet-draw/dist/leaflet.draw.css";

// Pinellas Park, FL — default home base
const DEFAULT_CENTER: [number, number] = [27.8428, -82.6993];
const DEFAULT_ZOOM = 12;

interface RegionFormData {
  name: string;
  stories: number;
  coastDistance: number;
}

export default function MapViewInner({ onRegionCreated }: { onRegionCreated: () => void }) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<L.Map | null>(null);
  const [pendingBounds, setPendingBounds] = useState<{ north: number; south: number; east: number; west: number } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState<RegionFormData>({ name: "", stories: 3, coastDistance: 5 });
  const [searchQuery, setSearchQuery] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const drawnLayerRef = useRef<L.Layer | null>(null);
  const drawnItemsRef = useRef<L.FeatureGroup | null>(null);

  useEffect(() => {
    if (!mapRef.current || mapInstance.current) return;

    const map = L.map(mapRef.current, {
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      zoomControl: true,
    });

    // OpenStreetMap tile layer
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(map);

    // Home base marker
    L.circleMarker(DEFAULT_CENTER, {
      radius: 8,
      fillColor: "#3b82f6",
      fillOpacity: 1,
      color: "#1e40af",
      weight: 2,
    })
      .bindTooltip("Home Base — Pinellas Park, FL", { permanent: false })
      .addTo(map);

    // Drawing layer
    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);
    drawnItemsRef.current = drawnItems;

    // Drawing controls
    const drawControl = new L.Control.Draw({
      position: "topright",
      draw: {
        rectangle: {
          shapeOptions: {
            color: "#3b82f6",
            weight: 2,
            fillOpacity: 0.15,
          },
        },
        polyline: false,
        polygon: false,
        circle: false,
        marker: false,
        circlemarker: false,
      },
      edit: {
        featureGroup: drawnItems,
      },
    });
    map.addControl(drawControl);

    // Handle rectangle drawn
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.on(L.Draw.Event.CREATED, (e: any) => {
      const layer = e.layer;
      drawnItems.addLayer(layer);
      drawnLayerRef.current = layer;

      const bounds = (layer as L.Rectangle).getBounds();
      setPendingBounds({
        north: bounds.getNorth(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        west: bounds.getWest(),
      });
      setShowForm(true);
    });

    mapInstance.current = map;

    return () => {
      map.remove();
      mapInstance.current = null;
    };
  }, []);

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
    if (drawnLayerRef.current && drawnItemsRef.current) {
      drawnItemsRef.current.removeLayer(drawnLayerRef.current);
      drawnLayerRef.current = null;
    }
    setPendingBounds(null);
    setShowForm(false);
  }

  return (
    <div className="relative w-full h-full">
      {/* Search bar */}
      <form onSubmit={handleSearch} className="absolute top-3 left-3 z-[1000] flex gap-2">
        <input
          type="text"
          placeholder="Search zip code or address..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="bg-gray-900/90 border border-gray-700 rounded px-3 py-2 text-white text-sm w-64 focus:outline-none focus:border-blue-500"
        />
        <button
          type="submit"
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm font-medium"
        >
          Go
        </button>
      </form>

      {/* Map */}
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
                {pendingBounds.south.toFixed(4)}N to {pendingBounds.north.toFixed(4)}N,{" "}
                {pendingBounds.west.toFixed(4)}W to {pendingBounds.east.toFixed(4)}W
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
