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
  FindingReviewOut,
  ApprovalReadinessOut,
  ApprovalReadiness,
  FindingStatus,
  FindingReviewUpdate,
  READINESS_LABEL,
  READINESS_BADGE,
} from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function severityBadge(s: string | null) {
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
    default:               return "badge badge--gray";
  }
}

const STATUS_OPTIONS: FindingStatus[] = [
  "open", "in_review", "in_negotiation", "resolved",
  "accepted_risk", "not_applicable", "deferred",
];

function statusLabel(s: FindingStatus): string {
  return s.replace(/_/g, " ");
}

// ── Readiness banner ──────────────────────────────────────────────────────────

function ReadinessBanner({
  readiness,
  contractId,
  versionId,
  onQuickFilter,
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
        <button
          className="btn btn-xs btn-outline"
          onClick={() => onQuickFilter("HIGH", "open")}
        >
          HIGH open
        </button>
        <button
          className="btn btn-xs btn-outline"
          onClick={() => onQuickFilter("MEDIUM", "open")}
        >
          MEDIUM open
        </button>
        <button
          className="btn btn-xs btn-outline"
          onClick={() => onQuickFilter("", "accepted_risk")}
        >
          Accepted risk
        </button>
        <button
          className="btn btn-xs btn-ghost"
          onClick={() => onQuickFilter("", "")}
        >
          Clear
        </button>
        <Link
          href={`/contracts/${contractId}/versions/${versionId}/report`}
          className="btn btn-xs btn-outline"
          style={{ marginLeft: "0.5rem" }}
        >
          ← Risk report
        </Link>
      </div>
    </div>
  );
}

// ── Edit Modal ────────────────────────────────────────────────────────────────

