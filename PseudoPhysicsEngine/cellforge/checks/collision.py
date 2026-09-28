"""Native FCL collision sampling for articulated CellForge scenes."""

from __future__ import annotations

import fnmatch
import math
from dataclasses import dataclass
from typing import Any

import fcl
import numpy as np

from cellforge.build.glb import (
    SceneItem,
    _assembly_collision_meshes,
    _assembly_link_meshes,
    _module_item,
    _rest_transforms,
    _workpiece_item,
)
from cellforge.schema.models import ContactDecl, Process
from cellforge.sim.sampling import state_at, world_transforms
from cellforge.sim.scene import SceneModel, SimulationState
from cellforge.sim.workpiece import PRIMARY_PART

SAMPLE_PERIOD_S = 0.02
BROADPHASE_MM = 15.0
WARNING_DISTANCE_MM = 10.0
STATIC_PENETRATION_MM = 1.0

# 宣告接觸：區域邊界容許的誤差、判定接近方向所需的最小相對位移與容許夾角。
CONTACT_REGION_MARGIN_MM = 0.5
CONTACT_MOTION_EPS_MM = 0.05
CONTACT_DIRECTION_TOLERANCE_DEG = 30.0


@dataclass(slots=True)
class CollisionPart:
    key: str
    name: str
    module: str
    link: str
    vertices: np.ndarray
    geometry: Any
    static: bool
    workpiece: bool = False
    cover: bool = False
    tool: bool = False


@dataclass(slots=True)
class _Observation:
    t: float
    distance: float
    source: str
    allowed: bool
    static_pair: bool
    support: bool
    # 宣告接觸：contact 為宣告 id；violation 為不合法的原因（None 表示在宣告範圍內）。
    contact: str | None = None
    violation: str | None = None
    tolerance: float | None = None

    def worse_than(self, other: _Observation) -> bool:
        if (self.violation is not None) != (other.violation is not None):
            return self.violation is not None
        return self.distance < other.distance


def _convex(vertices: np.ndarray, faces: np.ndarray) -> Any:
    encoded = np.asarray(
        [value for face in faces for value in (len(face), *(int(index) for index in face))],
        dtype=np.int32,
    )
    return fcl.Convex(np.asarray(vertices, dtype=float), len(faces), encoded)


def _parts(item: SceneItem, *, dynamic_root: bool, part: bool = False) -> list[CollisionPart]:
    rest = _rest_transforms(item)
    child_to_axis = {axis.child or axis.id: axis.id for axis in item.definition.axes}
    child_to_axis.update({joint.child: joint.id for joint in item.fixed_joints})
    dynamic_links = set(child_to_axis)
    explicit = _assembly_collision_meshes(item.assembly)
    output: list[CollisionPart] = []
    for index, (part_name, declared_link, mesh) in enumerate(_assembly_link_meshes(item.assembly)):
        link = declared_link if declared_link in dynamic_links else part_name
        link = link if link in dynamic_links else "base"
        # 有原廠碰撞幾何（URDF <collision>）時以它為準，否則用外形的凸包。
        local = explicit.get(part_name, mesh).copy()
        local.apply_transform(np.linalg.inv(rest[link]))
        hull = local.convex_hull
        if not len(hull.vertices) or not len(hull.faces):
            continue
        suffix = child_to_axis.get(link)
        name = item.id if suffix is None else f"{item.id}.{suffix}"
        is_workpiece = part
        output.append(
            CollisionPart(
                key=f"{item.id}:{link}:{part_name}:{index}",
                name=name,
                module=item.id,
                link=link,
                vertices=np.asarray(hull.vertices, dtype=float),
                geometry=_convex(hull.vertices, hull.faces),
                static=not dynamic_root and link == "base",
                workpiece=is_workpiece,
                cover=is_workpiece and link != "base",
                tool=link == "tool",
            )
        )
    return output


