"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  listContracts,
  ContractSummaryOut,
  ReviewStatus,
} from "@/lib/api";

const REVIEW_STATUS_CLASS: Record<ReviewStatus, string> = {
  uploaded:             "badge badge--gray",
  ingested:             "badge badge--gray",
  analysis_completed:   "badge badge--blue",
  under_review:         "badge badge--yellow",
  in_negotiation:       "badge badge--yellow",
  approved:             "badge badge--green",
  rejected:             "badge badge--red",
  archived:             "badge badge--gray",
};

const REVIEW_STATUS_LABEL: Record<ReviewStatus, string> = {
  uploaded:             "Uploaded",
  ingested:             "Ingested",
  analysis_completed:   "Awaiting review",
  under_review:         "Under review",
  in_negotiation:       "In negotiation",
  approved:             "Approved",
  rejected:             "Rejected",
  archived:             "Archived",
};

function riskClass(r: string | null) {
  if (!r) return "badge badge--gray";
  const u = r.toUpperCase();
  if (u === "HIGH")   return "badge badge--red";
  if (u === "MEDIUM") return "badge badge--yellow";
  if (u === "LOW")    return "badge badge--green";
  return "badge badge--gray";
}

function ContractTable({ contracts, emptyMsg }: { contracts: ContractSummaryOut[]; emptyMsg: string }) {
  if (contracts.length === 0) {
    return <div className="empty-state">{emptyMsg}</div>;
  }
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Contract ID</th>
            <th>Filename</th>
            <th>Review status</th>
            <th>Latest risk</th>
            <th>Last analysis</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {contracts.map((c) => (
            <tr key={c.contract_id}>
              <td className="mono">{c.contract_id}</td>
              <td className="filename">{c.filename}</td>
              <td>
                <span className={REVIEW_STATUS_CLASS[c.review_status]}>
                  {REVIEW_STATUS_LABEL[c.review_status]}
                </span>
              </td>
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
    </div>
  );
}

function ReviewsContent({ user }: { user: SessionUser }) {
  const [pending,       setPending]      = useState<ContractSummaryOut[]>([]);
  const [inProgress,    setInProgress]   = useState<ContractSummaryOut[]>([]);
  const [loading,       setLoading]      = useState(true);
  const [error,         setError]        = useState("");

  useEffect(() => {
    Promise.all([
      listContracts(0, 50, { review_status: "analysis_completed" }),
      listContracts(0, 50, { review_status: "under_review" }),
      listContracts(0, 50, { review_status: "in_negotiation" }),
    ])
      .then(([completed, underReview, inNeg]) => {
        setPending(completed.contracts);
        setInProgress([...underReview.contracts, ...inNeg.contracts]);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const totalOpen = pending.length + inProgress.length;

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <h1>Findings &amp; Review Queue</h1>
            <p className="page-subtitle">
              Contracts requiring reviewer action.
            </p>
          </div>
          <Link href="/contracts" className="btn btn-outline">All contracts</Link>
        </div>

        {error && <div className="error-box">{error}</div>}
        {loading && <div className="loading">Loading…</div>}

        {!loading && (
          <>
            <div className="stats-grid" style={{ marginBottom: "1.5rem" }}>
              <div className="stat-card">
                <div className="stat-label">Awaiting review</div>
                <div className="stat-value">
                  <span className={pending.length > 0 ? "badge badge--blue" : "badge badge--gray"}>
                    {pending.length}
                  </span>
                </div>
              </div>
              <div className="stat-card">
                <div className="stat-label">In progress</div>
                <div className="stat-value">
                  <span className={inProgress.length > 0 ? "badge badge--yellow" : "badge badge--gray"}>
                    {inProgress.length}
                  </span>
                </div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Total open</div>
                <div className="stat-value">{totalOpen}</div>
              </div>
            </div>

            <div className="section">
              <div className="section-header">
                <h2>Awaiting review <span className="count">({pending.length})</span></h2>
                <span className="section-meta">Analysis complete — reviewer action required</span>
              </div>
              <ContractTable
                contracts={pending}
                emptyMsg="No contracts awaiting review."
              />
            </div>

            <div className="section" style={{ marginTop: "2rem" }}>
              <div className="section-header">
                <h2>In progress <span className="count">({inProgress.length})</span></h2>
                <span className="section-meta">Under review or in negotiation</span>
              </div>
              <ContractTable
                contracts={inProgress}
                emptyMsg="No contracts currently under review."
              />
            </div>
          </>
        )}
      </main>
    </div>
  );
}

export default function ReviewsPage() {
  return <AuthGuard>{(user) => <ReviewsContent user={user} />}</AuthGuard>;
}
