"""Deterministic L1 checks over the simulated articulated scene."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from cellforge.build.modules import BuiltModule, build_module, load_part
from cellforge.schema.models import Cell, Process, Workpiece
from cellforge.sim import SceneModel, build_parts
from cellforge.sim.sampling import state_at

from .collision import run_collision_checks


def _item(check_id: str, kind: str, severity: str, **values: Any) -> dict[str, Any]:
    return {"id": check_id, "type": kind, "severity": severity, **values}


def _make_scene(
    cell: Cell,
    workpiece: Workpiece,
    process: Process,
    vendors: dict[str, dict[str, Any]],
) -> SceneModel:
    station_by_module = {
        module_id: station.id for station in process.stations for module_id in station.modules
    }
    modules: list[BuiltModule] = []
    for machine in cell.machines:
        for instance in machine.modules:
            built = build_module(instance, vendors)
            built.station = station_by_module.get(instance.id)
            modules.append(built)
    return SceneModel(cell, modules, build_parts(workpiece, process))


def _keys_in_span(track: list[list[Any]], t0: float, t1: float) -> int:
    return sum(t0 - 1e-9 <= float(key[0]) <= t1 + 1e-9 for key in track)


def _reachability(process: Process, timeline: dict[str, Any]) -> list[dict[str, Any]]:
    process_steps = {step.id: step for step in process.steps}
    failures_by_step: dict[str, list[dict[str, Any]]] = {}
    for failure in timeline.get("ik_failures", []):
        failures_by_step.setdefault(str(failure["step_id"]), []).append(failure)
    jumps_by_step = {
        str(item["step_id"]): item for item in timeline.get("path_discontinuities", [])
    }
    output = []
    index = 0
    for timed in timeline.get("steps", []):
        step = process_steps.get(str(timed.get("id")))
        if step is None:
            continue
        cover_tracking = step.action == "actuate" and bool(step.driven_by)
        if step.action not in {"move_to", "flip"} and not cover_tracking:
            continue
        robot = step.driven_by if cover_tracking else step.actor
        track = timeline.get("nodes", {}).get(robot, {}).get("joints_deg", [])
        is_path = (
            step.action == "flip"
            or cover_tracking
            or (isinstance(step.value, dict) and step.value.get("linear"))
        )
        total = (
            max(1, _keys_in_span(track, float(timed["t0"]), float(timed["t1"]))) if is_path else 1
        )
        failures = failures_by_step.get(step.id, [])
        failed = [
            failure
            for failure in failures
            if float(failure["position_error_mm"]) > 1.0
            or float(failure["orientation_error_deg"]) > 1.0
        ]
        worst = max(failed, key=lambda failure: float(failure["position_error_mm"]), default=None)
        passed = max(0, total - len(failed))
        index += 1
        jump = jumps_by_step.get(step.id)
        if jump is not None and worst is None:
            output.append(
                _item(
                    f"CHK-REACH-{index:03d}",
                    "reachability",
                    "red",
                    t=float(jump["t"]),
                    value=float(jump["jump_deg"]),
                    unit="deg",
                    objects=[robot],
                    detail=(
                        f"直線移動 {step.id} 在 t={float(jump['t']):.2f}s 處 IK 跳解："
                        f"{jump['joint']} 在相鄰取樣點之間變化 {float(jump['jump_deg']):.1f}°，"
                        "加密取樣也無法縮小，無法以連續直線路徑到達"
                    ),
                    suggestion="改為非直線 move_to、調整目標姿態，或移動手臂基座避開奇異與解支切換",
                    source="timeline.path_discontinuities",
                )
            )
            continue
        output.append(
            _item(
                f"CHK-REACH-{index:03d}",
                "reachability",
                "red" if worst else "green",
                t=float(worst["t"]) if worst else float(timed["t1"]),
                value=float(worst["position_error_mm"]) if worst else 0.0,
                limit=1.0,
                unit="mm",
                objects=[robot],
                detail=(
                    f"{passed}/{total} 目標點可達"
                    + (
                        f"；最差姿態誤差 {float(worst['orientation_error_deg']):.3f}°"
                        if worst
                        else ""
                    )
                ),
                suggestion="移動手臂基座、調整逼近姿態或選用較長工作半徑機型" if worst else None,
                source="timeline.ik_failures 與 IK 路徑樣本",
            )
        )
    return output


def _joint_limits(scene: SceneModel, timeline: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    index = 0
    for robot, module in scene.robots.items():
        track = timeline.get("nodes", {}).get(robot, {}).get("joints_deg", [])
        if not track:
            continue
        for column, joint in enumerate(module.chain.active_joints, 1):
            low, high = module.chain.limits[column - 1]
            candidates = []
            for key in track:
                value = float(key[column])
                if np.isfinite(low) and np.isfinite(high) and high > low:
                    midpoint = (low + high) / 2.0
                    ratio = abs(value - midpoint) / ((high - low) / 2.0)
                else:
                    ratio = 0.0
                violation = max(float(low - value), float(value - high), 0.0)
                candidates.append((violation > 0, ratio, float(key[0]), value))
            exceeded, ratio, t, value = max(candidates, key=lambda item: (item[0], item[1]))
            severity = "red" if exceeded else "yellow" if ratio >= 0.9 else "green"
            limit = float(low if value < (low + high) / 2.0 else high)
            index += 1
            output.append(
                _item(
                    f"CHK-JOINT-{index:03d}",
                    "joint_limit",
                    severity,
                    t=t,
                    value=value,
                    limit=limit,
                    unit="deg" if joint.type != "prismatic" else "mm",
                    objects=[f"{robot}.{joint.id}"],
                    detail=(
                        f"{joint.id} 使用範圍比例 {ratio * 100:.1f}%，限制 [{low:.3f}, {high:.3f}]"
                    ),
                    suggestion="重新求解路徑，使關節遠離極限" if severity != "green" else None,
                    source="timeline 關節樣本與運動鏈限制",
                )
            )
    return output


def _tool_mass(module: BuiltModule) -> float:
    if module.definition.tool_mass_kg is not None:
        return float(module.definition.tool_mass_kg)
    tool = module.instance.params.get("tool") or {}
    if not isinstance(tool, dict):
        return 0.0
    if "mass_kg" in tool:
        return float(tool["mass_kg"])
    part = tool.get("part")
    if part:
        definition = getattr(load_part(str(part)), "MODULE", None)
        if definition is not None and definition.payload_kg is not None:
            return float(definition.payload_kg)
    return 0.0


def _max_speed(track: list[list[Any]], column: int = 1) -> tuple[float, float]:
    maximum = 0.0
    at = float(track[0][0]) if track else 0.0
    for first, second in zip(track, track[1:], strict=False):
        elapsed = float(second[0]) - float(first[0])
        if elapsed <= 1e-12:
            continue
        speed = abs(float(second[column]) - float(first[column])) / elapsed
        if speed > maximum:
            maximum, at = speed, float(second[0])
    return maximum, at


def _hardware(
    scene: SceneModel,
    workpiece: Workpiece,
    timeline: dict[str, Any],
) -> list[dict[str, Any]]:
    output = []
    index = 0
    for robot, module in scene.robots.items():
        held, held_mass = _held_by(scene, timeline, f"{robot}.tool")
        payload = module.definition.payload_kg
        if payload is not None:
            load = held_mass + _tool_mass(module) if held else 0.0
            index += 1
            output.append(
                _item(
                    f"CHK-HW-{index:03d}",
                    "hardware",
                    "red" if load > payload else "green",
                    t=float(held[0][0]) if held else 0.0,
                    value=load,
                    limit=float(payload),
                    unit="kg",
                    objects=[robot],
                    detail=f"夾持期間負載 {load:.3f}/{float(payload):.3f} kg",
                    suggestion="降低工具或工件質量，或選用較高負載手臂" if load > payload else None,
                    source="工件質量、工具質量與模組 payload_kg",
                )
            )
        elif held:
            # 原廠 URDF 通常不含額定負載：實際夾持卻無從比較時明示未評估，不可默默略過。
            load = held_mass + _tool_mass(module)
            index += 1
            output.append(
                _item(
                    f"CHK-HW-{index:03d}",
                    "hardware",
                    "yellow",
                    t=float(held[0][0]),
                    value=load,
                    unit="kg",
                    objects=[robot],
                    detail=(
                        f"夾持期間負載 {load:.3f} kg；{robot} 沒有額定負載（payload_kg），未評估"
                    ),
                    suggestion="向廠商確認額定負載，登記於 vendor 條目 limits.payload_kg 後重建",
                    source="工件質量、工具質量；模組缺少 payload_kg",
                )
            )
        track = timeline.get("nodes", {}).get(robot, {}).get("joints_deg", [])
        for column, joint in enumerate(module.chain.active_joints, 1):
            if joint.max_speed is None or not track:
                continue
            speed, at = _max_speed(track, column)
            index += 1
            output.append(
                _item(
                    f"CHK-HW-{index:03d}",
                    "hardware",
                    "red" if speed > joint.max_speed + 1e-9 else "green",
                    t=at,
                    value=speed,
                    limit=float(joint.max_speed),
                    unit="deg/s" if joint.type != "prismatic" else "mm/s",
                    objects=[f"{robot}.{joint.id}"],
                    detail=f"峰值速度 {speed:.3f}/{joint.max_speed:.3f}",
                    suggestion="增加動作時間或降低 speed_scale"
                    if speed > joint.max_speed
                    else None,
                    source="timeline 關節樣本差分與運動鏈速度限制",
                )
            )

    for module_name, module in scene.modules.items():
        if module.chain is not None:
            continue
        for axis in module.definition.axes:
            name = f"{module_name}.{axis.id}"
            node = timeline.get("nodes", {}).get(name, {})
            key = "value_deg" if axis.type == "revolute" else "value_mm"
            track = node.get(key, [])
            if not track:
                continue
            low, high = axis.range_deg if axis.type == "revolute" else axis.range_mm
            worst = max(track, key=lambda item: max(low - float(item[1]), float(item[1]) - high))
            value = float(worst[1])
            exceeded = value < low or value > high
            index += 1
            output.append(
                _item(
                    f"CHK-HW-{index:03d}",
                    "hardware",
                    "red" if exceeded else "green",
                    t=float(worst[0]),
                    value=value,
                    limit=float(low if value < low else high),
                    unit="deg" if axis.type == "revolute" else "mm",
                    objects=[name],
                    detail=f"軸行程 {value:.3f}，範圍 [{low:.3f}, {high:.3f}]",
                    suggestion="調整模組軸行程或選用較長行程致動器" if exceeded else None,
                    source="timeline 模組軸樣本與 ModuleDef range",
                )
            )
            speed_limit = axis.max_speed_dps if axis.type == "revolute" else axis.max_speed_mm_s
            if speed_limit is not None:
                speed, at = _max_speed(track)
                index += 1
                output.append(
                    _item(
                        f"CHK-HW-{index:03d}",
                        "hardware",
                        "red" if speed > speed_limit + 1e-9 else "green",
                        t=at,
                        value=speed,
                        limit=float(speed_limit),
                        unit="deg/s" if axis.type == "revolute" else "mm/s",
                        objects=[name],
                        detail=f"軸峰值速度 {speed:.3f}/{speed_limit:.3f}",
                        suggestion="增加致動時間或降低軸速度" if speed > speed_limit else None,
                        source="timeline 模組軸樣本差分與 ModuleDef max_speed",
                    )
                )

    for part_id, part in scene.parts.items():
        covers = part.sku.covers if part.sku is not None else []
        if not covers and len(scene.parts) > 1:
            continue
        cover_ids = {cover.id for cover in covers}
        animated = {
            node.removeprefix(f"{part_id}.")
            for node, track in timeline.get("nodes", {}).items()
            if node.startswith(f"{part_id}.")
            and track.get("value_deg")
            and len({round(float(key[1]), 9) for key in track["value_deg"]}) > 1
        }
        missing = sorted(cover_ids - animated)
        coverage = f"護蓋開關動畫覆蓋 {len(animated)}/{len(cover_ids)}"
        index += 1
        output.append(
            _item(
                f"CHK-HW-{index:03d}",
                "hardware",
                "red" if missing else "green",
                value=float(len(animated)),
                limit=float(len(cover_ids)),
                unit="covers",
                objects=[f"{part_id}.{cover}" for cover in sorted(cover_ids)],
                detail=f"{coverage}；缺少：{', '.join(missing) or '無'}",
                suggestion="為缺少的護蓋加入開啟與關閉動作" if missing else None,
                source="workpiece.yaml 與 timeline 護蓋軌跡",
            )
        )
    return output


def _held_by(
    scene: SceneModel, timeline: dict[str, Any], tool: str
) -> tuple[list[list[Any]], float]:
    """Attachment keys that put a part on ``tool`` and the heaviest load carried at once.

    被夾零件上承載的其他零件（例如載盤上的板子）也一併算入負載。
    """

    nodes = timeline.get("nodes", {})
    held = sorted(
        (
            key
            for part_id in scene.parts
            for key in nodes.get(part_id, {}).get("attached_to", [])
            if key[1] == tool
        ),
        key=lambda key: float(key[0]),
    )
    heaviest = 0.0
    for key in held:
        state = state_at(timeline, float(key[0]))
        carried = {part_id for part_id in scene.parts if state.part(part_id).holder == tool}
        frontier = set(carried)
        while frontier:
            frontier = {
                part_id
                for part_id in scene.parts
                if state.part(part_id).holder in frontier and part_id not in carried
            }
            carried |= frontier
        heaviest = max(heaviest, sum(scene.parts[part_id].mass_kg for part_id in carried))
    return held, heaviest


def _process_contracts(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    """每個動作契約一項：完成為綠；前置條件或路徑失敗為紅並附固定代碼與原因。"""

    output = []
    results = [item for item in timeline.get("action_results", []) if item["action"] != "inspect"]
    for index, result in enumerate(results, 1):
        failed = result["status"] == "failed"
        label = f"{result['step_id']} {result['action']}"
        detail = (
            f"{label} 失敗（{result['reason_code']}）：{result['reason']}"
            if failed
            else f"{label} 完成"
        )
        output.append(
            _item(
                f"CHK-PROC-{index:03d}",
                "process",
                "red" if failed else "green",
                t=float(result["t0"] if failed else result["t1"]),
                objects=list(result.get("objects", [])),
                detail=detail,
                suggestion="依失敗原因修正前置條件、工具或路徑後重建" if failed else None,
                source="timeline.action_results（動作契約的前置條件、工具與路徑）",
            )
        )
    return output


def _vision(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    """檢測步驟：相機無法判定為紅；可判定時逐 ROI 列出依狀態模型的 OK／NG。"""

    output = []
    index = 0
    note = "判定值來自壓合狀態模型的間隙，不是實拍影像的演算法結果"
    inspections = [
        item for item in timeline.get("action_results", []) if item["action"] == "inspect"
    ]

    def final_ok(roi: str, after: float) -> bool:
        """同一 ROI 之後最後一次可判定的檢測為 OK（例如補壓後複檢）。"""
        later = [
            item["details"]["rois"][roi]["judgement"]
            for item in inspections
            if float(item["t1"]) > after + 1e-9
            and roi in (item.get("details") or {}).get("rois", {})
            and (item.get("details") or {})["rois"][roi].get("judgement") in {"OK", "NG"}
        ]
        return bool(later) and later[-1] == "OK"

    for result in timeline.get("action_results", []):
        if result["action"] != "inspect":
            continue
        rois = (result.get("details") or {}).get("rois", {})
        camera = (result.get("details") or {}).get("camera")
        if result["status"] == "failed":
            index += 1
            output.append(
                _item(
                    f"CHK-VIS-{index:03d}",
                    "vision",
                    "red",
                    t=float(result["t1"]),
                    objects=[camera, *result.get("objects", [])],
                    detail=f"{result['step_id']} {result['reason']}",
                    suggestion="調整相機位置、工作距離或視角，或改用視野／景深合適的鏡頭",
                    source="相機幾何視野、薄透鏡景深、像素解析度與碰撞外形遮蔽",
                )
            )
            continue
        limit = (result.get("details") or {}).get("max_gap_mm")
        for roi, evaluation in rois.items():
            judgement = evaluation.get("judgement")
            if judgement is None:
                continue
            index += 1
            gap = float(evaluation["gap_mm"])
            corrected = judgement == "NG" and final_ok(roi, float(result["t1"]))
            severity = "green" if judgement == "OK" else "yellow" if corrected else "red"
            if corrected:
                judgement = "NG，補壓後複檢 OK"
            output.append(
                _item(
                    f"CHK-VIS-{index:03d}",
                    "vision",
                    severity,
                    t=float(result["t1"]),
                    objects=[roi.partition(".")[0]],
                    value=gap,
                    limit=float(limit) if limit is not None else None,
                    unit="mm",
                    detail=f"{result['step_id']} {roi} 間隙 {gap:.3f} mm：{judgement}（{note}）",
                    suggestion="原位補壓後複檢" if severity == "red" else None,
                    source=f"{camera} 取像；{note}",
                )
            )
    return output


def _takt(process: Process, timeline: dict[str, Any]) -> dict[str, Any]:
    effective = float(timeline.get("duration_s", 0.0)) / max(process.takt.parallel_workpieces, 1)
    target = float(process.takt.target_s)
    occupancies = {
        str(station["id"]): max(0.0, float(station["t1"]) - float(station["t0"]))
        for station in timeline.get("stations", [])
    }
    bottleneck, bottleneck_time = max(
        occupancies.items(), key=lambda item: item[1], default=("無", 0.0)
    )
    detail = "、".join(f"{name} {duration:.2f}s" for name, duration in occupancies.items())
    severity = "red" if effective > target * 1.1 else "yellow" if effective > target else "green"
    return _item(
        "CHK-TAKT-001",
        "takt",
        severity,
        value=effective,
        limit=target,
        unit="s",
        objects=list(occupancies),
        detail=(
            f"有效節拍 {effective:.2f}/{target:.2f}s；站別佔用：{detail}；瓶頸 {bottleneck}，"
            f"若各站可同時處理不同工件，理論穩態節拍約 {bottleneck_time:.2f}s"
        ),
        suggestion="縮短瓶頸站動作或提高並行工件數" if severity != "green" else None,
        source="timeline 總長、parallel_workpieces 與站別佔用",
    )


def _mark_approximated_models(scene: SceneModel, items: list[dict[str, Any]]) -> None:
    """涉及近似廠商模型的檢查必須明示：數值來自型錄尺寸近似，不代表原廠真機。"""

    approximated = {name for name, module in scene.modules.items() if module.approximated}
    for item in items:
        hit = sorted({str(name).split(".")[0] for name in item.get("objects", [])} & approximated)
        if not hit:
            continue
        item["approximated_models"] = hit
        note = f"{'、'.join(hit)} 為近似廠商模型（approximated stub），結果不代表原廠真機"
        item["source"] = f"{item['source']}；{note}" if item.get("source") else note


def run_checks(
    cell: Cell,
    workpiece: Workpiece,
    process: Process,
    timeline: dict[str, Any],
    version: int,
    vendors: dict[str, dict[str, Any]] | None = None,
    *,
    scene: SceneModel | None = None,
) -> dict[str, Any]:
    vendors = vendors or {}
    scene = scene or _make_scene(cell, workpiece, process, vendors)
    interference, engine = run_collision_checks(scene, process, timeline)
    items = [
        *interference,
        *_reachability(process, timeline),
        *_joint_limits(scene, timeline),
        *_hardware(scene, workpiece, timeline),
        *_process_contracts(timeline),
        *_vision(timeline),
        _takt(process, timeline),
    ]
    _mark_approximated_models(scene, items)
    summary = {
        color: sum(item["severity"] == color for item in items)
        for color in ("red", "yellow", "green")
    }
    return {
        "version": version,
        "generated": datetime.now().astimezone().isoformat(),
        "summary": summary,
        "items": items,
        "engine": engine,
    }
