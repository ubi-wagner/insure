"use client";

import { useEffect, useState, useCallback } from "react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

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
  policies: { id: number; coverage_type: string; carrier: string | null; premium: number | null; tiv: number | null; deductible: string | null; expiration: string | null; is_active: number }[];
  engagements: { id: number; type: string; channel: string; status: string; subject: string | null; body: string | null; style: string | null; created_at: string }[];
  assets: { id: number; doc_type: string; extracted_text: string; source: string | null; filename: string | null }[];
  contacts: { id: number; name: string; title: string; email: string | null; phone: string | null; is_primary: number; source: string | null; source_url: string | null }[];
  children: { id: number; name: string; address: string; pipeline_stage: string }[];
  enrichment_sources: Record<string, { source: string; timestamp: string; fields_updated: string[]; url: string | null }>;
  readiness: Record<string, { ready: boolean; checks: Record<string, { done: boolean; label: string }> }>;
}

interface EntityDetailModalProps {
  entityId: number;
  onClose: () => void;
  isActive: boolean;
  onFlyTo?: (lat: number, lng: number) => void;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const HEAT_STYLES: Record<string, string> = {
  hot: "bg-red-600",
  warm: "bg-orange-600",
  cool: "bg-blue-600",
  cold: "bg-gray-600",
  none: "bg-gray-600",
};

const STAGE_COLORS: Record<string, string> = {
  TARGET: "bg-gray-700 text-gray-200",
  LEAD: "bg-cyan-900 text-cyan-200",
  OPPORTUNITY: "bg-amber-900 text-amber-200",
  CUSTOMER: "bg-green-900 text-green-200",
  ARCHIVED: "bg-red-900 text-red-200",
};

const STAGES = ["TARGET", "LEAD", "OPPORTUNITY", "CUSTOMER", "ARCHIVED"];

type TabName = "overview" | "contacts" | "sources";

const SOURCE_BADGE_COLORS: Record<string, string> = {
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

/** Fields rendered in dedicated sections -- excluded from the catch-all Intelligence grid. */
const KNOWN_FIELDS = new Set([
  "emails", "osm_tags", "osm_id",
  "construction_class", "iso_class", "dor_construction_class",
  "building_material", "building_type", "year_built", "stories",
  "units_estimate", "footprint_sqft", "tiv_estimate", "height_m",
  "flood_zone", "flood_zone_label", "flood_zone_subtype", "flood_risk",
  "flood_sfha", "flood_base_elev_ft", "flood_score_impact", "fema_map_url",
  "pa_owner", "pa_assessed_value", "pa_year_built", "pa_building_sqft",
  "pa_parcel_id", "pa_lot_sqft", "pa_acres", "pa_use_code",
  "pa_last_sale_date", "pa_last_sale_price", "pa_county", "pa_lookup_url",
  "sunbiz_search_url", "sunbiz_search_name", "sunbiz_corp_name",
  "sunbiz_doc_number", "sunbiz_detail_url", "sunbiz_filing_status",
  "sunbiz_registered_agent", "property_manager", "sunbiz_filing_date",
  "sunbiz_principal_address",
  "dbpr_condo_name", "dbpr_project_number", "dbpr_file_number",
  "dbpr_official_units", "dbpr_status", "dbpr_managing_entity",
  "dbpr_managing_entity_number", "dbpr_managing_entity_address",
  "dbpr_operating_revenue", "dbpr_operating_expenses", "dbpr_reserve_revenue",
  "dbpr_operating_fund_balance", "dbpr_reserve_fund_balance",
  "dbpr_fiscal_year_end", "dbpr_search_url", "dbpr_cam_name",
  "dbpr_cam_license", "dbpr_cam_status", "dbpr_cam_address",
  "dbpr_management_company",
  "cam_license_number", "cam_license_name", "cam_license_address",
  "cam_license_expiration", "cam_license_active", "cam_license_found",
  "cam_license_warning",
  "citizens_likelihood", "citizens_county_penetration",
  "citizens_estimated_premium", "citizens_premium_display",
  "citizens_risk_factors", "on_citizens", "citizens_swap_opportunity",
  "dor_parcel_id", "dor_owner", "dor_owner_address", "dor_market_value",
  "dor_land_value", "dor_use_code", "dor_use_description",
  "dor_year_built", "dor_effective_year_built", "dor_living_sqft",
  "dor_num_buildings", "dor_num_units", "dor_last_sale_price",
  "dor_last_sale_year", "dor_last_sale_date", "dor_special_features_value",
  "dor_land_sqft",
  "has_user_intel", "user_doc_types", "_field_sources",
]);

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function fmt(val: number | null | undefined): string {
  if (val === null || val === undefined || isNaN(val)) return "\u2014";
  return "$" + val.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/** Safe number display for JSONB unknown values */
function safeNum(val: unknown): string {
  if (val === null || val === undefined) return "\u2014";
  const n = Number(val);
  return isNaN(n) ? String(val) : n.toLocaleString();
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

/** Single key-value row used inside DataSection cards. Returns null when value is empty. */
function DataRow({ label, value, href }: { label: string; value: unknown; href?: string }) {
  if (value === null || value === undefined || value === "" || value === 0) return null;
  return (
    <div className="flex justify-between py-1 border-b border-gray-800/50 last:border-0">
      <span className="text-gray-500 text-xs shrink-0">{label}</span>
      {href ? (
        <a href={String(href)} target="_blank" rel="noopener noreferrer"
          className="text-blue-400 text-xs hover:underline truncate ml-2 max-w-[220px]">
          {String(value)}
        </a>
      ) : (
        <span className="text-white text-xs font-medium truncate ml-2 max-w-[220px]">{String(value)}</span>
      )}
    </div>
  );
}

/**
 * Collapsible section wrapper. Automatically hides itself when all children
 * are null / false (i.e. every DataRow returned null because its value was empty).
 */
function DataSection({ title, children }: { title: string; children?: React.ReactNode }) {
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

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function EntityDetailModal({
  entityId,
  onClose,
  isActive,
  onFlyTo,
}: EntityDetailModalProps) {
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabName>("overview");
  const [stageChanging, setStageChanging] = useState(false);
  const [showAddContact, setShowAddContact] = useState(false);
  const [contactForm, setContactForm] = useState({ name: "", title: "", email: "", phone: "", is_primary: 0 });
  const [savingContact, setSavingContact] = useState(false);

  /* ---- Fetch entity ---- */
  const fetchEntity = useCallback(() => {
    setError(null);
    setLead(null);
    setTab("overview");
    fetch(`/api/proxy/leads/${entityId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(`${r.status}`)))
      .then(setLead)
      .catch((e) => setError(String(e)));
  }, [entityId]);

  useEffect(() => {
    fetchEntity();
  }, [fetchEntity]);

  /* ---- Reload helper ---- */
  async function reload() {
    try {
      const r = await fetch(`/api/proxy/leads/${entityId}`);
      if (r.ok) setLead(await r.json());
    } catch { /* swallow */ }
  }

  /* ---- Stage change ---- */
  async function changeStage(stage: string) {
    setStageChanging(true);
    try {
      const res = await fetch(`/api/proxy/leads/${entityId}/stage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage, force: true }),
      });
      if (res.ok) await reload();
      else {
        setError("Stage change failed (" + res.status + ")");
      }
    } catch (err) {
      setError("Failed to change stage");
    }
    setStageChanging(false);
  }

  /* ---- Add contact ---- */
  async function handleAddContact() {
    if (!contactForm.name.trim()) return;
    setSavingContact(true);
    try {
      const res = await fetch(`/api/proxy/leads/${entityId}/contacts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(contactForm),
      });
      if (res.ok) {
        await reload();
        setContactForm({ name: "", title: "", email: "", phone: "", is_primary: 0 });
        setShowAddContact(false);
      }
    } catch (err) {
      setError("Failed to add contact");
    }
    setSavingContact(false);
  }

  /* ---- Close on Escape ---- */
  useEffect(() => {
    if (!isActive) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isActive, onClose]);

  /* ---- Derived ---- */
  const chars = lead?.characteristics || {};

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */

  return (
    <div
      className={`fixed inset-y-0 right-0 w-full sm:w-[480px] ${
        isActive ? "z-50" : "z-40 opacity-95"
      } flex flex-col bg-gray-950 border-l border-gray-800 shadow-2xl shadow-black/60 transition-all duration-200`}
    >
      {/* ---- Header ---- */}
      <div className="bg-gray-900 border-b border-gray-800 px-4 py-3 shrink-0">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-2.5 right-3 text-gray-500 hover:text-white text-lg w-6 h-6 flex items-center justify-center rounded hover:bg-gray-800 transition-colors"
          aria-label="Close panel"
        >
          &times;
        </button>

        {/* Loading / Error states */}
        {!lead && !error && (
          <p className="text-gray-600 text-xs">Loading entity #{entityId}...</p>
        )}
        {error && (
          <p className="text-red-400 text-xs">Failed to load: {error}</p>
        )}

        {lead && (
          <>
            {/* Name + badges */}
            <div className="flex items-center gap-2 flex-wrap pr-8 mb-1">
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full text-white shrink-0 ${HEAT_STYLES[lead.heat_score] || HEAT_STYLES.none}`}>
                {lead.heat_score}
              </span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full shrink-0 ${STAGE_COLORS[lead.pipeline_stage] || STAGE_COLORS.TARGET}`}>
                {lead.pipeline_stage}
              </span>
              <h2 className="text-sm font-bold text-white truncate">{lead.name}</h2>
            </div>

            {/* Address + county */}
            <div className="flex items-center gap-3 text-[11px] text-gray-500">
              <span className="truncate">{lead.address}</span>
              {lead.county && <span className="shrink-0">{lead.county}</span>}
              {lead.latitude != null && lead.longitude != null && lead.latitude !== 0 && onFlyTo && (
                <button
                  onClick={() => onFlyTo(lead.latitude!, lead.longitude!)}
                  className="text-blue-400 hover:underline shrink-0"
                >
                  Fly to
                </button>
              )}
            </div>

            {/* Stage selector + metrics */}
            <div className="flex items-center gap-3 mt-1.5 flex-wrap">
              <span className="text-xs text-gray-500">
                TIV: <span className="text-white font-medium">{fmt(lead.tiv_parsed ?? (typeof chars.tiv_estimate === "number" ? chars.tiv_estimate : null))}</span>
              </span>
              {chars.dor_market_value != null && (
                <span className="text-xs text-gray-500">
                  Mkt: <span className="text-white font-medium">{fmt(Number(chars.dor_market_value))}</span>
                </span>
              )}
              <div className="ml-auto">
                <select
                  value={lead.pipeline_stage}
                  onChange={(e) => changeStage(e.target.value)}
                  disabled={stageChanging}
                  className="bg-gray-800 border border-gray-700 text-white text-[11px] rounded px-1.5 py-0.5"
                >
                  {STAGES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </div>
          </>
        )}
      </div>

      {/* ---- Tabs ---- */}
      {lead && (
        <div className="flex border-b border-gray-800 shrink-0">
          {([
            { key: "overview" as TabName, label: "Overview" },
            { key: "contacts" as TabName, label: `Contacts (${(lead.contacts || []).length})` },
            { key: "sources" as TabName, label: `Sources (${Object.keys(lead.enrichment_sources || {}).length})` },
          ]).map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 text-center py-2 text-xs font-medium border-b-2 transition-colors ${
                tab === t.key
                  ? "border-blue-500 text-white"
                  : "border-transparent text-gray-500 hover:text-gray-300"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      {/* ---- Scrollable body ---- */}
      <div className="flex-1 overflow-y-auto px-4 py-3">

        {/* ============================================================ */}
        {/*  OVERVIEW TAB                                                 */}
        {/* ============================================================ */}
        {lead && tab === "overview" && (
          <>
            {/* Building Profile */}
            <DataSection title="Building Profile">
              <DataRow label="Construction" value={chars.construction_class ?? chars.dor_construction_class} />
              <DataRow label="Stories" value={chars.stories} />
              <DataRow label="Building Type" value={chars.building_type} />
              <DataRow label="Year Built" value={chars.year_built ?? chars.dor_year_built} />
              <DataRow label="Units" value={chars.units_estimate ?? chars.dor_num_units} />
              <DataRow label="Living Area" value={chars.dor_living_sqft ? `${safeNum(chars.dor_living_sqft)} sqft` : null} />
              <DataRow label="Footprint" value={chars.footprint_sqft ? `${safeNum(chars.footprint_sqft)} sqft` : null} />
              <DataRow label="Est. TIV" value={chars.tiv_estimate ? `$${safeNum(chars.tiv_estimate)}` : null} />
            </DataSection>

            {/* Flood & Risk */}
            <DataSection title="Flood & Risk">
              <DataRow label="FEMA Zone" value={chars.flood_zone_label || chars.flood_zone} />
              <DataRow label="SFHA" value={
                chars.flood_sfha === true ? "Yes \u2014 flood insurance required" :
                chars.flood_sfha === false ? "No" : null
              } />
              <DataRow label="Risk Level" value={chars.flood_risk} />
              <DataRow label="Base Elevation" value={chars.flood_base_elev_ft ? `${chars.flood_base_elev_ft} ft` : null} />
              <DataRow label="FEMA Map" value={chars.fema_map_url ? "View on FEMA MSC" : null} href={typeof chars.fema_map_url === "string" ? chars.fema_map_url : undefined} />
            </DataSection>

            {/* Property Appraiser */}
            <DataSection title="Property Appraiser">
              <DataRow label="Lookup" value={chars.pa_lookup_url ? "View on PA Site" : null} href={typeof chars.pa_lookup_url === "string" ? chars.pa_lookup_url : undefined} />
              <DataRow label="Owner" value={chars.pa_owner} />
              <DataRow label="Assessed Value" value={chars.pa_assessed_value ? `$${safeNum(chars.pa_assessed_value)}` : null} />
              <DataRow label="Parcel ID" value={chars.pa_parcel_id} />
              <DataRow label="Year Built (PA)" value={chars.pa_year_built} />
              <DataRow label="Building Sqft" value={chars.pa_building_sqft ? safeNum(chars.pa_building_sqft) : null} />
            </DataSection>

            {/* DOR Tax Roll */}
            <DataSection title="DOR Tax Roll">
              <DataRow label="Owner" value={chars.dor_owner} />
              <DataRow label="Owner Address" value={chars.dor_owner_address} />
              <DataRow label="Market Value" value={chars.dor_market_value ? `$${safeNum(chars.dor_market_value)}` : null} />
              <DataRow label="Land Value" value={chars.dor_land_value ? `$${safeNum(chars.dor_land_value)}` : null} />
              <DataRow label="Use Type" value={chars.dor_use_description} />
              <DataRow label="Units" value={chars.dor_num_units} />
              <DataRow label="Buildings" value={chars.dor_num_buildings} />
              <DataRow label="Living Area" value={chars.dor_living_sqft ? `${safeNum(chars.dor_living_sqft)} sqft` : null} />
              <DataRow label="Land Sqft" value={chars.dor_land_sqft ? `${safeNum(chars.dor_land_sqft)} sqft` : null} />
              <DataRow label="Last Sale" value={
                chars.dor_last_sale_price
                  ? `$${safeNum(chars.dor_last_sale_price)}${chars.dor_last_sale_date ? ` (${String(chars.dor_last_sale_date)})` : ""}`
                  : null
              } />
              <DataRow label="Parcel ID" value={chars.dor_parcel_id} />
            </DataSection>

            {/* DBPR Condo */}
            <DataSection title="DBPR Condo Registry">
              <DataRow label="Condo Name" value={chars.dbpr_condo_name} />
              <DataRow label="Managing Entity" value={chars.dbpr_managing_entity} />
              <DataRow label="Project #" value={chars.dbpr_project_number} />
              <DataRow label="Status" value={chars.dbpr_status} />
              <DataRow label="Official Units" value={chars.dbpr_official_units} />
              <DataRow label="Operating Revenue" value={chars.dbpr_operating_revenue} />
              <DataRow label="Reserve Fund" value={chars.dbpr_reserve_fund_balance} />
            </DataSection>

            {/* CAM License */}
            <DataSection title="CAM License">
              <DataRow label="License #" value={chars.cam_license_number} />
              <DataRow label="Name" value={chars.cam_license_name} />
              <DataRow label="Expires" value={
                chars.cam_license_expiration
                  ? `${String(chars.cam_license_expiration)} ${chars.cam_license_active ? "(active)" : "(EXPIRED)"}`
                  : null
              } />
              <DataRow label="Active" value={
                chars.cam_license_active === true ? "Yes" :
                chars.cam_license_active === false ? "EXPIRED" : null
              } />
              {!!chars.cam_license_warning && (
                <div className="py-1">
                  <span className="text-amber-400 text-xs">{String(chars.cam_license_warning)}</span>
                </div>
              )}
            </DataSection>

            {/* Sunbiz */}
            <DataSection title="Association (Sunbiz)">
              <DataRow label="Corp Name" value={chars.sunbiz_corp_name} />
              <DataRow label="Filing Status" value={chars.sunbiz_filing_status} />
              <DataRow label="Registered Agent" value={chars.property_manager} />
              <DataRow label="Doc #" value={chars.sunbiz_doc_number} />
              <DataRow
                label="Lookup"
                value={(chars.sunbiz_detail_url || chars.sunbiz_search_url) ? "View on Sunbiz" : null}
                href={String(chars.sunbiz_detail_url || chars.sunbiz_search_url || "")}
              />
            </DataSection>

            {/* Citizens Insurance */}
            <DataSection title="Citizens Insurance">
              <DataRow label="Likelihood" value={chars.citizens_likelihood} />
              <DataRow label="Swap Opportunity" value={chars.citizens_swap_opportunity} />
              <DataRow label="Est. Premium" value={chars.citizens_premium_display || (chars.citizens_estimated_premium ? fmt(Number(chars.citizens_estimated_premium)) : null)} />
              <DataRow label="On Citizens" value={
                chars.on_citizens === true ? "Yes" :
                chars.on_citizens === false ? "No" : null
              } />
              <DataRow label="Risk Factors" value={
                chars.citizens_risk_factors
                  ? (Array.isArray(chars.citizens_risk_factors)
                      ? (Array.isArray(chars.citizens_risk_factors) ? chars.citizens_risk_factors.map(String).join(", ") : String(chars.citizens_risk_factors))
                      : String(chars.citizens_risk_factors))
                  : null
              } />
            </DataSection>

            {/* Insurance Intelligence -- remaining characteristics not shown above */}
            {(() => {
              const extras = Object.entries(chars).filter(([k]) => !KNOWN_FIELDS.has(k));
              if (extras.length === 0) return null;
              return (
                <DataSection title="Insurance Intelligence">
                  {extras.map(([key, val]) => (
                    <DataRow
                      key={key}
                      label={key.replace(/_/g, " ")}
                      value={
                        Array.isArray(val)
                          ? val.map(String).join(", ")
                          : (val ?? null)
                      }
                    />
                  ))}
                </DataSection>
              );
            })()}

            {/* Policies summary (compact) */}
            {(lead.policies || []).length > 0 && (
              <DataSection title={`Policies (${(lead.policies || []).length})`}>
                {lead.policies.map((p) => (
                  <div key={p.id} className="py-1.5 border-b border-gray-800/50 last:border-0">
                    <div className="flex justify-between">
                      <span className="text-xs text-blue-400">{p.coverage_type}</span>
                      <span className={`text-[10px] ${p.is_active ? "text-green-400" : "text-gray-600"}`}>
                        {p.is_active ? "ACTIVE" : "expired"}
                      </span>
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
            {lead.latitude != null && lead.latitude !== 0 && (
              <DataSection title="Location">
                <DataRow label="Coordinates" value={lead.latitude && lead.longitude ? `${lead.latitude.toFixed(5)}, ${lead.longitude.toFixed(5)}` : null} />
              </DataSection>
            )}
          </>
        )}

        {/* ============================================================ */}
        {/*  CONTACTS TAB                                                 */}
        {/* ============================================================ */}
        {lead && tab === "contacts" && (
          <div className="space-y-2">
            {(lead.contacts || []).length === 0 && !showAddContact && (
              <p className="text-gray-600 text-xs">No contacts on record.</p>
            )}

            {lead.contacts.map((c) => (
              <div key={c.id} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <div className="flex items-center gap-2">
                  <span className="text-white text-xs font-medium">{c.name}</span>
                  {!!c.is_primary && (
                    <span className="bg-green-900 text-green-300 text-[9px] px-1 py-0.5 rounded">PRIMARY</span>
                  )}
                  {c.source && (
                    <span className="bg-gray-800 text-gray-500 text-[9px] px-1 py-0.5 rounded">{c.source}</span>
                  )}
                </div>
                {c.title && <p className="text-gray-500 text-[10px] mt-0.5">{c.title}</p>}
                <div className="flex gap-3 mt-1 text-[11px]">
                  {c.email && (
                    <a href={`mailto:${c.email}`} className="text-blue-400 hover:underline">{c.email}</a>
                  )}
                  {c.phone && <span className="text-gray-400">{c.phone}</span>}
                </div>
              </div>
            ))}

            {/* Add contact form */}
            {showAddContact ? (
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 space-y-2">
                <p className="text-xs font-semibold text-gray-300 mb-1">Add Contact</p>
                <input
                  type="text"
                  placeholder="Name *"
                  value={contactForm.name}
                  onChange={(e) => setContactForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1.5 placeholder-gray-600 focus:outline-none focus:border-blue-600"
                />
                <input
                  type="text"
                  placeholder="Title"
                  value={contactForm.title}
                  onChange={(e) => setContactForm((f) => ({ ...f, title: e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1.5 placeholder-gray-600 focus:outline-none focus:border-blue-600"
                />
                <input
                  type="email"
                  placeholder="Email"
                  value={contactForm.email}
                  onChange={(e) => setContactForm((f) => ({ ...f, email: e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1.5 placeholder-gray-600 focus:outline-none focus:border-blue-600"
                />
                <input
                  type="tel"
                  placeholder="Phone"
                  value={contactForm.phone}
                  onChange={(e) => setContactForm((f) => ({ ...f, phone: e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1.5 placeholder-gray-600 focus:outline-none focus:border-blue-600"
                />
                <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={contactForm.is_primary === 1}
                    onChange={(e) => setContactForm((f) => ({ ...f, is_primary: e.target.checked ? 1 : 0 }))}
                    className="rounded bg-gray-800 border-gray-700"
                  />
                  Primary contact
                </label>
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={handleAddContact}
                    disabled={savingContact || !contactForm.name.trim()}
                    className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs px-3 py-1 rounded font-medium transition-colors"
                  >
                    {savingContact ? "Saving..." : "Save"}
                  </button>
                  <button
                    onClick={() => {
                      setShowAddContact(false);
                      setContactForm({ name: "", title: "", email: "", phone: "", is_primary: 0 });
                    }}
                    className="text-gray-500 hover:text-gray-300 text-xs px-3 py-1 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setShowAddContact(true)}
                className="w-full bg-gray-900 border border-dashed border-gray-700 hover:border-gray-500 text-gray-500 hover:text-gray-300 text-xs py-2 rounded-lg transition-colors"
              >
                + Add Contact
              </button>
            )}
          </div>
        )}

        {/* ============================================================ */}
        {/*  SOURCES TAB                                                  */}
        {/* ============================================================ */}
        {lead && tab === "sources" && (
          <div className="space-y-2">
            {Object.keys(lead.enrichment_sources || {}).length === 0 ? (
              <p className="text-gray-600 text-xs">No enrichment sources yet.</p>
            ) : (
              Object.entries(lead.enrichment_sources).map(([src, info]) => (
                <div key={src} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${SOURCE_BADGE_COLORS[src] || "bg-gray-800 text-gray-400"}`}>
                      {src}
                    </span>
                    <span className="text-gray-600 text-[10px]">
                      {info.timestamp
                        ? new Date(info.timestamp).toLocaleDateString("en-US", {
                            month: "short",
                            day: "numeric",
                            year: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : ""}
                    </span>
                  </div>
                  {(info.fields_updated || []).length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {info.fields_updated.slice(0, 12).map((f: string) => (
                        <span key={f} className="bg-gray-800 text-gray-500 text-[9px] px-1 py-0.5 rounded">
                          {f.replace(/_/g, " ")}
                        </span>
                      ))}
                      {info.fields_updated.length > 12 && (
                        <span className="text-gray-600 text-[9px]">+{info.fields_updated.length - 12} more</span>
                      )}
                    </div>
                  )}
                  {info.url && (
                    <a href={info.url} target="_blank" rel="noopener noreferrer"
                      className="text-blue-400 text-[10px] hover:underline mt-1.5 block">
                      Source URL
                    </a>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
