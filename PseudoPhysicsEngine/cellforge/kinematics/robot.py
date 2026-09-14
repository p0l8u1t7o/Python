"""Small URDF reader used by checks without requiring a native IK runtime."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class RobotDescription:
    name: str
    reach_mm: float
    payload_kg: float
    joint_limits_deg: list[tuple[float, float]] = field(default_factory=list)

    def reachable(self, xyz_mm: tuple[float, float, float]) -> bool:
        return math.dist((0.0, 0.0, 0.0), xyz_mm) <= self.reach_mm

    def joints_within_limits(self, joints_deg: list[float]) -> bool:
        return len(joints_deg) <= len(self.joint_limits_deg) and all(
            low <= value <= high
            for value, (low, high) in zip(joints_deg, self.joint_limits_deg, strict=False)
        )


def load_robot_description(
    path: Path, *, reach_mm: float = 905, payload_kg: float = 7
) -> RobotDescription:
    root = ET.parse(path).getroot()
    limits: list[tuple[float, float]] = []
    for joint in root.findall("joint"):
        if joint.get("type") == "fixed":
            continue
        limit = joint.find("limit")
        if limit is None:
            limits.append((-180.0, 180.0))
            continue
        lower = math.degrees(float(limit.get("lower", str(-math.pi))))
        upper = math.degrees(float(limit.get("upper", str(math.pi))))
        limits.append((round(lower, 6), round(upper, 6)))
    return RobotDescription(root.get("name", path.stem), reach_mm, payload_kg, limits)
