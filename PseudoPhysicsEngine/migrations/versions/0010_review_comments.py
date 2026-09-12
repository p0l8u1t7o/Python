"""Add revision review comments.

Revision ID: 0010_review_comments
Revises: 0009_scene_assembly_specs
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_review_comments"
down_revision: str | None = "0009_scene_assembly_specs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_comments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=False),
        sa.Column("object_ids", sa.JSON(), nullable=False),
        sa.Column("parent_comment_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["parent_comment_id"], ["review_comments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_id"], ["project_revisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_review_comments_project_id"), "review_comments", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_review_comments_revision_id"), "review_comments", ["revision_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_review_comments_revision_id"), table_name="review_comments")
    op.drop_index(op.f("ix_review_comments_project_id"), table_name="review_comments")
    op.drop_table("review_comments")
