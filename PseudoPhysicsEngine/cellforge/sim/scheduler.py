"""Dependency validation and earliest-startable process scheduling."""

from __future__ import annotations

import fnmatch
from collections import defaultdict

from cellforge.schema.models import Process, ProcessStep

from .engine import Simulator
from .scene import SceneModel
from .workpiece import PRIMARY_PART

WORKPIECE_ACTIONS = {
    "grip",
    "attach",
    "release",
    "detach",
    "transfer",
    "flip",
    "pick",
    "place",
    "insert",
}
# 同時作用於多個零件的契約（objects），各零件的步驟依序執行。
MULTI_OBJECT_ACTIONS = {"press", "inspect"}


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


def _objects(step: ProcessStep, part_ids: set[str], held: set[str]) -> set[str]:
    """Parts whose state a step reads or changes; steps on one part run in order."""
    if step.action in WORKPIECE_ACTIONS:
        return {step.object or PRIMARY_PART}
    if step.action in MULTI_OBJECT_ACTIONS:
        return set(step.objects) | ({step.object} if step.object else set())
    owner = step.actor.partition(".")[0]
    if "." in step.actor and owner in part_ids:
        return {owner}
    if step.action in {"move_to", "move_joint"}:
        return set(held)
    return set()


def _dependencies(process: Process, part_ids: set[str] | None = None) -> dict[str, set[str]]:
    part_ids = part_ids or {PRIMARY_PART}
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
    last_by_object: dict[str, ProcessStep] = {}
    holders: dict[str, set[str]] = defaultdict(set)
    for step in process.steps:
        for resource in _resources(step):
            if resource in last_by_resource:
                dependencies[step.id].add(f"{last_by_resource[resource].id}.done")
            last_by_resource[resource] = step
        for part_id in _objects(step, part_ids, holders[step.actor]):
            if part_id in last_by_object:
                dependencies[step.id].add(f"{last_by_object[part_id].id}.done")
            last_by_object[part_id] = step
        if step.action in {"grip", "attach", "pick"}:
            holders[step.actor].add(step.object or PRIMARY_PART)
        elif step.action in {"release", "detach", "place", "insert"}:
            holders[step.actor].discard(step.object or PRIMARY_PART)
    return dependencies


def validate_schedule(process: Process, part_ids: set[str] | None = None) -> None:
    universe = _event_universe(process)
    dependencies = _dependencies(process, part_ids)
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


def _validate_initial_holders(scene: SceneModel) -> None:
    """每個零件只有一個持有者；初始放置的持有鏈不得成環（例如 A 放在 B 上、B 又放在 A 上）。"""
    holder = {
        part.id: scene.frame_owner(part.initial.frame)
        for part in scene.parts.values()
        if part.initial is not None
    }
    for start in holder:
        seen = [start]
        current = holder.get(start)
        while current in holder:
            if current in seen:
                cycle = " → ".join([*seen[seen.index(current) :], current])
                raise ValueError(f"零件初始持有關係成環：{cycle}")
            seen.append(current)
            current = holder[current]


def _validate_press(scene: SceneModel, step: ProcessStep) -> None:
    if not (step.target or {}).get("frame"):
        raise ValueError(f"步驟 {step.id} 的 press 必須以 target frame 指定壓墊對位位置")
    objects = step.objects or ([step.object] if step.object else [])
    if not objects:
        raise ValueError(f"步驟 {step.id} 的 press 必須以 objects 指定被壓的零件")
    pads = step.press.pads if step.press else []
    if pads and len(pads) != len(objects):
        raise ValueError(f"步驟 {step.id} 的壓墊數 {len(pads)} 與零件數 {len(objects)} 不符")
    face = step.press.face if step.press else "press_face"
    for part_id in objects:
        if not scene.frame_exists(f"{part_id}.{face}"):
            raise ValueError(f"步驟 {step.id} 的零件 {part_id} 沒有壓合面 frame：{face}")


def _validate_inspect(scene: SceneModel, step: ProcessStep) -> None:
    spec = step.inspect
    if spec is None:
        raise ValueError(f"步驟 {step.id} 的 inspect 缺少 inspect 規格（相機、ROI、解析度）")
    try:
        scene.camera(spec.camera, scene.initial_state())
    except (KeyError, ValueError) as error:
        raise ValueError(f"步驟 {step.id} 的相機無法使用：{error}") from error
    owner = spec.camera.partition(".")[0]
    if spec.view is not None and owner != step.actor:
        raise ValueError(f"步驟 {step.id} 以 view 移動相機時，actor 必須是裝相機的手臂 {owner}")
    objects = step.objects or ([step.object] if step.object else [])
    rois = [f"{part_id}.{spec.roi}" for part_id in objects] or [spec.roi]
    for roi in rois:
        if not scene.frame_exists(roi):
            raise ValueError(f"步驟 {step.id} 的 ROI frame 不存在：{roi}")