def build_collision_parts(scene: SceneModel) -> list[CollisionPart]:
    """Create one convex FCL object for every CadQuery assembly sub-part."""

    parts: list[CollisionPart] = []
    for module in scene.modules.values():
        parts.extend(_parts(_module_item(module), dynamic_root=False))
    for product_part in scene.parts.values():
        if product_part.assembly is not None:
            parts.extend(_parts(_workpiece_item(product_part), dynamic_root=True, part=True))
    return parts


def _sample_times(duration: float) -> list[float]:
    count = int(math.floor(max(0.0, duration) / SAMPLE_PERIOD_S + 1e-9))
    times = [index * SAMPLE_PERIOD_S for index in range(count + 1)]
    if not times or duration - times[-1] > 1e-9:
        times.append(max(0.0, duration))
    return times


def _state_signature(state: SimulationState) -> tuple[Any, ...]:
    values: list[Any] = []
    for name, part in sorted(state.parts.items()):
        values.extend((name, part.holder))
    for name, joints in sorted(state.joints.items()):
        values.extend((name, *np.round(joints, 10).tolist()))
    for name, value in sorted(state.axes.items()):
        values.extend((name, round(float(value), 10)))
    for _name, part in sorted(state.parts.items()):
        values.extend(np.round(part.pose.ravel(), 10).tolist())
    return tuple(values)


def _world_vertices(part: CollisionPart, transform: np.ndarray) -> np.ndarray:
    return part.vertices @ transform[:3, :3].T + transform[:3, 3]


def _aabb_distance(first: np.ndarray, second: np.ndarray) -> float:
    delta = np.maximum(0.0, np.maximum(first[0] - second[1], second[0] - first[1]))
    return float(np.linalg.norm(delta))


def _set_transform(obj: Any, matrix: np.ndarray) -> None:
    obj.setTransform(fcl.Transform(matrix[:3, :3], matrix[:3, 3]))


def _broadphase_candidates(
    parts: list[CollisionPart], bounds: dict[str, np.ndarray]
) -> list[tuple[int, int]]:
    """Index pairs (i < j) whose world AABB gap is below BROADPHASE_MM, in nested-loop order.

    與逐對呼叫 _aabb_distance 的公式相同，但每個取樣時刻一次以 numpy 算完所有配對；
    DEV-006 實測逐對版本在約 200 個零件時占 L1 建置時間的八成以上。
    """

    if len(parts) < 2:
        return []
    lows = np.stack([bounds[part.key][0] for part in parts])
    highs = np.stack([bounds[part.key][1] for part in parts])
    gaps = np.maximum(
        0.0,
        np.maximum(lows[:, None, :] - highs[None, :, :], lows[None, :, :] - highs[:, None, :]),
    )
    near = np.triu(np.linalg.norm(gaps, axis=2) < BROADPHASE_MM, k=1)
    return [(int(i), int(j)) for i, j in zip(*np.nonzero(near), strict=True)]


def _signed_distance(first: Any, second: Any, aabb_a: np.ndarray, aabb_b: np.ndarray):
    """Signed clearance in mm: positive gap, negative penetration depth.

    不使用 FCL 的 enable_signed_distance：兩個凸體恰好面貼面時，其 GJK＋EPA 會在原生程式碼內
    無限迴圈且持有 GIL，任何計時器都無法中斷（DEV-006 實測整個 L1 建置卡死）。改為先以 collide
    （MPR）判定並取 contact depth（D-014 原本穿透時就改用它），未碰撞時才用不帶號的 GJK 距離。
    """

    overlap = np.minimum(aabb_a[1], aabb_b[1]) - np.maximum(aabb_a[0], aabb_b[0])
    collision = fcl.CollisionResult()
    colliding = fcl.collide(
        first,
        second,
        fcl.CollisionRequest(num_max_contacts=8, enable_contact=True),
        collision,
    )
    if colliding:
        depths = [
            float(contact.penetration_depth)
            for contact in collision.contacts
            if math.isfinite(float(contact.penetration_depth))
        ]
        if depths:
            aabb_depth = max(0.0, float(np.min(overlap)))
            return -min(max(depths), aabb_depth), "python-fcl collide；穿透深度：FCL contact depth"
        return (
            -max(0.0, float(np.min(overlap))),
            "python-fcl collide；穿透深度 fallback：AABB 最小重疊",
        )
    result = fcl.DistanceResult()
    distance = float(fcl.distance(first, second, fcl.DistanceRequest(), result))
    if math.isfinite(distance) and distance >= 0:
        return distance, "python-fcl GJK distance"
    # collide 判定分離、distance 卻回報重疊：數值上的貼合，改以世界 AABB 估計。
    if np.all(overlap >= 0):
        return -float(np.min(overlap)), "python-fcl；穿透深度 fallback：AABB 最小重疊"
    return _aabb_distance(aabb_a, aabb_b), "python-fcl；距離 fallback：AABB 間距"


