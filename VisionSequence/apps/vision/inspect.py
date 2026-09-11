"""檢測任務清單與流程圖之間的無狀態翻譯器。"""

from __future__ import annotations

import copy
import math
import re
from typing import Any

from apps.vision.tools.messages import Msg, parts as message_parts
from apps.core.errors import ValidationError
from apps.vision import inspect_composite as composite
from apps.vision.graph import FLOW_IN, validate_graph
from apps.vision.tasks import base as task_base
from apps.vision.tasks import get as get_definition
from apps.vision.tools import base as tools

TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
SUMMARY_ID = "inspection_summary"
SUMMARY_TASK_ID = "summary"
CUSTOM_REASON_CODES = frozenset({
    "role_missing", "unexpected_node", "tool_changed", "managed_edge_changed",
    "managed_edge_missing", "public_input_changed", "schema_version_unknown",
})


def build(graph: dict[str, Any], task: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """把一項檢測任務加入流程圖，並重算必要檢測彙總。`ctx["composite"]` 為真時放成內建複合工具的實例（P4 起 API 與助手的預設）。"""
    ctx = dict(ctx or {})
    if ctx.get("composite"):
        definition = get_definition(str(task.get("kind") or ""), task.get("version"))
        supplied = {**(task.get("fields") if isinstance(task.get("fields"), dict) else {}), **{k: task[k] for k in definition.fields if k in task}}
        if composite.available(definition.kind, supplied):
            return composite.build_instance(graph, task, ctx)
    out = _clone_graph(graph)
    definition = get_definition(str(task.get("kind") or ""), task.get("version"))
    task = {**task, "task_id": _unique_task_id(out, str(task.get("task_id") or task.get("id") or definition.kind))}
    nodes, edges = definition.build(task, ctx)
    _place_nodes(out, nodes)
    out.setdefault("nodes", []).extend(nodes)
    out.setdefault("edges", []).extend(edges)
    source = ctx.get("image_node") or ctx.get("source_node") or _image_source_node(out, exclude={n["id"] for n in nodes})
    if source is None:
        raise ValidationError("Add an image source before building inspection tasks", code="missing_image_source")
    _connect_image_inputs(out, definition, task["task_id"], str(source))
    _connect_locator(out, task["task_id"], str((task.get("fields") or {}).get("locator") or task.get("locator") or ""))
    _maintain_summary(out)
    return validate_graph(out)


def read(graph: dict[str, Any]) -> dict[str, Any]:
    """從流程圖讀回檢測任務、共用節點與未受管理的節點。"""
    g = _clone_graph(graph)
    nodes = g.get("nodes") or []
    edges = g.get("edges") or []
    piles: dict[str, list[dict[str, Any]]] = {}
    shared: list[dict[str, Any]] = []
    loose: list[dict[str, Any]] = []
    instances: list[dict[str, Any]] = []
    for node in nodes:
        marker = inspect_marker(node)
        if marker:
            if marker["kind"] == "summary":
                shared.append({"id": node["id"], "type": node["type"], "kind": "summary"})
            else:
                piles.setdefault(marker["task_id"], []).append(node)
        elif composite.spec_of(node) is not None:
            instances.append(node)
        elif node.get("type") in ("image_source", "fixed_image", "stereo_grab", "multi_light_grab"):
            shared.append({"id": node["id"], "type": node.get("type")})
        else:
            loose.append({"id": node.get("id"), "type": node.get("type")})
    tasks = [_read_task(task_id, pile, edges, nodes) for task_id, pile in piles.items()]
    tasks.extend(composite.read_instance(node, edges, nodes) for node in instances)
    return {"tasks": tasks, "shared": shared, "loose": loose}


def update(graph: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    """共用 build 重算欄位差異，只替換任務內受管理的參數與接線。"""
    task_id = str(task.get("task_id") or task.get("id") or "")
    if not task_id:
        raise ValidationError("task_id is required", code="missing_task_id")
    if _instance(graph, task_id) is not None:
        return composite.update_instance(graph, task_id, task)
    out = _clone_graph(graph)
    nodes = _task_nodes(out, task_id)
    if not nodes:
        raise ValidationError(f"Inspection task '{task_id}' was not found", code="task_not_found")
    marker = inspect_marker(nodes[0]) or {}
    current = _read_task(task_id, nodes, out.get("edges", []), out["nodes"])
    if current["custom"]:
        raise ValidationError("Edit this custom task in the advanced flow", code="custom_task")
    definition = get_definition(current["kind"], current["version"])
    supplied = dict(task.get("fields") if isinstance(task.get("fields"), dict) else {})
    supplied.update({k: task[k] for k in definition.fields if k in task})
    fields = {**current["fields"], **supplied}
    if "calibration" in definition.fields and "calibration" in supplied and "unit" not in supplied:
        fields["unit"] = "mm" if fields.get("calibration") else "px"
    if "required" in task:
        fields["required"] = task["required"]
    old_nodes, old_edges = definition.build({"task_id": task_id, "fields": current["fields"]}, {})
    new_nodes, new_edges = definition.build({"task_id": task_id, "fields": fields}, {})
    # 節點名稱不是任務歸屬；進階畫布改名後仍以角色對應原本節點。
    actual_ids = {f"{task_id}_{role}": nid for role, nid in current["nodes"].items()}
    for generated in (old_nodes, new_nodes):
        for node in generated:
            node["id"] = actual_ids.get(node["id"], node["id"])
    for generated in (old_edges, new_edges):
        for link in generated:
            link["source"] = actual_ids.get(link["source"], link["source"])
            link["target"] = actual_ids.get(link["target"], link["target"])
    before = {inspect_marker(n)["role"]: n for n in old_nodes}
    after = {inspect_marker(n)["role"]: n for n in new_nodes}
    removed_ids = {str(n["id"]) for n in nodes if inspect_marker(n)["role"] not in after}
    node_ids = {str(n["id"]) for n in nodes}
    old_inputs = {(current["nodes"].get(p.role), p.port) for p in definition.inputs_for(current["fields"])}
    image_source = next((e["source"] for e in out.get("edges", []) if (e.get("target"), e.get("target_handle")) in old_inputs and e.get("target_handle") == "image"), None)
    shared_ids = {n["id"] for n in out["nodes"] if (inspect_marker(n) or {}).get("kind") == "summary"}
    if any((e.get("source") in removed_ids and e.get("target") not in node_ids) or
           (e.get("target") in removed_ids and e.get("source") not in node_ids and (e.get("target"), e.get("target_handle")) not in old_inputs)
           for e in out.get("edges", []) if e.get("target") not in shared_ids):
        raise ValidationError("A step needed by another connection would be removed; edit the advanced flow first", code="task_dependency")
    out["nodes"] = [n for n in out["nodes"] if n["id"] not in removed_ids]
    out["edges"] = [e for e in out.get("edges", []) if e.get("source") not in removed_ids and e.get("target") not in removed_ids]
    added = [n for n in new_nodes if inspect_marker(n)["role"] not in before]
    _place_nodes(out, added)
    out["nodes"].extend(added)
    for node in nodes:
        role = inspect_marker(node)["role"]
        if role not in after:
            continue
        old, new = before[role], after[role]
        params = node.setdefault("params", {})
        if node["type"] != new["type"]:
            # 換工具時只帶過仍有效的具名輸出名稱（interface.outputs[].alias），避免舊工具參數污染新工具。
            published = tools.output_aliases(node)
            node["type"] = new["type"]
            node["params"] = copy.deepcopy(new["params"])
            node.pop(tools.INTERFACE_KEY, None)
            ports = {p.key for p in tools.get(new["type"]).outputs}
            retained = {p: name for p, name in published.items() if p in ports}
            retained.update(tools.output_aliases(new))
            for port, name in retained.items():
                tools.set_output_alias(node, port, name)
        else:
            for key in old["params"].keys() | new["params"].keys():
                if old["params"].get(key) == new["params"].get(key):
                    continue
                if key in new["params"]:
                    params[key] = copy.deepcopy(new["params"][key])
                else:
                    params.pop(key, None)
            old_alias, new_alias = tools.output_aliases(old), tools.output_aliases(new)
            if old_alias != new_alias:
                current_alias = tools.output_aliases(node)
                retained_name = next((current_alias[p] for p in old_alias if p in current_alias), None)
                for port in old_alias:
                    tools.set_output_alias(node, port, "")
                for port, name in new_alias.items():
                    tools.set_output_alias(node, port, retained_name if retained_name is not None and "result_name" not in supplied else name)
    def connection(e: dict[str, Any]) -> tuple[str, str, str, str]:
        return tuple(str(e.get(k) or "") for k in ("source", "source_handle", "target", "target_handle"))
    old_connections = {connection(e) for e in old_edges}
    new_connections = {connection(e) for e in new_edges}
    out["edges"] = [e for e in out.get("edges", []) if connection(e) not in old_connections - new_connections]
    out["edges"].extend(e for e in new_edges if connection(e) not in old_connections)
    if image_source:
        _connect_image_inputs(out, definition, task_id, image_source)
    if "required" in supplied or "required" in task:
        required = bool(task.get("required", supplied.get("required", marker.get("required", True))))
        for node in nodes:
            marker = inspect_marker(node)
            if marker:
                marker["required"] = required
    if "locator" in supplied or "locator" in task or set(before) != set(after):
        _connect_locator(out, task_id, str(fields.get("locator") or ""))
    if fields.get("required") != current["required"] or definition.layout_hook:
        _maintain_summary(out)
    return validate_graph(out)


def remove(graph: dict[str, Any], task_id: str) -> dict[str, Any]:
    """刪除任務；若輸出仍被外部使用，回依賴清單且不改圖。"""
    if _instance(graph, task_id) is not None:
        return composite.remove_instance(graph, task_id)
    out = _clone_graph(graph)
    nodes = _task_nodes(out, task_id)
    if not nodes:
        raise ValidationError(f"Inspection task '{task_id}' was not found", code="task_not_found")
    node_ids = {str(n["id"]) for n in nodes}
    deps = _external_users(out, node_ids)
    if deps:
        return {"graph": out, "dependencies": deps, "removed": False}
    out["nodes"] = [n for n in out.get("nodes", []) if str(n.get("id")) not in node_ids]
    out["edges"] = [
        e for e in out.get("edges", [])
        if str(e.get("source")) not in node_ids and str(e.get("target")) not in node_ids
    ]
    _maintain_summary(out)
    return {"graph": validate_graph(out), "dependencies": [], "removed": True}


def evidence(graph: dict[str, Any], report: Any) -> list[dict[str, Any]]:
    """把引擎報告轉成檢測任務的讀值清單。"""
    tasks = read(graph)["tasks"]
    nodes = _report_nodes(report)
    readings: list[dict[str, Any]] = []
    for task in tasks:
        if task.get("kind") == "summary":
            continue
        task_id = task["task_id"]
        instance = _instance(graph, task_id)
        if task["disabled"]:
            nid = task_id if instance is not None else next(n["id"] for n in _task_nodes(graph, task_id) if n.get("enabled") is False)
            readings.append(_reading(task_id, "skipped", False, None, None, task.get("unit", ""), Msg.of("inspect.step_disabled", "A task step is disabled"), [], nid))
            continue
        if task["custom"]:
            reason = task["reasons"][0]
            readings.append(_reading(task_id, "skipped", False, None, None, task.get("unit", ""), Msg.of("inspect.custom_task", "Review this custom task in the advanced flow"), [], reason["node_id"]))
            continue
        roles = composite.report_roles(instance) if instance is not None else (task.get("nodes") or {})
        find_id = roles.get("find")
        tol_id = roles.get("tol")
        align_id = roles.get("align")
        role_ids = [nid for nid in roles.values() if nid]
        reports = {nid: nodes.get(nid, {}) for nid in role_ids}
        missing = [nid for nid, row in reports.items() if not row]
        if missing:
            readings.append(_reading(task_id, "skipped", False, None, None, task.get("unit", ""), Msg.of("inspect.no_result", "No run result is available for this task step"), [], missing[0]))
            continue
        skipped = [nid for nid, row in reports.items() if row.get("status") == "skipped"]
        errors = [nid for nid, row in reports.items() if row.get("status") == "error"]
        overlays = [ov for row in reports.values() for ov in (row.get("overlays") or [])]
        if _skipped_by_locator(graph, task_id, nodes):
            readings.append(_reading(task_id, "locate_failed", False, None, None, task.get("unit", ""), Msg.of("inspect.locate_failed", "Location failed"), [], role_ids[0]))
            continue
        if errors:
            nid = errors[0]
            readings.append(_reading(task_id, "error", False, None, None, task.get("unit", ""), _row_msg(reports[nid]), overlays, nid))
            continue
        if skipped:
            verdict = "locate_failed" if _skipped_by_locator(graph, task_id, nodes) else "skipped"
            readings.append(_reading(task_id, verdict, False, None, None, task.get("unit", ""), Msg.of("inspect.not_run", "The task did not run"), overlays, skipped[0]))
            continue
        if task["kind"] == "locate_part":
            row = reports.get(find_id or "", {})
            if row.get("status") == "ng" or row.get("branch") == "not_found":
                readings.append(_reading(task_id, "not_found", True, False, None, "", _row_msg(row), overlays, find_id or ""))
            else:
                value = (reports.get(align_id or "", {}).get("outputs") or {}).get("transform")
                readings.append(_reading(task_id, "pass", True, True, value, "", _row_msg(reports.get(align_id or "", {})), overlays, align_id or find_id or ""))
            continue
        definition = get_definition(task["kind"], task["version"])
        if definition.layout_hook:
            layout = definition.layout_hook(task["fields"])
            ref = layout.value_port
            value = (reports[roles[ref.role]].get("outputs") or {}).get(ref.port) if ref else None
            row = reports[roles[layout.verdict_role]]
            valid = all((r.get("outputs") or {}).get("valid", True) for r in reports.values())
            detected = (row.get("outputs") or {}).get("detected")
            failed = next((nid for nid, r in reports.items() if r.get("status") != "ok"), None)
            verdict = "pass" if valid and not failed else "fail"
            if task["kind"] == "measure_distance" and any(r.get("branch") == "not_found" or (nid != tol_id and r.get("status") == "ng") for nid, r in reports.items()):
                verdict, detected = "not_found", False
            nid = failed or roles[layout.verdict_role]
            # 展開座標上的掃描標記不疊到原圖；還原節點提供原圖缺陷幾何。
            if task["kind"] == "inspect_circular_surface":
                overlays = reports[roles["restore"]].get("overlays") or []
            reason = _row_msg(reports[nid])
            unit = task.get("unit", "")
            if task["kind"] == "inspect_circular_surface":
                fields = task["fields"]
                counts = [d.get("count", 0) for d in (reports[roles["defect"]].get("outputs") or {}).get("defects", [])]
                per_caliper = .5
                if unit == "mm":
                    region = fields["roi"]
                    radius = (region["r_inner"] + region["r_outer"]) / 2
                    scale = reports[roles["scale"]]["outputs"]["scale"]
                    per_caliper = radius * math.radians(.5) * scale
                longest = max(counts, default=0) * per_caliper
                count_unit = "defect" if value == 1 else "defects"
                reason = f"{int(value or 0)} {count_unit}, longest {longest:.3f} {unit} (minimum {fields['min_length']:.3f} {unit})"
                unit = count_unit
            readings.append(_reading(task_id, verdict, valid, detected, value, unit, reason, overlays, nid))
            continue
        find_row = reports.get(find_id or "", {})
        tol_row = reports.get(tol_id or "", {})
        if find_row.get("status") == "ng" or find_row.get("branch") == "not_found":
            readings.append(_reading(task_id, "not_found", True, False, None, task.get("unit", ""), _row_msg(find_row), overlays, find_id or ""))
            continue
        value = _task_value(task, find_row, tol_row)
        verdict = "pass" if tol_row.get("status") == "ok" else "fail"
        readings.append(_reading(task_id, verdict, True, True, value, task.get("unit", ""), _row_msg(tol_row), overlays, tol_id or find_id or ""))
    for reading in readings:
        if _instance(graph, reading["task_id"]) is not None:
            reading["node_id"] = reading["task_id"]
    return readings


def teach_pose(graph: dict[str, Any], task_id: str, report: Any) -> dict[str, Any]:
    """把定位試跑結果寫回 ref_x/ref_y/ref_angle。"""
    if _instance(graph, task_id) is not None:
        return composite.teach_pose_instance(graph, task_id, report)
    out = _clone_graph(graph)
    nodes = _task_nodes(out, task_id)
    by_role = {inspect_marker(n)["role"]: n for n in nodes if inspect_marker(n)}
    find = by_role.get("find")
    align = by_role.get("align")
    if not find or not align:
        raise ValidationError("The task is not a locator", code="not_locator")
    row = _report_nodes(report).get(str(find["id"]), {})
    outputs = row.get("outputs") or {}
    if row.get("status") != "ok":
        raise ValidationError("The locator did not find a part", code="locate_not_found")
    x = outputs.get("best_x")
    y = outputs.get("best_y")
    angle = outputs.get("best_angle", 0)
    if x is None or y is None:
        matches = outputs.get("matches") or []
        first = matches[0] if matches else {}
        x, y, angle = first.get("cx"), first.get("cy"), first.get("angle", 0)
    try:
        params = align.setdefault("params", {})
        params["ref_x"] = float(x)
        params["ref_y"] = float(y)
        params["ref_angle"] = float(angle or 0)
    except (TypeError, ValueError):
        raise ValidationError("The locator result did not include a usable pose", code="bad_locator_pose") from None
    return validate_graph(out)


def inspect_marker(node: dict[str, Any]) -> dict[str, Any] | None:
    marker = ((node.get("meta") or {}).get("inspect") if isinstance(node.get("meta"), dict) else None)
    return marker if isinstance(marker, dict) else None


def _clone_graph(graph: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(graph or {"nodes": [], "edges": []})


def _unique_task_id(graph: dict[str, Any], base: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", base or "task")[:40] or "task"
    used = {m["task_id"] for n in graph.get("nodes", []) if (m := inspect_marker(n))} | {str(n.get("id")) for n in graph.get("nodes", [])}
    if base not in used:
        return base
    for i in range(2, 1000):
        suffix = f"_{i}"
        candidate = f"{base[:40 - len(suffix)]}{suffix}"
        if candidate not in used:
            return candidate
    raise ValidationError("Could not allocate a task id", code="task_id_exhausted")


def _task_nodes(graph: dict[str, Any], task_id: str) -> list[dict[str, Any]]:
    return [n for n in graph.get("nodes", []) if (m := inspect_marker(n)) and m.get("task_id") == task_id]


def _instance(graph: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    """task_id 是內建複合工具實例的節點 id 時回那個節點。"""
    return next((n for n in graph.get("nodes", []) if str(n.get("id")) == task_id and composite.spec_of(n) is not None), None)


def _task_node_ids(graph: dict[str, Any], task_id: str) -> set[str]:
    ids = {str(n["id"]) for n in _task_nodes(graph, task_id)}
    if not ids and _instance(graph, task_id) is not None:
        ids = {task_id}
    return ids


def _locator_ports(graph: dict[str, Any], locator_id: str) -> tuple[tuple[str, str], tuple[str, str]] | None:
    """定位來源的 (位置修正埠, 找到分支)：定位工具實例或舊的定位任務。"""
    if composite.is_locator(_instance(graph, locator_id)):
        return (locator_id, "align:transform"), (locator_id, "find:found")
    roles = {inspect_marker(n).get("role"): str(n["id"]) for n in _task_nodes(graph, locator_id) if inspect_marker(n)}
    if roles.get("find") and roles.get("align"):
        return (roles["align"], "transform"), (roles["find"], "found")
    return None


def _image_source_node(graph: dict[str, Any], *, exclude: set[str]) -> str | None:
    for node in graph.get("nodes", []):
        if str(node.get("id")) in exclude:
            continue
        if node.get("type") in ("image_source", "fixed_image", "stereo_grab", "multi_light_grab"):
            return str(node.get("id"))
    return None


def _connect_image_inputs(graph: dict[str, Any], definition: task_base.TaskDefinition, task_id: str, source: str) -> None:
    nodes = _task_nodes(graph, task_id)
    fields_item = {"task_id": task_id, "required": bool((inspect_marker(nodes[0]) or {}).get("required")), "fields": {}}
    _read_fields(fields_item, definition, nodes, graph.get("edges", []), graph["nodes"])
    by_role = {inspect_marker(n)["role"]: n["id"] for n in nodes}
    for ref in definition.inputs_for(fields_item["fields"]):
        if ref.port != "image":
            continue
        target = by_role.get(ref.role)
        if target and not any(e.get("target") == target and e.get("target_handle") == "image" for e in graph.get("edges", [])):
            graph.setdefault("edges", []).append(task_base.edge(source, "image", target, "image"))


def _connect_locator(graph: dict[str, Any], task_id: str, locator_id: str) -> None:
    """定位依賴一律兩條線（transform → _transform、found → _flow）；目標與定位來源都可以是舊任務或複合工具實例。"""
    target_ids = _task_node_ids(graph, task_id)
    previous = _locator_for(task_id, graph.get("edges", []), graph.get("nodes", []))
    managed: set[tuple[str, str, str]] = set()
    if previous and (ports := _locator_ports(graph, previous)):
        (align_id, align_port), (find_id, find_port) = ports
        managed = {(align_id, align_port, tools.TRANSFORM_IN), (find_id, find_port, FLOW_IN)}
    graph["edges"] = [
        e for e in graph.get("edges", [])
        if not (str(e.get("target")) in target_ids and (str(e.get("source")), str(e.get("source_handle") or ""), str(e.get("target_handle") or "")) in managed)
    ]
    if not locator_id:
        return
    ports = _locator_ports(graph, locator_id)
    if ports is None:
        raise ValidationError(f"Locator task '{locator_id}' was not found", code="locator_not_found")
    (align_id, align_port), (find_id, find_port) = ports
    if _instance(graph, task_id) is not None:
        targets = [task_id]
    else:
        task = next(t for t in read(graph)["tasks"] if t["task_id"] == task_id)
        definition = get_definition(task["kind"], task["version"])
        locator_roles = definition.layout_hook(task["fields"]).locator_roles if definition.layout_hook else ("find",)
        by_id = {str(n.get("id")): n for n in graph.get("nodes", [])}
        targets = [t for t in sorted(target_ids) if (inspect_marker(by_id.get(t) or {}) or {}).get("role") in locator_roles]
    for target in targets:
        graph.setdefault("edges", []).append(task_base.edge(align_id, align_port, target, tools.TRANSFORM_IN))
        graph.setdefault("edges", []).append(task_base.edge(find_id, find_port, target, FLOW_IN))


def _replace_single_edge(graph: dict[str, Any], target: str, target_port: str, new_edge: dict[str, str]) -> None:
    graph["edges"] = [e for e in graph.get("edges", []) if not (str(e.get("target")) == target and str(e.get("target_handle") or "") == target_port)]
    graph.setdefault("edges", []).append(new_edge)


def _place_nodes(graph: dict[str, Any], nodes: list[dict[str, Any]]) -> None:
    xs = [float((n.get("position") or {}).get("x", 0)) for n in graph.get("nodes", []) if isinstance(n.get("position"), dict)]
    base_x = (max(xs) + 220) if xs else 120
    base_y = 80
    for i, node in enumerate(nodes):
        node.setdefault("position", {"x": base_x + i * 220, "y": base_y})


def _task_port(task: dict[str, Any], ref: task_base.PortRef) -> tuple[str, str]:
    """任務的一個角色埠在圖上的 (節點 id, 把手)：實例＝(實例 id, `<role>:<port>`)。"""
    if task.get("source") == composite.SOURCE:
        return task["task_id"], composite.port_key(ref)
    return task["nodes"][ref.role], ref.port


def _task_flow_ports(graph: dict[str, Any], task: dict[str, Any], role: str) -> list[tuple[str, str]]:
    node_id, _ = _task_port(task, task_base.PortRef(role, ""))
    node = next(n for n in graph["nodes"] if n["id"] == node_id)
    prefix = f"{role}:" if task.get("source") == composite.SOURCE else ""
    return [(node_id, port.key) for port in tools.get(node["type"]).outputs if port.type == "flow" and port.key.startswith(prefix)]


def _maintain_summary(graph: dict[str, Any]) -> None:
    tasks = read({k: v for k, v in graph.items() if k in ("nodes", "edges")})["tasks"]
    required: list[tuple[str, str]] = []
    adapter_ids: set[str] = set()
    for task in tasks:
        if not task.get("required") or task.get("custom"):
            continue
        try:
            definition = get_definition(task["kind"], task.get("version"))
        except ValidationError:
            continue
        layout = definition.layout_hook(task["fields"]) if definition.layout_hook else None
        ref = layout.pass_port if layout else definition.pass_port
        if layout and layout.summary_expression:
            # 單節點任務沒有布林埠時，用既有工具在共用彙總層轉換；控制線防止沿用缺席值。
            adapter_id = f"inspection_result_{task['task_id']}"
            adapter_ids.add(adapter_id)
            adapter = next((n for n in graph["nodes"] if n["id"] == adapter_id), None)
            if adapter is None:
                adapter = task_base.task_node(SUMMARY_TASK_ID, f"result_{task['task_id']}", "formula", {}, "summary", 1, False)
                adapter["id"] = adapter_id
                _place_nodes(graph, [adapter])
                graph["nodes"].append(adapter)
            elif (inspect_marker(adapter) or {}).get("kind") != "summary":
                raise ValidationError("An inspection summary step name is already in use", code="task_id_conflict")
            adapter["params"] = {"expression": layout.summary_expression}
            adapter_edges = []
            for key, source in zip(("a", "b", "c", "d"), layout.summary_inputs):
                adapter_edges.append(task_base.edge(*_task_port(task, source), adapter_id, key))
            for source_id, port_key in _task_flow_ports(graph, task, layout.summary_inputs[0].role):
                adapter_edges.append(task_base.edge(source_id, port_key, adapter_id, FLOW_IN))
            expected_edges = {(e["source"], e["source_handle"], e["target_handle"]) for e in adapter_edges}
            graph["edges"] = [e for e in graph.get("edges", []) if e.get("target") != adapter_id or (e.get("source"), e.get("source_handle"), e.get("target_handle")) in expected_edges]
            existing_edges = {(e.get("source"), e.get("source_handle"), e.get("target_handle")) for e in graph["edges"] if e.get("target") == adapter_id}
            graph["edges"].extend(e for e in adapter_edges if (e["source"], e["source_handle"], e["target_handle"]) not in existing_edges)
            required.append((adapter_id, "result"))
        elif ref is not None:
            required.append(_task_port(task, ref))
    obsolete = {n["id"] for n in graph["nodes"] if (inspect_marker(n) or {}).get("kind") == "summary" and n["type"] == "formula" and n["id"] not in adapter_ids}
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] not in obsolete]
    graph["edges"] = [e for e in graph.get("edges", []) if e.get("source") not in obsolete and e.get("target") not in obsolete]
    if not required:
        graph["nodes"] = [n for n in graph.get("nodes", []) if n.get("id") != SUMMARY_ID]
        graph["edges"] = [e for e in graph.get("edges", []) if e.get("source") != SUMMARY_ID and e.get("target") != SUMMARY_ID]
        return
    summary = next((n for n in graph.get("nodes", []) if n.get("id") == SUMMARY_ID), None)
    if summary is None:
        summary = {
            "id": SUMMARY_ID,
            "type": "inspection_summary",
            "params": {"expected_count": len(required)},
            "meta": {"inspect": {"task_id": SUMMARY_TASK_ID, "role": "summary", "kind": "summary", "schema_version": 1, "required": False}},
            "position": {"x": 120 + len(graph.get("nodes", [])) * 220, "y": 360},
        }
        graph.setdefault("nodes", []).append(summary)
    else:
        summary.setdefault("params", {})["expected_count"] = len(required)
    expected = set(required)
    task_ids = {nid for task in tasks for nid in task["nodes"].values()} | adapter_ids
    graph["edges"] = [e for e in graph.get("edges", []) if not (
        e.get("target") == SUMMARY_ID and e.get("target_handle") == "results"
        and e.get("source") in task_ids and (e.get("source"), e.get("source_handle")) not in expected
    )]
    for node_id, port_key in required:
        if not any(e.get("source") == node_id and e.get("source_handle") == port_key and e.get("target") == SUMMARY_ID and e.get("target_handle") == "results" for e in graph["edges"]):
            graph["edges"].append(task_base.edge(node_id, port_key, SUMMARY_ID, "results"))


def _read_task(task_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], all_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    first = inspect_marker(nodes[0]) or {}
    kind = str(first.get("kind") or "")
    version = first.get("schema_version", 1)
    roles = {inspect_marker(n)["role"]: str(n["id"]) for n in nodes if inspect_marker(n)}
    item: dict[str, Any] = {
        "task_id": task_id,
        "kind": kind,
        "version": version,
        "required": bool(first.get("required")),
        "nodes": roles,
        "fields": {},
        "custom": False,
        "disabled": any(n.get("enabled") is False for n in nodes),
        "reasons": [],
    }
    try:
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError("Unsupported task schema")
        definition = get_definition(kind, version)
        if any((inspect_marker(n).get("kind"), inspect_marker(n).get("schema_version", 1)) != (kind, version) for n in nodes):
            raise ValueError("Inconsistent task schema")
    except (ValidationError, ValueError, TypeError):
        item["custom"] = True
        item["reasons"].append(_reason("schema_version_unknown", str(first.get("role") or ""), str(nodes[0]["id"]), "This task schema is not supported"))
        return item
    _read_fields(item, definition, nodes, edges, all_nodes)
    item["reasons"] = _custom_reasons(task_id, definition, nodes, edges, all_nodes)
    item["custom"] = bool(item["reasons"])
    return item


def _read_fields(item: dict[str, Any], definition: task_base.TaskDefinition, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], all_nodes: list[dict[str, Any]]) -> None:
    by_role = {inspect_marker(n)["role"]: n for n in nodes if inspect_marker(n)}
    fields = item["fields"]
    for key, spec in definition.fields.items():
        if key == "required":
            fields[key] = item["required"]
            continue
        if key == "locator":
            fields[key] = _locator_for(item["task_id"], edges, all_nodes)
            continue
        node = by_role.get(spec.role or "")
        params = node.get("params") if node else {}
        if spec.read is not None and isinstance(params, dict):
            fields[key] = spec.read(params)
        elif spec.param and isinstance(params, dict) and spec.param in params:
            fields[key] = params.get(spec.param)
        else:
            fields[key] = spec.default
    if definition.kind == "measure_diameter":
        tol = by_role.get("tol") or {}
        fields["mode"] = "roundness" if tol.get("type") == "gdt_measure" else "check"
        if fields["mode"] == "roundness":
            fields["upper_tol"] = (tol.get("params") or {}).get("tolerance", 1)
        fields["result_name"] = (tol.get("params") or {}).get("name") or _published_name(by_role.get("find"), "diameter_world" if fields.get("calibration") else "diameter")
        item["unit"] = fields.get("unit") or "px"
    elif definition.kind == "locate_part":
        fields["allow_rotation"] = bool(((by_role.get("align") or {}).get("params") or {}).get("use_angle", False))
    if definition.read_hook:
        definition.read_hook(fields, by_role, edges)
        for key, spec in definition.fields.items():
            if spec.visible_when and any(fields.get(k) not in (v if isinstance(v, list) else [v]) for k, v in spec.visible_when.items()):
                fields[key] = copy.deepcopy(spec.default)
    if "unit" in fields:
        item["unit"] = fields.get("unit") or "px"


def _locator_for(task_id: str, edges: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> str:
    target_ids = _task_node_ids({"nodes": nodes}, task_id)
    by_id = {str(n.get("id")): n for n in nodes}
    for e in edges:
        if str(e.get("target")) not in target_ids or e.get("target_handle") != tools.TRANSFORM_IN:
            continue
        source = by_id.get(str(e.get("source")))
        marker = inspect_marker(source) if source else None
        if marker and marker.get("kind") == "locate_part" and marker.get("role") == "align":
            return str(marker["task_id"])
        if composite.is_locator(source):
            return str(source["id"])
    return ""


def _published_name(node: dict[str, Any] | None, port: str) -> str:
    return tools.output_aliases(node).get(port, "")


def _reason(code: str, role: str, node_id: str, detail: str) -> dict[str, str]:
    """原因代碼是封閉集合，前端只翻譯這些鍵。"""
    assert code in CUSTOM_REASON_CODES
    return {"code": code, "role": role, "node_id": node_id, "detail": detail}


def _custom_reasons(task_id: str, definition: task_base.TaskDefinition, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], all_nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    item = {"task_id": task_id, "required": True, "fields": {}}
    _read_fields(item, definition, nodes, edges, all_nodes)
    fields = item["fields"]
    expected_roles = dict(definition.roles)
    if definition.layout_hook:
        expected_roles = {r: t for r, (t, _) in definition.layout_hook(fields).steps.items()}
    if definition.kind == "measure_diameter" and fields.get("mode") == "roundness" and fields.get("unit") == "mm":
        expected_roles["scale"] = "calibration"
    by_role = {inspect_marker(n)["role"]: n for n in nodes}
    ids = {str(n["id"]) for n in nodes}
    roles = {str(n["id"]): inspect_marker(n)["role"] for n in nodes}
    def role_id(role: str) -> str:
        return str(by_role[role]["id"]) if role in by_role else f"{task_id}_{role}"
    for role, tool_key in expected_roles.items():
        if role not in by_role:
            reasons.append(_reason("role_missing", role, "", f"The task is missing its {role} step"))
        elif by_role[role]["type"] != tool_key and not (definition.kind == "measure_diameter" and role == "tol" and by_role[role]["type"] in ("tolerance_judge", "gdt_measure")):
            reasons.append(_reason("tool_changed", role, role_id(role), f"The tool used for the {role} step has changed"))
    seen_roles: set[str] = set()
    for node in nodes:
        role = inspect_marker(node)["role"]
        if role not in expected_roles or role in seen_roles:
            reasons.append(_reason("unexpected_node", role, str(node["id"]), "The task contains an extra step"))
        seen_roles.add(role)
    expected = {(role_id(e.source_role), e.source_port, role_id(e.target_role), e.target_port) for e in definition.edges_for(fields)}
    actual = {
        (str(e.get("source")), str(e.get("source_handle") or ""), str(e.get("target")), str(e.get("target_handle") or ""))
        for e in edges
        if str(e.get("source")) in ids and str(e.get("target")) in ids
    }
    for entry in sorted(expected - actual):
        reasons.append(_reason("managed_edge_missing", roles.get(entry[2], ""), entry[2] if entry[2] in ids else "", f"Missing {entry[0]}.{entry[1]} -> {entry[2]}.{entry[3]}"))
    for entry in sorted(actual - expected):
        reasons.append(_reason("managed_edge_changed", roles[entry[2]], entry[2], f"Unexpected {entry[0]}.{entry[1]} -> {entry[2]}.{entry[3]}"))
    allowed_inputs = {(role_id(p.role), p.port) for p in definition.inputs_for(fields)}
    by_id = {str(n["id"]): n for n in all_nodes}
    for e in edges:
        target = (str(e.get("target")), str(e.get("target_handle") or ""))
        source = str(e.get("source"))
        if target[0] in ids and source not in ids:
            if target not in allowed_inputs or not _allowed_source(by_id.get(source), str(e.get("source_handle") or ""), target[1]):
                reasons.append(_reason("public_input_changed", roles[target[0]], target[0], f"Unexpected input {source}.{e.get('source_handle') or ''} -> {target[0]}.{target[1]}"))
    for target, port in sorted(allowed_inputs):
        if port == "image" and target in ids and not any(e.get("target") == target and e.get("target_handle") == port for e in edges):
            reasons.append(_reason("public_input_changed", roles[target], target, f"Missing image input for {target}.{port}"))
    return reasons


def _allowed_source(node: dict[str, Any] | None, port_key: str, target_port: str) -> bool:
    """只接受公開輸入宣告的影像、區域、位置修正與控制來源。"""
    if node is None or not tools.has(str(node.get("type"))):
        return False
    tool = tools.get(str(node["type"]))
    port = tools.implicit_output(port_key) or next((p for p in (*tool.outputs, *tools.case_ports(tool, node)) if p.key == port_key), None)
    if port is None:
        return False
    if target_port == tools.TRANSFORM_IN:
        return port.semantic == "transform"
    if target_port in ("line", "circle"):
        return port.semantic == target_port
    return port.type == {"image": "image", "roi": "region", FLOW_IN: "flow"}.get(target_port)


def _external_users(graph: dict[str, Any], node_ids: set[str]) -> list[dict[str, str]]:
    deps = []
    seen_tasks: set[str] = set()
    node_by_id = {str(n.get("id")): n for n in graph.get("nodes", [])}
    for e in graph.get("edges", []):
        source = str(e.get("source"))
        target = str(e.get("target"))
        if source in node_ids and target not in node_ids:
            target_node = node_by_id.get(target, {})
            marker = inspect_marker(target_node)
            if marker and marker.get("kind") == "summary":
                continue
            if marker and marker.get("task_id"):
                tid = str(marker["task_id"])
                if tid in seen_tasks:
                    continue
                seen_tasks.add(tid)
                deps.append({"task_id": tid, "target": target, "title": str(target_node.get("label") or target), "target_handle": str(e.get("target_handle") or "")})
                continue
            deps.append({"source": source, "source_handle": str(e.get("source_handle") or ""), "target": target, "title": str(target_node.get("label") or target), "target_handle": str(e.get("target_handle") or "")})
    return deps


def _report_nodes(report: Any) -> dict[str, dict[str, Any]]:
    raw = report.get("nodes") if isinstance(report, dict) else getattr(report, "nodes", {})
    out: dict[str, dict[str, Any]] = {}
    for key, value in (raw or {}).items():
        if isinstance(value, dict):
            out[str(key)] = value
        else:
            out[str(key)] = {
                "status": getattr(value, "status", ""),
                "message": getattr(value, "message", ""),
                "branch": getattr(value, "branch", None),
                "outputs": getattr(value, "outputs", {}),
                "overlays": getattr(value, "overlays", []),
            }
    return out


def _skipped_by_locator(graph: dict[str, Any], task_id: str, nodes: dict[str, dict[str, Any]]) -> bool:
    target_ids = _task_node_ids(graph, task_id)
    by_id = {str(n.get("id")): n for n in graph.get("nodes", [])}
    for e in graph.get("edges", []):
        if str(e.get("target")) in target_ids and str(e.get("target_handle") or "") == FLOW_IN:
            src = str(e.get("source"))
            marker = inspect_marker(by_id.get(src) or {}) or {}
            legacy_find = marker.get("kind") == "locate_part" and marker.get("role") == "find"
            if not legacy_find and not composite.is_locator(by_id.get(src)):
                continue
            row = nodes.get(src, {})
            if str(row.get("branch") or "").endswith("not_found") or row.get("status") == "ng":
                return True
    return False


def _task_value(task: dict[str, Any], find_row: dict[str, Any], tol_row: dict[str, Any]) -> Any:
    fields = task.get("fields") or {}
    if fields.get("mode") == "roundness":
        return (tol_row.get("outputs") or {}).get("deviation")
    port = "diameter_world" if fields.get("calibration") else "diameter"
    return (find_row.get("outputs") or {}).get(port)


def _row_msg(row: dict[str, Any] | None) -> str:
    """節點報告的訊息；帶代碼就還原成 Msg，讀值才能一路把代碼帶到檢測任務頁。"""
    row = row or {}
    text = str(row.get("message") or "")
    code = str(row.get("message_code") or "")
    return Msg(text, code, row.get("message_args") or {}) if code else text


def _reading(task_id: str, verdict: str, valid: bool, detected: bool | None, value: Any, unit: str, reason: str, overlays: list[dict[str, Any]], node_id: str) -> dict[str, Any]:
    code, args = message_parts(reason)
    return {
        "task_id": task_id,
        "verdict": verdict,
        "valid": valid,
        "detected": detected,
        "value": value,
        "unit": unit,
        "reason": str(reason or ""),
        "reason_code": code,
        "reason_args": args,
        "overlays": overlays,
        "node_id": node_id,
    }
