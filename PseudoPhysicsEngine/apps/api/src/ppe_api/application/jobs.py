import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from ppe_schemas import (
    JobClaimRequest,
    JobCompleteRequest,
    JobFailRequest,
    JobHeartbeatRequest,
    JobKind,
    JobRead,
    JobStatus,
    JobSubmit,
)
from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from ppe_api.application.audit import record_audit_event
from ppe_api.application.projects import ProjectNotFound
from ppe_api.application.revisions import RevisionNotFound
from ppe_api.db.models import ArtifactRecord, JobRecord, ProjectRecord, ProjectRevisionRecord


class JobNotFound(LookupError):
    pass


class JobConflict(ValueError):
    pass


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_utc(value: datetime) -> datetime:
    result = _as_utc(value)
    if result is None:
        raise RuntimeError("Required job timestamp is missing")
    return result


def _to_schema(record: JobRecord) -> JobRead:
    return JobRead(
        id=UUID(record.id),
        project_id=UUID(record.project_id),
        revision_id=UUID(record.revision_id),
        kind=JobKind(record.kind),
        status=JobStatus(record.status),
        idempotency_key=record.idempotency_key,
        input_artifact_ids=[UUID(value) for value in record.input_artifact_ids],
        result_artifact_ids=[UUID(value) for value in record.result_artifact_ids],
        parameters=record.parameters,
        tool_name=record.tool_name,
        tool_version=record.tool_version,
        worker_id=record.worker_id,
        attempt_count=record.attempt_count,
        max_attempts=record.max_attempts,
        error=record.error,
        created_at=_required_utc(record.created_at),
        started_at=_as_utc(record.started_at),
        heartbeat_at=_as_utc(record.heartbeat_at),
        lease_expires_at=_as_utc(record.lease_expires_at),
        finished_at=_as_utc(record.finished_at),
    )


def _payload_hash(request: JobSubmit) -> str:
    data = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def _validate_job_scope(session: Session, request: JobSubmit) -> None:
    project = session.get(ProjectRecord, str(request.project_id))
    if project is None:
        raise ProjectNotFound(str(request.project_id))
    revision = session.get(ProjectRevisionRecord, str(request.revision_id))
    if revision is None:
        raise RevisionNotFound(str(request.revision_id))
    if revision.project_id != project.id:
        raise JobConflict("Revision does not belong to the job project")
    if len(request.input_artifact_ids) != len(set(request.input_artifact_ids)):
        raise JobConflict("Input artifact ids must be unique")
    for artifact_id in request.input_artifact_ids:
        artifact = session.get(ArtifactRecord, str(artifact_id))
        if artifact is None:
            raise JobConflict(f"Input artifact {artifact_id} does not exist")
        if artifact.project_id != project.id or artifact.revision_id != revision.id:
            raise JobConflict(f"Input artifact {artifact_id} is outside the job revision")


def submit_job(session: Session, request: JobSubmit) -> JobRead:
    payload_sha256 = _payload_hash(request)
    with session.begin():
        existing = session.scalar(
            select(JobRecord).where(
                JobRecord.project_id == str(request.project_id),
                JobRecord.idempotency_key == request.idempotency_key,
            )
        )
        if existing is not None:
            if existing.payload_sha256 != payload_sha256:
                raise JobConflict("Idempotency key was already used with a different payload")
            return _to_schema(existing)

        _validate_job_scope(session, request)
        record = JobRecord(
            id=str(uuid4()),
            project_id=str(request.project_id),
            revision_id=str(request.revision_id),
            kind=request.kind,
            status=JobStatus.PENDING,
            idempotency_key=request.idempotency_key,
            payload_sha256=payload_sha256,
            input_artifact_ids=[str(value) for value in request.input_artifact_ids],
            result_artifact_ids=[],
            parameters=request.parameters,
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            worker_id=None,
            attempt_count=0,
            max_attempts=request.max_attempts,
            error=None,
            created_at=datetime.now(UTC),
            started_at=None,
            heartbeat_at=None,
            lease_expires_at=None,
            finished_at=None,
        )
        session.add(record)
        session.flush()
        record_audit_event(
            session,
            project_id=record.project_id,
            revision_id=record.revision_id,
            event_type="JOB_SUBMITTED",
            entity_type="Job",
            entity_id=record.id,
            details={"kind": record.kind, "tool_name": record.tool_name},
        )
        return _to_schema(record)


def get_job(session: Session, job_id: UUID) -> JobRead:
    record = session.get(JobRecord, str(job_id))
    if record is None:
        raise JobNotFound(str(job_id))
    return _to_schema(record)


def list_jobs(session: Session, project_id: UUID, revision_id: UUID | None = None) -> list[JobRead]:
    if session.get(ProjectRecord, str(project_id)) is None:
        raise ProjectNotFound(str(project_id))
    query = select(JobRecord).where(JobRecord.project_id == str(project_id))
    if revision_id is not None:
        query = query.where(JobRecord.revision_id == str(revision_id))
    records = session.scalars(
        query.order_by(JobRecord.created_at.desc(), JobRecord.id.desc())
    ).all()
    return [_to_schema(record) for record in records]


