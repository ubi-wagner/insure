"use client";

import { useState } from "react";
import Link from "next/link";
import UserMenu from "@/components/UserMenu";

type TabName = "compare" | "events";

export default function ValidationPage() {
  const [tab, setTab] = useState<TabName>("compare");

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="bg-gray-900 border-b border-gray-800 px-4 md:px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-blue-400 hover:text-blue-300 text-xs">&larr; Pipeline</Link>
          <h1 className="text-base font-bold tracking-tight">Validation</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/ops" className="text-gray-500 hover:text-white text-xs">Ops</Link>
          <Link href="/files" className="text-gray-500 hover:text-white text-xs">Files</Link>
          <Link href="/ref" className="text-gray-500 hover:text-white text-xs">Ref</Link>
          <UserMenu />
        </div>
      </header>

      <div className="px-4 md:px-6 py-4">
        <div className="flex items-center gap-1 border-b border-gray-800 mb-4">
          <TabButton active={tab === "compare"} onClick={() => setTab("compare")}>
            Bulk Compare
          </TabButton>
          <TabButton active={tab === "events"} onClick={() => setTab("events")}>
            Events
          </TabButton>
        </div>

        {tab === "compare" && (
          <div className="text-gray-500 text-sm py-12 text-center border border-dashed border-gray-800 rounded-lg">
            Bulk Compare — coming next build
          </div>
        )}

        {tab === "events" && (
          <div className="text-gray-500 text-sm py-12 text-center border border-dashed border-gray-800 rounded-lg">
            Events stream — coming next build
          </div>
        )}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
        active
          ? "border-blue-500 text-blue-400"
          : "border-transparent text-gray-500 hover:text-gray-300"
      }`}
    >
      {children}
    </button>
  );
}
