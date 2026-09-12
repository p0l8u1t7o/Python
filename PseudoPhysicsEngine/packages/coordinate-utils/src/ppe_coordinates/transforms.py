from collections.abc import Sequence
from math import isclose

type Vector4 = tuple[float, float, float, float]
type Matrix4 = tuple[Vector4, Vector4, Vector4, Vector4]
type Point3 = tuple[float, float, float]

IDENTITY_MATRIX: Matrix4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def matrix4(values: Sequence[Sequence[float]]) -> Matrix4:
    """Convert nested values into an immutable 4x4 matrix."""
    if len(values) != 4 or any(len(row) != 4 for row in values):
        raise ValueError("A transform must contain exactly four rows of four values")
    rows = tuple(tuple(float(value) for value in row) for row in values)
    return rows  # type: ignore[return-value]


def _determinant3(matrix: Matrix4) -> float:
    a, b, c = matrix[0][:3]
    d, e, f = matrix[1][:3]
    g, h, i = matrix[2][:3]
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def validate_rigid_transform(matrix: Matrix4, *, tolerance: float = 1e-9) -> None:
    """Reject non-rigid or reflected transforms.

    Matrices are row-major, operate on column vectors, and store translation in
    the final column. A positive unit determinant preserves right-handedness.
    """
    expected_last_row = (0.0, 0.0, 0.0, 1.0)
    if any(
        not isclose(actual, expected, abs_tol=tolerance)
        for actual, expected in zip(matrix[3], expected_last_row, strict=True)
    ):
        raise ValueError("A rigid transform must end with [0, 0, 0, 1]")

    rotation_rows = [matrix[row][:3] for row in range(3)]
    for row_index, row in enumerate(rotation_rows):
        magnitude_squared = sum(value * value for value in row)
        if not isclose(magnitude_squared, 1.0, abs_tol=tolerance):
            raise ValueError(f"Rotation row {row_index} is not unit length")
        for other_index in range(row_index + 1, 3):
            dot_product = sum(
                row[column] * rotation_rows[other_index][column] for column in range(3)
            )
            if not isclose(dot_product, 0.0, abs_tol=tolerance):
                raise ValueError("Rotation rows must be orthogonal")

    if not isclose(_determinant3(matrix), 1.0, abs_tol=tolerance):
        raise ValueError("Rotation must preserve a right-handed coordinate system")


def compose(parent_from_child: Matrix4, child_from_object: Matrix4) -> Matrix4:
    """Compose transforms using column-vector convention."""
    result = tuple(
        tuple(
            sum(parent_from_child[row][k] * child_from_object[k][column] for k in range(4))
            for column in range(4)
        )
        for row in range(4)
    )
    composed = matrix4(result)
    validate_rigid_transform(composed)
    return composed


def inverse_rigid(transform: Matrix4) -> Matrix4:
    validate_rigid_transform(transform)
    rotation_transpose = tuple(
        tuple(transform[column][row] for column in range(3)) for row in range(3)
    )
    translation = (transform[0][3], transform[1][3], transform[2][3])
    inverse_translation = tuple(
        -sum(rotation_transpose[row][column] * translation[column] for column in range(3))
        for row in range(3)
    )
    inverse = matrix4(
        tuple((*rotation_transpose[row], inverse_translation[row]) for row in range(3))
        + ((0.0, 0.0, 0.0, 1.0),)
    )
    validate_rigid_transform(inverse)
    return inverse


def transform_point(transform: Matrix4, point_mm: Point3) -> Point3:
    validate_rigid_transform(transform)
    homogeneous = (*point_mm, 1.0)
    values = tuple(
        sum(transform[row][column] * homogeneous[column] for column in range(4)) for row in range(3)
    )
    return values  # type: ignore[return-value]
