"""Runtime scene model and named-frame resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation

from cellforge.build.modules import BuiltModule
from cellforge.schema.base import ModuleAxis
from cellforge.schema.models import Cell

from .workpiece import BuiltWorkpiece


def transform(xyz=(0.0, 0.0, 0.0), rpy_deg=(0.0, 0.0, 0.0)) -> np.ndarray:
    result = np.eye(4, dtype=float)
    result[:3, :3] = Rotation.from_euler("xyz", rpy_deg, degrees=True).as_matrix()
    result[:3, 3] = np.asarray(xyz, dtype=float)
    return result


def motion(axis: ModuleAxis, value: float) -> np.ndarray:
    result = np.eye(4, dtype=float)
    direction = np.asarray(axis.axis, dtype=float)
    direction /= np.linalg.norm(direction)
    if axis.type == "revolute":
        result[:3, :3] = Rotation.from_rotvec(direction * np.radians(value)).as_matrix()
    else:
        result[:3, 3] = direction * value
    return result


@dataclass(slots=True)
class SimulationState:
    joints: dict[str, np.ndarray] = field(default_factory=dict)
    axes: dict[str, float] = field(default_factory=dict)
    workpiece_pose: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=float))
    attached_to: str | None = None
    attachment_relative: np.ndarray | None = None

    def copy(self) -> SimulationState:
        return SimulationState(
            joints={name: values.copy() for name, values in self.joints.items()},
            axes=dict(self.axes),
            workpiece_pose=self.workpiece_pose.copy(),
            attached_to=self.attached_to,
            attachment_relative=(
                None if self.attachment_relative is None else self.attachment_relative.copy()
            ),
        )


class SceneModel:
    """Articulated modules and workpiece in plant/world coordinates."""

    def __init__(self, cell: Cell, modules: list[BuiltModule], workpiece: BuiltWorkpiece) -> None:
        self.cell = cell
        self.modules = {module.instance.id: module for module in modules}
        self.workpiece = workpiece
        self.module_poses: dict[str, np.ndarray] = {}
        for machine in cell.machines:
            machine_pose = transform(machine.pose.xyz, machine.pose.rpy_deg)
            for instance in machine.modules:
                self.module_poses[instance.id] = machine_pose @ transform(
                    instance.pose.xyz, instance.pose.rpy_deg
                )

    def initial_state(self) -> SimulationState:
        return SimulationState(
            joints={
                name: np.zeros(len(module.chain.active_joints), dtype=float)
                for name, module in self.modules.items()
                if module.chain is not None
            },
            axes={
                f"{name}.{axis.id}": 0.0
                for name, module in self.modules.items()
                for axis in module.definition.axes
                if module.chain is None
            }
            | {f"workpiece.{axis.id}": 0.0 for axis in self.workpiece.definition.axes},
        )

    @property
    def robots(self) -> dict[str, BuiltModule]:
        return {name: module for name, module in self.modules.items() if module.chain is not None}

    def actor_exists(self, name: str) -> bool:
        if name in {"system", "workpiece", *self.modules}:
            return True
        if name.startswith("workpiece."):
            return any(
                axis.id == name.removeprefix("workpiece.")
                for axis in self.workpiece.definition.axes
            )
        module_name, _, suffix = name.partition(".")
        module = self.modules.get(module_name)
        if module is None:
            return False
        return suffix in {axis.id for axis in module.definition.axes} or (
            module.chain is not None and suffix in {"tool", "camera", "grip"}
        )

    def frame_exists(self, name: str) -> bool:
        try:
            self.resolve_frame(name, self.initial_state())
        except (KeyError, ValueError):
            return False
        return True

    def module_link_transforms(
        self, module_name: str, state: SimulationState
    ) -> dict[str, np.ndarray]:
        module = self.modules[module_name]
        root = self.module_poses[module_name]
        if module.chain is not None:
            values = state.joints.get(module_name, np.zeros(len(module.chain.active_joints)))
            return {
                link: root @ local for link, local in module.chain.link_transforms(values).items()
            }
        result = {"base": root}
        remaining = list(module.definition.axes)
        while remaining:
            progressed = False
            for axis in list(remaining):
                if axis.parent not in result:
                    continue
                origin = transform(axis.origin.xyz, axis.origin.rpy_deg)
                value = state.axes.get(f"{module_name}.{axis.id}", 0.0)
                result[axis.child or axis.id] = result[axis.parent] @ origin @ motion(axis, value)
                remaining.remove(axis)
                progressed = True
            if not progressed:
                raise ValueError(f"模組 {module_name} 的關節階層無法解析")
        return result

    def _workpiece_frame(self, suffix: str, state: SimulationState) -> np.ndarray:
        definition = self.workpiece.definition
        frame = definition.frames.get(suffix or "workpiece")
        if frame is None:
            raise KeyError(f"不存在的工件 frame：workpiece.{suffix}")
        local = transform(frame.xyz, frame.rpy_deg)
        for axis in definition.axes:
            if suffix == axis.id or suffix.startswith(f"{axis.id}."):
                origin = transform(axis.origin.xyz, axis.origin.rpy_deg)
                value = state.axes.get(f"workpiece.{axis.id}", 0.0)
                local = origin @ motion(axis, value) @ np.linalg.inv(origin) @ local
                break
        return state.workpiece_pose @ local

    def resolve_frame(self, name: str, state: SimulationState) -> np.ndarray:
        if name == "workpiece":
            return state.workpiece_pose.copy()
        if name.startswith("workpiece."):
            return self._workpiece_frame(name.removeprefix("workpiece."), state)
        module_name, separator, suffix = name.partition(".")
        module = self.modules.get(module_name)
        if module is None:
            raise KeyError(f"不存在的模組或 frame：{name}")
        if not separator:
            return self.module_poses[module_name].copy()
        links = self.module_link_transforms(module_name, state)
        if module.chain is not None and suffix in {"tool", *links}:
            return links[suffix].copy()
        frame = module.definition.frames.get(suffix)
        if frame is None:
            raise KeyError(f"不存在的 frame：{name}")
        if module.chain is not None and suffix == "flange":
            parent = module.chain.active_joints[-1].child
            rest = module.chain.link_transforms(np.zeros(len(module.chain.active_joints)))
            return links[parent] @ np.linalg.inv(rest[parent]) @ transform(frame.xyz, frame.rpy_deg)
        parent = getattr(frame, "link", None) or "base"
        if parent not in links:
            raise KeyError(f"frame {name} 引用不存在的 link：{parent}")
        return links[parent] @ transform(frame.xyz, frame.rpy_deg)

    def frame_owner(self, frame_name: str) -> str | None:
        if frame_name.startswith("workpiece"):
            return "workpiece"
        owner = frame_name.partition(".")[0]
        return owner if owner in self.modules else None

    def robot_target(self, actor: str, world: np.ndarray) -> np.ndarray:
        return np.linalg.inv(self.module_poses[actor]) @ world

    def frame_target(
        self, target: dict[str, Any], state: SimulationState, *, tool: bool
    ) -> np.ndarray:
        if "frame" in target:
            result = self.resolve_frame(str(target["frame"]), state)
            offset = target.get("offset") or {}
            result = result @ transform(
                offset.get("xyz", (0, 0, 0)), offset.get("rpy_deg", (0, 0, 0))
            )
        else:
            result = transform(target.get("xyz", (0, 0, 0)), target.get("rpy_deg", (0, 0, 0)))
        if tool:
            result = result @ transform(rpy_deg=(180, 0, 0))
        return result
