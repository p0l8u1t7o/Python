"""Serial/tree kinematic chains in CellForge millimetres and degrees."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
from scipy.spatial.transform import Rotation

JointType = Literal["revolute", "continuous", "prismatic", "fixed"]


def _transform(xyz: Sequence[float], rpy_rad: Sequence[float]) -> np.ndarray:
    result = np.eye(4, dtype=float)
    result[:3, :3] = Rotation.from_euler("xyz", rpy_rad).as_matrix()
    result[:3, 3] = np.asarray(xyz, dtype=float)
    return result


@lru_cache(maxsize=4096)
def _origin_matrix(xyz: tuple[float, ...], rpy_deg: tuple[float, ...]) -> np.ndarray:
    """關節原點是常數；IK 每次殘差都要做 FK，重算 scipy 旋轉曾占建置時間的三分之一。"""
    matrix = _transform(xyz, np.radians(rpy_deg))
    matrix.setflags(write=False)
    return matrix


def _motion(joint_type: JointType, axis: np.ndarray, value: float) -> np.ndarray:
    result = np.eye(4, dtype=float)
    if joint_type in {"revolute", "continuous"}:
        # Rodrigues 閉式解；axis 已在 Joint 建立時正規化，與 Rotation.from_rotvec 等價。
        angle = math.radians(value)
        cosine, sine = math.cos(angle), math.sin(angle)
        versine = 1.0 - cosine
        x, y, z = float(axis[0]), float(axis[1]), float(axis[2])
        result[:3, :3] = (
            (cosine + x * x * versine, x * y * versine - z * sine, x * z * versine + y * sine),
            (y * x * versine + z * sine, cosine + y * y * versine, y * z * versine - x * sine),
            (z * x * versine - y * sine, z * y * versine + x * sine, cosine + z * z * versine),
        )
    elif joint_type == "prismatic":
        result[:3, 3] = axis * value
    return result


@dataclass(frozen=True, slots=True)
class Joint:
    """A URDF-style joint; origins are mm/degrees and axes are joint-local."""

    id: str
    type: JointType
    parent: str
    child: str
    origin_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    origin_rpy_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    limit: tuple[float, float] | None = None
    max_speed: float | None = None

    def __post_init__(self) -> None:
        axis = np.asarray(self.axis, dtype=float)
        length = float(np.linalg.norm(axis))
        if self.type != "fixed" and length <= 1e-12:
            raise ValueError(f"關節 {self.id} 的軸向不可為零向量")
        if length > 0:
            object.__setattr__(self, "axis", tuple(float(v) for v in axis / length))
        if self.limit is not None and self.limit[0] > self.limit[1]:
            raise ValueError(f"關節 {self.id} 的下限不可大於上限")

    @property
    def active(self) -> bool:
        return self.type != "fixed"

    @property
    def origin(self) -> np.ndarray:
        """Read-only parent-to-joint transform (cached; do not modify in place)."""
        return _origin_matrix(tuple(self.origin_xyz), tuple(self.origin_rpy_deg))


class Chain:
    """A validated kinematic tree with FK and a geometric Jacobian."""

    def __init__(
        self,
        joints: Iterable[Joint],
        *,
        base_link: str | None = None,
        tip_link: str | None = None,
        name: str = "robot",
    ) -> None:
        self.name = name
        self.joints = tuple(joints)
        children = [joint.child for joint in self.joints]
        if len(children) != len(set(children)):
            raise ValueError("每個 link 只能由一個關節驅動")
        parents = {joint.parent for joint in self.joints}
        self.base_link = base_link or next(iter(parents - set(children)), "base")
        self.tip_link = tip_link or (self.joints[-1].child if self.joints else self.base_link)
        self._by_child = {joint.child: joint for joint in self.joints}
        self._order = self._validate_tree()
        self._axes = {joint.id: np.asarray(joint.axis, dtype=float) for joint in self.joints}

    def _validate_tree(self) -> tuple[Joint, ...]:
        """Validate connectivity and return the joints in parent-before-child order."""
        known = {self.base_link}
        remaining = list(self.joints)
        order: list[Joint] = []
        while remaining:
            ready = [joint for joint in remaining if joint.parent in known]
            if not ready:
                names = ", ".join(joint.id for joint in remaining)
                raise ValueError(f"關節鏈不連通或含循環：{names}")
            for joint in ready:
                known.add(joint.child)
                remaining.remove(joint)
                order.append(joint)
        if self.tip_link not in known:
            raise ValueError(f"末端 link 不存在：{self.tip_link}")
        return tuple(order)

    @property
    def active_joints(self) -> tuple[Joint, ...]:
        return tuple(joint for joint in self.joints if joint.active)

    @property
    def joint_names(self) -> tuple[str, ...]:
        return tuple(joint.id for joint in self.active_joints)

    @property
    def limits(self) -> np.ndarray:
        values = []
        for joint in self.active_joints:
            if joint.limit is not None:
                values.append(joint.limit)
            elif joint.type == "continuous":
                values.append((-360.0, 360.0))
            elif joint.type == "prismatic":
                values.append((-np.inf, np.inf))
            else:
                values.append((-180.0, 180.0))
        return np.asarray(values, dtype=float)

    def values_dict(self, values: Sequence[float] | dict[str, float]) -> dict[str, float]:
        if isinstance(values, dict):
            return {name: float(values.get(name, 0.0)) for name in self.joint_names}
        if len(values) != len(self.active_joints):
            raise ValueError(f"關節值數量應為 {len(self.active_joints)}，實際 {len(values)}")
        return dict(zip(self.joint_names, (float(value) for value in values), strict=True))

    def forward_kinematics(
        self, values: Sequence[float] | dict[str, float], link: str | None = None
    ) -> np.ndarray:
        return self.link_transforms(values)[link or self.tip_link].copy()

    fk = forward_kinematics

    def link_transforms(self, values: Sequence[float] | dict[str, float]) -> dict[str, np.ndarray]:
        positions = self.values_dict(values)
        result = {self.base_link: np.eye(4, dtype=float)}
        for joint in self._order:
            motion = _motion(joint.type, self._axes[joint.id], positions.get(joint.id, 0.0))
            result[joint.child] = result[joint.parent] @ joint.origin @ motion
        return result

    def geometric_jacobian(
        self, values: Sequence[float] | dict[str, float], link: str | None = None
    ) -> np.ndarray:
        """Return [linear mm/unit; angular rad/unit] for active ancestors of ``link``."""

        target_link = link or self.tip_link
        positions = self.values_dict(values)
        transforms = self.link_transforms(positions)
        end = transforms[target_link][:3, 3]
        ancestors: set[str] = set()
        cursor = target_link
        while cursor != self.base_link:
            joint = self._by_child.get(cursor)
            if joint is None:
                break
            ancestors.add(joint.id)
            cursor = joint.parent
        jacobian = np.zeros((6, len(self.active_joints)), dtype=float)
        for column, joint in enumerate(self.active_joints):
            if joint.id not in ancestors:
                continue
            joint_frame = transforms[joint.parent] @ joint.origin
            axis_world = joint_frame[:3, :3] @ np.asarray(joint.axis)
            if joint.type in {"revolute", "continuous"}:
                # Input API uses degrees, so both derivatives are per degree.
                scale = math.pi / 180.0
                jacobian[:3, column] = np.cross(axis_world, end - joint_frame[:3, 3]) * scale
                jacobian[3:, column] = axis_world * scale
            else:
                jacobian[:3, column] = axis_world
        return jacobian

    @classmethod
    def from_urdf(cls, path: str | Path, *, tip_link: str | None = None) -> Chain:
        """Load URDF metres/radians and convert to CellForge mm/degrees."""

        root = ET.parse(path).getroot()
        joints: list[Joint] = []
        for element in root.findall("joint"):
            joint_type = element.get("type", "fixed")
            if joint_type not in {"revolute", "continuous", "prismatic", "fixed"}:
                raise ValueError(f"不支援的 URDF 關節型別：{joint_type}")
            parent = element.find("parent")
            child = element.find("child")
            if parent is None or child is None:
                raise ValueError("URDF 關節缺少 parent 或 child")
            origin = element.find("origin")
            xyz_m = _numbers(origin.get("xyz") if origin is not None else None, (0, 0, 0))
            rpy_rad = _numbers(origin.get("rpy") if origin is not None else None, (0, 0, 0))
            axis_element = element.find("axis")
            axis = _numbers(
                axis_element.get("xyz") if axis_element is not None else None, (1, 0, 0)
            )
            limit_element = element.find("limit")
            limit: tuple[float, float] | None = None
            speed: float | None = None
            if limit_element is not None and joint_type != "fixed":
                lower = float(limit_element.get("lower", "-inf"))
                upper = float(limit_element.get("upper", "inf"))
                velocity = limit_element.get("velocity")
                if joint_type == "continuous":
                    # URDF 規範：continuous 關節忽略 lower／upper，只保留速度。
                    speed = math.degrees(float(velocity)) if velocity else None
                elif joint_type == "revolute":
                    limit = (math.degrees(lower), math.degrees(upper))
                    speed = math.degrees(float(velocity)) if velocity else None
                else:
                    limit = (lower * 1000.0, upper * 1000.0)
                    speed = float(velocity) * 1000.0 if velocity else None
            joints.append(
                Joint(
                    id=element.get("name", f"joint_{len(joints)}"),
                    type=joint_type,
                    parent=parent.get("link", ""),
                    child=child.get("link", ""),
                    origin_xyz=tuple(value * 1000.0 for value in xyz_m),
                    origin_rpy_deg=tuple(math.degrees(value) for value in rpy_rad),
                    axis=axis,
                    limit=limit,
                    max_speed=speed,
                )
            )
        return cls(joints, tip_link=tip_link, name=root.get("name", Path(path).stem))


def _numbers(value: str | None, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if not value:
        return default
    parsed = tuple(float(part) for part in value.split())
    if len(parsed) != 3:
        raise ValueError(f"向量應有三個數值：{value}")
    return parsed


def transform_error(actual: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    """Return translation error in mm and shortest rotation error in degrees."""

    position = float(np.linalg.norm(actual[:3, 3] - target[:3, 3]))
    relative = target[:3, :3] @ actual[:3, :3].T
    orientation = math.degrees(float(np.linalg.norm(Rotation.from_matrix(relative).as_rotvec())))
    return position, orientation
