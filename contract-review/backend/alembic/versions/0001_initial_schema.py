"""Initial schema — contract review application (v1.1, all 10 fixes applied)

Revision ID: 0001
Revises:
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Enum definitions (created once, referenced by multiple tables)
# ---------------------------------------------------------------------------

clause_category_enum = postgresql.ENUM(
    "incident_reporting",
    "audit_rights",
    "subcontractor_management",
    "data_protection_obligations",
    "security_requirements",
    "availability_sla",
    "business_continuity",
    "data_breach_notification",
    "data_retention_deletion",
    "encryption_requirements",
    "access_control",
    "penetration_testing",
    "change_management",
    "termination_data_return",
    "liability_cap",
    "governing_law",
    name="clause_category_enum",
)

# Fix 4: severity_enum defined before sub_requirements (hoisted from Section 3).
severity_enum = postgresql.ENUM(
    "critical", "high", "medium", "low", "info",
    name="severity_enum",
)

contract_type_enum = postgresql.ENUM(
    "saas",
    "outsourcing",
    "cloud_iaas_paas",
    "dpa",
    "managed_security",
    "professional_svcs",
    "software_license",
    "maintenance",
    "joint_venture",
    "nda",
    name="contract_type_enum",
)

analysis_status_enum = postgresql.ENUM(
    "uploaded",
    "parsing",
    "chunking",
    "classifying",
    "extracting_clauses",
    "analyzing",
    "scoring",
    "generating_summary",
    "completed",
    "failed",
    name="analysis_status_enum",
)

classification_method_enum = postgresql.ENUM(
    "embedding_similarity",
    "llm_classification",
    "hybrid",
    "manual",
    name="classification_method_enum",
)

modifier_type_enum = postgresql.ENUM(
    "frequency_cap",
    "notice_requirement",
    "cost_condition",
    "supplier_approval",
    "scope_carveout",
    "timing_delay",
    "best_efforts_qualifier",
    name="modifier_type_enum",
)

finding_type_enum = postgresql.ENUM(
    "present", "partial", "non_compliant", "missing",
    name="finding_type_enum",
)

risk_level_enum = postgresql.ENUM(
    "clause", "framework", "contract",
    name="risk_level_enum",
)


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # PostgreSQL extensions
    # -----------------------------------------------------------------------
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgvector"')

    # -----------------------------------------------------------------------
    # Create enum types
    # Fix 4: clause_category_enum and severity_enum are created BEFORE
    # sub_requirements so the table can reference them without a workaround.
    # -----------------------------------------------------------------------
    clause_category_enum.create(op.get_bind(), checkfirst=True)
    severity_enum.create(op.get_bind(), checkfirst=True)
    contract_type_enum.create(op.get_bind(), checkfirst=True)
    analysis_status_enum.create(op.get_bind(), checkfirst=True)
    classification_method_enum.create(op.get_bind(), checkfirst=True)
    modifier_type_enum.create(op.get_bind(), checkfirst=True)
    finding_type_enum.create(op.get_bind(), checkfirst=True)
    risk_level_enum.create(op.get_bind(), checkfirst=True)

    # -----------------------------------------------------------------------
    # SECTION 1: REQUIREMENT LIBRARY
    # -----------------------------------------------------------------------

    op.create_table(
        "frameworks",
        sa.Column("id",            sa.Text,    primary_key=True),
        sa.Column("name",          sa.Text,    nullable=False),
        sa.Column("version",       sa.Text,    nullable=False),
        sa.Column("description",   sa.Text),
        sa.Column("authority",     sa.Text),
        sa.Column("reference_url", sa.Text),
        sa.Column("is_active",     sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at",    sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at",    sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(r"id ~ '^[a-z0-9_]+$'", name="frameworks_id_format"),
    )
    op.execute("COMMENT ON TABLE frameworks IS 'Compliance frameworks (ISO 27001, DORA, NIS2, etc.)'")

    op.create_table(
        "domains",
        sa.Column("id",          sa.Text, primary_key=True),
        sa.Column("framework_id", sa.Text, sa.ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name",        sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("sort_order",  sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at",  sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at",  sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(r"id ~ '^[a-z0-9_]+$'", name="domains_id_format"),
    )
    op.create_index("idx_domains_framework", "domains", ["framework_id"])
    op.execute("COMMENT ON TABLE domains IS 'Control families / chapters within a framework'")

    op.create_table(
        "requirements",
        sa.Column("id",            sa.Text, primary_key=True),
        sa.Column("domain_id",     sa.Text, sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name",          sa.Text, nullable=False),
        sa.Column("description",   sa.Text, nullable=False),
        sa.Column("guidance_text", sa.Text),
        sa.Column("sort_order",    sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at",    sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at",    sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(r"id ~ '^[a-z0-9_]+$'", name="requirements_id_format"),
    )
    op.create_index("idx_requirements_domain", "requirements", ["domain_id"])
    op.execute("COMMENT ON TABLE requirements IS 'Specific controls or articles within a domain'")

    op.create_table(
        "sub_requirements",
        sa.Column("id",                       sa.Text, primary_key=True),
        sa.Column("requirement_id",           sa.Text, sa.ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name",                     sa.Text, nullable=False),
        sa.Column("description",              sa.Text, nullable=False),
        # Fix 9: non-empty CHECK enforced in __table_args__ below
        sa.Column("clause_categories",        postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("evidence_keywords",        postgresql.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        # Fix 4: severity_enum type (not TEXT)
        sa.Column("missing_severity",         severity_enum, nullable=False, server_default=sa.text("'high'")),
        sa.Column("missing_finding_template", sa.Text),
        sa.Column("sort_order",               sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at",               sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at",               sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(r"id ~ '^[a-z0-9_]+$'", name="sub_req_id_format"),
        # Fix 9
        sa.CheckConstraint("array_length(clause_categories, 1) >= 1", name="sub_req_categories_nonempty"),
    )
    op.create_index("idx_sub_requirements_requirement", "sub_requirements", ["requirement_id"])
    op.create_index(
        "idx_sub_requirements_categories", "sub_requirements",
        ["clause_categories"], postgresql_using="gin",
    )
    op.execute("COMMENT ON TABLE sub_requirements IS 'Leaf-level obligations within a requirement, linked to clause categories'")

    op.create_table(
        "contract_type_req_mapping",
        sa.Column("id",                 postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contract_type",      contract_type_enum, nullable=False),
        sa.Column("sub_requirement_id", sa.Text, sa.ForeignKey("sub_requirements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mandatory",          sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
        sa.Column("min_quality_score",  sa.Numeric(4, 3), nullable=False, server_default=sa.text("0.500")),
        sa.Column("weight",             sa.Numeric(4, 3), nullable=False, server_default=sa.text("0.100")),
        sa.Column("created_at",         sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("contract_type", "sub_requirement_id", name="uq_contract_type_sub_req"),
        sa.CheckConstraint("min_quality_score BETWEEN 0.0 AND 1.0", name="min_quality_range"),
        sa.CheckConstraint("weight BETWEEN 0.0 AND 1.0", name="weight_range"),
    )
    op.create_index(
        "idx_ctrm_type_mandatory", "contract_type_req_mapping",
        ["contract_type", "mandatory"],
        postgresql_where=sa.text("mandatory = TRUE"),
    )
    op.create_index("idx_ctrm_sub_req", "contract_type_req_mapping", ["sub_requirement_id"])
    op.execute("COMMENT ON TABLE contract_type_req_mapping IS 'Per contract type: which sub-requirements are mandatory and their quality thresholds'")

    op.create_table(
        "contract_type_framework_weights",
        sa.Column("id",            postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contract_type", contract_type_enum, nullable=False),
        sa.Column("framework_id",  sa.Text, sa.ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weight",        sa.Numeric(4, 3), nullable=False),
        # Fix 6: created_at added
        sa.Column("created_at",    sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("contract_type", "framework_id", name="uq_ct_fw_weight"),
        sa.CheckConstraint("weight BETWEEN 0.0 AND 1.0", name="ctfw_weight_range"),
    )
    op.create_index("idx_ctfw_type", "contract_type_framework_weights", ["contract_type"])
    op.execute("COMMENT ON TABLE contract_type_framework_weights IS 'Framework weight overrides per contract type. Weights are renormalized to sum=1.0 at query time'")

    # -----------------------------------------------------------------------
    # SECTION 2: CONTRACT PROCESSING
    # -----------------------------------------------------------------------

    op.create_table(
        "contracts",
        sa.Column("id",                      postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("filename",                sa.Text, nullable=False),
        sa.Column("file_hash_sha256",        sa.Text, nullable=False),
        sa.Column("file_size_bytes",         sa.BigInteger, nullable=False),
        sa.Column("file_type",               sa.Text, nullable=False),
        sa.Column("page_count",              sa.Integer),
        sa.Column("primary_type",            contract_type_enum),
        sa.Column("secondary_types",         postgresql.ARRAY(sa.Text), server_default=sa.text("'{}'")),
        sa.Column("type_confidence",         sa.Numeric(4, 3)),
        sa.Column("status",                  analysis_status_enum, nullable=False, server_default=sa.text("'uploaded'")),
        sa.Column("error_message",           sa.Text),
        sa.Column("contract_title",          sa.Text),
        sa.Column("supplier_name",           sa.Text),
        sa.Column("effective_date",          sa.Date),
        sa.Column("expiry_date",             sa.Date),
        sa.Column("uploaded_by",             sa.Text),
        sa.Column("uploaded_at",             sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("processing_started_at",   sa.TIMESTAMP(timezone=True)),
        sa.Column("processing_completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at",              sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at",              sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("file_type IN ('pdf', 'docx')", name="file_type_check"),
        sa.CheckConstraint("type_confidence BETWEEN 0.0 AND 1.0", name="type_confidence_range"),
    )
    op.create_index("idx_contracts_status",    "contracts", ["status"])
    op.create_index("idx_contracts_file_hash", "contracts", ["file_hash_sha256"])
    op.create_index(
        "idx_contracts_supplier", "contracts", ["supplier_name"],
        postgresql_where=sa.text("supplier_name IS NOT NULL"),
    )
    op.create_index("idx_contracts_uploaded",  "contracts", [sa.text("uploaded_at DESC")])
    op.execute("COMMENT ON TABLE contracts IS 'Uploaded contract documents with classification and processing status'")

    op.create_table(
        "contract_chunks",
        sa.Column("id",                postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contract_id",       postgresql.UUID(as_uuid=True), sa.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index",       sa.Integer, nullable=False),
        sa.Column("page_start",        sa.Integer, nullable=False),
        sa.Column("page_end",          sa.Integer, nullable=False),
        sa.Column("para_index_start",  sa.Integer),
        sa.Column("para_index_end",    sa.Integer),
        sa.Column("section_header",    sa.Text),
        sa.Column("char_offset_start", sa.Integer, nullable=False),
        sa.Column("char_offset_end",   sa.Integer, nullable=False),
        sa.Column("raw_text",          sa.Text, nullable=False),
        sa.Column("normalized_text",   sa.Text, nullable=False),
        sa.Column("token_count",       sa.Integer, nullable=False),
        # embedding created via raw SQL — pgvector type not natively in SQLAlchemy core
        sa.Column("created_at",        sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        # Fix 10: added updated_at
        sa.Column("updated_at",        sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("contract_id", "chunk_index", name="uq_chunk_order"),
        sa.CheckConstraint("page_end >= page_start",              name="page_range_valid"),
        sa.CheckConstraint("char_offset_end > char_offset_start", name="char_range_valid"),
        sa.CheckConstraint("token_count > 0",                     name="token_count_positive"),
    )
    # Add vector column separately — requires pgvector extension already installed
    op.execute("ALTER TABLE contract_chunks ADD COLUMN embedding vector(1536)")
    op.create_index("idx_chunks_contract_order", "contract_chunks", ["contract_id", "chunk_index"])
    op.execute(
        "CREATE INDEX idx_chunks_embedding ON contract_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.create_index("idx_chunks_pages", "contract_chunks", ["contract_id", "page_start", "page_end"])
    op.execute("COMMENT ON TABLE contract_chunks IS 'Text segments from contracts with full page/paragraph provenance and embeddings'")

    op.create_table(
        "clauses",
        sa.Column("id",                        postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contract_id",               postgresql.UUID(as_uuid=True), sa.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_id",                  postgresql.UUID(as_uuid=True), sa.ForeignKey("contract_chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clause_text",               sa.Text, nullable=False),
        sa.Column("section_reference",         sa.Text),
        sa.Column("canonical_categories",      postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("primary_category",          sa.Text, nullable=False),
        sa.Column("classification_method",     classification_method_enum, nullable=False),
        sa.Column("classification_confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("created_at",                sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("classification_confidence BETWEEN 0.0 AND 1.0", name="classification_confidence_range"),
    )
    op.execute("ALTER TABLE clauses ADD COLUMN clause_embedding vector(1536)")
    op.create_index("idx_clauses_contract",     "clauses", ["contract_id"])
    op.create_index("idx_clauses_primary_cat",  "clauses", ["primary_category"])
    op.create_index("idx_clauses_categories",   "clauses", ["canonical_categories"], postgresql_using="gin")
    op.create_index("idx_clauses_chunk",        "clauses", ["chunk_id"])
    op.execute(
        "CREATE INDEX idx_clauses_embedding ON clauses "
        "USING ivfflat (clause_embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute("COMMENT ON TABLE clauses IS 'Normalized contractual clauses with canonical category classification and provenance'")

    op.create_table(
        "clause_quality_scores",
        sa.Column("id",                       postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("clause_id",                postgresql.UUID(as_uuid=True), sa.ForeignKey("clauses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language_strength",        sa.Numeric(4, 3), nullable=False),
        sa.Column("language_pattern_matched", sa.Text),
        sa.Column("specificity_score",        sa.Numeric(4, 3), nullable=False),
        sa.Column("specificity_timeline",     sa.Numeric(4, 3), nullable=False),
        sa.Column("specificity_named_std",    sa.Numeric(4, 3), nullable=False),
        sa.Column("specificity_metric",       sa.Numeric(4, 3), nullable=False),
        sa.Column("specificity_scope",        sa.Numeric(4, 3), nullable=False),
        sa.Column("enforceability_score",     sa.Numeric(4, 3), nullable=False),
        sa.Column("enforceability_details",   postgresql.JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("raw_quality_score",        sa.Numeric(4, 3), nullable=False),
        sa.Column("quality_band",             sa.Text, nullable=False),
        sa.Column("created_at",               sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("clause_id", name="uq_clause_quality"),
        sa.CheckConstraint("language_strength    BETWEEN 0.0 AND 1.0", name="ls_range"),
        sa.CheckConstraint("specificity_score    BETWEEN 0.0 AND 1.0", name="ss_range"),
        sa.CheckConstraint("enforceability_score BETWEEN 0.0 AND 1.0", name="es_range"),
        sa.CheckConstraint("raw_quality_score    BETWEEN 0.0 AND 1.0", name="rqs_range"),
        sa.CheckConstraint(
            "quality_band IN ('STRONG','ADEQUATE','WEAK','INADEQUATE','NOMINAL')",
            name="quality_band_check",
        ),
    )
    op.create_index("idx_cqs_clause", "clause_quality_scores", ["clause_id"])
    op.create_index("idx_cqs_band",   "clause_quality_scores", ["quality_band"])
    op.execute("COMMENT ON TABLE clause_quality_scores IS 'Three-dimension quality evaluation per clause with full sub-component scores'")

    op.create_table(
        "clause_modifiers",
        sa.Column("id",                 postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("clause_id",          postgresql.UUID(as_uuid=True), sa.ForeignKey("clauses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("modifier_type",      modifier_type_enum, nullable=False),
        sa.Column("matched_text",       sa.Text, nullable=False),
        sa.Column("char_offset_start",  sa.Integer),
        sa.Column("penalty_multiplier", sa.Numeric(4, 3), nullable=False),
        sa.Column("audit_note",         sa.Text, nullable=False),
        sa.Column("created_at",         sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("penalty_multiplier BETWEEN 0.0 AND 1.0", name="penalty_range"),
    )
    op.create_index("idx_modifiers_clause", "clause_modifiers", ["clause_id"])
    op.create_index("idx_modifiers_type",   "clause_modifiers", ["modifier_type"])
    op.execute("COMMENT ON TABLE clause_modifiers IS 'Detected limitations/weakeners on clauses with individual penalty scores'")

    # -----------------------------------------------------------------------
    # SECTION 3: ANALYSIS
    # -----------------------------------------------------------------------

    op.create_table(
        "findings",
        sa.Column("id",                    postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contract_id",           postgresql.UUID(as_uuid=True), sa.ForeignKey("contracts.id",        ondelete="CASCADE"),   nullable=False),
        sa.Column("clause_id",             postgresql.UUID(as_uuid=True), sa.ForeignKey("clauses.id",          ondelete="SET NULL"),  nullable=True),
        # Fix 1: ON DELETE RESTRICT
        sa.Column("framework_id",          sa.Text,                       sa.ForeignKey("frameworks.id",       ondelete="RESTRICT"),  nullable=False),
        # Fix 2: ON DELETE RESTRICT
        sa.Column("sub_requirement_id",    sa.Text,                       sa.ForeignKey("sub_requirements.id", ondelete="RESTRICT"),  nullable=False),
        sa.Column("finding_type",          finding_type_enum, nullable=False),
        sa.Column("severity",              severity_enum,     nullable=False),
        sa.Column("confidence",            sa.Numeric(4, 3),  nullable=False),
        sa.Column("justification",         sa.Text,           nullable=False),
        sa.Column("recommendation",        sa.Text,           nullable=False),
        sa.Column("clause_risk_score",     sa.Numeric(5, 2),  nullable=False, server_default=sa.text("0.00")),
        sa.Column("clause_quality_score",  sa.Numeric(4, 3)),
        # Fix 5: CHECK added below
        sa.Column("clause_quality_band",   sa.Text),
        sa.Column("post_modifier_quality", sa.Numeric(4, 3)),
        sa.Column("llm_model_used",        sa.Text),
        sa.Column("llm_prompt_version",    sa.Text),
        sa.Column("created_at",            sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("confidence        BETWEEN 0.0 AND 1.0",   name="confidence_range"),
        sa.CheckConstraint("clause_risk_score BETWEEN 0.0 AND 100.0", name="clause_risk_range"),
        # Fix 5
        sa.CheckConstraint(
            "clause_quality_band IS NULL "
            "OR clause_quality_band IN ('STRONG','ADEQUATE','WEAK','INADEQUATE','NOMINAL')",
            name="clause_quality_band_check",
        ),
        sa.CheckConstraint(
            "(finding_type = 'missing' AND clause_id IS NULL) "
            "OR (finding_type != 'missing' AND clause_id IS NOT NULL)",
            name="missing_clause_null",
        ),
    )
    op.create_index("idx_findings_contract",          "findings", ["contract_id"])
    op.create_index("idx_findings_contract_framework","findings", ["contract_id", "framework_id"])
    op.create_index(
        "idx_findings_severity", "findings", ["severity"],
        postgresql_where=sa.text("severity IN ('critical', 'high')"),
    )
    op.create_index("idx_findings_type",    "findings", ["finding_type"])
    op.create_index(
        "idx_findings_clause", "findings", ["clause_id"],
        postgresql_where=sa.text("clause_id IS NOT NULL"),
    )
    op.create_index("idx_findings_sub_req", "findings", ["sub_requirement_id"])
    # Fix 8: gap-detection composite index
    op.create_index(
        "idx_findings_gap_detection", "findings",
        ["contract_id", "sub_requirement_id", "finding_type"],
    )
    op.execute("COMMENT ON TABLE findings IS 'Core analytical output: each finding links a clause (or absence) to a framework sub-requirement'")

    op.create_table(
        "risk_scores",
        sa.Column("id",                    postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contract_id",           postgresql.UUID(as_uuid=True), sa.ForeignKey("contracts.id", ondelete="CASCADE"),  nullable=False),
        sa.Column("risk_level",            risk_level_enum, nullable=False),
        sa.Column("clause_id",             postgresql.UUID(as_uuid=True), sa.ForeignKey("clauses.id",   ondelete="CASCADE"),  nullable=True),
        # Fix 3: ON DELETE SET NULL
        sa.Column("framework_id",          sa.Text, sa.ForeignKey("frameworks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("risk_score",            sa.Numeric(5, 2), nullable=False),
        sa.Column("risk_band",             sa.Text,          nullable=False),
        sa.Column("weight_used",           sa.Numeric(4, 3)),
        sa.Column("missing_count",         sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("critical_count",        sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("high_count",            sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("partial_count",         sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("compliant_count",       sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("scoring_model_version", sa.Text, nullable=False, server_default=sa.text("'1.0.0'")),
        sa.Column("created_at",            sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("risk_score BETWEEN 0.0 AND 100.0", name="risk_score_range"),
        sa.CheckConstraint("risk_band IN ('CRITICAL','HIGH','MEDIUM','LOW')", name="risk_band_check"),
        sa.CheckConstraint(
            "(risk_level = 'clause'    AND clause_id IS NOT NULL AND framework_id IS NOT NULL) "
            "OR (risk_level = 'framework' AND clause_id IS NULL    AND framework_id IS NOT NULL) "
            "OR (risk_level = 'contract'  AND clause_id IS NULL    AND framework_id IS NULL)",
            name="risk_level_refs",
        ),
    )
    op.create_index("idx_risk_scores_contract_level", "risk_scores", ["contract_id", "risk_level"])
    op.create_index(
        "idx_risk_scores_framework", "risk_scores", ["contract_id", "framework_id"],
        postgresql_where=sa.text("risk_level = 'framework'"),
    )
    op.create_index(
        "idx_risk_scores_contract_level_contract", "risk_scores", ["contract_id"],
        postgresql_where=sa.text("risk_level = 'contract'"),
    )
    op.execute("COMMENT ON TABLE risk_scores IS 'Three-level risk scores (clause/framework/contract) with breakdown counts'")

    op.create_table(
        "explainability_records",
        sa.Column("id",                          postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contract_id",                 postgresql.UUID(as_uuid=True), sa.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scoring_model_version",       sa.Text, nullable=False),
        sa.Column("requirement_library_version", sa.Text, nullable=False),
        sa.Column("llm_model_used",              sa.Text, nullable=False),
        sa.Column("input_data_hash",             sa.Text, nullable=False),
        sa.Column("explanation_tree",            postgresql.JSONB, nullable=False),
        sa.Column("score_reconstruction",        postgresql.JSONB, nullable=False),
        sa.Column("human_review_required",       sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
        sa.Column("human_review_flags",          postgresql.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("reviewed_by",                 sa.Text),
        sa.Column("reviewed_at",                 sa.TIMESTAMP(timezone=True)),
        sa.Column("review_notes",                sa.Text),
        sa.Column("generated_at",               sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_at",                  sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("contract_id", "scoring_model_version", name="uq_explainability_contract"),
    )
    op.create_index("idx_explain_contract", "explainability_records", ["contract_id"])
    # Fix 7: index on contract_id (not on the constant-value column human_review_required)
    op.create_index(
        "idx_explain_review_pending", "explainability_records", ["contract_id"],
        postgresql_where=sa.text("human_review_required = TRUE AND reviewed_at IS NULL"),
    )
    op.execute("COMMENT ON TABLE explainability_records IS 'Deterministic score decomposition trees for audit documentation, hash-verified'")

    # -----------------------------------------------------------------------
    # SECTION 4: REPORTING
    # -----------------------------------------------------------------------

    op.create_table(
        "management_summaries",
        sa.Column("id",                 postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contract_id",        postgresql.UUID(as_uuid=True), sa.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("executive_summary",  sa.Text,          nullable=False),
        sa.Column("key_findings",       postgresql.JSONB,  nullable=False),
        sa.Column("risk_assessment",    sa.Text,          nullable=False),
        sa.Column("recommendations",    postgresql.JSONB,  nullable=False),
        sa.Column("llm_model_used",     sa.Text,          nullable=False),
        sa.Column("llm_prompt_version", sa.Text,          nullable=False),
        sa.Column("is_ai_generated",    sa.Boolean,       nullable=False, server_default=sa.text("TRUE")),
        sa.Column("generated_at",       sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_at",         sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("contract_id", name="uq_summary_contract"),
    )
    op.create_index("idx_summaries_contract", "management_summaries", ["contract_id"])
    op.execute("COMMENT ON TABLE management_summaries IS 'LLM-generated management summaries, explicitly labeled as AI-generated output'")

    # -----------------------------------------------------------------------
    # SECTION 5: AUDIT LOG
    # -----------------------------------------------------------------------

    op.create_table(
        "audit_log",
        sa.Column("id",          postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action",      sa.Text,         nullable=False),
        sa.Column("actor",       sa.Text,         nullable=False),
        sa.Column("details",     postgresql.JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at",  sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_audit_contract", "audit_log", ["contract_id", "created_at"])
    op.create_index("idx_audit_actor",    "audit_log", ["actor", "created_at"])
    op.create_index("idx_audit_action",   "audit_log", ["action"])
    op.execute("COMMENT ON TABLE audit_log IS 'Append-only audit trail for all significant actions. Required for ISO 27001 / DORA compliance.'")


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("audit_log")
    op.drop_table("management_summaries")
    op.drop_table("explainability_records")
    op.drop_table("risk_scores")
    op.drop_table("findings")
    op.drop_table("clause_modifiers")
    op.drop_table("clause_quality_scores")
    op.drop_table("clauses")
    op.drop_table("contract_chunks")
    op.drop_table("contracts")
    op.drop_table("contract_type_framework_weights")
    op.drop_table("contract_type_req_mapping")
    op.drop_table("sub_requirements")
    op.drop_table("requirements")
    op.drop_table("domains")
    op.drop_table("frameworks")

    # Drop enum types in reverse order
    risk_level_enum.drop(op.get_bind(), checkfirst=True)
    finding_type_enum.drop(op.get_bind(), checkfirst=True)
    modifier_type_enum.drop(op.get_bind(), checkfirst=True)
    classification_method_enum.drop(op.get_bind(), checkfirst=True)
    analysis_status_enum.drop(op.get_bind(), checkfirst=True)
    contract_type_enum.drop(op.get_bind(), checkfirst=True)
    severity_enum.drop(op.get_bind(), checkfirst=True)
    clause_category_enum.drop(op.get_bind(), checkfirst=True)
