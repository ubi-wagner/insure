"use client";

import { useEffect, useRef, useState } from "react";
import { Loader } from "@googlemaps/js-api-loader";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface RegionFormData {
  name: string;
  stories: number;
  coastDistance: number;
}

export default function MapView({ onRegionCreated }: { onRegionCreated: () => void }) {
  const mapRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<google.maps.Map | null>(null);
  const [pendingRect, setPendingRect] = useState<google.maps.Rectangle | null>(null);
  const [pendingBounds, setPendingBounds] = useState<{ north: number; south: number; east: number; west: number } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState<RegionFormData>({ name: "", stories: 3, coastDistance: 5 });
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
    if (!apiKey) {
      console.error("Google Maps API key not set");
      return;
    }

    const loader = new Loader({
      apiKey,
      version: "weekly",
      libraries: ["drawing", "places", "geocoding"],
    });

    loader.importLibrary("maps").then(() => {
      loader.importLibrary("drawing").then(() => {
        if (!mapRef.current) return;

        const mapInstance = new google.maps.Map(mapRef.current, {
          center: { lat: 27.9506, lng: -82.4572 }, // Tampa, FL
          zoom: 10,
          mapTypeId: "hybrid",
          styles: [{ featureType: "all", elementType: "labels", stylers: [{ visibility: "on" }] }],
        });

        const drawingManager = new google.maps.drawing.DrawingManager({
          drawingMode: null,
          drawingControl: true,
          drawingControlOptions: {
            position: google.maps.ControlPosition.TOP_CENTER,
            drawingModes: [google.maps.drawing.OverlayType.RECTANGLE],
          },
          rectangleOptions: {
            fillColor: "#3b82f6",
            fillOpacity: 0.2,
            strokeWeight: 2,
            strokeColor: "#3b82f6",
            editable: true,
          },
        });

        drawingManager.setMap(mapInstance);

        google.maps.event.addListener(drawingManager, "rectanglecomplete", (rectangle: google.maps.Rectangle) => {
          drawingManager.setDrawingMode(null);
          const bounds = rectangle.getBounds();
          if (!bounds) return;

          const ne = bounds.getNorthEast();
          const sw = bounds.getSouthWest();

          setPendingRect(rectangle);
          setPendingBounds({
            north: ne.lat(),
            south: sw.lat(),
            east: ne.lng(),
            west: sw.lng(),
          });
          setShowForm(true);
        });

        setMap(mapInstance);
      });
    });
  }, []);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!map || !searchQuery) return;

    const geocoder = new google.maps.Geocoder();
    geocoder.geocode({ address: searchQuery + ", Florida" }, (results, status) => {
      if (status === "OK" && results && results[0]) {
        map.setCenter(results[0].geometry.location);
        map.setZoom(14);
      }
    });
  }

  async function handleSubmitRegion(e: React.FormEvent) {
    e.preventDefault();
    if (!pendingBounds) return;

    try {
      const res = await fetch(`${API_URL}/api/regions`, {
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
      }
    } catch (err) {
      console.error("Failed to create region:", err);
    }
  }

  function handleCancelRegion() {
    if (pendingRect) {
      pendingRect.setMap(null);
      setPendingRect(null);
    }
    setPendingBounds(null);
    setShowForm(false);
  }

  return (
    <div className="relative">
      {/* Search bar */}
      <form onSubmit={handleSearch} className="absolute top-3 left-3 z-10 flex gap-2">
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
      <div ref={mapRef} className="w-full h-[500px] rounded-lg" />

      {/* Region form modal */}
      {showForm && (
        <div className="absolute inset-0 bg-black/50 flex items-center justify-center z-20">
          <form
            onSubmit={handleSubmitRegion}
            className="bg-gray-900 p-6 rounded-xl border border-gray-700 w-80"
          >
            <h3 className="text-lg font-bold mb-4">New Hunt Region</h3>

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

            <div className="flex gap-2">
              <button
                type="submit"
                className="flex-1 bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 rounded text-sm"
              >
                Start Hunt
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
