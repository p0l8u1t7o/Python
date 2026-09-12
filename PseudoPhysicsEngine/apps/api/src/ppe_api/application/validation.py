from datetime import UTC, datetime
from uuid import UUID, uuid4

from ppe_domain import TrustStatus, calculate_critical_path
from ppe_schemas import (
    ArtifactFormat,
    MotionSpec,
    ProcessSpec,
    SceneAssemblySpec,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ppe_api.application.audit import record_audit_event
from ppe_api.application.revisions import RevisionNotFound
from ppe_api.db.models import (
    ArtifactRecord,
    CoordinateFrameRecord,
    FrameTransformRecord,
    MotionSpecRecord,
    ProcessSpecRecord,
    ProjectRevisionRecord,
    ReviewCommentRecord,
    SceneAssemblySpecRecord,
    ValidationReportRecord,
)

VALIDATOR_VERSION = "0.1.0"


class ValidationReportNotFound(LookupError):
    pass


def _issue(
    code: str,
    message: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
    blocks_release: bool = True,
    object_ids: list[UUID] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        blocks_release=blocks_release,
        object_ids=object_ids or [],
    )


def _validate_process(record: ProcessSpecRecord | None) -> list[ValidationIssue]:
    if record is None:
        return [_issue("PROCESS_SPEC_MISSING", "A ProcessSpec is required for release")]
    spec = ProcessSpec.model_validate(record.payload)
    graph = {
        step.id: (step.estimated_duration_seconds, step.predecessor_ids) for step in spec.steps
    }
    path = calculate_critical_path(graph)
    issues: list[ValidationIssue] = []
    if path.cycle_time_seconds > spec.target_cycle_time_seconds:
        issues.append(
            _issue(
                "CYCLE_TIME_EXCEEDED",
                f"Critical-path cycle time {path.cycle_time_seconds:g}s exceeds target "
                f"{spec.target_cycle_time_seconds:g}s",
                object_ids=list(path.step_ids),
            )
        )
    if spec.unresolved_questions:
        issues.append(
            _issue(
                "PROCESS_QUESTIONS_UNRESOLVED",
                f"{len(spec.unresolved_questions)} process question(s) remain unresolved",
            )
        )
    if spec.assumptions:
        issues.append(
            _issue(
                "PROCESS_ASSUMPTIONS_REMAIN",
                f"{len(spec.assumptions)} documented assumption(s) require review",
                severity=ValidationSeverity.WARNING,
                blocks_release=False,
            )
        )
    return issues


def _validate_motion(
    record: MotionSpecRecord | None, target: float | None
) -> list[ValidationIssue]:
    if record is None:
        return [_issue("MOTION_SPEC_MISSING", "A MotionSpec is required for release")]
    if target is None:
        return []
    spec = MotionSpec.model_validate(record.payload)
    duration = max(track.keyframes[-1].time_seconds for track in spec.tracks)
    if duration <= target:
        return []
    return [
        _issue(
            "MOTION_EXCEEDS_TARGET",
            f"Motion duration {duration:g}s exceeds target cycle time {target:g}s",
            object_ids=[
                track.id for track in spec.tracks if track.keyframes[-1].time_seconds > target
            ],
        )
    ]


def _validate_scene_motion(
    scene_record: SceneAssemblySpecRecord | None,
    motion_record: MotionSpecRecord | None,
) -> list[ValidationIssue]:
    if scene_record is None:
        return [_issue("SCENE_ASSEMBLY_MISSING", "A SceneAssemblySpec is required for release")]
    scene = SceneAssemblySpec.model_validate(scene_record.payload)
    if not scene.nodes:
        return [_issue("SCENE_ASSEMBLY_EMPTY", "The scene assembly must contain at least one node")]
    if motion_record is None:
        return []
    node_ids = {node.id for node in scene.nodes}
    motion = MotionSpec.model_validate(motion_record.payload)
    invalid_track_ids = [track.id for track in motion.tracks if track.scene_node_id not in node_ids]
    if not invalid_track_ids:
        return []
    return [
        _issue(
            "MOTION_SCENE_NODE_UNKNOWN",
            f"{len(invalid_track_ids)} motion track(s) reference unknown scene nodes",
            object_ids=invalid_track_ids,
        )
    ]


def run_validation(session: Session, revision_id: UUID) -> ValidationReport:
    revision = session.get(ProjectRevisionRecord, str(revision_id))
    if revision is None:
        raise RevisionNotFound(str(revision_id))

    process_record = session.scalar(
        select(ProcessSpecRecord).where(ProcessSpecRecord.revision_id == str(revision_id))
    )
    motion_record = session.scalar(
        select(MotionSpecRecord).where(MotionSpecRecord.revision_id == str(revision_id))
    )
    scene_record = session.scalar(
        select(SceneAssemblySpecRecord).where(
            SceneAssemblySpecRecord.revision_id == str(revision_id)
        )
    )
    artifacts = session.scalars(
        select(ArtifactRecord).where(ArtifactRecord.revision_id == str(revision_id))
    ).all()
    frames = session.scalars(
        select(CoordinateFrameRecord).where(CoordinateFrameRecord.revision_id == str(revision_id))
    ).all()
    transforms = session.scalars(
        select(FrameTransformRecord).where(FrameTransformRecord.revision_id == str(revision_id))
    ).all()
    open_comments = session.scalars(
        select(ReviewCommentRecord).where(
            ReviewCommentRecord.revision_id == str(revision_id),
            ReviewCommentRecord.resolved_at.is_(None),
        )
    ).all()

    issues = _validate_process(process_record)
    target = (
        ProcessSpec.model_validate(process_record.payload).target_cycle_time_seconds
        if process_record
        else None
    )
    issues.extend(_validate_motion(motion_record, target))
    issues.extend(_validate_scene_motion(scene_record, motion_record))
    if not any(artifact.format == ArtifactFormat.STEP for artifact in artifacts):
        issues.append(
            _issue("STEP_ARTIFACT_MISSING", "A source STEP artifact is required for release")
        )
    if not frames:
        issues.append(_issue("COORDINATE_FRAME_MISSING", "A coordinate-frame tree is required"))
    inferred_ids = [
        UUID(transform.id)
        for transform in transforms
        if transform.trust_status == TrustStatus.INFERRED
    ]
    if inferred_ids:
        issues.append(
            _issue(
                "INFERRED_COORDINATE",
                f"{len(inferred_ids)} coordinate transform(s) are still inferred",
                object_ids=inferred_ids,
            )
        )
    if open_comments:
        issues.append(
            _issue(
                "REVIEW_COMMENTS_OPEN",
                f"{len(open_comments)} review comment(s) remain unresolved",
                object_ids=[UUID(comment.id) for comment in open_comments],
            )
        )

    report = ValidationReport(
        id=uuid4(),
        project_id=UUID(revision.project_id),
        revision_id=revision_id,
        status=(
            ValidationStatus.FAILED
            if any(issue.blocks_release for issue in issues)
            else ValidationStatus.PASSED
        ),
        validator_version=VALIDATOR_VERSION,
        issues=issues,
    )
    with session.begin_nested():
        session.add(
            ValidationReportRecord(
                id=str(report.id),
                project_id=revision.project_id,
                revision_id=str(revision_id),
                status=report.status,
                validator_version=report.validator_version,
                payload=report.model_dump(mode="json"),
                created_at=datetime.now(UTC),
            )
        )
        record_audit_event(
            session,
            project_id=revision.project_id,
            revision_id=revision_id,
            event_type="VALIDATION_COMPLETED",
            entity_type="ValidationReport",
            entity_id=report.id,
            details={
                "status": report.status.value,
                "issue_count": len(report.issues),
                "validator_version": report.validator_version,
            },
        )
    session.commit()
    return report


def get_latest_validation(session: Session, revision_id: UUID) -> ValidationReport:
    if session.get(ProjectRevisionRecord, str(revision_id)) is None:
        raise RevisionNotFound(str(revision_id))
    record = session.scalar(
        select(ValidationReportRecord)
        .where(ValidationReportRecord.revision_id == str(revision_id))
        .order_by(ValidationReportRecord.created_at.desc(), ValidationReportRecord.id.desc())
        .limit(1)
    )
    if record is None:
        raise ValidationReportNotFound(str(revision_id))
    return ValidationReport.model_validate(record.payload)
