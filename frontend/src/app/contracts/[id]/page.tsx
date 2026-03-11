"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  getContract,
  getContractStatus,
  getOrgProfile,
  getWorkflow,
  getContractHistory,
  updateReviewStatus,
  listAnalyses,
  triggerAnalysis,
  listVersions,
  uploadVersion,
  getApprovalReadiness,
  ContractOut,
  AnalysisOut,
  AnalysisStatusOut,
  AnalysisStage,
  OrgProfile,
  WorkflowOut,
  WorkflowEventOut,
  HistoryOut,
  ReviewStatus,
  ReviewDecision,
  ContractVersionOut,
  VersionListOut,
  ApprovalReadinessOut,
  ApprovalReadiness,
  READINESS_LABEL,
  READINESS_BADGE,
  READINESS_ORDER,
  ApiError,
  ForbiddenError,
} from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";

// ── Stage metadata ─────────────────────────────────────────────────────────────

const STAGE_ORDER: AnalysisStage[] = [
  "stage16_ingestion",
  "stage3_classification",
  "stage4_5_obligation_analysis",
  "stage5_clause_matching",
  "stage6_compliance",
  "stage8_remediation",
  "stage9_brief",
  "stage10_trace",
  "stage11_risk",
  "stage12_action_plan",
  "stage13_negotiation",
  "stage14_report",
  "done",
];

const STAGE_LABELS: Record<AnalysisStage, string> = {
  stage16_ingestion:           "Ingesting contract text",
  stage3_classification:       "Classifying contract type",
  stage4_5_obligation_analysis: "Analysing obligations",
  stage5_clause_matching:      "Matching clauses to requirements",
  stage6_compliance:           "Generating compliance report",
  stage8_remediation:          "Building remediation proposals",
  stage9_brief:                "Building negotiation brief",
  stage10_trace:               "Generating audit trace",
  stage11_risk:                "Scoring clause risks",
  stage12_action_plan:         "Composing action plan",
  stage13_negotiation:         "Packaging negotiation items",
  stage14_report:              "Compiling risk report",
  done:                        "Complete",
};

function stageIndex(stage: AnalysisStage | null): number {
  if (!stage) return -1;
  return STAGE_ORDER.indexOf(stage);
}

function progressPct(stage: AnalysisStage | null): number {
  if (!stage) return 0;
  const idx = stageIndex(stage);
  if (idx < 0) return 0;
  return Math.round(((idx + 1) / STAGE_ORDER.length) * 100);
}

// ── Badge helpers ──────────────────────────────────────────────────────────────

function statusBadge(status: string) {
  if (status === "analyzed" || status === "completed") return "badge badge--green";
  if (status === "failed") return "badge badge--red";
  if (status === "running" || status === "ingested") return "badge badge--blue";
  if (status === "pending") return "badge badge--yellow";
  return "badge badge--gray";
}

function riskBadge(risk: string | null) {
  if (risk === "HIGH")   return "badge badge--red";
  if (risk === "MEDIUM") return "badge badge--yellow";
  if (risk === "LOW")    return "badge badge--green";
  return "badge badge--gray";
}

// ── Analysis progress panel ────────────────────────────────────────────────────

