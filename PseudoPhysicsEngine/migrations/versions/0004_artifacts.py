"""Add content-addressed artifact metadata.

Revision ID: 0004_artifacts
Revises: 0003_changesets
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_artifacts"
down_revision: str | None = "0003_changesets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=30), nullable=False),
        sa.Column("mime_type", sa.String(length=200), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_uri", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_id"], ["project_revisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_artifacts_project_id"), "artifacts", ["project_id"], unique=False)
    op.create_index(op.f("ix_artifacts_revision_id"), "artifacts", ["revision_id"], unique=False)
    op.create_index(op.f("ix_artifacts_sha256"), "artifacts", ["sha256"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_artifacts_sha256"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_revision_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_project_id"), table_name="artifacts")
    op.drop_table("artifacts")
