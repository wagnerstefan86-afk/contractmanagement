/**
 * Typed API client for the contract analysis backend.
 * All requests attach the Bearer token from localStorage.
 * 401 → redirect to /login
 * 403 → throw ForbiddenError with detail message
 */

import { getToken, clearToken } from "./session";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8765";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}
export class ForbiddenError extends ApiError {
  constructor(message: string) { super(403, message); }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  isPublic = false,
): Promise<T> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string>),
  };

  if (!(init.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const token = getToken();
  if (token && !isPublic) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Session expired.");
  }

  if (res.status === 403) {
    const body = await res.json().catch(() => ({ detail: "Forbidden." }));
    throw new ForbiddenError(body.detail ?? "Forbidden.");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export interface TokenOut {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export function login(email: string, password: string): Promise<TokenOut> {
  return request<TokenOut>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  }, true);
}

export function register(
  email: string, password: string, name: string, customer_id: number,
): Promise<{ id: number; email: string; name: string }> {
  return request("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name, customer_id }),
  }, true);
}

export interface MeOut {
  id: number; email: string; name: string;
  customer_id: number; role: string; is_active: boolean; created_at: string;
}

export function getMe(): Promise<MeOut> {
  return request<MeOut>("/auth/me");
}

// ── Customer ──────────────────────────────────────────────────────────────────

export interface CustomerOut {
  id: number; name: string; industry: string | null; created_at: string;
}

export function getMyCustomer(): Promise<CustomerOut> {
  return request<CustomerOut>("/customers/me");
}

export function createCustomer(name: string, industry?: string): Promise<CustomerOut> {
  return request<CustomerOut>("/customers", {
    method: "POST",
    body: JSON.stringify({ name, industry }),
  });
}

// ── Org Profile ───────────────────────────────────────────────────────────────

export type Nis2EntityType = "ESSENTIAL" | "IMPORTANT" | "NONE";

export const ALL_FRAMEWORKS = [
  "ISO27001", "DORA", "GDPR", "NIS2", "SOC2", "PCI_DSS", "HIPAA", "CCPA",
] as const;
export type RegulatoryFramework = typeof ALL_FRAMEWORKS[number];

export const ALL_DATA_CLASSES = [
  "PUBLIC", "INTERNAL", "CONFIDENTIAL", "PERSONAL_DATA", "SPECIAL_CATEGORY",
] as const;
export type DataClassificationLevel = typeof ALL_DATA_CLASSES[number];

export const ALL_VENDOR_RISK_MODELS = [
  "THIRD_PARTY_RISK_V1", "THIRD_PARTY_RISK_V2",
] as const;
export type VendorRiskModel = typeof ALL_VENDOR_RISK_MODELS[number];

export interface OrgProfile {
  organization_name:             string;
  industry:                      string;
  is_regulated_financial_entity: boolean;
  nis2_entity_type:              Nis2EntityType;
  regulatory_frameworks:         RegulatoryFramework[];
  default_vendor_risk_model:     VendorRiskModel;
  data_classification_levels:    DataClassificationLevel[];
}

export function getOrgProfile(): Promise<OrgProfile> {
  return request<OrgProfile>("/customers/me/profile");
}

export function updateOrgProfile(profile: OrgProfile): Promise<OrgProfile> {
  return request<OrgProfile>("/customers/me/profile", {
    method: "PUT",
    body: JSON.stringify(profile),
  });
}

// ── Users ─────────────────────────────────────────────────────────────────────

export interface UserOut {
  id: number; email: string; name: string;
  customer_id: number; role: string; is_active: boolean; created_at: string;
}

export function listUsers(): Promise<UserOut[]> {
  return request<UserOut[]>("/users");
}

export function createUser(email: string, password: string, name: string, role: string): Promise<UserOut> {
  return request<UserOut>("/users", {
    method: "POST",
    body: JSON.stringify({ email, password, name, role }),
  });
}

export function deactivateUser(id: number): Promise<UserOut> {
  return request<UserOut>(`/users/${id}/deactivate`, { method: "PATCH" });
}

// ── Contracts + workflow ──────────────────────────────────────────────────────