function AnalysisProgress({ jobStatus }: { jobStatus: AnalysisStatusOut }) {
  const { status, current_stage, started_at, completed_at, error_message } = jobStatus;
  const isActive  = status === "pending" || status === "running";
  const isDone    = status === "completed";
  const isFailed  = status === "failed";
  const pct       = isDone ? 100 : progressPct(current_stage);
  const stageLabel = current_stage ? STAGE_LABELS[current_stage] ?? current_stage : null;

  return (
    <div className={`progress-panel ${isDone ? "progress-panel--done" : isFailed ? "progress-panel--failed" : "progress-panel--running"}`}>
      <div className="progress-panel-header">
        <div className="progress-status-row">
          {isActive && <span className="spinner" aria-label="Running" />}
          {isDone   && <span className="progress-icon progress-icon--done">✓</span>}
          {isFailed && <span className="progress-icon progress-icon--fail">✗</span>}
          <span className="progress-label">
            {isDone   && "Analysis complete"}
            {isFailed && "Analysis failed"}
            {isActive && (stageLabel ?? "Starting…")}
          </span>
          <span className={statusBadge(status)}>{status}</span>
        </div>

        {isActive && stageLabel && (
          <div className="progress-stage-name">
            Stage: <strong>{stageLabel}</strong>
          </div>
        )}

        {/* Progress bar */}
        <div className="progress-bar-track">
          <div
            className={`progress-bar-fill ${isDone ? "progress-bar-fill--done" : isFailed ? "progress-bar-fill--fail" : ""}`}
            style={{ width: `${pct}%` }}
          />
        </div>

        {/* Stage breadcrumbs */}
        <div className="stage-trail">
          {STAGE_ORDER.slice(0, -1).map((s) => {
            const idx     = stageIndex(s);
            const currIdx = stageIndex(current_stage);
            const done    = isDone || idx < currIdx;
            const active  = !isDone && idx === currIdx;
            return (
              <span
                key={s}
                className={`stage-chip ${done ? "stage-chip--done" : active ? "stage-chip--active" : "stage-chip--pending"}`}
                title={STAGE_LABELS[s]}
              >
                {done ? "✓" : active ? "…" : "·"}
              </span>
            );
          })}
        </div>
      </div>

      {/* Timestamps */}
      <div className="progress-meta">
        {started_at && (
          <span>Started: {new Date(started_at).toLocaleTimeString()}</span>
        )}
        {completed_at && (
          <span>Completed: {new Date(completed_at).toLocaleTimeString()}</span>
        )}
      </div>

      {/* Error */}
      {isFailed && error_message && (
        <div className="error-box" style={{ marginTop: "0.75rem" }}>
          {error_message}
        </div>
      )}
    </div>
  );
}

// ── Workflow constants ─────────────────────────────────────────────────────────

const REVIEW_STATUSES: ReviewStatus[] = [
  "analysis_completed", "under_review", "in_negotiation",
  "approved", "rejected", "archived",
];
const ADMIN_ONLY_STATUSES: ReviewStatus[] = ["approved", "rejected", "archived"];

const REVIEW_STATUS_LABEL: Record<ReviewStatus, string> = {
  uploaded:             "Uploaded",
  ingested:             "Ingested",
  analysis_completed:   "Analysis complete",
  under_review:         "Under review",
  in_negotiation:       "In negotiation",
  approved:             "Approved",
  rejected:             "Rejected",
  archived:             "Archived",
};

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

const DECISION_OPTIONS: { value: ReviewDecision; label: string }[] = [
  { value: "none",                label: "No decision" },
  { value: "approve",             label: "Approve" },
  { value: "conditional_approve", label: "Conditional approve" },
  { value: "reject",              label: "Reject" },
];

// ── WorkflowPanel ─────────────────────────────────────────────────────────────

