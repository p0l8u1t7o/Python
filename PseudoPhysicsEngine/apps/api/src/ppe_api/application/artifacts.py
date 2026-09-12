import hashlib
import os
import tempfile
from collections.abc import AsyncIterable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from ppe_schemas import ArtifactFormat, ArtifactRead
from sqlalchemy import select
from sqlalchemy.orm import Session

from ppe_api.application.audit import record_audit_event
from ppe_api.application.projects import ProjectNotFound
from ppe_api.application.revisions import RevisionNotFound
from ppe_api.db.models import ArtifactRecord, ProjectRecord, ProjectRevisionRecord


class ArtifactNotFound(LookupError):
    pass


class ArtifactRejected(ValueError):
    pass


_FORMAT_BY_EXTENSION = {
    ".step": ArtifactFormat.STEP,
    ".stp": ArtifactFormat.STEP,
    ".glb": ArtifactFormat.GLB,
    ".pdf": ArtifactFormat.PDF,
}
_MIME_BY_FORMAT = {
    ArtifactFormat.STEP: "application/step",
    ArtifactFormat.GLB: "model/gltf-binary",
    ArtifactFormat.PDF: "application/pdf",
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_schema(record: ArtifactRecord) -> ArtifactRead:
    return ArtifactRead(
        id=UUID(record.id),
        project_id=UUID(record.project_id),
        revision_id=UUID(record.revision_id),
        original_filename=record.original_filename,
        format=ArtifactFormat(record.format),
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        storage_uri=record.storage_uri,
        source=record.source,
        created_at=_as_utc(record.created_at),
    )


def _safe_filename(filename: str) -> str:
    if "\x00" in filename:
        raise ArtifactRejected("Filename contains a null byte")
    safe_name = Path(filename.replace("\\", "/")).name.strip()
    if not safe_name or safe_name in {".", ".."}:
        raise ArtifactRejected("Filename is empty")
    if len(safe_name) > 255:
        raise ArtifactRejected("Filename exceeds 255 characters")
    return safe_name


def _detect_format(filename: str, header: bytes, size_bytes: int) -> ArtifactFormat:
    expected = _FORMAT_BY_EXTENSION.get(Path(filename).suffix.lower())
    if expected is None:
        raise ArtifactRejected("Only STEP, GLB, and PDF uploads are currently supported")

    stripped = header.lstrip(b"\xef\xbb\xbf \t\r\n")
    glb_header_valid = (
        len(header) >= 20
        and header.startswith(b"glTF")
        and int.from_bytes(header[4:8], "little") == 2
        and int.from_bytes(header[8:12], "little") == size_bytes
        and header[16:20] == b"JSON"
    )
    signature_matches = {
        ArtifactFormat.STEP: stripped.startswith(b"ISO-10303-21;"),
        ArtifactFormat.GLB: glb_header_valid,
        ArtifactFormat.PDF: stripped.startswith(b"%PDF-"),
    }
    if not signature_matches[expected]:
        raise ArtifactRejected(f"File content does not match the {expected} signature")
    return expected


def _validate_ownership(session: Session, project_id: UUID, revision_id: UUID) -> None:
    project = session.get(ProjectRecord, str(project_id))
    if project is None:
        raise ProjectNotFound(str(project_id))
    revision = session.get(ProjectRevisionRecord, str(revision_id))
    if revision is None:
        raise RevisionNotFound(str(revision_id))
    if revision.project_id != str(project_id):
        raise ArtifactRejected("Revision does not belong to the project")
    session.rollback()


async def create_artifact(
    session: Session,
    *,
    project_id: UUID,
    revision_id: UUID,
    filename: str,
    source: str,
    content: AsyncIterable[bytes],
    storage_dir: Path,
    max_upload_bytes: int,
) -> ArtifactRead:
    _validate_ownership(session, project_id, revision_id)
    safe_name = _safe_filename(filename)
    if not source.strip():
        raise ArtifactRejected("Source is required")

    temporary_directory = storage_dir / "tmp"
    temporary_directory.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(dir=temporary_directory)
    temporary_path = Path(temporary_name)
    digest = hashlib.sha256()
    size_bytes = 0
    header = bytearray()
    try:
        with os.fdopen(file_descriptor, "wb") as output:
            async for chunk in content:
                if not chunk:
                    continue
                size_bytes += len(chunk)
                if size_bytes > max_upload_bytes:
                    raise ArtifactRejected(f"File exceeds the {max_upload_bytes}-byte upload limit")
                digest.update(chunk)
                if len(header) < 4096:
                    header.extend(chunk[: 4096 - len(header)])
                output.write(chunk)

        if size_bytes == 0:
            raise ArtifactRejected("File is empty")
        artifact_format = _detect_format(safe_name, bytes(header), size_bytes)
        sha256 = digest.hexdigest()
        storage_uri = f"objects/sha256/{sha256[:2]}/{sha256}"
        destination = storage_dir / Path(storage_uri)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            temporary_path.unlink()
        else:
            os.replace(temporary_path, destination)

        now = datetime.now(UTC)
        record = ArtifactRecord(
            id=str(uuid4()),
            project_id=str(project_id),
            revision_id=str(revision_id),
            original_filename=safe_name,
            format=artifact_format,
            mime_type=_MIME_BY_FORMAT[artifact_format],
            size_bytes=size_bytes,
            sha256=sha256,
            storage_uri=storage_uri,
            source=source.strip(),
            created_at=now,
        )
        with session.begin():
            session.add(record)
            session.flush()
            record_audit_event(
                session,
                project_id=project_id,
                revision_id=revision_id,
                event_type="ARTIFACT_UPLOADED",
                entity_type="Artifact",
                entity_id=record.id,
                details={
                    "filename": safe_name,
                    "format": artifact_format.value,
                    "sha256": sha256,
                    "size_bytes": size_bytes,
                },
            )
        return _to_schema(record)
    finally:
        temporary_path.unlink(missing_ok=True)


def list_artifacts(
    session: Session, project_id: UUID, revision_id: UUID | None = None
) -> list[ArtifactRead]:
    if session.get(ProjectRecord, str(project_id)) is None:
        raise ProjectNotFound(str(project_id))
    query = select(ArtifactRecord).where(ArtifactRecord.project_id == str(project_id))
    if revision_id is not None:
        query = query.where(ArtifactRecord.revision_id == str(revision_id))
    records = session.scalars(
        query.order_by(ArtifactRecord.created_at.desc(), ArtifactRecord.id.desc())
    ).all()
    return [_to_schema(record) for record in records]


def get_artifact_content(
    session: Session, artifact_id: UUID, storage_dir: Path
) -> tuple[ArtifactRead, Path]:
    record = session.get(ArtifactRecord, str(artifact_id))
    if record is None:
        raise ArtifactNotFound(str(artifact_id))
    root = storage_dir.resolve()
    path = (root / record.storage_uri).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ArtifactRejected("Artifact storage path escapes the configured root") from error
    if not path.is_file():
        raise ArtifactNotFound(f"{artifact_id} content")
    return _to_schema(record), path