export type ReviewStatus =
  | "uploaded" | "ingested" | "analysis_completed"
  | "under_review" | "in_negotiation"
  | "approved" | "rejected" | "archived";

export type ReviewDecision = "none" | "approve" | "conditional_approve" | "reject";

export interface ContractOut {
  id: number; contract_id: string; filename: string; file_format: string;
  status: string; clauses_extracted: number | null;
  customer_id: number; uploaded_by: number | null;
  current_version_id: number | null;
  // workflow
  review_status: ReviewStatus;
  review_decision: ReviewDecision;
  review_owner_user_id: number | null;
  reviewed_at: string | null;
  internal_notes: string | null;
  created_at: string; updated_at: string;
}

export interface ContractSummaryOut extends ContractOut {
  latest_overall_risk: string | null;
  latest_analysis_at: string | null;
  version_count: number;
  current_version_number: number | null;
}

export interface ContractListOut {
  total: number;
  contracts: ContractSummaryOut[];
}

export interface ContractListFilters {
  skip?: number;
  limit?: number;
  status?: string;
  review_status?: ReviewStatus;
  review_decision?: ReviewDecision;
}

export function listContracts(skip = 0, limit = 50, filters: Omit<ContractListFilters, "skip" | "limit"> = {}): Promise<ContractListOut> {
  const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
  if (filters.status)          params.set("status",          filters.status);
  if (filters.review_status)   params.set("review_status",   filters.review_status);
  if (filters.review_decision) params.set("review_decision", filters.review_decision);
  return request<ContractListOut>(`/contracts?${params}`);
}

export function uploadContract(file: File): Promise<ContractOut> {
  const form = new FormData();
  form.append("file", file);
  return request<ContractOut>("/contracts/upload", { method: "POST", body: form });
}

// ── Workflow ───────────────────────────────────────────────────────────────────

export interface WorkflowEventOut {
  id: number;
  contract_id: string;
  changed_by_user_id: number | null;
  changed_by_name: string | null;
  old_status: ReviewStatus | null;
  new_status: ReviewStatus;
  old_decision: ReviewDecision | null;
  new_decision: ReviewDecision | null;
  notes: string | null;
  created_at: string;
}

export interface WorkflowOut {
  contract_id: string;
  review_status: ReviewStatus;
  review_decision: ReviewDecision;
  review_owner_user_id: number | null;
  review_owner_name: string | null;
  reviewed_at: string | null;
  internal_notes: string | null;
  has_completed_analysis: boolean;
  latest_overall_risk: string | null;
  events: WorkflowEventOut[];
}

export interface HistoryOut {
  contract_id: string;
  uploaded_at: string;
  analyses: AnalysisOut[];
  workflow_events: WorkflowEventOut[];
}

export interface ReviewStatusUpdate {
  review_status?: ReviewStatus;
  review_decision?: ReviewDecision;
  review_owner_user_id?: number | null;
  internal_notes?: string;
}

export function getWorkflow(contractId: string): Promise<WorkflowOut> {
  return request<WorkflowOut>(`/contracts/${contractId}/workflow`);
}

export function getContractHistory(contractId: string): Promise<HistoryOut> {
  return request<HistoryOut>(`/contracts/${contractId}/history`);
}