function WorkflowPanel({
  workflow,
  canEdit,
  isAdmin,
  hasCompletedAnalysis,
  latestRisk,
  readiness,
  saving,
  saveError,
  saveSuccess,
  onSave,
}: {
  workflow:              WorkflowOut | null;
  canEdit:               boolean;
  isAdmin:               boolean;
  hasCompletedAnalysis:  boolean;
  latestRisk:            string | null;
  readiness:             ApprovalReadinessOut | null;
  saving:                boolean;
  saveError:             string;
  saveSuccess:           boolean;
  onSave: (rs: ReviewStatus, rd: ReviewDecision, ownerId: number | null, notes: string) => void;
}) {
  const [selStatus,   setSelStatus]   = useState<ReviewStatus>(workflow?.review_status ?? "analysis_completed");
  const [selDecision, setSelDecision] = useState<ReviewDecision>(workflow?.review_decision ?? "none");
  const [notes,       setNotes]       = useState(workflow?.internal_notes ?? "");

  useEffect(() => {
    if (workflow) {
      setSelStatus(workflow.review_status);
      setSelDecision(workflow.review_decision);
      setNotes(workflow.internal_notes ?? "");
    }
  }, [workflow]);

  const approvalBlocked = selStatus === "approved" && !hasCompletedAnalysis;

  // Readiness-based gating
  const r = readiness?.approval_readiness ?? null;
  const counts = readiness?.counts ?? null;

  const wantsApproval         = selStatus === "approved";
  const wantsConditional      = selDecision === "conditional_approve";
  const wantsArchive          = selStatus === "archived";
  const currentStatus         = workflow?.review_status ?? "";

  const readinessBlocked =
    wantsApproval && r !== null && r !== "ready_for_approval";
  const conditionalBlocked =
    wantsConditional && r !== null &&
    READINESS_ORDER.indexOf(r) < READINESS_ORDER.indexOf("ready_for_conditional_approval");
  const archiveBlocked =
    wantsArchive && !["approved", "rejected"].includes(currentStatus);

  const canSave = !approvalBlocked && !readinessBlocked && !conditionalBlocked && !archiveBlocked;

  return (
    <div className="workflow-panel" style={{ marginTop: "1.5rem" }}>
      <div className="workflow-panel-header">
        <h2>Review workflow</h2>
        {workflow && (
          <span className={REVIEW_STATUS_CLASS[workflow.review_status]}>
            {REVIEW_STATUS_LABEL[workflow.review_status]}
          </span>
        )}
        {r && (
          <span className={READINESS_BADGE[r as ApprovalReadiness]} style={{ marginLeft: "0.5rem" }}>
            {READINESS_LABEL[r as ApprovalReadiness]}
          </span>
        )}
      </div>

      {/* Current state info (read-only) */}
      {workflow && (
        <div className="workflow-meta-row">
          {workflow.review_owner_name && (
            <span className="workflow-meta-item">
              <span className="workflow-meta-label">Owner:</span> {workflow.review_owner_name}
            </span>
          )}
          {workflow.reviewed_at && (
            <span className="workflow-meta-item">
              <span className="workflow-meta-label">Reviewed:</span>{" "}
              {new Date(workflow.reviewed_at).toLocaleString()}
            </span>
          )}
          {workflow.review_decision !== "none" && (
            <span className="workflow-meta-item">
              <span className="workflow-meta-label">Decision:</span>{" "}
              <strong>{workflow.review_decision.replace(/_/g, " ")}</strong>
            </span>
          )}
        </div>
      )}

      {!canEdit ? (
        <p className="workflow-readonly-note">
          Read-only — ADMIN or ANALYST role required to update workflow.
        </p>
      ) : (
        <div className="workflow-form">
          {saveSuccess && (
            <div className="success-box" style={{ marginBottom: "0.75rem" }}>
              Workflow updated.
            </div>
          )}
          {saveError && (
            <div className="error-box" style={{ marginBottom: "0.75rem" }}>
              {saveError}
            </div>
          )}

          {approvalBlocked && (
            <div className="warn-box" style={{ marginBottom: "0.75rem" }}>
              <strong>Cannot approve:</strong> A completed analysis is required before approval.
            </div>
          )}
          {readinessBlocked && counts && (
            <div className="warn-box" style={{ marginBottom: "0.75rem" }}>
              <strong>Approval blocked:</strong> {counts.high_open} HIGH and {counts.medium_open} MEDIUM findings remain unresolved.
              Current readiness: <strong>{READINESS_LABEL[r as ApprovalReadiness]}</strong>.
              All findings must be resolved, accepted, or marked not_applicable before approval.
            </div>
          )}
          {conditionalBlocked && counts && !readinessBlocked && (
            <div className="warn-box" style={{ marginBottom: "0.75rem" }}>
              <strong>Conditional approval blocked:</strong> {counts.high_open} HIGH findings remain unresolved.
              All HIGH findings must be closed for conditional approval.
            </div>
          )}
          {wantsConditional && !conditionalBlocked && counts && counts.medium_open > 0 && (
            <div className="info-box" style={{ marginBottom: "0.75rem" }}>
              <strong>Conditional approval:</strong> {counts.medium_open} MEDIUM findings remain in negotiation.
            </div>
          )}
          {archiveBlocked && (
            <div className="warn-box" style={{ marginBottom: "0.75rem" }}>
              <strong>Cannot archive:</strong> Version must be approved or rejected first.
            </div>
          )}

          <div className="workflow-fields">
            <div className="form-group">
              <label className="form-label">Review status</label>
              <select
                className="filter-select"
                value={selStatus}
                onChange={(e) => setSelStatus(e.target.value as ReviewStatus)}
                disabled={saving}
              >
                {REVIEW_STATUSES
                  .filter((s) => isAdmin || !ADMIN_ONLY_STATUSES.includes(s))
                  .map((s) => (
                    <option key={s} value={s}>{REVIEW_STATUS_LABEL[s]}</option>
                  ))}
              </select>
            </div>

            {isAdmin && (
              <div className="form-group">
                <label className="form-label">Decision</label>
                <select
                  className="filter-select"
                  value={selDecision}
                  onChange={(e) => setSelDecision(e.target.value as ReviewDecision)}
                  disabled={saving}
                >
                  {DECISION_OPTIONS.map((d) => (
                    <option key={d.value} value={d.value}>{d.label}</option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="form-group" style={{ marginTop: "0.75rem" }}>
            <label className="form-label">Internal notes</label>
            <textarea
              className="workflow-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              disabled={saving}
              rows={3}
              placeholder="Optional review notes…"
            />
          </div>

          <button
            className="btn btn-primary"
            style={{ marginTop: "0.75rem" }}
            disabled={saving || !canSave}
            onClick={() => onSave(selStatus, selDecision, workflow?.review_owner_user_id ?? null, notes)}
          >
            {saving ? "Saving…" : "Save workflow"}
          </button>
        </div>
      )}
    </div>
  );
}

// ── HistoryTimeline ────────────────────────────────────────────────────────────

const WF_EVENT_ICON: Record<string, string> = {
  uploaded:           "↑",
  ingested:           "→",
  analysis_completed: "✓",
  under_review:       "👁",
  in_negotiation:     "↔",
  approved:           "✔",
  rejected:           "✗",
  archived:           "📦",
};

function HistoryTimeline({ history }: { history: HistoryOut }) {
  type TimelineEntry =
    | { kind: "upload"; ts: string }
    | { kind: "analysis"; ts: string; status: string; risk: string | null; id: number }
    | { kind: "workflow"; event: WorkflowEventOut };

  const entries: TimelineEntry[] = [
    { kind: "upload", ts: history.uploaded_at },
    ...history.analyses.map((a) => ({
      kind:   "analysis" as const,
      ts:     a.created_at,
      status: a.status,
      risk:   a.overall_risk,
      id:     a.id,
    })),
    ...history.workflow_events.map((e) => ({ kind: "workflow" as const, event: e })),
  ].sort((a, b) => {
    const ta = a.kind === "workflow" ? a.event.created_at : a.ts;
    const tb = b.kind === "workflow" ? b.event.created_at : b.ts;
    return new Date(ta).getTime() - new Date(tb).getTime();
  });

  return (
    <div className="timeline">
      {entries.map((entry, i) => {
        if (entry.kind === "upload") {
          return (
            <div key={`upload-${i}`} className="timeline-event">
              <div className="timeline-icon timeline-icon--gray">↑</div>
              <div className="timeline-body">
                <span className="timeline-label">Contract uploaded</span>
                <span className="timeline-ts">{new Date(entry.ts).toLocaleString()}</span>
              </div>
            </div>
          );
        }
        if (entry.kind === "analysis") {
          const cls = entry.status === "completed" ? "timeline-icon--green"
                    : entry.status === "failed"    ? "timeline-icon--red"
                    : "timeline-icon--gray";
          return (
            <div key={`analysis-${entry.id}`} className="timeline-event">
              <div className={`timeline-icon ${cls}`}>⚙</div>
              <div className="timeline-body">
                <span className="timeline-label">
                  Analysis #{entry.id} — {entry.status}
                  {entry.risk && <> · <strong>{entry.risk}</strong> risk</>}
                </span>
                <span className="timeline-ts">{new Date(entry.ts).toLocaleString()}</span>
              </div>
            </div>
          );
        }
        // workflow event
        const ev = entry.event;
        const icon = WF_EVENT_ICON[ev.new_status] ?? "•";
        const isTerminal = ev.new_status === "approved" || ev.new_status === "rejected";
        const iconClass = ev.new_status === "approved" ? "timeline-icon--green"
                        : ev.new_status === "rejected" ? "timeline-icon--red"
                        : "timeline-icon--blue";
        return (
          <div key={`wf-${ev.id}`} className="timeline-event">
            <div className={`timeline-icon ${iconClass}`}>{icon}</div>
            <div className="timeline-body">
              <span className="timeline-label">
                Status → <strong>{REVIEW_STATUS_LABEL[ev.new_status]}</strong>
                {ev.new_decision && ev.new_decision !== "none" && (
                  <> · decision: <strong>{ev.new_decision.replace(/_/g, " ")}</strong></>
                )}
                {ev.changed_by_name && <> by {ev.changed_by_name}</>}
              </span>
              {ev.notes && <span className="timeline-notes">{ev.notes}</span>}
              <span className="timeline-ts">{new Date(ev.created_at).toLocaleString()}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── VersionsPanel ─────────────────────────────────────────────────────────────

function VersionsPanel({
  contractId,
  versions,
  currentVersionId,
  canUpload,
  onUpload,
  uploading,
  uploadError,
}: {
  contractId:       string;
  versions:         ContractVersionOut[];
  currentVersionId: number | null;
  canUpload:        boolean;
  onUpload:         (file: File) => void;
  uploading:        boolean;
  uploadError:      string;
}) {
  const fileRef = useRef<HTMLInputElement>(null);

  function riskClass(r: string | null) {
    if (!r) return "badge badge--gray";
    const u = r.toUpperCase();
    if (u === "HIGH")   return "badge badge--red";
    if (u === "MEDIUM") return "badge badge--yellow";
    if (u === "LOW")    return "badge badge--green";
    return "badge badge--gray";
  }

  return (
    <div className="versions-panel" style={{ marginTop: "1.5rem" }}>
      <div className="versions-panel-header">
        <h2>Versions <span className="count">({versions.length})</span></h2>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          {versions.length >= 2 && (
            <Link
              href={`/contracts/${contractId}/compare?from=${versions[0].version_number}&to=${versions[versions.length - 1].version_number}`}
              className="btn btn-sm btn-outline"
            >
              Compare versions
            </Link>
          )}
          {canUpload && (
            <>
              <button
                className="btn btn-sm btn-primary"
                disabled={uploading}
                onClick={() => fileRef.current?.click()}
              >
                {uploading ? "Uploading…" : "Upload revised version"}
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.docx,.txt"
                style={{ display: "none" }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onUpload(f);
                  e.target.value = "";
                }}
              />
            </>
          )}
        </div>
      </div>

      {uploadError && (
        <div className="error-box" style={{ marginBottom: "0.75rem" }}>{uploadError}</div>
      )}

      <div className="version-list">
        {versions.map((v) => {
          const isCurrent      = v.id === currentVersionId;
          const hasBundleState = v.review_status === "approved"
                              || v.review_status === "rejected"
                              || v.review_status === "archived";
          const bundleDecision = v.review_decision !== "none" ? v.review_decision.replace(/_/g, " ") : null;
          return (
            <div key={v.id} className={`version-item${isCurrent ? " version-item--current" : ""}`}>
              <div className="version-badge">v{v.version_number}</div>
              <div className="version-info">
                <span className="version-filename">{v.original_filename}</span>
                {isCurrent && <span className="badge badge--blue" style={{ marginLeft: "0.5rem" }}>current</span>}
                {hasBundleState && (
                  <span
                    className={v.review_status === "approved" ? "badge badge--green" : "badge badge--red"}
                    style={{ marginLeft: "0.5rem" }}
                    title="Closure bundle available"
                  >
                    📦 {bundleDecision ?? v.review_status}
                  </span>
                )}
                <span className="text-muted" style={{ marginLeft: "0.5rem" }}>
                  {new Date(v.uploaded_at).toLocaleDateString()}
                </span>
              </div>
              <div className="version-meta">
                {v.clauses_extracted != null && (
                  <span className="text-muted">{v.clauses_extracted} clauses</span>
                )}
                {v.latest_overall_risk && (
                  <span className={riskClass(v.latest_overall_risk)}>
                    {v.latest_overall_risk}
                  </span>
                )}
              </div>
              <div className="version-actions">
                {v.latest_overall_risk && (
                  <Link
                    href={`/contracts/${contractId}/versions/${v.id}/report`}
                    className="btn btn-xs btn-outline"
                  >
                    Report
                  </Link>
                )}
                {v.latest_overall_risk && (
                  <Link
                    href={`/contracts/${contractId}/versions/${v.id}/clauses`}
                    className="btn btn-xs btn-outline"
                    title="Browse extracted clauses"
                  >
                    Clauses
                  </Link>
                )}
                {v.latest_overall_risk && (
                  <Link
                    href={`/contracts/${contractId}/versions/${v.id}/findings`}
                    className="btn btn-xs btn-outline"
                  >
                    Findings
                  </Link>
                )}
                {hasBundleState && (
                  <Link
                    href={`/contracts/${contractId}/versions/${v.id}/report`}
                    className="btn btn-xs btn-outline"
                    title="View closure bundle in report page"
                  >
                    📦 Bundle
                  </Link>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

function ContractDetailContent({
  user,
  contractId,
}: {
  user: SessionUser;
  contractId: string;
}) {
  const [contract,    setContract]   = useState<ContractOut | null>(null);
  const [jobStatus,   setJobStatus]  = useState<AnalysisStatusOut | null>(null);
  const [analyses,    setAnalyses]   = useState<AnalysisOut[]>([]);
  const [orgProfile,  setOrgProfile] = useState<OrgProfile | null>(null);
  const [workflow,    setWorkflow]   = useState<WorkflowOut | null>(null);
  const [history,     setHistory]    = useState<HistoryOut | null>(null);
  const [versions,    setVersions]   = useState<ContractVersionOut[]>([]);
  const [readiness,   setReadiness]  = useState<ApprovalReadinessOut | null>(null);
  const [pageError,   setPageError]  = useState("");
  const [actError,    setActError]   = useState("");
  const [loading,     setLoading]    = useState(true);
  const [triggering,  setTriggering] = useState(false);
  const [wfSaving,    setWfSaving]   = useState(false);
  const [wfError,     setWfError]    = useState("");
  const [wfSuccess,   setWfSuccess]  = useState(false);
  const [vUploadErr,  setVUploadErr] = useState("");
  const [vUploading,  setVUploading] = useState(false);

  // Polling is active while status is pending or running
  const isJobActive = jobStatus?.status === "pending" || jobStatus?.status === "running";

  // ── Initial data load ──────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const [c, analysesList, profile, wf, hist, vList] = await Promise.all([
          getContract(contractId),
          listAnalyses(contractId).catch(() => [] as AnalysisOut[]),
          getOrgProfile().catch(() => null),
          getWorkflow(contractId).catch(() => null),
          getContractHistory(contractId).catch(() => null),
          listVersions(contractId).catch(() => ({ total: 0, versions: [] } as VersionListOut)),
        ]);
        if (cancelled) return;
        setContract(c);
        setAnalyses(analysesList);
        setOrgProfile(profile);
        setWorkflow(wf);
        setHistory(hist);
        setVersions(vList.versions);
        // Fetch readiness for the current version
        if (c.current_version_id) {
          getApprovalReadiness(contractId, c.current_version_id)
            .then(setReadiness)
            .catch(() => null);
        }

        // Seed jobStatus from the latest analysis if one exists
        if (analysesList.length > 0) {
          const latest = analysesList[0];
          setJobStatus({
            analysis_id:              latest.id,
            contract_id:              latest.contract_id,
            status:                   latest.status,
            current_stage:            latest.current_stage,
            started_at:               latest.started_at,
            completed_at:             latest.completed_at,
            error_message:            latest.error_message,
            outputs_ready:            latest.outputs_ready,
            org_profile_version_hash: null,
          });
        }
      } catch (err: unknown) {
        if (!cancelled) setPageError(err instanceof Error ? err.message : "Failed to load.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    init();
    return () => { cancelled = true; };
  }, [contractId]);

  // ── Status polling ─────────────────────────────────────────────────────────

  const pollStatus = useCallback(async () => {
    try {
      const s = await getContractStatus(contractId);
      setJobStatus(s);
      // Refresh analyses, workflow, and history whenever a run completes
      if (s.status === "completed" || s.status === "failed") {
        const [list, wf, hist] = await Promise.all([
          listAnalyses(contractId).catch(() => [] as AnalysisOut[]),
          getWorkflow(contractId).catch(() => null),
          getContractHistory(contractId).catch(() => null),
        ]);
        setAnalyses(list);
        setWorkflow(wf);
        setHistory(hist);
      }
    } catch {
      // 404 = no analyses yet; ignore silently
    }
  }, [contractId]);

  usePolling(pollStatus, 3000, isJobActive);

  // ── Trigger analysis ───────────────────────────────────────────────────────

  async function handleAnalyze() {
    setActError("");
    setTriggering(true);
    try {
      const a = await triggerAnalysis(contractId);
      setJobStatus({
        analysis_id:              a.id,
        contract_id:              a.contract_id,
        status:                   a.status,
        current_stage:            a.current_stage,
        started_at:               a.started_at,
        completed_at:             a.completed_at,
        error_message:            a.error_message,
        outputs_ready:            a.outputs_ready,
        org_profile_version_hash: null,
      });
    } catch (err: unknown) {
      if (err instanceof ForbiddenError) {
        setActError("You don't have permission to run analysis.");
      } else if (err instanceof ApiError) {
        setActError(err.message);
      } else {
        setActError("Failed to start analysis.");
      }
    } finally {
      setTriggering(false);
    }
  }

  // ── Workflow save ───────────────────────────────────────────────────────────

  async function handleWorkflowSave(
    rs: ReviewStatus,
    rd: ReviewDecision,
    ownerId: number | null,
    notes: string,
  ) {
    setWfError("");
    setWfSuccess(false);
    setWfSaving(true);
    try {
      await updateReviewStatus(contractId, {
        review_status:        rs,
        review_decision:      rd,
        review_owner_user_id: ownerId,
        internal_notes:       notes,
      });
      // Refresh workflow and history
      const [wf, hist] = await Promise.all([
        getWorkflow(contractId).catch(() => null),
        getContractHistory(contractId).catch(() => null),
      ]);
      setWorkflow(wf);
      setHistory(hist);
      setWfSuccess(true);
      setTimeout(() => setWfSuccess(false), 3000);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setWfError(err.message);
      } else {
        setWfError("Failed to update workflow.");
      }
    } finally {
      setWfSaving(false);
    }
  }

  // ── Upload revised version ─────────────────────────────────────────────────

  async function handleVersionUpload(file: File) {
    setVUploadErr("");
    setVUploading(true);
    try {
      await uploadVersion(contractId, file);
      const vList = await listVersions(contractId);
      setVersions(vList.versions);
    } catch (err: unknown) {
      setVUploadErr(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setVUploading(false);
    }
  }

  // ── Derived state ──────────────────────────────────────────────────────────

  const canAnalyze      = user.role === "ADMIN" || user.role === "ANALYST";
  const canEditWorkflow = user.role === "ADMIN" || user.role === "ANALYST";
  const isAdmin         = user.role === "ADMIN";
  const profileMissing  = orgProfile === null;
  const isRunning       = isJobActive || triggering;
  const outputsReady    = jobStatus?.outputs_ready === true;
  const isArchived      = workflow?.review_status === "archived";

  // ── Render ─────────────────────────────────────────────────────────────────

  if (loading) return (
    <div className="page">
      <Nav user={user} />
      <main className="main"><div className="loading">Loading…</div></main>
    </div>
  );

  if (pageError) return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="error-box">{pageError}</div>
        <Link href="/contracts" className="btn btn-outline btn-sm">← Contracts</Link>
      </main>
    </div>
  );

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">

        {/* Header */}
        <div className="page-header">
          <div>
            <Link href="/contracts" className="breadcrumb">← Contracts</Link>
            <h1>{contract?.filename}</h1>
          </div>
        </div>

        {/* Contract info */}
        <div className="detail-grid">
          <div className="detail-card">
            <h3>Contract details</h3>
            <table className="detail-table">
              <tbody>
                <tr><th>Contract ID</th><td className="mono">{contract?.contract_id}</td></tr>
                <tr><th>Format</th><td>{contract?.file_format?.toUpperCase()}</td></tr>
                <tr>
                  <th>Status</th>
                  <td><span className={statusBadge(contract?.status ?? "")}>{contract?.status}</span></td>
                </tr>
                <tr><th>Clauses extracted</th><td>{contract?.clauses_extracted ?? "—"}</td></tr>
                <tr>
                  <th>Uploaded</th>
                  <td>{contract ? new Date(contract.created_at).toLocaleString() : "—"}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Analysis summary (shown once completed) */}
          {jobStatus?.status === "completed" && analyses[0] && (
            <div className="detail-card">
              <h3>Analysis results</h3>
              <table className="detail-table">
                <tbody>
                  <tr>
                    <th>Overall risk</th>
                    <td>
                      <span className={riskBadge(analyses[0].overall_risk)}>
                        {analyses[0].overall_risk ?? "—"}
                      </span>
                    </td>
                  </tr>
                  <tr><th>Total clauses</th><td>{analyses[0].total_clauses ?? "—"}</td></tr>
                  <tr><th>Total findings</th><td>{analyses[0].total_findings ?? "—"}</td></tr>
                  <tr>
                    <th>Risk breakdown</th>
                    <td>
                      <span className="badge badge--red">H: {analyses[0].high_risk_clauses ?? 0}</span>{" "}
                      <span className="badge badge--yellow">M: {analyses[0].medium_risk_clauses ?? 0}</span>{" "}
                      <span className="badge badge--green">L: {analyses[0].low_risk_clauses ?? 0}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Compliance profile — blocking banner if missing, info strip if set */}
        {profileMissing ? (
          <div className="warn-box" style={{ marginBottom: "1rem" }}>
            <strong>No compliance profile configured.</strong>{" "}
            Analysis cannot be started until a compliance profile is set up.{" "}
            <a href="/settings/customer-profile">Configure profile →</a>
          </div>
        ) : (
          <div className="profile-info-box">
            <span className="profile-info-label">Analysis profile:</span>
            <span className="profile-info-org">{orgProfile!.organization_name}</span>
            <span className="profile-info-sep">·</span>
            <span className="profile-info-frameworks">
              {orgProfile!.regulatory_frameworks.length > 0
                ? orgProfile!.regulatory_frameworks.join(", ")
                : "No frameworks"}
            </span>
            {jobStatus?.org_profile_version_hash && (
              <>
                <span className="profile-info-sep">·</span>
                <span className="profile-info-hash" title="Profile snapshot hash used for this analysis">
                  snapshot {jobStatus.org_profile_version_hash}
                </span>
              </>
            )}
          </div>
        )}

        {/* Progress panel — shown whenever a job exists */}
        {jobStatus && <AnalysisProgress jobStatus={jobStatus} />}

        {/* Action row */}
        <div className="action-row" style={{ marginTop: "1.25rem" }}>
          {canAnalyze && (
            <button
              className="btn btn-primary"
              onClick={handleAnalyze}
              disabled={isRunning || profileMissing}
              title={
                profileMissing
                  ? "Configure a compliance profile before running analysis"
                  : isRunning
                    ? "Analysis in progress"
                    : undefined
              }
            >
              {triggering
                ? "Starting…"
                : isJobActive
                  ? "Analysis in progress…"
                  : jobStatus
                    ? "Re-run analysis"
                    : "Run analysis"}
            </button>
          )}

          <Link
            href={outputsReady ? `/contracts/${contractId}/report` : "#"}
            className={`btn ${outputsReady ? "btn-outline" : "btn-ghost"}`}
            aria-disabled={!outputsReady}
            onClick={(e) => { if (!outputsReady) e.preventDefault(); }}
            title={outputsReady ? undefined : "Analysis not ready yet"}
          >
            Risk report {!outputsReady && <span className="btn-lock">🔒</span>}
          </Link>

          <Link
            href={outputsReady ? `/contracts/${contractId}/negotiation` : "#"}
            className={`btn ${outputsReady ? "btn-outline" : "btn-ghost"}`}
            aria-disabled={!outputsReady}
            onClick={(e) => { if (!outputsReady) e.preventDefault(); }}
            title={outputsReady ? undefined : "Analysis not ready yet"}
          >
            Negotiation package {!outputsReady && <span className="btn-lock">🔒</span>}
          </Link>
        </div>

        {actError && (
          <div className="error-box" style={{ marginTop: "0.75rem" }}>{actError}</div>
        )}

        {/* ── Workflow panel ──────────────────────────────────────────────── */}
        <WorkflowPanel
          workflow={workflow}
          canEdit={canEditWorkflow && !isArchived}
          isAdmin={isAdmin}
          hasCompletedAnalysis={analyses.some((a) => a.status === "completed")}
          latestRisk={analyses.find((a) => a.status === "completed")?.overall_risk ?? null}
          readiness={readiness}
          saving={wfSaving}
          saveError={wfError}
          saveSuccess={wfSuccess}
          onSave={handleWorkflowSave}
        />

        {/* ── History timeline ────────────────────────────────────────────── */}
        {history && (history.workflow_events.length > 0 || history.analyses.length > 0) && (
          <div className="section" style={{ marginTop: "1.5rem" }}>
            <h2>Timeline</h2>
            <HistoryTimeline history={history} />
          </div>
        )}

        {/* ── Versions panel ──────────────────────────────────────────────── */}
        <VersionsPanel
          contractId={contractId}
          versions={versions}
          currentVersionId={contract?.current_version_id ?? null}
          canUpload={canAnalyze && !isArchived}
          onUpload={handleVersionUpload}
          uploading={vUploading}
          uploadError={vUploadErr}
        />

        {/* Analysis history */}
        {analyses.length > 0 && (
          <div className="section" style={{ marginTop: "2rem" }}>
            <h2>Analysis history</h2>
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Status</th>
                  <th>Stage</th>
                  <th>Overall risk</th>
                  <th>Findings</th>
                  <th>Started</th>
                  <th>Completed</th>
                </tr>
              </thead>
              <tbody>
                {analyses.map((a) => (
                  <tr key={a.id}>
                    <td className="mono">#{a.id}</td>
                    <td><span className={statusBadge(a.status)}>{a.status}</span></td>
                    <td className="mono">{a.current_stage ?? "—"}</td>
                    <td>
                      {a.overall_risk
                        ? <span className={riskBadge(a.overall_risk)}>{a.overall_risk}</span>
                        : "—"}
                    </td>
                    <td>{a.total_findings ?? "—"}</td>
                    <td>{a.started_at ? new Date(a.started_at).toLocaleString() : "—"}</td>
                    <td>{a.completed_at ? new Date(a.completed_at).toLocaleString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}

export default function ContractDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <AuthGuard>
      {(user) => <ContractDetailContent user={user} contractId={id} />}
    </AuthGuard>
  );
}
