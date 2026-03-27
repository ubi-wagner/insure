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
  emails?: Record<string, string>;
}

type SortBy = "date" | "coast_distance";

export default function LeadPipeline({ refreshKey }: { refreshKey: number }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [sortBy, setSortBy] = useState<SortBy>("date");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchLeads();
  }, [refreshKey, sortBy]);

  async function fetchLeads() {
    try {
      const res = await fetch(`${API_URL}/api/leads?sort_by=${sortBy}`);
      if (res.ok) {
        const data = await res.json();
        setLeads(data);
      }
    } catch (err) {
      console.error("Failed to fetch leads:", err);
    }
  }

  async function handleVote(entityId: number, action: "USER_THUMB_UP" | "USER_THUMB_DOWN") {
    setLoading(true);
    try {
      await fetch(`${API_URL}/api/leads/${entityId}/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_type: action }),
      });
      fetchLeads();
    } catch (err) {
      console.error("Vote failed:", err);
    }
    setLoading(false);
  }

  function getStaticMapUrl(lat: number, lng: number) {
    const key = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
    if (!key) return "";
    return `https://maps.googleapis.com/maps/api/staticmap?center=${lat},${lng}&zoom=18&size=400x200&maptype=satellite&key=${key}&markers=color:red|${lat},${lng}`;
  }

  function getStatusBadge(status: string) {
    switch (status) {
      case "CANDIDATE":
        return <span className="bg-green-700 text-green-200 text-xs px-2 py-0.5 rounded">Candidate</span>;
      case "REJECTED":
        return <span className="bg-red-700 text-red-200 text-xs px-2 py-0.5 rounded">Rejected</span>;
      default:
        return <span className="bg-yellow-700 text-yellow-200 text-xs px-2 py-0.5 rounded">New</span>;
    }
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold">Lead Pipeline</h2>
        <div className="flex gap-2">
          <button
            onClick={() => setSortBy("date")}
            className={`px-3 py-1 rounded text-sm ${sortBy === "date" ? "bg-blue-600" : "bg-gray-700 hover:bg-gray-600"}`}
          >
            Date Found
          </button>
          <button
            onClick={() => setSortBy("coast_distance")}
            className={`px-3 py-1 rounded text-sm ${sortBy === "coast_distance" ? "bg-blue-600" : "bg-gray-700 hover:bg-gray-600"}`}
          >
            Coast Distance
          </button>
        </div>
      </div>

      {leads.length === 0 && (
        <div className="text-gray-500 text-center py-12">
          No leads found yet. Draw a region on the map to start hunting.
        </div>
      )}

      {/* Lead Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {leads.map((lead) => (
          <div
            key={lead.id}
            className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden hover:border-gray-600 transition cursor-pointer"
            onClick={() => setSelectedLead(lead)}
          >
            {lead.latitude && lead.longitude && (
              <img
                src={getStaticMapUrl(lead.latitude, lead.longitude)}
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

              {lead.characteristics?.carrier && (
                <div className="text-xs text-gray-400 mb-3 space-y-0.5">
                  <p>Carrier: <span className="text-white">{String(lead.characteristics.carrier)}</span></p>
                  <p>Premium: <span className="text-white">{String(lead.characteristics.premium)}</span></p>
                  <p>Expires: <span className="text-white">{String(lead.characteristics.expiration)}</span></p>
                </div>
              )}

              <div className="flex gap-2">
                <button
                  onClick={(e) => { e.stopPropagation(); handleVote(lead.id, "USER_THUMB_UP"); }}
                  disabled={loading || lead.status === "CANDIDATE"}
                  className="flex-1 bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white text-sm py-1.5 rounded flex items-center justify-center gap-1"
                >
                  👍 Hunt
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); handleVote(lead.id, "USER_THUMB_DOWN"); }}
                  disabled={loading || lead.status === "REJECTED"}
                  className="flex-1 bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-sm py-1.5 rounded flex items-center justify-center gap-1"
                >
                  👎 Pass
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Lead Detail Modal */}
      {selectedLead && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
          onClick={() => setSelectedLead(null)}
        >
          <div
            className="bg-gray-900 border border-gray-700 rounded-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h2 className="text-xl font-bold">{selectedLead.name}</h2>
                  <p className="text-gray-400 text-sm">{selectedLead.address}</p>
                </div>
                <button
                  onClick={() => setSelectedLead(null)}
                  className="text-gray-500 hover:text-white text-xl"
                >
                  ✕
                </button>
              </div>

              {selectedLead.latitude && selectedLead.longitude && (
                <img
                  src={getStaticMapUrl(selectedLead.latitude, selectedLead.longitude)}
                  alt={selectedLead.name}
                  className="w-full h-48 object-cover rounded-lg mb-4"
                />
              )}

              {selectedLead.characteristics && (
                <div className="mb-4 p-4 bg-gray-800 rounded-lg">
                  <h3 className="font-semibold mb-2 text-blue-400">Extracted Intel</h3>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    {Object.entries(selectedLead.characteristics).map(([key, val]) => (
                      <div key={key}>
                        <span className="text-gray-400 capitalize">{key.replace(/_/g, " ")}: </span>
                        <span className="text-white">{String(val)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {selectedLead.emails && (
                <div>
                  <h3 className="font-semibold mb-3 text-blue-400">Email Drafts</h3>
                  <div className="space-y-3">
                    {Object.entries(selectedLead.emails).map(([style, content]) => (
                      <details key={style} className="bg-gray-800 rounded-lg">
                        <summary className="px-4 py-2 cursor-pointer text-sm font-medium capitalize hover:text-blue-400">
                          {style.replace(/_/g, " ")} Approach
                        </summary>
                        <div className="px-4 pb-3 text-sm text-gray-300 whitespace-pre-wrap">
                          {String(content)}
                        </div>
                      </details>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
