"""Interpolate simulation timelines without re-running IK."""

from __future__ import annotations

import bisect
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from .scene import SceneModel, SimulationState


def _bracket(keys: list[list[Any]], t: float) -> tuple[list[Any], list[Any], float]:
    if not keys:
        raise ValueError("時間軸軌跡不可為空")
    times = [float(key[0]) for key in keys]
    right = bisect.bisect_right(times, t)
    if right <= 0:
        return keys[0], keys[0], 0.0
    if right >= len(keys):
        return keys[-1], keys[-1], 0.0
    first, second = keys[right - 1], keys[right]
    span = float(second[0]) - float(first[0])
    return first, second, 0.0 if span <= 0 else (t - float(first[0])) / span


def _linear(keys: list[list[Any]], t: float) -> np.ndarray:
    first, second, ratio = _bracket(keys, t)
    a = np.asarray(first[1:], dtype=float)
    b = np.asarray(second[1:], dtype=float)
    return a + (b - a) * ratio


def _pose(keys: list[list[Any]], t: float) -> np.ndarray:
    first, second, ratio = _bracket(keys, t)
    ratio = min(1.0, max(0.0, float(ratio)))
    translation = (
        np.asarray(first[1:4], dtype=float)
        + (np.asarray(second[1:4], dtype=float) - np.asarray(first[1:4], dtype=float)) * ratio
    )
    if first is second or ratio <= 0:
        rotation = Rotation.from_quat(first[4:8]).as_matrix()
    else:
        rotations = Rotation.from_quat([first[4:8], second[4:8]])
        rotation = Slerp([0.0, 1.0], rotations)([ratio]).as_matrix()[0]
    result = np.eye(4, dtype=float)
    result[:3, :3] = rotation
    result[:3, 3] = translation
    return result


def _held(keys: list[list[Any]], t: float) -> Any:
    if not keys:
        return None
    times = [float(key[0]) for key in keys]
    index = max(0, bisect.bisect_right(times, t) - 1)
    return keys[index][1]


def state_at(timeline: dict[str, Any], t: float) -> SimulationState:
    """Return the complete articulated state at ``t`` seconds."""

    state = SimulationState()
    for name, node in timeline.get("nodes", {}).items():
        node_type = node.get("type")
        if node_type == "robot" and node.get("joints_deg"):
            state.joints[name] = _linear(node["joints_deg"], t)
        elif node_type == "pose":
            part = state.part(name)
            if node.get("pose_quat"):
                part.pose = _pose(node["pose_quat"], t)
            part.holder = _held(node.get("attached_to", []), t)
        elif node.get("value_mm"):
            state.axes[name] = float(_linear(node["value_mm"], t)[0])
        elif node.get("value_deg"):
            state.axes[name] = float(_linear(node["value_deg"], t)[0])
        elif node.get("value"):
            state.axes[name] = float(_linear(node["value"], t)[0])
    return state


def world_transforms(scene: SceneModel, state: SimulationState) -> dict[str, np.ndarray]:
    """Return world transforms for every articulated GLB link node."""

    result: dict[str, np.ndarray] = {}
    for module_name, module in scene.modules.items():
        links = scene.module_link_transforms(module_name, state)
        root_link = module.chain.base_link if module.chain is not None else "base"
        result[module_name] = links[root_link].copy()
        for axis in module.definition.axes:
            child = axis.child or axis.id
            if child in links:
                result[f"{module_name}.{axis.id}"] = links[child].copy()
        if module.chain is not None:
            # 固定關節（含 URDF 中夾在活動關節之間的）也是 GLB 節點與碰撞零件的父座標。
            for joint in module.chain.joints:
                if not joint.active and joint.child in links:
                    result[f"{module_name}.{joint.id}"] = links[joint.child].copy()
            result[f"{module_name}.tool"] = links[module.chain.tip_link].copy()
    for part_id, part in scene.parts.items():
        pose = state.part(part_id).pose
        result[part_id] = pose.copy()
        # GLB joint nodes live at the axis origin; named part frames may live
        # elsewhere on the moving link and therefore are not node transforms.
        links = scene.part_link_transforms(part_id, state)
        for axis in part.definition.axes:
            result[f"{part_id}.{axis.id}"] = links[axis.child or axis.id].copy()
    return result
