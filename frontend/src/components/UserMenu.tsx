"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";

/**
 * User account chip + dropdown menu shown in the top-right of every header.
 * Displays current user's initial + name, expands to show role and log-out
 * action.
 */
export default function UserMenu() {
  const { displayName, role, isAdmin, isViewer, loading, authenticated } = useAuth();
  const [open, setOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const router = useRouter();

  // Close when clicking outside
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/auth", { method: "DELETE" });
    } catch {}
    try {
      sessionStorage.removeItem("insure_auth");
    } catch {}
    router.push("/login");
    router.refresh();
  }

  if (loading || !authenticated) return null;

  const initial = (displayName?.[0] ?? "?").toUpperCase();
  const chipColor = isAdmin
    ? "bg-purple-700 hover:bg-purple-600"
    : isViewer
      ? "bg-gray-600 hover:bg-gray-500"
      : "bg-blue-700 hover:bg-blue-600";
  const chipSolid = isAdmin ? "bg-purple-700" : isViewer ? "bg-gray-600" : "bg-blue-700";
  const roleLabel = isAdmin ? "Admin" : isViewer ? "Viewer" : "User";

  return (
    <div ref={menuRef} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 group"
        title={`${displayName} — ${role}`}
      >
        <span className={`w-6 h-6 rounded-full ${chipColor} text-white text-[10px] font-bold flex items-center justify-center transition-colors`}>
          {initial}
        </span>
        <span className="hidden sm:inline text-xs text-gray-400 group-hover:text-white transition-colors">
          {displayName}
        </span>
        <span className="text-gray-600 text-[10px]">▾</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-52 bg-gray-900 border border-gray-700 rounded-lg shadow-xl z-50 overflow-hidden">
          <div className="px-3 py-2.5 border-b border-gray-800 bg-gray-900">
            <div className="flex items-center gap-2">
              <span className={`w-8 h-8 rounded-full ${chipSolid} text-white text-sm font-bold flex items-center justify-center`}>
                {initial}
              </span>
              <div>
                <p className="text-xs text-white font-semibold">{displayName}</p>
                <p className="text-[10px] text-gray-500 uppercase tracking-wider">
                  {roleLabel}
                </p>
              </div>
            </div>
          </div>

          <div className="py-1">
            <button
              onClick={() => {
                setOpen(false);
                router.push("/help");
              }}
              className="w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-800 transition-colors"
            >
              ? Help
            </button>
            <button
              onClick={logout}
              disabled={loggingOut}
              className="w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-red-900/40 transition-colors disabled:opacity-50"
            >
              {loggingOut ? "Logging out..." : "Log Out"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
