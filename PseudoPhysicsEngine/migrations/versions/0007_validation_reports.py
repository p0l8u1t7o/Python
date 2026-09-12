"""Persist validation reports.

Revision ID: 0007_validation_reports
Revises: 0006_engineering_specs
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_validation_reports"
down_revision: str | None = "0006_engineering_specs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "validation_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("validator_version", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_id"], ["project_revisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_validation_reports_project_id"),
        "validation_reports",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_validation_reports_revision_id"),
        "validation_reports",
        ["revision_id"],
        unique=False,
    )
    op.create_index(
        "ix_validation_reports_revision_created",
        "validation_reports",
        ["revision_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_validation_reports_revision_created", table_name="validation_reports")
    op.drop_index(op.f("ix_validation_reports_revision_id"), table_name="validation_reports")
    op.drop_index(op.f("ix_validation_reports_project_id"), table_name="validation_reports")
    op.drop_table("validation_reports")
