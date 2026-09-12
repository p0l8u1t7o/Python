"""Add approved ChangeSet audit records.

Revision ID: 0003_changesets
Revises: 0002_frames
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_changesets"
down_revision: str | None = "0002_frames"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "change_sets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("base_revision_id", sa.String(length=36), nullable=False),
        sa.Column("result_revision_id", sa.String(length=36), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("user_instruction", sa.String(length=10000), nullable=False),
        sa.Column("interpreted_intent", sa.String(length=10000), nullable=False),
        sa.Column("operations", sa.JSON(), nullable=False),
        sa.Column("requires_tessellation", sa.Boolean(), nullable=False),
        sa.Column("requires_simulation", sa.Boolean(), nullable=False),
        sa.Column("requires_render", sa.Boolean(), nullable=False),
        sa.Column("approved_by", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["base_revision_id"], ["project_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["result_revision_id"], ["project_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("result_revision_id"),
    )
    op.create_index(
        op.f("ix_change_sets_base_revision_id"),
        "change_sets",
        ["base_revision_id"],
        unique=False,
    )
    op.create_index(op.f("ix_change_sets_project_id"), "change_sets", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_change_sets_project_id"), table_name="change_sets")
    op.drop_index(op.f("ix_change_sets_base_revision_id"), table_name="change_sets")
    op.drop_table("change_sets")