def _adjacent(scene: SceneModel, first: CollisionPart, second: CollisionPart) -> bool:
    if first.module != second.module or first.module in scene.parts:
        return False
    module = scene.modules[first.module]
    first_link = first.link
    second_link = second.link
    if module.chain is not None:
        if first_link == "base":
            first_link = module.chain.base_link
        if second_link == "base":
            second_link = module.chain.base_link
    edges = {frozenset((axis.parent, axis.child or axis.id)) for axis in module.definition.axes}
    if module.chain is not None:
        by_child = {joint.child: joint for joint in module.chain.joints}

        def rigid_parent(link: str) -> str:
            # 經固定關節剛性相連的 link 屬同一剛體：原廠鏈的 J6 → flange（無外形）→ tool
            # 中，工具仍直接裝在 J6 上。
            while (driver := by_child.get(link)) is not None and not driver.active:
                link = driver.parent
            return link

        for joint in module.chain.joints:
            edges.add(frozenset((joint.parent, joint.child)))
            edges.add(frozenset((rigid_parent(joint.parent), joint.child)))
        for joint in module.chain.joints:
            if np.linalg.norm(joint.origin[:3, 3]) > 1e-9:
                continue
            previous = by_child.get(joint.parent)
            if previous is not None:
                edges.add(frozenset((previous.parent, joint.child)))
    return frozenset((first_link, second_link)) in edges


def _driven_pairs(
    process: Process, timeline: dict[str, Any], part_ids: set[str] | None = None
) -> list[tuple[float, float, str, str]]:
    part_ids = part_ids or {PRIMARY_PART}
    specifications = {
        step.id: (step.driven_by, _cover_name(step, part_ids))
        for step in process.steps
        if step.driven_by and _cover_name(step, part_ids)
    }
    return [
        (
            float(step["t0"]),
            float(step["t1"]),
            f"{specifications[step['id']][0]}.tool",
            specifications[step["id"]][1],
        )
        for step in timeline.get("steps", [])
        if step.get("id") in specifications
    ]


def _cover_name(step, part_ids: set[str] | None = None) -> str | None:
    part_ids = part_ids or {PRIMARY_PART}
    if "." in step.actor and step.actor.partition(".")[0] in part_ids:
        return step.actor
    target = step.target or {}
    if target.get("module") in part_ids and target.get("id"):
        return f"{target['module']}.{target['id']}"
    return None


def _is_driven(pair: tuple[str, str], t: float, spans) -> bool:
    names = frozenset(pair)
    return any(
        t0 - 1e-9 <= t <= t1 + 1e-9 and names == frozenset((tool, cover))
        for t0, t1, tool, cover in spans
    )


def _support_windows(
    scene: SceneModel, process: Process, timeline: dict[str, Any]
) -> list[tuple[float, float, str, str]]:
    """Intervals (start, end, module, part) where a module may support a part in a hand-off."""

    result: list[tuple[float, float, str, str]] = []
    single = next(iter(scene.parts)) if len(scene.parts) == 1 else None
    for part_id in scene.parts:
        steps = [
            step
            for step in process.steps
            if (step.object or (PRIMARY_PART if PRIMARY_PART in scene.parts else single)) == part_id
        ]
        result.extend(
            (start, end, owner, part_id)
            for start, end, owner in _part_support_windows(scene, steps, timeline, part_id)
        )
    return result


