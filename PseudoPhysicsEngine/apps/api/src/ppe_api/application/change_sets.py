import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from ppe_coordinates import matrix4
from ppe_domain import FrameTreeError, RevisionStatus, TrustStatus, validate_frame_tree
from ppe_schemas import (
    ChangeSet,
    ChangeSetApplyResult,
    ChangeSetIssue,
    ChangeSetPreview,
    CoordinateFrameChange,
    FrameTransformChange,
    ProjectRevision,
)
from ppe_schemas.v1.change_set import OperationType
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ppe_api.application.audit import record_audit_event
from ppe_api.application.frames import get_frame_tree
from ppe_api.application.revisions import RevisionNotFound
from ppe_api.db.models import (
    ArtifactRecord,
    ChangeSetRecord,
    CoordinateFrameRecord,
    FrameTransformRecord,
    MotionSpecRecord,
    ProcessSpecRecord,
    ProjectRevisionRecord,
    SceneAssemblySpecRecord,
)


class ChangeSetConflict(ValueError):
    pass


class ChangeSetRejected(ValueError):
    def __init__(self, issues: list[ChangeSetIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{issue.code}: {issue.message}" for issue in issues))


FrameSnapshot = dict[UUID, CoordinateFrameChange]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_revision(record: ProjectRevisionRecord) -> ProjectRevision:
    return ProjectRevision(
        id=UUID(record.id),
        project_id=UUID(record.project_id),
        sequence=record.sequence,
        status=RevisionStatus(record.status),
        parent_revision_id=UUID(record.parent_revision_id) if record.parent_revision_id else None,
        created_at=_as_utc(record.created_at),
    )


def _load_snapshot(session: Session, revision_id: UUID) -> FrameSnapshot:
    frame_records = session.scalars(
        select(CoordinateFrameRecord).where(CoordinateFrameRecord.revision_id == str(revision_id))
    ).all()
    transform_records = session.scalars(
        select(FrameTransformRecord).where(FrameTransformRecord.revision_id == str(revision_id))
    ).all()
    transform_by_child = {record.child_frame_id: record for record in transform_records}

    snapshot: FrameSnapshot = {}
    for frame in frame_records:
        transform_record = transform_by_child.get(frame.id)
        transform = None
        if transform_record is not None:
            transform = FrameTransformChange(
                id=UUID(transform_record.id),
                matrix=matrix4(transform_record.matrix),
                trust_status=TrustStatus(transform_record.trust_status),
                source=transform_record.source,
            )
        snapshot[UUID(frame.id)] = CoordinateFrameChange(
            name=frame.name,
            parent_frame_id=UUID(frame.parent_frame_id) if frame.parent_frame_id else None,
            transform_from_parent=transform,
        )
    return snapshot


def _parse_payload(
    payload: dict[str, object] | None,
    *,
    operation_index: int,
    field_name: str,
    issues: list[ChangeSetIssue],
) -> CoordinateFrameChange | None:
    if payload is None:
        return None
    try:
        return CoordinateFrameChange.model_validate(payload)
    except ValidationError as error:
        issues.append(
            ChangeSetIssue(
                code="INVALID_COORDINATE_FRAME_PAYLOAD",
                message=f"{field_name} payload is invalid: {error.errors(include_url=False)}",
                operation_index=operation_index,
            )
        )
        return None


def _evaluate_operations(
    original: FrameSnapshot, change_set: ChangeSet
) -> tuple[FrameSnapshot, list[ChangeSetIssue]]:
    snapshot = dict(original)
    issues: list[ChangeSetIssue] = []

    for index, operation in enumerate(change_set.operations):
        if operation.object_type != "CoordinateFrame":
            issues.append(
                ChangeSetIssue(
                    code="UNSUPPORTED_OBJECT_TYPE",
                    message=f"Object type {operation.object_type!r} is not supported yet",
                    operation_index=index,
                )
            )
            continue

        before = _parse_payload(
            operation.before,
            operation_index=index,
            field_name="before",
            issues=issues,
        )
        after = _parse_payload(
            operation.after,
            operation_index=index,
            field_name="after",
            issues=issues,
        )
        current = snapshot.get(operation.object_id)

        if operation.operation == OperationType.ADD:
            if current is not None:
                issues.append(
                    ChangeSetIssue(
                        code="OBJECT_ALREADY_EXISTS",
                        message=f"CoordinateFrame {operation.object_id} already exists",
                        operation_index=index,
                    )
                )
            elif after is not None:
                snapshot[operation.object_id] = after
        elif operation.operation == OperationType.UPDATE:
            if current is None:
                issues.append(
                    ChangeSetIssue(
                        code="OBJECT_NOT_FOUND",
                        message=f"CoordinateFrame {operation.object_id} does not exist",
                        operation_index=index,
                    )
                )
            elif before is not None and current != before:
                issues.append(
                    ChangeSetIssue(
                        code="STALE_BEFORE_STATE",
                        message=f"CoordinateFrame {operation.object_id} no longer matches before",
                        operation_index=index,
                    )
                )
            elif after is not None:
                snapshot[operation.object_id] = after
        elif operation.operation == OperationType.REMOVE:
            if current is None:
                issues.append(
                    ChangeSetIssue(
                        code="OBJECT_NOT_FOUND",
                        message=f"CoordinateFrame {operation.object_id} does not exist",
                        operation_index=index,
                    )
                )
            elif before is not None and current != before:
                issues.append(
                    ChangeSetIssue(
                        code="STALE_BEFORE_STATE",
                        message=f"CoordinateFrame {operation.object_id} no longer matches before",
                        operation_index=index,
                    )
                )
            else:
                snapshot.pop(operation.object_id)

    names: dict[str, UUID] = {}
    transform_ids: dict[UUID, UUID] = {}
    for frame_id, frame in snapshot.items():
        duplicate_name = names.get(frame.name)
        if duplicate_name is not None:
            issues.append(
                ChangeSetIssue(
                    code="DUPLICATE_FRAME_NAME",
                    message=f"Frames {duplicate_name} and {frame_id} both use name {frame.name!r}",
                )
            )
        names[frame.name] = frame_id

        transform = frame.transform_from_parent
        if transform is not None:
            duplicate_transform = transform_ids.get(transform.id)
            if duplicate_transform is not None:
                issues.append(
                    ChangeSetIssue(
                        code="DUPLICATE_TRANSFORM_ID",
                        message=(
                            f"Frames {duplicate_transform} and {frame_id} both use transform "
                            f"{transform.id}"
                        ),
                    )
                )
            transform_ids[transform.id] = frame_id

    try:
        validate_frame_tree(
            {frame_id: frame.parent_frame_id for frame_id, frame in snapshot.items()}
        )
    except FrameTreeError as error:
        issues.append(ChangeSetIssue(code="INVALID_FRAME_TREE", message=str(error)))

    return snapshot, issues


def _evaluate_change_set(
    session: Session, route_revision_id: UUID, change_set: ChangeSet
) -> tuple[ChangeSetPreview, FrameSnapshot, ProjectRevisionRecord]:
    if change_set.base_revision_id != route_revision_id:
        raise ChangeSetConflict("ChangeSet base revision does not match the route revision")

    revision = session.get(ProjectRevisionRecord, str(route_revision_id))
    if revision is None:
        raise RevisionNotFound(str(route_revision_id))
    if revision.project_id != str(change_set.project_id):
        raise ChangeSetConflict("ChangeSet project does not own the base revision")

    latest_revision = session.scalar(
        select(ProjectRevisionRecord)
        .where(ProjectRevisionRecord.project_id == revision.project_id)
        .order_by(ProjectRevisionRecord.sequence.desc())
        .limit(1)
    )
    issues: list[ChangeSetIssue] = []
    if latest_revision is None or latest_revision.id != revision.id:
        issues.append(
            ChangeSetIssue(
                code="BASE_REVISION_NOT_CURRENT",
                message="ChangeSet must target the current project revision",
            )
        )

    snapshot, operation_issues = _evaluate_operations(
        _load_snapshot(session, route_revision_id), change_set
    )
    issues.extend(operation_issues)
    affected_ids = sorted({operation.object_id for operation in change_set.operations}, key=str)
    return (
        ChangeSetPreview(
            change_set_id=change_set.id,
            base_revision_id=change_set.base_revision_id,
            valid=not issues,
            affected_object_ids=affected_ids,
            issues=issues,
        ),
        snapshot,
        revision,
    )


def preview_change_set(
    session: Session, revision_id: UUID, change_set: ChangeSet
) -> ChangeSetPreview:
    preview, _, _ = _evaluate_change_set(session, revision_id, change_set)
    return preview


def _insert_snapshot(session: Session, revision_id: UUID, snapshot: FrameSnapshot) -> None:
    pending = dict(snapshot)
    inserted: set[UUID] = set()
    while pending:
        ready = sorted(
            (
                (frame_id, frame)
                for frame_id, frame in pending.items()
                if frame.parent_frame_id is None or frame.parent_frame_id in inserted
            ),
            key=lambda item: (item[1].name, str(item[0])),
        )
        if not ready:
            raise RuntimeError("Validated frame snapshot could not be ordered")
        for frame_id, frame in ready:
            session.add(
                CoordinateFrameRecord(
                    id=str(frame_id),
                    revision_id=str(revision_id),
                    name=frame.name,
                    parent_frame_id=str(frame.parent_frame_id) if frame.parent_frame_id else None,
                    length_unit="mm",
                    axis_system="RIGHT_HANDED_Z_UP",
                )
            )
            session.flush()
            inserted.add(frame_id)
            pending.pop(frame_id)

    for frame_id, frame in snapshot.items():
        transform = frame.transform_from_parent
        if transform is None or frame.parent_frame_id is None:
            continue
        session.add(
            FrameTransformRecord(
                id=str(transform.id),
                revision_id=str(revision_id),
                parent_frame_id=str(frame.parent_frame_id),
                child_frame_id=str(frame_id),
                matrix=[list(row) for row in transform.matrix],
                trust_status=transform.trust_status,
                source=transform.source,
            )
        )


def _versioned_payload(
    payload: dict[str, object], *, new_id: UUID, revision_id: UUID
) -> dict[str, object]:
    copied = deepcopy(payload)
    copied["id"] = str(new_id)
    copied["revision_id"] = str(revision_id)
    return copied


def _copy_revision_resources(
    session: Session,
    *,
    source_revision_id: UUID,
    target_revision_id: UUID,
    project_id: str,
    now: datetime,
) -> None:
    artifacts = session.scalars(
        select(ArtifactRecord).where(ArtifactRecord.revision_id == str(source_revision_id))
    ).all()
    artifact_id_map: dict[str, str] = {}
    for artifact in artifacts:
        copied_artifact_id = str(uuid4())
        artifact_id_map[artifact.id] = copied_artifact_id
        session.add(
            ArtifactRecord(
                id=copied_artifact_id,
                project_id=project_id,
                revision_id=str(target_revision_id),
                original_filename=artifact.original_filename,
                format=artifact.format,
                mime_type=artifact.mime_type,
                size_bytes=artifact.size_bytes,
                sha256=artifact.sha256,
                storage_uri=artifact.storage_uri,
                source=artifact.source,
                created_at=now,
            )
        )

    process = session.scalar(
        select(ProcessSpecRecord).where(ProcessSpecRecord.revision_id == str(source_revision_id))
    )
    if process is not None:
        copied_process_id = uuid4()
        session.add(
            ProcessSpecRecord(
                id=str(copied_process_id),
                project_id=project_id,
                revision_id=str(target_revision_id),
                schema_version=process.schema_version,
                payload=_versioned_payload(
                    process.payload,
                    new_id=copied_process_id,
                    revision_id=target_revision_id,
                ),
                created_at=now,
                updated_at=now,
            )
        )

    motion = session.scalar(
        select(MotionSpecRecord).where(MotionSpecRecord.revision_id == str(source_revision_id))
    )
    if motion is not None:
        copied_motion_id = uuid4()
        session.add(
            MotionSpecRecord(
                id=str(copied_motion_id),
                project_id=project_id,
                revision_id=str(target_revision_id),
                schema_version=motion.schema_version,
                payload=_versioned_payload(
                    motion.payload,
                    new_id=copied_motion_id,
                    revision_id=target_revision_id,
                ),
                created_at=now,
                updated_at=now,
            )
        )

    scene = session.scalar(
        select(SceneAssemblySpecRecord).where(
            SceneAssemblySpecRecord.revision_id == str(source_revision_id)
        )
    )
    if scene is not None:
        copied_scene_id = uuid4()
        payload = _versioned_payload(
            scene.payload, new_id=copied_scene_id, revision_id=target_revision_id
        )
        nodes = cast(list[dict[str, object]], payload.get("nodes", []))
        for node in nodes:
            original_artifact_id = str(node["asset_version_id"])
            if original_artifact_id in artifact_id_map:
                node["asset_version_id"] = artifact_id_map[original_artifact_id]
        session.add(
            SceneAssemblySpecRecord(
                id=str(copied_scene_id),
                project_id=project_id,
                revision_id=str(target_revision_id),
                schema_version=scene.schema_version,
                payload=payload,
                created_at=now,
                updated_at=now,
            )
        )


def _payload_hash(change_set: ChangeSet) -> str:
    payload = json.dumps(
        change_set.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def apply_change_set(
    session: Session, revision_id: UUID, change_set: ChangeSet
) -> ChangeSetApplyResult:
    if change_set.base_revision_id != revision_id:
        raise ChangeSetConflict("ChangeSet base revision does not match the route revision")
    if change_set.approved_by is None:
        raise ChangeSetRejected(
            [ChangeSetIssue(code="APPROVAL_REQUIRED", message="approved_by is required to apply")]
        )

    payload_sha256 = _payload_hash(change_set)
    result_revision_id: UUID
    with session.begin():
        existing = session.get(ChangeSetRecord, str(change_set.id))
        if existing is not None:
            if existing.payload_sha256 != payload_sha256:
                raise ChangeSetConflict("ChangeSet id was already used with a different payload")
            result_revision_id = UUID(existing.result_revision_id)
        else:
            preview, snapshot, base_revision = _evaluate_change_set(
                session, revision_id, change_set
            )
            if not preview.valid:
                raise ChangeSetRejected(preview.issues)

            now = datetime.now(UTC)
            result_revision_id = uuid4()
            result_revision = ProjectRevisionRecord(
                id=str(result_revision_id),
                project_id=base_revision.project_id,
                sequence=base_revision.sequence + 1,
                status=RevisionStatus.DRAFT,
                parent_revision_id=base_revision.id,
                created_at=now,
            )
            session.add(result_revision)
            session.flush()
            _insert_snapshot(session, result_revision_id, snapshot)
            _copy_revision_resources(
                session,
                source_revision_id=revision_id,
                target_revision_id=result_revision_id,
                project_id=base_revision.project_id,
                now=now,
            )
            session.add(
                ChangeSetRecord(
                    id=str(change_set.id),
                    project_id=str(change_set.project_id),
                    base_revision_id=str(change_set.base_revision_id),
                    result_revision_id=str(result_revision_id),
                    payload_sha256=payload_sha256,
                    reason=change_set.reason,
                    user_instruction=change_set.user_instruction,
                    interpreted_intent=change_set.interpreted_intent,
                    operations=cast(
                        list[dict[str, object]],
                        change_set.model_dump(mode="json")["operations"],
                    ),
                    requires_tessellation=change_set.requires_tessellation,
                    requires_simulation=change_set.requires_simulation,
                    requires_render=change_set.requires_render,
                    approved_by=str(change_set.approved_by),
                    status="APPLIED",
                    created_at=now,
                    applied_at=now,
                )
            )
            record_audit_event(
                session,
                project_id=base_revision.project_id,
                revision_id=result_revision_id,
                actor_id=change_set.approved_by,
                event_type="CHANGE_SET_APPLIED",
                entity_type="ChangeSet",
                entity_id=change_set.id,
                details={
                    "base_revision_id": str(revision_id),
                    "operation_count": len(change_set.operations),
                },
            )

    persisted_revision = session.get(ProjectRevisionRecord, str(result_revision_id))
    if persisted_revision is None:
        raise RuntimeError("Applied ChangeSet result revision is missing")
    return ChangeSetApplyResult(
        change_set_id=change_set.id,
        revision=_to_revision(persisted_revision),
        frame_tree=get_frame_tree(session, result_revision_id),
    )
