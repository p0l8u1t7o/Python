from collections.abc import Mapping
from uuid import UUID


class FrameTreeError(ValueError):
    pass


def validate_frame_tree(parent_by_frame: Mapping[UUID, UUID | None]) -> None:
    """Validate one connected, acyclic coordinate-frame tree."""
    if not parent_by_frame:
        return

    roots = [frame_id for frame_id, parent_id in parent_by_frame.items() if parent_id is None]
    if len(roots) != 1:
        raise FrameTreeError("A frame tree must contain exactly one root")

    known_ids = set(parent_by_frame)
    for frame_id, parent_id in parent_by_frame.items():
        if frame_id == parent_id:
            raise FrameTreeError("A coordinate frame cannot be its own parent")
        if parent_id is not None and parent_id not in known_ids:
            raise FrameTreeError("A coordinate frame references an unknown parent")

    for starting_id in parent_by_frame:
        visited_on_path: set[UUID] = set()
        current_id: UUID | None = starting_id
        while current_id is not None:
            if current_id in visited_on_path:
                raise FrameTreeError("A coordinate frame tree must not contain a cycle")
            visited_on_path.add(current_id)
            current_id = parent_by_frame[current_id]
