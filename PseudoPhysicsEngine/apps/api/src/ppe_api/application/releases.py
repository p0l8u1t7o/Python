import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ppe_domain import RevisionStatus
from ppe_schemas import (
    ArtifactFormat,
    ArtifactKind,
    ReleaseArtifact,
    ReleaseManifest,
    ReleaseRequest,
    ValidationStatus,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ppe_api.application.audit import record_audit_event
from ppe_api.application.revisions import RevisionNotFound, ensure_revision_editable
from ppe_api.application.validation import run_validation
from ppe_api.db.models import ArtifactRecord, ProjectRevisionRecord, ReleaseManifestRecord


class ReleaseNotFound(LookupError):
    pass


class ReleaseRejected(ValueError):
    pass


def _artifact_kind(value: str) -> ArtifactKind:
    return ArtifactKind.STEP if value == ArtifactFormat.STEP else ArtifactKind.OTHER


def _to_schema(record: ReleaseManifestRecord) -> ReleaseManifest:
    return ReleaseManifest.model_validate(record.payload)


def get_release_manifest(session: Session, revision_id: UUID) -> ReleaseManifest:
    if session.get(ProjectRevisionRecord, str(revision_id)) is None:
        raise RevisionNotFound(str(revision_id))
    record = session.scalar(
        select(ReleaseManifestRecord).where(ReleaseManifestRecord.revision_id == str(revision_id))
    )
    if record is None:
        raise ReleaseNotFound(str(revision_id))
    return _to_schema(record)


def release_revision(
    session: Session, revision_id: UUID, request: ReleaseRequest
) -> ReleaseManifest:
    existing = session.scalar(
        select(ReleaseManifestRecord).where(ReleaseManifestRecord.revision_id == str(revision_id))
    )
    if existing is not None:
        if existing.approved_by != str(request.approved_by):
            raise ReleaseRejected("Revision was already released by another approver")
        return _to_schema(existing)
    session.commit()

    report = run_validation(session, revision_id)
    if report.status != ValidationStatus.PASSED:
        codes = ", ".join(issue.code for issue in report.issues if issue.blocks_release)
        raise ReleaseRejected(f"Revision failed release validation: {codes}")

    artifact_records = session.scalars(
        select(ArtifactRecord)
        .where(ArtifactRecord.revision_id == str(revision_id))
        .order_by(ArtifactRecord.created_at, ArtifactRecord.id)
    ).all()
    unique_by_hash: dict[str, ArtifactRecord] = {}
    for artifact in artifact_records:
        unique_by_hash.setdefault(artifact.sha256, artifact)
    now = datetime.now(UTC)
    manifest = ReleaseManifest(
        id=uuid4(),
        project_id=report.project_id,
        revision_id=revision_id,
        validation_report_id=report.id,
        approved_by=request.approved_by,
        generated_at=now,
        artifacts=[
            ReleaseArtifact(
                id=UUID(artifact.id),
                kind=_artifact_kind(artifact.format),
                uri=artifact.storage_uri,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                mime_type=artifact.mime_type,
            )
            for artifact in unique_by_hash.values()
        ],
    )
    payload = manifest.model_dump(mode="json")
    manifest_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    session.commit()
    with session.begin():
        revision = ensure_revision_editable(session, revision_id)
        revision.status = RevisionStatus.RELEASED
        session.add(
            ReleaseManifestRecord(
                id=str(manifest.id),
                project_id=revision.project_id,
                revision_id=str(revision_id),
                validation_report_id=str(report.id),
                approved_by=str(request.approved_by),
                manifest_sha256=manifest_hash,
                payload=payload,
                generated_at=now,
            )
        )
        record_audit_event(
            session,
            project_id=revision.project_id,
            revision_id=revision_id,
            actor_id=request.approved_by,
            event_type="REVISION_RELEASED",
            entity_type="ReleaseManifest",
            entity_id=manifest.id,
            details={
                "manifest_sha256": manifest_hash,
                "artifact_count": len(manifest.artifacts),
            },
        )
    return manifest
