from datetime import UTC, datetime
from uuid import UUID, uuid4

from ppe_schemas import ReviewCommentCreate, ReviewCommentRead, ReviewCommentResolve
from sqlalchemy import select
from sqlalchemy.orm import Session

from ppe_api.application.audit import record_audit_event
from ppe_api.application.revisions import RevisionNotFound
from ppe_api.db.models import ProjectRevisionRecord, ReviewCommentRecord


class ReviewCommentNotFound(LookupError):
    pass


class ReviewCommentConflict(ValueError):
    pass


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _to_schema(record: ReviewCommentRecord) -> ReviewCommentRead:
    created_at = _as_utc(record.created_at)
    if created_at is None:
        raise RuntimeError("Review comment creation time is missing")
    return ReviewCommentRead(
        id=UUID(record.id),
        project_id=UUID(record.project_id),
        revision_id=UUID(record.revision_id),
        author_id=UUID(record.author_id),
        body=record.body,
        object_ids=[UUID(value) for value in record.object_ids],
        parent_comment_id=UUID(record.parent_comment_id) if record.parent_comment_id else None,
        created_at=created_at,
        resolved_at=_as_utc(record.resolved_at),
        resolved_by=UUID(record.resolved_by) if record.resolved_by else None,
    )


def create_review_comment(
    session: Session, revision_id: UUID, request: ReviewCommentCreate
) -> ReviewCommentRead:
    with session.begin():
        revision = session.get(ProjectRevisionRecord, str(revision_id))
        if revision is None:
            raise RevisionNotFound(str(revision_id))
        if len(request.object_ids) != len(set(request.object_ids)):
            raise ReviewCommentConflict("Comment object ids must be unique")
        if request.parent_comment_id is not None:
            parent = session.get(ReviewCommentRecord, str(request.parent_comment_id))
            if parent is None:
                raise ReviewCommentNotFound(str(request.parent_comment_id))
            if parent.revision_id != str(revision_id):
                raise ReviewCommentConflict("Parent comment belongs to a different revision")
        record = ReviewCommentRecord(
            id=str(uuid4()),
            project_id=revision.project_id,
            revision_id=str(revision_id),
            author_id=str(request.author_id),
            body=request.body,
            object_ids=[str(value) for value in request.object_ids],
            parent_comment_id=(
                str(request.parent_comment_id) if request.parent_comment_id else None
            ),
            created_at=datetime.now(UTC),
            resolved_at=None,
            resolved_by=None,
        )
        session.add(record)
        session.flush()
        record_audit_event(
            session,
            project_id=revision.project_id,
            revision_id=revision_id,
            actor_id=request.author_id,
            event_type="REVIEW_COMMENT_CREATED",
            entity_type="ReviewComment",
            entity_id=record.id,
            details={"parent_comment_id": record.parent_comment_id or ""},
        )
        return _to_schema(record)


def list_review_comments(session: Session, revision_id: UUID) -> list[ReviewCommentRead]:
    if session.get(ProjectRevisionRecord, str(revision_id)) is None:
        raise RevisionNotFound(str(revision_id))
    records = session.scalars(
        select(ReviewCommentRecord)
        .where(ReviewCommentRecord.revision_id == str(revision_id))
        .order_by(ReviewCommentRecord.created_at, ReviewCommentRecord.id)
    ).all()
    return [_to_schema(record) for record in records]


def resolve_review_comment(
    session: Session, comment_id: UUID, request: ReviewCommentResolve
) -> ReviewCommentRead:
    with session.begin():
        record = session.get(ReviewCommentRecord, str(comment_id))
        if record is None:
            raise ReviewCommentNotFound(str(comment_id))
        newly_resolved = False
        if record.resolved_at is None:
            record.resolved_at = datetime.now(UTC)
            record.resolved_by = str(request.resolved_by)
            newly_resolved = True
        elif record.resolved_by != str(request.resolved_by):
            raise ReviewCommentConflict("Comment was already resolved by another reviewer")
        if newly_resolved:
            record_audit_event(
                session,
                project_id=record.project_id,
                revision_id=record.revision_id,
                actor_id=request.resolved_by,
                event_type="REVIEW_COMMENT_RESOLVED",
                entity_type="ReviewComment",
                entity_id=record.id,
            )
        session.flush()
        return _to_schema(record)
