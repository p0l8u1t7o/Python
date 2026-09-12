from dataclasses import dataclass
from math import sqrt

import numpy as np
import numpy.typing as npt

from ppe_coordinates.transforms import Matrix4, Point3, matrix4, validate_rigid_transform


@dataclass(frozen=True, slots=True)
class RigidCalibration:
    transform: Matrix4
    residuals_mm: tuple[float, ...]
    rms_error_mm: float
    max_error_mm: float


def fit_rigid_transform(
    source_points_mm: list[Point3], target_points_mm: list[Point3]
) -> RigidCalibration:
    """Fit a right-handed source-to-target transform with the Kabsch algorithm."""
    if len(source_points_mm) != len(target_points_mm):
        raise ValueError("Source and target control-point counts must match")
    if len(source_points_mm) < 3:
        raise ValueError("At least three control-point pairs are required")
    source: npt.NDArray[np.float64] = np.asarray(source_points_mm, dtype=np.float64)
    target: npt.NDArray[np.float64] = np.asarray(target_points_mm, dtype=np.float64)
    source_centered = source - source.mean(axis=0)
    target_centered = target - target.mean(axis=0)
    if np.linalg.matrix_rank(source_centered) < 2:
        raise ValueError("Source control points must not be collinear")
    if np.linalg.matrix_rank(target_centered) < 2:
        raise ValueError("Target control points must not be collinear")

    covariance = source_centered.T @ target_centered
    left, _singular_values, right_transpose = np.linalg.svd(covariance)
    rotation = right_transpose.T @ left.T
    if np.linalg.det(rotation) < 0:
        right_transpose[-1, :] *= -1
        rotation = right_transpose.T @ left.T
    translation = target.mean(axis=0) - rotation @ source.mean(axis=0)
    transform = matrix4(
        [
            [float(rotation[row, column]) for column in range(3)] + [float(translation[row])]
            for row in range(3)
        ]
        + [[0.0, 0.0, 0.0, 1.0]]
    )
    validate_rigid_transform(transform, tolerance=1e-7)

    fitted = (rotation @ source.T).T + translation
    residuals = np.linalg.norm(fitted - target, axis=1)
    residual_values = tuple(float(value) for value in residuals)
    rms = sqrt(sum(value * value for value in residual_values) / len(residual_values))
    return RigidCalibration(
        transform=transform,
        residuals_mm=residual_values,
        rms_error_mm=rms,
        max_error_mm=max(residual_values),
    )
