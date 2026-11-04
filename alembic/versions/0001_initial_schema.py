"""Initial schema: cases, submissions, outcomes, exhibits

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-11-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("case_id", sa.String(length=80), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("notice_json", sa.Text(), nullable=False),
        sa.Column("folio_json", sa.Text(), nullable=False),
        sa.Column("evidence_items_json", sa.Text(), nullable=True),
        sa.Column("draft_text", sa.Text(), nullable=True),
        sa.Column("policy_text", sa.Text(), nullable=True),
        sa.Column("custom_notes", sa.Text(), nullable=True),
        sa.Column("approval_json", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(length=128), nullable=True),
        sa.Column("audit_session_id", sa.String(length=80), nullable=True),
        sa.Column("audit_head_hash", sa.String(length=80), nullable=True),
        sa.Column("audit_event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("case_id"),
    )
    op.create_index("ix_cases_tenant_id", "cases", ["tenant_id"], unique=False)

    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(length=80), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=True),
        sa.Column("portal_id", sa.String(length=80), nullable=False),
        sa.Column("portal_name", sa.String(length=120), nullable=True),
        sa.Column("submitted_by", sa.String(length=120), nullable=True),
        sa.Column("submitted_at", sa.String(length=40), nullable=True),
        sa.Column("confirmation_reference", sa.String(length=120), nullable=True),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=True),
        sa.Column("packet_sha256", sa.String(length=64), nullable=True),
        sa.Column("approval_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="prepared"),
        sa.Column("expected_decision_by", sa.String(length=40), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_submissions_case_id", "submissions", ["case_id"], unique=False)
    op.create_index("ix_submissions_tenant_id", "submissions", ["tenant_id"], unique=False)

    op.create_table(
        "outcomes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(length=80), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=True),
        sa.Column("decision", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("decided_at", sa.String(length=40), nullable=True),
        sa.Column("amount_recovered", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("next_stage", sa.String(length=40), nullable=True),
        sa.Column("next_deadline", sa.String(length=40), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outcomes_case_id", "outcomes", ["case_id"], unique=False)
    op.create_index("ix_outcomes_tenant_id", "outcomes", ["tenant_id"], unique=False)

    op.create_table(
        "exhibits",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_backend", sa.String(length=40), nullable=False, server_default="local"),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("sha256"),
    )
    op.create_index("ix_exhibits_tenant_id", "exhibits", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_table("exhibits")
    op.drop_table("outcomes")
    op.drop_table("submissions")
    op.drop_table("cases")
