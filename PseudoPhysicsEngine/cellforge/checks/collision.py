"""Native FCL collision sampling for articulated CellForge scenes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import fcl
import numpy as np

from cellforge.build.glb import (
    SceneItem,
    _assembly_meshes,
    _module_item,
    _rest_transforms,
    _workpiece_item,
)
from cellforge.schema.models import Process
from cellforge.sim.sampling import state_at, world_transforms
from cellforge.sim.scene import SceneModel, SimulationState

SAMPLE_PERIOD_S = 0.02
BROADPHASE_MM = 15.0
WARNING_DISTANCE_MM = 10.0
STATIC_PENETRATION_MM = 1.0


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


def _convex(vertices: np.ndarray, faces: np.ndarray) -> Any:
    encoded = np.asarray(
        [value for face in faces for value in (len(face), *(int(index) for index in face))],
        dtype=np.int32,
    )
    return fcl.Convex(np.asarray(vertices, dtype=float), len(faces), encoded)


def _parts(item: SceneItem, *, dynamic_root: bool) -> list[CollisionPart]:
    rest = _rest_transforms(item)
    child_to_axis = {axis.child or axis.id: axis.id for axis in item.definition.axes}
    child_to_axis.update({joint.child: joint.id for joint in item.fixed_joints})
    dynamic_links = set(child_to_axis)
    output: list[CollisionPart] = []
    for index, (part_name, mesh) in enumerate(_assembly_meshes(item.assembly)):
        link = part_name if part_name in dynamic_links else "base"
        local = mesh.copy()
        local.apply_transform(np.linalg.inv(rest[link]))
        hull = local.convex_hull
        if not len(hull.vertices) or not len(hull.faces):
            continue
        suffix = child_to_axis.get(link)
        name = item.id if suffix is None else f"{item.id}.{suffix}"
        is_workpiece = item.id == "workpiece"
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
    if scene.workpiece.assembly is not None:
        parts.extend(_parts(_workpiece_item(scene.workpiece), dynamic_root=True))
    return parts


def _sample_times(duration: float) -> list[float]:
    count = int(math.floor(max(0.0, duration) / SAMPLE_PERIOD_S + 1e-9))
    times = [index * SAMPLE_PERIOD_S for index in range(count + 1)]
    if not times or duration - times[-1] > 1e-9:
        times.append(max(0.0, duration))
    return times


def _state_signature(state: SimulationState) -> tuple[Any, ...]:
    values: list[Any] = [state.attached_to]
    for name, joints in sorted(state.joints.items()):
        values.extend((name, *np.round(joints, 10).tolist()))
    for name, value in sorted(state.axes.items()):
        values.extend((name, round(float(value), 10)))
    values.extend(np.round(state.workpiece_pose.ravel(), 10).tolist())
    return tuple(values)


def _world_vertices(part: CollisionPart, transform: np.ndarray) -> np.ndarray:
    return part.vertices @ transform[:3, :3].T + transform[:3, 3]


def _aabb_distance(first: np.ndarray, second: np.ndarray) -> float:
    delta = np.maximum(0.0, np.maximum(first[0] - second[1], second[0] - first[1]))
    return float(np.linalg.norm(delta))


def _set_transform(obj: Any, matrix: np.ndarray) -> None:
    obj.setTransform(fcl.Transform(matrix[:3, :3], matrix[:3, 3]))


def _signed_distance(first: Any, second: Any, aabb_a: np.ndarray, aabb_b: np.ndarray):
    request = fcl.DistanceRequest(enable_nearest_points=True, enable_signed_distance=True)
    result = fcl.DistanceResult()
    distance = float(fcl.distance(first, second, request, result))
    source = "python-fcl signed distance（20 ms）"
    if distance < 0:
        collision = fcl.CollisionResult()
        fcl.collide(
            first,
            second,
            fcl.CollisionRequest(num_max_contacts=8, enable_contact=True),
            collision,
        )
        depths = [
            float(contact.penetration_depth)
            for contact in collision.contacts
            if math.isfinite(float(contact.penetration_depth))
        ]
        if depths:
            overlap = np.minimum(aabb_a[1], aabb_b[1]) - np.maximum(aabb_a[0], aabb_b[0])
            aabb_depth = max(0.0, float(np.min(overlap)))
            distance = -min(max(depths), aabb_depth)
            source = "python-fcl signed distance；穿透深度 fallback：FCL contact depth"
        else:
            overlap = np.minimum(aabb_a[1], aabb_b[1]) - np.maximum(aabb_a[0], aabb_b[0])
            distance = -max(0.0, float(np.min(overlap)))
            source = "python-fcl；穿透深度 fallback：AABB 最小重疊"
    if not math.isfinite(distance):
        overlap = np.minimum(aabb_a[1], aabb_b[1]) - np.maximum(aabb_a[0], aabb_b[0])
        if np.all(overlap >= 0):
            distance = -float(np.min(overlap))
            source = "python-fcl；穿透深度 fallback：AABB 最小重疊"
        else:
            distance = _aabb_distance(aabb_a, aabb_b)
            source = "python-fcl；距離 fallback：AABB 間距"
    return distance, source


def _adjacent(scene: SceneModel, first: CollisionPart, second: CollisionPart) -> bool:
    if first.module != second.module or first.module == "workpiece":
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
        edges.update(frozenset((joint.parent, joint.child)) for joint in module.chain.joints)
        by_child = {joint.child: joint for joint in module.chain.joints}
        for joint in module.chain.joints:
            if np.linalg.norm(joint.origin[:3, 3]) > 1e-9:
                continue
            previous = by_child.get(joint.parent)
            if previous is not None:
                edges.add(frozenset((previous.parent, joint.child)))
    return frozenset((first_link, second_link)) in edges


def _driven_pairs(
    process: Process, timeline: dict[str, Any]
) -> list[tuple[float, float, str, str]]:
    specifications = {
        step.id: (step.driven_by, _cover_name(step))
        for step in process.steps
        if step.driven_by and _cover_name(step)
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


def _cover_name(step) -> str | None:
    if step.actor.startswith("workpiece."):
        return step.actor
    target = step.target or {}
    if target.get("module") == "workpiece" and target.get("id"):
        return f"workpiece.{target['id']}"
    return None


def _is_driven(pair: tuple[str, str], t: float, spans) -> bool:
    names = frozenset(pair)
    return any(
        t0 - 1e-9 <= t <= t1 + 1e-9 and names == frozenset((tool, cover))
        for t0, t1, tool, cover in spans
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
        return (first.link == "base" and second.cover) or (second.link == "base" and first.cover)
    work, other = (first, second) if first.workpiece else (second, first)
    if not work.workpiece:
        return False
    attached = state.attached_to
    if attached and other.module == attached.partition(".")[0]:
        if attached.endswith(".tool"):
            return other.name == attached
        return True
    return False


def _severity(distance: float, *, allowed: bool, static_pair: bool) -> str | None:
    if allowed:
        return "green"
    if static_pair:
        if distance < -STATIC_PENETRATION_MM:
            return "red"
        return "yellow" if distance < WARNING_DISTANCE_MM else None
    if distance < -1e-6:
        return "red"
    return "yellow" if distance < WARNING_DISTANCE_MM else None


def _finish_segment(pair: tuple[str, str], segment: dict[str, Any]) -> dict[str, Any]:
    worst: _Observation = segment["worst"]
    severity = _severity(worst.distance, allowed=worst.allowed, static_pair=worst.static_pair)
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
    spans = _driven_pairs(process, timeline)
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
        for index, first in enumerate(parts):
            for second in parts[index + 1 :]:
                static_pair = first.static and second.static
                if static_pair and t > 1e-9:
                    continue
                if _excluded(scene, first, second, state):
                    continue
                aabb_a, aabb_b = bounds[first.key], bounds[second.key]
                if _aabb_distance(aabb_a, aabb_b) >= BROADPHASE_MM:
                    continue
                distance, source = _signed_distance(
                    fcl_objects[first.key], fcl_objects[second.key], aabb_a, aabb_b
                )
                pairs_evaluated += 1
                pair = tuple(sorted((first.name, second.name)))
                allowed = _is_driven(pair, t, spans)
                if _severity(distance, allowed=allowed, static_pair=static_pair) is None:
                    continue
                current = observations.get(pair)
                if current is None or distance < current.distance:
                    observations[pair] = _Observation(
                        t=t,
                        distance=distance,
                        source=source,
                        allowed=allowed,
                        static_pair=static_pair,
                    )

        missing = set(active) - set(observations)
        for pair in sorted(missing):
            finished.append(_finish_segment(pair, active.pop(pair)))
        for pair, observation in observations.items():
            if pair not in active:
                active[pair] = {"worst": observation}
            elif observation.distance < active[pair]["worst"].distance:
                active[pair]["worst"] = observation

    for pair in sorted(active):
        finished.append(_finish_segment(pair, active[pair]))
    finished.sort(key=lambda item: (item["t"], item["objects"]))
    for index, item in enumerate(finished, 1):
        item["id"] = f"CHK-INT-{index:03d}"
    return finished, {
        "collision": "fcl-signed-distance-20ms",
        "native_fcl": True,
        "samples": samples,
        "pairs_evaluated": pairs_evaluated,
    }
