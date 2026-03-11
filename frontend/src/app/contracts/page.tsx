"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  listContracts,
  ContractSummaryOut,
  ReviewStatus,
  ReviewDecision,
} from "@/lib/api";

const PAGE_SIZE = 20;

// ── Badge helpers ─────────────────────────────────────────────────────────────

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
  analysis_completed:   "Analysis done",
  under_review:         "Under review",
  in_negotiation:       "In negotiation",
  approved:             "Approved",
  rejected:             "Rejected",
  archived:             "Archived",
};

const DECISION_CLASS: Record<ReviewDecision, string> = {
  none:                "badge badge--gray",
  approve:             "badge badge--green",
  conditional_approve: "badge badge--yellow",
  reject:              "badge badge--red",
};

const DECISION_LABEL: Record<ReviewDecision, string> = {
  none:                "—",
  approve:             "Approve",
  conditional_approve: "Conditional",
  reject:              "Reject",
};

function riskClass(r: string | null) {
  if (!r) return "badge badge--gray";
  const u = r.toUpperCase();
  if (u === "HIGH")   return "badge badge--red";
  if (u === "MEDIUM") return "badge badge--yellow";
  if (u === "LOW")    return "badge badge--green";
  return "badge badge--gray";
}

// ── Filter bar ────────────────────────────────────────────────────────────────

const REVIEW_STATUSES: ReviewStatus[] = [
  "uploaded", "ingested", "analysis_completed",
  "under_review", "in_negotiation", "approved", "rejected", "archived",
];
const REVIEW_DECISIONS: ReviewDecision[] = [
  "none", "approve", "conditional_approve", "reject",
];