export function updateReviewStatus(contractId: string, body: ReviewStatusUpdate): Promise<ContractOut> {
  return request<ContractOut>(`/contracts/${contractId}/review-status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ── Contract Versions ──────────────────────────────────────────────────────────

export interface ContractVersionOut {
  id: number;
  contract_id: string;
  version_number: number;
  original_filename: string;
  status: string;
  clauses_extracted: number | null;
  uploaded_by_user_id: number | null;
  review_status: ReviewStatus;
  review_decision: ReviewDecision;
  review_owner_user_id: number | null;
  reviewed_at: string | null;
  internal_notes: string | null;
  uploaded_at: string;
  latest_overall_risk: string | null;
  latest_analysis_at: string | null;
}

export interface VersionListOut {
  total: number;
  versions: ContractVersionOut[];
}

export interface CompareVersionOut {
  contract_id: string;
  from_version: number;
  to_version: number;
  from_summary: {
    version_number: number;
    original_filename: string;
    review_status: ReviewStatus;
    overall_risk: string | null;
    total_findings: number;
    high_risk_clauses: number;
    medium_risk_clauses: number;
    low_risk_clauses: number;
    risk_topics: string[];
    has_analysis: boolean;
  };
  to_summary: {
    version_number: number;
    original_filename: string;
    review_status: ReviewStatus;
    overall_risk: string | null;
    total_findings: number;
    high_risk_clauses: number;
    medium_risk_clauses: number;
    low_risk_clauses: number;
    risk_topics: string[];
    has_analysis: boolean;
  };
  risk_changed: boolean;
  findings_delta: number;
  high_delta: number;
  medium_delta: number;
  low_delta: number;
  new_topics: string[];
  resolved_topics: string[];
}

export function listVersions(contractId: string): Promise<VersionListOut> {
  return request<VersionListOut>(`/contracts/${contractId}/versions`);
}

export function getVersion(contractId: string, versionId: number): Promise<ContractVersionOut> {
  return request<ContractVersionOut>(`/contracts/${contractId}/versions/${versionId}`);
}

export function uploadVersion(contractId: string, file: File): Promise<ContractVersionOut> {
  const form = new FormData();
  form.append("file", file);
  return request<ContractVersionOut>(`/contracts/${contractId}/versions/upload`, {
    method: "POST",
    body: form,
  });
}

export function triggerVersionAnalysis(contractId: string, versionId: number): Promise<AnalysisOut> {
  return request<AnalysisOut>(`/contracts/${contractId}/versions/${versionId}/analyze`, {
    method: "POST",
  });
}

export function getVersionReport(contractId: string, versionId: number): Promise<ReportOut> {
  return request<ReportOut>(`/contracts/${contractId}/versions/${versionId}/report`);
}

export function getVersionNegotiation(contractId: string, versionId: number): Promise<NegotiationOut> {
  return request<NegotiationOut>(`/contracts/${contractId}/versions/${versionId}/negotiation`);
}

export function updateVersionReviewStatus(
  contractId: string,
  versionId: number,
  body: ReviewStatusUpdate,
): Promise<ContractVersionOut> {
  return request<ContractVersionOut>(
    `/contracts/${contractId}/versions/${versionId}/review-status`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

export function getVersionWorkflow(contractId: string, versionId: number): Promise<WorkflowOut> {
  return request<WorkflowOut>(`/contracts/${contractId}/versions/${versionId}/workflow`);
}

export function compareVersions(
  contractId: string,
  fromVersion: number,
  toVersion: number,
): Promise<CompareVersionOut> {
  const params = new URLSearchParams({
    from_version: String(fromVersion),
    to_version:   String(toVersion),
  });
  return request<CompareVersionOut>(`/contracts/${contractId}/compare?${params}`);
}

// ── Finding Reviews ───────────────────────────────────────────────────────────

export type FindingStatus =
  | "open" | "in_review" | "in_negotiation" | "resolved"
  | "accepted_risk" | "not_applicable" | "deferred";

export interface FindingReviewOut {
  id:                 number;
  contract_id:        string;
  version_id:         number;
  analysis_id:        number | null;
  finding_key:        string;
  finding_type:       string;
  topic:              string | null;
  severity:           string | null;
  clause_id:          string | null;
  text_preview:       string | null;
  status:             FindingStatus;
  reviewer_user_id:   number | null;
  assigned_user_id:   number | null;
  review_comment:     string | null;
  disposition_reason: string | null;
  created_at:         string;
  updated_at:         string;
  reviewer_name:      string | null;
  assignee_name:      string | null;
}

export interface FindingsListOut {
  total:    number;
  findings: FindingReviewOut[];
}

export interface FindingsSummaryOut {
  total:          number;
  open:           number;
  in_review:      number;
  in_negotiation: number;
  resolved:       number;
  accepted_risk:  number;
  not_applicable: number;
  deferred:       number;
  by_severity:    Record<string, number>;
}

export interface FindingReviewUpdate {
  status?:             FindingStatus;
  assigned_user_id?:   number | null;
  review_comment?:     string;
  disposition_reason?: string;
}

export function listFindings(
  contractId: string,
  versionId: number,
  params?: { severity?: string; status?: string; topic?: string },
): Promise<FindingsListOut> {
  const q = new URLSearchParams();
  if (params?.severity) q.set("severity", params.severity);
  if (params?.status)   q.set("status",   params.status);
  if (params?.topic)    q.set("topic",    params.topic);
  const qs = q.toString() ? `?${q}` : "";
  return request<FindingsListOut>(
    `/contracts/${contractId}/versions/${versionId}/findings${qs}`
  );
}

export function getFindingsSummary(
  contractId: string,
  versionId: number,
): Promise<FindingsSummaryOut> {
  return request<FindingsSummaryOut>(
    `/contracts/${contractId}/versions/${versionId}/findings/summary`
  );
}

export function updateFinding(
  contractId: string,
  versionId: number,
  findingKey: string,
  body: FindingReviewUpdate,
): Promise<FindingReviewOut> {
  return request<FindingReviewOut>(
    `/contracts/${contractId}/versions/${versionId}/findings/${encodeURIComponent(findingKey)}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

// ── Approval Readiness ────────────────────────────────────────────────────────

export type ApprovalReadiness =
  | "blocked"
  | "review_required"
  | "ready_for_conditional_approval"
  | "ready_for_approval";

export const READINESS_ORDER: ApprovalReadiness[] = [
  "blocked",
  "review_required",
  "ready_for_conditional_approval",
  "ready_for_approval",
];

export const READINESS_LABEL: Record<ApprovalReadiness, string> = {
  blocked:                        "Blocked",
  review_required:                "Review Required",
  ready_for_conditional_approval: "Ready for Conditional Approval",
  ready_for_approval:             "Ready for Approval",
};

export const READINESS_BADGE: Record<ApprovalReadiness, string> = {
  blocked:                        "badge badge--red",
  review_required:                "badge badge--yellow",
  ready_for_conditional_approval: "badge badge--yellow",
  ready_for_approval:             "badge badge--green",
};

export interface BlockingFinding {
  finding_key: string;
  severity:    string | null;
  status:      string;
  topic:       string | null;
  clause_id:   string | null;
}

export interface ReadinessCounts {
  high_open:     number;
  medium_open:   number;
  low_open:      number;
  resolved:      number;
  accepted_risk: number;
  total:         number;
}

export interface ApprovalReadinessOut {
  contract_id:        string;
  version_id:         number;
  approval_readiness: ApprovalReadiness;
  blocking_reasons:   BlockingFinding[];
  counts:             ReadinessCounts;
}

export interface FindingsSummaryWithReadinessOut extends FindingsSummaryOut {
  approval_readiness:      ApprovalReadiness;
  unresolved_high_count:   number;
  unresolved_medium_count: number;
}

export function getApprovalReadiness(
  contractId: string,
  versionId: number,
): Promise<ApprovalReadinessOut> {
  return request<ApprovalReadinessOut>(
    `/contracts/${contractId}/versions/${versionId}/approval-readiness`
  );
}

// ── Clause Explorer ───────────────────────────────────────────────────────────

export interface SRMatchOut {
  sr_id:              string;
  sr_title:           string | null;
  framework:          string;
  control_id:         string | null;
  match_type:         string;
  match_confidence:   number;
  extracted_evidence: string | null;
  match_reasoning:    string | null;
  // Additive pipeline metadata — null when LLM is disabled or field not yet populated
  ai_metadata:        Record<string, unknown> | null;
  baseline_result:    string | null;
  decision_delta:     string | null;
  confidence_bucket:  string | null;
  review_priority:    string | null;
  ai_trace:           unknown[] | null;
  candidate_metadata: Record<string, unknown> | null;
}

export interface ObligationAssessmentOut {
  assessment:         string;
  severity:           string | null;
  reason:             string | null;
  recommended_action: string | null;
}

export interface ClauseRiskScoreOut {
  risk_score:      number;
  priority:        string | null;
  topic:           string | null;
  obligation:      string | null;
  score_breakdown: Record<string, unknown> | null;
  text_preview:    string | null;
}

export interface ClauseFindingOut {
  id:             number;
  finding_key:    string;
  finding_type:   string;
  topic:          string | null;
  severity:       string | null;
  status:         string;
  review_comment: string | null;
  text_preview:   string | null;
}

export interface NegotiationItemOut {
  neg_id:           string | null;
  action_id:        string | null;
  finding_type:     string | null;
  priority:         string | null;
  topic:            string | null;
  position_summary: string | null;
  recommended_text: string | null;
}

export interface ClauseListItem {
  clause_id:        string;
  page:             number | null;
  layout_type:      string | null;
  text_preview:     string | null;
  topic:            string | null;
  severity:         string | null;
  risk_score:       number | null;
  finding_count:    number;
  finding_statuses: string[];
  sr_match_count:   number;
  has_direct_match: boolean;
}

export interface ClauseListOut {
  version_id: number;
  total:      number;
  clauses:    ClauseListItem[];
}

export interface ClauseDetailOut {
  clause_id:             string;
  page:                  number | null;
  layout_type:           string | null;
  text:                  string | null;
  obligation_assessment: ObligationAssessmentOut | null;
  sr_matches:            SRMatchOut[];
  findings:              ClauseFindingOut[];
  risk_score:            ClauseRiskScoreOut | null;
  negotiation_items:     NegotiationItemOut[];
  workflow_context:      {
    review_status:      string;
    review_decision:    string;
    approval_readiness: string;
  };
}

export interface ClauseFilters {
  severity?:       string;
  topic?:          string;
  finding_status?: string;
  layout_type?:    string;
  min_risk_score?: number;
  q?:              string;
}

export function listClauses(
  contractId: string,
  versionId:  number,
  filters:    ClauseFilters = {},
): Promise<ClauseListOut> {
  const p = new URLSearchParams();
  if (filters.severity)       p.set("severity",       filters.severity);
  if (filters.topic)          p.set("topic",          filters.topic);
  if (filters.finding_status) p.set("finding_status", filters.finding_status);
  if (filters.layout_type)    p.set("layout_type",    filters.layout_type);
  if (filters.min_risk_score != null)
                              p.set("min_risk_score", String(filters.min_risk_score));
  if (filters.q)              p.set("q",              filters.q);
  const qs = p.toString() ? `?${p}` : "";
  return request<ClauseListOut>(
    `/contracts/${contractId}/versions/${versionId}/clauses${qs}`
  );
}

export function getClauseDetail(
  contractId: string,
  versionId:  number,
  clauseId:   string,
): Promise<ClauseDetailOut> {
  return request<ClauseDetailOut>(
    `/contracts/${contractId}/versions/${versionId}/clauses/${encodeURIComponent(clauseId)}`
  );
}

// ── Closure Bundle ────────────────────────────────────────────────────────────

export interface ClosureBundleManifestOut {
  contract_id:              string;
  case_id:                  number;
  version_id:               number;
  version_number?:          number;
  analysis_id:              number;
  customer_id:              number;
  review_status:            string;
  review_decision:          string;
  approved_or_rejected_at:  string | null;
  org_profile_version_hash: string | null;
  overall_risk:             string | null;
  bundle_contents:          string[];
  bundle_hash:              string | null;
  generated_at:             string;
}

export interface ClosureBundleOut {
  contract_id: string;
  version_id:  number;
  manifest:    ClosureBundleManifestOut;
  has_zip:     boolean;
}

export function getClosureBundle(
  contractId: string,
  versionId: number,
): Promise<ClosureBundleOut> {
  return request<ClosureBundleOut>(
    `/contracts/${contractId}/versions/${versionId}/closure-bundle`
  );
}

/**
 * Download the closure bundle ZIP using the auth token.
 * Returns a blob URL that the caller should revoke after use.
 */
export async function downloadClosureBundleBlob(
  contractId: string,
  versionId: number,
): Promise<{ url: string; filename: string }> {
  const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const token = typeof window !== "undefined"
    ? getToken()
    : null;
  const res = await fetch(
    `${API_BASE}/contracts/${contractId}/versions/${versionId}/closure-bundle/download`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, text || `HTTP ${res.status}`);
  }
  const cd = res.headers.get("content-disposition") ?? "";
  const match = cd.match(/filename="([^"]+)"/);
  const filename = match ? match[1] : `closure_${contractId}_v${versionId}.zip`;
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), filename };
}

