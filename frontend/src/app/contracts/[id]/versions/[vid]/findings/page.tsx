"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  listFindings,
  getApprovalReadiness,
  updateFinding,
  getClauseDetail,
  FindingReviewOut,
  ApprovalReadinessOut,
  ApprovalReadiness,
  FindingStatus,
  FindingReviewUpdate,
  ClauseDetailOut,
  READINESS_LABEL,
  READINESS_BADGE,
} from "@/lib/api";

// ── German label helpers ───────────────────────────────────────────────────────

function severityBadge(s: string | null | undefined) {
  const u = (s ?? "").toUpperCase();
  if (u === "HIGH")   return "badge badge--red";
  if (u === "MEDIUM") return "badge badge--yellow";
  if (u === "LOW")    return "badge badge--green";
  return "badge badge--gray";
}

function statusBadge(s: FindingStatus) {
  switch (s) {
    case "open":           return "badge badge--red";
    case "in_review":      return "badge badge--yellow";
    case "in_negotiation": return "badge badge--yellow";
    case "resolved":       return "badge badge--green";
    case "accepted_risk":  return "badge badge--green";
    default:               return "badge badge--gray";
  }
}

function statusLabel(s: string): string {
  const labels: Record<string, string> = {
    open:           "Offen",
    in_review:      "In Prüfung",
    in_negotiation: "In Verhandlung",
    resolved:       "Erledigt",
    accepted_risk:  "Risiko akzeptiert",
    not_applicable: "Nicht anwendbar",
    deferred:       "Zurückgestellt",
  };
  return labels[s] ?? s.replace(/_/g, " ");
}

const TOPIC_DE: Record<string, string> = {
  REGULATORY_COMPLIANCE: "Reg. Compliance",
  DATA_PROTECTION:       "Datenschutz",
  SECURITY_CONTROLS:     "Sicherheit",
  AUDIT_RIGHTS:          "Prüfungsrechte",
  INCIDENT_MANAGEMENT:   "Vorfallmgmt.",
  SERVICE_LEVELS:        "Service-Level",
  OTHER:                 "Sonstiges",
};

function topicLabel(t: string | null | undefined): string {
  if (!t) return "—";
  return TOPIC_DE[t] ?? t.replace(/_/g, " ");
}

// German reviewer decision options
const REVIEWER_DECISIONS: { label: string; value: FindingStatus; description: string }[] = [
  { label: "Risiko akzeptieren",         value: "accepted_risk",  description: "Risiko akzeptiert — keine Vertragsänderung erforderlich" },
  { label: "Vertragsänderung anfordern", value: "in_negotiation", description: "Vertragsänderung beim Anbieter einfordern" },
  { label: "An Rechtsabteilung",         value: "in_review",      description: "Zur rechtlichen Prüfung weiterleiten" },
  { label: "Nicht anwendbar",            value: "not_applicable", description: "Befund ist auf diesen Kontext nicht anwendbar" },
  { label: "Klärung erforderlich",       value: "deferred",       description: "Zurückstellen bis zur Klärung" },
  { label: "Erledigt",                   value: "resolved",       description: "Problem wurde behoben" },
];

// ── Approval readiness banner ──────────────────────────────────────────────────

function ReadinessBanner({
  readiness, contractId, versionId, onQuickFilter,
}: {
  readiness: ApprovalReadinessOut;
  contractId: string;
  versionId: number;
  onQuickFilter: (severity: string, status: string) => void;
}) {
  const r = readiness.approval_readiness;
  const c = readiness.counts;
  const bannerClass: Record<ApprovalReadiness, string> = {
    blocked:                        "readiness-panel readiness-panel--blocked",
    review_required:                "readiness-panel readiness-panel--warn",
    ready_for_conditional_approval: "readiness-panel readiness-panel--conditional",
    ready_for_approval:             "readiness-panel readiness-panel--ready",
  };
  return (
    <div className={bannerClass[r]} style={{ marginBottom: "1.5rem" }}>
      <div className="readiness-header">
        <span>Freigabefähigkeit:</span>
        <span className={READINESS_BADGE[r]}>{READINESS_LABEL[r]}</span>
        <span className="meta-chip">HOCH offen: <strong>{c.high_open}</strong></span>
        <span className="meta-chip">MITTEL offen: <strong>{c.medium_open}</strong></span>
        <span className="meta-chip">Erledigt: <strong>{c.resolved}</strong></span>
      </div>
      <div className="readiness-quick-filters">
        <span style={{ fontSize: "0.85rem", color: "var(--color-muted)", marginRight: "0.5rem" }}>Schnellfilter:</span>
        <button className="btn btn-xs btn-outline" onClick={() => onQuickFilter("HIGH", "open")}>HIGH offen</button>
        <button className="btn btn-xs btn-outline" onClick={() => onQuickFilter("MEDIUM", "open")}>MEDIUM offen</button>
        <button className="btn btn-xs btn-outline" onClick={() => onQuickFilter("", "accepted_risk")}>Risiko akzeptiert</button>
        <button className="btn btn-xs btn-ghost" onClick={() => onQuickFilter("", "")}>Zurücksetzen</button>
        <Link href={`/contracts/${contractId}/versions/${versionId}/report`} className="btn btn-xs btn-outline" style={{ marginLeft: "0.5rem" }}>
          ← Risikobericht
        </Link>
      </div>
    </div>
  );
}

