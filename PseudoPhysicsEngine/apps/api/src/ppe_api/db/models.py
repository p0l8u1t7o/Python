from datetime import datetime
from uuid import uuid4

from ppe_domain import RevisionStatus, TrustStatus
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ProjectRecord(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    revisions: Mapped[list["ProjectRevisionRecord"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectRevisionRecord(Base):
    __tablename__ = "project_revisions"
    __table_args__ = (UniqueConstraint("project_id", "sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=RevisionStatus.DRAFT, nullable=False)
    parent_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    project: Mapped[ProjectRecord] = relationship(back_populates="revisions")


class CoordinateFrameRecord(Base):
    __tablename__ = "coordinate_frames"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "parent_frame_id"],
            ["coordinate_frames.revision_id", "coordinate_frames.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("revision_id", "name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_frame_id: Mapped[str | None] = mapped_column(String(36))
    length_unit: Mapped[str] = mapped_column(String(10), nullable=False, default="mm")
    axis_system: Mapped[str] = mapped_column(
        String(40), nullable=False, default="RIGHT_HANDED_Z_UP"
    )


class FrameTransformRecord(Base):
    __tablename__ = "frame_transforms"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "parent_frame_id"],
            ["coordinate_frames.revision_id", "coordinate_frames.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["revision_id", "child_frame_id"],
            ["coordinate_frames.revision_id", "coordinate_frames.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("revision_id", "child_frame_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    parent_frame_id: Mapped[str] = mapped_column(String(36), nullable=False)
    child_frame_id: Mapped[str] = mapped_column(String(36), nullable=False)
    matrix: Mapped[list[list[float]]] = mapped_column(JSON, nullable=False)
    trust_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=TrustStatus.INFERRED
    )
    source: Mapped[str] = mapped_column(String(500), nullable=False)


class ChangeSetRecord(Base):
    __tablename__ = "change_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    base_revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    result_revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    user_instruction: Mapped[str] = mapped_column(String(10_000), nullable=False)
    interpreted_intent: Mapped[str] = mapped_column(String(10_000), nullable=False)
    operations: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    requires_tessellation: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_simulation: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_render: Mapped[bool] = mapped_column(Boolean, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(30), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_uri: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobRecord(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key"),
        Index("ix_jobs_claim", "status", "kind", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_artifact_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    result_artifact_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(100), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(200))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(String(4000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessSpecRecord(Base):
    __tablename__ = "process_specs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MotionSpecRecord(Base):
    __tablename__ = "motion_specs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ValidationReportRecord(Base):
    __tablename__ = "validation_reports"
    __table_args__ = (Index("ix_validation_reports_revision_created", "revision_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    validator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReleaseManifestRecord(Base):
    __tablename__ = "release_manifests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    validation_report_id: Mapped[str] = mapped_column(
        ForeignKey("validation_reports.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[str] = mapped_column(String(36), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SceneAssemblySpecRecord(Base):
    __tablename__ = "scene_assembly_specs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewCommentRecord(Base):
    __tablename__ = "review_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    author_id: Mapped[str] = mapped_column(String(36), nullable=False)
    body: Mapped[str] = mapped_column(String(4000), nullable=False)
    object_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    parent_comment_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_comments.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(36))


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_project_created", "project_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="RESTRICT"), index=True
    )
    actor_id: Mapped[str | None] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36))
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
