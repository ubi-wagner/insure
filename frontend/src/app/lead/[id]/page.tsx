"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

interface PolicyItem {
  id: number;
  coverage_type: string;
  carrier: string | null;
  policy_number: string | null;
  premium: number | null;
  tiv: number | null;
  deductible: string | null;
  expiration: string | null;
  prior_premium: number | null;
  premium_increase_pct: number | null;
  is_active: number;
  notes: string | null;
}

interface EngagementItem {
  id: number;
  type: string;
  channel: string;
  status: string;
  subject: string | null;
  body: string | null;
  style: string | null;
  sent_at: string | null;
  responded_at: string | null;
  follow_up_at: string | null;
  created_at: string;
}

interface ChildEntity {
  id: number;
  name: string;
  address: string;
  pipeline_stage: string;
}

interface LeadDetail {
  id: number;
  parent_id: number | null;
  name: string;
  address: string;
  county: string;
  latitude: number;
  longitude: number;
  pipeline_stage: string;
  characteristics: Record<string, unknown>;
  emails: Record<string, { subject: string; body: string }> | null;
  wind_ratio: number | null;
  heat_score: string;
  premium_parsed: number | null;
  tiv_parsed: number | null;
  policies: PolicyItem[];
  engagements: EngagementItem[];
  assets: { id: number; doc_type: string; extracted_text: string }[];
  contacts: { id: number; name: string; title: string; email: string | null; phone: string | null; is_primary: number }[];
  children: ChildEntity[];
}

const HEAT_STYLES: Record<string, string> = {
  hot: "bg-red-600", warm: "bg-orange-600", cool: "bg-blue-600", none: "bg-gray-600",
};

const STAGE_COLORS: Record<string, string> = {
  NEW: "bg-gray-700", CANDIDATE: "bg-purple-900", TARGET: "bg-amber-900",
  OPPORTUNITY: "bg-blue-900", CUSTOMER: "bg-green-800", CHURNED: "bg-gray-800", ARCHIVED: "bg-red-900",
};

