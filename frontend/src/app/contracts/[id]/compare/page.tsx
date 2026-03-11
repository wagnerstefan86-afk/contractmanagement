"use client";

import { Suspense, use, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  compareVersions,
  listVersions,
  CompareVersionOut,
  ContractVersionOut,
  ApiError,
} from "@/lib/api";

// ── Badge helpers ─────────────────────────────────────────────────────────────

function riskClass(r: string | null) {
  if (!r) return "badge badge--gray";
  const u = r.toUpperCase();
  if (u === "HIGH")   return "badge badge--red";
  if (u === "MEDIUM") return "badge badge--yellow";
  if (u === "LOW")    return "badge badge--green";
  return "badge badge--gray";
}

function deltaClass(n: number) {
  if (n > 0)  return "delta delta--worse";
  if (n < 0)  return "delta delta--better";
  return "delta delta--same";
}

function deltaLabel(n: number) {
  if (n > 0) return `+${n}`;
  if (n < 0) return `${n}`;
  return "±0";
}

// ── CompareContent ────────────────────────────────────────────────────────────

function CompareContent({
  user,
  contractId,
}: {
  user:       SessionUser;
  contractId: string;
}) {
  const searchParams = useSearchParams();
  const initFrom = Number(searchParams.get("from") ?? "1");
  const initTo   = Number(searchParams.get("to")   ?? "2");

  const [versions,   setVersions]   = useState<ContractVersionOut[]>([]);
  const [fromVer,    setFromVer]    = useState(initFrom);
  const [toVer,      setToVer]      = useState(initTo);
  const [result,     setResult]     = useState<CompareVersionOut | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [comparing,  setComparing]  = useState(false);
  const [error,      setError]      = useState("");

  // Load versions list once
  useEffect(() => {
    listVersions(contractId)
      .then((r) => setVersions(r.versions))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [contractId]);

  // Run comparison when from/to are valid
  async function runCompare() {
    if (fromVer === toVer) {
      setError("Select two different versions to compare.");
      return;
    }
    setError("");
    setComparing(true);
    try {
      const r = await compareVersions(contractId, fromVer, toVer);
      setResult(r);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Comparison failed.");
    } finally {
      setComparing(false);
    }
  }

  // Auto-run on initial load once versions are fetched
  useEffect(() => {
    if (!loading && versions.length >= 2) {
      runCompare();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">

        {/* Header */}
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}`} className="breadcrumb">
              ← Contract detail
            </Link>
            <h1>Compare versions</h1>
          </div>
        </div>

        {/* Version selector */}
        <div className="compare-selector">
          <label className="form-label">From version</label>
          <select
            className="filter-select"
            value={fromVer}
            onChange={(e) => setFromVer(Number(e.target.value))}
            disabled={comparing}
          >
            {versions.map((v) => (
              <option key={v.id} value={v.version_number}>
                v{v.version_number} — {v.original_filename}
              </option>
            ))}
          </select>

          <label className="form-label">To version</label>
          <select
            className="filter-select"
            value={toVer}
            onChange={(e) => setToVer(Number(e.target.value))}
            disabled={comparing}
          >
            {versions.map((v) => (
              <option key={v.id} value={v.version_number}>
                v{v.version_number} — {v.original_filename}
              </option>
            ))}
          </select>

          <button
            className="btn btn-primary"
            disabled={comparing || versions.length < 2}
            onClick={runCompare}
          >
            {comparing ? "Comparing…" : "Compare"}
          </button>
        </div>

        {error && <div className="error-box" style={{ marginTop: "1rem" }}>{error}</div>}

        {result && (
          <>
            {/* Risk change banner */}
            {result.risk_changed ? (
              <div className="warn-box" style={{ marginTop: "1rem" }}>
                <strong>Risk level changed:</strong>{" "}
                <span className={riskClass(result.from_summary.overall_risk)}>
                  {result.from_summary.overall_risk ?? "—"}
                </span>
                {" → "}
                <span className={riskClass(result.to_summary.overall_risk)}>
                  {result.to_summary.overall_risk ?? "—"}
                </span>
              </div>
            ) : (
              <div className="success-box" style={{ marginTop: "1rem" }}>
                Risk level unchanged: <strong>{result.from_summary.overall_risk ?? "—"}</strong>
              </div>
            )}

            {/* Side-by-side summary */}
            <div className="compare-grid" style={{ marginTop: "1.5rem" }}>
              {/* From */}
              <div className="compare-col">
                <div className="compare-col-header">
                  v{result.from_version} — {result.from_summary.original_filename}
                </div>
                <table className="detail-table">
                  <tbody>
                    <tr>
                      <th>Overall risk</th>
                      <td>
                        <span className={riskClass(result.from_summary.overall_risk)}>
                          {result.from_summary.overall_risk ?? "—"}
                        </span>
                      </td>
                    </tr>
                    <tr><th>Total findings</th><td>{result.from_summary.total_findings}</td></tr>
                    <tr>
                      <th>Risk breakdown</th>
                      <td>
                        <span className="badge badge--red">H: {result.from_summary.high_risk_clauses}</span>{" "}
                        <span className="badge badge--yellow">M: {result.from_summary.medium_risk_clauses}</span>{" "}
                        <span className="badge badge--green">L: {result.from_summary.low_risk_clauses}</span>
                      </td>
                    </tr>
                    <tr>
                      <th>Review status</th>
                      <td><span className="badge badge--gray">{result.from_summary.review_status}</span></td>
                    </tr>
                    {result.from_summary.has_analysis ? (
                      <tr>
                        <th></th>
                        <td>
                          <Link
                            href={`/contracts/${contractId}/versions/${versions.find(v => v.version_number === result.from_version)?.id}/report`}
                            className="btn btn-xs btn-outline"
                          >
                            View report
                          </Link>
                        </td>
                      </tr>
                    ) : (
                      <tr><td colSpan={2} className="text-muted">No analysis yet</td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Delta column */}
              <div className="compare-delta-col">
                <div className="compare-col-header">Δ Change</div>
                <table className="detail-table">
                  <tbody>
                    <tr>
                      <th>Risk</th>
                      <td>
                        {result.risk_changed
                          ? <span className="delta delta--worse">changed</span>
                          : <span className="delta delta--same">—</span>}
                      </td>
                    </tr>
                    <tr>
                      <th>Findings</th>
                      <td><span className={deltaClass(result.findings_delta)}>{deltaLabel(result.findings_delta)}</span></td>
                    </tr>
                    <tr>
                      <th>High</th>
                      <td><span className={deltaClass(result.high_delta)}>{deltaLabel(result.high_delta)}</span></td>
                    </tr>
                    <tr>
                      <th>Medium</th>
                      <td><span className={deltaClass(result.medium_delta)}>{deltaLabel(result.medium_delta)}</span></td>
                    </tr>
                    <tr>
                      <th>Low</th>
                      <td><span className={deltaClass(-result.low_delta)}>{deltaLabel(result.low_delta)}</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* To */}
              <div className="compare-col">
                <div className="compare-col-header">
                  v{result.to_version} — {result.to_summary.original_filename}
                </div>
                <table className="detail-table">
                  <tbody>
                    <tr>
                      <th>Overall risk</th>
                      <td>
                        <span className={riskClass(result.to_summary.overall_risk)}>
                          {result.to_summary.overall_risk ?? "—"}
                        </span>
                      </td>
                    </tr>
                    <tr><th>Total findings</th><td>{result.to_summary.total_findings}</td></tr>
                    <tr>
                      <th>Risk breakdown</th>
                      <td>
                        <span className="badge badge--red">H: {result.to_summary.high_risk_clauses}</span>{" "}
                        <span className="badge badge--yellow">M: {result.to_summary.medium_risk_clauses}</span>{" "}
                        <span className="badge badge--green">L: {result.to_summary.low_risk_clauses}</span>
                      </td>
                    </tr>
                    <tr>
                      <th>Review status</th>
                      <td><span className="badge badge--gray">{result.to_summary.review_status}</span></td>
                    </tr>
                    {result.to_summary.has_analysis ? (
                      <tr>
                        <th></th>
                        <td>
                          <Link
                            href={`/contracts/${contractId}/versions/${versions.find(v => v.version_number === result.to_version)?.id}/report`}
                            className="btn btn-xs btn-outline"
                          >
                            View report
                          </Link>
                        </td>
                      </tr>
                    ) : (
                      <tr><td colSpan={2} className="text-muted">No analysis yet</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Topic changes */}
            {(result.new_topics.length > 0 || result.resolved_topics.length > 0) && (
              <div className="compare-topics" style={{ marginTop: "1.5rem" }}>
                <h2>Risk topic changes</h2>
                <div className="compare-topics-grid">
                  {result.new_topics.length > 0 && (
                    <div>
                      <h3 className="compare-topics-label compare-topics-label--new">
                        New topics in v{result.to_version}
                      </h3>
                      <ul className="compare-topics-list">
                        {result.new_topics.map((t) => (
                          <li key={t} className="compare-topic compare-topic--new">{t}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {result.resolved_topics.length > 0 && (
                    <div>
                      <h3 className="compare-topics-label compare-topics-label--resolved">
                        Topics resolved in v{result.to_version}
                      </h3>
                      <ul className="compare-topics-list">
                        {result.resolved_topics.map((t) => (
                          <li key={t} className="compare-topic compare-topic--resolved">{t}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}
          </>
        )}

        {loading && <div className="loading">Loading versions…</div>}
        {!loading && versions.length < 2 && !error && (
          <div className="empty-state" style={{ marginTop: "2rem" }}>
            This contract only has one version. Upload a revised version to compare.
          </div>
        )}

      </main>
    </div>
  );
}

export default function ComparePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <AuthGuard>
      {(user) => (
        <Suspense fallback={<div className="loading">Loading…</div>}>
          <CompareContent user={user} contractId={id} />
        </Suspense>
      )}
    </AuthGuard>
  );
}
