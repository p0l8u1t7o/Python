"""Persist versioned process and motion specifications.

Revision ID: 0006_engineering_specs
Revises: 0005_jobs
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_engineering_specs"
down_revision: str | None = "0005_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_spec_table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_id"], ["project_revisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revision_id"),
    )
    op.create_index(op.f(f"ix_{name}_project_id"), name, ["project_id"], unique=False)


def upgrade() -> None:
    _create_spec_table("process_specs")
    _create_spec_table("motion_specs")


def downgrade() -> None:
    op.drop_index(op.f("ix_motion_specs_project_id"), table_name="motion_specs")
    op.drop_table("motion_specs")
    op.drop_index(op.f("ix_process_specs_project_id"), table_name="process_specs")
    op.drop_table("process_specs")
