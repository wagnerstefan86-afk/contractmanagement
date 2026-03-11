"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  getVersionReport,
  getApprovalReadiness,
  getClosureBundle,
  downloadClosureBundleBlob,
  ReportOut,
  ApprovalReadinessOut,
  ApprovalReadiness,
  ClosureBundleOut,
  READINESS_LABEL,
  READINESS_BADGE,
  BlockingFinding,
} from "@/lib/api";

function riskBadge(severity: string) {
  if (severity === "HIGH" || severity === "high") return "badge badge--red";
  if (severity === "MEDIUM" || severity === "medium") return "badge badge--yellow";
  if (severity === "LOW" || severity === "low") return "badge badge--green";
  return "badge badge--gray";
}

interface RiskItem {
  clause_id: string;
  page?: number;
  topic?: string;
  severity?: string;
  risk_score?: number;
  text_preview?: string;
}
interface Metadata {
  overall_risk?: string;
  total_clauses?: number;
  total_findings?: number;
  high_risk_clauses?: number;
  medium_risk_clauses?: number;
  low_risk_clauses?: number;
  frameworks_in_scope?: string[];
}

// ── Readiness panel ────────────────────────────────────────────────────────────

function ReadinessPanel({
  readiness,
  contractId,
  versionId,
}: {
  readiness: ApprovalReadinessOut;
  contractId: string;
  versionId: number;
}) {
  const r = readiness.approval_readiness;
  const c = readiness.counts;

  const desc: Record<ApprovalReadiness, string> = {
    blocked:                        "HIGH severity findings remain unresolved. Approval is blocked until they are addressed.",
    review_required:                "MEDIUM severity findings require attention before approval.",
    ready_for_conditional_approval: "All HIGH findings are closed. MEDIUM findings may still be in negotiation.",
    ready_for_approval:             "All HIGH and MEDIUM findings are closed. Version is ready for full approval.",
  };

  const panelClass: Record<ApprovalReadiness, string> = {
    blocked:                        "readiness-panel readiness-panel--blocked",
    review_required:                "readiness-panel readiness-panel--warn",
    ready_for_conditional_approval: "readiness-panel readiness-panel--conditional",
    ready_for_approval:             "readiness-panel readiness-panel--ready",
  };

  return (
    <div className={panelClass[r]} style={{ marginTop: "1.5rem" }}>
      <div className="readiness-header">
        <h2>Approval Readiness</h2>
        <span className={READINESS_BADGE[r]}>{READINESS_LABEL[r]}</span>
      </div>
      <p className="readiness-desc">{desc[r]}</p>

      <div className="readiness-counts">
        <span className="meta-chip">HIGH unresolved: <strong>{c.high_open}</strong></span>
        <span className="meta-chip">MEDIUM unresolved: <strong>{c.medium_open}</strong></span>
        <span className="meta-chip">Resolved: <strong>{c.resolved}</strong></span>
        <span className="meta-chip">Accepted risk: <strong>{c.accepted_risk}</strong></span>
        <span className="meta-chip">Total findings: <strong>{c.total}</strong></span>
      </div>

      {readiness.blocking_reasons.length > 0 && (
        <div style={{ marginTop: "1rem" }}>
          <h4 style={{ marginBottom: "0.5rem" }}>Blocking findings (top {Math.min(readiness.blocking_reasons.length, 5)})</h4>
          <table className="table" style={{ fontSize: "0.85rem" }}>
            <thead>
              <tr>
                <th>Clause</th><th>Severity</th><th>Status</th><th>Topic</th>
              </tr>
            </thead>
            <tbody>
              {readiness.blocking_reasons.slice(0, 5).map((b: BlockingFinding) => (
                <tr key={b.finding_key}>
                  <td className="mono">{b.clause_id ?? "—"}</td>
                  <td><span className={riskBadge(b.severity ?? "")}>{b.severity ?? "—"}</span></td>
                  <td>{b.status}</td>
                  <td>{b.topic ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ marginTop: "1rem" }}>
        <Link
          href={`/contracts/${contractId}/versions/${versionId}/findings`}
          className="btn btn-outline btn-sm"
        >
          View all findings →
        </Link>
      </div>
    </div>
  );
}

// ── Closure Bundle panel ───────────────────────────────────────────────────────

function ClosureBundlePanel({
  bundle,
  contractId,
  versionId,
}: {
  bundle: ClosureBundleOut;
  contractId: string;
  versionId: number;
}) {
  const [downloading, setDownloading] = useState(false);
  const [dlError,     setDlError]     = useState("");

  const m = bundle.manifest;
  const statusClass = m.review_status === "approved"
    ? "badge badge--green"
    : "badge badge--red";

  async function handleDownload() {
    setDlError("");
    setDownloading(true);
    try {
      const { url, filename } = await downloadClosureBundleBlob(contractId, versionId);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      setDlError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="section" style={{ marginTop: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.75rem" }}>
        <h2 style={{ margin: 0 }}>Closure Bundle</h2>
        <span className={statusClass}>{m.review_status}</span>
        {m.review_decision !== "none" && (
          <span className="badge badge--gray">{m.review_decision.replace(/_/g, " ")}</span>
        )}
      </div>

      <div className="stats-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", marginBottom: "1rem" }}>
        <div className="stat-card">
          <div className="stat-label">Generated at</div>
          <div className="stat-value" style={{ fontSize: "0.875rem" }}>
            {new Date(m.generated_at).toLocaleString()}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Analysis ID</div>
          <div className="stat-value stat-value--sm">#{m.analysis_id}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Overall risk</div>
          <div className="stat-value">
            {m.overall_risk
              ? <span className={riskBadge(m.overall_risk)}>{m.overall_risk}</span>
              : "—"}
          </div>
        </div>
        {m.approved_or_rejected_at && (
          <div className="stat-card">
            <div className="stat-label">Decision at</div>
            <div className="stat-value" style={{ fontSize: "0.875rem" }}>
              {new Date(m.approved_or_rejected_at).toLocaleString()}
            </div>
          </div>
        )}
      </div>

      <div style={{ marginBottom: "1rem" }}>
        <span className="form-label">Bundle contents ({m.bundle_contents.length} files)</span>
        <div className="tag-list" style={{ marginTop: "0.4rem" }}>
          {m.bundle_contents.map((f) => (
            <span key={f} className="tag mono" style={{ fontSize: "0.8rem" }}>{f}</span>
          ))}
        </div>
      </div>

      {m.bundle_hash && (
        <div style={{ marginBottom: "1rem", fontSize: "0.8rem", color: "var(--color-muted)" }}>
          <span className="form-label">Integrity hash</span>
          <code className="mono" style={{ display: "block", marginTop: "0.25rem", wordBreak: "break-all" }}>
            {m.bundle_hash}
          </code>
        </div>
      )}

      {dlError && (
        <div className="error-box" style={{ marginBottom: "0.75rem" }}>{dlError}</div>
      )}

      {bundle.has_zip ? (
        <button
          className="btn btn-primary"
          onClick={handleDownload}
          disabled={downloading}
        >
          {downloading ? "Preparing download…" : "⬇ Download ZIP"}
        </button>
      ) : (
        <span className="badge badge--gray">ZIP not yet available</span>
      )}
    </div>
  );
}

// ── Main content ───────────────────────────────────────────────────────────────

function VersionReportContent({
  user,
  contractId,
  versionId,
}: {
  user: SessionUser;
  contractId: string;
  versionId: number;
}) {
  const [report,    setReport]    = useState<ReportOut | null>(null);
  const [readiness, setReadiness] = useState<ApprovalReadinessOut | null>(null);
  const [bundle,    setBundle]    = useState<ClosureBundleOut | null>(null);
  const [error,     setError]     = useState("");
  const [loading,   setLoading]   = useState(true);

  useEffect(() => {
    Promise.all([
      getVersionReport(contractId, versionId),
      getApprovalReadiness(contractId, versionId).catch(() => null),
      getClosureBundle(contractId, versionId).catch(() => null),
    ])
      .then(([rep, read, bndl]) => {
        setReport(rep);
        setReadiness(read);
        setBundle(bndl);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [contractId, versionId]);

  if (loading) return <div className="page"><Nav user={user} /><main className="main"><div className="loading">Loading…</div></main></div>;
  if (error)   return <div className="page"><Nav user={user} /><main className="main"><div className="error-box">{error}</div></main></div>;
  if (!report) return null;

  const r        = report.report;
  const meta     = (r.metadata ?? {}) as Metadata;
  const riskDist = (r.risk_distribution ?? []) as RiskItem[];

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}`} className="breadcrumb">← {contractId}</Link>
            <h1>Risk Report — v{versionId}</h1>
          </div>
          <Link href={`/contracts/${contractId}/versions/${versionId}/clauses`} className="btn btn-outline">
            Clause explorer →
          </Link>
          <Link href={`/contracts/${contractId}/versions/${versionId}/findings`} className="btn btn-outline">
            Findings →
          </Link>
          <Link href={`/contracts/${contractId}/versions/${versionId}/negotiation`} className="btn btn-outline">
            Negotiation package →
          </Link>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Overall risk</div>
            <div className="stat-value">
              <span className={riskBadge(meta.overall_risk ?? "")}>{meta.overall_risk ?? "—"}</span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Total clauses</div>
            <div className="stat-value">{meta.total_clauses ?? "—"}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Total findings</div>
            <div className="stat-value">{meta.total_findings ?? "—"}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Risk breakdown</div>
            <div className="stat-value">
              <span className="badge badge--red">H:{meta.high_risk_clauses ?? 0}</span>{" "}
              <span className="badge badge--yellow">M:{meta.medium_risk_clauses ?? 0}</span>{" "}
              <span className="badge badge--green">L:{meta.low_risk_clauses ?? 0}</span>
            </div>
          </div>
        </div>

        {/* Closure bundle — shown first when available (indicates final state) */}
        {bundle && (
          <ClosureBundlePanel
            bundle={bundle}
            contractId={contractId}
            versionId={versionId}
          />
        )}

        {/* Approval readiness panel */}
        {readiness && (
          <ReadinessPanel
            readiness={readiness}
            contractId={contractId}
            versionId={versionId}
          />
        )}

        {meta.frameworks_in_scope && meta.frameworks_in_scope.length > 0 && (
          <div className="section">
            <h2>Frameworks in scope</h2>
            <div className="tag-list">
              {meta.frameworks_in_scope.map((f) => (
                <span key={f} className="tag">{f}</span>
              ))}
            </div>
          </div>
        )}

        {riskDist.length > 0 && (
          <div className="section">
            <h2>Risk findings ({riskDist.length})</h2>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Clause</th><th>Page</th><th>Topic</th>
                    <th>Severity</th><th>Score</th><th>Preview</th>
                  </tr>
                </thead>
                <tbody>
                  {riskDist.map((item, i) => (
                    <tr key={i}>
                      <td>
                        <Link
                          href={`/contracts/${contractId}/versions/${versionId}/clauses/${encodeURIComponent(item.clause_id)}`}
                          className="mono link"
                          title="Open source clause"
                        >
                          {item.clause_id}
                        </Link>
                      </td>
                      <td>{item.page ?? "—"}</td>
                      <td>{item.topic ?? "—"}</td>
                      <td><span className={riskBadge(item.severity ?? "")}>{item.severity ?? "—"}</span></td>
                      <td>{item.risk_score ?? "—"}</td>
                      <td className="preview-cell">{item.text_preview ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default function VersionReportPage({
  params,
}: {
  params: Promise<{ id: string; vid: string }>;
}) {
  const { id, vid } = use(params);
  return (
    <AuthGuard>
      {(user) => (
        <VersionReportContent user={user} contractId={id} versionId={Number(vid)} />
      )}
    </AuthGuard>
  );
}
