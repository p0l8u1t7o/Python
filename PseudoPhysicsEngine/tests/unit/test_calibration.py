import pytest
from ppe_coordinates import fit_rigid_transform, transform_point


def test_kabsch_calibration_recovers_right_handed_transform() -> None:
    source = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 100.0, 0.0), (50.0, 30.0, 20.0)]
    target = [(10.0, 20.0, 30.0), (10.0, 120.0, 30.0), (-90.0, 20.0, 30.0), (-20.0, 70.0, 50.0)]

    result = fit_rigid_transform(source, target)

    assert result.rms_error_mm == pytest.approx(0, abs=1e-10)
    assert result.max_error_mm == pytest.approx(0, abs=1e-10)
    for original, expected in zip(source, target, strict=True):
        assert transform_point(result.transform, original) == pytest.approx(expected, abs=1e-9)


def test_kabsch_calibration_rejects_collinear_control_points() -> None:
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    with pytest.raises(ValueError, match="must not be collinear"):
        fit_rigid_transform(points, points)
