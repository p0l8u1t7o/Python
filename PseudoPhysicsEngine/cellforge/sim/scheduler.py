"""Dependency validation and earliest-startable process scheduling."""

from __future__ import annotations

from collections import defaultdict

from cellforge.schema.models import Process, ProcessStep

from .engine import Simulator
from .scene import SceneModel

WORKPIECE_ACTIONS = {"grip", "attach", "release", "detach", "transfer", "flip"}


def _resources(step: ProcessStep) -> set[str]:
    result = {step.actor}
    if step.driven_by:
        result.add(step.driven_by)
    return result


def _event_universe(process: Process) -> set[str]:
    events = {f"{step.id}.done" for step in process.steps}
    events.update(f"{station.id}.done" for station in process.stations)
    events.update(event for step in process.steps for event in step.emits)
    events.update(event for step in process.steps for event in _action_events(step))
    events.update(f"{step.id}.capture" for step in process.steps if step.action == "capture")
    return events


def _action_events(step: ProcessStep) -> list[str]:
    if step.action != "emit":
        return []
    if isinstance(step.value, str):
        return [step.value]
    if isinstance(step.value, dict) and step.value.get("event"):
        return [str(step.value["event"])]
    return []


def _dependencies(process: Process) -> dict[str, set[str]]:
    station_steps: dict[str, list[ProcessStep]] = defaultdict(list)
    for step in process.steps:
        station_steps[step.station].append(step)
    dependencies = {step.id: set(step.requires) for step in process.steps}
    stations = {station.id: index for index, station in enumerate(process.stations)}
    for station_id, steps in station_steps.items():
        for previous, current in zip(steps, steps[1:], strict=False):
            dependencies[current.id].add(f"{previous.id}.done")
        if steps and not steps[0].requires and stations[station_id] > 0:
            previous_station = process.stations[stations[station_id] - 1].id
            dependencies[steps[0].id].add(f"{previous_station}.done")
    last_by_resource: dict[str, ProcessStep] = {}
    last_workpiece: ProcessStep | None = None
    holders: set[str] = set()
    for step in process.steps:
        for resource in _resources(step):
            if resource in last_by_resource:
                dependencies[step.id].add(f"{last_by_resource[resource].id}.done")
            last_by_resource[resource] = step
        uses_workpiece = (
            step.action in WORKPIECE_ACTIONS
            or step.actor.startswith("workpiece.")
            or (step.actor in holders and step.action in {"move_to", "move_joint"})
        )
        if uses_workpiece:
            if last_workpiece is not None:
                dependencies[step.id].add(f"{last_workpiece.id}.done")
            last_workpiece = step
        if step.action in {"grip", "attach"}:
            holders.add(step.actor)
        elif step.action in {"release", "detach"}:
            holders.discard(step.actor)
    return dependencies


def validate_schedule(process: Process) -> None:
    universe = _event_universe(process)
    dependencies = _dependencies(process)
    unknown = sorted({event for values in dependencies.values() for event in values} - universe)
    if unknown:
        raise ValueError(f"流程 requires 引用不存在的事件：{', '.join(unknown)}")
    produced = set()
    remaining = list(process.steps)
    last_by_station = {
        station.id: next(
            (step.id for step in reversed(process.steps) if step.station == station.id), None
        )
        for station in process.stations
    }
    while remaining:
        ready = [step for step in remaining if dependencies[step.id] <= produced]
        if not ready:
            ids = ", ".join(step.id for step in remaining)
            raise ValueError(f"流程 requires 存在循環或無法滿足的相依：{ids}")
        for step in ready:
            produced.add(f"{step.id}.done")
            produced.update(step.emits)
            produced.update(_action_events(step))
            if last_by_station[step.station] == step.id:
                produced.add(f"{step.station}.done")
            remaining.remove(step)


