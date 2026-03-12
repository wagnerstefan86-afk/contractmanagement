"use client";

import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  getNegotiation,
  getContract,
  updateFinding,
  NegotiationOut,
  ContractOut,
  FindingStatus,
} from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function priorityClass(priority: string) {
  const p = priority?.toLowerCase();
  if (p === "high")   return "card-priority card-priority--high";
  if (p === "medium") return "card-priority card-priority--medium";
  return "card-priority card-priority--low";
}

function priorityBadge(priority: string) {
  const p = priority?.toLowerCase();
  if (p === "high")   return "badge badge--red";
  if (p === "medium") return "badge badge--yellow";
  return "badge badge--green";
}

const TOPIC_DE: Record<string, string> = {
  REGULATORY_COMPLIANCE: "Regulatorische Compliance",
  DATA_PROTECTION:       "Datenschutz",
  SECURITY_CONTROLS:     "Sicherheitsmaßnahmen",
  AUDIT_RIGHTS:          "Prüfungsrechte",
  INCIDENT_MANAGEMENT:  "Vorfallmanagement",
  SERVICE_LEVELS:        "Service-Level",
  OTHER:                 "Sonstiges",
};

const FINDING_TYPE_DE: Record<string, string> = {
  NON_TRANSFERABLE_REGULATION: "Nicht übertragbare Regulierungspflicht",
  SCOPE_UNDEFINED:             "Undefinierter Anwendungsbereich",
  OPERATIONAL_RISK:            "Operatives Risiko",
  CUSTOMER_RESPONSIBILITY:     "Kundenseitige Verantwortung",
  AMBIGUOUS_REQUIREMENT:       "Unklare Anforderung",
};

function topicLabel(t: string | undefined): string {
  if (!t) return "—";
  return TOPIC_DE[t] ?? t.replace(/_/g, " ");
}

// German reviewer decision options
const REVIEWER_DECISIONS: { label: string; value: FindingStatus; description: string }[] = [
  { label: "Risiko akzeptieren",          value: "accepted_risk",  description: "Risiko akzeptiert — keine Vertragsänderung erforderlich" },
  { label: "Vertragsänderung anfordern",  value: "in_negotiation", description: "Vertragsänderung beim Anbieter einfordern" },
  { label: "An Rechtsabteilung",          value: "in_review",      description: "Zur rechtlichen Prüfung weiterleiten" },
  { label: "Eigene Verantwortung",        value: "not_applicable", description: "Verantwortung liegt auf unserer Seite" },
  { label: "Nicht anwendbar",             value: "not_applicable", description: "Befund ist auf diesen Kontext nicht anwendbar" },
  { label: "Klärung erforderlich",        value: "deferred",       description: "Zurückstellen bis zur Klärung" },
  { label: "Erledigt",                    value: "resolved",       description: "Problem wurde behoben" },
];

// ── Types ─────────────────────────────────────────────────────────────────────

interface RegulatoryBasisItem {
  sr_id?: string; framework?: string; article?: string;
  obligation?: string; penalty?: string; regulation?: string;
  match_type?: string; confidence?: number;
}

interface ClauseExcerpt {
  clause_id?: string; page?: number; text?: string;
}

