from datetime import UTC, datetime
from uuid import UUID

from ppe_domain import calculate_critical_path
from ppe_schemas import MotionSpec, ProcessAnalysis, ProcessSpec, SceneAssemblySpec
from sqlalchemy import select
from sqlalchemy.orm import Session

from ppe_api.application.audit import record_audit_event
from ppe_api.application.revisions import ensure_revision_editable
from ppe_api.db.models import (
    ArtifactRecord,
    CoordinateFrameRecord,
    MotionSpecRecord,
    ProcessSpecRecord,
    ProjectRevisionRecord,
    SceneAssemblySpecRecord,
)


class EngineeringSpecNotFound(LookupError):
    pass


class EngineeringSpecConflict(ValueError):
    pass


def _validate_owner(
    revision: ProjectRevisionRecord,
    *,
    route_revision_id: UUID,
    payload_project_id: UUID,
    payload_revision_id: UUID,
) -> None:
    if payload_revision_id != route_revision_id:
        raise EngineeringSpecConflict("Specification revision does not match the route revision")
    if str(payload_project_id) != revision.project_id:
        raise EngineeringSpecConflict("Specification project does not own the route revision")


def save_process_spec(session: Session, revision_id: UUID, spec: ProcessSpec) -> ProcessSpec:
    now = datetime.now(UTC)
    with session.begin():
        revision = ensure_revision_editable(session, revision_id)
        _validate_owner(
            revision,
            route_revision_id=revision_id,
            payload_project_id=spec.project_id,
            payload_revision_id=spec.revision_id,
        )
        existing = session.scalar(
            select(ProcessSpecRecord).where(ProcessSpecRecord.revision_id == str(revision_id))
        )
        payload = spec.model_dump(mode="json")
        if existing is None:
            session.add(
                ProcessSpecRecord(
                    id=str(spec.id),
                    project_id=str(spec.project_id),
                    revision_id=str(revision_id),
                    schema_version=spec.schema_version,
                    payload=payload,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            if existing.id != str(spec.id):
                raise EngineeringSpecConflict("ProcessSpec id cannot change within a revision")
            existing.schema_version = spec.schema_version
            existing.payload = payload
            existing.updated_at = now
        record_audit_event(
            session,
            project_id=revision.project_id,
            revision_id=revision_id,
            event_type="PROCESS_SPEC_SAVED",
            entity_type="ProcessSpec",
            entity_id=spec.id,
            details={"step_count": len(spec.steps)},
        )
    return spec


def get_process_spec(session: Session, revision_id: UUID) -> ProcessSpec:
    if session.get(ProjectRevisionRecord, str(revision_id)) is None:
        from ppe_api.application.revisions import RevisionNotFound

        raise RevisionNotFound(str(revision_id))
    record = session.scalar(
        select(ProcessSpecRecord).where(ProcessSpecRecord.revision_id == str(revision_id))
    )
    if record is None:
        raise EngineeringSpecNotFound(f"ProcessSpec for revision {revision_id}")
    return ProcessSpec.model_validate(record.payload)


def analyze_process(session: Session, revision_id: UUID) -> ProcessAnalysis:
    spec = get_process_spec(session, revision_id)
    graph = {
        step.id: (step.estimated_duration_seconds, step.predecessor_ids) for step in spec.steps
    }
    result = calculate_critical_path(graph)
    return ProcessAnalysis(
        process_spec_id=spec.id,
        project_id=spec.project_id,
        revision_id=spec.revision_id,
        critical_path_step_ids=list(result.step_ids),
        cycle_time_seconds=result.cycle_time_seconds,
        target_cycle_time_seconds=spec.target_cycle_time_seconds,
        within_target=result.cycle_time_seconds <= spec.target_cycle_time_seconds,
    )


def save_motion_spec(session: Session, revision_id: UUID, spec: MotionSpec) -> MotionSpec:
    now = datetime.now(UTC)
    with session.begin():
        revision = ensure_revision_editable(session, revision_id)
        _validate_owner(
            revision,
            route_revision_id=revision_id,
            payload_project_id=spec.project_id,
            payload_revision_id=spec.revision_id,
        )
        scene_record = session.scalar(
            select(SceneAssemblySpecRecord).where(
                SceneAssemblySpecRecord.revision_id == str(revision_id)
            )
        )
        if scene_record is not None:
            scene = SceneAssemblySpec.model_validate(scene_record.payload)
            scene_node_ids = {node.id for node in scene.nodes}
            unknown_track_ids = [
                track.id for track in spec.tracks if track.scene_node_id not in scene_node_ids
            ]
            if unknown_track_ids:
                raise EngineeringSpecConflict(
                    "MotionSpec tracks reference scene nodes outside the revision assembly: "
                    + ", ".join(str(track_id) for track_id in unknown_track_ids)
                )
        existing = session.scalar(
            select(MotionSpecRecord).where(MotionSpecRecord.revision_id == str(revision_id))
        )
        payload = spec.model_dump(mode="json")
        if existing is None:
            session.add(
                MotionSpecRecord(
                    id=str(spec.id),
                    project_id=str(spec.project_id),
                    revision_id=str(revision_id),
                    schema_version=spec.schema_version,
                    payload=payload,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            if existing.id != str(spec.id):
                raise EngineeringSpecConflict("MotionSpec id cannot change within a revision")
            existing.schema_version = spec.schema_version
            existing.payload = payload
            existing.updated_at = now
        record_audit_event(
            session,
            project_id=revision.project_id,
            revision_id=revision_id,
            event_type="MOTION_SPEC_SAVED",
            entity_type="MotionSpec",
            entity_id=spec.id,
            details={"track_count": len(spec.tracks)},
        )
    return spec


def get_motion_spec(session: Session, revision_id: UUID) -> MotionSpec:
    if session.get(ProjectRevisionRecord, str(revision_id)) is None:
        from ppe_api.application.revisions import RevisionNotFound

        raise RevisionNotFound(str(revision_id))
    record = session.scalar(
        select(MotionSpecRecord).where(MotionSpecRecord.revision_id == str(revision_id))
    )
    if record is None:
        raise EngineeringSpecNotFound(f"MotionSpec for revision {revision_id}")
    return MotionSpec.model_validate(record.payload)


def save_scene_assembly(
    session: Session, revision_id: UUID, spec: SceneAssemblySpec
) -> SceneAssemblySpec:
    now = datetime.now(UTC)
    with session.begin():
        revision = ensure_revision_editable(session, revision_id)
        _validate_owner(
            revision,
            route_revision_id=revision_id,
            payload_project_id=spec.project_id,
            payload_revision_id=spec.revision_id,
        )
        frame_ids = set(
            session.scalars(
                select(CoordinateFrameRecord.id).where(
                    CoordinateFrameRecord.revision_id == str(revision_id)
                )
            ).all()
        )
        artifact_ids = set(
            session.scalars(
                select(ArtifactRecord.id).where(ArtifactRecord.revision_id == str(revision_id))
            ).all()
        )
        for node in spec.nodes:
            if str(node.coordinate_frame_id) not in frame_ids:
                raise EngineeringSpecConflict(
                    f"Scene node {node.id} references a coordinate frame outside the revision"
                )
            if str(node.asset_version_id) not in artifact_ids:
                raise EngineeringSpecConflict(
                    f"Scene node {node.id} references an artifact outside the revision"
                )
        existing = session.scalar(
            select(SceneAssemblySpecRecord).where(
                SceneAssemblySpecRecord.revision_id == str(revision_id)
            )
        )
        payload = spec.model_dump(mode="json")
        if existing is None:
            session.add(
                SceneAssemblySpecRecord(
                    id=str(spec.id),
                    project_id=str(spec.project_id),
                    revision_id=str(revision_id),
                    schema_version=spec.schema_version,
                    payload=payload,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            if existing.id != str(spec.id):
                raise EngineeringSpecConflict(
                    "SceneAssemblySpec id cannot change within a revision"
                )
            existing.schema_version = spec.schema_version
            existing.payload = payload
            existing.updated_at = now
        record_audit_event(
            session,
            project_id=revision.project_id,
            revision_id=revision_id,
            event_type="SCENE_ASSEMBLY_SAVED",
            entity_type="SceneAssemblySpec",
            entity_id=spec.id,
            details={"node_count": len(spec.nodes)},
        )
    return spec


def get_scene_assembly(session: Session, revision_id: UUID) -> SceneAssemblySpec:
    if session.get(ProjectRevisionRecord, str(revision_id)) is None:
        from ppe_api.application.revisions import RevisionNotFound

        raise RevisionNotFound(str(revision_id))
    record = session.scalar(
        select(SceneAssemblySpecRecord).where(
            SceneAssemblySpecRecord.revision_id == str(revision_id)
        )
    )
    if record is None:
        raise EngineeringSpecNotFound(f"SceneAssemblySpec for revision {revision_id}")
    return SceneAssemblySpec.model_validate(record.payload)