function EditModal({
  finding,
  onClose,
  onSave,
}: {
  finding:  FindingReviewOut;
  onClose:  () => void;
  onSave:   (updated: FindingReviewOut) => void;
}) {
  const [status,  setStatus]  = useState<FindingStatus>(finding.status);
  const [comment, setComment] = useState(finding.review_comment ?? "");
  const [reason,  setReason]  = useState(finding.disposition_reason ?? "");
  const [saving,  setSaving]  = useState(false);
  const [err,     setErr]     = useState("");

  async function handleSave() {
    setSaving(true);
    setErr("");
    try {
      const body: FindingReviewUpdate = {};
      if (status  !== finding.status)                        body.status             = status;
      if (comment !== (finding.review_comment   ?? ""))      body.review_comment     = comment;
      if (reason  !== (finding.disposition_reason ?? ""))    body.disposition_reason = reason;
      const updated = await updateFinding(
        finding.contract_id,
        finding.version_id,
        finding.finding_key,
        body,
      );
      onSave(updated);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Update finding</h3>
          <button className="btn btn-ghost" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <p className="mono" style={{ fontSize: "0.8rem", color: "var(--color-muted)" }}>
            {finding.finding_key}
          </p>
          {finding.topic && <p><strong>{finding.topic}</strong></p>}
          {finding.severity && (
            <span className={severityBadge(finding.severity)}>{finding.severity}</span>
          )}

          <label className="form-label" style={{ marginTop: "1rem" }}>Status</label>
          <select
            className="filter-select"
            value={status}
            onChange={(e) => setStatus(e.target.value as FindingStatus)}
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>{statusLabel(s)}</option>
            ))}
          </select>

          <label className="form-label" style={{ marginTop: "1rem" }}>Review comment</label>
          <textarea
            className="form-textarea"
            rows={3}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Add a comment..."
          />

          <label className="form-label" style={{ marginTop: "1rem" }}>Disposition reason</label>
          <textarea
            className="form-textarea"
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why was this finding closed/deferred/accepted?"
          />

          {err && <div className="error-box" style={{ marginTop: "0.5rem" }}>{err}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main content ──────────────────────────────────────────────────────────────

function FindingsContent({
  user,
  contractId,
  versionId,
}: {
  user:       SessionUser;
  contractId: string;
  versionId:  number;
}) {
  const [readiness, setReadiness] = useState<ApprovalReadinessOut | null>(null);
  const [findings,  setFindings]  = useState<FindingReviewOut[]>([]);
  const [total,     setTotal]     = useState(0);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState("");

  const [filterSeverity, setFilterSeverity] = useState("");
  const [filterStatus,   setFilterStatus]   = useState("");
  const [filterTopic,    setFilterTopic]    = useState("");

  const [editing, setEditing] = useState<FindingReviewOut | null>(null);

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
    setEditing(null);
    // Refresh readiness after a finding update
    getApprovalReadiness(contractId, versionId).then(setReadiness).catch(() => null);
  }

  function handleQuickFilter(severity: string, status: string) {
    setFilterSeverity(severity);
    setFilterStatus(status);
  }

  const isViewer = user.role === "VIEWER";

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}`} className="breadcrumb">
              ← {contractId}
            </Link>
            <h1>Finding Reviews — v{versionId}</h1>
          </div>
          <Link href={`/contracts/${contractId}/versions/${versionId}/clauses`} className="btn btn-outline">
            Clause explorer →
          </Link>
          <Link href={`/contracts/${contractId}/versions/${versionId}/report`} className="btn btn-outline">
            ← Risk report
          </Link>
        </div>

        {/* Readiness banner */}
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
          <select
            className="filter-select"
            value={filterSeverity}
            onChange={(e) => setFilterSeverity(e.target.value)}
          >
            <option value="">All severities</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low</option>
          </select>

          <select
            className="filter-select"
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
          >
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>{statusLabel(s)}</option>
            ))}
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

        {!loading && findings.length > 0 && (
          <div className="section">
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Clause</th>
                    <th>Type</th>
                    <th>Topic</th>
                    <th>Severity</th>
                    <th>Status</th>
                    <th>Assigned</th>
                    <th>Comment</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {findings.map((f) => (
                    <tr key={f.id}>
                      <td>
                        {f.clause_id ? (
                          <Link
                            href={`/contracts/${contractId}/versions/${versionId}/clauses/${encodeURIComponent(f.clause_id)}`}
                            className="mono link"
                            title="Open source clause"
                          >
                            {f.clause_id}
                          </Link>
                        ) : "—"}
                      </td>
                      <td><span className="tag">{f.finding_type}</span></td>
                      <td>{f.topic ?? "—"}</td>
                      <td>
                        <span className={severityBadge(f.severity)}>{f.severity ?? "—"}</span>
                      </td>
                      <td>
                        <span className={statusBadge(f.status)}>{statusLabel(f.status)}</span>
                      </td>
                      <td>{f.assignee_name ?? "—"}</td>
                      <td className="preview-cell">{f.review_comment ?? "—"}</td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {f.clause_id && (
                          <Link
                            href={`/contracts/${contractId}/versions/${versionId}/clauses/${encodeURIComponent(f.clause_id)}`}
                            className="btn btn-xs btn-ghost"
                            title="Open source clause"
                          >
                            ¶ Clause
                          </Link>
                        )}
                        {!isViewer && (
                          <button
                            className="btn btn-xs btn-outline"
                            onClick={() => setEditing(f)}
                            style={{ marginLeft: "0.3rem" }}
                          >
                            Edit
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {!loading && findings.length === 0 && !error && (
          <div className="empty-state" style={{ marginTop: "2rem" }}>
            No findings match the current filters.
          </div>
        )}
      </main>

      {editing && (
        <EditModal
          finding={editing}
          onClose={() => setEditing(null)}
          onSave={handleSaved}
        />
      )}
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
      {(user) => (
        <FindingsContent user={user} contractId={id} versionId={Number(vid)} />
      )}
    </AuthGuard>
  );
}