def _part_support_windows(
    scene: SceneModel, steps: list, timeline: dict[str, Any], part_id: str
) -> list[tuple[float, float, str]]:
    duration = float(timeline.get("duration_s", 0.0))
    attachment_keys = sorted(
        (float(key[0]), key[1])
        for key in timeline.get("nodes", {}).get(part_id, {}).get("attached_to", [])
    )

    def module_owner(name: str | None) -> str | None:
        if not name:
            return None
        owner = name.partition(".")[0]
        return owner if owner in scene.modules else None

    intervals: list[tuple[float, float, str]] = []
    for index, (start, attached) in enumerate(attachment_keys):
        owner = module_owner(attached)
        if owner is not None:
            end = attachment_keys[index + 1][0] if index + 1 < len(attachment_keys) else duration
            intervals.append((start, max(start, end), owner))

    specifications = {step.id: step for step in steps}

    def owner_before(t: float) -> str | None:
        previous = None
        for key_t, attached in attachment_keys:
            if key_t >= t - 1e-9:
                break
            previous = module_owner(attached)
        if previous is None and attachment_keys and attachment_keys[0][0] <= t + 1e-9:
            previous = module_owner(attachment_keys[0][1])
        return previous

    timed_steps = sorted(timeline.get("steps", []), key=lambda item: float(item["t0"]))
    for timed in timed_steps:
        specification = specifications.get(timed.get("id"))
        if specification is None:
            continue
        t0, t1 = float(timed["t0"]), float(timed["t1"])
        action = specification.action
        target = specification.target or {}
        target_frame = target.get("frame")
        if action in {"transfer", "release", "detach", "place", "insert"} and target_frame:
            owner = scene.frame_owner(target_frame)
            if owner in scene.modules:
                intervals.append((t0, t1, owner))
        if action in {"transfer", "grip", "attach", "pick"}:
            owner = owner_before(t0)
            if owner is not None:
                intervals.append((t0, t1, owner))
                # Grip only changes attachment state.  When the engine models the
                # physical lift as the following held motion, that motion is the
                # remainder of the same support hand-off.
                if action in {"grip", "attach"}:
                    for later in timed_steps:
                        if float(later["t0"]) < t1 - 1e-9:
                            continue
                        later_specification = specifications.get(later.get("id"))
                        if later_specification is None:
                            continue
                        if later_specification.actor != specification.actor:
                            continue
                        if later_specification.action in {"release", "detach"}:
                            break
                        if later_specification.action in {"move_to", "move_joint", "flip"}:
                            intervals.append((t0, float(later["t1"]), owner))
                            break

    merged: list[tuple[float, float, str]] = []
    for owner in sorted({interval[2] for interval in intervals}):
        owner_intervals = sorted((start, end) for start, end, item in intervals if item == owner)
        for start, end in owner_intervals:
            if merged and merged[-1][2] == owner and start <= merged[-1][1] + 1e-9:
                old_start, old_end, _ = merged[-1]
                merged[-1] = (old_start, max(old_end, end), owner)
            else:
                merged.append((start, end, owner))
    return merged


def _carrier(state: SimulationState, part_id: str) -> tuple[str, str | None]:
    """(top part, its non-part holder) of the carried assembly a part belongs to."""
    seen = {part_id}
    current = part_id
    holder = state.part(part_id).holder
    while holder is not None and holder in state.parts and holder not in seen:
        seen.add(holder)
        current = holder
        holder = state.part(holder).holder
    return current, holder


def _mounted(scene: SceneModel, first: str, second: str) -> bool:
    """One module is installed on the other with ``mount`` (e.g. a robot on its riser)."""
    for child, parent in ((first, second), (second, first)):
        module = scene.modules.get(child)
        mount = getattr(module.instance, "mount", None) if module is not None else None
        if mount and str(mount).partition(".")[0] == parent:
            return True
    return False