interface NegItem {
  negotiation_id?:          string;
  action_id?:               string;
  topic?:                   string | string[];
  finding_type?:            string;
  finding_label?:           string;
  priority?:                string;
  affected_clauses?:        string[];
  problem_summary?:         string;
  regulatory_basis?:        string | RegulatoryBasisItem[];
  recommended_clause_text?: string;
  negotiation_argument?:    string;
  fallback_option?:         string;
  owner_role?:              string;
  estimated_effort?:        string;
  expected_risk_reduction?: string;
  current_clause_excerpts?: (string | ClauseExcerpt)[];
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({
  letter, title, children,
}: { letter: string; title: string; children: React.ReactNode }) {
  return (
    <div style={{
      borderLeft: "3px solid var(--color-border)",
      paddingLeft: "0.875rem",
      marginBottom: "1rem",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.4rem" }}>
        <span style={{
          fontSize: "0.65rem", fontWeight: 700, color: "var(--color-muted)",
          background: "var(--color-surface)", border: "1px solid var(--color-border)",
          borderRadius: "0.25rem", padding: "0.1rem 0.3rem", letterSpacing: "0.04em",
        }}>{letter}</span>
        <span style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{title}</span>
      </div>
      {children}
    </div>
  );
}

// ── Reviewer decision panel (Section F) ───────────────────────────────────────

function ReviewerDecisionPanel({
  item, contractId, versionId, isViewer,
}: {
  item: NegItem; contractId: string; versionId: number | null; isViewer: boolean;
}) {
  const findingKey = item.action_id ?? item.negotiation_id;
  const [decision,  setDecision]  = useState<FindingStatus | "">("");
  const [notes,     setNotes]     = useState("");
  const [saving,    setSaving]    = useState(false);
  const [saved,     setSaved]     = useState(false);
  const [saveError, setSaveError] = useState("");

  if (!findingKey || !versionId || isViewer) return null;

  async function handleRecord() {
    if (!decision || !findingKey || !versionId) return;
    setSaving(true); setSaveError("");
    try {
      await updateFinding(contractId, versionId, findingKey, {
        status: decision,
        disposition_reason: notes || undefined,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Speichern fehlgeschlagen.");
    } finally {
      setSaving(false);
    }
  }

  const selected = REVIEWER_DECISIONS.find((d) => d.value === decision && d.label === REVIEWER_DECISIONS.find(x => x.value === decision)?.label);

  return (
    <Section letter="F" title="Prüferentscheidung">
      {saved     && <div className="success-box" style={{ marginBottom: "0.5rem" }}>Entscheidung gespeichert.</div>}
      {saveError && <div className="error-box"   style={{ marginBottom: "0.5rem" }}>{saveError}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.35rem", marginBottom: "0.5rem" }}>
        {REVIEWER_DECISIONS.map((d) => (
          <button
            key={`${d.label}-${d.value}`}
            className={`btn btn-sm ${decision === d.value && REVIEWER_DECISIONS.find(x => x.value === decision && x.label === d.label) ? "btn-primary" : "btn-outline"}`}
            style={{ textAlign: "left", justifyContent: "flex-start", fontSize: "0.8rem" }}
            onClick={() => setDecision(decision === d.value && REVIEWER_DECISIONS.find(x => x.value === decision && x.label === d.label) ? "" : d.value)}
            disabled={saving}
            title={d.description}
          >
            {d.label}
          </button>
        ))}
      </div>

      {decision && (
        <p style={{ fontSize: "0.8rem", color: "var(--color-muted)", marginBottom: "0.5rem" }}>
          {selected?.description ?? REVIEWER_DECISIONS.find(d => d.value === decision)?.description}
        </p>
      )}

      <textarea
        className="workflow-notes"
        rows={2}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        disabled={saving}
        placeholder="Interne Anmerkungen (optional)…"
        style={{ marginBottom: "0.5rem" }}
      />
      <button
        className="btn btn-sm btn-primary"
        onClick={handleRecord}
        disabled={!decision || saving}
      >
        {saving ? "Speichern…" : "Entscheidung erfassen"}
      </button>
    </Section>
  );
}

// ── Negotiation item card ─────────────────────────────────────────────────────

function NegCard({
  item, contractId, versionId, isViewer, isHighlighted,
}: {
  item: NegItem; contractId: string; versionId: number | null; isViewer: boolean; isHighlighted: boolean;
}) {
  const [expanded, setExpanded] = useState(isHighlighted);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isHighlighted && cardRef.current) {
      cardRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
      setExpanded(true);
    }
  }, [isHighlighted]);

  const topics = Array.isArray(item.topic) ? item.topic : (item.topic ? [item.topic] : []);
  const anchorId = item.action_id ?? item.negotiation_id;

  return (
    <div
      id={anchorId}
      ref={cardRef}
      className={`neg-card ${priorityClass(item.priority ?? "")} ${isHighlighted ? "neg-card--highlighted" : ""}`}
    >
      {/* ── Section A: Zusammenfassung ─────────────────────────────────────── */}
      <div className="neg-card-header" onClick={() => setExpanded((x) => !x)} style={{ cursor: "pointer" }}>
        <div className="neg-card-meta">
          {item.action_id && <span className="mono neg-id">{item.action_id}</span>}
          {item.negotiation_id && item.negotiation_id !== item.action_id && (
            <span className="mono" style={{ fontSize: "0.75rem", color: "var(--color-muted)" }}>{item.negotiation_id}</span>
          )}
          <span className={priorityBadge(item.priority ?? "")}>{item.priority}</span>
          {item.owner_role && <span className="tag">{item.owner_role}</span>}
        </div>

        {/* Topic labels in German */}
        <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", marginBottom: "0.25rem" }}>
          {topics.map((t) => (
            <span key={t} className="tag" style={{ fontSize: "0.8rem" }}>{topicLabel(t)}</span>
          ))}
          {item.finding_type && !item.finding_label && (
            <span className="tag" style={{ fontSize: "0.8rem", color: "var(--color-muted)" }}>
              {FINDING_TYPE_DE[item.finding_type] ?? item.finding_type.replace(/_/g, " ")}
            </span>
          )}
          {item.finding_label && (
            <span className="tag" style={{ fontSize: "0.8rem", color: "var(--color-muted)" }}>{item.finding_label}</span>
          )}
        </div>

        {/* Affected clauses row */}
        {item.affected_clauses && item.affected_clauses.length > 0 && (
          <p style={{ fontSize: "0.8rem", color: "var(--color-muted)", marginBottom: "0.25rem" }}>
            Klauseln: {item.affected_clauses.map((c) => (
              versionId
                ? <Link
                    key={c}
                    href={`/contracts/${contractId}/versions/${versionId}/clauses/${encodeURIComponent(c)}`}
                    className="mono link"
                    style={{ fontSize: "0.8rem", marginRight: "0.3rem" }}
                    onClick={(e) => e.stopPropagation()}
                  >{c}</Link>
                : <span key={c} className="mono" style={{ fontSize: "0.8rem", marginRight: "0.3rem" }}>{c}</span>
            ))}
          </p>
        )}

        {/* Problem summary as short intro */}
        {item.problem_summary && (
          <p className="neg-summary" style={{ fontSize: "0.875rem" }}>
            {item.problem_summary.slice(0, 220)}{item.problem_summary.length > 220 ? "…" : ""}
          </p>
        )}

        <button className="btn btn-sm btn-ghost expand-btn" style={{ marginTop: "0.25rem" }}>
          {expanded ? "▲ Weniger" : "▼ Mehr"}
        </button>
      </div>

      {expanded && (
        <div className="neg-card-body">
          {/* ── Section B: Warum ist das problematisch? ───────────────────── */}
          {(item.regulatory_basis || item.problem_summary) && (
            <Section letter="B" title="Warum ist das problematisch?">
              {item.problem_summary && (
                <p style={{ fontSize: "0.875rem", marginBottom: "0.5rem" }}>{item.problem_summary}</p>
              )}
              {item.regulatory_basis && (
                <>
                  <p style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--color-muted)", marginBottom: "0.3rem" }}>Regulatorische Grundlage</p>
                  {Array.isArray(item.regulatory_basis)
                    ? item.regulatory_basis.map((rb, i) => (
                        <div key={i} style={{ marginBottom: "0.4rem", padding: "0.35rem 0.5rem", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "0.375rem", fontSize: "0.85rem" }}>
                          {typeof rb === "object" ? (
                            <>
                              <p style={{ fontWeight: 600, marginBottom: "0.15rem" }}>
                                {rb.framework && <span className="tag" style={{ marginRight: "0.3rem" }}>{rb.framework}</span>}
                                {rb.article}
                              </p>
                              {rb.obligation && <p style={{ margin: "0.1rem 0", color: "var(--color-muted)" }}>{rb.obligation}</p>}
                              {rb.penalty && <p style={{ margin: "0.1rem 0", fontSize: "0.8rem", color: "var(--color-warning)" }}>Sanktion: {rb.penalty}</p>}
                              {rb.match_type && (
                                <span className={rb.match_type === "DIRECT_MATCH" ? "badge badge--green" : "badge badge--gray"} style={{ fontSize: "0.7rem" }}>
                                  {rb.match_type === "DIRECT_MATCH" ? "Direkter Treffer" : "Indirekter Treffer"}
                                  {rb.confidence != null ? ` ${rb.confidence}%` : ""}
                                </span>
                              )}
                            </>
                          ) : <p>{rb}</p>}
                        </div>
                      ))
                    : <p style={{ fontSize: "0.875rem" }}>{item.regulatory_basis}</p>}
                </>
              )}
            </Section>
          )}

          {/* ── Section C: Vorgeschlagene Formulierung ────────────────────── */}
          {(item.recommended_clause_text || item.current_clause_excerpts?.length) && (
            <Section letter="C" title="Vorgeschlagene Vertragsformulierung">
              {item.current_clause_excerpts && item.current_clause_excerpts.length > 0 && (
                <>
                  <p style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--color-muted)", marginBottom: "0.3rem" }}>Aktueller Vertragstext (Originalsprache)</p>
                  {item.current_clause_excerpts.map((ex, i) => (
                    <blockquote key={i} className="clause-excerpt" style={{ marginBottom: "0.4rem" }}>
                      {typeof ex === "object" ? (
                        <>
                          {ex.clause_id && <span className="clause-id">{ex.clause_id}{ex.page ? ` (S. ${ex.page})` : ""}: </span>}
                          {ex.text}
                        </>
                      ) : ex}
                    </blockquote>
                  ))}
                </>
              )}
              {item.recommended_clause_text && (
                <>
                  <p style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--color-muted)", marginBottom: "0.3rem", marginTop: item.current_clause_excerpts?.length ? "0.5rem" : "0" }}>
                    Empfohlene Formulierung (in Sprache des Quellvertrags)
                  </p>
                  <blockquote className="clause-recommended">{item.recommended_clause_text}</blockquote>
                </>
              )}
            </Section>
          )}

          {/* ── Section D: Verhandlungsargument ──────────────────────────── */}
          {item.negotiation_argument && (
            <Section letter="D" title="Verhandlungsargument">
              <p style={{ fontSize: "0.875rem" }}>{item.negotiation_argument}</p>
            </Section>
          )}

          {/* ── Section E: Rückfallposition ───────────────────────────────── */}
          {item.fallback_option && (
            <Section letter="E" title="Rückfallposition">
              <p style={{ fontSize: "0.875rem", color: "var(--color-muted)" }}>{item.fallback_option}</p>
            </Section>
          )}

          {/* Effort / risk reduction meta */}
          {(item.estimated_effort || item.expected_risk_reduction) && (
            <div className="neg-meta-row" style={{ marginBottom: "0.75rem" }}>
              {item.estimated_effort && <span className="meta-chip">Aufwand: {item.estimated_effort}</span>}
              {item.expected_risk_reduction && <span className="meta-chip">Risikoreduzierung: {item.expected_risk_reduction}</span>}
            </div>
          )}

          {/* ── Section F: Prüferentscheidung ─────────────────────────────── */}
          <ReviewerDecisionPanel
            item={item}
            contractId={contractId}
            versionId={versionId}
            isViewer={isViewer}
          />
        </div>
      )}
    </div>
  );
}

