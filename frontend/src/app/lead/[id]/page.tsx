"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";

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
  latitude: number | null;
  longitude: number | null;
  pipeline_stage: string;
  characteristics: Record<string, unknown>;
  emails: Record<string, { subject: string; body: string }> | null;
  wind_ratio: number | null;
  heat_score: string;
  premium_parsed: number | null;
  tiv_parsed: number | null;
  policies: PolicyItem[];
  engagements: EngagementItem[];
  assets: { id: number; doc_type: string; extracted_text: string; source: string | null; filename: string | null }[];
  contacts: { id: number; name: string; title: string; email: string | null; phone: string | null; is_primary: number; source: string | null; source_url: string | null }[];
  children: ChildEntity[];
  enrichment_sources: Record<string, { source: string; timestamp: string; fields_updated: string[]; url: string | null }>;
  readiness: Record<string, {
    ready: boolean;
    checks: Record<string, { done: boolean; label: string }>;
  }>;
}

const HEAT_STYLES: Record<string, string> = {
  hot: "bg-red-600", warm: "bg-orange-600", cool: "bg-blue-600", none: "bg-gray-600",
};

const STAGE_COLORS: Record<string, string> = {
  TARGET: "bg-gray-700", LEAD: "bg-cyan-900",
  OPPORTUNITY: "bg-blue-900", CUSTOMER: "bg-green-800", ARCHIVED: "bg-red-900",
};

function safeNum(val: unknown): string {
  const n = Number(val);
  return isNaN(n) ? "\u2014" : n.toLocaleString();
}