// ── Review card (expanded finding detail) ─────────────────────────────────────

function ReviewCard({
  finding, contractId, versionId, isViewer, onSaved,
}: {
  finding: FindingReviewOut;
  contractId: string;
  versionId: number;
  isViewer: boolean;
  onSaved: (updated: FindingReviewOut) => void;
}) {
  const [clauseDetail, setClauseDetail] = useState<ClauseDetailOut | null>(null);
  const [loadingClause, setLoadingClause] = useState(false);

  const [decision,  setDecision]  = useState<FindingStatus | "">("");
  const [notes,     setNotes]     = useState(finding.disposition_reason ?? "");
  const [comment,   setComment]   = useState(finding.review_comment ?? "");
  const [saving,    setSaving]    = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saved,     setSaved]     = useState(false);

  useEffect(() => {
    if (finding.clause_id) {
      setLoadingClause(true);
      getClauseDetail(contractId, versionId, finding.clause_id)
        .then(setClauseDetail)
        .catch(() => null)
        .finally(() => setLoadingClause(false));
    }
  }, [finding.clause_id, contractId, versionId]);

  async function handleDecision() {
    if (!decision) return;
    setSaving(true); setSaveError("");
    try {
      const body: FindingReviewUpdate = {
        status: decision,
        disposition_reason: notes || undefined,
        review_comment: comment || undefined,
      };
      const updated = await updateFinding(contractId, versionId, finding.finding_key, body);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      onSaved(updated);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Speichern fehlgeschlagen.");
    } finally {
      setSaving(false);
    }
  }

  const srMatches = clauseDetail?.sr_matches ?? [];
  const ai = clauseDetail?.obligation_assessment as Record<string, unknown> | null ?? null;
  const obligationAssessment = clauseDetail?.obligation_assessment;

  return (
    <div className="finding-detail" style={{ display: "grid", gap: "0.875rem" }}>

      {/* ── 1. Vertragsklausel (original language) ─────────────────────── */}
      {finding.clause_id && (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.35rem" }}>
            <span style={{ fontSize: "0.75rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-muted)" }}>
              Vertragsklausel
            </span>
            <Link
              href={`/contracts/${contractId}/versions/${versionId}/clauses/${encodeURIComponent(finding.clause_id)}`}
              className="link"
              style={{ fontSize: "0.8rem" }}
            >
              {finding.clause_id} →
            </Link>
          </div>
          {loadingClause ? (
            <div className="text-muted" style={{ fontSize: "0.85rem" }}>Lädt Klausel…</div>
          ) : clauseDetail?.text ? (
            <blockquote className="clause-excerpt" style={{ maxHeight: "8rem", overflowY: "auto", fontSize: "0.875rem" }}>
              {clauseDetail.text}
            </blockquote>
          ) : (
            <p className="text-muted" style={{ fontSize: "0.85rem" }}>{finding.text_preview ?? "—"}</p>
          )}
        </div>
      )}

      {/* ── 2. Verpflichtungsanalyse ───────────────────────────────────── */}
      {(obligationAssessment || finding.recommended_action) && (
        <div style={{ padding: "0.6rem 0.75rem", background: "var(--color-surface)", borderRadius: "0.375rem", border: "1px solid var(--color-border)" }}>
          <p style={{ fontSize: "0.75rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-muted)", marginBottom: "0.35rem" }}>
            Verpflichtungsanalyse
          </p>
          {obligationAssessment && (
            <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: "0.3rem" }}>
              <span className="tag">{obligationAssessment.assessment?.replace(/_/g, " ")}</span>
              {obligationAssessment.severity && (
                <span className={severityBadge(obligationAssessment.severity)}>{obligationAssessment.severity}</span>
              )}
              {(ai as any)?.llm_used === true  && <span className="badge badge--blue"  style={{ fontSize: "0.7rem" }}>KI</span>}
              {(ai as any)?.llm_used === false && <span className="badge badge--gray"  style={{ fontSize: "0.7rem" }}>Regelbasiert</span>}
            </div>
          )}
          {obligationAssessment?.reason && (
            <p style={{ fontSize: "0.875rem", marginBottom: "0.3rem" }}>{obligationAssessment.reason}</p>
          )}
          {/* Recommended action */}
          {finding.recommended_action && (
            <div className="info-box" style={{ margin: "0.3rem 0 0", fontSize: "0.875rem" }}>
              <strong>Empfohlene Maßnahme:</strong> {finding.recommended_action}
            </div>
          )}
        </div>
      )}

      {/* ── 3. Regulatorische Treffer ──────────────────────────────────── */}
      {srMatches.length > 0 && (
        <div>
          <p style={{ fontSize: "0.75rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-muted)", marginBottom: "0.35rem" }}>
            Regulatorische Treffer ({srMatches.length})
          </p>
          <div style={{ display: "grid", gap: "0.3rem" }}>
            {srMatches.slice(0, 4).map((m, i) => (
              <div key={i} style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", alignItems: "center", padding: "0.35rem 0.5rem", background: "var(--color-surface)", borderRadius: "0.375rem", border: "1px solid var(--color-border)", fontSize: "0.8rem" }}>
                <span className="mono" style={{ fontSize: "0.78rem" }}>{m.sr_id}</span>
                <span className="tag">{m.framework}</span>
                {m.match_type === "DIRECT_MATCH"
                  ? <span className="badge badge--green" style={{ fontSize: "0.7rem" }}>Direkter Treffer</span>
                  : <span className="badge badge--gray"  style={{ fontSize: "0.7rem" }}>Indirekter Treffer</span>}
                {m.confidence_bucket && <span className="meta-chip" style={{ fontSize: "0.7rem" }}>{m.confidence_bucket}</span>}
                {m.decision_delta && m.decision_delta !== "none" && (
                  <span className="badge badge--yellow" style={{ fontSize: "0.7rem" }}>delta: {m.decision_delta}</span>
                )}
                {m.sr_title && <span style={{ color: "var(--color-muted)", fontSize: "0.78rem" }}>{m.sr_title}</span>}
                {m.extracted_evidence && (
                  <span style={{ fontStyle: "italic", fontSize: "0.75rem" }}>&ldquo;{m.extracted_evidence}&rdquo;</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 4. Prüferentscheidung ──────────────────────────────────────── */}
      {!isViewer && (
        <div style={{ borderTop: "2px solid var(--color-border)", paddingTop: "0.75rem" }}>
          <p style={{ fontSize: "0.75rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-muted)", marginBottom: "0.5rem" }}>
            Prüferentscheidung
          </p>
          {saved     && <div className="success-box" style={{ marginBottom: "0.5rem" }}>Entscheidung gespeichert.</div>}
          {saveError && <div className="error-box"   style={{ marginBottom: "0.5rem" }}>{saveError}</div>}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.35rem", marginBottom: "0.5rem" }}>
            {REVIEWER_DECISIONS.map((d) => (
              <button
                key={`${d.label}-${d.value}`}
                className={`btn btn-sm ${decision === d.value && REVIEWER_DECISIONS.find(x => x.value === decision && x.label === d.label) ? "btn-primary" : "btn-outline"}`}
                style={{ textAlign: "left", justifyContent: "flex-start", fontSize: "0.78rem" }}
                onClick={() => setDecision(d.value)}
                disabled={saving}
                title={d.description}
              >
                {d.label}
              </button>
            ))}
          </div>

          {decision && (
            <p style={{ fontSize: "0.8rem", color: "var(--color-muted)", marginBottom: "0.4rem" }}>
              {REVIEWER_DECISIONS.find((d) => d.value === decision)?.description}
            </p>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.4rem", marginBottom: "0.5rem" }}>
            <textarea
              className="workflow-notes"
              rows={2}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              disabled={saving}
              placeholder="Prüfungskommentar (optional)…"
            />
            <textarea
              className="workflow-notes"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              disabled={saving}
              placeholder="Begründung der Entscheidung (optional)…"
            />
          </div>

          <button
            className="btn btn-sm btn-primary"
            onClick={handleDecision}
            disabled={!decision || saving}
          >
            {saving ? "Speichern…" : "Entscheidung erfassen"}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Finding row ───────────────────────────────────────────────────────────────

function FindingRow({
  finding, contractId, versionId, isViewer, onSaved,
}: {
  finding: FindingReviewOut;
  contractId: string;
  versionId: number;
  isViewer: boolean;
  onSaved: (updated: FindingReviewOut) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const priority = (finding.review_priority ?? finding.severity ?? "").toUpperCase();

  return (
    <>
      <tr
        className={expanded ? "finding-row finding-row--expanded" : "finding-row"}
        style={{ cursor: "pointer" }}
        onClick={() => setExpanded((x) => !x)}
      >
        <td>{priority && <span className={severityBadge(priority)}>{priority}</span>}</td>
        <td>
          {finding.clause_id
            ? <span className="mono" style={{ fontSize: "0.85rem" }}>{finding.clause_id}</span>
            : "—"}
        </td>
        <td className="preview-cell" style={{ maxWidth: "14rem" }}>
          <span style={{ fontSize: "0.82rem" }}>{finding.text_preview ?? "—"}</span>
        </td>
        <td>
          {finding.topic
            ? <span className="tag" style={{ fontSize: "0.78rem" }}>{topicLabel(finding.topic)}</span>
            : <span className="text-muted">—</span>}
        </td>
        <td><span className={severityBadge(finding.severity)}>{finding.severity ?? "—"}</span></td>
        <td className="preview-cell" style={{ maxWidth: "13rem" }}>
          {finding.recommended_action
            ? <span style={{ fontSize: "0.82rem" }}>{finding.recommended_action.slice(0, 100)}{finding.recommended_action.length > 100 ? "…" : ""}</span>
            : <span className="text-muted">—</span>}
        </td>
        <td style={{ whiteSpace: "nowrap" }}>
          {finding.ai_used === true  && <span className="badge badge--blue" style={{ fontSize: "0.7rem" }}>KI</span>}
          {finding.ai_used === false && <span className="badge badge--gray" style={{ fontSize: "0.7rem" }}>det.</span>}
          {finding.ai_used == null   && <span className="text-muted"       style={{ fontSize: "0.7rem" }}>—</span>}
          {finding.confidence_bucket && (
            <span className="meta-chip" style={{ fontSize: "0.7rem", marginLeft: "0.25rem" }}>{finding.confidence_bucket}</span>
          )}
        </td>
        <td><span className={statusBadge(finding.status)}>{statusLabel(finding.status)}</span></td>
        <td style={{ fontSize: "0.82rem" }}>
          {finding.assigned_owner_role ?? (finding as any).assignee_name ?? "—"}
        </td>
        <td style={{ whiteSpace: "nowrap" }}>
          <button className="btn btn-xs btn-ghost" onClick={(e) => { e.stopPropagation(); setExpanded((x) => !x); }}>
            {expanded ? "▲" : "▼"}
          </button>
        </td>
      </tr>

      {expanded && (
        <tr>
          <td colSpan={10} style={{ padding: "0", background: "var(--color-surface-raised)" }}>
            <div style={{ padding: "1rem 1.25rem", borderBottom: "1px solid var(--color-border)" }}>
              <ReviewCard
                finding={finding}
                contractId={contractId}
                versionId={versionId}
                isViewer={isViewer}
                onSaved={onSaved}
              />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main content ───────────────────────────────────────────────────────────────

function FindingsContent({
  user, contractId, versionId,
}: {
  user: SessionUser; contractId: string; versionId: number;
}) {
  const [readiness, setReadiness] = useState<ApprovalReadinessOut | null>(null);
  const [findings,  setFindings]  = useState<FindingReviewOut[]>([]);
  const [total,     setTotal]     = useState(0);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState("");

  const [filterSeverity, setFilterSeverity] = useState("");
  const [filterStatus,   setFilterStatus]   = useState("");
  const [filterTopic,    setFilterTopic]    = useState("");

  async function load() {
    setLoading(true); setError("");
    try {
      const [read, lst] = await Promise.all([
        getApprovalReadiness(contractId, versionId).catch(() => null),
        listFindings(contractId, versionId, {
          severity: filterSeverity || undefined,
          status:   filterStatus   || undefined,
          topic:    filterTopic    || undefined,
        }),
      ]);
      setReadiness(read);
      setFindings(lst.findings);
      setTotal(lst.total);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Laden der Befunde fehlgeschlagen.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [contractId, versionId, filterSeverity, filterStatus, filterTopic]);

  function handleSaved(updated: FindingReviewOut) {
    setFindings((prev) => prev.map((f) => f.id === updated.id ? updated : f));
    getApprovalReadiness(contractId, versionId).then(setReadiness).catch(() => null);
  }

  function handleQuickFilter(severity: string, status: string) {
    setFilterSeverity(severity);
    setFilterStatus(status);
  }

  const isViewer = user.role === "VIEWER";

  const SEVERITY_ORDER: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };
  const STATUS_ORDER:   Record<string, number>  = { open: 0, in_review: 1, in_negotiation: 2, deferred: 3, resolved: 4, accepted_risk: 5, not_applicable: 6 };
  const sorted = [...findings].sort((a, b) => {
    const sa = SEVERITY_ORDER[(a.review_priority ?? a.severity ?? "").toUpperCase()] ?? 9;
    const sb = SEVERITY_ORDER[(b.review_priority ?? b.severity ?? "").toUpperCase()] ?? 9;
    if (sa !== sb) return sa - sb;
    return (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
  });

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <Link href={`/contracts/${contractId}`} className="breadcrumb">← {contractId}</Link>
            <h1>Prüf-Warteschlange — v{versionId}</h1>
            <p className="page-subtitle">Klappen Sie Zeilen auf, um Klauseltext, Verpflichtungsanalyse und Regulierungstreffer einzusehen und Entscheidungen zu erfassen.</p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Link href={`/contracts/${contractId}/versions/${versionId}/clauses`} className="btn btn-outline">
              Klausel-Explorer →
            </Link>
            <Link href={`/contracts/${contractId}/versions/${versionId}/report`} className="btn btn-outline">
              ← Risikobericht
            </Link>
          </div>
        </div>

        {readiness && (
          <ReadinessBanner
            readiness={readiness}
            contractId={contractId}
            versionId={versionId}
            onQuickFilter={handleQuickFilter}
          />
        )}

        {/* Filters */}
        <div className="filter-row">
          <select className="filter-select" value={filterSeverity} onChange={(e) => setFilterSeverity(e.target.value)}>
            <option value="">Alle Schweregrade</option>
            <option value="HIGH">Hoch</option>
            <option value="MEDIUM">Mittel</option>
            <option value="LOW">Niedrig</option>
          </select>
          <select className="filter-select" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            <option value="">Alle Status</option>
            <option value="open">Offen</option>
            <option value="in_review">In Prüfung</option>
            <option value="in_negotiation">In Verhandlung</option>
            <option value="deferred">Zurückgestellt</option>
            <option value="accepted_risk">Risiko akzeptiert</option>
            <option value="resolved">Erledigt</option>
            <option value="not_applicable">Nicht anwendbar</option>
          </select>
          <input
            className="filter-input"
            placeholder="Nach Thema filtern…"
            value={filterTopic}
            onChange={(e) => setFilterTopic(e.target.value)}
          />
          <span className="filter-count">{total} Befund{total !== 1 ? "e" : ""}</span>
        </div>

        {error   && <div className="error-box" style={{ marginTop: "1rem" }}>{error}</div>}
        {loading && <div className="loading"   style={{ marginTop: "1rem" }}>Laden…</div>}

        {!loading && sorted.length > 0 && (
          <div className="section">
            <div className="table-scroll">
              <table className="table findings-queue">
                <thead>
                  <tr>
                    <th>Priorität</th>
                    <th>Klausel</th>
                    <th>Vorschau</th>
                    <th>Thema</th>
                    <th>Schwere</th>
                    <th>Empfohlene Maßnahme</th>
                    <th>KI</th>
                    <th>Status</th>
                    <th>Verantwortlich</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((f) => (
                    <FindingRow
                      key={f.id}
                      finding={f}
                      contractId={contractId}
                      versionId={versionId}
                      isViewer={isViewer}
                      onSaved={handleSaved}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {!loading && sorted.length === 0 && !error && (
          <div className="empty-state" style={{ marginTop: "2rem" }}>
            Keine Befunde für den aktuellen Filter.
          </div>
        )}
      </main>
    </div>
  );
}

export default function FindingsPage({
  params,
}: {
  params: Promise<{ id: string; vid: string }>;
}) {
  const { id, vid } = use(params);
  return (
    <AuthGuard>
      {(user) => <FindingsContent user={user} contractId={id} versionId={Number(vid)} />}
    </AuthGuard>
  );
}
