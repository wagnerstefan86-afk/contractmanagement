"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  getClauseDetail,
  ClauseDetailOut,
  SRMatchOut,
  ClauseFindingOut,
  NegotiationItemOut,
  FindingStatus,
} from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function severityBadge(s: string | null | undefined) {
  switch ((s ?? "").toUpperCase()) {
    case "HIGH":   return "badge badge--red";
    case "MEDIUM": return "badge badge--yellow";
    case "LOW":    return "badge badge--green";
    default:       return "badge badge--gray";
  }
}

function statusBadge(s: string) {
  switch (s as FindingStatus) {
    case "open":           return "badge badge--red";
    case "in_review":
    case "in_negotiation": return "badge badge--yellow";
    case "resolved":       return "badge badge--green";
    default:               return "badge badge--gray";
  }
}

function matchBadge(mt: string) {
  if (mt === "DIRECT_MATCH")   return "badge badge--green";
  if (mt === "INDIRECT_MATCH") return "badge badge--yellow";
  return "badge badge--gray";
}

function priorityBadge(p: string | null | undefined) {
  switch ((p ?? "").toUpperCase()) {
    case "HIGH":   return "badge badge--red";
    case "MEDIUM": return "badge badge--yellow";
    case "LOW":    return "badge badge--green";
    default:       return "badge badge--gray";
  }
}

// ── Page content ──────────────────────────────────────────────────────────────

