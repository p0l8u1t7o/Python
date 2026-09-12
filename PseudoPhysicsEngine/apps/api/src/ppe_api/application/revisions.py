from copy import deepcopy
from typing import cast
from uuid import UUID

from ppe_domain import RevisionStatus
from ppe_schemas import (
    ProjectRevision,
    RevisionChangeKind,
    RevisionDiff,
    RevisionDiffEntry,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ppe_api.application.projects import ProjectNotFound
from ppe_api.db.models import (
    ArtifactRecord,
    CoordinateFrameRecord,
    FrameTransformRecord,
    MotionSpecRecord,
    ProcessSpecRecord,
    ProjectRecord,
    ProjectRevisionRecord,
    SceneAssemblySpecRecord,
)


class RevisionNotFound(LookupError):
    pass


class RevisionImmutable(ValueError):
    pass


class RevisionComparisonConflict(ValueError):
    pass


def _to_schema(record: ProjectRevisionRecord) -> ProjectRevision:
    from ppe_api.application.projects import _as_utc

    return ProjectRevision(
        id=UUID(record.id),
        project_id=UUID(record.project_id),
        sequence=record.sequence,
        status=RevisionStatus(record.status),
        parent_revision_id=UUID(record.parent_revision_id) if record.parent_revision_id else None,
        created_at=_as_utc(record.created_at),
    )


def list_project_revisions(session: Session, project_id: UUID) -> list[ProjectRevision]:
    if session.get(ProjectRecord, str(project_id)) is None:
        raise ProjectNotFound(str(project_id))
    records = session.scalars(
        select(ProjectRevisionRecord)
        .where(ProjectRevisionRecord.project_id == str(project_id))
        .order_by(ProjectRevisionRecord.sequence.desc())
    ).all()
    return [_to_schema(record) for record in records]


def _frame_state(session: Session, revision_id: UUID) -> dict[str, dict[str, object]]:
    frames = session.scalars(
        select(CoordinateFrameRecord).where(CoordinateFrameRecord.revision_id == str(revision_id))
    ).all()
    transforms = session.scalars(
        select(FrameTransformRecord).where(FrameTransformRecord.revision_id == str(revision_id))
    ).all()
    by_child = {transform.child_frame_id: transform for transform in transforms}
    state: dict[str, dict[str, object]] = {}
    for frame in frames:
        value: dict[str, object] = {
            "id": frame.id,
            "name": frame.name,
            "parent_frame_id": frame.parent_frame_id,
            "length_unit": frame.length_unit,
            "axis_system": frame.axis_system,
        }
        transform = by_child.get(frame.id)
        if transform is not None:
            value["transform_from_parent"] = {
                "id": transform.id,
                "matrix": transform.matrix,
                "trust_status": transform.trust_status,
                "source": transform.source,
            }
        state[frame.id] = value
    return state


def _artifact_state(session: Session, revision_id: UUID) -> dict[str, dict[str, object]]:
    records = session.scalars(
        select(ArtifactRecord).where(ArtifactRecord.revision_id == str(revision_id))
    ).all()
    return {
        record.sha256: {
            "sha256": record.sha256,
            "original_filename": record.original_filename,
            "format": record.format,
            "mime_type": record.mime_type,
            "size_bytes": record.size_bytes,
            "source": record.source,
        }
        for record in records
    }


def _singleton_state(
    session: Session,
    revision_id: UUID,
    key: str,
    record_type: type[ProcessSpecRecord] | type[MotionSpecRecord] | type[SceneAssemblySpecRecord],
) -> dict[str, dict[str, object]]:
    record = cast(
        ProcessSpecRecord | MotionSpecRecord | SceneAssemblySpecRecord | None,
        session.scalar(select(record_type).where(record_type.revision_id == str(revision_id))),
    )
    if record is None:
        return {}
    payload = deepcopy(record.payload)
    payload.pop("id", None)
    payload.pop("revision_id", None)
    return {key: payload}


def _diff_state(
    object_type: str,
    before: dict[str, dict[str, object]],
    after: dict[str, dict[str, object]],
) -> list[RevisionDiffEntry]:
    entries: list[RevisionDiffEntry] = []
    for key in sorted(before.keys() | after.keys()):
        old = before.get(key)
        new = after.get(key)
        if old == new:
            continue
        kind = (
            RevisionChangeKind.ADDED
            if old is None
            else RevisionChangeKind.REMOVED
            if new is None
            else RevisionChangeKind.MODIFIED
        )
        entries.append(
            RevisionDiffEntry(
                object_type=object_type,
                object_key=key,
                change_kind=kind,
                before=old,
                after=new,
            )
        )
    return entries


def compare_revisions(
    session: Session, project_id: UUID, from_revision_id: UUID, to_revision_id: UUID
) -> RevisionDiff:
    if session.get(ProjectRecord, str(project_id)) is None:
        raise ProjectNotFound(str(project_id))
    revisions = [
        session.get(ProjectRevisionRecord, str(from_revision_id)),
        session.get(ProjectRevisionRecord, str(to_revision_id)),
    ]
    if any(revision is None for revision in revisions):
        missing = from_revision_id if revisions[0] is None else to_revision_id
        raise RevisionNotFound(str(missing))
    if any(
        revision is not None and revision.project_id != str(project_id) for revision in revisions
    ):
        raise RevisionComparisonConflict("Both revisions must belong to the route project")

    entries = _diff_state(
        "CoordinateFrame",
        _frame_state(session, from_revision_id),
        _frame_state(session, to_revision_id),
    )
    entries.extend(
        _diff_state(
            "Artifact",
            _artifact_state(session, from_revision_id),
            _artifact_state(session, to_revision_id),
        )
    )
    for label, record_type in (
        ("ProcessSpec", ProcessSpecRecord),
        ("MotionSpec", MotionSpecRecord),
        ("SceneAssemblySpec", SceneAssemblySpecRecord),
    ):
        entries.extend(
            _diff_state(
                label,
                _singleton_state(session, from_revision_id, label, record_type),
                _singleton_state(session, to_revision_id, label, record_type),
            )
        )
    return RevisionDiff(
        project_id=project_id,
        from_revision_id=from_revision_id,
        to_revision_id=to_revision_id,
        entries=entries,
    )


def ensure_revision_editable(session: Session, revision_id: UUID) -> ProjectRevisionRecord:
    revision = session.get(ProjectRevisionRecord, str(revision_id))
    if revision is None:
        raise RevisionNotFound(str(revision_id))
    if revision.status != RevisionStatus.DRAFT:
        raise RevisionImmutable(f"Revision {revision_id} is {revision.status}")
    child_revision_id = session.scalar(
        select(ProjectRevisionRecord.id)
        .where(ProjectRevisionRecord.parent_revision_id == str(revision_id))
        .limit(1)
    )
    if child_revision_id is not None:
        raise RevisionImmutable(f"Revision {revision_id} has a successor")
    return revision