function fmt(val: number | null | undefined): string {
  if (val === null || val === undefined) return "\u2014";
  return "$" + val.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

type TabName = "overview" | "policies" | "documents" | "emails" | "engagements" | "contacts";

export default function LeadDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabName>("overview");
  const [stageChanging, setStageChanging] = useState(false);
  const [sendingStyle, setSendingStyle] = useState<string | null>(null);
  const [showAddContact, setShowAddContact] = useState(false);
  const [contactForm, setContactForm] = useState({ name: "", title: "", email: "", phone: "", is_primary: 0 });
  const [savingContact, setSavingContact] = useState(false);

  useEffect(() => {
    fetch(`/api/proxy/leads/${id}`)
      .then((r) => r.ok ? r.json() : Promise.reject(`${r.status}`))
      .then(setLead)
      .catch((e) => setError(String(e)));
  }, [id]);

  async function handleSendOutreach(style: string, subject: string, body: string) {
    setSendingStyle(style);
    try {
      const res = await fetch(`/api/proxy/leads/${id}/engagements`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ style, subject, body, channel: "EMAIL" }),
      });
      if (res.ok) {
        // Refresh lead data to show new engagement
        const updated = await fetch(`/api/proxy/leads/${id}`);
        if (updated.ok) setLead(await updated.json());
      }
    } catch {}
    setSendingStyle(null);
  }

  async function handleAddContact() {
    if (!contactForm.name.trim()) return;
    setSavingContact(true);
    try {
      const res = await fetch(`/api/proxy/leads/${id}/contacts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(contactForm),
      });
      if (res.ok) {
        const updated = await fetch(`/api/proxy/leads/${id}`);
        if (updated.ok) setLead(await updated.json());
        setContactForm({ name: "", title: "", email: "", phone: "", is_primary: 0 });
        setShowAddContact(false);
      }
    } catch {}
    setSavingContact(false);
  }

  async function handleStageChange(newStage: string) {
    setStageChanging(true);
    try {
      const res = await fetch(`/api/proxy/leads/${id}/stage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: newStage }),
      });
      if (res.ok) {
        setLead((prev) => prev ? { ...prev, pipeline_stage: newStage } : prev);
      }
    } catch {}
    setStageChanging(false);
  }

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
  const stages = ["NEW", "CANDIDATE", "TARGET", "OPPORTUNITY", "CUSTOMER", "CHURNED", "ARCHIVED"];
  const tabs: { key: TabName; label: string; count?: number }[] = [
    { key: "overview", label: "Overview" },
    { key: "policies", label: "Policies", count: lead.policies.length },
    { key: "documents", label: "Documents", count: lead.assets.length },
    { key: "emails", label: "Emails", count: lead.emails ? Object.keys(lead.emails).length : 0 },
    { key: "engagements", label: "Engagements", count: lead.engagements.length },
    { key: "contacts", label: "Contacts", count: lead.contacts.length },
  ];

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
            <span className={`text-xs px-2 py-0.5 rounded-full text-white ${STAGE_COLORS[lead.pipeline_stage] || STAGE_COLORS.NEW}`}>
              {lead.pipeline_stage}
            </span>
          </div>
          <div className="text-gray-500 text-sm">Lead #{lead.id}</div>
        </div>
      </header>

      {/* Metrics bar + stage selector */}
      <div className="bg-gray-900/50 border-b border-gray-800 px-6 py-3">
        <div className="flex gap-6 text-sm items-center flex-wrap">
          <div><span className="text-gray-500">Address: </span><span>{lead.address}</span></div>
          <div><span className="text-gray-500">County: </span><span>{lead.county}</span></div>
          <div><span className="text-gray-500">TIV: </span><span className="font-semibold">{fmt(lead.tiv_parsed)}</span></div>
          <div><span className="text-gray-500">Premium: </span><span className="font-semibold">{fmt(lead.premium_parsed)}</span></div>
          <div><span className="text-gray-500">Wind: </span>
            <span className={`font-semibold ${lead.heat_score === "hot" ? "text-red-400" : ""}`}>
              {lead.wind_ratio !== null ? `${lead.wind_ratio.toFixed(2)}%` : "\u2014"}
            </span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-gray-500 text-xs">Stage:</span>
            <select
              value={lead.pipeline_stage}
              onChange={(e) => handleStageChange(e.target.value)}
              disabled={stageChanging}
              className="bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1"
            >
              {stages.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
        {lead.children.length > 0 && (
          <div className="mt-2 flex gap-2 items-center">
            <span className="text-gray-500 text-xs">Sub-entities:</span>
            {lead.children.map((ch) => (
              <Link key={ch.id} href={`/lead/${ch.id}`}
                className="bg-gray-800 text-gray-300 hover:text-white text-xs px-2 py-1 rounded">
                {ch.name}
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-800 px-6">
        <div className="flex gap-1 -mb-px">
          {tabs.map((tab) => (
            <button key={tab.key} onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 ${
                activeTab === tab.key
                  ? "border-blue-500 text-white"
                  : "border-transparent text-gray-500 hover:text-gray-300"
              }`}>
              {tab.label}{tab.count !== undefined ? ` (${tab.count})` : ""}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="px-6 py-6 max-w-6xl">

        {activeTab === "overview" && (
          <div className="space-y-6">
            {/* Building Profile */}
            {(chars.construction_class || chars.stories || chars.building_type) && (
              <div>
                <h2 className="text-sm font-semibold text-gray-300 mb-3">Building Profile</h2>
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {chars.construction_class && (
                      <div>
                        <p className="text-gray-500 text-xs">Construction Class</p>
                        <p className={`text-sm font-medium mt-1 ${
                          String(chars.construction_class).includes("Fire Resistive") ? "text-emerald-400" :
                          String(chars.construction_class).includes("Non-Combustible") ? "text-sky-400" :
                          String(chars.construction_class).includes("Masonry") ? "text-amber-400" :
                          String(chars.construction_class).includes("Frame") ? "text-red-400" : "text-white"
                        }`}>{String(chars.construction_class)}</p>
                        {chars.iso_class ? <p className="text-gray-600 text-xs mt-0.5">ISO Class {String(chars.iso_class)}</p> : null}
                      </div>
                    )}
                    {chars.stories && (
                      <div>
                        <p className="text-gray-500 text-xs">Stories</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.stories)}</p>
                      </div>
                    )}
                    {chars.building_type && (
                      <div>
                        <p className="text-gray-500 text-xs">Building Type</p>
                        <p className="text-white text-sm font-medium mt-1 capitalize">{String(chars.building_type)}</p>
                      </div>
                    )}
                    {chars.building_material && (
                      <div>
                        <p className="text-gray-500 text-xs">Material</p>
                        <p className="text-white text-sm font-medium mt-1 capitalize">{String(chars.building_material)}</p>
                      </div>
                    )}
                    {chars.year_built && (
                      <div>
                        <p className="text-gray-500 text-xs">Year Built</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.year_built)}</p>
                      </div>
                    )}
                    {chars.units_estimate && (
                      <div>
                        <p className="text-gray-500 text-xs">Est. Units</p>
                        <p className="text-white text-sm font-medium mt-1">~{String(chars.units_estimate)}</p>
                      </div>
                    )}
                    {chars.footprint_sqft && (
                      <div>
                        <p className="text-gray-500 text-xs">Footprint</p>
                        <p className="text-white text-sm font-medium mt-1">{Number(chars.footprint_sqft).toLocaleString()} sqft</p>
                      </div>
                    )}
                    {chars.tiv_estimate && (
                      <div>
                        <p className="text-gray-500 text-xs">Est. TIV</p>
                        <p className="text-white text-sm font-semibold mt-1">${Number(chars.tiv_estimate).toLocaleString()}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Insurance Intelligence */}
            <div>
              <h2 className="text-sm font-semibold text-gray-300 mb-3">Insurance Intelligence</h2>
              {Object.keys(chars).length > 0 ? (
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  {Object.entries(chars)
                    .filter(([k]) => !["emails", "osm_tags", "osm_id", "construction_class", "iso_class",
                      "building_material", "building_type", "year_built", "stories", "units_estimate",
                      "footprint_sqft", "tiv_estimate", "height_m"].includes(k))
                    .map(([key, val]) => (
                    <div key={key} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                      <p className="text-gray-500 text-xs capitalize">{key.replace(/_/g, " ")}</p>
                      <p className="text-white text-sm mt-1">
                        {Array.isArray(val) ? (val as string[]).join(", ") : String(val || "\u2014")}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-gray-600 text-sm">No intelligence yet. Click Hunt to trigger analysis.</p>
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

        {activeTab === "policies" && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Insurance Policies</h2>
            {lead.policies.length === 0 ? (
              <p className="text-gray-600 text-sm">No policies on record.</p>
            ) : (
              lead.policies.map((pol) => (
                <div key={pol.id} className={`bg-gray-900 border rounded-lg p-4 ${pol.is_active ? "border-green-800" : "border-gray-800 opacity-60"}`}>
                  <div className="flex items-center gap-2 mb-3">
                    <span className="bg-blue-900 text-blue-300 text-xs px-2 py-0.5 rounded font-medium">{pol.coverage_type}</span>
                    {pol.is_active ? (
                      <span className="bg-green-900 text-green-300 text-[10px] px-1.5 py-0.5 rounded">ACTIVE</span>
                    ) : (
                      <span className="bg-gray-800 text-gray-500 text-[10px] px-1.5 py-0.5 rounded">EXPIRED</span>
                    )}
                    {pol.policy_number && <span className="text-gray-500 text-xs">{pol.policy_number}</span>}
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                    <div><span className="text-gray-500">Carrier: </span><span>{pol.carrier || "\u2014"}</span></div>
                    <div><span className="text-gray-500">Premium: </span><span className="font-semibold">{fmt(pol.premium)}</span></div>
                    <div><span className="text-gray-500">TIV: </span><span className="font-semibold">{fmt(pol.tiv)}</span></div>
                    <div><span className="text-gray-500">Expires: </span><span>{pol.expiration || "\u2014"}</span></div>
                    <div><span className="text-gray-500">Deductible: </span><span>{pol.deductible || "\u2014"}</span></div>
                    {pol.prior_premium && <div><span className="text-gray-500">Prior: </span><span>{fmt(pol.prior_premium)}</span></div>}
                    {pol.premium && pol.tiv && pol.tiv > 0 && (
                      <div><span className="text-gray-500">Wind Ratio: </span>
                        <span className={pol.premium / pol.tiv * 100 >= 3 ? "text-red-400 font-semibold" : ""}>
                          {(pol.premium / pol.tiv * 100).toFixed(2)}%
                        </span>
                      </div>
                    )}
                  </div>
                  {pol.notes && <p className="text-gray-500 text-xs mt-2">{pol.notes}</p>}
                </div>
              ))
            )}
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
              Object.entries(lead.emails).map(([style, email]) => {
                const emailObj = typeof email === "object" && email !== null ? email as {subject?: string; body?: string} : null;
                return (
                <div key={style} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="bg-purple-900 text-purple-300 text-xs px-2 py-0.5 rounded font-medium uppercase">{style}</span>
                    {emailObj && (
                      <button
                        onClick={() => handleSendOutreach(style, emailObj.subject || "", emailObj.body || "")}
                        disabled={sendingStyle === style}
                        className="bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white text-xs px-3 py-1 rounded font-medium"
                      >
                        {sendingStyle === style ? "Queuing..." : "Send as Outreach"}
                      </button>
                    )}
                  </div>
                  {emailObj ? (
                    <>
                      <p className="text-white text-sm font-medium mb-2">Subject: {emailObj.subject || ""}</p>
                      <div className="bg-gray-800 rounded p-3 text-sm text-gray-300 whitespace-pre-wrap">
                        {emailObj.body || ""}
                      </div>
                    </>
                  ) : (
                    <pre className="text-sm text-gray-300 whitespace-pre-wrap mt-2">{String(email)}</pre>
                  )}
                </div>
                );
              })
            )}
          </div>
        )}

        {activeTab === "engagements" && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Engagement History</h2>
            {lead.engagements.length === 0 ? (
              <p className="text-gray-600 text-sm">No engagements yet. Emails will appear here when sent.</p>
            ) : (
              lead.engagements.map((eng) => (
                <div key={eng.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="bg-blue-900 text-blue-300 text-xs px-2 py-0.5 rounded font-medium">{eng.type}</span>
                    <span className="bg-gray-800 text-gray-400 text-xs px-2 py-0.5 rounded">{eng.channel}</span>
                    <span className="bg-gray-800 text-gray-400 text-xs px-2 py-0.5 rounded">{eng.status}</span>
                    {eng.style && <span className="text-gray-500 text-xs">Style: {eng.style}</span>}
                  </div>
                  {eng.subject && <p className="text-white text-sm font-medium mb-1">{eng.subject}</p>}
                  {eng.body && <div className="bg-gray-800 rounded p-3 text-xs text-gray-300 whitespace-pre-wrap">{eng.body}</div>}
                  <div className="flex gap-4 mt-2 text-xs text-gray-500">
                    {eng.sent_at && <span>Sent: {new Date(eng.sent_at).toLocaleDateString()}</span>}
                    {eng.responded_at && <span>Response: {new Date(eng.responded_at).toLocaleDateString()}</span>}
                    {eng.follow_up_at && <span>Follow-up: {new Date(eng.follow_up_at).toLocaleDateString()}</span>}
                    <span>Created: {new Date(eng.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "contacts" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-300">Contacts & Decision Makers</h2>
              <button
                onClick={() => setShowAddContact(!showAddContact)}
                className="bg-blue-600 hover:bg-blue-700 text-white text-xs px-3 py-1 rounded font-medium"
              >
                {showAddContact ? "Cancel" : "+ Add Contact"}
              </button>
            </div>
            {showAddContact && (
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <input type="text" placeholder="Name *" value={contactForm.name}
                    onChange={(e) => setContactForm({ ...contactForm, name: e.target.value })}
                    className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white" />
                  <input type="text" placeholder="Title (e.g. Property Manager)" value={contactForm.title}
                    onChange={(e) => setContactForm({ ...contactForm, title: e.target.value })}
                    className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white" />
                  <input type="email" placeholder="Email" value={contactForm.email}
                    onChange={(e) => setContactForm({ ...contactForm, email: e.target.value })}
                    className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white" />
                  <input type="tel" placeholder="Phone" value={contactForm.phone}
                    onChange={(e) => setContactForm({ ...contactForm, phone: e.target.value })}
                    className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white" />
                </div>
                <div className="flex items-center justify-between">
                  <label className="flex items-center gap-2 text-sm text-gray-400">
                    <input type="checkbox" checked={contactForm.is_primary === 1}
                      onChange={(e) => setContactForm({ ...contactForm, is_primary: e.target.checked ? 1 : 0 })}
                      className="rounded bg-gray-800 border-gray-600" />
                    Primary contact
                  </label>
                  <button onClick={handleAddContact} disabled={savingContact || !contactForm.name.trim()}
                    className="bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white text-xs px-4 py-1.5 rounded font-medium">
                    {savingContact ? "Saving..." : "Save Contact"}
                  </button>
                </div>
              </div>
            )}
            {lead.contacts.length === 0 && !showAddContact ? (
              <p className="text-gray-600 text-sm">No contacts found. Add one to start outreach.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {lead.contacts.map((contact) => (
                  <div key={contact.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                    <div className="flex items-center gap-2">
                      <p className="text-white font-medium">{contact.name}</p>
                      {!!contact.is_primary && <span className="bg-green-900 text-green-300 text-[10px] px-1.5 py-0.5 rounded">PRIMARY</span>}
                    </div>
                    <p className="text-gray-500 text-sm">{contact.title}</p>
                    {contact.email && <p className="text-blue-400 text-sm mt-1">{contact.email}</p>}
                    {contact.phone && <p className="text-gray-400 text-sm">{contact.phone}</p>}
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
