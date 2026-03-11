"use client";

import { useEffect, useState } from "react";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  getOrgProfile,
  updateOrgProfile,
  OrgProfile,
  ALL_FRAMEWORKS,
  ALL_DATA_CLASSES,
  ALL_VENDOR_RISK_MODELS,
  Nis2EntityType,
  RegulatoryFramework,
  DataClassificationLevel,
  VendorRiskModel,
  ApiError,
} from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const NIS2_TYPES: Nis2EntityType[] = ["ESSENTIAL", "IMPORTANT", "NONE"];

const FRAMEWORK_LABELS: Record<string, string> = {
  ISO27001: "ISO 27001",
  DORA:     "DORA",
  GDPR:     "GDPR",
  NIS2:     "NIS2",
  SOC2:     "SOC 2",
  PCI_DSS:  "PCI DSS",
  HIPAA:    "HIPAA",
  CCPA:     "CCPA",
};

const DATA_CLASS_LABELS: Record<string, string> = {
  PUBLIC:           "Public",
  INTERNAL:         "Internal",
  CONFIDENTIAL:     "Confidential",
  PERSONAL_DATA:    "Personal Data",
  SPECIAL_CATEGORY: "Special Category",
};

const EMPTY_PROFILE: OrgProfile = {
  organization_name:             "",
  industry:                      "",
  is_regulated_financial_entity: false,
  nis2_entity_type:              "NONE",
  regulatory_frameworks:         [],
  default_vendor_risk_model:     "THIRD_PARTY_RISK_V1",
  data_classification_levels:    ["PUBLIC", "INTERNAL", "CONFIDENTIAL"],
};

// ── Helper: collect Pydantic-style 422 validation errors ─────────────────────

function extractValidationErrors(err: unknown): string[] {
  if (err instanceof ApiError) {
    try {
      const parsed = JSON.parse(err.message);
      if (Array.isArray(parsed?.detail)) {
        return parsed.detail.map(
          (e: { loc: string[]; msg: string }) =>
            `${e.loc.slice(1).join(".")}: ${e.msg}`,
        );
      }
      if (typeof parsed?.detail === "string") return [parsed.detail];
    } catch {
      return [err.message];
    }
  }
  if (err instanceof Error) return [err.message];
  return ["An unexpected error occurred."];
}

// ── Multi-select checkbox group ───────────────────────────────────────────────

