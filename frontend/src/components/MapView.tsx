"use client";

import dynamic from "next/dynamic";

interface LeadLocation {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  heat_score: string;
  status: string;
}

interface MapViewProps {
  onRegionCreated: () => void;
  leads?: LeadLocation[];
  hoveredLeadId?: number | null;
  flyToTarget?: { lat: number; lng: number } | null;
}

const MapViewInner = dynamic(() => import("./MapViewInner"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full bg-gray-900 flex items-center justify-center">
      <div className="text-gray-500 text-sm">Loading map...</div>
    </div>
  ),
});

export default function MapView(props: MapViewProps) {
  return <MapViewInner {...props} />;
}
