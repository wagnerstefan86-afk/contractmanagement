"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  getMe,
  getMyCustomer,
  listContracts,
  getRiskSummary,
  getOrgProfile,
  MeOut,
  CustomerOut,
  ContractOut,
  OrgProfile,
  RiskSummaryOut,
  RiskTopicItem,
  RegulatoryFwItem,
  FindingTypeItem,
  ContractRiskItem,
} from "@/lib/api";

// ── Utilities ──────────────────────────────────────────────────────────────────

function toLabel(key: string): string {
  return key
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function riskClass(risk: string) {
  if (risk === "HIGH")   return "badge badge--red";
  if (risk === "MEDIUM") return "badge badge--yellow";
  if (risk === "LOW")    return "badge badge--green";
  return "badge badge--gray";
}

function statusClass(status: string) {
  if (status === "analyzed") return "badge badge--green";
  if (status === "failed")   return "badge badge--red";
  if (status === "ingested") return "badge badge--blue";
  return "badge badge--gray";
}

// ── Bar chart ─────────────────────────────────────────────────────────────────

function BarChart({
  rows,
  valueKey,
  labelKey,
  colorClass = "bar-fill--primary",
  emptyMsg = "No data yet.",
}: {
  rows:       Record<string, string | number>[];
  valueKey:   string;
  labelKey:   string;
  colorClass?: string;
  emptyMsg?:  string;
}) {
  if (rows.length === 0) {
    return <div className="chart-empty">{emptyMsg}</div>;
  }
  const max = Math.max(...rows.map((r) => Number(r[valueKey]))) || 1;
  return (
    <div className="bar-chart">
      {rows.map((row, i) => {
        const val = Number(row[valueKey]);
        const pct = Math.round((val / max) * 100);
        return (
          <div key={i} className="bar-row">
            <div className="bar-label" title={String(row[labelKey])}>
              {toLabel(String(row[labelKey]))}
            </div>
            <div className="bar-track">
              <div
                className={`bar-fill ${colorClass}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="bar-value">{val}</div>
          </div>
        );
      })}
    </div>
  );
}

// ── Risk score gauge ──────────────────────────────────────────────────────────

function RiskScoreBadge({ score }: { score: number }) {
  const pct   = Math.min(100, Math.round((score / 10) * 100));
  const color = score >= 7 ? "var(--color-danger)"
              : score >= 4 ? "var(--color-warning)"
              :               "var(--color-success)";
  return (
    <div className="risk-gauge">
      <div className="risk-gauge-track">
        <div
          className="risk-gauge-fill"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="risk-gauge-label" style={{ color }}>{score.toFixed(1)}</span>
    </div>
  );
}

// ── Contracts by risk table ───────────────────────────────────────────────────

function ContractsByRisk({ contracts }: { contracts: ContractRiskItem[] }) {
  if (contracts.length === 0) {
    return <div className="chart-empty">No completed analyses yet.</div>;
  }
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Contract ID</th>
          <th>File</th>
          <th>Risk</th>
          <th>Score</th>
          <th>Findings</th>
          <th>High-risk clauses</th>
          <th>Analysed</th>
        </tr>
      </thead>
      <tbody>
        {contracts.map((c) => (
          <tr key={c.contract_id}>
            <td>
              <Link href={`/contracts/${c.contract_id}`} className="link">
                {c.contract_id}
              </Link>
            </td>
            <td className="filename">{c.filename}</td>
            <td><span className={riskClass(c.overall_risk)}>{c.overall_risk}</span></td>
            <td><RiskScoreBadge score={c.risk_score} /></td>
            <td>{c.total_findings}</td>
            <td>{c.high_risk_clauses}</td>
            <td>
              {c.completed_at
                ? new Date(c.completed_at).toLocaleDateString()
                : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Main dashboard ─────────────────────────────────────────────────────────────

function DashboardContent({ user }: { user: SessionUser }) {
  const [me,         setMe]         = useState<MeOut | null>(null);
  const [customer,   setCustomer]   = useState<CustomerOut | null>(null);
  const [recent,     setRecent]     = useState<ContractOut[]>([]);
  const [total,      setTotal]      = useState(0);
  const [risk,       setRisk]       = useState<RiskSummaryOut | null>(null);
  const [orgProfile, setOrgProfile] = useState<OrgProfile | null | undefined>(undefined); // undefined = loading
  const [error,      setError]      = useState("");

  useEffect(() => {
    Promise.all([
      getMe(),
      getMyCustomer(),
      listContracts(0, 5),
      getRiskSummary().catch(() => null),
      getOrgProfile().catch(() => null),
    ])
      .then(([meData, custData, listData, riskData, profileData]) => {
        setMe(meData);
        setCustomer(custData);
        setRecent(listData.contracts);
        setTotal(listData.total);
        setRisk(riskData);
        setOrgProfile(profileData);
      })
      .catch((err) => setError(err.message));
  }, []);

  const hasRiskData = risk !== null && risk.analyses_completed > 0;

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">

        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="page-header">
          <h1>Dashboard</h1>
          {customer?.name && (
            <span className="dash-tenant">{customer.name}</span>
          )}
        </div>

        {error && <div className="error-box">{error}</div>}

        {/* ── No compliance profile warning ────────────────────────────────── */}
        {orgProfile === null && (
          <div className="warn-box" style={{ marginBottom: "1rem" }}>
            <strong>Compliance profile not configured.</strong>{" "}
            Analysis cannot be started on any contract until a profile is set up.{" "}
            {(user.role === "ADMIN") ? (
              <Link href="/settings/customer-profile">Configure profile →</Link>
            ) : (
              "Contact your ADMIN to configure the compliance profile."
            )}
          </div>
        )}

        {/* ── Overview stat cards ─────────────────────────────────────────── */}
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Total contracts</div>
            <div className="stat-value">{total}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Analyses completed</div>
            <div className="stat-value">{risk?.analyses_completed ?? "—"}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Avg clause risk score</div>
            <div className="stat-value">
              {risk ? `${risk.average_risk_score} / 10` : "—"}
            </div>
          </div>
          <div className="stat-card stat-card--split">
            <div>
              <div className="stat-label">Risk breakdown</div>
              <div className="stat-risk-row">
                <span className="stat-risk stat-risk--high">
                  {risk?.high_risk_contracts ?? 0} HIGH
                </span>
                <span className="stat-risk stat-risk--med">
                  {risk?.medium_risk_contracts ?? 0} MED
                </span>
                <span className="stat-risk stat-risk--low">
                  {risk?.low_risk_contracts ?? 0} LOW
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* ── Risk Intelligence ───────────────────────────────────────────── */}
        {hasRiskData ? (
          <>
            <div className="section-divider" />

            <div className="section-header" style={{ marginBottom: "1.25rem" }}>
              <h2>Risk Intelligence</h2>
              <span className="section-meta">
                Based on {risk!.analyses_completed} completed{" "}
                {risk!.analyses_completed === 1 ? "analysis" : "analyses"} across{" "}
                {risk!.total_contracts}{" "}
                {risk!.total_contracts === 1 ? "contract" : "contracts"}
              </span>
            </div>

            {/* Charts grid — two columns on wide screens */}
            <div className="charts-grid">
              <div className="chart-card">
                <h3 className="chart-title">Top Risk Topics</h3>
                <p className="chart-desc">
                  Clauses flagged per compliance topic
                </p>
                <BarChart
                  rows={risk!.top_risk_topics as unknown as Record<string, string | number>[]}
                  labelKey="topic"
                  valueKey="count"
                  colorClass="bar-fill--danger"
                  emptyMsg="No topic data yet."
                />
              </div>

              <div className="chart-card">
                <h3 className="chart-title">Regulatory Framework Exposure</h3>
                <p className="chart-desc">
                  Clauses matching each framework across all contracts
                </p>
                <BarChart
                  rows={risk!.top_regulatory_frameworks as unknown as Record<string, string | number>[]}
                  labelKey="framework"
                  valueKey="issues"
                  colorClass="bar-fill--warning"
                  emptyMsg="No framework exposure data yet."
                />
              </div>

              <div className="chart-card chart-card--full">
                <h3 className="chart-title">Most Common Finding Types</h3>
                <p className="chart-desc">
                  Frequency of each finding type (by affected clauses) across all contracts
                </p>
                <BarChart
                  rows={risk!.most_common_finding_types as unknown as Record<string, string | number>[]}
                  labelKey="finding_type"
                  valueKey="count"
                  colorClass="bar-fill--primary"
                  emptyMsg="No finding data yet."
                />
              </div>
            </div>

            {/* ── Contracts by risk table ─────────────────────────────────── */}
            <div className="section" style={{ marginTop: "1.5rem" }}>
              <div className="section-header">
                <h2>Contracts by Risk</h2>
                <Link href="/contracts" className="btn btn-sm btn-outline">
                  View all contracts
                </Link>
              </div>
              <ContractsByRisk contracts={risk!.contracts_by_risk} />
            </div>
          </>
        ) : (
          !error && (
            <div className="empty-state" style={{ marginTop: "1.5rem" }}>
              No completed analyses yet.{" "}
              {(user.role === "ADMIN" || user.role === "ANALYST") && (
                <>
                  <Link href="/contracts/upload">Upload a contract</Link> and run
                  analysis to see risk intelligence.
                </>
              )}
            </div>
          )
        )}

        {/* ── Recent contracts ────────────────────────────────────────────── */}
        <div className="section" style={{ marginTop: "2rem" }}>
          <div className="section-header">
            <h2>Recent uploads</h2>
            <Link href="/contracts" className="btn btn-sm btn-outline">
              View all
            </Link>
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
                  <th>Status</th>
                  <th>Clauses</th>
                  <th>Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((c) => (
                  <tr key={c.contract_id}>
                    <td>
                      <Link
                        href={`/contracts/${c.contract_id}`}
                        className="link"
                      >
                        {c.contract_id}
                      </Link>
                    </td>
                    <td className="filename">{c.filename}</td>
                    <td>
                      <span className={statusClass(c.status)}>{c.status}</span>
                    </td>
                    <td>{c.clauses_extracted ?? "—"}</td>
                    <td>{new Date(c.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* ── User info footer ─────────────────────────────────────────────── */}
        <div className="dash-footer">
          Signed in as <strong>{me?.name}</strong> ({me?.email}) ·{" "}
          <span className="dash-role">{me?.role}</span>
        </div>
      </main>
    </div>
  );
}

export default function DashboardPage() {
  return <AuthGuard>{(user) => <DashboardContent user={user} />}</AuthGuard>;
}