// ── Main content ──────────────────────────────────────────────────────────────

function NegotiationContent({ user, contractId }: { user: SessionUser; contractId: string }) {
  const [data,     setData]     = useState<NegotiationOut | null>(null);
  const [contract, setContract] = useState<ContractOut | null>(null);
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(true);
  const [filter,   setFilter]   = useState<"ALLE" | "HIGH" | "MEDIUM" | "LOW">("ALLE");
  const [highlight, setHighlight] = useState<string | null>(null);

  const isViewer = user.role === "VIEWER";

  useEffect(() => {
    Promise.all([
      getNegotiation(contractId),
      getContract(contractId).catch(() => null),
    ])
      .then(([neg, c]) => { setData(neg); setContract(c); })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [contractId]);

  // Resolve URL hash for deep linking from Risk Report
  useEffect(() => {
    if (!loading && typeof window !== "undefined" && window.location.hash) {
      setHighlight(window.location.hash.slice(1));
    }
  }, [loading]);

  if (loading) return <div className="page"><Nav user={user} /><main className="main"><div className="loading">Laden…</div></main></div>;
  if (error)   return <div className="page"><Nav user={user} /><main className="main"><div className="error-box">{error}</div></main></div>;
  if (!data)   return null;

  const pkg      = data.package;
  const items    = (pkg.negotiation_items ?? []) as NegItem[];
  const filtered = filter === "ALLE" ? items : items.filter(
    (it) => it.priority?.toUpperCase() === filter
  );
  const versionId = contract?.current_version_id ?? null;

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}`} className="breadcrumb">← {contractId}</Link>
            <h1>Verhandlungspaket</h1>
            <p className="page-subtitle">
              Klappen Sie Einträge auf, um Formulierungsvorschläge und Verhandlungsargumente einzusehen und Ihre Prüfungsentscheidung zu erfassen.
            </p>
          </div>
          <Link href={`/contracts/${contractId}/report`} className="btn btn-outline">
            ← Risikobericht
          </Link>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Einträge gesamt</div>
            <div className="stat-value">{(pkg.total_items as number) ?? items.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Hohe Priorität</div>
            <div className="stat-value"><span className="badge badge--red">{(pkg.high_priority as number) ?? 0}</span></div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Mittlere Priorität</div>
            <div className="stat-value"><span className="badge badge--yellow">{(pkg.medium_priority as number) ?? 0}</span></div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Niedrige Priorität</div>
            <div className="stat-value"><span className="badge badge--green">{(pkg.low_priority as number) ?? 0}</span></div>
          </div>
        </div>

        {Array.isArray(pkg.frameworks_referenced) && (pkg.frameworks_referenced as string[]).length > 0 && (
          <div className="tag-list" style={{ marginBottom: "1.5rem" }}>
            {(pkg.frameworks_referenced as string[]).map((f) => (
              <span key={f} className="tag">{f}</span>
            ))}
          </div>
        )}

        <div className="filter-row">
          {(["ALLE", "HIGH", "MEDIUM", "LOW"] as const).map((f) => (
            <button
              key={f}
              className={`btn btn-sm ${filter === f ? "btn-primary" : "btn-outline"}`}
              onClick={() => setFilter(f)}
            >
              {f === "ALLE" ? "Alle" : f}
            </button>
          ))}
          <span className="filter-count">{filtered.length} Eintrag{filtered.length !== 1 ? "e" : ""}</span>
        </div>

        {!isViewer && versionId && (
          <div className="info-box" style={{ marginBottom: "1rem" }}>
            Klappen Sie jeden Eintrag auf und nutzen Sie den Abschnitt <strong>Prüferentscheidung</strong>, um Ihre Position zu erfassen.
          </div>
        )}

        <div className="neg-list">
          {filtered.map((item, i) => (
            <NegCard
              key={item.negotiation_id ?? item.action_id ?? i}
              item={item}
              contractId={contractId}
              versionId={versionId}
              isViewer={isViewer}
              isHighlighted={!!(highlight && (item.action_id === highlight || item.negotiation_id === highlight))}
            />
          ))}
          {filtered.length === 0 && (
            <div className="empty-state">Keine Einträge für diesen Filter.</div>
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