def claim_job(session: Session, request: JobClaimRequest) -> JobRead | None:
    now = datetime.now(UTC)
    expired = and_(
        JobRecord.status == JobStatus.RUNNING,
        JobRecord.lease_expires_at.is_not(None),
        JobRecord.lease_expires_at <= now,
    )
    eligible = or_(JobRecord.status == JobStatus.PENDING, expired)
    with session.begin():
        session.execute(
            update(JobRecord)
            .where(expired, JobRecord.attempt_count >= JobRecord.max_attempts)
            .values(
                status=JobStatus.FAILED,
                error="Worker lease expired after maximum attempts",
                worker_id=None,
                lease_expires_at=None,
                finished_at=now,
            )
        )
        candidate = session.scalar(
            select(JobRecord)
            .where(
                JobRecord.kind.in_([kind.value for kind in request.supported_kinds]),
                JobRecord.attempt_count < JobRecord.max_attempts,
                eligible,
            )
            .order_by(JobRecord.created_at, JobRecord.id)
            .limit(1)
        )
        if candidate is None:
            return None

        claimed = cast(
            CursorResult[Any],
            session.execute(
                update(JobRecord)
                .where(
                    JobRecord.id == candidate.id,
                    JobRecord.attempt_count == candidate.attempt_count,
                    eligible,
                )
                .values(
                    status=JobStatus.RUNNING,
                    worker_id=request.worker_id,
                    attempt_count=candidate.attempt_count + 1,
                    started_at=now,
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=request.lease_seconds),
                    error=None,
                    finished_at=None,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        if claimed.rowcount != 1:
            raise JobConflict("Job claim raced with another worker; retry the claim")
        session.expire_all()
        record = session.get(JobRecord, candidate.id)
        if record is None:
            raise RuntimeError("Claimed job disappeared")
        record_audit_event(
            session,
            project_id=record.project_id,
            revision_id=record.revision_id,
            event_type="JOB_CLAIMED",
            entity_type="Job",
            entity_id=record.id,
            details={"worker_id": request.worker_id, "attempt": record.attempt_count},
        )
        return _to_schema(record)


def _running_job(session: Session, job_id: UUID, worker_id: str) -> JobRecord:
    record = session.get(JobRecord, str(job_id))
    if record is None:
        raise JobNotFound(str(job_id))
    if record.status != JobStatus.RUNNING:
        raise JobConflict(f"Job {job_id} is {record.status}, not RUNNING")
    if record.worker_id != worker_id:
        raise JobConflict("Job is leased to a different worker")
    lease_expires_at = _as_utc(record.lease_expires_at)
    if lease_expires_at is None or lease_expires_at <= datetime.now(UTC):
        raise JobConflict("Worker lease has expired")
    return record


def heartbeat_job(session: Session, job_id: UUID, request: JobHeartbeatRequest) -> JobRead:
    with session.begin():
        record = _running_job(session, job_id, request.worker_id)
        now = datetime.now(UTC)
        record.heartbeat_at = now
        record.lease_expires_at = now + timedelta(seconds=request.lease_seconds)
        session.flush()
        return _to_schema(record)


def complete_job(session: Session, job_id: UUID, request: JobCompleteRequest) -> JobRead:
    with session.begin():
        record = _running_job(session, job_id, request.worker_id)
        if len(request.result_artifact_ids) != len(set(request.result_artifact_ids)):
            raise JobConflict("Result artifact ids must be unique")
        for artifact_id in request.result_artifact_ids:
            artifact = session.get(ArtifactRecord, str(artifact_id))
            if artifact is None:
                raise JobConflict(f"Result artifact {artifact_id} does not exist")
            if (
                artifact.project_id != record.project_id
                or artifact.revision_id != record.revision_id
            ):
                raise JobConflict(f"Result artifact {artifact_id} is outside the job revision")
        record.status = JobStatus.SUCCEEDED
        record.result_artifact_ids = [str(value) for value in request.result_artifact_ids]
        record.heartbeat_at = datetime.now(UTC)
        record.lease_expires_at = None
        record.finished_at = datetime.now(UTC)
        record_audit_event(
            session,
            project_id=record.project_id,
            revision_id=record.revision_id,
            event_type="JOB_COMPLETED",
            entity_type="Job",
            entity_id=record.id,
            details={"worker_id": request.worker_id},
        )
        session.flush()
        return _to_schema(record)


def fail_job(session: Session, job_id: UUID, request: JobFailRequest) -> JobRead:
    with session.begin():
        record = _running_job(session, job_id, request.worker_id)
        record.error = request.error
        record.worker_id = None
        record.heartbeat_at = None
        record.lease_expires_at = None
        if request.retryable and record.attempt_count < record.max_attempts:
            record.status = JobStatus.PENDING
            record.finished_at = None
        else:
            record.status = JobStatus.FAILED
            record.finished_at = datetime.now(UTC)
        record_audit_event(
            session,
            project_id=record.project_id,
            revision_id=record.revision_id,
            event_type=("JOB_REQUEUED" if record.status == JobStatus.PENDING else "JOB_FAILED"),
            entity_type="Job",
            entity_id=record.id,
            details={"worker_id": request.worker_id, "error": request.error},
        )
        session.flush()
        return _to_schema(record)


def cancel_job(session: Session, job_id: UUID) -> JobRead:
    with session.begin():
        record = session.get(JobRecord, str(job_id))
        if record is None:
            raise JobNotFound(str(job_id))
        if record.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
            raise JobConflict(f"Job {job_id} is already terminal")
        record.status = JobStatus.CANCELLED
        record.worker_id = None
        record.lease_expires_at = None
        record.finished_at = datetime.now(UTC)
        record_audit_event(
            session,
            project_id=record.project_id,
            revision_id=record.revision_id,
            event_type="JOB_CANCELLED",
            entity_type="Job",
            entity_id=record.id,
        )
        session.flush()
        return _to_schema(record)
