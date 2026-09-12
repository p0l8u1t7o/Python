from datetime import UTC, datetime
from uuid import UUID, uuid4

from ppe_domain import RevisionStatus
from ppe_schemas import ProjectCreate, ProjectRead, ProjectRevision
from sqlalchemy import select
from sqlalchemy.orm import Session

from ppe_api.application.audit import record_audit_event
from ppe_api.db.models import ProjectRecord, ProjectRevisionRecord


class ProjectNotFound(LookupError):
    pass


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_schema(project: ProjectRecord, revision: ProjectRevisionRecord) -> ProjectRead:
    return ProjectRead(
        id=UUID(project.id),
        name=project.name,
        customer_name=project.customer_name,
        created_at=_as_utc(project.created_at),
        current_revision=ProjectRevision(
            id=UUID(revision.id),
            project_id=UUID(revision.project_id),
            sequence=revision.sequence,
            status=RevisionStatus(revision.status),
            parent_revision_id=(
                UUID(revision.parent_revision_id) if revision.parent_revision_id else None
            ),
            created_at=_as_utc(revision.created_at),
        ),
    )


def create_project(session: Session, request: ProjectCreate) -> ProjectRead:
    now = datetime.now(UTC)
    project = ProjectRecord(
        id=str(uuid4()),
        name=request.name,
        customer_name=request.customer_name,
        created_at=now,
    )
    revision = ProjectRevisionRecord(
        id=str(uuid4()),
        project_id=project.id,
        sequence=1,
        status=RevisionStatus.DRAFT,
        created_at=now,
    )

    with session.begin():
        session.add(project)
        session.add(revision)
        session.flush()
        record_audit_event(
            session,
            project_id=project.id,
            revision_id=revision.id,
            event_type="PROJECT_CREATED",
            entity_type="Project",
            entity_id=project.id,
            details={"name": project.name},
        )

    return _to_schema(project, revision)


def get_project(session: Session, project_id: UUID) -> ProjectRead:
    project = session.get(ProjectRecord, str(project_id))
    if project is None:
        raise ProjectNotFound(str(project_id))

    revision = session.scalar(
        select(ProjectRevisionRecord)
        .where(ProjectRevisionRecord.project_id == project.id)
        .order_by(ProjectRevisionRecord.sequence.desc())
        .limit(1)
    )
    if revision is None:
        raise RuntimeError(f"Project {project_id} has no revision")
    return _to_schema(project, revision)


def list_projects(session: Session) -> list[ProjectRead]:
    projects = session.scalars(
        select(ProjectRecord).order_by(ProjectRecord.created_at.desc(), ProjectRecord.id.desc())
    ).all()
    revisions = session.scalars(
        select(ProjectRevisionRecord).order_by(
            ProjectRevisionRecord.project_id,
            ProjectRevisionRecord.sequence.desc(),
        )
    ).all()
    latest_by_project: dict[str, ProjectRevisionRecord] = {}
    for revision in revisions:
        latest_by_project.setdefault(revision.project_id, revision)

    result: list[ProjectRead] = []
    for project in projects:
        latest_revision = latest_by_project.get(project.id)
        if latest_revision is None:
            raise RuntimeError(f"Project {project.id} has no revision")
        result.append(_to_schema(project, latest_revision))
    return result
