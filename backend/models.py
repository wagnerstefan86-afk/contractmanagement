"""
SQLAlchemy ORM models.

Tables
------
customers          – organisations using the platform (e.g. FinanzBank AG)
users              – platform users, each belonging to exactly one customer (tenant)
contracts          – contract cases (one per negotiation cycle)
contract_versions  – individual file revisions within a case (v1, v2, …)
analyses           – pipeline runs associated with a contract version
contract_workflow_events – immutable audit log for status changes
finding_reviews    – human review disposition for individual analysis findings

Schema changes from v1
----------------------
users:
  + password_hash   (str, NOT NULL)
  + role            (str, NOT NULL, default "ANALYST")
  + is_active       (bool, NOT NULL, default True)
  + is_platform_admin (bool, NOT NULL, default False) — future-ready, not exposed
  customer_id is now NOT NULL (tenancy is mandatory)

v2.3 (versioning):
  contracts:
    + current_version_id  (int, nullable — points to the active ContractVersion)
  contract_versions:      new table (one row per file revision)
  analyses:
    + version_id          (int, nullable — which ContractVersion this run belongs to)

v2.4 (finding review):
  finding_reviews:        new table (one row per finding per version, auto-created after analysis)
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Role enum ─────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    """
    Tenant-scoped roles.  ADMIN is still restricted to their own customer.
    """
    ADMIN   = "ADMIN"
    ANALYST = "ANALYST"
    VIEWER  = "VIEWER"

    # Convenience helper used in permission checks
    @classmethod
    def analyst_and_above(cls) -> frozenset["UserRole"]:
        return frozenset({cls.ADMIN, cls.ANALYST})

    @classmethod
    def all_roles(cls) -> frozenset["UserRole"]:
        return frozenset({cls.ADMIN, cls.ANALYST, cls.VIEWER})


# ── customers ──────────────────────────────────────────────────────────────────

class Customer(Base):
    __tablename__ = "customers"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:        Mapped[str]      = mapped_column(String(255), nullable=False)
    industry:    Mapped[str|None] = mapped_column(String(100))
    # Serialised org_profile JSON (the full org_profile.json payload)
    org_profile: Mapped[str|None] = mapped_column(Text)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    users:     Mapped[list["User"]]     = relationship("User",     back_populates="customer", cascade="all, delete-orphan")
    contracts: Mapped[list["Contract"]] = relationship("Contract", back_populates="customer")


# ── users ──────────────────────────────────────────────────────────────────────

class User(Base):
    """
    Platform user.  Each user belongs to exactly one Customer (tenant).

    Role summary
    ------------
    ADMIN   – manage users/contracts within their tenant; run analyses
    ANALYST – upload contracts, run analyses, view results
    VIEWER  – read-only access to contracts and reports

    Fields
    ------
    is_platform_admin
        Reserved for future cross-tenant platform operators.
        Not exposed via any current API endpoint.
    """
    __tablename__ = "users"

    id:                Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    email:             Mapped[str]      = mapped_column(String(255), unique=True, nullable=False)
    name:              Mapped[str]      = mapped_column(String(255), nullable=False)
    password_hash:     Mapped[str]      = mapped_column(String(255), nullable=False)
    role:              Mapped[str]      = mapped_column(String(20),  nullable=False, default=UserRole.ANALYST.value)
    is_active:         Mapped[bool]     = mapped_column(Boolean,     nullable=False, default=True)
    is_platform_admin: Mapped[bool]     = mapped_column(Boolean,     nullable=False, default=False)

    # customer_id is NOT NULL — every user must belong to a tenant
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    customer:  Mapped["Customer"]       = relationship("Customer",  back_populates="users")
    contracts: Mapped[list["Contract"]] = relationship("Contract",  back_populates="uploaded_by_user", foreign_keys="[Contract.uploaded_by]")


# ── contracts ──────────────────────────────────────────────────────────────────

class Contract(Base):
    """
    Represents an uploaded contract file.

    Status lifecycle
    ----------------
    uploaded → ingested → analyzed
                       ↘ failed
    """
    __tablename__ = "contracts"

    id:                Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id:       Mapped[str]      = mapped_column(String(50),   unique=True, nullable=False)
    filename:          Mapped[str]      = mapped_column(String(512),  nullable=False)
    file_path:         Mapped[str]      = mapped_column(String(1024), nullable=False)
    file_format:       Mapped[str]      = mapped_column(String(10),   nullable=False)
    status:            Mapped[str]      = mapped_column(String(20),   nullable=False, default="uploaded")
    clauses_extracted: Mapped[int|None] = mapped_column(Integer)
    error_message:     Mapped[str|None] = mapped_column(Text)

    # customer_id links the contract to its tenant (NOT NULL — required)
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_by: Mapped[int|None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )

    # ── Review workflow ────────────────────────────────────────────────────────
    # review_status: uploaded|ingested|analysis_completed|under_review|
    #                in_negotiation|approved|rejected|archived
    review_status:        Mapped[str]           = mapped_column(String(30), nullable=False, default="uploaded")
    # review_decision: none|approve|conditional_approve|reject  (ADMIN only)
    review_decision:      Mapped[str]           = mapped_column(String(30), nullable=False, default="none")
    review_owner_user_id: Mapped[int|None]      = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at:          Mapped[datetime|None] = mapped_column(DateTime(timezone=True))
    internal_notes:       Mapped[str|None]      = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Points to the active/latest ContractVersion (no FK constraint to avoid circular dep)
    current_version_id: Mapped[int|None] = mapped_column(Integer, nullable=True)

    customer:          Mapped["Customer"]       = relationship("Customer", back_populates="contracts")
    uploaded_by_user:  Mapped["User|None"]      = relationship("User", back_populates="contracts", foreign_keys="[Contract.uploaded_by]")
    review_owner:      Mapped["User|None"]      = relationship("User", foreign_keys="[Contract.review_owner_user_id]")
    analyses:          Mapped[list["Analysis"]] = relationship("Analysis", back_populates="contract", cascade="all, delete-orphan")
    workflow_events:   Mapped[list["ContractWorkflowEvent"]] = relationship("ContractWorkflowEvent", back_populates="contract", cascade="all, delete-orphan", order_by="ContractWorkflowEvent.created_at")
    versions:          Mapped[list["ContractVersion"]]       = relationship("ContractVersion", back_populates="contract", cascade="all, delete-orphan", order_by="ContractVersion.version_number")


# ── analyses ───────────────────────────────────────────────────────────────────

class Analysis(Base):
    """
    One pipeline run (stages 9-14) for a contract.

    Status lifecycle
    ----------------
    pending → running → completed
                     ↘ failed
    """
    __tablename__ = "analyses"

    id:                 Mapped[int]       = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id:        Mapped[str]       = mapped_column(String(50), nullable=False, index=True)
    contract_db_id:     Mapped[int|None]  = mapped_column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"))
    status:             Mapped[str]       = mapped_column(String(20), nullable=False, default="pending")
    current_stage:      Mapped[str|None]  = mapped_column(String(50))
    overall_risk:       Mapped[str|None]  = mapped_column(String(20))
    total_clauses:      Mapped[int|None]  = mapped_column(Integer)
    total_findings:     Mapped[int|None]  = mapped_column(Integer)
    high_risk_clauses:  Mapped[int|None]  = mapped_column(Integer)
    medium_risk_clauses: Mapped[int|None] = mapped_column(Integer)
    low_risk_clauses:   Mapped[int|None]  = mapped_column(Integer)
    outputs_ready:               Mapped[bool]      = mapped_column(Boolean, nullable=False, default=False)
    org_profile_snapshot_path:   Mapped[str|None]  = mapped_column(String(1024))
    org_profile_version_hash:    Mapped[str|None]  = mapped_column(String(64))
    output_dir:                  Mapped[str]       = mapped_column(String(1024), nullable=False)
    error_message:               Mapped[str|None]  = mapped_column(Text)
    started_at:         Mapped[datetime|None] = mapped_column(DateTime(timezone=True))
    completed_at:       Mapped[datetime|None] = mapped_column(DateTime(timezone=True))
    created_at:         Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_utcnow)

    # version_id links this run to a specific ContractVersion (nullable for backward compat)
    version_id: Mapped[int|None] = mapped_column(
        Integer, ForeignKey("contract_versions.id", ondelete="SET NULL"), nullable=True
    )

    contract: Mapped["Contract|None"] = relationship("Contract", back_populates="analyses")
    version:  Mapped["ContractVersion|None"] = relationship("ContractVersion", back_populates="analyses")


# ── contract_versions ──────────────────────────────────────────────────────────

class ContractVersion(Base):
    """
    One file revision within a contract case.

    Version numbers start at 1 and increment with each new upload.
    The active version is tracked via Contract.current_version_id.
    Each version carries its own ingestion status, workflow state,
    and is linked to all Analysis runs performed against it.
    """
    __tablename__ = "contract_versions"

    id:               Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_db_id:   Mapped[int]  = mapped_column(
        Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalised string ID for query convenience (mirrors contracts.contract_id)
    contract_id:      Mapped[str]  = mapped_column(String(50), nullable=False, index=True)
    version_number:   Mapped[int]  = mapped_column(Integer, nullable=False)

    file_path:         Mapped[str]      = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str]      = mapped_column(String(512),  nullable=False)
    status:            Mapped[str]      = mapped_column(String(20),   nullable=False, default="uploaded")
    clauses_extracted: Mapped[int|None] = mapped_column(Integer)
    error_message:     Mapped[str|None] = mapped_column(Text)

    uploaded_by_user_id: Mapped[int|None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Per-version workflow (mirrors the fields on Contract for case-level workflow)
    review_status:        Mapped[str]           = mapped_column(String(30), nullable=False, default="uploaded")
    review_decision:      Mapped[str]           = mapped_column(String(30), nullable=False, default="none")
    review_owner_user_id: Mapped[int|None]      = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at:          Mapped[datetime|None] = mapped_column(DateTime(timezone=True))
    internal_notes:       Mapped[str|None]      = mapped_column(Text)

    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    contract:     Mapped["Contract|None"]  = relationship("Contract",  back_populates="versions")
    uploaded_by:  Mapped["User|None"]      = relationship("User", foreign_keys="[ContractVersion.uploaded_by_user_id]")
    review_owner: Mapped["User|None"]      = relationship("User", foreign_keys="[ContractVersion.review_owner_user_id]")
    analyses:     Mapped[list["Analysis"]] = relationship("Analysis",  back_populates="version")


# ── finding_reviews ────────────────────────────────────────────────────────────

class FindingReview(Base):
    """
    Human review disposition for one finding produced by an analysis run.

    One row per (version_id, finding_key) — finding_key is a deterministic
    identifier computed from clause_id + finding_type + topic so that the
    same logical finding can be tracked across re-runs.

    Status lifecycle
    ----------------
    open → in_review → in_negotiation → resolved
                    ↘ accepted_risk
                    ↘ not_applicable
                    ↘ deferred
    """
    __tablename__ = "finding_reviews"

    id:               Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id:      Mapped[str] = mapped_column(String(50),  nullable=False, index=True)
    version_id:       Mapped[int] = mapped_column(Integer, ForeignKey("contract_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_id:      Mapped[int|None] = mapped_column(Integer, ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True)

    # Deterministic key: "{clause_id}__{finding_type}__{topic}"
    finding_key:      Mapped[str] = mapped_column(String(512),  nullable=False, index=True)
    finding_type:     Mapped[str] = mapped_column(String(50),   nullable=False)
    topic:            Mapped[str|None] = mapped_column(String(255))
    severity:         Mapped[str|None] = mapped_column(String(20))
    clause_id:        Mapped[str|None] = mapped_column(String(50))
    text_preview:     Mapped[str|None] = mapped_column(Text)

    # Auto-populated from analysis outputs
    recommended_action:  Mapped[str|None] = mapped_column(Text)
    assigned_owner_role: Mapped[str|None] = mapped_column(String(100))
    confidence_bucket:   Mapped[str|None] = mapped_column(String(50))
    ai_used:             Mapped[bool|None] = mapped_column(Boolean)
    review_priority:     Mapped[str|None] = mapped_column(String(20))

    # Review disposition
    status:            Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    reviewer_user_id:  Mapped[int|None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_user_id:  Mapped[int|None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_comment:    Mapped[str|None] = mapped_column(Text)
    disposition_reason: Mapped[str|None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    version:  Mapped["ContractVersion|None"] = relationship("ContractVersion")
    reviewer: Mapped["User|None"]            = relationship("User", foreign_keys="[FindingReview.reviewer_user_id]")
    assignee: Mapped["User|None"]            = relationship("User", foreign_keys="[FindingReview.assigned_user_id]")


# ── contract_workflow_events ───────────────────────────────────────────────────

class ContractWorkflowEvent(Base):
    """
    Immutable audit log entry recording every workflow state change on a contract.
    Written by PATCH /contracts/{id}/review-status and by pipeline auto-advances.
    Never updated after creation.
    """
    __tablename__ = "contract_workflow_events"

    id:                  Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id:         Mapped[str]           = mapped_column(String(50), ForeignKey("contracts.contract_id", ondelete="CASCADE"), nullable=False, index=True)
    changed_by_user_id:  Mapped[int|None]      = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    old_status:          Mapped[str|None]      = mapped_column(String(30))
    new_status:          Mapped[str]           = mapped_column(String(30), nullable=False)
    old_decision:        Mapped[str|None]      = mapped_column(String(30))
    new_decision:        Mapped[str|None]      = mapped_column(String(30))
    notes:               Mapped[str|None]      = mapped_column(Text)
    created_at:          Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_utcnow)

    contract:      Mapped["Contract|None"] = relationship("Contract", back_populates="workflow_events")
    changed_by:    Mapped["User|None"]     = relationship("User", foreign_keys="[ContractWorkflowEvent.changed_by_user_id]")


# ── app_settings ───────────────────────────────────────────────────────────────

class AppSetting(Base):
    """
    Per-tenant application configuration stored in the database.
    Used for operational switches that admins control without restarting the service.

    Keys (namespaced with module prefix):
      llm.app_enabled  — whether AI-assisted analysis is enabled at the app level
    """
    __tablename__ = "app_settings"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int]      = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key:         Mapped[str]      = mapped_column(String(100), nullable=False)
    value:       Mapped[str|None] = mapped_column(Text)
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