def _carried_by(state: SimulationState, part_id: str, holder: str) -> bool:
    seen = {part_id}
    current = state.part(part_id).holder
    while current is not None and current in state.parts and current not in seen:
        if current == holder:
            return True
        seen.add(current)
        current = state.part(current).holder
    return False


def _is_support_pair(
    first: CollisionPart,
    second: CollisionPart,
    t: float,
    windows: list[tuple[float, float, str, str]],
    state: SimulationState | None = None,
) -> bool:
    work, other = (first, second) if first.workpiece else (second, first)
    if not work.workpiece:
        return False
    if state is not None and first.workpiece and second.workpiece:
        if first.module == second.module:
            return False
        # 零件放在另一個零件上（安裝或承載，含持有鏈上更上層的零件，例如接頭殼體落在
        # PCB 下方的載盤上），或同屬一個被承載的產品組件：接觸面是支撐，只有深穿透才算干涉。
        return (
            _carried_by(state, first.module, second.module)
            or _carried_by(state, second.module, first.module)
            or _carrier(state, first.module)[0] == _carrier(state, second.module)[0]
        )
    if state is not None and state.part(work.module).holder in state.parts:
        # 經由其他零件間接承載（例如載盤上的接頭）：與最終承載的模組之間也是支撐關係。
        top, carrier = _carrier(state, work.module)
        if carrier is not None and carrier.partition(".")[0] == other.module:
            return True
    return any(
        owner == other.module and part_id == work.module and start - 1e-9 <= t <= end + 1e-9
        for start, end, owner, part_id in windows
    )


def _excluded(
    scene: SceneModel,
    first: CollisionPart,
    second: CollisionPart,
    state: SimulationState,
) -> bool:
    if first.name == second.name:
        return True
    if first.module == second.module:
        if first.static and second.static:
            return True
        if _adjacent(scene, first, second):
            return True
    if first.workpiece and second.workpiece:
        if first.module != second.module:
            return False
        return (first.link == "base" and second.cover) or (second.link == "base" and first.cover)
    work, other = (first, second) if first.workpiece else (second, first)
    if not work.workpiece:
        return False
    attached = state.part(work.module).holder
    return bool(attached and attached.endswith(".tool") and other.name == attached)


def _severity(
    distance: float, *, allowed: bool, static_pair: bool, support: bool = False
) -> str | None:
    if support:
        return "red" if distance < -STATIC_PENETRATION_MM else None
    if allowed:
        return "green"
    if static_pair:
        if distance < -STATIC_PENETRATION_MM:
            return "red"
        return "yellow" if distance < WARNING_DISTANCE_MM else None
    if distance < -1e-6:
        return "red"
    return "yellow" if distance < WARNING_DISTANCE_MM else None


def _contact_windows(
    process: Process, timeline: dict[str, Any]
) -> list[tuple[ContactDecl, list[tuple[float, float]]]]:
    spans = {step["id"]: (float(step["t0"]), float(step["t1"])) for step in timeline["steps"]}
    return [
        (contact, [spans[step_id] for step_id in contact.window if step_id in spans])
        for contact in process.contacts
    ]


def _matches(element: str, part: CollisionPart) -> bool:
    if any(char in element for char in "*?["):
        return fnmatch.fnmatchcase(part.module, element) or fnmatch.fnmatchcase(part.name, element)
    return part.module == element or part.name == element or part.name.startswith(f"{element}.")


def _declared_contact(
    windows: list[tuple[ContactDecl, list[tuple[float, float]]]],
    first: CollisionPart,
    second: CollisionPart,
    t: float,
) -> tuple[ContactDecl, bool] | None:
    """Declared contact covering this pair at ``t``; the flag says ``first`` is ``pair[0]``."""
    for contact, spans in windows:
        if not any(start - 1e-9 <= t <= end + 1e-9 for start, end in spans):
            continue
        a, b = contact.pair
        if _matches(a, first) and _matches(b, second):
            return contact, True
        if _matches(a, second) and _matches(b, first):
            return contact, False
    return None