function FilterBar({
  reviewStatus,
  reviewDecision,
  onReviewStatus,
  onReviewDecision,
  onClear,
}: {
  reviewStatus:     ReviewStatus | "";
  reviewDecision:   ReviewDecision | "";
  onReviewStatus:   (v: ReviewStatus | "") => void;
  onReviewDecision: (v: ReviewDecision | "") => void;
  onClear:          () => void;
}) {
  const hasFilter = reviewStatus !== "" || reviewDecision !== "";
  return (
    <div className="filter-bar">
      <select
        className="filter-select"
        value={reviewStatus}
        onChange={(e) => onReviewStatus(e.target.value as ReviewStatus | "")}
        aria-label="Filter by review status"
      >
        <option value="">All review statuses</option>
        {REVIEW_STATUSES.map((s) => (
          <option key={s} value={s}>{REVIEW_STATUS_LABEL[s]}</option>
        ))}
      </select>

      <select
        className="filter-select"
        value={reviewDecision}
        onChange={(e) => onReviewDecision(e.target.value as ReviewDecision | "")}
        aria-label="Filter by decision"
      >
        <option value="">All decisions</option>
        {REVIEW_DECISIONS.map((d) => (
          <option key={d} value={d}>{DECISION_LABEL[d]}</option>
        ))}
      </select>

      {hasFilter && (
        <button className="btn btn-sm btn-outline" onClick={onClear}>
          Clear filters
        </button>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

function ContractsContent({ user }: { user: SessionUser }) {
  const [contracts,      setContracts]      = useState<ContractSummaryOut[]>([]);
  const [total,          setTotal]          = useState(0);
  const [skip,           setSkip]           = useState(0);
  const [loading,        setLoading]        = useState(true);
  const [error,          setError]          = useState("");
  const [reviewStatus,   setReviewStatus]   = useState<ReviewStatus | "">("");
  const [reviewDecision, setReviewDecision] = useState<ReviewDecision | "">("");

  const load = useCallback((s: number, rs: ReviewStatus | "", rd: ReviewDecision | "") => {
    setLoading(true);
    setError("");
    listContracts(s, PAGE_SIZE, {
      review_status:   rs || undefined,
      review_decision: rd || undefined,
    })
      .then(({ contracts, total }) => {
        setContracts(contracts);
        setTotal(total);
        setSkip(s);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(0, "", ""); }, [load]);

  function applyFilter(rs: ReviewStatus | "", rd: ReviewDecision | "") {
    setReviewStatus(rs);
    setReviewDecision(rd);
    load(0, rs, rd);
  }

  const pages = Math.ceil(total / PAGE_SIZE);
  const page  = Math.floor(skip / PAGE_SIZE) + 1;

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <h1>Contracts <span className="count">({total})</span></h1>
          {(user.role === "ADMIN" || user.role === "ANALYST") && (
            <Link href="/contracts/upload" className="btn btn-primary">Upload contract</Link>
          )}
        </div>

        <FilterBar
          reviewStatus={reviewStatus}
          reviewDecision={reviewDecision}
          onReviewStatus={(v)   => applyFilter(v, reviewDecision)}
          onReviewDecision={(v) => applyFilter(reviewStatus, v)}
          onClear={() => applyFilter("", "")}
        />

        {error && <div className="error-box">{error}</div>}

        {loading ? (
          <div className="loading">Loading…</div>
        ) : contracts.length === 0 ? (
          <div className="empty-state">
            No contracts found.{" "}
            {(user.role === "ADMIN" || user.role === "ANALYST") && (
              <Link href="/contracts/upload">Upload your first contract →</Link>
            )}
          </div>
        ) : (
          <>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Contract ID</th>
                    <th>Filename</th>
                    <th>Versions</th>
                    <th>Review status</th>
                    <th>Decision</th>
                    <th>Latest risk</th>
                    <th>Last analysis</th>
                    <th>Uploaded</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {contracts.map((c) => (
                    <tr key={c.contract_id} className={c.review_status === "archived" ? "row--archived" : ""}>
                      <td className="mono">{c.contract_id}</td>
                      <td className="filename">{c.filename}</td>
                      <td className="text-muted">
                        <span className="version-tag">
                          {c.current_version_number != null
                            ? `v${c.current_version_number}`
                            : "v1"}
                          {c.version_count > 1 && (
                            <span className="version-count"> ({c.version_count})</span>
                          )}
                        </span>
                      </td>
                      <td>
                        <span className={REVIEW_STATUS_CLASS[c.review_status]}>
                          {REVIEW_STATUS_LABEL[c.review_status]}
                        </span>
                      </td>
                      <td>
                        {c.review_decision !== "none" ? (
                          <span className={DECISION_CLASS[c.review_decision]}>
                            {DECISION_LABEL[c.review_decision]}
                          </span>
                        ) : <span className="text-muted">—</span>}
                      </td>
                      <td>
                        {c.latest_overall_risk ? (
                          <span className={riskClass(c.latest_overall_risk)}>
                            {c.latest_overall_risk}
                          </span>
                        ) : <span className="text-muted">—</span>}
                      </td>
                      <td className="text-muted">
                        {c.latest_analysis_at
                          ? new Date(c.latest_analysis_at).toLocaleDateString()
                          : "—"}
                      </td>
                      <td className="text-muted">
                        {new Date(c.created_at).toLocaleDateString()}
                      </td>
                      <td>
                        <Link href={`/contracts/${c.contract_id}`} className="btn btn-sm btn-outline">
                          View
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {pages > 1 && (
              <div className="pagination">
                <button
                  className="btn btn-sm btn-outline"
                  disabled={page === 1}
                  onClick={() => load(skip - PAGE_SIZE, reviewStatus, reviewDecision)}
                >← Prev</button>
                <span>Page {page} of {pages}</span>
                <button
                  className="btn btn-sm btn-outline"
                  disabled={page === pages}
                  onClick={() => load(skip + PAGE_SIZE, reviewStatus, reviewDecision)}
                >Next →</button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

export default function ContractsPage() {
  return <AuthGuard>{(user) => <ContractsContent user={user} />}</AuthGuard>;
}