def validate_process(scene: SceneModel, process: Process) -> None:
    if process.initial_workpiece_frame and not scene.frame_exists(process.initial_workpiece_frame):
        raise ValueError(f"初始工件 frame 不存在：{process.initial_workpiece_frame}")
    for step in process.steps:
        if not scene.actor_exists(step.actor):
            raise ValueError(f"步驟 {step.id} 引用不存在的 actor：{step.actor}")
        if step.driven_by and step.driven_by not in scene.robots:
            raise ValueError(f"步驟 {step.id} 的 driven_by 不是手臂：{step.driven_by}")
        if step.action in {"move_to", "move_joint", "grip", "attach", "release", "detach"}:
            if step.actor not in scene.robots:
                raise ValueError(f"步驟 {step.id} 的 {step.action} actor 必須是手臂")
        if step.action == "move_to" and not step.target:
            raise ValueError(f"步驟 {step.id} 的 move_to 缺少 target")
        target = step.target or {}
        if "frame" in target and not scene.frame_exists(str(target["frame"])):
            raise ValueError(f"步驟 {step.id} 引用不存在的 frame：{target['frame']}")
        if step.action == "transfer" and step.actor not in scene.modules:
            raise ValueError(f"步驟 {step.id} 的 transfer actor 必須是模組")
        if step.action == "actuate":
            cover_target = target.get("module") == "workpiece" and target.get("id")
            if cover_target and not scene.actor_exists(f"workpiece.{target['id']}"):
                raise ValueError(f"步驟 {step.id} 引用不存在的護蓋：{target['id']}")
            if not cover_target and step.actor in scene.robots:
                raise ValueError(f"步驟 {step.id} 的手臂 actuate 缺少工件護蓋 target")
        if step.action == "flip" and step.actor not in scene.robots:
            module = scene.modules.get(step.actor)
            if module is None or not any(axis.id == "flip" for axis in module.definition.axes):
                raise ValueError(f"步驟 {step.id} 的 actor 沒有 flip 軸")
    validate_schedule(process)


def schedule_process(process: Process, simulator: Simulator) -> dict:
    validate_process(simulator.scene, process)
    simulator.initialize_workpiece(process.initial_workpiece_frame)
    dependencies = _dependencies(process)
    event_times: dict[str, float] = {}
    remaining = list(enumerate(process.steps))
    last_by_station = {
        station.id: next(
            (step.id for step in reversed(process.steps) if step.station == station.id), None
        )
        for station in process.stations
    }
    station_names = {station.id: station.name for station in process.stations}
    while remaining:
        candidates: list[tuple[float, int, ProcessStep]] = []
        for index, step in remaining:
            required = dependencies[step.id]
            if required <= event_times.keys():
                start = max((event_times[event] for event in required), default=0.0)
                candidates.append((start, index, step))
        if not candidates:
            ids = ", ".join(step.id for _, step in remaining)
            raise ValueError(f"流程 requires 存在循環或無法滿足的相依：{ids}")
        t0, index, step = min(candidates, key=lambda item: (item[0], item[1]))
        t1, ik = simulator.execute(step, t0)
        simulator.steps.append(
            {
                "id": step.id,
                "station": step.station,
                "actor": step.actor,
                "action": step.action,
                "t0": t0,
                "t1": t1,
                "ik": ik,
            }
        )
        bounds = simulator.station_ranges.setdefault(step.station, [t0, t1])
        bounds[0] = min(bounds[0], t0)
        bounds[1] = max(bounds[1], t1)
        emitted = [f"{step.id}.done", *step.emits, *_action_events(step)]
        if last_by_station[step.station] == step.id:
            emitted.append(f"{step.station}.done")
        for event in emitted:
            event_times[event] = t1
            simulator.events.append({"t": t1, "id": event})
        remaining.remove((index, step))
    timeline = simulator.timeline()
    for station in timeline["stations"]:
        station["name"] = station_names.get(station["id"], station["id"])
    return timeline
