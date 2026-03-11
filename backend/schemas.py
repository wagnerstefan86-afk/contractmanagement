"""
Pydantic request / response schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ── Shared config ─────────────────────────────────────────────────────────────

class _OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════════════════════
# ORG PROFILE
# ═══════════════════════════════════════════════════════════════════════════════

# All allowed values — validated explicitly so errors are human-readable

VALID_FRAMEWORKS: frozenset[str] = frozenset({
    "ISO27001", "DORA", "GDPR", "NIS2", "SOC2", "PCI_DSS", "HIPAA", "CCPA",
})

VALID_NIS2_TYPES: frozenset[str] = frozenset({"ESSENTIAL", "IMPORTANT", "NONE"})

VALID_VENDOR_RISK_MODELS: frozenset[str] = frozenset({
    "THIRD_PARTY_RISK_V1", "THIRD_PARTY_RISK_V2",
})

VALID_DATA_CLASSES: frozenset[str] = frozenset({
    "PUBLIC", "INTERNAL", "CONFIDENTIAL", "PERSONAL_DATA", "SPECIAL_CATEGORY",
})


class OrgProfileIn(BaseModel):
    """Validated org-profile payload — used on create and PUT /customers/me/profile."""
    organization_name:             str  = Field(..., min_length=1, max_length=255)
    industry:                      str  = Field(..., min_length=1, max_length=100)
    is_regulated_financial_entity: bool
    nis2_entity_type:              str
    regulatory_frameworks:         list[str]
    default_vendor_risk_model:     str
    data_classification_levels:    list[str]

    @field_validator("nis2_entity_type")
    @classmethod
    def _nis2_valid(cls, v: str) -> str:
        if v not in VALID_NIS2_TYPES:
            raise ValueError(
                f"Invalid nis2_entity_type '{v}'. "
                f"Must be one of: {sorted(VALID_NIS2_TYPES)}"
            )
        return v

    @field_validator("regulatory_frameworks")
    @classmethod
    def _frameworks_valid(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("regulatory_frameworks must contain at least one entry.")
        bad = sorted(set(v) - VALID_FRAMEWORKS)
        if bad:
            raise ValueError(
                f"Unknown regulatory frameworks: {bad}. "
                f"Allowed: {sorted(VALID_FRAMEWORKS)}"
            )
        return sorted(set(v))  # deduplicate + stable order

    @field_validator("default_vendor_risk_model")
    @classmethod
    def _vendor_model_valid(cls, v: str) -> str:
        if v not in VALID_VENDOR_RISK_MODELS:
            raise ValueError(
                f"Unknown vendor risk model '{v}'. "
                f"Must be one of: {sorted(VALID_VENDOR_RISK_MODELS)}"
            )
        return v

    @field_validator("data_classification_levels")
    @classmethod
    def _data_levels_valid(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("data_classification_levels must contain at least one entry.")
        bad = sorted(set(v) - VALID_DATA_CLASSES)
        if bad:
            raise ValueError(
                f"Unknown data classification levels: {bad}. "
                f"Allowed: {sorted(VALID_DATA_CLASSES)}"
            )
        return sorted(set(v))


class OrgProfileOut(BaseModel):
    """Read-only org-profile returned by GET /customers/me/profile."""
    organization_name:             str
    industry:                      str
    is_regulated_financial_entity: bool
    nis2_entity_type:              str
    regulatory_frameworks:         list[str]
    default_vendor_risk_model:     str
    data_classification_levels:    list[str]


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════════════════════

class RegisterIn(BaseModel):
    """Public self-registration payload."""
    email:       EmailStr = Field(..., description="Unique email address")
    password:    str      = Field(..., min_length=8, max_length=128)
    name:        str      = Field(..., min_length=1, max_length=255)
    customer_id: int      = Field(..., description="ID of the customer/tenant to join")


class LoginIn(BaseModel):
    """Credential payload for token exchange."""
    email:    EmailStr
    password: str


class TokenOut(BaseModel):
    """JWT access token response."""
    access_token: str
    token_type:   Literal["bearer"] = "bearer"
    expires_in:   int               = Field(..., description="Token lifetime in seconds")


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOMER
# ═══════════════════════════════════════════════════════════════════════════════

class CustomerCreate(BaseModel):
    name:        str
    industry:    str | None  = None
    org_profile: OrgProfileIn | None = None


class CustomerOut(_OrmBase):
    id:         int
    name:       str
    industry:   str | None
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════════════
# USER
# ═══════════════════════════════════════════════════════════════════════════════

class UserCreate(BaseModel):
    """
    Used by ADMIN to create users within their own tenant.
    password_hash is computed server-side; never accepted raw from clients.
    """
    email:    EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name:     str = Field(..., min_length=1, max_length=255)
    role:     str = Field("ANALYST", description="ADMIN | ANALYST | VIEWER")

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        from .models import UserRole
        try:
            UserRole(v)
        except ValueError:
            raise ValueError(f"Invalid role '{v}'. Must be ADMIN, ANALYST, or VIEWER.")
        return v


class UserOut(_OrmBase):
    id:          int
    email:       str
    name:        str
    customer_id: int
    role:        str
    is_active:   bool
    created_at:  datetime


# ═══════════════════════════════════════════════════════════════════════════════
# CONTRACT + REVIEW WORKFLOW
# ═══════════════════════════════════════════════════════════════════════════════

# Allowed values for validation
VALID_REVIEW_STATUSES: frozenset[str] = frozenset({
    "uploaded", "ingested", "analysis_completed",
    "under_review", "in_negotiation", "approved", "rejected", "archived",
})
VALID_REVIEW_DECISIONS: frozenset[str] = frozenset({
    "none", "approve", "conditional_approve", "reject",
})
# Statuses that ANALYST (not ADMIN) may set
ANALYST_SETTABLE_STATUSES: frozenset[str] = frozenset({
    "analysis_completed", "under_review", "in_negotiation",
})
# Statuses only ADMIN may set
ADMIN_ONLY_STATUSES: frozenset[str] = frozenset({
    "approved", "rejected", "archived",
})


class ContractOut(_OrmBase):
    """Returned from upload, get, and list endpoints — includes workflow state."""
    id:                   int
    contract_id:          str
    filename:             str
    file_format:          str
    status:               str
    clauses_extracted:    int | None
    customer_id:          int
    uploaded_by:          int | None
    current_version_id:   int | None
    # Workflow
    review_status:        str
    review_decision:      str
    review_owner_user_id: int | None
    reviewed_at:          datetime | None
    internal_notes:       str | None
    created_at:           datetime
    updated_at:           datetime


class ContractSummaryOut(_OrmBase):
    """Extended list-item response that includes latest analysis data."""
    id:                   int
    contract_id:          str
    filename:             str
    file_format:          str
    status:               str
    clauses_extracted:    int | None
    customer_id:          int
    uploaded_by:          int | None
    review_status:        str
    review_decision:      str
    review_owner_user_id: int | None
    reviewed_at:          datetime | None
    internal_notes:       str | None
    created_at:           datetime
    updated_at:           datetime
    # Populated at query time from the latest completed analysis
    latest_overall_risk:  str | None = None
    latest_analysis_at:   datetime | None = None
    # Populated at query time from the versions table
    version_count:        int = 1
    current_version_number: int | None = None


class ContractListOut(BaseModel):
    total:     int
    contracts: list[ContractSummaryOut]


class ReviewStatusUpdate(BaseModel):
    """Body for PATCH /contracts/{id}/review-status."""
    review_status:        str | None = None
    review_decision:      str | None = None
    review_owner_user_id: int | None = None
    internal_notes:       str | None = None

    @field_validator("review_status")
    @classmethod
    def _status_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_REVIEW_STATUSES:
            raise ValueError(
                f"Invalid review_status '{v}'. "
                f"Must be one of: {sorted(VALID_REVIEW_STATUSES)}"
            )
        return v

    @field_validator("review_decision")
    @classmethod
    def _decision_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_REVIEW_DECISIONS:
            raise ValueError(
                f"Invalid review_decision '{v}'. "
                f"Must be one of: {sorted(VALID_REVIEW_DECISIONS)}"
            )
        return v


class WorkflowEventOut(BaseModel):
    """One entry in the workflow audit log."""
    id:                  int
    contract_id:         str
    changed_by_user_id:  int | None
    changed_by_name:     str | None
    old_status:          str | None
    new_status:          str
    old_decision:        str | None
    new_decision:        str | None
    notes:               str | None
    created_at:          datetime


class WorkflowOut(BaseModel):
    """Full workflow state for GET /contracts/{id}/workflow."""
    contract_id:          str
    review_status:        str
    review_decision:      str
    review_owner_user_id: int | None
    review_owner_name:    str | None
    reviewed_at:          datetime | None
    internal_notes:       str | None
    has_completed_analysis: bool
    latest_overall_risk:  str | None
    events:               list[WorkflowEventOut]


class HistoryOut(BaseModel):
    """Combined upload + analysis + workflow timeline for GET /contracts/{id}/history."""
    contract_id:     str
    uploaded_at:     datetime
    analyses:        list[Any]          # AnalysisOut dicts
    workflow_events: list[WorkflowEventOut]


# ═══════════════════════════════════════════════════════════════════════════════
# CONTRACT VERSIONING
# ═══════════════════════════════════════════════════════════════════════════════

class ContractVersionOut(_OrmBase):
    """Single version of a contract file."""
    id:                   int
    contract_id:          str
    version_number:       int
    original_filename:    str
    status:               str
    clauses_extracted:    int | None
    uploaded_by_user_id:  int | None
    review_status:        str
    review_decision:      str
    review_owner_user_id: int | None
    reviewed_at:          datetime | None
    internal_notes:       str | None
    uploaded_at:          datetime
    # Populated at query time
    latest_overall_risk:  str | None = None
    latest_analysis_at:   datetime | None = None


class VersionListOut(BaseModel):
    total:    int
    versions: list[ContractVersionOut]


class CompareVersionOut(BaseModel):
    """Cross-version risk comparison."""
    contract_id:    str
    from_version:   int
    to_version:     int
    # Summary rows for each version
    from_summary:   dict[str, Any]
    to_summary:     dict[str, Any]
    # Deltas
    risk_changed:   bool
    findings_delta: int   # positive = more findings in to_version
    high_delta:     int
    medium_delta:   int
    low_delta:      int
    # Topics that are new or resolved between versions
    new_topics:     list[str]
    resolved_topics: list[str]


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

class AnalysisOut(_OrmBase):
    """Returned from the analyze endpoint and list queries."""
    id:                          int
    contract_id:                 str
    version_id:                  int | None
    status:                      str
    current_stage:               str | None
    overall_risk:                str | None
    total_clauses:               int | None
    total_findings:              int | None
    high_risk_clauses:           int | None
    medium_risk_clauses:         int | None
    low_risk_clauses:            int | None
    outputs_ready:               bool
    org_profile_version_hash:    str | None
    org_profile_snapshot_path:   str | None
    error_message:               str | None
    started_at:                  datetime | None
    completed_at:                datetime | None
    created_at:                  datetime


class AnalysisStatusOut(BaseModel):
    """Lightweight polling response for a single analysis run."""
    analysis_id:                 int
    contract_id:                 str
    status:                      str
    current_stage:               str | None
    started_at:                  datetime | None
    completed_at:                datetime | None
    error_message:               str | None
    outputs_ready:               bool
    org_profile_version_hash:    str | None


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD / RISK SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

class RiskTopicItem(BaseModel):
    topic: str
    count: int


class RegulatoryFrameworkItem(BaseModel):
    framework: str
    issues:    int


class FindingTypeItem(BaseModel):
    finding_type: str
    count:        int


class ContractRiskItem(BaseModel):
    contract_id:      str
    filename:         str
    overall_risk:     str
    risk_score:       float
    total_findings:   int
    high_risk_clauses: int
    completed_at:     str | None


class RiskSummaryOut(BaseModel):
    """Tenant-level risk aggregation across all completed analyses."""
    total_contracts:            int
    analyses_completed:         int
    average_risk_score:         float
    high_risk_contracts:        int
    medium_risk_contracts:      int
    low_risk_contracts:         int
    top_risk_topics:            list[RiskTopicItem]
    top_regulatory_frameworks:  list[RegulatoryFrameworkItem]
    most_common_finding_types:  list[FindingTypeItem]
    contracts_by_risk:          list[ContractRiskItem]


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE OUTPUT PASS-THROUGHS
# ═══════════════════════════════════════════════════════════════════════════════

class ReportOut(BaseModel):
    contract_id: str
    analysis_id: int
    report:      dict[str, Any]


class NegotiationOut(BaseModel):
    contract_id: str
    analysis_id: int
    package:     dict[str, Any]


# ═══════════════════════════════════════════════════════════════════════════════
# FINDING REVIEWS
# ═══════════════════════════════════════════════════════════════════════════════

VALID_FINDING_STATUSES: frozenset[str] = frozenset({
    "open", "in_review", "in_negotiation", "resolved",
    "accepted_risk", "not_applicable", "deferred",
})

# Statuses that ANALYST may set (ADMIN can set all)
ANALYST_FINDING_STATUSES: frozenset[str] = frozenset({
    "open", "in_review", "in_negotiation", "resolved", "not_applicable", "deferred",
})


class FindingReviewOut(_OrmBase):
    """Full finding-review row."""
    id:                 int
    contract_id:        str
    version_id:         int
    analysis_id:        int | None
    finding_key:        str
    finding_type:       str
    topic:              str | None
    severity:           str | None
    clause_id:          str | None
    text_preview:       str | None
    status:             str
    reviewer_user_id:   int | None
    assigned_user_id:   int | None
    review_comment:     str | None
    disposition_reason: str | None
    created_at:         datetime
    updated_at:         datetime
    # Populated at serialisation time
    reviewer_name:      str | None = None
    assignee_name:      str | None = None


class FindingReviewUpdate(BaseModel):
    """Body for PATCH …/findings/{finding_key}."""
    status:             str | None = None
    assigned_user_id:   int | None = None
    review_comment:     str | None = None
    disposition_reason: str | None = None

    @field_validator("status")
    @classmethod
    def _status_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_FINDING_STATUSES:
            raise ValueError(
                f"Invalid status '{v}'. Must be one of: {sorted(VALID_FINDING_STATUSES)}"
            )
        return v


class FindingsSummaryOut(BaseModel):
    """Counts by severity and status for GET …/findings/summary."""
    total:          int
    open:           int
    in_review:      int
    in_negotiation: int
    resolved:       int
    accepted_risk:  int
    not_applicable: int
    deferred:       int
    by_severity:    dict[str, int]   # HIGH/MEDIUM/LOW → count


class FindingsListOut(BaseModel):
    total:    int
    findings: list[FindingReviewOut]


# ═══════════════════════════════════════════════════════════════════════════════
# APPROVAL READINESS
# ═══════════════════════════════════════════════════════════════════════════════

# Ordered from least ready → most ready
READINESS_ORDER: list[str] = [
    "blocked",
    "review_required",
    "ready_for_conditional_approval",
    "ready_for_approval",
]

READINESS_LABELS: dict[str, str] = {
    "blocked":                      "Blocked",
    "review_required":              "Review Required",
    "ready_for_conditional_approval": "Ready for Conditional Approval",
    "ready_for_approval":           "Ready for Approval",
}


class BlockingFinding(BaseModel):
    finding_key: str
    severity:    str | None
    status:      str
    topic:       str | None
    clause_id:   str | None


class ReadinessCounts(BaseModel):
    high_open:     int
    medium_open:   int
    low_open:      int
    resolved:      int
    accepted_risk: int
    total:         int


class ApprovalReadinessOut(BaseModel):
    contract_id:       str
    version_id:        int
    approval_readiness: str
    blocking_reasons:  list[BlockingFinding]
    counts:            ReadinessCounts


class FindingsSummaryWithReadinessOut(FindingsSummaryOut):
    """Extended summary that includes approval readiness."""
    approval_readiness:    str
    unresolved_high_count: int
    unresolved_medium_count: int


# ═══════════════════════════════════════════════════════════════════════════════
# CLAUSE EXPLORER
# ═══════════════════════════════════════════════════════════════════════════════

class SRMatchOut(BaseModel):
    """One clause→SR regulatory match."""
    sr_id:             str
    sr_title:          str | None
    framework:         str
    control_id:        str | None
    match_type:        str        # DIRECT_MATCH | INDIRECT_MATCH | NO_MATCH
    match_confidence:  float
    extracted_evidence: str | None
    match_reasoning:   str | None
    # Additive pipeline metadata — present when Stage 5 runs with LLM or hybrid mode.
    # Field names drop the leading underscore (Pydantic private-attribute conflict);
    # _sr_match_out() maps them from the raw pipeline dict keys.
    ai_metadata:        dict[str, Any] | None = None
    baseline_result:    str | None = None
    decision_delta:     str | None = None
    confidence_bucket:  str | None = None
    review_priority:    str | None = None
    ai_trace:           list[Any] | None = None
    candidate_metadata: dict[str, Any] | None = None


class ObligationAssessmentOut(BaseModel):
    """Obligation analysis result for a single clause."""
    assessment:         str        # NON_TRANSFERABLE_REGULATION | … | VALID
    severity:           str | None
    reason:             str | None
    recommended_action: str | None


class ClauseRiskScoreOut(BaseModel):
    """Per-clause risk score detail from Stage 11."""
    risk_score:           float
    priority:             str | None   # HIGH | MEDIUM | LOW
    topic:                str | None
    obligation:           str | None
    score_breakdown:      dict | None
    text_preview:         str | None


class ClauseFindingOut(BaseModel):
    """Minimal finding record linked to a clause."""
    id:               int
    finding_key:      str
    finding_type:     str
    topic:            str | None
    severity:         str | None
    status:           str
    review_comment:   str | None
    text_preview:     str | None


class NegotiationItemOut(BaseModel):
    """One negotiation package item linked to a clause."""
    neg_id:            str | None
    action_id:         str | None
    finding_type:      str | None
    priority:          str | None
    topic:             str | None
    position_summary:  str | None
    recommended_text:  str | None


class ClauseListItem(BaseModel):
    """Row in the clause explorer list."""
    clause_id:        str
    page:             int | None
    layout_type:      str | None
    text_preview:     str | None           # first ~200 chars
    topic:            str | None
    severity:         str | None           # from obligation analysis
    risk_score:       float | None
    finding_count:    int
    finding_statuses: list[str]
    sr_match_count:   int
    has_direct_match: bool


class ClauseListOut(BaseModel):
    version_id: int
    total:      int
    clauses:    list[ClauseListItem]


class ClauseDetailOut(BaseModel):
    """Full clause-centric detail object."""
    clause_id:              str
    page:                   int | None
    layout_type:            str | None
    text:                   str | None
    obligation_assessment:  ObligationAssessmentOut | None
    sr_matches:             list[SRMatchOut]
    findings:               list[ClauseFindingOut]
    risk_score:             ClauseRiskScoreOut | None
    negotiation_items:      list[NegotiationItemOut]
    workflow_context: dict   # review_status, approval_readiness


# ═══════════════════════════════════════════════════════════════════════════════
# CLOSURE BUNDLE
# ═══════════════════════════════════════════════════════════════════════════════

class ClosureBundleManifestOut(BaseModel):
    """Manifest for a frozen, audit-ready closure bundle."""
    contract_id:              str
    case_id:                  int              # Integer DB id of the Contract
    version_id:               int
    analysis_id:              int
    customer_id:              int
    review_status:            str              # approved | rejected
    review_decision:          str              # approve | conditional_approve | reject | none
    approved_or_rejected_at:  str | None
    org_profile_version_hash: str | None
    overall_risk:             str | None
    bundle_contents:          list[str]        # Filenames present in the bundle dir
    bundle_hash:              str | None       # SHA-256 of the ZIP archive
    generated_at:             str             # ISO-8601 timestamp


class ClosureBundleOut(BaseModel):
    """Response envelope for closure bundle metadata."""
    contract_id: str
    version_id:  int
    manifest:    ClosureBundleManifestOut
    has_zip:     bool                          # Whether the ZIP archive exists


# ═══════════════════════════════════════════════════════════════════════════════
# ERROR
# ═══════════════════════════════════════════════════════════════════════════════

class ErrorOut(BaseModel):
    detail: str
