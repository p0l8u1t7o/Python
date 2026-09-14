"""Coordinate transform helpers (fixed-axis X then Y then Z)."""

from __future__ import annotations

import math

import cadquery as cq
import numpy as np


def matrix_from_pose(
    xyz: tuple[float, float, float], rpy_deg: tuple[float, float, float]
) -> np.ndarray:
    rx, ry, rz = (math.radians(value) for value in rpy_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    rot_x = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    rot_y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rot_z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    result = np.eye(4)
    result[:3, :3] = rot_z @ rot_y @ rot_x
    result[:3, 3] = xyz
    return result


def cadquery_location(
    xyz: tuple[float, float, float], rpy_deg: tuple[float, float, float]
) -> cq.Location:
    return cq.Location(tuple(xyz), tuple(rpy_deg))
