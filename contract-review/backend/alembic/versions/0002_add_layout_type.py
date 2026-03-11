"""Add layout_type, ocr_confidence, table_data to contract_chunks

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

layout_type_enum = postgresql.ENUM(
    "paragraph",
    "bullet_list",
    "numbered_list",
    "table",
    "heading",
    "ocr_text",
    name="layout_type_enum",
)


def upgrade() -> None:
    layout_type_enum.create(op.get_bind(), checkfirst=True)

    # layout_type: NOT NULL with default so existing rows get 'paragraph'
    op.add_column(
        "contract_chunks",
        sa.Column(
            "layout_type",
            layout_type_enum,
            nullable=False,
            server_default=sa.text("'paragraph'"),
        ),
    )
    # Remove server_default after backfill so future inserts must supply the value
    op.alter_column("contract_chunks", "layout_type", server_default=None)

    op.add_column(
        "contract_chunks",
        sa.Column("ocr_confidence", sa.Numeric(4, 3), nullable=True),
    )
    op.add_column(
        "contract_chunks",
        sa.Column("table_data", postgresql.JSONB, nullable=True),
    )

    op.create_check_constraint(
        "ocr_confidence_layout",
        "contract_chunks",
        "ocr_confidence IS NULL OR layout_type = 'ocr_text'",
    )
    op.create_check_constraint(
        "table_data_layout",
        "contract_chunks",
        "table_data IS NULL OR layout_type = 'table'",
    )
    op.create_check_constraint(
        "ocr_confidence_range",
        "contract_chunks",
        "ocr_confidence IS NULL OR ocr_confidence BETWEEN 0.0 AND 1.0",
    )

    op.create_index(
        "idx_chunks_layout_type",
        "contract_chunks",
        ["contract_id", "layout_type"],
    )
    op.create_index(
        "idx_chunks_low_ocr",
        "contract_chunks",
        ["contract_id", "ocr_confidence"],
        postgresql_where=sa.text(
            "layout_type = 'ocr_text' AND ocr_confidence IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("idx_chunks_low_ocr", table_name="contract_chunks")
    op.drop_index("idx_chunks_layout_type", table_name="contract_chunks")

    op.drop_constraint("ocr_confidence_range", "contract_chunks", type_="check")
    op.drop_constraint("table_data_layout",    "contract_chunks", type_="check")
    op.drop_constraint("ocr_confidence_layout","contract_chunks", type_="check")

    op.drop_column("contract_chunks", "table_data")
    op.drop_column("contract_chunks", "ocr_confidence")
    op.drop_column("contract_chunks", "layout_type")

    layout_type_enum.drop(op.get_bind(), checkfirst=True)
