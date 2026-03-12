"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import { getReport, ReportOut } from "@/lib/api";

function riskBadge(severity: string) {
  const s = (severity ?? "").toUpperCase();
  if (s === "HIGH")   return "badge badge--red";
  if (s === "MEDIUM") return "badge badge--yellow";
  if (s === "LOW")    return "badge badge--green";
  return "badge badge--gray";
}

interface RiskItem {
  clause_id:        string;
  page?:            number;
  topic?:           string;
  obligation?:      string;
  severity?:        string;
  risk_score?:      number;
  priority?:        string;
  text_preview?:    string;
  linked_action?:   string;
  linked_neg_item?: string;
}

interface ActionItem {
  action_id?:          string;
  action_type?:        string;
  priority?:           string;
  finding_type?:       string;
  topic?:              string;
  obligation?:         string;
  recommended_action?: string;
  affected_clause?:    string;
}

interface Metadata {
  overall_risk?:        string;
  total_clauses?:       number;
  total_findings?:      number;
  high_risk_clauses?:   number;
  medium_risk_clauses?: number;
  low_risk_clauses?:    number;
  total_actions?:       number;
  frameworks_in_scope?: string[];
  organization?:        string;
}

function ReportContent({ user, contractId }: { user: SessionUser; contractId: string }) {
  const [report,  setReport]  = useState<ReportOut | null>(null);
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getReport(contractId)
      .then(setReport)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [contractId]);

  if (loading) return <div className="page"><Nav user={user} /><main className="main"><div className="loading">Loading…</div></main></div>;
  if (error)   return <div className="page"><Nav user={user} /><main className="main"><div className="error-box">{error}</div></main></div>;
  if (!report) return null;

  const r            = report.report;
  const meta         = (r.metadata ?? {}) as Metadata;
  const riskDist     = (r.risk_distribution ?? []) as RiskItem[];
  const topRiskAreas = r.top_risk_areas as string[] | undefined;
  const actionPlan   = r.action_plan_overview as Record<string, unknown> | undefined;

  const actionItems: ActionItem[] = (() => {
    if (!actionPlan) return [];
    const items = actionPlan.actions ?? actionPlan.items ?? actionPlan.action_items;
    if (Array.isArray(items)) return items as ActionItem[];
    return [];
  })();

  const sortedRisk = [...riskDist].sort((a, b) => {
    const order: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };
    return (order[(a.severity ?? "").toUpperCase()] ?? 3) - (order[(b.severity ?? "").toUpperCase()] ?? 3);
  });

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}`} className="breadcrumb">← {contractId}</Link>
            <h1>Risk Report</h1>
            {meta.organization && <p className="page-subtitle">{meta.organization}</p>}
          </div>
          <Link href={`/contracts/${contractId}/negotiation`} className="btn btn-outline">
            Negotiation package →
          </Link>
        </div>

        {/* Summary stats */}
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Overall risk</div>
            <div className="stat-value">
              <span className={riskBadge(meta.overall_risk ?? "")}>{meta.overall_risk ?? "—"}</span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Risk breakdown</div>
            <div className="stat-value">
              <span className="badge badge--red">H:{meta.high_risk_clauses ?? 0}</span>{" "}
              <span className="badge badge--yellow">M:{meta.medium_risk_clauses ?? 0}</span>{" "}
              <span className="badge badge--green">L:{meta.low_risk_clauses ?? 0}</span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Total findings</div>
            <div className="stat-value">{meta.total_findings ?? "—"}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Actions required</div>
            <div className="stat-value">{(meta.total_actions ?? actionItems.length) || "—"}</div>
          </div>
        </div>

        {/* Frameworks */}
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

        {/* Key risk areas — actionable list */}
        {topRiskAreas && topRiskAreas.length > 0 && (
          <div className="section">
            <h2>Key risk areas requiring attention</h2>
            <div style={{ display: "grid", gap: "0.5rem" }}>
              {topRiskAreas.map((area, i) => (
                <div key={i} className="info-box" style={{ margin: 0 }}>{area}</div>
              ))}
            </div>
          </div>
        )}

        {/* Risk findings — sorted HIGH first, with recommended action column */}
        {sortedRisk.length > 0 && (
          <div className="section">
            <h2>Risk findings ({sortedRisk.length})</h2>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Clause</th>
                    <th>Page</th>
                    <th>Framework topic</th>
                    <th>Severity</th>
                    <th>Score</th>
                    <th>Recommended action</th>
                    <th>Preview</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedRisk.map((item, i) => (
                    <tr key={i}>
                      <td className="mono">{item.clause_id}</td>
                      <td>{item.page ?? "—"}</td>
                      <td>{item.topic ?? item.obligation ?? "—"}</td>
                      <td><span className={riskBadge(item.severity ?? "")}>{item.severity ?? "—"}</span></td>
                      <td>{item.risk_score ?? "—"}</td>
                      <td className="preview-cell">
                        {item.linked_action
                          ? <span style={{ color: "var(--color-primary)" }}>{item.linked_action}</span>
                          : <span className="text-muted">—</span>}
                      </td>
                      <td className="preview-cell">{item.text_preview ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Action plan */}
        {actionPlan && (
          <div className="section">
            <h2>Action plan</h2>
            {actionItems.length > 0 ? (
              <div style={{ display: "grid", gap: "0.75rem" }}>
                {actionItems.map((item, i) => (
                  <div key={i} style={{ padding: "0.75rem", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "0.5rem" }}>
                    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.25rem" }}>
                      {item.action_id && <span className="mono" style={{ fontSize: "0.8rem" }}>{item.action_id}</span>}
                      {item.priority && <span className={riskBadge(item.priority)}>{item.priority}</span>}
                      {item.topic && <span className="tag">{item.topic}</span>}
                      {item.finding_type && <span className="tag">{item.finding_type.replace(/_/g, " ")}</span>}
                    </div>
                    {item.obligation && <p style={{ margin: "0.25rem 0", fontSize: "0.9rem" }}>{item.obligation}</p>}
                    {item.recommended_action && (
                      <div className="info-box" style={{ margin: "0.25rem 0 0" }}>
                        <strong>Action:</strong> {item.recommended_action}
                      </div>
                    )}
                    {item.affected_clause && (
                      <p style={{ fontSize: "0.8rem", color: "var(--color-muted)", marginTop: "0.25rem" }}>
                        Clause: <span className="mono">{item.affected_clause}</span>
                      </p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <details>
                <summary style={{ cursor: "pointer", color: "var(--color-primary)", fontSize: "0.85rem" }}>
                  Show raw action plan data
                </summary>
                <pre className="json-block" style={{ marginTop: "0.5rem" }}>{JSON.stringify(actionPlan, null, 2)}</pre>
              </details>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <AuthGuard>{(user) => <ReportContent user={user} contractId={id} />}</AuthGuard>;
}
