"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  getVersionNegotiation,
  updateFinding,
  NegotiationOut,
  FindingStatus,
} from "@/lib/api";

function priorityClass(priority: string) {
  const p = priority?.toLowerCase();
  if (p === "high")   return "card-priority card-priority--high";
  if (p === "medium") return "card-priority card-priority--medium";
  return "card-priority card-priority--low";
}

function priorityBadge(priority: string) {
  const p = priority?.toLowerCase();
  if (p === "high")   return "badge badge--red";
  if (p === "medium") return "badge badge--yellow";
  return "badge badge--green";
}

// Reviewer decision options mapped to FindingStatus
const REVIEWER_DECISIONS: { label: string; value: FindingStatus; description: string }[] = [
  { label: "Accept risk",                  value: "accepted_risk",  description: "Risk accepted — no contract change needed" },
  { label: "Request contract change",      value: "in_negotiation", description: "Request vendor to amend this clause" },
  { label: "Escalate to legal",            value: "in_review",      description: "Flag for legal team review" },
  { label: "Customer responsibility",      value: "not_applicable", description: "Responsibility accepted by customer side" },
  { label: "Not applicable",               value: "not_applicable", description: "This finding does not apply to our context" },
  { label: "Needs clarification",          value: "deferred",       description: "Defer pending further information" },
  { label: "Resolved",                     value: "resolved",       description: "Issue has been resolved" },
];

interface RegulatoryBasisItem {
  sr_id?:      string;
  framework?:  string;
  article?:    string;
  obligation?: string;
  penalty?:    string;
  match_type?: string;
  confidence?: number;
  regulation?: string;
}

interface ClauseExcerpt {
  clause_id?: string;
  page?:      number;
  text?:      string;
}

interface NegItem {
  negotiation_id?:          string;
  action_id?:               string;
  topic?:                   string | string[];
  priority?:                string;
  affected_clauses?:        string[];
  problem_summary?:         string;
  regulatory_basis?:        string | RegulatoryBasisItem[];
  recommended_clause_text?: string;
  negotiation_argument?:    string;
  fallback_option?:         string;
  owner_role?:              string;
  estimated_effort?:        string;
  expected_risk_reduction?: string;
  current_clause_excerpts?: (string | ClauseExcerpt)[];
}

