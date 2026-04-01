"use client";

import dynamic from "next/dynamic";

const MapViewInner = dynamic(() => import("./MapViewInner"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full bg-gray-900 flex items-center justify-center">
      <div className="text-gray-500 text-sm">Loading map...</div>
    </div>
  ),
});

export default function MapView({ onRegionCreated }: { onRegionCreated: () => void }) {
  return <MapViewInner onRegionCreated={onRegionCreated} />;
}
