"use client";

import { useEffect, useState } from "react";

interface LeadDetail {
  id: number;
  name: string;
  address: string;
  county: string;
  latitude: number;
  longitude: number;
  pipeline_stage: string;
  characteristics: Record<string, unknown>;
  heat_score: string;
  tiv_parsed: number | null;
  premium_parsed: number | null;
  contacts: { id: number; name: string; title: string; email: string | null; phone: string | null; is_primary: number; source: string | null }[];
  enrichment_sources: Record<string, { source: string; timestamp: string; fields_updated: string[]; url: string | null }>;
  policies: { id: number; coverage_type: string; carrier: string | null; premium: number | null; tiv: number | null; is_active: number }[];
  assets: { id: number; doc_type: string; filename: string | null }[];
}

const HEAT = { hot: "bg-red-600", warm: "bg-orange-600", cold: "bg-gray-700" } as Record<string, string>;
const STAGE_C = { TARGET: "bg-gray-700", LEAD: "bg-cyan-900", OPPORTUNITY: "bg-amber-900", CUSTOMER: "bg-green-800", ARCHIVED: "bg-red-900" } as Record<string, string>;

function fmt(v: number | null | undefined) {
  if (v == null) return "\u2014";
  return "$" + v.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function DataRow({ label, value, href }: { label: string; value: unknown; href?: string }) {
  if (value === null || value === undefined || value === "" || value === 0) return null;
  return (
    <div className="flex justify-between py-1 border-b border-gray-800/50">
      <span className="text-gray-500 text-xs">{label}</span>
      {href ? (
        <a href={String(href)} target="_blank" rel="noopener noreferrer" className="text-blue-400 text-xs hover:underline truncate ml-2 max-w-[200px]">
          {String(value)}
        </a>
      ) : (
        <span className="text-white text-xs font-medium truncate ml-2 max-w-[200px]">{String(value)}</span>
      )}
    </div>
  );
}

function DataSection({ title, children }: { title: string; children: React.ReactNode }) {
  const filtered = Array.isArray(children)
    ? children.filter((c) => c !== null && c !== undefined && c !== false)
    : children ? [children] : [];
  if (filtered.length === 0) return null;
  return (
    <div className="mb-4">
      <h3 className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">{title}</h3>
      <div className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-1.5">{filtered}</div>
    </div>
  );
}

type Tab = "overview" | "contacts" | "sources";

interface Props {
  entityId: number;
  onClose: () => void;
  isActive: boolean;
  onFlyTo?: (lat: number, lng: number) => void;
}

export default function EntityDetailModal({ entityId, onClose, isActive, onFlyTo }: Props) {
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [stageChanging, setStageChanging] = useState(false);

  useEffect(() => {
    setError(null);
    setLead(null);
    setTab("overview");
    fetch(`/api/proxy/leads/${entityId}`)
      .then((r) => r.ok ? r.json() : Promise.reject(`${r.status}`))
      .then(setLead)
      .catch((e) => setError(String(e)));
  }, [entityId]);

  async function changeStage(stage: string) {
    setStageChanging(true);
    try {
      await fetch(`/api/proxy/leads/${entityId}/stage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage, force: true }),
      });
      const r = await fetch(`/api/proxy/leads/${entityId}`);
      if (r.ok) setLead(await r.json());
    } catch {}
    setStageChanging(false);
  }

  const chars = lead?.characteristics || {};

  return (
    <div className={`fixed top-0 right-0 h-full w-full sm:w-[460px] bg-gray-950 border-l border-gray-800 shadow-2xl flex flex-col transition-all ${isActive ? "z-50" : "z-40 opacity-90"}`}>
      {/* Header */}
      <div className="bg-gray-900 border-b border-gray-800 px-4 py-3 shrink-0">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full text-white shrink-0 ${HEAT[lead?.heat_score || "cold"] || HEAT.cold}`}>
              {lead?.heat_score || "..."}
            </span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full text-white shrink-0 ${STAGE_C[lead?.pipeline_stage || "TARGET"]}`}>
              {lead?.pipeline_stage || "..."}
            </span>
            <h2 className="text-sm font-bold truncate">{lead?.name || `#${entityId}`}</h2>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white text-lg ml-2 shrink-0 w-6 h-6 flex items-center justify-center">&times;</button>
        </div>
        {lead && (
          <div className="flex items-center gap-3 text-[11px] text-gray-500">
            <span className="truncate">{lead.address}</span>
            <span className="shrink-0">{lead.county}</span>
            {lead.latitude > 0 && onFlyTo && (
              <button onClick={() => onFlyTo(lead.latitude, lead.longitude)} className="text-blue-400 hover:underline shrink-0">Map</button>
            )}
          </div>
        )}
        {lead && (
          <div className="flex items-center gap-3 mt-1.5">
            <span className="text-xs text-gray-500">TIV: <span className="text-white font-medium">{fmt(lead.tiv_parsed || (chars.tiv_estimate as number))}</span></span>
            <span className="text-xs text-gray-500">MV: <span className="text-white font-medium">{fmt(chars.dor_market_value as number)}</span></span>
            <div className="ml-auto">
              <select value={lead.pipeline_stage} onChange={(e) => changeStage(e.target.value)} disabled={stageChanging}
                className="bg-gray-800 border border-gray-700 text-white text-[11px] rounded px-1.5 py-0.5">
                {["TARGET", "LEAD", "OPPORTUNITY", "CUSTOMER", "ARCHIVED"].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-800 shrink-0">
        {(["overview", "contacts", "sources"] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex-1 text-center py-2 text-xs font-medium border-b-2 ${tab === t ? "border-blue-500 text-white" : "border-transparent text-gray-500 hover:text-gray-300"}`}>
            {t === "overview" ? "Overview" : t === "contacts" ? `Contacts (${lead?.contacts.length || 0})` : `Sources (${Object.keys(lead?.enrichment_sources || {}).length})`}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {error && <p className="text-red-400 text-sm">Failed to load: {error}</p>}
        {!lead && !error && <p className="text-gray-600 text-sm">Loading...</p>}

        {lead && tab === "overview" && (
          <>
            <DataSection title="Building Profile">
              <DataRow label="Construction" value={chars.construction_class || chars.dor_construction_class} />
              <DataRow label="Stories" value={chars.stories} />
              <DataRow label="Year Built" value={chars.year_built || chars.dor_year_built} />
              <DataRow label="Units" value={chars.units_estimate || chars.dor_num_units} />
              <DataRow label="Living Area" value={chars.dor_living_sqft ? `${Number(chars.dor_living_sqft).toLocaleString()} sqft` : null} />
              <DataRow label="Buildings" value={chars.dor_num_buildings} />
              <DataRow label="Use Type" value={chars.dor_use_description} />
              <DataRow label="Est. TIV" value={chars.tiv_estimate ? `$${Number(chars.tiv_estimate).toLocaleString()}` : null} />
            </DataSection>

            <DataSection title="Flood & Risk">
              <DataRow label="FEMA Zone" value={chars.flood_zone_label || chars.flood_zone} />
              <DataRow label="Risk Level" value={chars.flood_risk} />
              <DataRow label="SFHA" value={chars.flood_sfha ? "Yes - flood insurance required" : chars.flood_sfha === false ? "No" : null} />
              <DataRow label="Base Elevation" value={chars.flood_base_elev_ft ? `${chars.flood_base_elev_ft} ft` : null} />
              <DataRow label="FEMA Map" value={chars.fema_map_url ? "View on FEMA" : null} href={chars.fema_map_url as string} />
            </DataSection>

            <DataSection title="Citizens Insurance">
              <DataRow label="Likelihood" value={chars.citizens_likelihood ? `${chars.citizens_likelihood}%` : null} />
              <DataRow label="On Citizens" value={chars.on_citizens ? "YES - Swap Opportunity" : null} />
              <DataRow label="Est. Premium" value={chars.citizens_premium_display} />
              <DataRow label="Swap Opp." value={chars.citizens_swap_opportunity ? "Yes" : null} />
            </DataSection>

            <DataSection title="DOR Tax Roll">
              <DataRow label="Owner" value={chars.dor_owner} />
              <DataRow label="Owner Address" value={chars.dor_owner_address} />
              <DataRow label="Market Value" value={chars.dor_market_value ? `$${Number(chars.dor_market_value).toLocaleString()}` : null} />
              <DataRow label="Land Value" value={chars.dor_land_value ? `$${Number(chars.dor_land_value).toLocaleString()}` : null} />
              <DataRow label="Last Sale" value={chars.dor_last_sale_price ? `$${Number(chars.dor_last_sale_price).toLocaleString()} (${chars.dor_last_sale_date || ""})` : null} />
              <DataRow label="Parcel ID" value={chars.dor_parcel_id} />
            </DataSection>

            <DataSection title="Property Appraiser">
              <DataRow label="PA Owner" value={chars.pa_owner} />
              <DataRow label="Assessed Value" value={chars.pa_assessed_value ? `$${Number(chars.pa_assessed_value).toLocaleString()}` : null} />
              <DataRow label="Parcel ID" value={chars.pa_parcel_id} />
              <DataRow label="Lookup" value={chars.pa_lookup_url ? "View on PA Site" : null} href={chars.pa_lookup_url as string} />
            </DataSection>

            <DataSection title="DBPR Condo Registry">
              <DataRow label="Condo Name" value={chars.dbpr_condo_name} />
              <DataRow label="Managing Entity" value={chars.dbpr_managing_entity} />
              <DataRow label="Project #" value={chars.dbpr_project_number} />
              <DataRow label="Official Units" value={chars.dbpr_official_units} />
              <DataRow label="Status" value={chars.dbpr_status} />
              <DataRow label="Reserve Fund" value={chars.dbpr_reserve_fund_balance} />
            </DataSection>

            <DataSection title="CAM License">
              <DataRow label="License #" value={chars.cam_license_number} />
              <DataRow label="Name" value={chars.cam_license_name} />
              <DataRow label="Expires" value={chars.cam_license_expiration} />
              <DataRow label="Active" value={chars.cam_license_active === true ? "Yes" : chars.cam_license_active === false ? "EXPIRED" : null} />
              {chars.cam_license_warning && <DataRow label="Warning" value={chars.cam_license_warning} />}
            </DataSection>

            <DataSection title="Sunbiz (Association)">
              <DataRow label="Corp Name" value={chars.sunbiz_corp_name} />
              <DataRow label="Filing Status" value={chars.sunbiz_filing_status} />
              <DataRow label="Registered Agent" value={chars.property_manager} />
              <DataRow label="Doc #" value={chars.sunbiz_doc_number} />
              <DataRow label="Lookup" value={chars.sunbiz_detail_url || chars.sunbiz_search_url ? "View on Sunbiz" : null} href={(chars.sunbiz_detail_url || chars.sunbiz_search_url) as string} />
            </DataSection>

            {lead.policies.length > 0 && (
              <DataSection title={`Policies (${lead.policies.length})`}>
                {lead.policies.map((p) => (
                  <div key={p.id} className="py-1.5 border-b border-gray-800/50">
                    <div className="flex justify-between">
                      <span className="text-xs text-blue-400">{p.coverage_type}</span>
                      <span className={`text-[10px] ${p.is_active ? "text-green-400" : "text-gray-600"}`}>{p.is_active ? "ACTIVE" : "expired"}</span>
                    </div>
                    <div className="flex gap-3 text-[11px] text-gray-400 mt-0.5">
                      {p.carrier && <span>{p.carrier}</span>}
                      {p.premium != null && <span>Premium: {fmt(p.premium)}</span>}
                      {p.tiv != null && <span>TIV: {fmt(p.tiv)}</span>}
                    </div>
                  </div>
                ))}
              </DataSection>
            )}

            {/* Location */}
            {lead.latitude > 0 && (
              <DataSection title="Location">
                <DataRow label="Coordinates" value={`${lead.latitude.toFixed(5)}, ${lead.longitude.toFixed(5)}`} />
              </DataSection>
            )}
          </>
        )}

        {lead && tab === "contacts" && (
          <div className="space-y-2">
            {lead.contacts.length === 0 ? (
              <p className="text-gray-600 text-sm">No contacts found.</p>
            ) : (
              lead.contacts.map((c) => (
                <div key={c.id} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                  <div className="flex items-center gap-2">
                    <span className="text-white text-sm font-medium">{c.name}</span>
                    {!!c.is_primary && <span className="bg-green-900 text-green-300 text-[9px] px-1 py-0.5 rounded">PRIMARY</span>}
                  </div>
                  {c.title && <p className="text-gray-500 text-xs">{c.title}</p>}
                  {c.email && <p className="text-blue-400 text-xs mt-0.5">{c.email}</p>}
                  {c.phone && <p className="text-gray-400 text-xs">{c.phone}</p>}
                  {c.source && <p className="text-gray-600 text-[10px] mt-0.5">via {c.source}</p>}
                </div>
              ))
            )}
          </div>
        )}

        {lead && tab === "sources" && (
          <div className="space-y-2">
            {Object.keys(lead.enrichment_sources || {}).length === 0 ? (
              <p className="text-gray-600 text-sm">No enrichment sources yet.</p>
            ) : (
              Object.entries(lead.enrichment_sources).map(([src, info]) => {
                const badgeColors: Record<string, string> = {
                  dor_nal: "bg-gray-800 text-gray-400",
                  fema_flood: "bg-cyan-900 text-cyan-300",
                  property_appraiser: "bg-amber-900 text-amber-300",
                  dbpr_bulk: "bg-teal-900 text-teal-300",
                  dbpr_payments: "bg-teal-900 text-teal-300",
                  cam_license: "bg-lime-900 text-lime-300",
                  sunbiz: "bg-purple-900 text-purple-300",
                  citizens_insurance: "bg-red-900 text-red-300",
                  fdot_parcels: "bg-orange-900 text-orange-300",
                  overpass: "bg-blue-900 text-blue-300",
                };
                return (
                  <div key={src} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${badgeColors[src] || "bg-gray-800 text-gray-400"}`}>{src}</span>
                      <span className="text-gray-600 text-[10px]">{info.timestamp ? new Date(info.timestamp).toLocaleDateString() : ""}</span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {(info.fields_updated || []).slice(0, 8).map((f: string) => (
                        <span key={f} className="bg-gray-800 text-gray-500 text-[9px] px-1 py-0.5 rounded">{f}</span>
                      ))}
                      {(info.fields_updated || []).length > 8 && (
                        <span className="text-gray-600 text-[9px]">+{info.fields_updated.length - 8} more</span>
                      )}
                    </div>
                    {info.url && (
                      <a href={info.url} target="_blank" rel="noopener noreferrer" className="text-blue-400 text-[10px] hover:underline mt-1 block">View source</a>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
    </div>
  );
}
