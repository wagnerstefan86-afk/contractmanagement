"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  listClauses,
  getClauseDetail,
  ClauseListItem,
  ClauseDetailOut,
  SRMatchOut,
  ClauseFindingOut,
  NegotiationItemOut,
  ClauseFilters,
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

// ── Clause Detail Drawer ───────────────────────────────────────────────────────

function ClauseDrawer({
  detail,
  contractId,
  versionId,
  onClose,
}: {
  detail:     ClauseDetailOut;
  contractId: string;
  versionId:  number;
  onClose:    () => void;
}) {
  const rs = detail.risk_score;
  const ob = detail.obligation_assessment;

  // Key-press to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="drawer-header">
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
            <h2 className="mono" style={{ margin: 0, fontSize: "1rem" }}>{detail.clause_id}</h2>
            {detail.page != null && (
              <span className="meta-chip">p.{detail.page}</span>
            )}
            {detail.layout_type && (
              <span className="tag">{detail.layout_type}</span>
            )}
            {ob?.severity && (
              <span className={severityBadge(ob.severity)}>{ob.severity}</span>
            )}
            {rs && (
              <span className="meta-chip">Risk: <strong>{rs.risk_score}</strong></span>
            )}
          </div>
          <button className="btn btn-ghost" onClick={onClose} title="Close (Esc)">✕</button>
        </div>

        <div className="drawer-body">
          {/* Clause text */}
          {detail.text && (
            <div className="clause-text-block">
              <span className="form-label">Contract text</span>
              <p className="clause-text">{detail.text}</p>
            </div>
          )}

          {/* Obligation assessment */}
          {ob && (
            <div className="section">
              <h3>Obligation assessment</h3>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.5rem" }}>
                <span className="tag">{ob.assessment.replace(/_/g, " ")}</span>
                {ob.severity && <span className={severityBadge(ob.severity)}>{ob.severity}</span>}
              </div>
              {ob.reason && <p style={{ fontSize: "0.875rem", margin: "0.25rem 0" }}>{ob.reason}</p>}
              {ob.recommended_action && (
                <p style={{ fontSize: "0.85rem", color: "var(--color-muted)", margin: "0.25rem 0" }}>
                  <strong>Recommended:</strong> {ob.recommended_action}
                </p>
              )}
            </div>
          )}

          {/* Risk score */}
          {rs && (
            <div className="section">
              <h3>Risk score</h3>
              <div className="readiness-counts">
                <span className="meta-chip">Score: <strong>{rs.risk_score}</strong></span>
                {rs.priority && (
                  <span className={priorityBadge(rs.priority)}>{rs.priority} priority</span>
                )}
                {rs.topic && <span className="meta-chip">Topic: {rs.topic}</span>}
              </div>
            </div>
          )}

          {/* SR Matches */}
          {detail.sr_matches.length > 0 && (
            <div className="section">
              <h3>Regulatory matches ({detail.sr_matches.length})</h3>
              <div className="table-scroll">
                <table className="table" style={{ fontSize: "0.82rem" }}>
                  <thead>
                    <tr>
                      <th>SR ID</th><th>Framework</th><th>Match</th><th>Confidence</th><th>Title</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.sr_matches.map((m: SRMatchOut) => (
                      <tr key={`${m.sr_id}-${m.match_type}`}>
                        <td className="mono">{m.sr_id}</td>
                        <td><span className="tag">{m.framework}</span></td>
                        <td><span className={matchBadge(m.match_type)}>{m.match_type.replace(/_/g, " ")}</span></td>
                        <td>{(m.match_confidence * 100).toFixed(0)}%</td>
                        <td className="preview-cell">{m.sr_title ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Findings */}
          {detail.findings.length > 0 ? (
            <div className="section">
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
                <h3 style={{ margin: 0 }}>Findings ({detail.findings.length})</h3>
                <Link
                  href={`/contracts/${contractId}/versions/${versionId}/findings`}
                  className="btn btn-xs btn-outline"
                >
                  All findings →
                </Link>
              </div>
              <div className="table-scroll">
                <table className="table" style={{ fontSize: "0.82rem" }}>
                  <thead>
                    <tr><th>Type</th><th>Topic</th><th>Severity</th><th>Status</th><th>Comment</th></tr>
                  </thead>
                  <tbody>
                    {detail.findings.map((f: ClauseFindingOut) => (
                      <tr key={f.id}>
                        <td><span className="tag">{f.finding_type}</span></td>
                        <td>{f.topic ?? "—"}</td>
                        <td><span className={severityBadge(f.severity)}>{f.severity ?? "—"}</span></td>
                        <td><span className={statusBadge(f.status)}>{f.status.replace(/_/g, " ")}</span></td>
                        <td className="preview-cell">{f.review_comment ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="section">
              <h3>Findings</h3>
              <p className="text-muted" style={{ fontSize: "0.875rem" }}>No findings linked to this clause.</p>
            </div>
          )}

          {/* Negotiation items */}
          {detail.negotiation_items.length > 0 && (
            <div className="section">
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
                <h3 style={{ margin: 0 }}>Negotiation items ({detail.negotiation_items.length})</h3>
                <Link
                  href={`/contracts/${contractId}/versions/${versionId}/negotiation`}
                  className="btn btn-xs btn-outline"
                >
                  Full package →
                </Link>
              </div>
              {detail.negotiation_items.map((n: NegotiationItemOut, i: number) => (
                <div key={i} className="neg-item-card">
                  <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.4rem" }}>
                    {n.neg_id && <span className="mono" style={{ fontSize: "0.8rem" }}>{n.neg_id}</span>}
                    {n.priority && <span className={priorityBadge(n.priority)}>{n.priority}</span>}
                    {n.topic && <span className="tag">{n.topic}</span>}
                    {n.finding_type && <span className="tag">{n.finding_type.replace(/_/g, " ")}</span>}
                  </div>
                  {n.position_summary && (
                    <p style={{ fontSize: "0.85rem", margin: "0.2rem 0" }}>{n.position_summary}</p>
                  )}
                  {n.recommended_text && (
                    <details style={{ fontSize: "0.8rem", marginTop: "0.4rem" }}>
                      <summary style={{ cursor: "pointer", color: "var(--color-primary)" }}>
                        Recommended clause text
                      </summary>
                      <p style={{ marginTop: "0.5rem", whiteSpace: "pre-wrap" }}>{n.recommended_text}</p>
                    </details>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Workflow context */}
          <div className="section">
            <h3>Workflow context</h3>
            <div className="readiness-counts">
              <span className="meta-chip">Status: <strong>{detail.workflow_context.review_status}</strong></span>
              {detail.workflow_context.review_decision !== "none" && (
                <span className="meta-chip">Decision: <strong>{detail.workflow_context.review_decision.replace(/_/g, " ")}</strong></span>
              )}
              <span className="meta-chip">Readiness: <strong>{detail.workflow_context.approval_readiness.replace(/_/g, " ")}</strong></span>
            </div>
          </div>
        </div>

        {/* Footer links */}
        <div className="drawer-footer">
          <Link
            href={`/contracts/${contractId}/versions/${versionId}/report`}
            className="btn btn-sm btn-outline"
          >
            Risk report
          </Link>
          <Link
            href={`/contracts/${contractId}/versions/${versionId}/findings`}
            className="btn btn-sm btn-outline"
          >
            Findings
          </Link>
          <Link
            href={`/contracts/${contractId}/versions/${versionId}/negotiation`}
            className="btn btn-sm btn-outline"
          >
            Negotiation
          </Link>
        </div>
      </div>
    </div>
  );
}

// ── Clause row ─────────────────────────────────────────────────────────────────

function ClauseRow({
  clause,
  isHighlighted,
  onClick,
}: {
  clause:        ClauseListItem;
  isHighlighted: boolean;
  onClick:       () => void;
}) {
  const openCount = clause.finding_statuses.filter(
    (s) => s === "open" || s === "in_review" || s === "in_negotiation"
  ).length;

  return (
    <tr
      className={`clause-row${isHighlighted ? " clause-row--active" : ""}${(clause.severity ?? "").toUpperCase() === "HIGH" ? " clause-row--high" : ""}`}
      onClick={onClick}
      style={{ cursor: "pointer" }}
    >
      <td className="mono" style={{ fontWeight: 600 }}>{clause.clause_id}</td>
      <td>{clause.page ?? "—"}</td>
      <td>
        {clause.severity
          ? <span className={severityBadge(clause.severity)}>{clause.severity}</span>
          : <span className="badge badge--gray">—</span>}
      </td>
      <td>{clause.risk_score != null ? clause.risk_score.toFixed(1) : "—"}</td>
      <td>{clause.topic ?? <span className="text-muted">—</span>}</td>
      <td>
        {clause.finding_count > 0 ? (
          <span style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
            <span className={openCount > 0 ? "badge badge--red" : "badge badge--green"}>
              {clause.finding_count} {openCount > 0 ? `(${openCount} open)` : "✓"}
            </span>
          </span>
        ) : (
          <span className="text-muted">—</span>
        )}
      </td>
      <td>
        {clause.sr_match_count > 0 ? (
          <span className={clause.has_direct_match ? "badge badge--green" : "badge badge--gray"}>
            {clause.sr_match_count} {clause.has_direct_match ? "direct" : ""}
          </span>
        ) : (
          <span className="text-muted">—</span>
        )}
      </td>
      <td className="preview-cell" style={{ maxWidth: "260px" }}>
        {clause.text_preview ?? "—"}
      </td>
    </tr>
  );
}

// ── Main content ───────────────────────────────────────────────────────────────

function ClauseExplorerContent({
  user,
  contractId,
  versionId,
}: {
  user:       SessionUser;
  contractId: string;
  versionId:  number;
}) {
  const router      = useRouter();
  const searchParams = useSearchParams();

  // ── Filter state (synced to URL) ────────────────────────────────────────────
  const [filterSeverity,    setFilterSeverity]    = useState(searchParams.get("severity") ?? "");
  const [filterTopic,       setFilterTopic]       = useState(searchParams.get("topic") ?? "");
  const [filterFindingSt,   setFilterFindingSt]   = useState(searchParams.get("finding_status") ?? "");
  const [filterLayoutType,  setFilterLayoutType]  = useState(searchParams.get("layout_type") ?? "");
  const [filterMinRisk,     setFilterMinRisk]     = useState(searchParams.get("min_risk_score") ?? "");
  const [filterQ,           setFilterQ]           = useState(searchParams.get("q") ?? "");

  const [clauses,  setClauses]  = useState<ClauseListItem[]>([]);
  const [total,    setTotal]    = useState(0);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState("");

  const [selected, setSelected] = useState<string | null>(null);
  const [detail,   setDetail]   = useState<ClauseDetailOut | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError,   setDetailError]   = useState("");

  // Debounce text search
  const qTimer = useRef<ReturnType<typeof setTimeout>>();
  const [debouncedQ, setDebouncedQ] = useState(filterQ);
  useEffect(() => {
    clearTimeout(qTimer.current);
    qTimer.current = setTimeout(() => setDebouncedQ(filterQ), 350);
    return () => clearTimeout(qTimer.current);
  }, [filterQ]);

  // ── Push current filters to URL ─────────────────────────────────────────────
  useEffect(() => {
    const p = new URLSearchParams();
    if (filterSeverity)  p.set("severity",       filterSeverity);
    if (filterTopic)     p.set("topic",           filterTopic);
    if (filterFindingSt) p.set("finding_status",  filterFindingSt);
    if (filterLayoutType) p.set("layout_type",    filterLayoutType);
    if (filterMinRisk)   p.set("min_risk_score",  filterMinRisk);
    if (debouncedQ)      p.set("q",               debouncedQ);
    const qs = p.toString();
    router.replace(
      `/contracts/${contractId}/versions/${versionId}/clauses${qs ? `?${qs}` : ""}`,
      { scroll: false }
    );
  }, [filterSeverity, filterTopic, filterFindingSt, filterLayoutType, filterMinRisk, debouncedQ]);

  // ── Fetch clauses ───────────────────────────────────────────────────────────
  useEffect(() => {
    setLoading(true);
    setError("");
    const filters: ClauseFilters = {};
    if (filterSeverity)   filters.severity       = filterSeverity;
    if (filterTopic)      filters.topic          = filterTopic;
    if (filterFindingSt)  filters.finding_status = filterFindingSt;
    if (filterLayoutType) filters.layout_type    = filterLayoutType;
    if (filterMinRisk)    filters.min_risk_score = Number(filterMinRisk);
    if (debouncedQ)       filters.q              = debouncedQ;
    listClauses(contractId, versionId, filters)
      .then((r) => { setClauses(r.clauses); setTotal(r.total); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load clauses."))
      .finally(() => setLoading(false));
  }, [contractId, versionId, filterSeverity, filterTopic, filterFindingSt, filterLayoutType, filterMinRisk, debouncedQ]);

  // ── Open clause detail ───────────────────────────────────────────────────────
  const openDetail = useCallback((clauseId: string) => {
    setSelected(clauseId);
    setDetailError("");
    if (detail?.clause_id === clauseId) return;  // already loaded
    setDetail(null);
    setDetailLoading(true);
    getClauseDetail(contractId, versionId, clauseId)
      .then(setDetail)
      .catch((e: unknown) => setDetailError(e instanceof Error ? e.message : "Failed to load clause."))
      .finally(() => setDetailLoading(false));
  }, [contractId, versionId, detail]);

  const closeDetail = useCallback(() => {
    setSelected(null);
    setDetail(null);
  }, []);

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}`} className="breadcrumb">← {contractId}</Link>
            <h1>Clause Explorer — v{versionId}</h1>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Link href={`/contracts/${contractId}/versions/${versionId}/report`}    className="btn btn-outline btn-sm">Report</Link>
            <Link href={`/contracts/${contractId}/versions/${versionId}/findings`}  className="btn btn-outline btn-sm">Findings</Link>
            <Link href={`/contracts/${contractId}/versions/${versionId}/negotiation`} className="btn btn-outline btn-sm">Negotiation</Link>
          </div>
        </div>

        {/* ── Filter bar ─────────────────────────────────────────────────── */}
        <div className="filter-row" style={{ flexWrap: "wrap" }}>
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
            value={filterFindingSt}
            onChange={(e) => setFilterFindingSt(e.target.value)}
          >
            <option value="">Any finding status</option>
            <option value="open">Open</option>
            <option value="in_review">In review</option>
            <option value="in_negotiation">In negotiation</option>
            <option value="resolved">Resolved</option>
            <option value="accepted_risk">Accepted risk</option>
            <option value="deferred">Deferred</option>
          </select>

          <select
            className="filter-select"
            value={filterLayoutType}
            onChange={(e) => setFilterLayoutType(e.target.value)}
          >
            <option value="">All types</option>
            <option value="paragraph">Paragraph</option>
            <option value="bullet_list">Bullet list</option>
            <option value="numbered_list">Numbered list</option>
            <option value="table">Table</option>
            <option value="heading">Heading</option>
          </select>

          <input
            className="filter-input"
            placeholder="Min risk score…"
            type="number"
            min={0}
            step={0.5}
            value={filterMinRisk}
            onChange={(e) => setFilterMinRisk(e.target.value)}
            style={{ width: "130px" }}
          />

          <input
            className="filter-input"
            placeholder="Topic filter…"
            value={filterTopic}
            onChange={(e) => setFilterTopic(e.target.value)}
          />

          <input
            className="filter-input"
            placeholder="Search clause text…"
            value={filterQ}
            onChange={(e) => setFilterQ(e.target.value)}
            style={{ minWidth: "200px" }}
          />

          {(filterSeverity || filterFindingSt || filterLayoutType || filterMinRisk || filterTopic || filterQ) && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setFilterSeverity(""); setFilterFindingSt(""); setFilterLayoutType("");
                setFilterMinRisk(""); setFilterTopic(""); setFilterQ(""); setDebouncedQ("");
              }}
            >
              Clear filters
            </button>
          )}

          <span className="filter-count">{total} clause{total !== 1 ? "s" : ""}</span>
        </div>

        {error && <div className="error-box" style={{ marginTop: "1rem" }}>{error}</div>}
        {loading && <div className="loading" style={{ marginTop: "1rem" }}>Loading clauses…</div>}

        {!loading && clauses.length === 0 && !error && (
          <div className="empty-state">
            <p>No clauses match the current filters.</p>
            <p style={{ fontSize: "0.875rem", marginTop: "0.5rem" }}>
              {total === 0 && "This version may not have a completed analysis yet."}
            </p>
          </div>
        )}

        {!loading && clauses.length > 0 && (
          <div className="section">
            <div className="table-scroll">
              <table className="table clause-table">
                <thead>
                  <tr>
                    <th>Clause</th>
                    <th>Page</th>
                    <th>Severity</th>
                    <th>Risk</th>
                    <th>Topic</th>
                    <th>Findings</th>
                    <th>SR matches</th>
                    <th>Preview</th>
                  </tr>
                </thead>
                <tbody>
                  {clauses.map((c) => (
                    <ClauseRow
                      key={c.clause_id}
                      clause={c}
                      isHighlighted={selected === c.clause_id}
                      onClick={() => openDetail(c.clause_id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>

      {/* Detail drawer */}
      {selected && (
        detailLoading ? (
          <div className="drawer-backdrop" onClick={closeDetail}>
            <div className="drawer">
              <div className="drawer-header">
                <h2 className="mono" style={{ margin: 0 }}>{selected}</h2>
                <button className="btn btn-ghost" onClick={closeDetail}>✕</button>
              </div>
              <div className="drawer-body">
                <div className="loading">Loading clause detail…</div>
              </div>
            </div>
          </div>
        ) : detailError ? (
          <div className="drawer-backdrop" onClick={closeDetail}>
            <div className="drawer">
              <div className="drawer-header">
                <h2 className="mono" style={{ margin: 0 }}>{selected}</h2>
                <button className="btn btn-ghost" onClick={closeDetail}>✕</button>
              </div>
              <div className="drawer-body">
                <div className="error-box">{detailError}</div>
              </div>
            </div>
          </div>
        ) : detail ? (
          <ClauseDrawer
            detail={detail}
            contractId={contractId}
            versionId={versionId}
            onClose={closeDetail}
          />
        ) : null
      )}
    </div>
  );
}

export default function ClauseExplorerPage({
  params,
}: {
  params: Promise<{ id: string; vid: string }>;
}) {
  const { id, vid } = use(params);
  return (
    <AuthGuard>
      {(user) => (
        <ClauseExplorerContent user={user} contractId={id} versionId={Number(vid)} />
      )}
    </AuthGuard>
  );
}
