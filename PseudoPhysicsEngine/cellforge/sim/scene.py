"""Runtime scene model and named-frame resolution."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation

from cellforge.build.modules import BuiltModule
from cellforge.schema.base import CameraSpec, ModuleAxis, ModuleDef
from cellforge.schema.models import Cell

from .workpiece import PRIMARY_PART, BuiltWorkpiece


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
class PartState:
    """一個零件在某時刻的世界位姿與唯一持有者；被帶著走時記錄相對持有者的位姿。"""

    pose: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=float))
    holder: str | None = None
    relative: np.ndarray | None = None

    def copy(self) -> PartState:
        return PartState(
            self.pose.copy(),
            self.holder,
            None if self.relative is None else self.relative.copy(),
        )


@dataclass(slots=True)
class SimulationState:
    joints: dict[str, np.ndarray] = field(default_factory=dict)
    axes: dict[str, float] = field(default_factory=dict)
    parts: dict[str, PartState] = field(default_factory=dict)

    def part(self, part_id: str = PRIMARY_PART) -> PartState:
        return self.parts.setdefault(part_id, PartState())

    # 單一工件案例的相容存取（id workpiece）。
    @property
    def workpiece_pose(self) -> np.ndarray:
        return self.part().pose

    @workpiece_pose.setter
    def workpiece_pose(self, value: np.ndarray) -> None:
        self.part().pose = value

    @property
    def attached_to(self) -> str | None:
        return self.part().holder

    @attached_to.setter
    def attached_to(self, value: str | None) -> None:
        self.part().holder = value

    @property
    def attachment_relative(self) -> np.ndarray | None:
        return self.part().relative

    @attachment_relative.setter
    def attachment_relative(self, value: np.ndarray | None) -> None:
        self.part().relative = value

    def copy(self) -> SimulationState:
        return SimulationState(
            joints={name: values.copy() for name, values in self.joints.items()},
            axes=dict(self.axes),
            parts={name: part.copy() for name, part in self.parts.items()},
        )


class SceneModel:
    """Articulated modules and product parts in plant/world coordinates."""

    def __init__(
        self,
        cell: Cell,
        modules: list[BuiltModule],
        workpiece: BuiltWorkpiece | Iterable[BuiltWorkpiece],
    ) -> None:
        self.cell = cell
        self.modules = {module.instance.id: module for module in modules}
        parts = [workpiece] if isinstance(workpiece, BuiltWorkpiece) else list(workpiece)
        if not parts:
            raise ValueError("場景至少需要一個工件或零件")
        self.parts: dict[str, BuiltWorkpiece] = {part.id: part for part in parts}
        clash = sorted(set(self.parts) & set(self.modules))
        if clash:
            raise ValueError(f"零件 id 與模組 id 重複：{', '.join(clash)}")
        # 手臂工具模組的定義（frame 與相機）；在建立場景時載入，案內 parts/ 工具需要案子根目錄。
        self._tools: dict[str, ModuleDef | Exception | None] = {
            name: _load_tool_definition(module) for name, module in self.robots.items()
        }
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
            | {
                f"{part_id}.{axis.id}": float(part.state.get(axis.id, 0.0))
                for part_id, part in self.parts.items()
                for axis in part.definition.axes
            },
            parts={part_id: PartState() for part_id in self.parts},
        )

    @property
    def workpiece(self) -> BuiltWorkpiece:
        """主工件：單一工件案例的 workpiece；多零件產品取第一個零件（僅供舊流程相容）。"""
        return self.parts.get(PRIMARY_PART) or next(iter(self.parts.values()))

    def part_axis(self, name: str) -> tuple[str, ModuleAxis] | None:
        part_id, _, suffix = name.partition(".")
        part = self.parts.get(part_id)
        if part is None:
            return None
        axis = next((item for item in part.definition.axes if item.id == suffix), None)
        return None if axis is None else (part_id, axis)

    @property
    def robots(self) -> dict[str, BuiltModule]:
        return {name: module for name, module in self.modules.items() if module.chain is not None}

    def actor_exists(self, name: str) -> bool:
        if name in {"system", *self.modules, *self.parts}:
            return True
        if self.part_axis(name) is not None:
            return True
        module_name, _, suffix = name.partition(".")
        module = self.modules.get(module_name)
        if module is None:
            return False
        if suffix in {axis.id for axis in module.definition.axes}:
            return True
        if module.chain is None:
            return False
        tool = self._tools.get(module_name)
        tool_frames = set(tool.frames) if isinstance(tool, ModuleDef) else set()
        return suffix in {"tool", "camera", "grip", *tool_frames}

    def tool_definition(self, robot: str) -> ModuleDef | None:
        tool = self._tools.get(robot)
        if isinstance(tool, Exception):
            raise ValueError(f"手臂 {robot} 的工具模組無法載入：{tool}") from tool
        return tool

    def camera(self, name: str, state: SimulationState) -> tuple[np.ndarray, CameraSpec]:
        """World pose and optics of a camera frame (fixed module or robot tool)."""
        owner, _, frame = name.partition(".")
        module = self.modules.get(owner)
        if module is None:
            raise KeyError(f"不存在的相機：{name}")
        spec = module.definition.cameras.get(frame)
        if spec is None and module.chain is not None:
            tool = self.tool_definition(owner)
            spec = tool.cameras.get(frame) if tool is not None else None
        if spec is None:
            raise KeyError(f"{name} 不是相機 frame（模組或工具沒有宣告 cameras）")
        return self.resolve_frame(name, state), spec

    def tool_mount_to_frame(self, robot: str, frame: str) -> np.ndarray:
        """Transform from the robot TCP (chain tool link) to a frame of its tool module."""
        tool = self.tool_definition(robot)
        if tool is None or frame not in tool.frames:
            raise KeyError(f"手臂 {robot} 的工具沒有 frame：{frame}")
        tcp = tool.frames.get("tool_center_point")
        tcp_matrix = np.eye(4) if tcp is None else transform(tcp.xyz, tcp.rpy_deg)
        target = tool.frames[frame]
        return np.linalg.inv(tcp_matrix) @ transform(target.xyz, target.rpy_deg)

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

    def part_link_transforms(self, part_id: str, state: SimulationState) -> dict[str, np.ndarray]:
        """World transform of every link of one part (base plus state/cover axes)."""

        result = {"base": state.part(part_id).pose}
        remaining = list(self.parts[part_id].definition.axes)
        while remaining:
            ready = [axis for axis in remaining if axis.parent in result]
            if not ready:
                raise ValueError(f"零件 {part_id} 的狀態軸階層無法解析")
            for axis in ready:
                origin = transform(axis.origin.xyz, axis.origin.rpy_deg)
                value = state.axes.get(f"{part_id}.{axis.id}", 0.0)
                result[axis.child or axis.id] = result[axis.parent] @ origin @ motion(axis, value)
                remaining.remove(axis)
        return result

    def _part_rest_links(self, part_id: str) -> dict[str, np.ndarray]:
        """Link frames of a part in its own module coordinates at the zero pose."""
        rest = SimulationState(parts={part_id: PartState()})
        return self.part_link_transforms(part_id, rest)

    def _part_frame(self, part_id: str, suffix: str, state: SimulationState) -> np.ndarray:
        part = self.parts[part_id]
        definition = part.definition
        if part.sku is None:
            # 零件模組：frame 以模組座標（靜止姿態）表示，隨所屬 link 移動；
            # 與零件品質檢查的包圍盒規則及 SKU 零件的 frame 語意一致。
            links = self.part_link_transforms(part_id, state)
            frame = definition.frames.get(suffix)
            if frame is None:
                if suffix in links:
                    return links[suffix].copy()
                raise KeyError(f"不存在的零件 frame：{part_id}.{suffix}")
            parent = frame.link or "base"
            if parent not in links:
                raise KeyError(f"零件 frame {part_id}.{suffix} 引用不存在的 link：{parent}")
            rest = self._part_rest_links(part_id)
            return links[parent] @ np.linalg.inv(rest[parent]) @ transform(frame.xyz, frame.rpy_deg)
        frame = definition.frames.get(suffix or "workpiece")
        if frame is None:
            raise KeyError(f"不存在的工件 frame：{part_id}.{suffix}")
        local = transform(frame.xyz, frame.rpy_deg)
        for axis in definition.axes:
            if suffix == axis.id or suffix.startswith(f"{axis.id}."):
                origin = transform(axis.origin.xyz, axis.origin.rpy_deg)
                value = state.axes.get(f"{part_id}.{axis.id}", 0.0)
                local = origin @ motion(axis, value) @ np.linalg.inv(origin) @ local
                break
        return state.part(part_id).pose @ local

    def resolve_frame(self, name: str, state: SimulationState) -> np.ndarray:
        if name in self.parts:
            return state.part(name).pose.copy()
        part_id, _, part_suffix = name.partition(".")
        if part_id in self.parts:
            return self._part_frame(part_id, part_suffix, state)
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
        if frame is None and module.chain is not None:
            tool = self.tool_definition(module_name)
            if tool is not None and suffix in tool.frames:
                # 工具模組的 frame 以工具安裝座為原點；手臂鏈的 tool link 即工具的 TCP。
                return links[module.chain.tip_link] @ self.tool_mount_to_frame(module_name, suffix)
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
        owner = frame_name.partition(".")[0]
        if owner in self.parts:
            return owner
        if frame_name.startswith(PRIMARY_PART) and PRIMARY_PART in self.parts:
            return PRIMARY_PART
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


def _load_tool_definition(module: BuiltModule) -> ModuleDef | Exception | None:
    tool = module.instance.params.get("tool")
    if not isinstance(tool, dict) or not tool.get("part"):
        return None
    from cellforge.build.modules import load_part

    try:
        loaded = load_part(str(tool["part"]))
        factory = getattr(loaded, "module_definition", None)
        params = dict(tool.get("params", {}))
        return factory(params) if callable(factory) else loaded.MODULE
    except (ImportError, AttributeError, OSError, ValueError) as error:
        return error