function CheckGroup<T extends string>({
  label,
  options,
  labels,
  selected,
  onChange,
  disabled,
}: {
  label:    string;
  options:  readonly T[];
  labels:   Record<string, string>;
  selected: T[];
  onChange: (v: T[]) => void;
  disabled: boolean;
}) {
  function toggle(opt: T) {
    const next = selected.includes(opt)
      ? selected.filter((x) => x !== opt)
      : [...selected, opt];
    onChange(next as T[]);
  }

  return (
    <div className="form-group">
      <label className="form-label">{label}</label>
      <div className="check-grid">
        {options.map((opt) => (
          <label
            key={opt}
            className={`check-chip ${selected.includes(opt) ? "check-chip--on" : ""} ${disabled ? "check-chip--disabled" : ""}`}
          >
            <input
              type="checkbox"
              checked={selected.includes(opt)}
              onChange={() => toggle(opt)}
              disabled={disabled}
              style={{ display: "none" }}
            />
            {labels[opt] ?? opt}
          </label>
        ))}
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

function CustomerProfileContent({ user }: { user: SessionUser }) {
  const isAdmin = user.role === "ADMIN";

  const [profile,  setProfile]  = useState<OrgProfile>(EMPTY_PROFILE);
  const [exists,   setExists]   = useState(false);       // false = 404, no profile yet
  const [loading,  setLoading]  = useState(true);
  const [saving,   setSaving]   = useState(false);
  const [success,  setSuccess]  = useState(false);
  const [errors,   setErrors]   = useState<string[]>([]);

  // ── Load ───────────────────────────────────────────────────────────────────

  useEffect(() => {
    getOrgProfile()
      .then((p) => { setProfile(p); setExists(true); })
      .catch((err) => {
        // 404 = not configured yet — show empty form
        if (err instanceof ApiError && err.status === 404) {
          setExists(false);
        } else {
          setErrors(extractValidationErrors(err));
        }
      })
      .finally(() => setLoading(false));
  }, []);

  // ── Save ───────────────────────────────────────────────────────────────────

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setErrors([]);
    setSuccess(false);

    // Client-side pre-validation
    const errs: string[] = [];
    if (!profile.organization_name.trim()) errs.push("Organization name is required.");
    if (!profile.industry.trim())          errs.push("Industry is required.");
    if (profile.regulatory_frameworks.length === 0)
      errs.push("Select at least one regulatory framework.");
    if (profile.data_classification_levels.length === 0)
      errs.push("Select at least one data classification level.");
    if (errs.length) { setErrors(errs); return; }

    setSaving(true);
    try {
      const saved = await updateOrgProfile(profile);
      setProfile(saved);
      setExists(true);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 4000);
    } catch (err) {
      setErrors(extractValidationErrors(err));
    } finally {
      setSaving(false);
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  function set<K extends keyof OrgProfile>(key: K, value: OrgProfile[K]) {
    setProfile((p) => ({ ...p, [key]: value }));
    setSuccess(false);
  }

  // ── Profile status (used for status indicator) ────────────────────────────

  type ProfileStatus = "not_configured" | "incomplete" | "ready";

  function getProfileStatus(): ProfileStatus {
    if (!exists) return "not_configured";
    const hasName       = profile.organization_name.trim().length > 0;
    const hasFrameworks = profile.regulatory_frameworks.length > 0;
    const hasDataClass  = profile.data_classification_levels.length > 0;
    if (hasName && hasFrameworks && hasDataClass) return "ready";
    return "incomplete";
  }

  const profileStatus = loading ? null : getProfileStatus();

  const STATUS_LABEL: Record<ProfileStatus, string> = {
    not_configured: "Not configured",
    incomplete:     "Missing required fields",
    ready:          "Ready for analysis",
  };

  const STATUS_CLASS: Record<ProfileStatus, string> = {
    not_configured: "badge badge--red",
    incomplete:     "badge badge--yellow",
    ready:          "badge badge--green",
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <div className="breadcrumb">Settings</div>
            <h1>Compliance Profile</h1>
            <p className="page-subtitle">
              <strong>Required for analysis.</strong>{" "}
              Every contract analysis run uses this profile to select applicable
              regulatory frameworks and match clauses to security requirements.
              Each run stores a frozen snapshot of the profile active at that time.
            </p>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.5rem" }}>
            {profileStatus && (
              <span className={STATUS_CLASS[profileStatus]}>
                {STATUS_LABEL[profileStatus]}
              </span>
            )}
            {!isAdmin && (
              <span className="badge badge--gray">Read-only — ADMIN access required to edit</span>
            )}
          </div>
        </div>

        {/* Not configured — blocking warning */}
        {profileStatus === "not_configured" && (
          <div className="warn-box">
            <strong>Compliance profile not configured.</strong>{" "}
            {isAdmin
              ? "Analysis cannot be started on any contract until this profile is saved. Fill in the form below."
              : "Contact your ADMIN to configure the compliance profile before analysis can run."}
          </div>
        )}

        {/* Incomplete — softer warning */}
        {profileStatus === "incomplete" && (
          <div className="warn-box">
            <strong>Profile is incomplete.</strong>{" "}
            Organisation name, at least one regulatory framework, and at least one
            data classification level are required before analysis can run.
          </div>
        )}

        {loading && <div className="loading">Loading profile…</div>}

        {!loading && (
          <form onSubmit={handleSave} className="profile-form">

            {/* Success banner */}
            {success && (
              <div className="success-box">
                Compliance profile saved.{" "}
                {profileStatus === "ready"
                  ? "Profile is ready for analysis."
                  : "Some required fields are still missing — analysis may not run until they are filled in."}
              </div>
            )}

            {/* Validation errors */}
            {errors.length > 0 && (
              <div className="error-box">
                {errors.map((e, i) => <div key={i}>{e}</div>)}
              </div>
            )}

            {/* ── Section: Organisation ─────────────────────────────────── */}
            <div className="profile-section">
              <h2 className="profile-section-title">Organisation</h2>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label" htmlFor="org-name">
                    Organisation name <span className="req">*</span>
                  </label>
                  <input
                    id="org-name"
                    className="form-input"
                    type="text"
                    value={profile.organization_name}
                    onChange={(e) => set("organization_name", e.target.value)}
                    disabled={!isAdmin}
                    placeholder="e.g. Acme Financial GmbH"
                  />
                </div>

                <div className="form-group">
                  <label className="form-label" htmlFor="industry">
                    Industry <span className="req">*</span>
                  </label>
                  <input
                    id="industry"
                    className="form-input"
                    type="text"
                    value={profile.industry}
                    onChange={(e) => set("industry", e.target.value)}
                    disabled={!isAdmin}
                    placeholder="e.g. Financial Services"
                  />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label form-label--check">
                  <input
                    type="checkbox"
                    checked={profile.is_regulated_financial_entity}
                    onChange={(e) => set("is_regulated_financial_entity", e.target.checked)}
                    disabled={!isAdmin}
                  />
                  Regulated financial entity (e.g. subject to DORA / BaFin oversight)
                </label>
              </div>
            </div>

            {/* ── Section: NIS2 classification ─────────────────────────── */}
            <div className="profile-section">
              <h2 className="profile-section-title">NIS2 Classification</h2>

              <div className="form-group">
                <label className="form-label" htmlFor="nis2">NIS2 entity type</label>
                <select
                  id="nis2"
                  className="form-select"
                  value={profile.nis2_entity_type}
                  onChange={(e) => set("nis2_entity_type", e.target.value as Nis2EntityType)}
                  disabled={!isAdmin}
                >
                  {NIS2_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* ── Section: Regulatory frameworks ───────────────────────── */}
            <div className="profile-section">
              <h2 className="profile-section-title">Regulatory Frameworks</h2>
              <p className="profile-section-desc">
                Select all frameworks that apply. Analyses will reference these
                during clause-level compliance checks.
              </p>

              <CheckGroup
                label="Active frameworks *"
                options={ALL_FRAMEWORKS}
                labels={FRAMEWORK_LABELS}
                selected={profile.regulatory_frameworks as RegulatoryFramework[]}
                onChange={(v) => set("regulatory_frameworks", v)}
                disabled={!isAdmin}
              />
            </div>

            {/* ── Section: Risk model ───────────────────────────────────── */}
            <div className="profile-section">
              <h2 className="profile-section-title">Risk Configuration</h2>

              <div className="form-group">
                <label className="form-label" htmlFor="vendor-model">
                  Default vendor risk model
                </label>
                <select
                  id="vendor-model"
                  className="form-select"
                  value={profile.default_vendor_risk_model}
                  onChange={(e) => set("default_vendor_risk_model", e.target.value as VendorRiskModel)}
                  disabled={!isAdmin}
                >
                  {ALL_VENDOR_RISK_MODELS.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* ── Section: Data classification ─────────────────────────── */}
            <div className="profile-section">
              <h2 className="profile-section-title">Data Classification</h2>
              <p className="profile-section-desc">
                Define which data sensitivity levels are recognised in your organisation.
              </p>

              <CheckGroup
                label="Active classification levels *"
                options={ALL_DATA_CLASSES}
                labels={DATA_CLASS_LABELS}
                selected={profile.data_classification_levels as DataClassificationLevel[]}
                onChange={(v) => set("data_classification_levels", v)}
                disabled={!isAdmin}
              />
            </div>

            {/* ── Save button ───────────────────────────────────────────── */}
            {isAdmin && (
              <div className="form-actions">
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={saving}
                >
                  {saving ? "Saving…" : "Save compliance profile"}
                </button>
                <span className="form-hint">
                  Changes take effect on the next analysis run.
                </span>
              </div>
            )}
          </form>
        )}
      </main>
    </div>
  );
}

export default function CustomerProfilePage() {
  return (
    <AuthGuard>
      {(user) => <CustomerProfileContent user={user} />}
    </AuthGuard>
  );
}