function fmt(val: number | null | undefined): string {
  if (val === null || val === undefined) return "\u2014";
  return "$" + val.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

type TabName = "overview" | "engage" | "policies" | "documents" | "emails" | "engagements" | "contacts" | "sources";

export default function LeadDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const { canEdit } = useAuth();
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabName>("overview");
  const [stageChanging, setStageChanging] = useState(false);
  const [stageError, setStageError] = useState<string | null>(null);
  const [sendingStyle, setSendingStyle] = useState<string | null>(null);
  const [showAddContact, setShowAddContact] = useState(false);
  const [contactForm, setContactForm] = useState({ name: "", title: "", email: "", phone: "", is_primary: 0 });
  const [savingContact, setSavingContact] = useState(false);

  useEffect(() => {
    setError(null);
    setLead(null);
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
        const updated = await fetch(`/api/proxy/leads/${id}`);
        if (updated.ok) setLead(await updated.json());
      }
    } catch (err) {
      console.error("Failed to send outreach:", err);
    }
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
    } catch (err) {
      console.error("Failed to add contact:", err);
    }
    setSavingContact(false);
  }

  async function handleStageChange(newStage: string, force = false) {
    setStageChanging(true);
    setStageError(null);
    try {
      const res = await fetch(`/api/proxy/leads/${id}/stage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: newStage, force }),
      });
      if (!res.ok && res.status === 422) {
        const data = await res.json().catch(() => ({}));
        setStageError(data.detail?.message || "Not ready for this stage");
      } else if (res.ok) {
        const updated = await fetch(`/api/proxy/leads/${id}`);
        if (updated.ok) setLead(await updated.json());
        else setLead((prev) => prev ? { ...prev, pipeline_stage: newStage } : prev);
      }
    } catch (err) {
      console.error("Failed to change stage:", err);
      setStageError("Network error — could not change stage");
    }
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
  const stages = ["TARGET", "LEAD", "OPPORTUNITY", "CUSTOMER", "ARCHIVED"];
  const isEngageReady = ["OPPORTUNITY", "CUSTOMER"].includes(lead.pipeline_stage);
  const tabs: { key: TabName; label: string; count?: number }[] = [
    { key: "overview", label: "Overview" },
    ...(isEngageReady || lead.engagements.length > 0 ? [{ key: "engage" as TabName, label: "Engage" }] : []),
    { key: "policies", label: "Policies", count: lead.policies.length },
    { key: "documents", label: "Documents", count: lead.assets.length },
    { key: "emails", label: "Emails", count: lead.emails ? Object.keys(lead.emails).length : 0 },
    { key: "engagements", label: "Engagements", count: lead.engagements.length },
    { key: "contacts", label: "Contacts", count: lead.contacts.length },
    { key: "sources", label: "Sources", count: Object.keys(lead.enrichment_sources || {}).length },
  ];

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-3 md:px-6 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 flex-wrap min-w-0">
            <Link href="/" className="text-gray-400 hover:text-white text-sm shrink-0">&larr;</Link>
            <h1 className="text-base md:text-lg font-bold truncate">{lead.name}</h1>
            <div className="flex gap-1 shrink-0">
              <span className={`text-[10px] md:text-xs px-2 py-0.5 rounded-full text-white ${HEAT_STYLES[lead.heat_score] || HEAT_STYLES.none}`}>
                {lead.heat_score}
              </span>
              <span className={`text-[10px] md:text-xs px-2 py-0.5 rounded-full text-white ${STAGE_COLORS[lead.pipeline_stage] || "bg-gray-700"}`}>
                {lead.pipeline_stage}
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* Metrics bar + stage selector */}
      <div className="bg-gray-900/50 border-b border-gray-800 px-3 md:px-6 py-2 md:py-3">
        <div className="flex gap-3 md:gap-6 text-xs md:text-sm items-center flex-wrap">
          <div><span className="text-gray-500">Address: </span><span>{lead.address}</span></div>
          <div><span className="text-gray-500">County: </span><span>{lead.county}</span></div>
          <div><span className="text-gray-500">TIV: </span><span className="font-semibold">{fmt(lead.tiv_parsed)}</span></div>
          <div><span className="text-gray-500">Premium: </span><span className="font-semibold">{fmt(lead.premium_parsed)}</span></div>
          <div><span className="text-gray-500">Wind: </span>
            <span className={`font-semibold ${lead.heat_score === "hot" ? "text-red-400" : ""}`}>
              {lead.wind_ratio != null ? `${lead.wind_ratio.toFixed(2)}%` : "\u2014"}
            </span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-gray-500 text-xs">Stage:</span>
            {canEdit ? (
              <select
                value={lead.pipeline_stage}
                onChange={(e) => handleStageChange(e.target.value)}
                disabled={stageChanging}
                className="bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1"
              >
                {stages.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            ) : (
              <span className="text-white text-xs">{lead.pipeline_stage}</span>
            )}
          </div>
        </div>
        {(lead.children?.length ?? 0) > 0 && (
          <div className="mt-2 flex gap-2 items-center">
            <span className="text-gray-500 text-xs">Sub-entities:</span>
            {(lead.children || []).map((ch) => (
              <Link key={ch.id} href={`/lead/${ch.id}`}
                className="bg-gray-800 text-gray-300 hover:text-white text-xs px-2 py-1 rounded">
                {ch.name}
              </Link>
            ))}
          </div>
        )}
        {/* Stage error / readiness warning */}
        {stageError && (
          <div className="mt-2 bg-amber-900/30 border border-amber-800 rounded px-3 py-2 flex items-center justify-between">
            <p className="text-amber-300 text-xs">{stageError}</p>
            {canEdit && (
              <button onClick={() => {
                const nextStage = lead.pipeline_stage === "TARGET" ? "LEAD" :
                  lead.pipeline_stage === "LEAD" ? "OPPORTUNITY" :
                  lead.pipeline_stage === "OPPORTUNITY" ? "CUSTOMER" : "";
                if (nextStage) handleStageChange(nextStage, true);
              }}
                className="bg-amber-800 hover:bg-amber-700 text-amber-200 text-xs px-2 py-1 rounded ml-3 shrink-0">
                Force Advance
              </button>
            )}
          </div>
        )}
        {/* Next stage readiness checklist */}
        {lead.readiness && (() => {
          const nextStageKey = lead.pipeline_stage === "LEAD" ? "opportunity" : null;
          if (!nextStageKey || !lead.readiness[nextStageKey]) return null;
          const r = lead.readiness[nextStageKey];
          const checks = Object.values(r.checks) as { done: boolean; label: string }[];
          const done = checks.filter((c) => c.done).length;
          return (
            <div className="mt-2 flex items-center gap-2 text-xs flex-wrap">
              <span className="text-gray-500 shrink-0">Next ({nextStageKey.toUpperCase()}):</span>
              <div className="flex gap-1 flex-wrap">
                {checks.map((check: { done: boolean; label: string }) => (
                  <span key={check.label} className={`px-1.5 py-0.5 rounded ${
                    check.done ? "bg-green-900/50 text-green-400" : "bg-gray-800 text-gray-600"
                  }`} title={check.label}>
                    {check.done ? "\u2713" : "\u2717"} {check.label}
                  </span>
                ))}
              </div>
              <span className={`font-medium ${r.ready ? "text-green-400" : "text-gray-600"}`}>
                {done}/{checks.length} {r.ready ? "Ready" : ""}
              </span>
            </div>
          );
        })()}
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-800 px-3 md:px-6 overflow-x-auto">
        <div className="flex gap-1 -mb-px min-w-max">
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
      <div className="px-3 md:px-6 py-4 md:py-6 max-w-6xl">

        {activeTab === "overview" && (
          <div className="space-y-6">
            {/* Building Profile */}
            {!!(chars.construction_class || chars.dor_construction_class || chars.stories || chars.building_type || chars.year_built || chars.dor_year_built || chars.units_estimate || chars.tiv_estimate) && (
              <div>
                <h2 className="text-sm font-semibold text-gray-300 mb-3">Building Profile</h2>
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {!!(chars.construction_class || chars.dor_construction_class) && (
                      <div>
                        <p className="text-gray-500 text-xs">Construction Class</p>
                        <p className={`text-sm font-medium mt-1 ${
                          String(chars.construction_class || chars.dor_construction_class).includes("Fire Resistive") ? "text-emerald-400" :
                          String(chars.construction_class || chars.dor_construction_class).includes("Non-Combustible") ? "text-sky-400" :
                          String(chars.construction_class || chars.dor_construction_class).includes("Masonry") ? "text-amber-400" :
                          String(chars.construction_class || chars.dor_construction_class).includes("Frame") ? "text-red-400" : "text-white"
                        }`}>{String(chars.construction_class || chars.dor_construction_class)}</p>
                      </div>
                    )}
                    {!!chars.stories && (
                      <div>
                        <p className="text-gray-500 text-xs">Stories</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.stories)}</p>
                      </div>
                    )}
                    {!!chars.building_type && (
                      <div>
                        <p className="text-gray-500 text-xs">Building Type</p>
                        <p className="text-white text-sm font-medium mt-1 capitalize">{String(chars.building_type)}</p>
                      </div>
                    )}
                    {!!chars.building_material && (
                      <div>
                        <p className="text-gray-500 text-xs">Material</p>
                        <p className="text-white text-sm font-medium mt-1 capitalize">{String(chars.building_material)}</p>
                      </div>
                    )}
                    {!!(chars.year_built || chars.dor_year_built) && (
                      <div>
                        <p className="text-gray-500 text-xs">Year Built</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.year_built || chars.dor_year_built)}</p>
                      </div>
                    )}
                    {!!(chars.units_estimate || chars.dor_num_units) && (
                      <div>
                        <p className="text-gray-500 text-xs">Units</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.units_estimate || chars.dor_num_units)}</p>
                      </div>
                    )}
                    {!!chars.footprint_sqft && (
                      <div>
                        <p className="text-gray-500 text-xs">Footprint</p>
                        <p className="text-white text-sm font-medium mt-1">{safeNum(chars.footprint_sqft)} sqft</p>
                      </div>
                    )}
                    {!!chars.tiv_estimate && (
                      <div>
                        <p className="text-gray-500 text-xs">Est. TIV</p>
                        <p className="text-white text-sm font-semibold mt-1">${safeNum(chars.tiv_estimate)}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Flood & Risk Profile */}
            {!!chars.flood_zone && (
              <div>
                <h2 className="text-sm font-semibold text-gray-300 mb-3">Flood & Risk Profile</h2>
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <p className="text-gray-500 text-xs">FEMA Flood Zone</p>
                      <p className={`text-sm font-medium mt-1 ${
                        String(chars.flood_risk) === "extreme" ? "text-red-400" :
                        String(chars.flood_risk) === "high" ? "text-orange-400" :
                        String(chars.flood_risk) === "moderate_high" ? "text-amber-400" :
                        "text-green-400"
                      }`}>{String(chars.flood_zone_label || chars.flood_zone)}</p>
                    </div>
                    {chars.flood_sfha !== undefined && (
                      <div>
                        <p className="text-gray-500 text-xs">Special Flood Hazard Area</p>
                        <p className={`text-sm font-medium mt-1 ${chars.flood_sfha ? "text-red-400" : "text-green-400"}`}>
                          {chars.flood_sfha ? "Yes — flood insurance required" : "No"}
                        </p>
                      </div>
                    )}
                    {!!chars.flood_base_elev_ft && (
                      <div>
                        <p className="text-gray-500 text-xs">Base Flood Elevation</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.flood_base_elev_ft)} ft</p>
                      </div>
                    )}
                    {!!chars.fema_map_url && (
                      <div>
                        <p className="text-gray-500 text-xs">FEMA Map</p>
                        <a href={String(chars.fema_map_url)} target="_blank" rel="noopener noreferrer"
                          className="text-blue-400 text-sm hover:underline mt-1 block">View on FEMA MSC</a>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Property Appraiser */}
            {!!chars.pa_lookup_url && (
              <div>
                <h2 className="text-sm font-semibold text-gray-300 mb-3">Property Appraiser</h2>
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {!!chars.pa_owner && (
                      <div>
                        <p className="text-gray-500 text-xs">Owner</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.pa_owner)}</p>
                      </div>
                    )}
                    {!!chars.pa_assessed_value && (
                      <div>
                        <p className="text-gray-500 text-xs">Assessed Value</p>
                        <p className="text-white text-sm font-medium mt-1">${safeNum(chars.pa_assessed_value)}</p>
                      </div>
                    )}
                    {!!chars.pa_year_built && (
                      <div>
                        <p className="text-gray-500 text-xs">Year Built (PA)</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.pa_year_built)}</p>
                      </div>
                    )}
                    {!!chars.pa_building_sqft && (
                      <div>
                        <p className="text-gray-500 text-xs">Building Sqft</p>
                        <p className="text-white text-sm font-medium mt-1">{safeNum(chars.pa_building_sqft)}</p>
                      </div>
                    )}
                    {!!chars.pa_parcel_id && (
                      <div>
                        <p className="text-gray-500 text-xs">Parcel ID</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.pa_parcel_id)}</p>
                      </div>
                    )}
                    <div>
                      <p className="text-gray-500 text-xs">Lookup</p>
                      <a href={String(chars.pa_lookup_url)} target="_blank" rel="noopener noreferrer"
                        className="text-blue-400 text-sm hover:underline mt-1 block">View on Property Appraiser</a>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* DOR Tax Roll */}
            {!!(chars.dor_owner || chars.dor_market_value) && (
              <div>
                <h2 className="text-sm font-semibold text-gray-300 mb-3">DOR Tax Roll</h2>
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {!!chars.dor_owner && (
                      <div className="col-span-2">
                        <p className="text-gray-500 text-xs">Owner</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.dor_owner)}</p>
                        {!!chars.dor_owner_address && (
                          <p className="text-gray-600 text-[10px] mt-0.5">{String(chars.dor_owner_address)}</p>
                        )}
                      </div>
                    )}
                    {!!chars.dor_market_value && (
                      <div>
                        <p className="text-gray-500 text-xs">Market Value</p>
                        <p className="text-white text-sm font-semibold mt-1">${safeNum(chars.dor_market_value)}</p>
                      </div>
                    )}
                    {!!chars.dor_land_value && (
                      <div>
                        <p className="text-gray-500 text-xs">Land Value</p>
                        <p className="text-white text-sm mt-1">${safeNum(chars.dor_land_value)}</p>
                      </div>
                    )}
                    {!!chars.dor_construction_class && (
                      <div>
                        <p className="text-gray-500 text-xs">Construction Class</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.dor_construction_class)}</p>
                      </div>
                    )}
                    {!!chars.dor_use_description && (
                      <div>
                        <p className="text-gray-500 text-xs">Use Type</p>
                        <p className="text-white text-sm mt-1">{String(chars.dor_use_description)}</p>
                      </div>
                    )}
                    {!!chars.dor_living_sqft && (
                      <div>
                        <p className="text-gray-500 text-xs">Living Area</p>
                        <p className="text-white text-sm mt-1">{safeNum(chars.dor_living_sqft)} sqft</p>
                      </div>
                    )}
                    {!!chars.dor_num_units && (
                      <div>
                        <p className="text-gray-500 text-xs">Units</p>
                        <p className="text-white text-sm mt-1">{String(chars.dor_num_units)}</p>
                      </div>
                    )}
                    {!!chars.dor_num_buildings && (
                      <div>
                        <p className="text-gray-500 text-xs">Buildings</p>
                        <p className="text-white text-sm mt-1">{String(chars.dor_num_buildings)}</p>
                      </div>
                    )}
                    {!!chars.dor_last_sale_price && (
                      <div>
                        <p className="text-gray-500 text-xs">Last Sale</p>
                        <p className="text-white text-sm mt-1">
                          ${safeNum(chars.dor_last_sale_price)}
                          {!!chars.dor_last_sale_date && <span className="text-gray-500 text-xs ml-1">({String(chars.dor_last_sale_date)})</span>}
                        </p>
                      </div>
                    )}
                    {!!chars.dor_parcel_id && (
                      <div>
                        <p className="text-gray-500 text-xs">Parcel ID</p>
                        <p className="text-gray-400 text-xs mt-1 font-mono">{String(chars.dor_parcel_id)}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* DBPR Condo Association Data */}
            {!!(chars.dbpr_condo_name || chars.dbpr_managing_entity) && (
              <div>
                <h2 className="text-sm font-semibold text-gray-300 mb-3">DBPR Condo Registry</h2>
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    {!!chars.dbpr_condo_name && (
                      <div>
                        <p className="text-gray-500 text-xs">DBPR Condo Name</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.dbpr_condo_name)}</p>
                      </div>
                    )}
                    {!!chars.dbpr_official_units && (
                      <div>
                        <p className="text-gray-500 text-xs">Official Units</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.dbpr_official_units)}</p>
                      </div>
                    )}
                    {!!chars.dbpr_managing_entity && (
                      <div>
                        <p className="text-gray-500 text-xs">Managing Entity</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.dbpr_managing_entity)}</p>
                      </div>
                    )}
                    {!!chars.dbpr_managing_entity_address && (
                      <div>
                        <p className="text-gray-500 text-xs">Mgmt Address</p>
                        <p className="text-gray-400 text-xs mt-1">{String(chars.dbpr_managing_entity_address)}</p>
                      </div>
                    )}
                    {!!chars.dbpr_status && (
                      <div>
                        <p className="text-gray-500 text-xs">Status</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.dbpr_status)}</p>
                      </div>
                    )}
                    {!!chars.dbpr_project_number && (
                      <div>
                        <p className="text-gray-500 text-xs">Project #</p>
                        <p className="text-gray-400 text-xs mt-1">{String(chars.dbpr_project_number)}</p>
                      </div>
                    )}
                    {!!chars.dbpr_operating_revenue && (
                      <div>
                        <p className="text-gray-500 text-xs">Operating Revenue</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.dbpr_operating_revenue)}</p>
                      </div>
                    )}
                    {!!chars.dbpr_operating_expenses && (
                      <div>
                        <p className="text-gray-500 text-xs">Operating Expenses</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.dbpr_operating_expenses)}</p>
                      </div>
                    )}
                    {!!chars.dbpr_reserve_fund_balance && (
                      <div>
                        <p className="text-gray-500 text-xs">Reserve Fund Balance</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.dbpr_reserve_fund_balance)}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* CAM License */}
            {!!(chars.cam_license_number || chars.cam_license_warning) && (
              <div>
                <h2 className="text-sm font-semibold text-gray-300 mb-3">CAM License</h2>
                <div className={`bg-gray-900 border rounded-lg p-4 ${
                  chars.cam_license_active === false ? "border-red-800" :
                  chars.cam_license_found === false ? "border-amber-800" :
                  "border-gray-800"
                }`}>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    {!!chars.cam_license_name && (
                      <div>
                        <p className="text-gray-500 text-xs">Licensed CAM</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.cam_license_name)}</p>
                      </div>
                    )}
                    {!!chars.cam_license_number && (
                      <div>
                        <p className="text-gray-500 text-xs">License #</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.cam_license_number)}</p>
                      </div>
                    )}
                    {!!chars.cam_license_expiration && (
                      <div>
                        <p className="text-gray-500 text-xs">Expires</p>
                        <p className={`text-sm font-medium mt-1 ${chars.cam_license_active ? "text-green-400" : "text-red-400"}`}>
                          {String(chars.cam_license_expiration)} {chars.cam_license_active ? "(active)" : "(EXPIRED)"}
                        </p>
                      </div>
                    )}
                    {!!chars.cam_license_warning && (
                      <div className="col-span-full">
                        <p className="text-amber-400 text-sm">{String(chars.cam_license_warning)}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Sunbiz / Association */}
            {!!(chars.sunbiz_corp_name || chars.sunbiz_search_url) && (
              <div>
                <h2 className="text-sm font-semibold text-gray-300 mb-3">Association (Sunbiz)</h2>
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    {!!chars.sunbiz_corp_name && (
                      <div>
                        <p className="text-gray-500 text-xs">Corporation Name</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.sunbiz_corp_name)}</p>
                      </div>
                    )}
                    {!!chars.sunbiz_filing_status && (
                      <div>
                        <p className="text-gray-500 text-xs">Filing Status</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.sunbiz_filing_status)}</p>
                      </div>
                    )}
                    {!!chars.property_manager && (
                      <div>
                        <p className="text-gray-500 text-xs">Registered Agent / Mgmt Co.</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.property_manager)}</p>
                      </div>
                    )}
                    {!!chars.sunbiz_doc_number && (
                      <div>
                        <p className="text-gray-500 text-xs">Document #</p>
                        <p className="text-white text-sm font-medium mt-1">{String(chars.sunbiz_doc_number)}</p>
                      </div>
                    )}
                    <div>
                      <p className="text-gray-500 text-xs">Lookup</p>
                      <a href={String(chars.sunbiz_detail_url || chars.sunbiz_search_url)} target="_blank" rel="noopener noreferrer"
                        className="text-blue-400 text-sm hover:underline mt-1 block">View on Sunbiz</a>
                    </div>
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
                      "footprint_sqft", "tiv_estimate", "height_m",
                      "flood_zone", "flood_zone_label", "flood_zone_subtype", "flood_risk", "flood_sfha",
                      "flood_base_elev_ft", "flood_score_impact", "fema_map_url",
                      "pa_owner", "pa_assessed_value", "pa_year_built", "pa_building_sqft", "pa_parcel_id",
                      "pa_lot_sqft", "pa_acres", "pa_use_code", "pa_last_sale_date", "pa_last_sale_price",
                      "pa_county", "pa_lookup_url",
                      "sunbiz_search_url", "sunbiz_search_name", "sunbiz_corp_name", "sunbiz_doc_number",
                      "sunbiz_detail_url", "sunbiz_filing_status", "sunbiz_registered_agent", "property_manager",
                      "sunbiz_filing_date", "sunbiz_principal_address",
                      "dbpr_condo_name", "dbpr_project_number", "dbpr_file_number", "dbpr_official_units",
                      "dbpr_status", "dbpr_managing_entity", "dbpr_managing_entity_number",
                      "dbpr_managing_entity_address", "dbpr_operating_revenue", "dbpr_operating_expenses",
                      "dbpr_reserve_revenue", "dbpr_operating_fund_balance", "dbpr_reserve_fund_balance",
                      "dbpr_fiscal_year_end", "dbpr_search_url", "dbpr_cam_name", "dbpr_cam_license",
                      "dbpr_cam_status", "dbpr_cam_address", "dbpr_management_company",
                      "cam_license_number", "cam_license_name", "cam_license_address",
                      "cam_license_expiration", "cam_license_active", "cam_license_found", "cam_license_warning",
                      "citizens_likelihood", "citizens_county_penetration", "citizens_estimated_premium",
                      "citizens_premium_display", "citizens_risk_factors", "on_citizens",
                      "citizens_swap_opportunity",
                      "dor_parcel_id", "dor_owner", "dor_owner_address", "dor_market_value",
                      "dor_land_value", "dor_construction_class", "dor_use_code", "dor_use_description",
                      "dor_year_built", "dor_effective_year_built", "dor_living_sqft",
                      "dor_num_buildings", "dor_num_units", "dor_last_sale_price",
                      "dor_last_sale_year", "dor_last_sale_date", "dor_special_features_value", "dor_land_sqft",
                      "has_user_intel", "user_doc_types", "_field_sources"].includes(k))
                    .map(([key, val]) => (
                    <div key={key} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                      <p className="text-gray-500 text-xs capitalize">{key.replace(/_/g, " ")}</p>
                      <p className="text-white text-sm mt-1">
                        {Array.isArray(val) ? val.map(String).join(", ") : String(val || "\u2014")}
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
                <p className="text-gray-500 mt-1">
                  {lead.latitude != null && lead.longitude != null
                    ? `${lead.latitude.toFixed(6)}, ${lead.longitude.toFixed(6)}`
                    : "No coordinates"}
                </p>
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
                    {pol.prior_premium != null && <div><span className="text-gray-500">Prior: </span><span>{fmt(pol.prior_premium)}</span></div>}
                    {pol.premium != null && pol.tiv != null && pol.tiv > 0 && (
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
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-300">Documents</h2>
              {canEdit && (
              <label className="bg-blue-600 hover:bg-blue-700 text-white text-xs px-3 py-1 rounded font-medium cursor-pointer">
                + Upload Document
                <input type="file" className="hidden" onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const docType = file.name.toLowerCase().includes("brochure") ? "BROCHURE" :
                    file.name.toLowerCase().includes("dec") ? "DEC_PAGE" :
                    file.name.toLowerCase().includes("loss") ? "LOSS_RUN" :
                    file.name.toLowerCase().includes("audit") ? "AUDIT" :
                    file.name.toLowerCase().includes("sunbiz") ? "SUNBIZ" : "OTHER";
                  try {
                    const formData = new FormData();
                    formData.append("file", file);
                    formData.append("doc_type", docType);
                    const res = await fetch(`/api/proxy/leads/${id}/upload`, { method: "POST", body: formData });
                    if (res.ok) {
                      const updated = await fetch(`/api/proxy/leads/${id}`);
                      if (updated.ok) setLead(await updated.json());
                    }
                  } catch (err) {
                    console.error("Upload failed:", err);
                  }
                  e.target.value = "";
                }} />
              </label>
              )}
            </div>
            {lead.assets.length === 0 ? (
              <p className="text-gray-600 text-sm">No documents attached. Upload brochures, dec pages, loss runs, or other intel.</p>
            ) : (
              lead.assets.map((asset) => (
                <div key={asset.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <span className="bg-blue-900 text-blue-300 text-xs px-2 py-0.5 rounded font-medium">{asset.doc_type}</span>
                    {asset.source && (
                      <span className="bg-gray-800 text-gray-500 text-[10px] px-1.5 py-0.5 rounded">via {asset.source}</span>
                    )}
                    {asset.filename && (
                      <span className="text-gray-500 text-xs">{asset.filename}</span>
                    )}
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
                    {emailObj && canEdit && (
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

        {activeTab === "engage" && (
          <div className="space-y-6">
            {/* Step 1: Select contact */}
            <div>
              <h2 className="text-sm font-semibold text-gray-300 mb-3">1. Select Contact</h2>
              {lead.contacts.length === 0 ? (
                <p className="text-gray-600 text-sm">No contacts yet. Add a contact on the Contacts tab first.</p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {lead.contacts.map((c) => (
                    <div key={c.id} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                      <div className="flex items-center gap-2">
                        <p className="text-white font-medium text-sm">{c.name}</p>
                        {!!c.is_primary && <span className="bg-green-900 text-green-300 text-[10px] px-1.5 py-0.5 rounded">PRIMARY</span>}
                      </div>
                      <p className="text-gray-500 text-xs">{c.title}</p>
                      {c.email && <p className="text-blue-400 text-xs">{c.email}</p>}
                      {c.phone && <p className="text-gray-400 text-xs">{c.phone}</p>}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Step 2: Pick email style & send */}
            <div>
              <h2 className="text-sm font-semibold text-gray-300 mb-3">2. Choose Outreach Email</h2>
              {!lead.emails || Object.keys(lead.emails).length === 0 ? (
                <p className="text-gray-600 text-sm">No emails generated. Mark as Candidate to trigger AI email generation.</p>
              ) : (
                <div className="space-y-3">
                  {Object.entries(lead.emails).map(([style, email]) => {
                    const emailObj = typeof email === "object" && email !== null ? email as {subject?: string; body?: string} : null;
                    if (!emailObj) return null;
                    return (
                      <div key={style} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                        <div className="flex items-center justify-between mb-2">
                          <span className="bg-purple-900 text-purple-300 text-xs px-2 py-0.5 rounded font-medium uppercase">{style}</span>
                          {canEdit && (
                            <button
                              onClick={() => handleSendOutreach(style, emailObj.subject || "", emailObj.body || "")}
                              disabled={sendingStyle === style || lead.contacts.length === 0}
                              className="bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white text-xs px-4 py-2 rounded font-medium"
                            >
                              {sendingStyle === style ? "Sending..." : "Queue Outreach"}
                            </button>
                          )}
                        </div>
                        <p className="text-white text-sm font-medium mb-1">{emailObj.subject}</p>
                        <div className="bg-gray-800 rounded p-3 text-xs text-gray-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
                          {emailObj.body}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Step 3: Convert to customer */}
            {lead.pipeline_stage === "OPPORTUNITY" && canEdit && (
              <div>
                <h2 className="text-sm font-semibold text-gray-300 mb-3">3. Convert to Customer</h2>
                <p className="text-gray-500 text-xs mb-3">When the deal closes, mark this as a customer to move it out of the pipeline.</p>
                <button
                  onClick={() => handleStageChange("CUSTOMER")}
                  disabled={stageChanging}
                  className="bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white text-sm px-6 py-2.5 rounded font-medium">
                  {stageChanging ? "Converting..." : "Mark as Customer"}
                </button>
              </div>
            )}

            {/* Engagement history */}
            {lead.engagements.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold text-gray-300 mb-3">Outreach History</h2>
                <div className="space-y-2">
                  {lead.engagements.map((eng) => (
                    <div key={eng.id} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="bg-blue-900 text-blue-300 text-[10px] px-1.5 py-0.5 rounded">{eng.type}</span>
                        <span className="bg-gray-800 text-gray-400 text-[10px] px-1.5 py-0.5 rounded">{eng.status}</span>
                        {eng.style && <span className="text-gray-600 text-[10px]">{eng.style}</span>}
                        <span className="text-gray-700 text-[10px] ml-auto">{new Date(eng.created_at).toLocaleDateString()}</span>
                      </div>
                      {eng.subject && <p className="text-white text-xs">{eng.subject}</p>}
                    </div>
                  ))}
                </div>
              </div>
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
              {canEdit && (
                <button
                  onClick={() => setShowAddContact(!showAddContact)}
                  className="bg-blue-600 hover:bg-blue-700 text-white text-xs px-3 py-1 rounded font-medium"
                >
                  {showAddContact ? "Cancel" : "+ Add Contact"}
                </button>
              )}
            </div>
            {canEdit && showAddContact && (
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
                      {contact.source && (
                        <span className="bg-gray-800 text-gray-500 text-[10px] px-1.5 py-0.5 rounded">
                          via {contact.source}
                        </span>
                      )}
                    </div>
                    <p className="text-gray-500 text-sm">{contact.title}</p>
                    {contact.email && <p className="text-blue-400 text-sm mt-1">{contact.email}</p>}
                    {contact.phone && <p className="text-gray-400 text-sm">{contact.phone}</p>}
                    {contact.source_url && (
                      <a href={contact.source_url} target="_blank" rel="noopener noreferrer"
                        className="text-gray-600 text-xs hover:text-blue-400 mt-1 block">Source link</a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === "sources" && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Data Sources & Enrichment History</h2>
            <p className="text-gray-600 text-xs mb-4">
              Every piece of intelligence is tracked back to its source. Click links to verify data.
            </p>
            {Object.keys(lead.enrichment_sources || {}).length === 0 ? (
              <p className="text-gray-600 text-sm">No enrichment sources recorded yet.</p>
            ) : (
              <div className="space-y-3">
                {Object.entries(lead.enrichment_sources).map(([sourceId, infoRaw]) => {
                  const info = infoRaw as { timestamp?: string; fields_updated: string[]; url?: string | null };
                  const sourceColors: Record<string, string> = {
                    overpass: "border-blue-800 bg-blue-950/30",
                    fema_flood: "border-cyan-800 bg-cyan-950/30",
                    fdot_parcels: "border-orange-800 bg-orange-950/30",
                    property_appraiser: "border-amber-800 bg-amber-950/30",
                    dbpr_bulk: "border-teal-800 bg-teal-950/30",
                    dbpr_condo: "border-lime-800 bg-lime-950/30",
                    sunbiz: "border-purple-800 bg-purple-950/30",
                    user_upload: "border-green-800 bg-green-950/30",
                    ai_analyzer: "border-pink-800 bg-pink-950/30",
                  };
                  const badgeColors: Record<string, string> = {
                    overpass: "bg-blue-900 text-blue-300",
                    fema_flood: "bg-cyan-900 text-cyan-300",
                    fdot_parcels: "bg-orange-900 text-orange-300",
                    property_appraiser: "bg-amber-900 text-amber-300",
                    dbpr_bulk: "bg-teal-900 text-teal-300",
                    dbpr_condo: "bg-lime-900 text-lime-300",
                    sunbiz: "bg-purple-900 text-purple-300",
                    user_upload: "bg-green-900 text-green-300",
                    ai_analyzer: "bg-pink-900 text-pink-300",
                  };
                  const sourceLabels: Record<string, string> = {
                    overpass: "OpenStreetMap Overpass API",
                    fema_flood: "FEMA National Flood Hazard Layer",
                    fdot_parcels: "FL DOT/DOR Statewide Parcels",
                    dor_nal: "FL DOR Tax Roll (NAL)",
                    property_appraiser: "County Property Appraiser",
                    dbpr_bulk: "DBPR Condo Registry (Bulk CSV)",
                    dbpr_condo: "DBPR CAM License Lookup",
                    cam_license: "CAM License Cross-Reference",
                    dbpr_payments: "DBPR Payment History",
                    sunbiz: "Florida Sunbiz (Div. of Corporations)",
                    user_upload: "User Upload",
                    ai_analyzer: "AI Analyzer (Claude)",
                  };
                  return (
                    <div key={sourceId} className={`border rounded-lg p-4 ${sourceColors[sourceId] || "border-gray-800 bg-gray-900"}`}>
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className={`text-xs px-2 py-0.5 rounded font-medium ${badgeColors[sourceId] || "bg-gray-800 text-gray-400"}`}>
                            {sourceId}
                          </span>
                          <span className="text-gray-400 text-sm">{sourceLabels[sourceId] || sourceId}</span>
                        </div>
                        <span className="text-gray-600 text-xs">
                          {info.timestamp ? new Date(info.timestamp).toLocaleDateString() : ""}
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-1 mb-2">
                        {(info.fields_updated || []).map((field: string) => (
                          <span key={field} className="bg-gray-800 text-gray-500 text-[10px] px-1.5 py-0.5 rounded">
                            {field}
                          </span>
                        ))}
                      </div>
                      {info.url && (
                        <a href={info.url} target="_blank" rel="noopener noreferrer"
                          className="text-blue-400 text-xs hover:underline">
                          View source
                        </a>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
