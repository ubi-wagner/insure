"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Lead {
  id: number;
  name: string;
  address: string;
  county: string;
  latitude: number;
  longitude: number;
  characteristics: Record<string, unknown> | null;
  created_at: string;
  status: string;
  emails?: Record<string, string> | null;
}

type SortBy = "date" | "coast_distance";

export default function LeadPipeline({ refreshKey }: { refreshKey: number }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [sortBy, setSortBy] = useState<SortBy>("date");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [votingId, setVotingId] = useState<number | null>(null);

  useEffect(() => {
    fetchLeads();
  }, [refreshKey, sortBy]);

  async function fetchLeads() {
    setFetchError(null);
    try {
      const res = await fetch(`${API_URL}/api/leads?sort_by=${sortBy}`, {
        credentials: "include",
      });
      if (res.ok) {
        const data = await res.json();
        setLeads(data);
      } else {
        setFetchError(`Failed to load leads (${res.status})`);
      }
    } catch (err) {
      console.error("Failed to fetch leads:", err);
      setFetchError("Unable to connect to API");
    }
  }

  async function handleVote(entityId: number, action: "USER_THUMB_UP" | "USER_THUMB_DOWN") {
    setVotingId(entityId);
    try {
      const res = await fetch(`${API_URL}/api/leads/${entityId}/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ action_type: action }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        console.error("Vote failed:", errData);
      }
      fetchLeads();
    } catch (err) {
      console.error("Vote failed:", err);
    }
    setVotingId(null);
  }

  function getStaticMapUrl(lat: number, lng: number) {
    const key = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
    if (!key) return null;
    return `https://maps.googleapis.com/maps/api/staticmap?center=${lat},${lng}&zoom=16&size=400x200&maptype=hybrid&key=${key}&markers=color:red%7C${lat},${lng}`;
  }

  function getStatusBadge(status: string) {
    switch (status) {
      case "CANDIDATE":
        return <span className="bg-green-700 text-green-100 text-xs px-2 py-0.5 rounded-full">Candidate</span>;
      case "REJECTED":
        return <span className="bg-red-900 text-red-200 text-xs px-2 py-0.5 rounded-full">Rejected</span>;
      default:
        return <span className="bg-gray-700 text-gray-300 text-xs px-2 py-0.5 rounded-full">New</span>;
    }
  }

  return (
    <div>
      {/* Sort controls */}
      <div className="flex items-center gap-3 mb-4">
        <span className="text-gray-400 text-sm">Sort by:</span>
        <button
          onClick={() => setSortBy("date")}
          className={`text-sm px-3 py-1 rounded ${sortBy === "date" ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400"}`}
        >
          Date
        </button>
        <button
          onClick={() => setSortBy("coast_distance")}
          className={`text-sm px-3 py-1 rounded ${sortBy === "coast_distance" ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400"}`}
        >
          Coast Proximity
        </button>
      </div>

      {/* Error state */}
      {fetchError && (
        <div className="text-red-400 text-center py-4 bg-red-900/20 rounded-lg mb-4">
          {fetchError}
          <button onClick={fetchLeads} className="ml-2 underline text-red-300 hover:text-red-200">Retry</button>
        </div>
      )}

      {/* Empty state */}
      {!fetchError && leads.length === 0 && (
        <div className="text-gray-500 text-center py-12">
          No leads found yet. Draw a region on the map to start hunting.
        </div>
      )}

      {/* Lead cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {leads.map((lead) => (
          <div
            key={lead.id}
            onClick={() => setSelectedLead(lead)}
            className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden cursor-pointer hover:border-gray-600 transition-colors"
          >
            {lead.latitude && lead.longitude && getStaticMapUrl(lead.latitude, lead.longitude) && (
              <img
                src={getStaticMapUrl(lead.latitude, lead.longitude)!}
                alt={lead.name}
                className="w-full h-40 object-cover"
              />
            )}
            <div className="p-4">
              <div className="flex items-start justify-between mb-2">
                <h3 className="font-semibold text-sm leading-tight">{lead.name}</h3>
                {getStatusBadge(lead.status)}
              </div>
              <p className="text-gray-400 text-xs mb-1">{lead.address}</p>
              <p className="text-gray-500 text-xs mb-3">{lead.county} County</p>

              {!!lead.characteristics?.carrier && (
                <div className="text-xs text-gray-400 mb-3 space-y-0.5">
                  <p>Carrier: <span className="text-white">{String(lead.characteristics.carrier)}</span></p>
                  <p>Premium: <span className="text-white">{String(lead.characteristics.premium)}</span></p>
                  <p>Expires: <span className="text-white">{String(lead.characteristics.expiration)}</span></p>
                </div>
              )}

              <div className="flex gap-2">
                <button
                  onClick={(e) => { e.stopPropagation(); handleVote(lead.id, "USER_THUMB_UP"); }}
                  disabled={votingId === lead.id || lead.status === "CANDIDATE"}
                  className="flex-1 bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white text-sm py-1.5 rounded flex items-center justify-center gap-1"
                >
                  Hunt
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); handleVote(lead.id, "USER_THUMB_DOWN"); }}
                  disabled={votingId === lead.id || lead.status === "REJECTED"}
                  className="flex-1 bg-red-900 hover:bg-red-800 disabled:opacity-50 text-white text-sm py-1.5 rounded flex items-center justify-center gap-1"
                >
                  Reject
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Detail modal */}
      {selectedLead && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" onClick={() => setSelectedLead(null)}>
          <div className="bg-gray-900 rounded-xl border border-gray-700 max-w-2xl w-full max-h-[80vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-4">
              <h2 className="text-xl font-bold">{selectedLead.name}</h2>
              <button onClick={() => setSelectedLead(null)} className="text-gray-400 hover:text-white text-xl">&times;</button>
            </div>
            <p className="text-gray-400 text-sm mb-1">{selectedLead.address}</p>
            <p className="text-gray-500 text-sm mb-4">{selectedLead.county} County</p>

            {selectedLead.characteristics && Object.keys(selectedLead.characteristics).length > 0 && (
              <div className="mb-4">
                <h3 className="text-sm font-semibold text-gray-300 mb-2">Insurance Intelligence</h3>
                <pre className="bg-gray-800 rounded p-3 text-xs text-gray-300 overflow-x-auto">
                  {JSON.stringify(selectedLead.characteristics, null, 2)}
                </pre>
              </div>
            )}

            {!!selectedLead.emails && (
              <div>
                <h3 className="text-sm font-semibold text-gray-300 mb-2">Generated Emails</h3>
                {Object.entries(selectedLead.emails).map(([style, email]) => (
                  <div key={style} className="mb-3 bg-gray-800 rounded p-3">
                    <p className="text-blue-400 text-xs font-semibold uppercase mb-1">{style}</p>
                    <pre className="text-xs text-gray-300 whitespace-pre-wrap">{typeof email === "object" ? JSON.stringify(email, null, 2) : String(email)}</pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
