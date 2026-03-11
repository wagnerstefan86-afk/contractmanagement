"""
SQLAlchemy ORM models — Contract Review Application
Matches schema.sql v1.1 exactly (all 10 validation fixes applied).

Dependencies:
    pip install sqlalchemy psycopg2-binary pgvector alembic
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import Enum as SAEnum
from pgvector.sqlalchemy import Vector


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Python enums  (mirror PostgreSQL enum types)
# ---------------------------------------------------------------------------

class ClauseCategory(str, enum.Enum):
    incident_reporting          = "incident_reporting"
    audit_rights                = "audit_rights"
    subcontractor_management    = "subcontractor_management"
    data_protection_obligations = "data_protection_obligations"
    security_requirements       = "security_requirements"
    availability_sla            = "availability_sla"
    business_continuity         = "business_continuity"
    data_breach_notification    = "data_breach_notification"
    data_retention_deletion     = "data_retention_deletion"
    encryption_requirements     = "encryption_requirements"
    access_control              = "access_control"
    penetration_testing         = "penetration_testing"
    change_management           = "change_management"
    termination_data_return     = "termination_data_return"
    liability_cap               = "liability_cap"
    governing_law               = "governing_law"


class Severity(str, enum.Enum):
    # Fix 4: 'info' is now valid (was excluded from the old TEXT CHECK)
    critical = "critical"
    high     = "high"
    medium   = "medium"
    low      = "low"
    info     = "info"


class ContractType(str, enum.Enum):
    saas             = "saas"
    outsourcing      = "outsourcing"
    cloud_iaas_paas  = "cloud_iaas_paas"
    dpa              = "dpa"
    managed_security = "managed_security"
    professional_svcs = "professional_svcs"
    software_license = "software_license"
    maintenance      = "maintenance"
    joint_venture    = "joint_venture"
    nda              = "nda"


class AnalysisStatus(str, enum.Enum):
    uploaded           = "uploaded"
    parsing            = "parsing"
    chunking           = "chunking"
    classifying        = "classifying"
    extracting_clauses = "extracting_clauses"
    analyzing          = "analyzing"
    scoring            = "scoring"
    generating_summary = "generating_summary"
    completed          = "completed"
    failed             = "failed"


class ClassificationMethod(str, enum.Enum):
    embedding_similarity = "embedding_similarity"
    llm_classification   = "llm_classification"
    hybrid               = "hybrid"
    manual               = "manual"


class LayoutType(str, enum.Enum):
    paragraph    = "paragraph"
    bullet_list  = "bullet_list"
    numbered_list = "numbered_list"
    table        = "table"
    heading      = "heading"
    ocr_text     = "ocr_text"


class ModifierType(str, enum.Enum):
    frequency_cap          = "frequency_cap"
    notice_requirement     = "notice_requirement"
    cost_condition         = "cost_condition"
    supplier_approval      = "supplier_approval"
    scope_carveout         = "scope_carveout"
    timing_delay           = "timing_delay"
    best_efforts_qualifier = "best_efforts_qualifier"


class FindingType(str, enum.Enum):
    present      = "present"
    partial      = "partial"
    non_compliant = "non_compliant"
    missing      = "missing"


class RiskLevel(str, enum.Enum):
    clause    = "clause"
    framework = "framework"
    contract  = "contract"


class Coverage(str, enum.Enum):
    full    = "full"
    partial = "partial"
    none    = "none"


# ---------------------------------------------------------------------------
# SQLAlchemy enum column types (reusable across models)
# ---------------------------------------------------------------------------

_clause_category_enum = SAEnum(
    ClauseCategory, name="clause_category_enum", create_type=False
)
_severity_enum = SAEnum(
    Severity, name="severity_enum", create_type=False
)
_contract_type_enum = SAEnum(
    ContractType, name="contract_type_enum", create_type=False
)
_analysis_status_enum = SAEnum(
    AnalysisStatus, name="analysis_status_enum", create_type=False
)
_classification_method_enum = SAEnum(
    ClassificationMethod, name="classification_method_enum", create_type=False
)
_layout_type_enum = SAEnum(
    LayoutType, name="layout_type_enum", create_type=False
)
_modifier_type_enum = SAEnum(
    ModifierType, name="modifier_type_enum", create_type=False
)
_finding_type_enum = SAEnum(
    FindingType, name="finding_type_enum", create_type=False
)
_risk_level_enum = SAEnum(
    RiskLevel, name="risk_level_enum", create_type=False
)
_coverage_enum = SAEnum(
    Coverage, name="coverage_enum", create_type=False
)


# ============================================================================
# SECTION 1: REQUIREMENT LIBRARY
# ============================================================================

class Framework(Base):
    """Compliance frameworks (ISO 27001, DORA, NIS2, etc.)"""

    __tablename__ = "frameworks"

    id            = Column(Text, primary_key=True)
    name          = Column(Text, nullable=False)
    version       = Column(Text, nullable=False)
    description   = Column(Text)
    authority     = Column(Text)
    reference_url = Column(Text)
    is_active     = Column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at    = Column(
        "created_at", String, nullable=False, server_default=text("NOW()")
    )
    updated_at    = Column(
        "updated_at", String, nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        CheckConstraint(r"id ~ '^[a-z0-9_]+$'", name="frameworks_id_format"),
    )

    # Relationships
    domains: List["Domain"] = relationship(
        "Domain", back_populates="framework", cascade="all, delete-orphan"
    )
    framework_weights: List["ContractTypeFrameworkWeight"] = relationship(
        "ContractTypeFrameworkWeight",
        back_populates="framework",
        cascade="all, delete-orphan",
    )
    # Findings reference frameworks with RESTRICT — no cascade delete here.
    findings: List["Finding"] = relationship(
        "Finding", back_populates="framework"
    )
    risk_scores: List["RiskScore"] = relationship(
        "RiskScore", back_populates="framework"
    )


class Domain(Base):
    """Control families / chapters within a framework."""

    __tablename__ = "domains"

    id           = Column(Text, primary_key=True)
    framework_id = Column(
        Text,
        ForeignKey("frameworks.id", ondelete="CASCADE"),
        nullable=False,
    )
    name         = Column(Text, nullable=False)
    description  = Column(Text)
    sort_order   = Column(Integer, nullable=False, server_default=text("0"))
    created_at   = Column("created_at", String, nullable=False, server_default=text("NOW()"))
    updated_at   = Column("updated_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        CheckConstraint(r"id ~ '^[a-z0-9_]+$'", name="domains_id_format"),
    )

    framework:     "Framework"         = relationship("Framework", back_populates="domains")
    requirements:  List["Requirement"] = relationship(
        "Requirement", back_populates="domain", cascade="all, delete-orphan"
    )


class Requirement(Base):
    """Specific controls or articles within a domain."""

    __tablename__ = "requirements"

    id            = Column(Text, primary_key=True)
    domain_id     = Column(
        Text,
        ForeignKey("domains.id", ondelete="CASCADE"),
        nullable=False,
    )
    name          = Column(Text, nullable=False)
    description   = Column(Text, nullable=False)
    guidance_text = Column(Text)
    sort_order    = Column(Integer, nullable=False, server_default=text("0"))
    created_at    = Column("created_at", String, nullable=False, server_default=text("NOW()"))
    updated_at    = Column("updated_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        CheckConstraint(r"id ~ '^[a-z0-9_]+$'", name="requirements_id_format"),
    )

    domain:           "Domain"               = relationship("Domain", back_populates="requirements")
    sub_requirements: List["SubRequirement"] = relationship(
        "SubRequirement", back_populates="requirement", cascade="all, delete-orphan"
    )


class SubRequirement(Base):
    """Leaf-level obligations within a requirement, linked to clause categories."""

    __tablename__ = "sub_requirements"

    id                       = Column(Text, primary_key=True)
    requirement_id           = Column(
        Text,
        ForeignKey("requirements.id", ondelete="CASCADE"),
        nullable=False,
    )
    name                     = Column(Text, nullable=False)
    description              = Column(Text, nullable=False)
    # Fix 9: non-empty array enforced via DB CHECK; mapped as ARRAY of enum.
    clause_categories        = Column(
        ARRAY(_clause_category_enum), nullable=False
    )
    evidence_keywords        = Column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    # Fix 4: was Text with manual CHECK; now uses severity_enum type.
    missing_severity         = Column(
        _severity_enum, nullable=False, server_default=text("'high'")
    )
    missing_finding_template = Column(Text)
    sort_order               = Column(Integer, nullable=False, server_default=text("0"))
    created_at               = Column("created_at", String, nullable=False, server_default=text("NOW()"))
    updated_at               = Column("updated_at", String, nullable=False, server_default=text("NOW()"))
    # Pre-computed embedding of (description || ' ' || array_to_string(evidence_keywords, ' ')).
    # NULL until the offline requirement library embedding worker runs.
    requirement_embedding    = Column(Vector(1536))

    __table_args__ = (
        CheckConstraint(r"id ~ '^[a-z0-9_]+$'", name="sub_req_id_format"),
        # Fix 9
        CheckConstraint(
            "array_length(clause_categories, 1) >= 1",
            name="sub_req_categories_nonempty",
        ),
    )

    requirement:  "Requirement"                    = relationship("Requirement", back_populates="sub_requirements")
    type_mappings: List["ContractTypeReqMapping"]  = relationship(
        "ContractTypeReqMapping", back_populates="sub_requirement", cascade="all, delete-orphan"
    )
    # RESTRICT on delete — findings and matches reference sub_requirements.
    findings: List["Finding"] = relationship("Finding", back_populates="sub_requirement")
    clause_matches: List["ClauseRequirementMatch"] = relationship(
        "ClauseRequirementMatch", back_populates="sub_requirement"
    )


class ContractTypeReqMapping(Base):
    """Per contract type: which sub-requirements are mandatory and their quality thresholds."""

    __tablename__ = "contract_type_req_mapping"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_type      = Column(_contract_type_enum, nullable=False)
    sub_requirement_id = Column(
        Text,
        ForeignKey("sub_requirements.id", ondelete="CASCADE"),
        nullable=False,
    )
    mandatory          = Column(Boolean, nullable=False, server_default=text("FALSE"))
    min_quality_score  = Column(Numeric(4, 3), nullable=False, server_default=text("0.500"))
    weight             = Column(Numeric(4, 3), nullable=False, server_default=text("0.100"))
    created_at         = Column("created_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("contract_type", "sub_requirement_id", name="uq_contract_type_sub_req"),
        CheckConstraint("min_quality_score BETWEEN 0.0 AND 1.0", name="min_quality_range"),
        CheckConstraint("weight BETWEEN 0.0 AND 1.0", name="weight_range"),
    )

    sub_requirement: "SubRequirement" = relationship("SubRequirement", back_populates="type_mappings")


class ContractTypeFrameworkWeight(Base):
    """Framework weight overrides per contract type."""

    __tablename__ = "contract_type_framework_weights"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_type = Column(_contract_type_enum, nullable=False)
    framework_id  = Column(
        Text,
        ForeignKey("frameworks.id", ondelete="CASCADE"),
        nullable=False,
    )
    weight        = Column(Numeric(4, 3), nullable=False)
    # Fix 6: added created_at — was missing from original schema.
    created_at    = Column("created_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("contract_type", "framework_id", name="uq_ct_fw_weight"),
        CheckConstraint("weight BETWEEN 0.0 AND 1.0", name="ctfw_weight_range"),
    )

    framework: "Framework" = relationship("Framework", back_populates="framework_weights")


# ============================================================================
# SECTION 2: CONTRACT PROCESSING
# ============================================================================

class Contract(Base):
    """Uploaded contract documents with classification and processing status."""

    __tablename__ = "contracts"

    id                      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename                = Column(Text, nullable=False)
    file_hash_sha256        = Column(Text, nullable=False)
    file_size_bytes         = Column(BigInteger, nullable=False)
    file_type               = Column(Text, nullable=False)
    page_count              = Column(Integer)
    # Classification
    primary_type            = Column(_contract_type_enum)
    secondary_types         = Column(ARRAY(_contract_type_enum), server_default=text("'{}'"))
    type_confidence         = Column(Numeric(4, 3))
    # Processing state
    status                  = Column(
        _analysis_status_enum, nullable=False, server_default=text("'uploaded'")
    )
    error_message           = Column(Text)
    # Metadata
    contract_title          = Column(Text)
    supplier_name           = Column(Text)
    effective_date          = Column(Date)
    expiry_date             = Column(Date)
    uploaded_by             = Column(Text)
    # Timestamps
    uploaded_at             = Column("uploaded_at", String, nullable=False, server_default=text("NOW()"))
    processing_started_at   = Column("processing_started_at", String)
    processing_completed_at = Column("processing_completed_at", String)
    created_at              = Column("created_at", String, nullable=False, server_default=text("NOW()"))
    updated_at              = Column("updated_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        CheckConstraint("file_type IN ('pdf', 'docx')", name="file_type_check"),
        CheckConstraint("type_confidence BETWEEN 0.0 AND 1.0", name="type_confidence_range"),
    )

    chunks:                  List["ContractChunk"]        = relationship(
        "ContractChunk", back_populates="contract", cascade="all, delete-orphan"
    )
    clauses:                 List["Clause"]               = relationship(
        "Clause", back_populates="contract", cascade="all, delete-orphan"
    )
    findings:                List["Finding"]              = relationship(
        "Finding", back_populates="contract", cascade="all, delete-orphan"
    )
    risk_scores:             List["RiskScore"]            = relationship(
        "RiskScore", back_populates="contract", cascade="all, delete-orphan"
    )
    explainability_records:  List["ExplainabilityRecord"] = relationship(
        "ExplainabilityRecord", back_populates="contract", cascade="all, delete-orphan"
    )
    management_summary:      Optional["ManagementSummary"] = relationship(
        "ManagementSummary", back_populates="contract", uselist=False, cascade="all, delete-orphan"
    )
    audit_entries:           List["AuditLog"]             = relationship(
        "AuditLog", back_populates="contract"
    )


class ContractChunk(Base):
    """Text segments from contracts with full page/paragraph provenance and embeddings."""

    __tablename__ = "contract_chunks"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id       = Column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index       = Column(Integer, nullable=False)
    # Provenance
    page_start        = Column(Integer, nullable=False)
    page_end          = Column(Integer, nullable=False)
    para_index_start  = Column(Integer)
    para_index_end    = Column(Integer)
    section_header    = Column(Text)
    char_offset_start = Column(Integer, nullable=False)
    char_offset_end   = Column(Integer, nullable=False)
    # Content
    raw_text          = Column(Text, nullable=False)
    normalized_text   = Column(Text, nullable=False)
    token_count       = Column(Integer, nullable=False)
    # Layout classification — set by Stage 2 chunker from Stage 1 structure map
    layout_type       = Column(_layout_type_enum, nullable=False, server_default=text("'paragraph'"))
    # OCR metadata — non-NULL only when layout_type = 'ocr_text'
    ocr_confidence    = Column(Numeric(4, 3))
    # Structured table content — non-NULL only when layout_type = 'table'
    # Schema: {"headers": [...], "rows": [[...]]}
    table_data        = Column(JSONB)
    # Embedding — NULL until embedding worker runs
    embedding         = Column(Vector(1536))
    # Timestamps
    created_at        = Column("created_at", String, nullable=False, server_default=text("NOW()"))
    # Fix 10: updated_at enables stale-embedding detection.
    updated_at        = Column("updated_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("contract_id", "chunk_index", name="uq_chunk_order"),
        CheckConstraint("page_end >= page_start",              name="page_range_valid"),
        CheckConstraint("char_offset_end > char_offset_start", name="char_range_valid"),
        CheckConstraint("token_count > 0",                     name="token_count_positive"),
        CheckConstraint(
            "ocr_confidence IS NULL OR layout_type = 'ocr_text'",
            name="ocr_confidence_layout",
        ),
        CheckConstraint(
            "table_data IS NULL OR layout_type = 'table'",
            name="table_data_layout",
        ),
        CheckConstraint(
            "ocr_confidence IS NULL OR ocr_confidence BETWEEN 0.0 AND 1.0",
            name="ocr_confidence_range",
        ),
    )

    contract: "Contract"   = relationship("Contract", back_populates="chunks")
    clauses:  List["Clause"] = relationship("Clause", back_populates="chunk")


class Clause(Base):
    """Normalized contractual clauses with canonical category classification and provenance."""

    __tablename__ = "clauses"

    id                        = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id               = Column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id                  = Column(
        UUID(as_uuid=True),
        ForeignKey("contract_chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Extracted content
    clause_text               = Column(Text, nullable=False)
    section_reference         = Column(Text)
    # Stage 3 classification
    canonical_categories      = Column(ARRAY(_clause_category_enum), nullable=False)
    primary_category          = Column(_clause_category_enum, nullable=False)
    classification_method     = Column(_classification_method_enum, nullable=False)
    classification_confidence = Column(Numeric(4, 3), nullable=False)
    # Embedding of clause_text (Stage 3 classification)
    clause_embedding          = Column(Vector(1536))
    # Stage 5: LLM-normalized obligation text (active voice, canonical verb "must").
    # NULL until Stage 5 normalization runs.
    normalized_clause         = Column(Text)
    # Embedding of normalized_clause (Stage 5 requirement matching).
    # Kept separate from clause_embedding — they cover different text surfaces.
    normalized_embedding      = Column(Vector(1536))
    # Timestamps
    created_at                = Column("created_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        CheckConstraint(
            "classification_confidence BETWEEN 0.0 AND 1.0",
            name="classification_confidence_range",
        ),
    )

    contract:         "Contract"                        = relationship("Contract", back_populates="clauses")
    chunk:            "ContractChunk"                   = relationship("ContractChunk", back_populates="clauses")
    quality_score:    Optional["ClauseQualityScore"]    = relationship(
        "ClauseQualityScore", back_populates="clause", uselist=False, cascade="all, delete-orphan"
    )
    modifiers:        List["ClauseModifier"]            = relationship(
        "ClauseModifier", back_populates="clause", cascade="all, delete-orphan"
    )
    findings:         List["Finding"]                   = relationship(
        "Finding", back_populates="clause"
    )
    risk_scores:      List["RiskScore"]                 = relationship(
        "RiskScore", back_populates="clause"
    )
    requirement_matches: List["ClauseRequirementMatch"] = relationship(
        "ClauseRequirementMatch", back_populates="clause", cascade="all, delete-orphan"
    )


class ClauseQualityScore(Base):
    """Three-dimension quality evaluation per clause with full sub-component scores."""

    __tablename__ = "clause_quality_scores"

    id                       = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clause_id                = Column(
        UUID(as_uuid=True),
        ForeignKey("clauses.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Dimension scores
    language_strength        = Column(Numeric(4, 3), nullable=False)
    language_pattern_matched = Column(Text)
    specificity_score        = Column(Numeric(4, 3), nullable=False)
    specificity_timeline     = Column(Numeric(4, 3), nullable=False)
    specificity_named_std    = Column(Numeric(4, 3), nullable=False)
    specificity_metric       = Column(Numeric(4, 3), nullable=False)
    specificity_scope        = Column(Numeric(4, 3), nullable=False)
    enforceability_score     = Column(Numeric(4, 3), nullable=False)
    enforceability_details   = Column(JSONB, nullable=False, server_default=text("'{}'"))
    # Composite
    raw_quality_score        = Column(Numeric(4, 3), nullable=False)
    quality_band             = Column(Text, nullable=False)
    # Timestamps
    created_at               = Column("created_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("clause_id", name="uq_clause_quality"),
        CheckConstraint("language_strength    BETWEEN 0.0 AND 1.0", name="ls_range"),
        CheckConstraint("specificity_score    BETWEEN 0.0 AND 1.0", name="ss_range"),
        CheckConstraint("enforceability_score BETWEEN 0.0 AND 1.0", name="es_range"),
        CheckConstraint("raw_quality_score    BETWEEN 0.0 AND 1.0", name="rqs_range"),
        CheckConstraint(
            "quality_band IN ('STRONG', 'ADEQUATE', 'WEAK', 'INADEQUATE', 'NOMINAL')",
            name="quality_band_check",
        ),
    )

    clause: "Clause" = relationship("Clause", back_populates="quality_score")


class ClauseModifier(Base):
    """Detected limitations/weakeners on clauses with individual penalty scores."""

    __tablename__ = "clause_modifiers"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clause_id          = Column(
        UUID(as_uuid=True),
        ForeignKey("clauses.id", ondelete="CASCADE"),
        nullable=False,
    )
    modifier_type      = Column(_modifier_type_enum, nullable=False)
    matched_text       = Column(Text, nullable=False)
    char_offset_start  = Column(Integer)
    penalty_multiplier = Column(Numeric(4, 3), nullable=False)
    audit_note         = Column(Text, nullable=False)
    created_at         = Column("created_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        CheckConstraint("penalty_multiplier BETWEEN 0.0 AND 1.0", name="penalty_range"),
    )

    clause: "Clause" = relationship("Clause", back_populates="modifiers")


class ClauseRequirementMatch(Base):
    """Stage 5 intermediate: every evaluated (clause, sub_requirement) pair.

    Pass 1 (embedding similarity) and Pass 2 (LLM validation) results live on
    the same row. is_best_match = TRUE marks the winning clause per
    (contract_id, sub_requirement_id); that row is promoted to findings.
    """

    __tablename__ = "clause_requirement_matches"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id          = Column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    clause_id            = Column(
        UUID(as_uuid=True), ForeignKey("clauses.id", ondelete="CASCADE"), nullable=False
    )
    sub_requirement_id   = Column(
        Text, ForeignKey("sub_requirements.id", ondelete="RESTRICT"), nullable=False
    )
    framework_id         = Column(
        Text, ForeignKey("frameworks.id", ondelete="RESTRICT"), nullable=False
    )
    # Pass 1 — always populated on insert
    embedding_similarity = Column(Numeric(5, 4), nullable=False)
    # Pass 2 — NULL until LLM step runs
    llm_validated        = Column(Boolean)
    llm_confidence       = Column(Numeric(4, 3))
    coverage             = Column(_coverage_enum)
    explanation          = Column(Text)
    missing_elements     = Column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    # Composite score — NULL until both passes complete
    # Formula: 0.35*embedding_similarity + 0.45*llm_confidence + 0.20*quality_band_score
    match_confidence     = Column(Numeric(4, 3))
    is_best_match        = Column(Boolean, nullable=False, server_default=text("FALSE"))
    # LLM metadata
    llm_model_used       = Column(Text)
    llm_prompt_version   = Column(Text)
    created_at           = Column("created_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        CheckConstraint("embedding_similarity BETWEEN 0.0 AND 1.0", name="emb_sim_range"),
        CheckConstraint(
            "llm_confidence IS NULL OR llm_confidence BETWEEN 0.0 AND 1.0",
            name="llm_conf_range",
        ),
        CheckConstraint(
            "match_confidence IS NULL OR match_confidence BETWEEN 0.0 AND 1.0",
            name="match_conf_range",
        ),
    )

    clause:          "Clause"          = relationship("Clause",         back_populates="requirement_matches")
    sub_requirement: "SubRequirement"  = relationship("SubRequirement", back_populates="clause_matches")


# ============================================================================
# SECTION 3: ANALYSIS
# ============================================================================

class Finding(Base):
    """Core analytical output: each finding links a clause (or absence) to a framework sub-requirement."""

    __tablename__ = "findings"

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id           = Column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # NULL for finding_type='missing'
    clause_id             = Column(
        UUID(as_uuid=True),
        ForeignKey("clauses.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Fix 1: ON DELETE RESTRICT — finding must not survive framework deletion.
    framework_id          = Column(
        Text,
        ForeignKey("frameworks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Fix 2: ON DELETE RESTRICT — same rationale.
    sub_requirement_id    = Column(
        Text,
        ForeignKey("sub_requirements.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Assessment
    finding_type          = Column(_finding_type_enum, nullable=False)
    severity              = Column(_severity_enum, nullable=False)
    confidence            = Column(Numeric(4, 3), nullable=False)
    justification         = Column(Text, nullable=False)
    recommendation        = Column(Text, nullable=False)
    # Scoring inputs
    clause_risk_score     = Column(Numeric(5, 2), nullable=False, server_default=text("0.00"))
    # Denormalized quality context
    clause_quality_score  = Column(Numeric(4, 3))
    # Fix 5: CHECK constraint added (see __table_args__)
    clause_quality_band   = Column(Text)
    post_modifier_quality = Column(Numeric(4, 3))
    # Metadata
    llm_model_used        = Column(Text)
    llm_prompt_version    = Column(Text)
    created_at            = Column("created_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        CheckConstraint("confidence        BETWEEN 0.0 AND 1.0",   name="confidence_range"),
        CheckConstraint("clause_risk_score BETWEEN 0.0 AND 100.0", name="clause_risk_range"),
        # Fix 5: enforce same domain as clause_quality_scores.quality_band.
        CheckConstraint(
            "clause_quality_band IS NULL "
            "OR clause_quality_band IN ('STRONG','ADEQUATE','WEAK','INADEQUATE','NOMINAL')",
            name="clause_quality_band_check",
        ),
        CheckConstraint(
            "(finding_type = 'missing' AND clause_id IS NULL) "
            "OR (finding_type != 'missing' AND clause_id IS NOT NULL)",
            name="missing_clause_null",
        ),
    )

    contract:         "Contract"        = relationship("Contract", back_populates="findings")
    clause:           Optional["Clause"] = relationship("Clause", back_populates="findings")
    framework:        "Framework"       = relationship("Framework", back_populates="findings")
    sub_requirement:  "SubRequirement"  = relationship("SubRequirement", back_populates="findings")


class RiskScore(Base):
    """Three-level risk scores (clause/framework/contract) with breakdown counts."""

    __tablename__ = "risk_scores"

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id           = Column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    risk_level            = Column(_risk_level_enum, nullable=False)
    # Polymorphic references
    clause_id             = Column(
        UUID(as_uuid=True),
        ForeignKey("clauses.id", ondelete="CASCADE"),
        nullable=True,
    )
    # Fix 3: ON DELETE SET NULL — preserves numeric history after framework deletion.
    framework_id          = Column(
        Text,
        ForeignKey("frameworks.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Score
    risk_score            = Column(Numeric(5, 2), nullable=False)
    risk_band             = Column(Text, nullable=False)
    weight_used           = Column(Numeric(4, 3))
    # Breakdown
    missing_count         = Column(Integer, nullable=False, server_default=text("0"))
    critical_count        = Column(Integer, nullable=False, server_default=text("0"))
    high_count            = Column(Integer, nullable=False, server_default=text("0"))
    partial_count         = Column(Integer, nullable=False, server_default=text("0"))
    compliant_count       = Column(Integer, nullable=False, server_default=text("0"))
    # Metadata
    scoring_model_version = Column(Text, nullable=False, server_default=text("'1.0.0'"))
    created_at            = Column("created_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        CheckConstraint("risk_score BETWEEN 0.0 AND 100.0", name="risk_score_range"),
        CheckConstraint(
            "risk_band IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')", name="risk_band_check"
        ),
        CheckConstraint(
            "(risk_level = 'clause'    AND clause_id IS NOT NULL AND framework_id IS NOT NULL) "
            "OR (risk_level = 'framework' AND clause_id IS NULL    AND framework_id IS NOT NULL) "
            "OR (risk_level = 'contract'  AND clause_id IS NULL    AND framework_id IS NULL)",
            name="risk_level_refs",
        ),
    )

    contract:  "Contract"           = relationship("Contract", back_populates="risk_scores")
    clause:    Optional["Clause"]   = relationship("Clause", back_populates="risk_scores")
    framework: Optional["Framework"] = relationship("Framework", back_populates="risk_scores")


class ExplainabilityRecord(Base):
    """Deterministic score decomposition trees for audit documentation, hash-verified."""

    __tablename__ = "explainability_records"

    id                          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id                 = Column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Versioning and integrity
    scoring_model_version       = Column(Text, nullable=False)
    requirement_library_version = Column(Text, nullable=False)
    llm_model_used              = Column(Text, nullable=False)
    input_data_hash             = Column(Text, nullable=False)
    # Decomposition tree
    explanation_tree            = Column(JSONB, nullable=False)
    score_reconstruction        = Column(JSONB, nullable=False)
    # Audit metadata
    human_review_required       = Column(Boolean, nullable=False, server_default=text("TRUE"))
    human_review_flags          = Column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    reviewed_by                 = Column(Text)
    reviewed_at                 = Column("reviewed_at", String)
    review_notes                = Column(Text)
    # Timestamps
    generated_at                = Column("generated_at", String, nullable=False, server_default=text("NOW()"))
    created_at                  = Column("created_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint(
            "contract_id", "scoring_model_version", name="uq_explainability_contract"
        ),
    )

    contract: "Contract" = relationship("Contract", back_populates="explainability_records")


# ============================================================================
# SECTION 4: REPORTING
# ============================================================================

class ManagementSummary(Base):
    """LLM-generated management summaries, explicitly labeled as AI-generated output."""

    __tablename__ = "management_summaries"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id       = Column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Summary content
    executive_summary = Column(Text, nullable=False)
    key_findings      = Column(JSONB, nullable=False)
    risk_assessment   = Column(Text, nullable=False)
    recommendations   = Column(JSONB, nullable=False)
    # Generation metadata
    llm_model_used    = Column(Text, nullable=False)
    llm_prompt_version = Column(Text, nullable=False)
    is_ai_generated   = Column(Boolean, nullable=False, server_default=text("TRUE"))
    # Timestamps
    generated_at      = Column("generated_at", String, nullable=False, server_default=text("NOW()"))
    created_at        = Column("created_at", String, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("contract_id", name="uq_summary_contract"),
    )

    contract: "Contract" = relationship("Contract", back_populates="management_summary")


# ============================================================================
# SECTION 5: AUDIT LOG
# ============================================================================

class AuditLog(Base):
    """Append-only audit trail for all significant actions."""

    __tablename__ = "audit_log"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id = Column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="SET NULL"),
        nullable=True,
    )
    action      = Column(Text, nullable=False)
    actor       = Column(Text, nullable=False)
    details     = Column(JSONB, nullable=False, server_default=text("'{}'"))
    created_at  = Column("created_at", String, nullable=False, server_default=text("NOW()"))

    contract: Optional["Contract"] = relationship("Contract", back_populates="audit_entries")
