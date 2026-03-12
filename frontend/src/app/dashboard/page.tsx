"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  getMe,
  listContracts,
  getRiskSummary,
  getOrgProfile,
  MeOut,
  ContractSummaryOut,
  OrgProfile,
  RiskSummaryOut,
} from "@/lib/api";

function riskClass(risk: string | null) {
  if (risk === "HIGH")   return "badge badge--red";
  if (risk === "MEDIUM") return "badge badge--yellow";
  if (risk === "LOW")    return "badge badge--green";
  return "badge badge--gray";
}

function BarChart({
  rows,
  valueKey,
  labelKey,
  colorClass = "bar-fill--primary",
  emptyMsg = "No data yet.",
}: {
  rows:        Record<string, string | number>[];
  valueKey:    string;
  labelKey:    string;
  colorClass?: string;
  emptyMsg?:   string;
}) {
  if (rows.length === 0) return <div className="chart-empty">{emptyMsg}</div>;
  const max = Math.max(...rows.map((r) => Number(r[valueKey]))) || 1;
  return (
    <div className="bar-chart">
      {rows.map((row, i) => {
        const val = Number(row[valueKey]);
        const pct = Math.round((val / max) * 100);
        const label = String(row[labelKey])
          .toLowerCase().replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
        return (
          <div key={i} className="bar-row">
            <div className="bar-label" title={label}>{label}</div>
            <div className="bar-track">
              <div className={`bar-fill ${colorClass}`} style={{ width: `${pct}%` }} />
            </div>
            <div className="bar-value">{val}</div>
          </div>
        );
      })}
    </div>
  );
}

