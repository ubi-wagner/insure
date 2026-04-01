"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

interface LeadDetail {
  id: number;
  name: string;
  address: string;
  county: string;
  latitude: number;
  longitude: number;
  characteristics: Record<string, unknown>;
  emails: Record<string, { subject: string; body: string }> | null;
  wind_ratio: number | null;
  heat_score: string;
  premium_parsed: number | null;
  tiv_parsed: number | null;
  assets: { id: number; doc_type: string; extracted_text: string }[];
  contacts: { id: number; name: string; title: string }[];
}

const HEAT_STYLES: Record<string, string> = {
  hot: "bg-red-600", warm: "bg-orange-600", cool: "bg-blue-600", none: "bg-gray-600",
};

function fmt(val: number | null): string {
  if (val === null) return "\u2014";
  return "$" + val.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export default function LeadDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "documents" | "emails" | "contacts">("overview");

  useEffect(() => {
    fetch(`/api/proxy/leads/${id}`)
      .then((r) => r.ok ? r.json() : Promise.reject(`${r.status}`))
      .then(setLead)
      .catch((e) => setError(String(e)));
  }, [id]);

  if (error) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 mb-4">Failed to load lead: {error}</p>
          <Link href="/" className="text-blue-400 hover:underline">Back to Dashboard</Link>
        </div>
      </div>
    );
  }

  if (!lead) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
        <div className="text-gray-500">Loading lead #{id}...</div>
      </div>
    );
  }

  const chars = lead.characteristics || {};
  const tabs = ["overview", "documents", "emails", "contacts"] as const;

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link href="/" className="text-gray-400 hover:text-white text-sm">&larr; Dashboard</Link>
            <span className="text-gray-700">|</span>
            <h1 className="text-lg font-bold">{lead.name}</h1>
            <span className={`text-xs px-2 py-0.5 rounded-full text-white ${HEAT_STYLES[lead.heat_score] || HEAT_STYLES.none}`}>
              {lead.heat_score}{lead.wind_ratio !== null && ` ${lead.wind_ratio.toFixed(2)}%`}
            </span>
          </div>
          <div className="text-gray-500 text-sm">Lead #{lead.id}</div>
        </div>
      </header>

      {/* Key metrics bar */}
      <div className="bg-gray-900/50 border-b border-gray-800 px-6 py-3">
        <div className="flex gap-8 text-sm">
          <div><span className="text-gray-500">Address: </span><span>{lead.address}</span></div>
          <div><span className="text-gray-500">County: </span><span>{lead.county}</span></div>
          <div><span className="text-gray-500">TIV: </span><span className="font-semibold">{fmt(lead.tiv_parsed)}</span></div>
          <div><span className="text-gray-500">Premium: </span><span className="font-semibold">{fmt(lead.premium_parsed)}</span></div>
          <div><span className="text-gray-500">Wind Ratio: </span>
            <span className={`font-semibold ${lead.heat_score === "hot" ? "text-red-400" : ""}`}>
              {lead.wind_ratio !== null ? `${lead.wind_ratio.toFixed(2)}%` : "\u2014"}
            </span>
          </div>
          {!!chars.carrier && <div><span className="text-gray-500">Carrier: </span><span>{String(chars.carrier)}</span></div>}
          {!!chars.expiration && <div><span className="text-gray-500">Expires: </span><span>{String(chars.expiration)}</span></div>}
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-800 px-6">
        <div className="flex gap-1 -mb-px">
          {tabs.map((tab) => (
            <button key={tab} onClick={() => setActiveTab(tab)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 capitalize ${
                activeTab === tab
                  ? "border-blue-500 text-white"
                  : "border-transparent text-gray-500 hover:text-gray-300"
              }`}>
              {tab}
              {tab === "documents" && ` (${lead.assets.length})`}
              {tab === "contacts" && ` (${lead.contacts.length})`}
              {tab === "emails" && lead.emails && ` (${Object.keys(lead.emails).length})`}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="px-6 py-6 max-w-6xl">
        {activeTab === "overview" && (
          <div className="space-y-6">
            {/* Intel grid */}
            <div>
              <h2 className="text-sm font-semibold text-gray-300 mb-3">Insurance Intelligence</h2>
              {Object.keys(chars).length > 0 ? (
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  {Object.entries(chars).filter(([k]) => k !== "emails").map(([key, val]) => (
                    <div key={key} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                      <p className="text-gray-500 text-xs capitalize">{key.replace(/_/g, " ")}</p>
                      <p className="text-white text-sm mt-1">
                        {Array.isArray(val) ? (val as string[]).join(", ") : String(val || "\u2014")}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-gray-600 text-sm">No intelligence yet. Click Hunt on the dashboard to trigger analysis.</p>
              )}
            </div>

            {/* Location */}
            <div>
              <h2 className="text-sm font-semibold text-gray-300 mb-3">Location</h2>
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-sm">
                <p>{lead.address}</p>
                <p className="text-gray-500 mt-1">{lead.latitude.toFixed(6)}, {lead.longitude.toFixed(6)}</p>
              </div>
            </div>
          </div>
        )}

        {activeTab === "documents" && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Documents</h2>
            {lead.assets.length === 0 ? (
              <p className="text-gray-600 text-sm">No documents attached.</p>
            ) : (
              lead.assets.map((asset) => (
                <div key={asset.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <span className="bg-blue-900 text-blue-300 text-xs px-2 py-0.5 rounded font-medium">{asset.doc_type}</span>
                    <span className="text-gray-500 text-xs">Document #{asset.id}</span>
                  </div>
                  <pre className="text-xs text-gray-300 whitespace-pre-wrap bg-gray-800 rounded p-3 max-h-96 overflow-y-auto">
                    {asset.extracted_text || "No text extracted."}
                  </pre>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "emails" && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Generated Outreach Emails</h2>
            {!lead.emails || Object.keys(lead.emails).length === 0 ? (
              <p className="text-gray-600 text-sm">No emails generated yet. Mark as Candidate to trigger AI analysis.</p>
            ) : (
              Object.entries(lead.emails).map(([style, email]) => (
                <div key={style} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="bg-purple-900 text-purple-300 text-xs px-2 py-0.5 rounded font-medium uppercase">{style}</span>
                  </div>
                  {typeof email === "object" && email !== null ? (
                    <>
                      <p className="text-white text-sm font-medium mb-2">Subject: {(email as {subject?: string}).subject || ""}</p>
                      <div className="bg-gray-800 rounded p-3 text-sm text-gray-300 whitespace-pre-wrap">
                        {(email as {body?: string}).body || ""}
                      </div>
                    </>
                  ) : (
                    <pre className="text-sm text-gray-300 whitespace-pre-wrap">{String(email)}</pre>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "contacts" && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Contacts & Decision Makers</h2>
            {lead.contacts.length === 0 ? (
              <p className="text-gray-600 text-sm">No contacts found.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {lead.contacts.map((contact) => (
                  <div key={contact.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                    <p className="text-white font-medium">{contact.name}</p>
                    <p className="text-gray-500 text-sm">{contact.title}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
