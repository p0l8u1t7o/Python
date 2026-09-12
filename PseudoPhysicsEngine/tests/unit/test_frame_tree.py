from uuid import uuid4

import pytest
from ppe_domain import FrameTreeError, validate_frame_tree


def test_accepts_one_connected_frame_tree() -> None:
    plant_id = uuid4()
    line_id = uuid4()
    machine_id = uuid4()

    validate_frame_tree({plant_id: None, line_id: plant_id, machine_id: line_id})


def test_rejects_more_than_one_root() -> None:
    with pytest.raises(FrameTreeError, match="exactly one root"):
        validate_frame_tree({uuid4(): None, uuid4(): None})


def test_rejects_cycle_even_when_every_parent_exists() -> None:
    first_id = uuid4()
    second_id = uuid4()

    with pytest.raises(FrameTreeError, match="exactly one root|must not contain a cycle"):
        validate_frame_tree({first_id: second_id, second_id: first_id})
