"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  listFindings,
  getApprovalReadiness,
  updateFinding,
  getClauseDetail,
  FindingReviewOut,
  ApprovalReadinessOut,
  ApprovalReadiness,
  FindingStatus,
  FindingReviewUpdate,
  ClauseDetailOut,
  READINESS_LABEL,
  READINESS_BADGE,
} from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function severityBadge(s: string | null | undefined) {
  const u = (s ?? "").toUpperCase();
  if (u === "HIGH")   return "badge badge--red";
  if (u === "MEDIUM") return "badge badge--yellow";
  if (u === "LOW")    return "badge badge--green";
  return "badge badge--gray";
}

function statusBadge(s: FindingStatus) {
  switch (s) {
    case "open":           return "badge badge--red";
    case "in_review":      return "badge badge--yellow";
    case "in_negotiation": return "badge badge--yellow";
    case "resolved":       return "badge badge--green";
    case "accepted_risk":  return "badge badge--green";
    default:               return "badge badge--gray";
  }
}

function statusLabel(s: string): string {
  const labels: Record<string, string> = {
    open:           "Open",
    in_review:      "In Review",
    in_negotiation: "In Negotiation",
    resolved:       "Resolved",
    accepted_risk:  "Accepted Risk",
    not_applicable: "Not Applicable",
    deferred:       "Deferred",
  };
  return labels[s] ?? s.replace(/_/g, " ");
}

const REVIEWER_DECISIONS: { label: string; value: FindingStatus; description: string }[] = [
  { label: "Accept risk",             value: "accepted_risk",  description: "Risk accepted — no contract change needed" },
  { label: "Request contract change", value: "in_negotiation", description: "Request vendor to amend this clause" },
  { label: "Escalate to legal",       value: "in_review",      description: "Flag for legal team review" },
  { label: "Customer responsibility", value: "not_applicable", description: "Responsibility accepted on our side" },
  { label: "Not applicable",          value: "not_applicable", description: "Finding does not apply to our context" },
  { label: "Needs clarification",     value: "deferred",       description: "Defer pending further information" },
  { label: "Resolved",                value: "resolved",       description: "Issue has been resolved" },
];

// ── Approval readiness banner ─────────────────────────────────────────────────

function ReadinessBanner({
  readiness, contractId, versionId, onQuickFilter,
}: {
  readiness: ApprovalReadinessOut;
  contractId: string;
  versionId: number;
  onQuickFilter: (severity: string, status: string) => void;
}) {
  const r = readiness.approval_readiness;
  const c = readiness.counts;
  const bannerClass: Record<ApprovalReadiness, string> = {
    blocked:                        "readiness-panel readiness-panel--blocked",
    review_required:                "readiness-panel readiness-panel--warn",
    ready_for_conditional_approval: "readiness-panel readiness-panel--conditional",
    ready_for_approval:             "readiness-panel readiness-panel--ready",
  };
  return (
    <div className={bannerClass[r]} style={{ marginBottom: "1.5rem" }}>
      <div className="readiness-header">
        <span>Approval Readiness:</span>
        <span className={READINESS_BADGE[r]}>{READINESS_LABEL[r]}</span>
        <span className="meta-chip">HIGH unresolved: <strong>{c.high_open}</strong></span>
        <span className="meta-chip">MEDIUM unresolved: <strong>{c.medium_open}</strong></span>
        <span className="meta-chip">Resolved: <strong>{c.resolved}</strong></span>
      </div>
      <div className="readiness-quick-filters">
        <span style={{ fontSize: "0.85rem", color: "var(--color-muted)", marginRight: "0.5rem" }}>Quick filters:</span>
        <button className="btn btn-xs btn-outline" onClick={() => onQuickFilter("HIGH", "open")}>HIGH open</button>
        <button className="btn btn-xs btn-outline" onClick={() => onQuickFilter("MEDIUM", "open")}>MEDIUM open</button>
        <button className="btn btn-xs btn-outline" onClick={() => onQuickFilter("", "accepted_risk")}>Accepted risk</button>
        <button className="btn btn-xs btn-ghost" onClick={() => onQuickFilter("", "")}>Clear</button>
        <Link href={`/contracts/${contractId}/versions/${versionId}/report`} className="btn btn-xs btn-outline" style={{ marginLeft: "0.5rem" }}>
          ← Risk report
        </Link>
      </div>
    </div>
  );
}

// ── Expanded finding detail ───────────────────────────────────────────────────

