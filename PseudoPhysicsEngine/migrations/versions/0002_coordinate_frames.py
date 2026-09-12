"""Add version-bound coordinate frame trees.

Revision ID: 0002_frames
Revises: 0001_initial
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_frames"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coordinate_frames",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("parent_frame_id", sa.String(length=36), nullable=True),
        sa.Column("length_unit", sa.String(length=10), nullable=False),
        sa.Column("axis_system", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id", "parent_frame_id"],
            ["coordinate_frames.revision_id", "coordinate_frames.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["revision_id"], ["project_revisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("revision_id", "id"),
        sa.UniqueConstraint("revision_id", "name"),
    )
    op.create_index(
        op.f("ix_coordinate_frames_revision_id"),
        "coordinate_frames",
        ["revision_id"],
        unique=False,
    )
    op.create_table(
        "frame_transforms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("parent_frame_id", sa.String(length=36), nullable=False),
        sa.Column("child_frame_id", sa.String(length=36), nullable=False),
        sa.Column("matrix", sa.JSON(), nullable=False),
        sa.Column("trust_status", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id", "child_frame_id"],
            ["coordinate_frames.revision_id", "coordinate_frames.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "parent_frame_id"],
            ["coordinate_frames.revision_id", "coordinate_frames.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["revision_id"], ["project_revisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("revision_id", "id"),
        sa.UniqueConstraint("revision_id", "child_frame_id"),
    )
    op.create_index(
        op.f("ix_frame_transforms_revision_id"),
        "frame_transforms",
        ["revision_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_frame_transforms_revision_id"), table_name="frame_transforms")
    op.drop_table("frame_transforms")
    op.drop_index(op.f("ix_coordinate_frames_revision_id"), table_name="coordinate_frames")
    op.drop_table("coordinate_frames")