// ── Analysis ──────────────────────────────────────────────────────────────────

export type AnalysisStatus = "pending" | "running" | "completed" | "failed";

export type AnalysisStage =
  | "stage16_ingestion"
  | "stage3_classification"
  | "stage4_5_obligation_analysis"
  | "stage5_clause_matching"
  | "stage6_compliance"
  | "stage8_remediation"
  | "stage9_brief"
  | "stage10_trace"
  | "stage11_risk"
  | "stage12_action_plan"
  | "stage13_negotiation"
  | "stage14_report"
  | "done";

export interface AnalysisOut {
  id: number;
  contract_id: string;
  version_id: number | null;
  status: AnalysisStatus;
  current_stage: AnalysisStage | null;
  overall_risk: string | null;
  total_clauses: number | null;
  total_findings: number | null;
  high_risk_clauses: number | null;
  medium_risk_clauses: number | null;
  low_risk_clauses: number | null;
  outputs_ready: boolean;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface AnalysisStatusOut {
  analysis_id: number;
  contract_id: string;
  status: AnalysisStatus;
  current_stage: AnalysisStage | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  outputs_ready: boolean;
  org_profile_version_hash: string | null;
}

export function triggerAnalysis(contractId: string): Promise<AnalysisOut> {
  return request<AnalysisOut>(`/contracts/${contractId}/analyze`, { method: "POST" });
}

export function getAnalysisStatus(
  contractId: string,
  analysisId: number,
): Promise<AnalysisStatusOut> {
  return request<AnalysisStatusOut>(
    `/contracts/${contractId}/analyses/${analysisId}`,
  );
}

export function getContractStatus(contractId: string): Promise<AnalysisStatusOut> {
  return request<AnalysisStatusOut>(`/contracts/${contractId}/status`);
}

export function listAnalyses(contractId: string): Promise<AnalysisOut[]> {
  return request<AnalysisOut[]>(`/contracts/${contractId}/analyses`);
}

export function getContract(contractId: string): Promise<ContractOut> {
  return request<ContractOut>(`/contracts/${contractId}`);
}

// ── Reports ───────────────────────────────────────────────────────────────────

export interface ReportOut {
  contract_id: string;
  analysis_id: number;
  report: Record<string, unknown>;
}

export function getReport(contractId: string): Promise<ReportOut> {
  return request<ReportOut>(`/contracts/${contractId}/report`);
}

export interface NegotiationOut {
  contract_id: string;
  analysis_id: number;
  package: Record<string, unknown>;
}

export function getNegotiation(contractId: string): Promise<NegotiationOut> {
  return request<NegotiationOut>(`/contracts/${contractId}/negotiation`);
}

// ── Dashboard / Risk Summary ───────────────────────────────────────────────────

export interface RiskTopicItem    { topic:        string; count:  number; }
export interface RegulatoryFwItem { framework:    string; issues: number; }
export interface FindingTypeItem  { finding_type: string; count:  number; }

export interface ContractRiskItem {
  contract_id:       string;
  filename:          string;
  overall_risk:      string;
  risk_score:        number;
  total_findings:    number;
  high_risk_clauses: number;
  completed_at:      string | null;
}

export interface RiskSummaryOut {
  total_contracts:            number;
  analyses_completed:         number;
  average_risk_score:         number;
  high_risk_contracts:        number;
  medium_risk_contracts:      number;
  low_risk_contracts:         number;
  top_risk_topics:            RiskTopicItem[];
  top_regulatory_frameworks:  RegulatoryFwItem[];
  most_common_finding_types:  FindingTypeItem[];
  contracts_by_risk:          ContractRiskItem[];
}

export function getRiskSummary(): Promise<RiskSummaryOut> {
  return request<RiskSummaryOut>("/dashboard/risk-summary");
}