def _contact_violation(
    scene: SceneModel,
    contact: ContactDecl,
    state: SimulationState,
    distance: float,
    bounds: tuple[np.ndarray, np.ndarray],
    motion: np.ndarray | None,
) -> str | None:
    """Why a penetration inside a declared window is not the declared contact."""
    if distance >= 0:
        return None
    if -distance > contact.tolerance_mm:
        return f"穿透 {-distance:.3f} mm 超過容差 {contact.tolerance_mm:.3f} mm"
    if contact.region is None:
        return None
    frame = scene.resolve_frame(contact.region.frame, state)
    lower = np.maximum(bounds[0][0], bounds[1][0])
    upper = np.minimum(bounds[0][1], bounds[1][1])
    local = np.linalg.inv(frame) @ np.append((lower + upper) / 2.0, 1.0)
    if contact.region.size_mm is not None:
        width, height = contact.region.size_mm
        margin = CONTACT_REGION_MARGIN_MM
        if abs(local[0]) > width / 2 + margin or abs(local[1]) > height / 2 + margin:
            return (
                f"接觸點不在宣告區域 {contact.region.frame} 內"
                f"（x {local[0]:.1f}、y {local[1]:.1f} mm；區域 {width:g}×{height:g} mm）"
            )
    if contact.direction is not None and motion is not None:
        moved = frame[:3, :3].T @ motion
        length = float(np.linalg.norm(moved))
        expected = np.asarray(contact.direction, dtype=float)
        expected /= np.linalg.norm(expected)
        if length > CONTACT_MOTION_EPS_MM:
            # 方向視為軸線：沿宣告方向接近或沿原路撤離都合法，橫向滑入才不符。
            cosine = abs(float(moved @ expected)) / length
            angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
            if angle > CONTACT_DIRECTION_TOLERANCE_DEG:
                return f"接近方向與宣告不符（與宣告軸線夾角 {angle:.0f}°）"
    return None


def _finish_segment(pair: tuple[str, str], segment: dict[str, Any]) -> dict[str, Any]:
    worst: _Observation = segment["worst"]
    if worst.contact is not None:
        within = worst.violation is None
        detail = f"宣告接觸 {worst.contact}：" + (
            f"最大穿透 {max(0.0, -worst.distance):.3f} mm，在容差 {worst.tolerance:g} mm 內"
            if within
            else str(worst.violation)
        )
        return {
            "type": "interference",
            "severity": "green" if within else "red",
            "t": round(worst.t, 6),
            "objects": list(pair),
            "detail": detail,
            "suggestion": None if within else "檢查壓入量、接觸位置與接近方向是否符合宣告",
            "value": worst.distance,
            "min_dist_mm": worst.distance,
            "limit": -float(worst.tolerance or 0.0),
            "unit": "mm",
            "source": worst.source,
            "contact_id": worst.contact,
        }
    severity = _severity(
        worst.distance,
        allowed=worst.allowed,
        static_pair=worst.static_pair,
        support=worst.support,
    )
    assert severity is not None
    clearance = max(0.0, -worst.distance) + WARNING_DISTANCE_MM
    detail = f"最小帶號距離 {worst.distance:.3f} mm"
    if worst.allowed:
        detail += "；此 tool 正在驅動護蓋，允許接觸"
    return {
        "type": "interference",
        "severity": severity,
        "t": round(worst.t, 6),
        "objects": list(pair),
        "detail": detail,
        "suggestion": (
            None if worst.allowed else f"{pair[0]} 沿逼近方向後退至少 {math.ceil(clearance):d} mm"
        ),
        "value": worst.distance,
        "min_dist_mm": worst.distance,
        "limit": 0.0,
        "unit": "mm",
        "source": worst.source,
    }