def validate_process(scene: SceneModel, process: Process) -> None:
    if process.initial_workpiece_frame and not scene.frame_exists(process.initial_workpiece_frame):
        raise ValueError(f"初始工件 frame 不存在：{process.initial_workpiece_frame}")
    for part in scene.parts.values():
        if part.initial is not None and not scene.frame_exists(part.initial.frame):
            raise ValueError(f"零件 {part.id} 的初始 frame 不存在：{part.initial.frame}")
    _validate_initial_holders(scene)
    for contact in process.contacts:
        for element in contact.pair:
            owner = element.partition(".")[0]
            known = [*scene.modules, *scene.parts]
            if any(char in owner for char in "*?["):
                if not fnmatch.filter(known, owner):
                    raise ValueError(f"接觸宣告 {contact.id} 的萬用字元沒有對到任何物件：{element}")
            elif owner not in known:
                raise ValueError(f"接觸宣告 {contact.id} 引用不存在的物件：{element}")
        if contact.region is not None and not scene.frame_exists(contact.region.frame):
            raise ValueError(f"接觸宣告 {contact.id} 的區域 frame 不存在：{contact.region.frame}")
        if contact.tolerance_mm < 0:
            raise ValueError(f"接觸宣告 {contact.id} 的容差不可為負值")
    single = PRIMARY_PART in scene.parts or len(scene.parts) == 1
    for step in process.steps:
        if not scene.actor_exists(step.actor):
            raise ValueError(f"步驟 {step.id} 引用不存在的 actor：{step.actor}")
        if step.object is not None and step.object not in scene.parts:
            raise ValueError(f"步驟 {step.id} 的 object 不是零件：{step.object}")
        if step.action in WORKPIECE_ACTIONS and step.object is None and not single:
            raise ValueError(f"步驟 {step.id} 作用於零件，多零件產品必須以 object 指定零件 id")
        if step.driven_by and step.driven_by not in scene.robots:
            raise ValueError(f"步驟 {step.id} 的 driven_by 不是手臂：{step.driven_by}")
        for part_id in step.objects:
            if part_id not in scene.parts:
                raise ValueError(f"步驟 {step.id} 的 objects 含有不是零件的 id：{part_id}")
        if step.action == "press":
            _validate_press(scene, step)
        if step.action == "inspect":
            _validate_inspect(scene, step)
        robot_actions = {"move_to", "move_joint", "grip", "attach", "release", "detach"}
        if step.action in robot_actions | {"pick", "place", "insert", "press"}:
            if step.actor not in scene.robots:
                raise ValueError(f"步驟 {step.id} 的 {step.action} actor 必須是手臂")
        if step.action in {"place", "insert"} and not (step.target or {}).get("frame"):
            raise ValueError(f"步驟 {step.id} 的 {step.action} 必須指定目標 frame")
        if step.action == "move_to" and not step.target:
            raise ValueError(f"步驟 {step.id} 的 move_to 缺少 target")
        target = step.target or {}
        if "frame" in target and not scene.frame_exists(str(target["frame"])):
            raise ValueError(f"步驟 {step.id} 引用不存在的 frame：{target['frame']}")
        if step.action == "transfer" and step.actor not in scene.modules:
            raise ValueError(f"步驟 {step.id} 的 transfer actor 必須是模組")
        if step.action == "actuate":
            cover_target = target.get("module") in scene.parts and target.get("id")
            if cover_target and not scene.actor_exists(f"{target['module']}.{target['id']}"):
                raise ValueError(f"步驟 {step.id} 引用不存在的護蓋：{target['id']}")
            if not cover_target and step.actor in scene.robots:
                raise ValueError(f"步驟 {step.id} 的手臂 actuate 缺少工件護蓋 target")
        if step.action == "flip" and step.actor not in scene.robots:
            module = scene.modules.get(step.actor)
            if module is None or not any(axis.id == "flip" for axis in module.definition.axes):
                raise ValueError(f"步驟 {step.id} 的 actor 沒有 flip 軸")
    validate_schedule(process, set(scene.parts))


def schedule_process(process: Process, simulator: Simulator) -> dict:
    validate_process(simulator.scene, process)
    simulator.initialize_parts(process.initial_workpiece_frame)
    dependencies = _dependencies(process, set(simulator.scene.parts))
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
