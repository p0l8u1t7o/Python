"""可重用的動作契約：每個動作宣告對象、前置條件、工具、路徑、完成事件與失敗原因。

契約由引擎的基本動作（關節移動、直線移動、夾持、放開）組合而成；前置條件不成立時不移動，
直接記錄失敗原因。每次執行都寫入 ``timeline.action_results``，完成事件為 ``<步驟>.done``。

失敗代碼：
- ``HELD_BY_OTHER``：取料時零件已被其他手臂持有。
- ``TOOL_OCCUPIED``：取料時手臂已經持有其他零件。
- ``WRONG_TOOL``：手臂裝的工具不是步驟要求的工具。
- ``NOT_HELD``：放置／插入時手臂沒有持有該零件。
- ``TARGET_OCCUPIED``：放置目標上已有其他零件。
- ``UNREACHABLE``：接近、下探或撤離的任一點 IK 失敗或路徑跳解。
- ``MISALIGNED``：放下時零件與目標的位置誤差超過容差。
- ``OFF_TARGET``／``NO_CONTACT``／``OVERTRAVEL``／``NOT_SEATED``：壓合時壓墊沒落在壓合面、沒碰到、
  貼平後下壓超過彈簧行程、或沒有壓到底。
- ``OUT_OF_VIEW``／``OUT_OF_FOCUS``／``LOW_RESOLUTION``／``OCCLUDED``：相機無法判定 ROI。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from cellforge.schema.models import ActionPath, ProcessStep

from .scene import transform

if TYPE_CHECKING:
    from .engine import Simulator

FLIP = transform(rpy_deg=(180, 0, 0))
PLACE_TOLERANCE_MM = 1.0
OCCUPIED_RADIUS_MM = 1.0


class ContractFailure(Exception):
    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _path(step: ProcessStep) -> ActionPath:
    return step.path or ActionPath()


def _tool_part(simulator: Simulator, actor: str) -> str | None:
    tool = simulator.scene.modules[actor].instance.params.get("tool")
    return str(tool.get("part")) if isinstance(tool, dict) and tool.get("part") else None


def _check_tool(simulator: Simulator, step: ProcessStep) -> None:
    if step.tool is None:
        return
    mounted = _tool_part(simulator, step.actor)
    if (mounted or "").replace("\\", "/") != step.tool.replace("\\", "/"):
        raise ContractFailure(
            "WRONG_TOOL",
            f"步驟 {step.id} 需要工具 {step.tool}，手臂 {step.actor} 裝的是 {mounted or '無工具'}",
        )


def _held_parts(simulator: Simulator, actor: str) -> list[str]:
    tool = f"{actor}.tool"
    return [part for part in simulator.scene.parts if simulator.state.part(part).holder == tool]


def _surface(simulator: Simulator, target: dict[str, Any]) -> np.ndarray:
    """World pose of the target frame with offset (no tool flip)."""
    return simulator.scene.frame_target(target, simulator.state, tool=False)


def _lifted(pose: np.ndarray, distance: float) -> np.ndarray:
    return pose @ transform((0.0, 0.0, distance))


def _record(
    simulator: Simulator,
    step: ProcessStep,
    objects: list[str],
    t0: float,
    t1: float,
    failure: ContractFailure | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    simulator.action_results.append(
        {
            "step_id": step.id,
            "action": step.action,
            "objects": objects,
            "status": "failed" if failure else "ok",
            "t0": float(t0),
            "t1": float(t1),
            "reason_code": failure.code if failure else None,
            "reason": failure.reason if failure else None,
            "details": details or {},
        }
    )


def _unreachable(simulator: Simulator, before: int, step: ProcessStep) -> ContractFailure | None:
    if simulator.motion_failures() > before:
        return ContractFailure(
            "UNREACHABLE", f"步驟 {step.id} 的接近、下探或撤離路徑有手臂到不了的點"
        )
    return None


def run_pick(simulator: Simulator, step: ProcessStep, t0: float) -> float:
    part_id = simulator._object(step)
    holder = simulator.state.part(part_id).holder
    try:
        if holder and holder.endswith(".tool"):
            raise ContractFailure(
                "HELD_BY_OTHER", f"零件 {part_id} 目前由 {holder} 持有，不能再取料"
            )
        held = _held_parts(simulator, step.actor)
        if held:
            raise ContractFailure(
                "TOOL_OCCUPIED",
                f"手臂 {step.actor} 已持有 {'、'.join(held)}，不能再取料 {part_id}",
            )
        _check_tool(simulator, step)
    except ContractFailure as failure:
        _record(simulator, step, [part_id], t0, t0, failure)
        return t0
    path = _path(step)
    before = simulator.motion_failures()
    grasp = _surface(simulator, step.target or {"frame": part_id})
    above = _lifted(grasp, path.approach_mm)
    retract = _lifted(grasp, path.retract_mm if path.retract_mm is not None else path.approach_mm)
    t = simulator._move_pose(
        step.id, step.actor, above @ FLIP, t0, linear=False, speed_scale=path.speed_scale
    )
    t = simulator._move_pose(
        step.id, step.actor, grasp @ FLIP, t, linear=True, speed_scale=path.speed_scale
    )
    tool = simulator.scene.resolve_frame(f"{step.actor}.tool", simulator.state)
    state = simulator.state.part(part_id)
    state.relative = np.linalg.inv(tool) @ state.pose
    simulator._append_attached(t, f"{step.actor}.tool", part_id)
    t += max(0.0, path.hold_s)
    t = simulator._move_pose(
        step.id, step.actor, retract @ FLIP, t, linear=True, speed_scale=path.speed_scale
    )
    _record(simulator, step, [part_id], t0, t, _unreachable(simulator, before, step))
    return t


def run_place(simulator: Simulator, step: ProcessStep, t0: float) -> float:
    part_id = simulator._object(step)
    target = step.target or {}
    frame = str(target.get("frame", ""))
    owner = simulator.scene.frame_owner(frame)
    goal = _surface(simulator, target)
    try:
        state = simulator.state.part(part_id)
        if state.holder != f"{step.actor}.tool" or state.relative is None:
            raise ContractFailure(
                "NOT_HELD", f"步驟 {step.id} 開始時手臂 {step.actor} 沒有持有零件 {part_id}"
            )
        _check_tool(simulator, step)
        for other in simulator.scene.parts:
            other_state = simulator.state.part(other)
            if other == part_id or other_state.holder != owner:
                continue
            if np.linalg.norm(other_state.pose[:3, 3] - goal[:3, 3]) <= OCCUPIED_RADIUS_MM:
                raise ContractFailure(
                    "TARGET_OCCUPIED", f"放置目標 {frame} 上已有零件 {other}，不能放入 {part_id}"
                )
    except ContractFailure as failure:
        _record(simulator, step, [part_id], t0, t0, failure)
        return t0
    path = _path(step)
    before = simulator.motion_failures()
    grip = np.linalg.inv(state.relative)  # object → tool
    above = _lifted(goal, path.approach_mm)
    retract = _lifted(goal, path.retract_mm if path.retract_mm is not None else path.approach_mm)
    linear_approach = step.action == "insert"
    t = simulator._move_pose(
        step.id,
        step.actor,
        above @ grip,
        t0,
        linear=linear_approach,
        speed_scale=path.speed_scale,
    )
    down = _lifted(goal, -path.depth_mm) if step.action == "insert" else goal
    t = simulator._move_pose(
        step.id, step.actor, down @ grip, t, linear=True, speed_scale=path.speed_scale
    )
    t += max(0.0, path.hold_s)
    placed = simulator.state.part(part_id).pose.copy()
    error = float(np.linalg.norm(placed[:3, 3] - down[:3, 3]))
    simulator._append_attached(t, owner, part_id)
    simulator.state.part(part_id).relative = simulator._relative_to_holder(part_id)
    tool_retract = retract @ grip
    t = simulator._move_pose(
        step.id, step.actor, tool_retract, t, linear=True, speed_scale=path.speed_scale
    )
    failure = _unreachable(simulator, before, step)
    if failure is None and error > PLACE_TOLERANCE_MM:
        failure = ContractFailure(
            "MISALIGNED",
            f"零件 {part_id} 放下時與目標 {frame} 相差 {error:.2f} mm，"
            f"超過 {PLACE_TOLERANCE_MM} mm",
        )
    details = {"target": frame, "holder": owner, "position_error_mm": error}
    if step.action == "insert":
        details["inserted_into"] = owner
    _record(simulator, step, [part_id], t0, t, failure, details)
    return t


# ---------------------------------------------------------------- 壓合


def _press_axis(simulator: Simulator, part_id: str, face: str) -> tuple[str, Any]:
    """The part state axis that moves the pressed face (e.g. a connector's tilt)."""
    definition = simulator.scene.parts[part_id].definition
    frame = definition.frames.get(face)
    if frame is None:
        raise ContractFailure("NO_FACE", f"零件 {part_id} 沒有壓合面 frame：{face}")
    axis = next((item for item in definition.axes if (item.child or item.id) == frame.link), None)
    if axis is None:
        raise ContractFailure("NO_FACE", f"零件 {part_id} 的壓合面 {face} 不在任何狀態軸上")
    return f"{part_id}.{axis.id}", axis


def _face_depth(
    simulator: Simulator, part_id: str, face: str, axis_name: str, value: float, pad: np.ndarray
) -> tuple[float, np.ndarray]:
    """Depth of the face point past the pad surface (+ = pressed in) and its pad-local XY."""
    simulator.state.axes[axis_name] = value
    point = simulator.scene.resolve_frame(f"{part_id}.{face}", simulator.state)[:3, 3]
    local = np.linalg.inv(pad) @ np.append(point, 1.0)
    # 壓墊 frame 的 +Z 指向工件：壓合面落在壓墊表面後方（局部 z < 0）即被壓入。
    return float(-local[2]), local[:2]


def _solve_tilt(
    simulator: Simulator,
    part_id: str,
    face: str,
    axis_name: str,
    upper: float,
    lower: float,
    pad: np.ndarray,
) -> float:
    """Largest axis value in [lower, upper] whose face does not pass the pad surface."""
    if _face_depth(simulator, part_id, face, axis_name, upper, pad)[0] <= 0:
        return upper
    low, high = lower, upper
    for _ in range(40):
        middle = (low + high) / 2.0
        if _face_depth(simulator, part_id, face, axis_name, middle, pad)[0] > 0:
            high = middle
        else:
            low = middle
    return low


def run_press(simulator: Simulator, step: ProcessStep, t0: float) -> float:
    """受限行程壓合：壓墊把接頭壓回貼平，貼平後的下壓量由壓墊彈簧吸收，超過行程即過壓。"""

    from cellforge.schema.models import PressSpec

    objects = list(step.objects) or [simulator._object(step)]
    spec = step.press or PressSpec()
    pads = spec.pads or (
        [f"pad_{index + 1}" for index in range(len(objects))]
        if len(objects) > 1
        else ["tool_center_point"]
    )
    try:
        _check_tool(simulator, step)
        if len(pads) != len(objects):
            raise ContractFailure(
                "CONFIG", f"步驟 {step.id} 的壓墊數 {len(pads)} 與零件數 {len(objects)} 不符"
            )
        axes = [_press_axis(simulator, part_id, spec.face) for part_id in objects]
    except ContractFailure as failure:
        _record(simulator, step, objects, t0, t0, failure)
        return t0
    path = _path(step)
    before = simulator.motion_failures()
    align = _surface(simulator, step.target or {})
    above = _lifted(align, path.approach_mm)
    bottom = _lifted(align, -path.depth_mm)
    t = simulator._move_pose(
        step.id, step.actor, above @ FLIP, t0, linear=False, speed_scale=path.speed_scale
    )
    down = t
    t = simulator._move_pose(
        step.id, step.actor, bottom @ FLIP, t, linear=True, speed_scale=path.speed_scale
    )
    hold_start = t
    t += max(0.0, path.hold_s)
    up = t
    retract = _lifted(align, path.retract_mm if path.retract_mm is not None else path.approach_mm)
    t = simulator._move_pose(
        step.id, step.actor, retract @ FLIP, t, linear=True, speed_scale=path.speed_scale
    )
    end = t
    times = sorted(
        {
            float(key[0])
            for key in simulator.nodes[step.actor]["joints_deg"]
            if down - 1e-9 <= float(key[0]) <= end + 1e-9
        }
        | {down, hold_start, up, end}
    )
    joints = simulator.nodes[step.actor]["joints_deg"]
    from .sampling import _linear

    tilts = [float(simulator.state.axes[name]) for name, _axis in axes]
    start_tilts = list(tilts)
    minimum = list(tilts)
    compression = [0.0] * len(objects)
    contacted = [False] * len(objects)
    off_target: list[str] = []
    # 回彈（示意）只發生在第一次壓合；補壓後即貼合。
    pressed = simulator.__dict__.setdefault("_press_counts", {})
    rebound = [
        float(simulator.scene.parts[part_id].params.get("rebound_deg", 0.0))
        if pressed.get(part_id, 0) == 0
        else 0.0
        for part_id in objects
    ]
    lower_limits = [float((axis.range_deg or (0.0, 0.0))[0]) for _name, axis in axes]
    for sample in times:
        simulator.state.joints[step.actor] = _linear(joints, sample)
        for index, (part_id, (axis_name, _axis)) in enumerate(zip(objects, axes, strict=True)):
            pad = simulator.scene.resolve_frame(f"{step.actor}.{pads[index]}", simulator.state)
            depth, lateral = _face_depth(
                simulator, part_id, spec.face, axis_name, tilts[index], pad
            )
            inside = abs(lateral[0]) <= spec.pad_size_mm[0] / 2 and abs(lateral[1]) <= (
                spec.pad_size_mm[1] / 2
            )
            if depth > 0 and not inside:
                if part_id not in off_target:
                    off_target.append(part_id)
                simulator.state.axes[axis_name] = tilts[index]
                continue
            retracting = sample > up + 1e-9
            if retracting:
                goal = min(minimum[index] + rebound[index], start_tilts[index])
                if goal > tilts[index]:
                    tilts[index] = _solve_tilt(
                        simulator, part_id, spec.face, axis_name, goal, tilts[index], pad
                    )
            elif depth > 0:
                contacted[index] = True
                flat, _ = _face_depth(
                    simulator, part_id, spec.face, axis_name, lower_limits[index], pad
                )
                if flat > 0:
                    tilts[index] = lower_limits[index]
                    compression[index] = max(compression[index], flat)
                else:
                    tilts[index] = _solve_tilt(
                        simulator,
                        part_id,
                        spec.face,
                        axis_name,
                        tilts[index],
                        lower_limits[index],
                        pad,
                    )
            minimum[index] = min(minimum[index], tilts[index])
            simulator.state.axes[axis_name] = tilts[index]
            simulator._append_axis(axis_name, sample, tilts[index])
    simulator.state.joints[step.actor] = _linear(joints, end)
    failure = _unreachable(simulator, before, step)
    over = [
        (part_id, value)
        for part_id, value in zip(objects, compression, strict=True)
        if value > spec.spring_mm + 1e-6
    ]
    missing = [
        part_id
        for part_id, touched in zip(objects, contacted, strict=True)
        if not touched and part_id not in off_target
    ]
    unseated = [
        part_id
        for part_id, value, limit in zip(objects, minimum, lower_limits, strict=True)
        if value > limit + 0.05
    ]
    if failure is None and off_target:
        failure = ContractFailure(
            "OFF_TARGET", f"壓墊沒有落在壓合面上：{'、'.join(off_target)}（治具或對位偏移）"
        )
    if failure is None and over:
        worst = max(value for _part, value in over)
        failure = ContractFailure(
            "OVERTRAVEL",
            f"貼平後下壓 {worst:.2f} mm 超過壓墊彈簧行程 {spec.spring_mm:g} mm："
            f"{'、'.join(part for part, _value in over)}",
        )
    if failure is None and missing:
        failure = ContractFailure("NO_CONTACT", f"壓墊沒有碰到：{'、'.join(missing)}")
    if failure is None and unseated:
        failure = ContractFailure("NOT_SEATED", f"壓合未到底：{'、'.join(unseated)}")
    details = {
        part_id: {
            "tilt_before_deg": start_tilts[index],
            "tilt_min_deg": minimum[index],
            "tilt_after_deg": tilts[index],
            "spring_compression_mm": compression[index],
        }
        for index, part_id in enumerate(objects)
    }
    for part_id, touched in zip(objects, contacted, strict=True):
        if touched:
            pressed[part_id] = pressed.get(part_id, 0) + 1
    _record(simulator, step, objects, t0, end, failure, {"objects": details})
    return end


# ---------------------------------------------------------------- 檢測


def _view_pose(reference: np.ndarray, distance: float, tilt: float, spin: float) -> np.ndarray:
    """Camera pose looking back at ``reference`` from ``distance`` along its tilted +Z."""
    return (
        reference
        @ transform(rpy_deg=(tilt, 0, 0))
        @ transform((0.0, 0.0, distance))
        @ FLIP
        @ transform(rpy_deg=(0, 0, spin))
    )


def _roi_points(roi: np.ndarray, size: tuple[float, float]) -> np.ndarray:
    width, height = size
    local = np.asarray(
        [
            [0.0, 0.0, 0.0, 1.0],
            [-width / 2, -height / 2, 0.0, 1.0],
            [width / 2, -height / 2, 0.0, 1.0],
            [width / 2, height / 2, 0.0, 1.0],
            [-width / 2, height / 2, 0.0, 1.0],
        ]
    )
    return (roi @ local.T).T[:, :3]


def _occluders(simulator: Simulator, camera_owner: str, excluded: set[str]):
    """World-space half-space planes of every convex collision part that could block the view."""
    import trimesh

    from cellforge.checks.collision import build_collision_parts
    from cellforge.sim.sampling import world_transforms

    if getattr(simulator, "_vision_parts", None) is None:
        simulator._vision_parts = build_collision_parts(simulator.scene)
    transforms = world_transforms(simulator.scene, simulator.state)
    planes = []
    owners = []
    for part in simulator._vision_parts:
        if part.module in excluded or (
            part.module == camera_owner and part.link in {"tool", "base"}
        ):
            continue
        matrix = transforms[part.name]
        vertices = part.vertices @ matrix[:3, :3].T + matrix[:3, 3]
        hull = trimesh.convex.convex_hull(vertices)
        normals = np.asarray(hull.face_normals)
        offsets = np.einsum("ij,ij->i", normals, hull.vertices[hull.faces[:, 0]])
        planes.append((normals, offsets))
        owners.append(part.name)
    return planes, owners


def _blocked(planes, owners, origin: np.ndarray, point: np.ndarray) -> str | None:
    """First convex part the segment origin→point enters before reaching the point."""
    direction = point - origin
    length = float(np.linalg.norm(direction))
    if length <= 1e-9:
        return None
    direction /= length
    for (normals, offsets), owner in zip(planes, owners, strict=True):
        denominator = normals @ direction
        numerator = offsets - normals @ origin
        parallel = np.abs(denominator) < 1e-12
        if np.any(parallel & (numerator < 0)):
            continue
        ratios = numerator[~parallel] / denominator[~parallel]
        entering = ratios[denominator[~parallel] < 0]
        exiting = ratios[denominator[~parallel] > 0]
        start = max(0.0, float(entering.max())) if len(entering) else 0.0
        stop = float(exiting.min()) if len(exiting) else float("inf")
        if start <= stop and start < length - 0.5 and stop > 0:
            return owner
    return None


def run_inspect(simulator: Simulator, step: ProcessStep, t0: float) -> float:
    """檢測：相機是否看得到 ROI（視野、景深、解析度、遮蔽），以及依狀態模型的判定結果。"""

    spec = step.inspect
    assert spec is not None
    objects = list(step.objects) or ([step.object] if step.object else [])
    camera_owner = spec.camera.partition(".")[0]
    camera_frame = spec.camera.partition(".")[2]
    before = simulator.motion_failures()
    t = t0
    try:
        if spec.view is not None:
            if camera_owner not in simulator.scene.robots:
                raise ContractFailure(
                    "CONFIG", f"步驟 {step.id} 指定了 view，但相機 {spec.camera} 不在手臂上"
                )
            reference = _surface(simulator, step.target or {"frame": f"{objects[0]}.{spec.roi}"})
            camera_pose = _view_pose(
                reference, spec.view.distance_mm, spec.view.tilt_deg, spec.view.spin_deg
            )
            tcp = camera_pose @ np.linalg.inv(
                simulator.scene.tool_mount_to_frame(camera_owner, camera_frame)
            )
            t = simulator._move_pose(step.id, camera_owner, tcp, t0, linear=False)
        elif step.target and camera_owner in simulator.scene.robots:
            # 示教點：手臂把 TCP 移到目標，相機落在工具上它實際的位置。
            tcp = simulator.scene.frame_target(step.target, simulator.state, tool=True)
            t = simulator._move_pose(step.id, camera_owner, tcp, t0, linear=False)
    except ContractFailure as failure:
        _record(simulator, step, objects, t0, t0, failure)
        return t0
    t += max(0.0, step.duration_s if step.duration_s is not None else 0.5)
    simulator.events.append({"t": t, "id": f"{step.id}.capture"})
    pose, camera = simulator.scene.camera(spec.camera, simulator.state)
    near, far = camera.depth_of_field_mm()
    half_w, half_h = (value / 2 for value in camera.sensor_mm)
    planes, owners = _occluders(simulator, camera_owner, set(objects))
    inverse = np.linalg.inv(pose)
    rois = [f"{part}.{spec.roi}" for part in objects] or [spec.roi]
    evaluations = {}
    problems: dict[str, list[str]] = {}
    for name in rois:
        roi = simulator.scene.resolve_frame(name, simulator.state)
        points = _roi_points(roi, spec.roi_size_mm)
        local = (inverse @ np.c_[points, np.ones(len(points))].T).T[:, :3]
        depth = local[:, 2]
        issues = []
        if np.any(depth <= 1e-6):
            issues.append("OUT_OF_VIEW")
        else:
            u = local[:, 0] / depth * camera.focal_mm
            v = local[:, 1] / depth * camera.focal_mm
            if np.any(np.abs(u) > half_w) or np.any(np.abs(v) > half_h):
                issues.append("OUT_OF_VIEW")
            if np.any(depth < near) or np.any(depth > far):
                issues.append("OUT_OF_FOCUS")
        resolution = camera.mm_per_px(float(depth[0])) if depth[0] > 0 else float("inf")
        if resolution > spec.max_mm_per_px:
            issues.append("LOW_RESOLUTION")
        blocker = (
            None
            if "OUT_OF_VIEW" in issues
            else next(
                (hit for point in points if (hit := _blocked(planes, owners, pose[:3, 3], point))),
                None,
            )
        )
        if blocker:
            issues.append("OCCLUDED")
        evaluation: dict[str, Any] = {
            "distance_mm": float(depth[0]),
            "depth_range_mm": [float(depth.min()), float(depth.max())],
            "mm_per_px": resolution,
            "focus_range_mm": [near, far],
            "issues": issues,
        }
        if blocker:
            evaluation["occluded_by"] = blocker
        part_id = name.partition(".")[0]
        if spec.gap_frames and spec.max_gap_mm is not None and part_id in simulator.scene.parts:
            tip = simulator.scene.resolve_frame(f"{part_id}.{spec.gap_frames[0]}", simulator.state)
            pad = simulator.scene.resolve_frame(f"{part_id}.{spec.gap_frames[1]}", simulator.state)
            gap = float((np.linalg.inv(pad) @ tip)[2, 3])
            evaluation["gap_mm"] = gap
            evaluation["judgement"] = (
                "undetermined" if issues else ("NG" if gap > spec.max_gap_mm else "OK")
            )
        evaluations[name] = evaluation
        if issues:
            problems[name] = issues
    failure = _unreachable(simulator, before, step)
    if failure is None and problems:
        codes = sorted({code for issues in problems.values() for code in issues})
        failure = ContractFailure(
            codes[0],
            "相機無法判定："
            + "；".join(f"{name}（{'、'.join(issues)}）" for name, issues in problems.items()),
        )
    _record(
        simulator,
        step,
        objects,
        t0,
        t,
        failure,
        {"camera": spec.camera, "rois": evaluations, "max_gap_mm": spec.max_gap_mm},
    )
    return t


CONTRACTS = {
    "pick": run_pick,
    "place": run_place,
    "insert": run_place,
    "press": run_press,
    "inspect": run_inspect,
}
