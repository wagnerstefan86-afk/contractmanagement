"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import { getNegotiation, NegotiationOut } from "@/lib/api";

function priorityClass(priority: string) {
  const p = priority?.toLowerCase();
  if (p === "high") return "card-priority card-priority--high";
  if (p === "medium") return "card-priority card-priority--medium";
  return "card-priority card-priority--low";
}

function priorityBadge(priority: string) {
  const p = priority?.toLowerCase();
  if (p === "high") return "badge badge--red";
  if (p === "medium") return "badge badge--yellow";
  return "badge badge--green";
}

interface NegItem {
  negotiation_id?: string;
  action_id?: string;
  topic?: string;
  priority?: string;
  affected_clauses?: string[];
  problem_summary?: string;
  regulatory_basis?: string;
  recommended_clause_text?: string;
  negotiation_argument?: string;
  fallback_option?: string;
  owner_role?: string;
  estimated_effort?: string;
  expected_risk_reduction?: string;
  current_clause_excerpts?: string[];
}

function NegCard({ item }: { item: NegItem }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`neg-card ${priorityClass(item.priority ?? "")}`}>
      <div className="neg-card-header" onClick={() => setExpanded((x) => !x)}>
        <div className="neg-card-meta">
          <span className="mono neg-id">{item.negotiation_id ?? item.action_id}</span>
          <span className={priorityBadge(item.priority ?? "")}>{item.priority}</span>
          {item.owner_role && <span className="tag">{item.owner_role}</span>}
        </div>
        <h3 className="neg-topic">{item.topic ?? "—"}</h3>
        <p className="neg-summary">{item.problem_summary ?? ""}</p>
        <button className="btn btn-sm btn-ghost expand-btn">
          {expanded ? "▲ Less" : "▼ More"}
        </button>
      </div>

      {expanded && (
        <div className="neg-card-body">
          {item.regulatory_basis && (
            <div className="neg-section">
              <h4>Regulatory basis</h4>
              <p>{item.regulatory_basis}</p>
            </div>
          )}

          {item.current_clause_excerpts && item.current_clause_excerpts.length > 0 && (
            <div className="neg-section">
              <h4>Current clause(s)</h4>
              {item.current_clause_excerpts.map((ex, i) => (
                <blockquote key={i} className="clause-excerpt">{ex}</blockquote>
              ))}
            </div>
          )}

          {item.recommended_clause_text && (
            <div className="neg-section">
              <h4>Recommended clause text</h4>
              <blockquote className="clause-recommended">{item.recommended_clause_text}</blockquote>
            </div>
          )}

          {item.negotiation_argument && (
            <div className="neg-section">
              <h4>Negotiation argument</h4>
              <p>{item.negotiation_argument}</p>
            </div>
          )}

          {item.fallback_option && (
            <div className="neg-section">
              <h4>Fallback option</h4>
              <p>{item.fallback_option}</p>
            </div>
          )}

          <div className="neg-meta-row">
            {item.estimated_effort && (
              <span className="meta-chip">Effort: {item.estimated_effort}</span>
            )}
            {item.expected_risk_reduction && (
              <span className="meta-chip">Risk reduction: {item.expected_risk_reduction}</span>
            )}
            {item.affected_clauses && item.affected_clauses.length > 0 && (
              <span className="meta-chip">
                Clauses: {item.affected_clauses.join(", ")}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function NegotiationContent({ user, contractId }: { user: SessionUser; contractId: string }) {
  const [data, setData] = useState<NegotiationOut | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"ALL" | "HIGH" | "MEDIUM" | "LOW">("ALL");

  useEffect(() => {
    getNegotiation(contractId)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [contractId]);

  if (loading) return <div className="page"><Nav user={user} /><main className="main"><div className="loading">Loading…</div></main></div>;
  if (error) return <div className="page"><Nav user={user} /><main className="main"><div className="error-box">{error}</div></main></div>;
  if (!data) return null;

  const pkg = data.package;
  const items = (pkg.negotiation_items ?? []) as NegItem[];
  const filtered = filter === "ALL" ? items : items.filter(
    (it) => it.priority?.toUpperCase() === filter
  );

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}`} className="breadcrumb">← {contractId}</Link>
            <h1>Negotiation Package</h1>
          </div>
          <Link href={`/contracts/${contractId}/report`} className="btn btn-outline">
            ← Risk report
          </Link>
        </div>

        {/* Summary */}
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Total items</div>
            <div className="stat-value">{pkg.total_items as number ?? items.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">High priority</div>
            <div className="stat-value">
              <span className="badge badge--red">{pkg.high_priority as number ?? 0}</span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Medium priority</div>
            <div className="stat-value">
              <span className="badge badge--yellow">{pkg.medium_priority as number ?? 0}</span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Low priority</div>
            <div className="stat-value">
              <span className="badge badge--green">{pkg.low_priority as number ?? 0}</span>
            </div>
          </div>
        </div>

        {/* Frameworks */}
        {Array.isArray(pkg.frameworks_referenced) && (pkg.frameworks_referenced as string[]).length > 0 && (
          <div className="tag-list" style={{ marginBottom: "1.5rem" }}>
            {(pkg.frameworks_referenced as string[]).map((f) => (
              <span key={f} className="tag">{f}</span>
            ))}
          </div>
        )}

        {/* Filter */}
        <div className="filter-row">
          {(["ALL", "HIGH", "MEDIUM", "LOW"] as const).map((f) => (
            <button
              key={f}
              className={`btn btn-sm ${filter === f ? "btn-primary" : "btn-outline"}`}
              onClick={() => setFilter(f)}
            >
              {f}
            </button>
          ))}
          <span className="filter-count">{filtered.length} item{filtered.length !== 1 ? "s" : ""}</span>
        </div>

        {/* Items */}
        <div className="neg-list">
          {filtered.map((item, i) => (
            <NegCard key={item.negotiation_id ?? i} item={item} />
          ))}
          {filtered.length === 0 && (
            <div className="empty-state">No items for this filter.</div>
          )}
        </div>
      </main>
    </div>
  );
}

export default function NegotiationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <AuthGuard>{(user) => <NegotiationContent user={user} contractId={id} />}</AuthGuard>;
}