def run_collision_checks(
    scene: SceneModel, process: Process, timeline: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Sample the timeline and return merged interference items and engine metrics."""

    parts = build_collision_parts(scene)
    fcl_objects = {part.key: fcl.CollisionObject(part.geometry) for part in parts}
    spans = _driven_pairs(process, timeline, set(scene.parts))
    contact_windows = _contact_windows(process, timeline)
    previous_transforms: dict[float, dict[str, np.ndarray]] = {}

    def transforms_before(t: float) -> dict[str, np.ndarray]:
        key = max(0.0, t - SAMPLE_PERIOD_S)
        if key not in previous_transforms:
            previous_transforms[key] = world_transforms(scene, state_at(timeline, key))
        return previous_transforms[key]

    support_windows = _support_windows(scene, process, timeline)
    active: dict[tuple[str, str], dict[str, Any]] = {}
    finished: list[dict[str, Any]] = []
    previous_signature: tuple[Any, ...] | None = None
    samples = 0
    pairs_evaluated = 0

    for t in _sample_times(float(timeline.get("duration_s", 0.0))):
        state = state_at(timeline, t)
        signature = _state_signature(state)
        if signature == previous_signature:
            continue
        previous_signature = signature
        samples += 1
        transforms = world_transforms(scene, state)
        bounds: dict[str, np.ndarray] = {}
        for part in parts:
            matrix = transforms[part.name]
            vertices = _world_vertices(part, matrix)
            bounds[part.key] = np.asarray([vertices.min(axis=0), vertices.max(axis=0)])
            _set_transform(fcl_objects[part.key], matrix)

        observations: dict[tuple[str, str], _Observation] = {}
        for index, other in _broadphase_candidates(parts, bounds):
            first, second = parts[index], parts[other]
            static_pair = first.static and second.static
            if static_pair and t > 1e-9:
                continue
            if _excluded(scene, first, second, state):
                continue
            aabb_a, aabb_b = bounds[first.key], bounds[second.key]
            distance, source = _signed_distance(
                fcl_objects[first.key], fcl_objects[second.key], aabb_a, aabb_b
            )
            pairs_evaluated += 1
            pair = tuple(sorted((first.name, second.name)))
            declared = _declared_contact(contact_windows, first, second, t)
            if declared is not None:
                contact, first_is_a = declared
                if distance >= 0:
                    continue
                a, b = (first, second) if first_is_a else (second, first)
                before = transforms_before(t)
                motion = (transforms[a.name][:3, 3] - before[a.name][:3, 3]) - (
                    transforms[b.name][:3, 3] - before[b.name][:3, 3]
                )
                violation = _contact_violation(
                    scene, contact, state, distance, (aabb_a, aabb_b), motion
                )
                observation = _Observation(
                    t=t,
                    distance=distance,
                    source=source,
                    allowed=violation is None,
                    static_pair=static_pair,
                    support=False,
                    contact=contact.id,
                    violation=violation,
                    tolerance=contact.tolerance_mm,
                )
                current = observations.get(pair)
                if current is None or observation.worse_than(current):
                    observations[pair] = observation
                continue
            allowed = _is_driven(pair, t, spans)
            support = _is_support_pair(first, second, t, support_windows, state) or (
                first.module != second.module and _mounted(scene, first.module, second.module)
            )
            if (
                _severity(
                    distance,
                    allowed=allowed,
                    static_pair=static_pair,
                    support=support,
                )
                is None
            ):
                continue
            current = observations.get(pair)
            if current is None or distance < current.distance:
                observations[pair] = _Observation(
                    t=t,
                    distance=distance,
                    source=source,
                    allowed=allowed,
                    static_pair=static_pair,
                    support=support,
                )

        missing = set(active) - set(observations)
        for pair in sorted(missing):
            finished.append(_finish_segment(pair, active.pop(pair)))
        for pair, observation in observations.items():
            if pair not in active:
                active[pair] = {"worst": observation}
            elif observation.worse_than(active[pair]["worst"]):
                active[pair]["worst"] = observation

    for pair in sorted(active):
        finished.append(_finish_segment(pair, active[pair]))
    finished.sort(key=lambda item: (item["t"], item["objects"]))
    for index, item in enumerate(finished, 1):
        item["id"] = f"CHK-INT-{index:03d}"
    return finished, {
        "collision": "fcl-collide-depth-gjk-distance-20ms",
        "native_fcl": True,
        "samples": samples,
        "pairs_evaluated": pairs_evaluated,
    }