function ReviewQueueTable({ contracts }: { contracts: ContractSummaryOut[] }) {
  if (contracts.length === 0) {
    return (
      <div className="empty-state">
        No contracts awaiting review.{" "}
        <Link href="/contracts" className="link">View all contracts →</Link>
      </div>
    );
  }
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Contract ID</th>
          <th>File</th>
          <th>Latest risk</th>
          <th>Analysis date</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {contracts.map((c) => (
          <tr key={c.contract_id}>
            <td className="mono">{c.contract_id}</td>
            <td className="filename">{c.filename}</td>
            <td>
              {c.latest_overall_risk
                ? <span className={riskClass(c.latest_overall_risk)}>{c.latest_overall_risk}</span>
                : <span className="text-muted">—</span>}
            </td>
            <td className="text-muted">
              {c.latest_analysis_at
                ? new Date(c.latest_analysis_at).toLocaleDateString()
                : "—"}
            </td>
            <td>
              <Link href={`/contracts/${c.contract_id}`} className="btn btn-sm btn-primary">
                Review →
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DashboardContent({ user }: { user: SessionUser }) {
  const [me,          setMe]          = useState<MeOut | null>(null);
  const [pending,     setPending]     = useState<ContractSummaryOut[]>([]);
  const [inReview,    setInReview]    = useState<ContractSummaryOut[]>([]);
  const [recent,      setRecent]      = useState<ContractSummaryOut[]>([]);
  const [risk,        setRisk]        = useState<RiskSummaryOut | null>(null);
  const [orgProfile,  setOrgProfile]  = useState<OrgProfile | null | undefined>(undefined);
  const [error,       setError]       = useState("");

  useEffect(() => {
    Promise.all([
      getMe(),
      listContracts(0, 10, { review_status: "analysis_completed" }),
      listContracts(0, 10, { review_status: "under_review" }),
      listContracts(0, 5),
      getRiskSummary().catch(() => null),
      getOrgProfile().catch(() => null),
    ])
      .then(([meData, pendingData, inReviewData, recentData, riskData, profileData]) => {
        setMe(meData);
        setPending(pendingData.contracts);
        setInReview(inReviewData.contracts);
        setRecent(recentData.contracts);
        setRisk(riskData);
        setOrgProfile(profileData);
      })
      .catch((err) => setError(err.message));
  }, []);

  const hasRiskData  = risk !== null && risk.analyses_completed > 0;
  const openCount    = pending.length + inReview.length;

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">

        <div className="page-header">
          <div>
            <h1>Dashboard</h1>
            <p className="page-subtitle">Internal AI-assisted InfoSec contract review workspace</p>
          </div>
        </div>

        {error && <div className="error-box">{error}</div>}

        {orgProfile === null && (
          <div className="warn-box" style={{ marginBottom: "1rem" }}>
            <strong>Compliance profile not configured.</strong>{" "}
            Analysis cannot run until a profile is set up.{" "}
            {user.role === "ADMIN"
              ? <Link href="/settings/customer-profile">Configure profile →</Link>
              : "Contact your ADMIN."}
          </div>
        )}

        {/* ── Open review work ─────────────────────────────────────────────── */}
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Awaiting review</div>
            <div className="stat-value">
              <span className={pending.length > 0 ? "badge badge--blue" : "badge badge--gray"}>
                {pending.length}
              </span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Under review</div>
            <div className="stat-value">
              <span className={inReview.length > 0 ? "badge badge--yellow" : "badge badge--gray"}>
                {inReview.length}
              </span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">High risk contracts</div>
            <div className="stat-value">
              <span className={risk && risk.high_risk_contracts > 0 ? "badge badge--red" : "badge badge--gray"}>
                {risk?.high_risk_contracts ?? "—"}
              </span>
            </div>
          </div>
          <div className="stat-card stat-card--split">
            <div className="stat-label">Risk breakdown</div>
            <div className="stat-risk-row">
              <span className="stat-risk stat-risk--high">{risk?.high_risk_contracts ?? 0} HIGH</span>
              <span className="stat-risk stat-risk--med">{risk?.medium_risk_contracts ?? 0} MED</span>
              <span className="stat-risk stat-risk--low">{risk?.low_risk_contracts ?? 0} LOW</span>
            </div>
          </div>
        </div>

        {/* ── Pending review queue ──────────────────────────────────────────── */}
        <div className="section" style={{ marginTop: "1.5rem" }}>
          <div className="section-header">
            <h2>
              Awaiting reviewer action{" "}
              <span className="count">({openCount})</span>
            </h2>
            <Link href="/reviews" className="btn btn-sm btn-outline">
              Full review queue →
            </Link>
          </div>
          {pending.length > 0 ? (
            <ReviewQueueTable contracts={pending} />
          ) : (
            <div className="empty-state">
              No contracts awaiting review.{" "}
              {inReview.length > 0 && (
                <Link href="/reviews" className="link">{inReview.length} contract{inReview.length !== 1 ? "s" : ""} currently under review →</Link>
              )}
            </div>
          )}
        </div>

        {/* ── Risk Intelligence ─────────────────────────────────────────────── */}
        {hasRiskData && (
          <>
            <div className="section-divider" />
            <div className="section-header" style={{ marginBottom: "1.25rem" }}>
              <h2>Risk Intelligence</h2>
              <span className="section-meta">
                {risk!.analyses_completed} completed {risk!.analyses_completed === 1 ? "analysis" : "analyses"} across {risk!.total_contracts} {risk!.total_contracts === 1 ? "contract" : "contracts"}
              </span>
            </div>

            <div className="charts-grid">
              <div className="chart-card">
                <h3 className="chart-title">Top Risk Topics</h3>
                <p className="chart-desc">Clauses flagged per compliance topic</p>
                <BarChart
                  rows={risk!.top_risk_topics as unknown as Record<string, string | number>[]}
                  labelKey="topic" valueKey="count" colorClass="bar-fill--danger"
                  emptyMsg="No topic data yet."
                />
              </div>
              <div className="chart-card">
                <h3 className="chart-title">Regulatory Framework Exposure</h3>
                <p className="chart-desc">Findings matched per framework</p>
                <BarChart
                  rows={risk!.top_regulatory_frameworks as unknown as Record<string, string | number>[]}
                  labelKey="framework" valueKey="issues" colorClass="bar-fill--warning"
                  emptyMsg="No framework exposure data yet."
                />
              </div>
              <div className="chart-card chart-card--full">
                <h3 className="chart-title">Most Common Finding Types</h3>
                <p className="chart-desc">Frequency by affected clauses across all contracts</p>
                <BarChart
                  rows={risk!.most_common_finding_types as unknown as Record<string, string | number>[]}
                  labelKey="finding_type" valueKey="count" colorClass="bar-fill--primary"
                  emptyMsg="No finding data yet."
                />
              </div>
            </div>
          </>
        )}

        {/* ── Recent uploads ────────────────────────────────────────────────── */}
        <div className="section" style={{ marginTop: "2rem" }}>
          <div className="section-header">
            <h2>Recent uploads</h2>
            <Link href="/contracts" className="btn btn-sm btn-outline">View all</Link>
          </div>
          {recent.length === 0 ? (
            <div className="empty-state">
              No contracts yet.{" "}
              {(user.role === "ADMIN" || user.role === "ANALYST") && (
                <Link href="/contracts/upload">Upload your first contract →</Link>
              )}
            </div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Contract ID</th>
                  <th>Filename</th>
                  <th>Risk</th>
                  <th>Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((c) => (
                  <tr key={c.contract_id}>
                    <td>
                      <Link href={`/contracts/${c.contract_id}`} className="link">{c.contract_id}</Link>
                    </td>
                    <td className="filename">{c.filename}</td>
                    <td>
                      {c.latest_overall_risk
                        ? <span className={riskClass(c.latest_overall_risk)}>{c.latest_overall_risk}</span>
                        : <span className="text-muted">—</span>}
                    </td>
                    <td>{new Date(c.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="dash-footer">
          Signed in as <strong>{me?.name}</strong> ({me?.email}) · <span className="dash-role">{me?.role}</span>
        </div>
      </main>
    </div>
  );
}

export default function DashboardPage() {
  return <AuthGuard>{(user) => <DashboardContent user={user} />}</AuthGuard>;
}