// Reviewer decision sub-component
function ReviewerDecisionPanel({
  item,
  contractId,
  versionId,
  isViewer,
}: {
  item:       NegItem;
  contractId: string;
  versionId:  number;
  isViewer:   boolean;
}) {
  const findingKey = item.action_id ?? item.negotiation_id;
  const [decision,  setDecision]  = useState<FindingStatus | "">("");
  const [notes,     setNotes]     = useState("");
  const [saving,    setSaving]    = useState(false);
  const [saved,     setSaved]     = useState(false);
  const [saveError, setSaveError] = useState("");

  if (!findingKey || isViewer) return null;

  async function handleRecord() {
    if (!decision || !findingKey) return;
    setSaving(true);
    setSaveError("");
    try {
      await updateFinding(contractId, versionId, findingKey, {
        status:             decision,
        disposition_reason: notes || undefined,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Failed to record decision.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="neg-section" style={{ borderTop: "2px solid var(--color-border)", paddingTop: "0.75rem", marginTop: "0.75rem" }}>
      <h4>Reviewer decision</h4>
      {saved && (
        <div className="success-box" style={{ marginBottom: "0.5rem" }}>Decision recorded.</div>
      )}
      {saveError && (
        <div className="error-box" style={{ marginBottom: "0.5rem" }}>{saveError}</div>
      )}
      <div className="form-group" style={{ marginBottom: "0.5rem" }}>
        <select
          className="filter-select"
          value={decision}
          onChange={(e) => setDecision(e.target.value as FindingStatus)}
          disabled={saving}
          style={{ width: "100%" }}
        >
          <option value="">— Select decision —</option>
          {REVIEWER_DECISIONS.map((d) => (
            <option key={`${d.label}-${d.value}`} value={d.value}>{d.label}</option>
          ))}
        </select>
        {decision && (
          <p style={{ fontSize: "0.8rem", color: "var(--color-muted)", marginTop: "0.25rem" }}>
            {REVIEWER_DECISIONS.find((d) => d.value === decision)?.description}
          </p>
        )}
      </div>
      <div className="form-group" style={{ marginBottom: "0.5rem" }}>
        <textarea
          className="workflow-notes"
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          disabled={saving}
          placeholder="Internal notes (optional)…"
        />
      </div>
      <button
        className="btn btn-sm btn-primary"
        onClick={handleRecord}
        disabled={!decision || saving}
      >
        {saving ? "Saving…" : "Record decision"}
      </button>
    </div>
  );
}

function NegCard({
  item,
  contractId,
  versionId,
  isViewer,
}: {
  item:       NegItem;
  contractId: string;
  versionId:  number;
  isViewer:   boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`neg-card ${priorityClass(item.priority ?? "")}`}>
      <div className="neg-card-header" onClick={() => setExpanded((x) => !x)}>
        <div className="neg-card-meta">
          <span className="mono neg-id">{item.negotiation_id ?? item.action_id}</span>
          <span className={priorityBadge(item.priority ?? "")}>{item.priority}</span>
          {item.owner_role && <span className="tag">{item.owner_role}</span>}
        </div>
        <h3 className="neg-topic">{Array.isArray(item.topic) ? item.topic.join(", ") : (item.topic ?? "—")}</h3>
        <p className="neg-summary">{item.problem_summary ?? ""}</p>
        <button className="btn btn-sm btn-ghost expand-btn">
          {expanded ? "▲ Less" : "▼ More"}
        </button>
      </div>

      {expanded && (
        <div className="neg-card-body">
          {/* Regulatory basis */}
          {item.regulatory_basis && (
            <div className="neg-section">
              <h4>Regulatory basis</h4>
              {Array.isArray(item.regulatory_basis)
                ? item.regulatory_basis.map((rb, i) => (
                    <div key={i} className="reg-basis-item">
                      {typeof rb === "object" ? (
                        <>
                          <p><strong>{rb.framework} — {rb.article}</strong></p>
                          {rb.obligation && <p>{rb.obligation}</p>}
                          {rb.penalty && <p className="penalty-note"><em>Penalty: {rb.penalty}</em></p>}
                        </>
                      ) : <p>{rb}</p>}
                    </div>
                  ))
                : <p>{item.regulatory_basis}</p>}
            </div>
          )}

          {/* Current clause excerpts */}
          {item.current_clause_excerpts && item.current_clause_excerpts.length > 0 && (
            <div className="neg-section">
              <h4>Current clause(s)</h4>
              {item.current_clause_excerpts.map((ex, i) => (
                <blockquote key={i} className="clause-excerpt">
                  {typeof ex === "object" ? (
                    <>
                      {ex.clause_id && <span className="clause-id">{ex.clause_id}{ex.page ? ` (p. ${ex.page})` : ""}: </span>}
                      {ex.text}
                    </>
                  ) : ex}
                </blockquote>
              ))}
            </div>
          )}

          {/* Proposed wording */}
          {item.recommended_clause_text && (
            <div className="neg-section">
              <h4>Proposed clause wording</h4>
              <blockquote className="clause-recommended">{item.recommended_clause_text}</blockquote>
            </div>
          )}

          {/* Negotiation argument */}
          {item.negotiation_argument && (
            <div className="neg-section">
              <h4>Negotiation argument</h4>
              <p>{item.negotiation_argument}</p>
            </div>
          )}

          {/* Fallback option */}
          {item.fallback_option && (
            <div className="neg-section">
              <h4>Fallback option</h4>
              <p className="text-muted">{item.fallback_option}</p>
            </div>
          )}

          {/* Metadata */}
          <div className="neg-meta-row">
            {item.estimated_effort && <span className="meta-chip">Effort: {item.estimated_effort}</span>}
            {item.expected_risk_reduction && <span className="meta-chip">Risk reduction: {item.expected_risk_reduction}</span>}
            {item.affected_clauses && item.affected_clauses.length > 0 && (
              <span className="meta-chip">Clauses: {item.affected_clauses.join(", ")}</span>
            )}
          </div>

          {/* Reviewer decision */}
          <ReviewerDecisionPanel
            item={item}
            contractId={contractId}
            versionId={versionId}
            isViewer={isViewer}
          />
        </div>
      )}
    </div>
  );
}

function VersionNegotiationContent({
  user,
  contractId,
  versionId,
}: {
  user:       SessionUser;
  contractId: string;
  versionId:  number;
}) {
  const [data,    setData]    = useState<NegotiationOut | null>(null);
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(true);
  const [filter,  setFilter]  = useState<"ALL" | "HIGH" | "MEDIUM" | "LOW">("ALL");

  const isViewer = user.role === "VIEWER";

  useEffect(() => {
    getVersionNegotiation(contractId, versionId)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [contractId, versionId]);

  if (loading) return <div className="page"><Nav user={user} /><main className="main"><div className="loading">Loading…</div></main></div>;
  if (error)   return <div className="page"><Nav user={user} /><main className="main"><div className="error-box">{error}</div></main></div>;
  if (!data)   return null;

  const pkg      = data.package;
  const items    = (pkg.negotiation_items ?? []) as NegItem[];
  const filtered = filter === "ALL" ? items : items.filter(
    (it) => it.priority?.toUpperCase() === filter
  );

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}`} className="breadcrumb">← {contractId}</Link>
            <h1>Negotiation Package — v{versionId}</h1>
            <p className="page-subtitle">
              Expand each item to view proposed wording, regulatory basis, and record your reviewer decision.
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Link href={`/contracts/${contractId}/versions/${versionId}/findings`} className="btn btn-outline">
              Findings →
            </Link>
            <Link href={`/contracts/${contractId}/versions/${versionId}/report`} className="btn btn-outline">
              ← Risk report
            </Link>
          </div>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Total items</div>
            <div className="stat-value">{(pkg.total_items as number) ?? items.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">High priority</div>
            <div className="stat-value"><span className="badge badge--red">{(pkg.high_priority as number) ?? 0}</span></div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Medium priority</div>
            <div className="stat-value"><span className="badge badge--yellow">{(pkg.medium_priority as number) ?? 0}</span></div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Low priority</div>
            <div className="stat-value"><span className="badge badge--green">{(pkg.low_priority as number) ?? 0}</span></div>
          </div>
        </div>

        {Array.isArray(pkg.frameworks_referenced) && (pkg.frameworks_referenced as string[]).length > 0 && (
          <div className="tag-list" style={{ marginBottom: "1rem" }}>
            {(pkg.frameworks_referenced as string[]).map((f) => (
              <span key={f} className="tag">{f}</span>
            ))}
          </div>
        )}

        <div className="filter-row">
          {(["ALL", "HIGH", "MEDIUM", "LOW"] as const).map((f) => (
            <button
              key={f}
              className={`btn btn-sm ${filter === f ? "btn-primary" : "btn-outline"}`}
              onClick={() => setFilter(f)}
            >
              {f}
            </button>
          ))}
          <span className="filter-count">{filtered.length} item{filtered.length !== 1 ? "s" : ""}</span>
        </div>

        {!isViewer && (
          <div className="info-box" style={{ marginBottom: "1rem" }}>
            Expand each item and use the <strong>Reviewer decision</strong> section to record your position on each negotiation item.
          </div>
        )}

        <div className="neg-list">
          {filtered.map((item, i) => (
            <NegCard
              key={item.negotiation_id ?? i}
              item={item}
              contractId={contractId}
              versionId={versionId}
              isViewer={isViewer}
            />
          ))}
          {filtered.length === 0 && <div className="empty-state">No items for this filter.</div>}
        </div>
      </main>
    </div>
  );
}

export default function VersionNegotiationPage({
  params,
}: {
  params: Promise<{ id: string; vid: string }>;
}) {
  const { id, vid } = use(params);
  return (
    <AuthGuard>
      {(user) => <VersionNegotiationContent user={user} contractId={id} versionId={Number(vid)} />}
    </AuthGuard>
  );
}
