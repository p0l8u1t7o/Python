from math import cos, pi, sin

import pytest
from ppe_coordinates import (
    IDENTITY_MATRIX,
    compose,
    inverse_rigid,
    matrix4,
    transform_point,
    validate_rigid_transform,
)


def test_composes_parent_and_child_transforms_in_millimetres() -> None:
    plant_from_machine = matrix4(
        (
            (1, 0, 0, 1_000),
            (0, 1, 0, 2_000),
            (0, 0, 1, 0),
            (0, 0, 0, 1),
        )
    )
    quarter_turn = pi / 2
    machine_from_asset = matrix4(
        (
            (cos(quarter_turn), -sin(quarter_turn), 0, 100),
            (sin(quarter_turn), cos(quarter_turn), 0, 0),
            (0, 0, 1, 50),
            (0, 0, 0, 1),
        )
    )

    plant_from_asset = compose(plant_from_machine, machine_from_asset)

    assert transform_point(plant_from_asset, (10, 0, 0)) == pytest.approx((1_100, 2_010, 50))


def test_rigid_inverse_round_trip() -> None:
    transform = matrix4(
        (
            (0, -1, 0, 120),
            (1, 0, 0, -50),
            (0, 0, 1, 30),
            (0, 0, 0, 1),
        )
    )

    round_trip = compose(transform, inverse_rigid(transform))
    for actual_row, expected_row in zip(round_trip, IDENTITY_MATRIX, strict=True):
        assert actual_row == pytest.approx(expected_row)


def test_rejects_reflection_that_changes_handedness() -> None:
    reflected = matrix4(
        (
            (-1, 0, 0, 0),
            (0, 1, 0, 0),
            (0, 0, 1, 0),
            (0, 0, 0, 1),
        )
    )

    with pytest.raises(ValueError, match="right-handed"):
        validate_rigid_transform(reflected)
