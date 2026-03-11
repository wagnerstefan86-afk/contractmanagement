"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import { getReport, ReportOut } from "@/lib/api";

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
  obligation?: string;
  severity?: string;
  risk_score?: number;
  priority?: string;
  text_preview?: string;
  linked_action?: string;
  linked_neg_item?: string;
}

interface Metadata {
  overall_risk?: string;
  total_clauses?: number;
  total_findings?: number;
  high_risk_clauses?: number;
  medium_risk_clauses?: number;
  low_risk_clauses?: number;
  total_actions?: number;
  frameworks_in_scope?: string[];
  organization?: string;
}

function ReportContent({ user, contractId }: { user: SessionUser; contractId: string }) {
  const [report, setReport] = useState<ReportOut | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getReport(contractId)
      .then(setReport)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [contractId]);

  if (loading) return <div className="page"><Nav user={user} /><main className="main"><div className="loading">Loading…</div></main></div>;
  if (error) return <div className="page"><Nav user={user} /><main className="main"><div className="error-box">{error}</div></main></div>;
  if (!report) return null;

  const r = report.report;
  const meta = (r.metadata ?? {}) as Metadata;
  const riskDist = (r.risk_distribution ?? []) as RiskItem[];
  const topRiskAreas = r.top_risk_areas as string[] | undefined;
  const actionPlan = r.action_plan_overview as Record<string, unknown> | undefined;

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}`} className="breadcrumb">← {contractId}</Link>
            <h1>Risk Report</h1>
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

        {/* Top risk areas */}
        {topRiskAreas && topRiskAreas.length > 0 && (
          <div className="section">
            <h2>Top risk areas</h2>
            <ul className="bullet-list">
              {topRiskAreas.map((area, i) => <li key={i}>{area}</li>)}
            </ul>
          </div>
        )}

        {/* Risk distribution table */}
        {riskDist.length > 0 && (
          <div className="section">
            <h2>Risk findings ({riskDist.length})</h2>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Clause</th>
                    <th>Page</th>
                    <th>Topic</th>
                    <th>Severity</th>
                    <th>Score</th>
                    <th>Preview</th>
                  </tr>
                </thead>
                <tbody>
                  {riskDist.map((item, i) => (
                    <tr key={i}>
                      <td className="mono">{item.clause_id}</td>
                      <td>{item.page ?? "—"}</td>
                      <td>{item.topic ?? "—"}</td>
                      <td>
                        <span className={riskBadge(item.severity ?? "")}>
                          {item.severity ?? "—"}
                        </span>
                      </td>
                      <td>{item.risk_score ?? "—"}</td>
                      <td className="preview-cell">{item.text_preview ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Action plan overview */}
        {actionPlan && (
          <div className="section">
            <h2>Action plan overview</h2>
            <pre className="json-block">{JSON.stringify(actionPlan, null, 2)}</pre>
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