function ClauseDetailContent({
  user,
  contractId,
  versionId,
  clauseId,
}: {
  user:       SessionUser;
  contractId: string;
  versionId:  number;
  clauseId:   string;
}) {
  const [detail,  setDetail]  = useState<ClauseDetailOut | null>(null);
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getClauseDetail(contractId, versionId, clauseId)
      .then(setDetail)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load clause."))
      .finally(() => setLoading(false));
  }, [contractId, versionId, clauseId]);

  if (loading) return (
    <div className="page"><Nav user={user} /><main className="main"><div className="loading">Loading…</div></main></div>
  );
  if (error) return (
    <div className="page"><Nav user={user} /><main className="main"><div className="error-box">{error}</div></main></div>
  );
  if (!detail) return null;

  const ob = detail.obligation_assessment;
  const rs = detail.risk_score;

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}/versions/${versionId}/clauses`} className="breadcrumb">
              ← Clause explorer
            </Link>
            <h1 className="mono">{detail.clause_id}</h1>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Link href={`/contracts/${contractId}/versions/${versionId}/findings`}   className="btn btn-outline btn-sm">Findings</Link>
            <Link href={`/contracts/${contractId}/versions/${versionId}/report`}     className="btn btn-outline btn-sm">Report</Link>
            <Link href={`/contracts/${contractId}/versions/${versionId}/negotiation`} className="btn btn-outline btn-sm">Negotiation</Link>
          </div>
        </div>

        {/* Meta chips */}
        <div className="readiness-counts" style={{ marginBottom: "1.5rem" }}>
          {detail.page != null && <span className="meta-chip">Page {detail.page}</span>}
          {detail.layout_type && <span className="tag">{detail.layout_type}</span>}
          {ob?.severity && <span className={severityBadge(ob.severity)}>{ob.severity}</span>}
          {rs && <span className="meta-chip">Risk score: <strong>{rs.risk_score}</strong></span>}
          {rs?.priority && <span className={priorityBadge(rs.priority)}>{rs.priority} priority</span>}
          <span className="meta-chip">Status: <strong>{detail.workflow_context.review_status}</strong></span>
          <span className="meta-chip">Readiness: <strong>{detail.workflow_context.approval_readiness.replace(/_/g, " ")}</strong></span>
        </div>

        {/* Clause text */}
        {detail.text && (
          <div className="section">
            <h2>Contract text</h2>
            <div className="clause-text-block">
              <p className="clause-text">{detail.text}</p>
            </div>
          </div>
        )}

        {/* Stats grid */}
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Obligation</div>
            <div className="stat-value" style={{ fontSize: "0.9rem" }}>
              {ob ? ob.assessment.replace(/_/g, " ") : "—"}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Risk score</div>
            <div className="stat-value">{rs?.risk_score ?? "—"}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Findings</div>
            <div className="stat-value">{detail.findings.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">SR matches</div>
            <div className="stat-value">{detail.sr_matches.length}</div>
          </div>
        </div>

        {/* Obligation assessment */}
        {ob && (
          <div className="section">
            <h2>Obligation assessment</h2>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
              <span className="tag">{ob.assessment.replace(/_/g, " ")}</span>
              {ob.severity && <span className={severityBadge(ob.severity)}>{ob.severity}</span>}
            </div>
            {ob.reason && <p>{ob.reason}</p>}
            {ob.recommended_action && (
              <div className="info-box" style={{ marginTop: "0.5rem" }}>
                <strong>Recommended action:</strong> {ob.recommended_action}
              </div>
            )}
          </div>
        )}

        {/* SR Matches */}
        {detail.sr_matches.length > 0 ? (
          <div className="section">
            <h2>Regulatory matches ({detail.sr_matches.length})</h2>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>SR ID</th><th>Framework</th><th>Match type</th>
                    <th>Confidence</th><th>Title</th><th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.sr_matches.map((m: SRMatchOut) => (
                    <tr key={`${m.sr_id}-${m.match_type}`}>
                      <td className="mono">{m.sr_id}</td>
                      <td><span className="tag">{m.framework}</span></td>
                      <td><span className={matchBadge(m.match_type)}>{m.match_type.replace(/_/g, " ")}</span></td>
                      <td>{(m.match_confidence * 100).toFixed(0)}%</td>
                      <td>{m.sr_title ?? "—"}</td>
                      <td className="preview-cell">{m.extracted_evidence ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="section">
            <h2>Regulatory matches</h2>
            <div className="empty-state" style={{ padding: "1.5rem" }}>No SR matches for this clause.</div>
          </div>
        )}

        {/* Findings */}
        <div className="section">
          <h2>Linked findings ({detail.findings.length})</h2>
          {detail.findings.length > 0 ? (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr><th>Type</th><th>Topic</th><th>Severity</th><th>Status</th><th>Comment</th><th>Preview</th></tr>
                </thead>
                <tbody>
                  {detail.findings.map((f: ClauseFindingOut) => (
                    <tr key={f.id}>
                      <td><span className="tag">{f.finding_type}</span></td>
                      <td>{f.topic ?? "—"}</td>
                      <td><span className={severityBadge(f.severity)}>{f.severity ?? "—"}</span></td>
                      <td><span className={statusBadge(f.status)}>{f.status.replace(/_/g, " ")}</span></td>
                      <td className="preview-cell">{f.review_comment ?? "—"}</td>
                      <td className="preview-cell">{f.text_preview ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state" style={{ padding: "1.5rem" }}>
              No findings linked to this clause.{" "}
              <Link href={`/contracts/${contractId}/versions/${versionId}/findings`} className="link">
                View all findings →
              </Link>
            </div>
          )}
        </div>

        {/* Negotiation items */}
        {detail.negotiation_items.length > 0 && (
          <div className="section">
            <h2>Negotiation items ({detail.negotiation_items.length})</h2>
            {detail.negotiation_items.map((n: NegotiationItemOut, i: number) => (
              <div key={i} className="neg-item-card" style={{ marginBottom: "1rem" }}>
                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.5rem" }}>
                  {n.neg_id && <span className="mono" style={{ fontWeight: 600 }}>{n.neg_id}</span>}
                  {n.priority && <span className={priorityBadge(n.priority)}>{n.priority}</span>}
                  {n.topic && <span className="tag">{n.topic}</span>}
                  {n.finding_type && <span className="tag">{n.finding_type.replace(/_/g, " ")}</span>}
                </div>
                {n.position_summary && <p>{n.position_summary}</p>}
                {n.recommended_text && (
                  <details style={{ marginTop: "0.5rem" }}>
                    <summary style={{ cursor: "pointer", color: "var(--color-primary)", fontSize: "0.875rem" }}>
                      Recommended clause text
                    </summary>
                    <pre style={{ marginTop: "0.5rem", whiteSpace: "pre-wrap", fontSize: "0.85rem", background: "#f8fafc", padding: "0.75rem", borderRadius: "0.375rem", border: "1px solid var(--color-border)" }}>
                      {n.recommended_text}
                    </pre>
                  </details>
                )}
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

export default function ClauseDetailPage({
  params,
}: {
  params: Promise<{ id: string; vid: string; clauseId: string }>;
}) {
  const { id, vid, clauseId } = use(params);
  return (
    <AuthGuard>
      {(user) => (
        <ClauseDetailContent
          user={user}
          contractId={id}
          versionId={Number(vid)}
          clauseId={decodeURIComponent(clauseId)}
        />
      )}
    </AuthGuard>
  );
}
