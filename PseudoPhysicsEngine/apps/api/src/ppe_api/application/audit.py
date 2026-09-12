from datetime import UTC, datetime
from uuid import UUID, uuid4

from ppe_schemas import AuditEventRead
from sqlalchemy import select
from sqlalchemy.orm import Session

from ppe_api.db.models import AuditEventRecord, ProjectRecord, ProjectRevisionRecord


def record_audit_event(
    session: Session,
    *,
    project_id: UUID | str,
    event_type: str,
    entity_type: str,
    revision_id: UUID | str | None = None,
    actor_id: UUID | str | None = None,
    entity_id: UUID | str | None = None,
    details: dict[str, object] | None = None,
) -> AuditEventRecord:
    record = AuditEventRecord(
        id=str(uuid4()),
        project_id=str(project_id),
        revision_id=str(revision_id) if revision_id is not None else None,
        actor_id=str(actor_id) if actor_id is not None else None,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details or {},
        created_at=datetime.now(UTC),
    )
    session.add(record)
    return record


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _to_schema(record: AuditEventRecord) -> AuditEventRead:
    return AuditEventRead(
        id=UUID(record.id),
        project_id=UUID(record.project_id),
        revision_id=UUID(record.revision_id) if record.revision_id else None,
        actor_id=UUID(record.actor_id) if record.actor_id else None,
        event_type=record.event_type,
        entity_type=record.entity_type,
        entity_id=UUID(record.entity_id) if record.entity_id else None,
        details=record.details,
        created_at=_as_utc(record.created_at),
    )


def list_audit_events(
    session: Session, project_id: UUID, revision_id: UUID | None = None
) -> list[AuditEventRead]:
    from ppe_api.application.projects import ProjectNotFound
    from ppe_api.application.revisions import RevisionComparisonConflict, RevisionNotFound

    if session.get(ProjectRecord, str(project_id)) is None:
        raise ProjectNotFound(str(project_id))
    query = select(AuditEventRecord).where(AuditEventRecord.project_id == str(project_id))
    if revision_id is not None:
        revision = session.get(ProjectRevisionRecord, str(revision_id))
        if revision is None:
            raise RevisionNotFound(str(revision_id))
        if revision.project_id != str(project_id):
            raise RevisionComparisonConflict("Audit revision belongs to a different project")
        query = query.where(AuditEventRecord.revision_id == str(revision_id))
    records = session.scalars(
        query.order_by(AuditEventRecord.created_at, AuditEventRecord.id)
    ).all()
    return [_to_schema(record) for record in records]
