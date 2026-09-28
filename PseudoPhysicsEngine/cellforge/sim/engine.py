"""Deterministic first-article simulation engine."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from cellforge.kinematics import solve_ik
from cellforge.schema.models import PartPlacement, ProcessStep

from .sampling import state_at
from .scene import SceneModel, transform
from .workpiece import PRIMARY_PART

SAMPLE_PERIOD_S = 0.1
# 直線移動依關節速度推導時長時，每輪最多放大的倍數；連續路徑幾輪內就會收斂。
LINEAR_DURATION_GROWTH = 4.0
# 連續路徑的最大單段關節變化會隨取樣加密倍數等比縮小，IK 解支跳躍則維持不變；
# 加密至少這麼多倍時才比較兩者，門檻取兩種情況的幾何中點（前一輪 ÷ √加密倍數）。
LINEAR_MIN_REFINEMENT = 1.5


def _sample_times(t0: float, t1: float) -> list[float]:
    if t1 <= t0:
        return [t0]
    count = max(1, math.ceil((t1 - t0) / SAMPLE_PERIOD_S))
    # 末點直接沿用原始 t1：以 (t1 - t0) * count / count 反推會有浮點漂移，
    # 使 ratio 變成 1.0000000000000002 而被 SciPy 的 Slerp 拒絕。
    times = [t0 + (t1 - t0) * index / count for index in range(count)]
    times.append(t1)
    return times


def _clamp_ratio(ratio: float) -> float:
    """把內插比例夾在 [0, 1]，避免呼叫端的浮點誤差讓 Slerp 直接丟例外。"""

    value = float(ratio)
    if not math.isfinite(value):
        raise ValueError(f"內插比例必須是有限數值，收到 {ratio!r}")
    return min(1.0, max(0.0, value))


def _interpolate_pose(first: np.ndarray, second: np.ndarray, ratio: float) -> np.ndarray:
    ratio = _clamp_ratio(ratio)
    result = np.eye(4, dtype=float)
    result[:3, 3] = first[:3, 3] + (second[:3, 3] - first[:3, 3]) * ratio
    rotations = Rotation.from_matrix([first[:3, :3], second[:3, :3]])
    result[:3, :3] = Slerp([0.0, 1.0], rotations)([ratio]).as_matrix()[0]
    return result


class Simulator:
    def __init__(self, scene: SceneModel, *, fps: int = 50) -> None:
        self.scene = scene
        self.fps = fps
        self.state = scene.initial_state()
        self.nodes: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.steps: list[dict[str, Any]] = []
        self.ik_failures: list[dict[str, Any]] = []
        self.path_discontinuities: list[dict[str, Any]] = []
        self.action_results: list[dict[str, Any]] = []
        self.station_ranges: dict[str, list[float]] = {}
        self.duration_s = 0.0
        self._initialize_tracks()

    def _initialize_tracks(self) -> None:
        for name, module in self.scene.robots.items():
            joints = self.state.joints[name]
            self.nodes[name] = {
                "type": "robot",
                "joint_names": list(module.chain.joint_names),
                "joints_deg": [[0.0, *joints.tolist()]],
            }
        for name, value in self.state.axes.items():
            axis = self._axis(name)
            key = "value_deg" if axis.type == "revolute" else "value_mm"
            self.nodes[name] = {"type": axis.type, key: [[0.0, value]]}
        for part_id in self.scene.parts:
            self.nodes[part_id] = {
                "type": "pose",
                "attached_to": [[0.0, None]],
                "pose": [],
                "pose_quat": [],
            }
            self._append_pose(0.0, self.state.part(part_id).pose, part_id)

    def initialize_workpiece(self, frame_name: str | None) -> None:
        """Legacy entry point: place the primary workpiece at ``frame_name``."""
        if frame_name:
            self._place(PRIMARY_PART, PartPlacement(frame=frame_name))

    def initialize_parts(self, legacy_frame: str | None = None) -> None:
        """Place every part at its declared initial frame, holders before the parts they hold.

        ``legacy_frame`` is ``process.initial_workpiece_frame`` for scenes whose primary
        workpiece was built without a process.
        """

        primary = self.scene.parts.get(PRIMARY_PART)
        if primary is not None and primary.initial is None and legacy_frame:
            primary.initial = PartPlacement(frame=legacy_frame)
        pending = [part for part in self.scene.parts.values() if part.initial is not None]
        placed = {part.id for part in self.scene.parts.values() if part.initial is None}
        while pending:
            ready = [
                part
                for part in pending
                if (owner := self.scene.frame_owner(part.initial.frame)) not in self.scene.parts
                or owner in placed
            ]
            if not ready:
                names = "、".join(part.id for part in pending)
                raise ValueError(f"零件初始位置互相引用成環：{names}")
            for part in ready:
                self._place(part.id, part.initial)
                placed.add(part.id)
                pending.remove(part)

    def _place(self, part_id: str, placement: PartPlacement) -> None:
        pose = self.scene.resolve_frame(placement.frame, self.state)
        offset = placement.offset
        if any(offset.xyz) or any(offset.rpy_deg):
            pose = pose @ transform(offset.xyz, offset.rpy_deg)
        state = self.state.part(part_id)
        state.pose = pose
        state.holder = self.scene.frame_owner(placement.frame)
        state.relative = self._relative_to_holder(part_id)
        node = self.nodes[part_id]
        node["pose"].clear()
        node["pose_quat"].clear()
        node["attached_to"] = [[0.0, state.holder]]
        self._append_pose(0.0, pose, part_id)

    def _object(self, step: ProcessStep) -> str:
        """The part a step acts on; single-part projects default to that part."""
        if step.object:
            if step.object not in self.scene.parts:
                raise ValueError(f"步驟 {step.id} 的 object 不是零件：{step.object}")
            return step.object
        if PRIMARY_PART in self.scene.parts:
            return PRIMARY_PART
        if len(self.scene.parts) == 1:
            return next(iter(self.scene.parts))
        raise ValueError(f"步驟 {step.id} 作用於零件，必須以 object 指定零件 id")

    def _holder_frame(self, holder: str | None) -> np.ndarray | None:
        """World frame that carries a held part (robot tool or another part)."""
        if not holder:
            return None
        if holder in self.scene.parts:
            return self.state.part(holder).pose
        robot, _, suffix = holder.partition(".")
        if robot in self.scene.robots and suffix == "tool":
            return self.scene.resolve_frame(holder, self.state)
        return None

    def _relative_to_holder(self, part_id: str) -> np.ndarray | None:
        state = self.state.part(part_id)
        frame = self._holder_frame(state.holder)
        return None if frame is None else np.linalg.inv(frame) @ state.pose

    def _carry(self, t: float, moved: set[str]) -> None:
        """Move every part held (directly or through other parts) by a moved holder."""
        frontier = set(moved)
        while frontier:
            following = set()
            for part_id in self.scene.parts:
                state = self.state.part(part_id)
                if state.holder not in frontier or state.relative is None:
                    continue
                frame = self._holder_frame(state.holder)
                if frame is None:
                    continue
                state.pose = frame @ state.relative
                self._append_pose(t, state.pose, part_id)
                following.add(part_id)
            frontier = following

    def _axis(self, name: str):
        found = self.scene.part_axis(name)
        if found is not None:
            return found[1]
        module_name, _, suffix = name.partition(".")
        module = self.scene.modules.get(module_name)
        axes = [] if module is None else module.definition.axes
        for axis in axes:
            if axis.id == suffix:
                return axis
        raise ValueError(f"不存在的模組軸：{name}")

    def _restore(self, t: float) -> None:
        sampled = state_at(self.timeline(), t)
        defaults = self.scene.initial_state()
        defaults.joints.update(sampled.joints)
        defaults.axes.update(sampled.axes)
        for part_id in self.scene.parts:
            source = sampled.part(part_id)
            target = defaults.part(part_id)
            target.pose = source.pose
            target.holder = source.holder
        self.state = defaults
        # 持有者先於被持有者還原，相對位姿才以持有者當下的 frame 計算。
        for part_id in self.scene.parts:
            self.state.part(part_id).relative = self._relative_to_holder(part_id)

    @staticmethod
    def _append(track: list[list[Any]], key: list[Any]) -> None:
        if track and abs(float(track[-1][0]) - float(key[0])) < 1e-9:
            track[-1] = key
        else:
            track.append(key)

    def _append_pose(self, t: float, pose: np.ndarray, part_id: str = PRIMARY_PART) -> None:
        quaternion = Rotation.from_matrix(pose[:3, :3]).as_quat()
        rpy = Rotation.from_matrix(pose[:3, :3]).as_euler("xyz", degrees=True)
        self._append(
            self.nodes[part_id]["pose"],
            [float(t), *pose[:3, 3].tolist(), *rpy.tolist()],
        )
        self._append(
            self.nodes[part_id]["pose_quat"],
            [float(t), *pose[:3, 3].tolist(), *quaternion.tolist()],
        )

    def _append_attached(self, t: float, target: str | None, part_id: str = PRIMARY_PART) -> None:
        self._append(self.nodes[part_id]["attached_to"], [float(t), target])
        self.state.part(part_id).holder = target

    def _append_joints(self, actor: str, t: float, joints: np.ndarray) -> None:
        self._append(self.nodes[actor]["joints_deg"], [float(t), *joints.tolist()])
        self.state.joints[actor] = joints.copy()
        self._carry(t, {f"{actor}.tool"})

    def _append_axis(self, actor: str, t: float, value: float) -> None:
        node = self.nodes[actor]
        key = "value_deg" if "value_deg" in node else "value_mm"
        self._append(node[key], [float(t), float(value)])
        self.state.axes[actor] = float(value)

    def _record_ik(self, step_id: str, t: float, result) -> None:
        if result.success:
            return
        self.ik_failures.append(
            {
                "step_id": step_id,
                "t": float(t),
                "position_error_mm": result.position_error_mm,
                "orientation_error_deg": result.orientation_error_deg,
                "nearest_distance_mm": result.nearest_distance_mm,
            }
        )

    def _solve(
        self,
        step_id: str,
        actor: str,
        target: np.ndarray,
        t: float,
        *,
        record: bool = True,
    ) -> np.ndarray:
        result = self._solve_result(step_id, actor, target)
        if record:
            self._record_ik(step_id, t, result)
        return result.joints

    def _solve_result(self, step_id: str, actor: str, target: np.ndarray):
        module = self.scene.robots.get(actor)
        if module is None:
            raise ValueError(f"步驟 {step_id} 的 actor 不是手臂：{actor}")
        result = solve_ik(
            module.chain,
            self.scene.robot_target(actor, target),
            self.state.joints[actor],
            max_nfev=180,
            seed_count=2,
        )
        return result

    def _joint_duration(
        self, actor: str, start: np.ndarray, end: np.ndarray, speed_scale: float
    ) -> float:
        if speed_scale <= 0:
            raise ValueError("speed_scale 必須大於零")
        speeds = self._joint_speeds(actor)
        return float(np.max(np.abs(end - start) / (speeds * speed_scale)))

    def _joint_speeds(self, actor: str) -> np.ndarray:
        joints = self.scene.robots[actor].chain.active_joints
        missing = [joint.id for joint in joints if joint.max_speed is None]
        if missing:
            raise ValueError(f"手臂 {actor} 的關節缺少最大速度：{', '.join(missing)}")
        return np.asarray([joint.max_speed for joint in joints], dtype=float)

    def _move_joints(
        self,
        step_id: str,
        actor: str,
        goal: np.ndarray,
        t0: float,
        duration_s: float | None,
        speed_scale: float = 0.5,
    ) -> float:
        start = self.state.joints[actor].copy()
        duration = (
            self._joint_duration(actor, start, goal, speed_scale)
            if duration_s is None
            else duration_s
        )
        t1 = t0 + max(0.0, float(duration))
        for t in _sample_times(t0, t1):
            ratio = 1.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            smooth = ratio * ratio * (3.0 - 2.0 * ratio)
            self._append_joints(actor, t, start + (goal - start) * smooth)
        return t1

    def _move_to(self, step: ProcessStep, t0: float) -> float:
        target = self.scene.frame_target(step.target or {}, self.state, tool=True)
        linear = isinstance(step.value, dict) and bool(step.value.get("linear"))
        speed_scale = (
            float(step.value.get("speed_scale", 0.5)) if isinstance(step.value, dict) else 0.5
        )
        return self._move_pose(
            step.id,
            step.actor,
            target,
            t0,
            linear=linear,
            duration_s=step.duration_s,
            speed_scale=speed_scale,
        )

    def _move_pose(
        self,
        step_id: str,
        actor: str,
        target: np.ndarray,
        t0: float,
        *,
        linear: bool,
        duration_s: float | None = None,
        speed_scale: float = 0.5,
    ) -> float:
        """Move ``actor``'s TCP to the world pose ``target`` (joint-interpolated or linear)."""
        if not linear:
            goal = self._solve(step_id, actor, target, t0)
            return self._move_joints(step_id, actor, goal, t0, duration_s, speed_scale)
        start_pose = self.scene.resolve_frame(f"{actor}.tool", self.state)
        endpoint = self._solve(step_id, actor, target, t0, record=False)
        derive_duration = duration_s is None
        initial_duration = (
            duration_s
            if duration_s is not None
            else self._joint_duration(actor, self.state.joints[actor], endpoint, speed_scale)
        )
        duration = max(0.0, float(initial_duration))
        start_joints = self.state.joints[actor].copy()
        speeds = self._joint_speeds(actor)
        plan = []
        previous: tuple[float, float] | None = None
        for _attempt in range(5 if derive_duration else 1):
            local_times = _sample_times(0.0, duration)
            seed = start_joints.copy()
            plan = []
            for local_t in local_times:
                ratio = 1.0 if duration <= 0 else local_t / duration
                desired = _interpolate_pose(start_pose, target, ratio)
                self.state.joints[actor] = seed
                result = self._solve_result(step_id, actor, desired)
                seed = result.joints
                plan.append((ratio, result))
            required = duration
            jump = 0.0
            jump_at: tuple[float, int, float] | None = None
            for (ratio_a, result_a), (ratio_b, result_b) in zip(plan, plan[1:], strict=False):
                ratio_span = ratio_b - ratio_a
                if ratio_span <= 1e-12:
                    continue
                change = np.abs(result_b.joints - result_a.joints)
                segment = np.max(change / (speeds * speed_scale * ratio_span))
                required = max(required, float(segment))
                joint_index = int(np.argmax(change))
                if float(change[joint_index]) > jump:
                    jump = float(change[joint_index])
                    jump_at = (ratio_b, joint_index, jump)
            if not derive_duration or required <= duration * (1.0 + 1e-9):
                break
            refinement = duration / previous[0] if previous and previous[0] > 0 else 1.0
            if (
                previous is not None
                and refinement >= LINEAR_MIN_REFINEMENT
                and jump >= previous[1] / math.sqrt(refinement)
            ):
                # 取樣加密後最大關節跳變沒有隨之縮小：直線路徑在 IK 解支之間跳躍，拉長時長只會
                # 讓取樣數無限增加（DEV-006 實測 29→404→5594 秒）。停止推導並記錄具體原因。
                assert jump_at is not None
                ratio_b, joint_index, change_deg = jump_at
                self.path_discontinuities.append(
                    {
                        "step_id": step_id,
                        "t": float(t0 + ratio_b * duration),
                        "joint": self.scene.robots[actor].chain.joint_names[joint_index],
                        "jump_deg": change_deg,
                    }
                )
                break
            previous = (duration, jump)
            duration = min(required, duration * LINEAR_DURATION_GROWTH)
        t1 = t0 + duration
        self.state.joints[actor] = start_joints
        for ratio, result in plan:
            t = t0 + ratio * duration
            self._record_ik(step_id, t, result)
            self._append_joints(actor, t, result.joints)
        return t1

    def _move_joint(self, step: ProcessStep, t0: float) -> float:
        value = step.value
        if value == "home":
            goal = np.zeros_like(self.state.joints[step.actor])
        else:
            raw = (value or {}).get("joints_deg") if isinstance(value, dict) else None
            raw = raw or (step.target or {}).get("joints_deg")
            if raw is None:
                raise ValueError(f"步驟 {step.id} 的 move_joint 缺少 joints_deg 或 home")
            goal = np.asarray(raw, dtype=float)
        limits = self.scene.robots[step.actor].chain.limits
        if goal.shape != (len(limits),):
            raise ValueError(f"步驟 {step.id} 的 move_joint 關節數量不符")
        goal = np.clip(goal, limits[:, 0], limits[:, 1])
        speed_scale = float(value.get("speed_scale", 0.5)) if isinstance(value, dict) else 0.5
        return self._move_joints(step.id, step.actor, goal, t0, step.duration_s, speed_scale)

    def _cover_name(self, step: ProcessStep) -> str | None:
        if self.scene.part_axis(step.actor) is not None:
            return step.actor
        target = step.target or {}
        if target.get("module") in self.scene.parts and target.get("id"):
            return f"{target['module']}.{target['id']}"
        return None

    def _cover_goal(self, name: str, value: Any) -> float:
        axis = self._axis(name)
        maximum = axis.range_deg[1]
        current = self.state.axes[name]
        if value is None:
            return maximum if abs(current) < 1e-9 else 0.0
        if isinstance(value, dict):
            return float(value.get("open_angle_deg", value.get("value_deg", maximum)))
        return float(value)

    def _track_cover(self, step: ProcessStep, name: str, t0: float) -> float:
        start = self.state.axes[name]
        goal = self._cover_goal(name, step.value)
        axis = self._axis(name)
        assert axis.range_deg is not None
        goal = float(np.clip(goal, *axis.range_deg))
        driven = step.driven_by or (step.actor if step.actor in self.scene.robots else None)
        duration = step.duration_s if step.duration_s is not None else abs(goal - start) / 45.0
        approach = min(0.5, max(0.0, duration) * 0.2) if driven else 0.0
        tracking_start = t0 + approach
        t1 = tracking_start + max(0.0, duration)
        self.nodes[name]["driven_by"] = driven
        if driven:
            edge_target = {"frame": f"{name}.edge", "offset": (step.target or {}).get("offset", {})}
            target = self.scene.frame_target(edge_target, self.state, tool=True)
            goal_joints = self._solve(step.id, driven, target, t0)
            self._move_joints(step.id, driven, goal_joints, t0, approach)
        self._append_axis(name, tracking_start, start)
        seed = self.state.joints.get(driven, np.array([])).copy()
        for t in _sample_times(tracking_start, t1):
            ratio = 1.0 if t1 <= tracking_start else (t - tracking_start) / (t1 - tracking_start)
            value = start + (goal - start) * ratio
            self._append_axis(name, t, value)
            if driven:
                self.state.joints[driven] = seed
                target = self.scene.frame_target(edge_target, self.state, tool=True)
                seed = self._solve(step.id, driven, target, t)
                self._append_joints(driven, t, seed)
        return t1

    def _actuate(self, step: ProcessStep, t0: float) -> float:
        cover = self._cover_name(step)
        if cover:
            return self._track_cover(step, cover, t0)
        axis = self._axis(step.actor)
        current = self.state.axes[step.actor]
        if isinstance(step.value, dict):
            key = "value_deg" if axis.type == "revolute" else "value_mm"
            goal = float(step.value[key])
        else:
            goal = float(step.value)
        limits = axis.range_deg if axis.type == "revolute" else axis.range_mm
        assert limits is not None
        goal = float(np.clip(goal, *limits))
        speed = axis.max_speed_dps if axis.type == "revolute" else axis.max_speed_mm_s
        duration = step.duration_s
        if duration is None:
            duration = abs(goal - current) / (speed or 100.0)
        t1 = t0 + max(0.0, duration)
        self._append_axis(step.actor, t0, current)
        owner = step.actor.partition(".")[0]
        followers = [
            part_id for part_id in self.scene.parts if self.state.part(part_id).holder == owner
        ]
        relatives = {}
        if followers:
            child = axis.child or axis.id
            current_link = self.scene.module_link_transforms(owner, self.state)[child]
            for part_id in followers:
                relatives[part_id] = np.linalg.inv(current_link) @ self.state.part(part_id).pose
                self._append_pose(t0, self.state.part(part_id).pose, part_id)
            self._carry(t0, set(followers))
        self._append_axis(step.actor, t1, goal)
        if followers:
            goal_link = self.scene.module_link_transforms(owner, self.state)[child]
            for part_id in followers:
                self.state.part(part_id).pose = goal_link @ relatives[part_id]
                self._append_pose(t1, self.state.part(part_id).pose, part_id)
            self._carry(t1, set(followers))
        return t1

    def _transfer(self, step: ProcessStep, t0: float) -> float:
        part_id = self._object(step)
        goal = self.scene.frame_target(step.target or {}, self.state, tool=False)
        start = self.state.part(part_id).pose.copy()
        distance = float(np.linalg.norm(goal[:3, 3] - start[:3, 3]))
        module = self.scene.modules[step.actor]
        speed = float(module.instance.params.get("speed_mm_s", 0.0))
        if speed <= 0:
            speed = next(
                (axis.max_speed_mm_s for axis in module.definition.axes if axis.max_speed_mm_s),
                300.0,
            )
        duration = step.duration_s if step.duration_s is not None else distance / speed
        t1 = t0 + max(0.0, duration)
        self._append_attached(t0, step.actor, part_id)
        self._append_pose(t0, start, part_id)
        self._carry(t0, {part_id})
        rotates = not np.allclose(start[:3, :3], goal[:3, :3], atol=1e-9)
        if rotates and self._holds_others(part_id):
            # 被帶著的子零件各自內插會與母零件的 slerp 不一致：旋轉時逐點取樣。
            for sample in _sample_times(t0, t1)[1:-1]:
                ratio = (sample - t0) / (t1 - t0)
                self.state.part(part_id).pose = _interpolate_pose(start, goal, ratio)
                self._append_pose(sample, self.state.part(part_id).pose, part_id)
                self._carry(sample, {part_id})
        self.state.part(part_id).pose = goal
        self._append_pose(t1, goal, part_id)
        self._carry(t1, {part_id})
        owner = self.scene.frame_owner(str((step.target or {}).get("frame", step.actor)))
        self._append_attached(t1, owner, part_id)
        self.state.part(part_id).relative = self._relative_to_holder(part_id)
        return t1

    def _holds_others(self, part_id: str) -> bool:
        return any(self.state.part(other).holder == part_id for other in self.scene.parts)

    def _attach(self, step: ProcessStep, t0: float) -> float:
        part_id = self._object(step)
        tool_name = f"{step.actor}.tool"
        tool = self.scene.resolve_frame(tool_name, self.state)
        self.state.part(part_id).relative = np.linalg.inv(tool) @ self.state.part(part_id).pose
        self._append_attached(t0, tool_name, part_id)
        return t0 + max(0.0, step.duration_s or 0.0)

    def _detach(self, step: ProcessStep, t0: float) -> float:
        part_id = self._object(step)
        state = self.state.part(part_id)
        duration = max(0.0, step.duration_s or 0.0)
        t1 = t0 + duration
        if step.target:
            self._append_pose(t0, state.pose, part_id)
            state.pose = self.scene.frame_target(step.target, self.state, tool=False)
            self._append_pose(t1, state.pose, part_id)
            self._carry(t1, {part_id})
            owner = self.scene.frame_owner(str(step.target.get("frame", "")))
        else:
            owner = None
        self._append_attached(t1, owner, part_id)
        state.relative = self._relative_to_holder(part_id)
        return t1

    def _flip_robot(self, step: ProcessStep, t0: float) -> float:
        part_id = self._object(step)
        held = self.state.part(part_id)
        if held.holder != f"{step.actor}.tool" or held.relative is None:
            raise ValueError(f"步驟 {step.id} 翻面前手臂必須先夾持工件")
        value = step.value if isinstance(step.value, dict) else {}
        lift = float(value.get("lift_mm", 150.0))
        angle = float(value.get("angle_deg", 180.0))
        duration = max(0.0, step.duration_s if step.duration_s is not None else 4.0)
        t1 = t0 + duration
        original = held.pose.copy()
        center_local = np.array([0.0, 0.0, self.scene.parts[part_id].height_mm / 2.0, 1.0])
        seed = self.state.joints[step.actor].copy()
        for t in _sample_times(t0, t1):
            ratio = 1.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            if ratio <= 0.25:
                pose = original.copy()
                pose[:3, 3] += np.array([0.0, 0.0, lift * ratio / 0.25])
            else:
                lifted = original.copy()
                lifted[:3, 3] += np.array([0.0, 0.0, lift])
                center = lifted @ center_local
                rotation = transform(rpy_deg=(angle * (ratio - 0.25) / 0.75, 0, 0))
                pose = transform(center[:3]) @ rotation @ transform(-center[:3]) @ lifted
            tool_goal = pose @ np.linalg.inv(held.relative)
            self.state.joints[step.actor] = seed
            seed = self._solve(step.id, step.actor, tool_goal, t)
            self._append_joints(step.actor, t, seed)
        return t1

    def _flip_module(self, step: ProcessStep, t0: float) -> float:
        part_id = self._object(step)
        module = self.scene.modules[step.actor]
        axis = next((item for item in module.definition.axes if item.id == "flip"), None)
        if axis is None:
            raise ValueError(f"步驟 {step.id} 的模組沒有 flip 軸")
        axis_name = f"{step.actor}.flip"
        current = self.state.axes[axis_name]
        child = axis.child or axis.id
        current_link = self.scene.module_link_transforms(step.actor, self.state)[child]
        relative = np.linalg.inv(current_link) @ self.state.part(part_id).pose
        duration = max(0.0, step.duration_s if step.duration_s is not None else 4.0)
        t1 = t0 + duration
        self._append_attached(t0, axis_name, part_id)
        for t in _sample_times(t0, t1):
            ratio = 1.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            self._append_axis(axis_name, t, current + (180.0 - current) * ratio)
            link = self.scene.module_link_transforms(step.actor, self.state)[child]
            self.state.part(part_id).pose = link @ relative
            self._append_pose(t, self.state.part(part_id).pose, part_id)
            self._carry(t, {part_id})
        self._append_attached(t1, None, part_id)
        self.state.part(part_id).relative = None
        return t1

    def motion_failures(self) -> int:
        return len(self.ik_failures) + len(self.path_discontinuities)

    def execute(self, step: ProcessStep, t0: float) -> tuple[float, str | None]:
        from .contracts import CONTRACTS

        self._restore(t0)
        failures_before = self.motion_failures()
        if step.action in CONTRACTS:
            t1 = CONTRACTS[step.action](self, step, t0)
        elif step.action == "move_to":
            t1 = self._move_to(step, t0)
        elif step.action == "move_joint":
            t1 = self._move_joint(step, t0)
        elif step.action == "actuate":
            t1 = self._actuate(step, t0)
        elif step.action == "transfer":
            t1 = self._transfer(step, t0)
        elif step.action in {"grip", "attach"}:
            t1 = self._attach(step, t0)
        elif step.action in {"release", "detach"}:
            t1 = self._detach(step, t0)
        elif step.action == "flip":
            t1 = (
                self._flip_robot(step, t0)
                if step.actor in self.scene.robots
                else self._flip_module(step, t0)
            )
        elif step.action in {"wait", "capture"}:
            default = 0.5 if step.action == "capture" else 0.0
            t1 = t0 + max(0.0, step.duration_s if step.duration_s is not None else default)
            if step.action == "capture":
                self.events.append({"t": t1, "id": f"{step.id}.capture"})
        elif step.action == "emit":
            t1 = t0
        else:
            raise ValueError(f"步驟 {step.id} 使用不支援的 action：{step.action}")
        self.duration_s = max(self.duration_s, t1)
        ik = None
        if step.action in {"move_to", "flip", *CONTRACTS} or self._cover_name(step):
            ik = "failed" if self.motion_failures() > failures_before else "ok"
        return t1, ik

    def timeline(self) -> dict[str, Any]:
        station_names = {}
        return {
            "fps": self.fps,
            "duration_s": self.duration_s,
            "stations": [
                {
                    "id": station,
                    "name": station_names.get(station, station),
                    "t0": span[0],
                    "t1": span[1],
                }
                for station, span in self.station_ranges.items()
            ],
            "steps": self.steps,
            "nodes": self.nodes,
            "events": sorted(self.events, key=lambda item: (item["t"], item["id"])),
            "ik_failures": self.ik_failures,
            "path_discontinuities": self.path_discontinuities,
            "action_results": self.action_results,
        }
