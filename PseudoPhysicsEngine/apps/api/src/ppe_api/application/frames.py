from uuid import UUID

from ppe_coordinates import matrix4
from ppe_domain import FrameTreeError, TrustStatus, validate_frame_tree
from ppe_schemas import CoordinateFrame, FrameCreate, FrameTransform, FrameTreeRead
from sqlalchemy import select
from sqlalchemy.orm import Session

from ppe_api.application.revisions import RevisionNotFound, ensure_revision_editable
from ppe_api.db.models import (
    CoordinateFrameRecord,
    FrameTransformRecord,
    ProjectRevisionRecord,
)


class FrameTreeConflict(ValueError):
    pass


def _to_frame(record: CoordinateFrameRecord) -> CoordinateFrame:
    return CoordinateFrame(
        id=UUID(record.id),
        revision_id=UUID(record.revision_id),
        name=record.name,
        parent_frame_id=UUID(record.parent_frame_id) if record.parent_frame_id else None,
        length_unit="mm",
        axis_system="RIGHT_HANDED_Z_UP",
    )


def _to_transform(record: FrameTransformRecord) -> FrameTransform:
    return FrameTransform(
        id=UUID(record.id),
        revision_id=UUID(record.revision_id),
        parent_frame_id=UUID(record.parent_frame_id),
        child_frame_id=UUID(record.child_frame_id),
        matrix=matrix4(record.matrix),
        trust_status=TrustStatus(record.trust_status),
        source=record.source,
    )


def get_frame_tree(session: Session, revision_id: UUID) -> FrameTreeRead:
    revision = session.get(ProjectRevisionRecord, str(revision_id))
    if revision is None:
        raise RevisionNotFound(str(revision_id))

    frames = session.scalars(
        select(CoordinateFrameRecord)
        .where(CoordinateFrameRecord.revision_id == str(revision_id))
        .order_by(CoordinateFrameRecord.name)
    ).all()
    transforms = session.scalars(
        select(FrameTransformRecord)
        .where(FrameTransformRecord.revision_id == str(revision_id))
        .order_by(FrameTransformRecord.id)
    ).all()
    return FrameTreeRead(
        revision_id=revision_id,
        frames=[_to_frame(frame) for frame in frames],
        transforms=[_to_transform(transform) for transform in transforms],
    )


def add_frame(session: Session, revision_id: UUID, request: FrameCreate) -> FrameTreeRead:
    with session.begin():
        ensure_revision_editable(session, revision_id)
        if request.frame.revision_id != revision_id:
            raise FrameTreeConflict("Frame revision does not match the route revision")

        existing_frames = session.scalars(
            select(CoordinateFrameRecord).where(
                CoordinateFrameRecord.revision_id == str(revision_id)
            )
        ).all()
        if any(frame.id == str(request.frame.id) for frame in existing_frames):
            raise FrameTreeConflict(f"Frame {request.frame.id} already exists")
        if any(frame.name == request.frame.name for frame in existing_frames):
            raise FrameTreeConflict(f"Frame name {request.frame.name!r} already exists")

        parent_by_frame = {
            UUID(frame.id): UUID(frame.parent_frame_id) if frame.parent_frame_id else None
            for frame in existing_frames
        }
        parent_by_frame[request.frame.id] = request.frame.parent_frame_id
        try:
            validate_frame_tree(parent_by_frame)
        except FrameTreeError as error:
            raise FrameTreeConflict(str(error)) from error

        session.add(
            CoordinateFrameRecord(
                id=str(request.frame.id),
                revision_id=str(revision_id),
                name=request.frame.name,
                parent_frame_id=(
                    str(request.frame.parent_frame_id) if request.frame.parent_frame_id else None
                ),
                length_unit=request.frame.length_unit,
                axis_system=request.frame.axis_system,
            )
        )
        session.flush()

        transform = request.transform_from_parent
        if transform is not None:
            session.add(
                FrameTransformRecord(
                    id=str(transform.id),
                    revision_id=str(revision_id),
                    parent_frame_id=str(transform.parent_frame_id),
                    child_frame_id=str(transform.child_frame_id),
                    matrix=[list(row) for row in transform.matrix],
                    trust_status=transform.trust_status,
                    source=transform.source,
                )
            )

    return get_frame_tree(session, revision_id)
