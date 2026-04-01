"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import MapView from "@/components/MapView";
import LeadPipeline from "@/components/LeadPipeline";

export default function Dashboard() {
  const [refreshKey, setRefreshKey] = useState(0);
  const router = useRouter();

  async function handleLogout() {
    await fetch("/api/auth", { method: "DELETE" });
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="min-h-screen">
      {/* Top Bar */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center justify-between">
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

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-8">
        {/* Map Section */}
        <section>
          <h2 className="text-xl font-bold mb-3">Region Targeting</h2>
          <MapView onRegionCreated={() => setRefreshKey((k) => k + 1)} />
        </section>

        {/* Pipeline Section */}
        <section>
          <LeadPipeline refreshKey={refreshKey} />
        </section>
      </main>
    </div>
  );
}
