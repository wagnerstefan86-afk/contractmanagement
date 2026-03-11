"""Stage 5: clause normalization, requirement embeddings, matching table

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-10

Changes:
  - clauses: add normalized_clause (TEXT), normalized_embedding (vector)
  - sub_requirements: add requirement_embedding (vector)
  - new enum: coverage_enum ('full', 'partial', 'none')
  - new table: clause_requirement_matches
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

coverage_enum = postgresql.ENUM("full", "partial", "none", name="coverage_enum")


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. clauses — normalized obligation text + embedding
    # ------------------------------------------------------------------
    op.add_column("clauses", sa.Column("normalized_clause",    sa.Text, nullable=True))
    op.execute("ALTER TABLE clauses ADD COLUMN normalized_embedding vector(1536)")
    op.execute(
        "CREATE INDEX idx_clauses_norm_embedding ON clauses "
        "USING ivfflat (normalized_embedding vector_cosine_ops) WITH (lists = 100)"
    )

    # ------------------------------------------------------------------
    # 2. sub_requirements — pre-computed requirement embedding
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE sub_requirements ADD COLUMN requirement_embedding vector(1536)")
    op.execute(
        "CREATE INDEX idx_sub_req_embedding ON sub_requirements "
        "USING ivfflat (requirement_embedding vector_cosine_ops) WITH (lists = 20)"
    )

    # ------------------------------------------------------------------
    # 3. coverage_enum + clause_requirement_matches
    # ------------------------------------------------------------------
    coverage_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "clause_requirement_matches",
        sa.Column("id",                   postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contract_id",          postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("contracts.id",        ondelete="CASCADE"),   nullable=False),
        sa.Column("clause_id",            postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("clauses.id",           ondelete="CASCADE"),   nullable=False),
        sa.Column("sub_requirement_id",   sa.Text,
                  sa.ForeignKey("sub_requirements.id",  ondelete="RESTRICT"),  nullable=False),
        sa.Column("framework_id",         sa.Text,
                  sa.ForeignKey("frameworks.id",        ondelete="RESTRICT"),  nullable=False),
        # Pass 1
        sa.Column("embedding_similarity", sa.Numeric(5, 4), nullable=False),
        # Pass 2 (NULL until LLM step)
        sa.Column("llm_validated",        sa.Boolean),
        sa.Column("llm_confidence",       sa.Numeric(4, 3)),
        sa.Column("coverage",             coverage_enum),
        sa.Column("explanation",          sa.Text),
        sa.Column("missing_elements",     postgresql.ARRAY(sa.Text),
                  nullable=False, server_default=sa.text("'{}'")),
        # Composite
        sa.Column("match_confidence",     sa.Numeric(4, 3)),
        sa.Column("is_best_match",        sa.Boolean, nullable=False,
                  server_default=sa.text("FALSE")),
        # Metadata
        sa.Column("llm_model_used",       sa.Text),
        sa.Column("llm_prompt_version",   sa.Text),
        sa.Column("created_at",           sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("NOW()")),
        # Constraints
        sa.CheckConstraint("embedding_similarity BETWEEN 0.0 AND 1.0", name="emb_sim_range"),
        sa.CheckConstraint(
            "llm_confidence IS NULL OR llm_confidence BETWEEN 0.0 AND 1.0",
            name="llm_conf_range",
        ),
        sa.CheckConstraint(
            "match_confidence IS NULL OR match_confidence BETWEEN 0.0 AND 1.0",
            name="match_conf_range",
        ),
    )

    op.create_index(
        "idx_crm_contract_subreq", "clause_requirement_matches",
        ["contract_id", "sub_requirement_id"],
    )
    op.create_index(
        "idx_crm_best_match", "clause_requirement_matches",
        ["contract_id", "sub_requirement_id", "is_best_match"],
        postgresql_where=sa.text("is_best_match = TRUE"),
    )
    op.create_index("idx_crm_clause", "clause_requirement_matches", ["clause_id"])
    op.create_index(
        "idx_crm_coverage", "clause_requirement_matches",
        ["contract_id", "coverage"],
        postgresql_where=sa.text("is_best_match = TRUE"),
    )
    op.create_index(
        "idx_crm_confidence", "clause_requirement_matches",
        ["match_confidence"],
        postgresql_where=sa.text("is_best_match = TRUE AND match_confidence IS NOT NULL"),
    )

    op.execute(
        "COMMENT ON TABLE clause_requirement_matches IS "
        "'Stage 5 intermediate: every evaluated (clause, sub_requirement) candidate pair "
        "with Pass 1 embedding similarity and Pass 2 LLM validation scores. "
        "is_best_match = TRUE rows are promoted to the findings table.'"
    )


def downgrade() -> None:
    op.drop_index("idx_crm_confidence",    table_name="clause_requirement_matches")
    op.drop_index("idx_crm_coverage",      table_name="clause_requirement_matches")
    op.drop_index("idx_crm_clause",        table_name="clause_requirement_matches")
    op.drop_index("idx_crm_best_match",    table_name="clause_requirement_matches")
    op.drop_index("idx_crm_contract_subreq", table_name="clause_requirement_matches")
    op.drop_table("clause_requirement_matches")
    coverage_enum.drop(op.get_bind(), checkfirst=True)

    op.execute("DROP INDEX IF EXISTS idx_sub_req_embedding")
    op.execute("ALTER TABLE sub_requirements DROP COLUMN IF EXISTS requirement_embedding")

    op.execute("DROP INDEX IF EXISTS idx_clauses_norm_embedding")
    op.execute("ALTER TABLE clauses DROP COLUMN IF EXISTS normalized_embedding")
    op.drop_column("clauses", "normalized_clause")