function FindingDetail({
  finding, contractId, versionId, isViewer, onSaved,
}: {
  finding: FindingReviewOut;
  contractId: string;
  versionId: number;
  isViewer: boolean;
  onSaved: (updated: FindingReviewOut) => void;
}) {
  const [clauseDetail, setClauseDetail] = useState<ClauseDetailOut | null>(null);
  const [loadingClause, setLoadingClause] = useState(false);

  const [decision,  setDecision]  = useState<FindingStatus | "">("");
  const [notes,     setNotes]     = useState(finding.disposition_reason ?? "");
  const [comment,   setComment]   = useState(finding.review_comment ?? "");
  const [saving,    setSaving]    = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saved,     setSaved]     = useState(false);

  useEffect(() => {
    if (finding.clause_id) {
      setLoadingClause(true);
      getClauseDetail(contractId, versionId, finding.clause_id)
        .then(setClauseDetail)
        .catch(() => null)
        .finally(() => setLoadingClause(false));
    }
  }, [finding.clause_id, contractId, versionId]);

  async function handleDecision() {
    if (!decision) return;
    setSaving(true);
    setSaveError("");
    try {
      const body: FindingReviewUpdate = {
        status: decision,
        disposition_reason: notes || undefined,
        review_comment: comment || undefined,
      };
      const updated = await updateFinding(contractId, versionId, finding.finding_key, body);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      onSaved(updated);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  // Find the best SR match for AI context
  const srMatches = clauseDetail?.sr_matches ?? [];
  const bestMatch = srMatches.find((m) => m.match_type === "DIRECT_MATCH") ?? srMatches[0] ?? null;
  const ai = bestMatch?.ai_metadata as Record<string, unknown> | null ?? null;
  const obligationAssessment = clauseDetail?.obligation_assessment;
  const riskScore = clauseDetail?.risk_score;

  return (
    <div className="finding-detail">
      {/* ── Clause text ─────────────────────────────────────────────────── */}
      {finding.clause_id && (
        <div className="neg-section">
          <h4>
            Clause{" "}
            <Link
              href={`/contracts/${contractId}/versions/${versionId}/clauses/${encodeURIComponent(finding.clause_id)}`}
              className="link"
              style={{ fontSize: "0.85rem" }}
            >
              {finding.clause_id} →
            </Link>
          </h4>
          {loadingClause ? (
            <div className="text-muted" style={{ fontSize: "0.85rem" }}>Loading clause…</div>
          ) : clauseDetail?.text ? (
            <blockquote className="clause-excerpt" style={{ maxHeight: "8rem", overflowY: "auto" }}>
              {clauseDetail.text}
            </blockquote>
          ) : (
            <p className="text-muted" style={{ fontSize: "0.85rem" }}>{finding.text_preview ?? "—"}</p>
          )}
        </div>
      )}

      {/* ── Obligation / risk context ────────────────────────────────────── */}
      {obligationAssessment && (
        <div className="neg-section">
          <h4>Obligation assessment</h4>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.25rem" }}>
            <span className="tag">{obligationAssessment.assessment?.replace(/_/g, " ")}</span>
            {obligationAssessment.severity && (
              <span className={severityBadge(obligationAssessment.severity)}>{obligationAssessment.severity}</span>
            )}
          </div>
          {obligationAssessment.reason && <p style={{ fontSize: "0.9rem" }}>{obligationAssessment.reason}</p>}
          {obligationAssessment.recommended_action && (
            <div className="info-box" style={{ margin: "0.25rem 0 0" }}>
              <strong>Action:</strong> {obligationAssessment.recommended_action}
            </div>
          )}
        </div>
      )}

      {/* ── Framework / SR matches ───────────────────────────────────────── */}
      {srMatches.length > 0 && (
        <div className="neg-section">
          <h4>Framework matches</h4>
          {srMatches.slice(0, 4).map((m, i) => (
            <div key={i} style={{ marginBottom: "0.5rem", padding: "0.4rem 0.6rem", background: "var(--color-surface)", borderRadius: "0.375rem", border: "1px solid var(--color-border)" }}>
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", alignItems: "center" }}>
                <span className="mono" style={{ fontSize: "0.8rem" }}>{m.sr_id}</span>
                <span className="tag">{m.framework}</span>
                {m.match_type === "DIRECT_MATCH"
                  ? <span className="badge badge--green" style={{ fontSize: "0.75rem" }}>Direct</span>
                  : <span className="badge badge--gray" style={{ fontSize: "0.75rem" }}>Indirect</span>}
                {m.confidence_bucket && <span className="meta-chip" style={{ fontSize: "0.75rem" }}>{m.confidence_bucket}</span>}
                {m.review_priority && <span className={severityBadge(m.review_priority)} style={{ fontSize: "0.75rem" }}>{m.review_priority}</span>}
                {m.decision_delta && m.decision_delta !== "none" && (
                  <span className="badge badge--yellow" style={{ fontSize: "0.75rem" }}>delta: {m.decision_delta}</span>
                )}
              </div>
              {m.sr_title && <p style={{ fontSize: "0.85rem", marginTop: "0.2rem", color: "var(--color-muted)" }}>{m.sr_title}</p>}
              {m.extracted_evidence && (
                <p style={{ fontSize: "0.8rem", marginTop: "0.2rem", fontStyle: "italic" }}>&ldquo;{m.extracted_evidence}&rdquo;</p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── AI assessment ───────────────────────────────────────────────── */}
      {ai && (
        <div className="neg-section">
          <h4>AI assessment</h4>
          <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: "0.4rem" }}>
            {ai.llm_used === true  && <span className="badge badge--blue" style={{ fontSize: "0.75rem" }}>AI used</span>}
            {ai.llm_used === false && <span className="badge badge--gray" style={{ fontSize: "0.75rem" }}>Deterministic</span>}
            {ai.provider != null   && <span className="tag" style={{ fontSize: "0.75rem" }}>{String(ai.provider)}</span>}
            {ai.model    != null   && <span className="tag" style={{ fontSize: "0.75rem" }}>{String(ai.model)}</span>}
            {ai.confidence != null && <span className="meta-chip" style={{ fontSize: "0.75rem" }}>confidence: {String(ai.confidence)}</span>}
          </div>
          {bestMatch?.baseline_result && (
            <p style={{ fontSize: "0.85rem" }}>
              Baseline: <strong>{bestMatch.baseline_result}</strong>
              {bestMatch.decision_delta && bestMatch.decision_delta !== "none" && (
                <> · AI override: <strong style={{ color: "var(--color-warning)" }}>{bestMatch.decision_delta}</strong></>
              )}
            </p>
          )}
          {bestMatch?.match_reasoning && (
            <p style={{ fontSize: "0.85rem", marginTop: "0.25rem", color: "var(--color-muted)" }}>{bestMatch.match_reasoning}</p>
          )}
        </div>
      )}

      {/* ── Recommended action ──────────────────────────────────────────── */}
      {finding.recommended_action && (
        <div className="neg-section">
          <h4>Recommended action</h4>
          <div className="info-box" style={{ margin: 0 }}>{finding.recommended_action}</div>
        </div>
      )}

      {/* ── Risk metadata ───────────────────────────────────────────────── */}
      {riskScore && (
        <div className="neg-meta-row">
          {riskScore.risk_score != null && <span className="meta-chip">Risk score: {riskScore.risk_score}</span>}
          {riskScore.priority && <span className={severityBadge(riskScore.priority)}>{riskScore.priority}</span>}
          {riskScore.obligation && <span className="meta-chip">Obligation: {riskScore.obligation}</span>}
        </div>
      )}

      {/* ── Reviewer decision ───────────────────────────────────────────── */}
      {!isViewer && (
        <div className="neg-section" style={{ borderTop: "2px solid var(--color-border)", paddingTop: "0.75rem", marginTop: "0.75rem" }}>
          <h4>Reviewer decision</h4>
          {saved && <div className="success-box" style={{ marginBottom: "0.5rem" }}>Decision recorded.</div>}
          {saveError && <div className="error-box" style={{ marginBottom: "0.5rem" }}>{saveError}</div>}

          <div style={{ display: "grid", gap: "0.5rem", gridTemplateColumns: "1fr 1fr", marginBottom: "0.5rem" }}>
            {REVIEWER_DECISIONS.map((d) => (
              <button
                key={`${d.label}-${d.value}`}
                className={`btn btn-sm ${decision === d.value && d.label === REVIEWER_DECISIONS.find(x => x.value === decision && x.label === d.label)?.label ? "btn-primary" : "btn-outline"}`}
                style={{ textAlign: "left", justifyContent: "flex-start" }}
                onClick={() => setDecision(d.value)}
                disabled={saving}
                title={d.description}
              >
                {d.label}
              </button>
            ))}
          </div>

          {decision && (
            <p style={{ fontSize: "0.8rem", color: "var(--color-muted)", marginBottom: "0.5rem" }}>
              {REVIEWER_DECISIONS.find((d) => d.value === decision)?.description}
            </p>
          )}

          <textarea
            className="workflow-notes"
            rows={2}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            disabled={saving}
            placeholder="Review comment (optional)…"
            style={{ marginBottom: "0.4rem" }}
          />
          <textarea
            className="workflow-notes"
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            disabled={saving}
            placeholder="Disposition reason (optional)…"
            style={{ marginBottom: "0.5rem" }}
          />
          <button
            className="btn btn-sm btn-primary"
            onClick={handleDecision}
            disabled={!decision || saving}
          >
            {saving ? "Saving…" : "Record decision"}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Finding row ───────────────────────────────────────────────────────────────

function FindingRow({
  finding, contractId, versionId, isViewer, onSaved,
}: {
  finding: FindingReviewOut;
  contractId: string;
  versionId: number;
  isViewer: boolean;
  onSaved: (updated: FindingReviewOut) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const priority = (finding.review_priority ?? finding.severity ?? "").toUpperCase();

  return (
    <>
      <tr
        className={expanded ? "finding-row finding-row--expanded" : "finding-row"}
        style={{ cursor: "pointer" }}
        onClick={() => setExpanded((x) => !x)}
      >
        {/* Priority */}
        <td>
          {priority && <span className={severityBadge(priority)}>{priority}</span>}
        </td>
        {/* Clause */}
        <td>
          {finding.clause_id ? (
            <span className="mono" style={{ fontSize: "0.85rem" }}>{finding.clause_id}</span>
          ) : "—"}
        </td>
        {/* Preview */}
        <td className="preview-cell" style={{ maxWidth: "14rem" }}>
          <span style={{ fontSize: "0.82rem" }}>{finding.text_preview ?? "—"}</span>
        </td>
        {/* Topic */}
        <td>
          {finding.topic
            ? <span className="tag" style={{ fontSize: "0.8rem" }}>{finding.topic}</span>
            : <span className="text-muted">—</span>}
        </td>
        {/* Severity */}
        <td>
          <span className={severityBadge(finding.severity)}>{finding.severity ?? "—"}</span>
        </td>
        {/* Recommended action (compact) */}
        <td className="preview-cell" style={{ maxWidth: "14rem" }}>
          {finding.recommended_action
            ? <span style={{ fontSize: "0.82rem" }}>{finding.recommended_action.slice(0, 120)}{finding.recommended_action.length > 120 ? "…" : ""}</span>
            : <span className="text-muted">—</span>}
        </td>
        {/* AI used */}
        <td style={{ whiteSpace: "nowrap" }}>
          {finding.ai_used === true  && <span className="badge badge--blue"  style={{ fontSize: "0.7rem" }}>AI</span>}
          {finding.ai_used === false && <span className="badge badge--gray"  style={{ fontSize: "0.7rem" }}>det.</span>}
          {finding.ai_used == null   && <span className="text-muted"        style={{ fontSize: "0.7rem" }}>—</span>}
          {finding.confidence_bucket && (
            <span className="meta-chip" style={{ fontSize: "0.7rem", marginLeft: "0.25rem" }}>{finding.confidence_bucket}</span>
          )}
        </td>
        {/* Status */}
        <td>
          <span className={statusBadge(finding.status)}>{statusLabel(finding.status)}</span>
        </td>
        {/* Owner */}
        <td style={{ fontSize: "0.82rem" }}>
          {finding.assigned_owner_role ?? finding.assignee_name ?? "—"}
        </td>
        {/* Expand toggle */}
        <td style={{ whiteSpace: "nowrap" }}>
          <button className="btn btn-xs btn-ghost" onClick={(e) => { e.stopPropagation(); setExpanded((x) => !x); }}>
            {expanded ? "▲" : "▼"}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={9} style={{ padding: "0", background: "var(--color-surface-raised)" }}>
            <div style={{ padding: "1rem 1.25rem", borderBottom: "1px solid var(--color-border)" }}>
              <FindingDetail
                finding={finding}
                contractId={contractId}
                versionId={versionId}
                isViewer={isViewer}
                onSaved={onSaved}
              />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main content ──────────────────────────────────────────────────────────────

function FindingsContent({
  user, contractId, versionId,
}: {
  user: SessionUser; contractId: string; versionId: number;
}) {
  const [readiness, setReadiness] = useState<ApprovalReadinessOut | null>(null);
  const [findings,  setFindings]  = useState<FindingReviewOut[]>([]);
  const [total,     setTotal]     = useState(0);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState("");

  const [filterSeverity, setFilterSeverity] = useState("");
  const [filterStatus,   setFilterStatus]   = useState("");
  const [filterTopic,    setFilterTopic]    = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [read, lst] = await Promise.all([
        getApprovalReadiness(contractId, versionId).catch(() => null),
        listFindings(contractId, versionId, {
          severity: filterSeverity || undefined,
          status:   filterStatus   || undefined,
          topic:    filterTopic    || undefined,
        }),
      ]);
      setReadiness(read);
      setFindings(lst.findings);
      setTotal(lst.total);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load findings.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [contractId, versionId, filterSeverity, filterStatus, filterTopic]);

  function handleSaved(updated: FindingReviewOut) {
    setFindings((prev) => prev.map((f) => f.id === updated.id ? updated : f));
    getApprovalReadiness(contractId, versionId).then(setReadiness).catch(() => null);
  }

  function handleQuickFilter(severity: string, status: string) {
    setFilterSeverity(severity);
    setFilterStatus(status);
  }

  const isViewer = user.role === "VIEWER";

  // Sort: open HIGH first, then MEDIUM, then others
  const SEVERITY_ORDER: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };
  const STATUS_ORDER:   Record<string, number>  = { open: 0, in_review: 1, in_negotiation: 2, deferred: 3, resolved: 4, accepted_risk: 5, not_applicable: 6 };
  const sorted = [...findings].sort((a, b) => {
    const sa = SEVERITY_ORDER[(a.review_priority ?? a.severity ?? "").toUpperCase()] ?? 9;
    const sb = SEVERITY_ORDER[(b.review_priority ?? b.severity ?? "").toUpperCase()] ?? 9;
    if (sa !== sb) return sa - sb;
    const oa = STATUS_ORDER[a.status] ?? 9;
    const ob = STATUS_ORDER[b.status] ?? 9;
    return oa - ob;
  });

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}`} className="breadcrumb">← {contractId}</Link>
            <h1>Finding Reviews — v{versionId}</h1>
            <p className="page-subtitle">Expand each row to view clause context, framework matches, and record your decision.</p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Link href={`/contracts/${contractId}/versions/${versionId}/clauses`} className="btn btn-outline">
              Clause explorer →
            </Link>
            <Link href={`/contracts/${contractId}/versions/${versionId}/report`} className="btn btn-outline">
              ← Risk report
            </Link>
          </div>
        </div>

        {readiness && (
          <ReadinessBanner
            readiness={readiness}
            contractId={contractId}
            versionId={versionId}
            onQuickFilter={handleQuickFilter}
          />
        )}

        {/* Filters */}
        <div className="filter-row">
          <select className="filter-select" value={filterSeverity} onChange={(e) => setFilterSeverity(e.target.value)}>
            <option value="">All severities</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low</option>
          </select>
          <select className="filter-select" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="in_review">In Review</option>
            <option value="in_negotiation">In Negotiation</option>
            <option value="deferred">Deferred</option>
            <option value="accepted_risk">Accepted Risk</option>
            <option value="resolved">Resolved</option>
            <option value="not_applicable">Not Applicable</option>
          </select>
          <input
            className="filter-input"
            placeholder="Filter by topic…"
            value={filterTopic}
            onChange={(e) => setFilterTopic(e.target.value)}
          />
          <span className="filter-count">{total} finding{total !== 1 ? "s" : ""}</span>
        </div>

        {error && <div className="error-box" style={{ marginTop: "1rem" }}>{error}</div>}
        {loading && <div className="loading" style={{ marginTop: "1rem" }}>Loading…</div>}

        {!loading && sorted.length > 0 && (
          <div className="section">
            <div className="table-scroll">
              <table className="table findings-queue">
                <thead>
                  <tr>
                    <th>Priority</th>
                    <th>Clause</th>
                    <th>Preview</th>
                    <th>Topic</th>
                    <th>Severity</th>
                    <th>Recommended action</th>
                    <th>AI</th>
                    <th>Status</th>
                    <th>Owner</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((f) => (
                    <FindingRow
                      key={f.id}
                      finding={f}
                      contractId={contractId}
                      versionId={versionId}
                      isViewer={isViewer}
                      onSaved={handleSaved}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {!loading && sorted.length === 0 && !error && (
          <div className="empty-state" style={{ marginTop: "2rem" }}>
            No findings match the current filters.
          </div>
        )}
      </main>
    </div>
  );
}

export default function FindingsPage({
  params,
}: {
  params: Promise<{ id: string; vid: string }>;
}) {
  const { id, vid } = use(params);
  return (
    <AuthGuard>
      {(user) => <FindingsContent user={user} contractId={id} versionId={Number(vid)} />}
    </AuthGuard>
  );
}
