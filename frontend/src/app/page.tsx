"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import MapView from "@/components/MapView";
import LeadPipeline from "@/components/LeadPipeline";
import StatusBar from "@/components/StatusBar";

export default function Dashboard() {
  const [refreshKey, setRefreshKey] = useState(0);
  const router = useRouter();

  async function handleLogout() {
    await fetch("/api/auth", { method: "DELETE" });
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="h-screen flex flex-col">
      {/* Top Bar */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-2 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-bold">Insure</h1>
          <span className="text-gray-500 text-sm">Hunt · Kill · Cook</span>
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/events"
            className="text-gray-400 hover:text-white text-sm"
          >
            Event Stream
          </Link>
          <button
            onClick={handleLogout}
            className="text-gray-400 hover:text-white text-sm"
          >
            Logout
          </button>
        </div>
      </header>

      <StatusBar />

      {/* Split layout: map left, cards right */}
      <main className="flex-1 flex overflow-hidden">
        {/* Map panel — fills left side */}
        <div className="flex-1 relative">
          <MapView onRegionCreated={() => setRefreshKey((k) => k + 1)} />
        </div>

        {/* Lead panel — scrollable right sidebar */}
        <div className="w-[420px] border-l border-gray-800 bg-gray-950 flex flex-col shrink-0">
          <div className="p-4 overflow-y-auto flex-1">
            <LeadPipeline refreshKey={refreshKey} />
          </div>
        </div>
      </main>
    </div>
  );
}
