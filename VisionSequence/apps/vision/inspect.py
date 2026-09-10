"""檢測任務清單與流程圖之間的無狀態翻譯器。"""

from __future__ import annotations

import copy
import re
from typing import Any

from apps.core.errors import ValidationError
from apps.vision.graph import FLOW_IN, validate_graph
from apps.vision.tasks import base as task_base
from apps.vision.tasks import get as get_definition
from apps.vision.tools import base as tools

TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
SUMMARY_ID = "inspection_summary"
SUMMARY_TASK_ID = "summary"


def build(graph: dict[str, Any], task: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """把一項檢測任務加入流程圖，並重算必要檢測彙總。"""
    out = _clone_graph(graph)
    ctx = dict(ctx or {})
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
    for node in nodes:
        marker = inspect_marker(node)
        if marker:
            if marker["kind"] == "summary":
                shared.append({"id": node["id"], "type": node["type"], "kind": "summary"})
            else:
                piles.setdefault(marker["task_id"], []).append(node)
        elif node.get("type") in ("image_source", "fixed_image", "stereo_grab", "multi_light_grab", "note"):
            shared.append({"id": node["id"], "type": node.get("type")})
        else:
            loose.append({"id": node.get("id"), "type": node.get("type")})
    tasks = [_read_task(task_id, pile, edges) for task_id, pile in sorted(piles.items())]
    return {"tasks": tasks, "shared": shared, "loose": loose}


def update(graph: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    """共用 build 重算欄位差異，只替換任務內受管理的參數與接線。"""
    out = _clone_graph(graph)
    task_id = str(task.get("task_id") or task.get("id") or "")
    if not task_id:
        raise ValidationError("task_id is required", code="missing_task_id")
    nodes = _task_nodes(out, task_id)
    if not nodes:
        raise ValidationError(f"Inspection task '{task_id}' was not found", code="task_not_found")
    marker = inspect_marker(nodes[0]) or {}
    definition = get_definition(str(marker.get("kind") or task.get("kind") or ""), int(marker.get("schema_version") or task.get("version") or 1))
    supplied = dict(task.get("fields") if isinstance(task.get("fields"), dict) else {})
    supplied.update({k: task[k] for k in definition.fields if k in task})
    current = _read_task(task_id, nodes, out.get("edges", []))
    if current["custom"]:
        raise ValidationError("Edit this custom task in the advanced flow", code="custom_task")
    fields = {**current["fields"], **supplied}
    if definition.kind == "measure_diameter" and "calibration" in supplied and "unit" not in supplied:
        fields["unit"] = "mm" if fields.get("calibration") else "px"
    if "required" in task:
        fields["required"] = task["required"]
    old_nodes, old_edges = definition.build({"task_id": task_id, "fields": current["fields"]}, {})
    new_nodes, new_edges = definition.build({"task_id": task_id, "fields": fields}, {})
    before = {inspect_marker(n)["role"]: n for n in old_nodes}
    after = {inspect_marker(n)["role"]: n for n in new_nodes}
    removed_ids = {str(n["id"]) for n in nodes if inspect_marker(n)["role"] not in after}
    node_ids = {str(n["id"]) for n in nodes}
    if any((e.get("source") in removed_ids and e.get("target") not in node_ids) or
           (e.get("target") in removed_ids and e.get("source") not in node_ids) for e in out.get("edges", [])):
        raise ValidationError("A step needed by another connection would be removed; edit the advanced flow first", code="task_dependency")
    out["nodes"] = [n for n in out["nodes"] if n["id"] not in removed_ids]
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
            # 換工具時只帶過仍有效的發布設定，避免舊工具參數污染新工具。
            published = params.get("_publish")
            node["type"] = new["type"]
            node["params"] = copy.deepcopy(new["params"])
            if published:
                node["params"]["_publish"] = copy.deepcopy(published)
        else:
            for key in old["params"].keys() | new["params"].keys():
                if old["params"].get(key) == new["params"].get(key):
                    continue
                if key == "_publish":
                    published = dict(params.get(key) or {})
                    retained_name = next((published[p] for p in old["params"].get(key, {}) if p in published), None)
                    for port in old["params"].get(key, {}):
                        published.pop(port, None)
                    published.update({port: retained_name if retained_name is not None and "result_name" not in supplied else name
                                      for port, name in new["params"].get(key, {}).items()})
                    if published:
                        params[key] = published
                    else:
                        params.pop(key, None)
                elif key in new["params"]:
                    params[key] = copy.deepcopy(new["params"][key])
                else:
                    params.pop(key, None)
    def connection(e: dict[str, Any]) -> tuple[str, str, str, str]:
        return tuple(str(e.get(k) or "") for k in ("source", "source_handle", "target", "target_handle"))
    old_connections = {connection(e) for e in old_edges}
    new_connections = {connection(e) for e in new_edges}
    out["edges"] = [e for e in out.get("edges", []) if connection(e) not in old_connections - new_connections]
    out["edges"].extend(e for e in new_edges if connection(e) not in old_connections)
    if "required" in supplied or "required" in task:
        required = bool(task.get("required", supplied.get("required", marker.get("required", True))))
        for node in nodes:
            marker = inspect_marker(node)
            if marker:
                marker["required"] = required
    if "locator" in supplied or "locator" in task:
        _connect_locator(out, task_id, str(supplied.get("locator") or task.get("locator") or ""))
    if fields.get("required") != current["required"]:
        _maintain_summary(out)
    return validate_graph(out)


def remove(graph: dict[str, Any], task_id: str) -> dict[str, Any]:
    """刪除任務；若輸出仍被外部使用，回依賴清單且不改圖。"""
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
        roles = task.get("nodes") or {}
        find_id = roles.get("find")
        tol_id = roles.get("tol")
        align_id = roles.get("align")
        role_ids = [nid for nid in roles.values() if nid]
        reports = {nid: nodes.get(nid, {}) for nid in role_ids}
        skipped = [nid for nid, row in reports.items() if row.get("status") == "skipped"]
        errors = [nid for nid, row in reports.items() if row.get("status") == "error"]
        overlays = [ov for row in reports.values() for ov in (row.get("overlays") or [])]
        if errors:
            nid = errors[0]
            readings.append(_reading(task_id, "error", False, None, None, task.get("unit", ""), reports[nid].get("message", ""), overlays, nid))
            continue
        if skipped:
            verdict = "locate_failed" if _skipped_by_locator(graph, task_id, nodes) else "skipped"
            readings.append(_reading(task_id, verdict, False, None, None, task.get("unit", ""), "The task did not run", overlays, skipped[0]))
            continue
        if task["kind"] == "locate_part":
            row = reports.get(find_id or "", {})
            if row.get("status") == "ng" or row.get("branch") == "not_found":
                readings.append(_reading(task_id, "not_found", True, False, None, "", row.get("message", ""), overlays, find_id or ""))
            else:
                value = (reports.get(align_id or "", {}).get("outputs") or {}).get("transform")
                readings.append(_reading(task_id, "pass", True, True, value, "", reports.get(align_id or "", {}).get("message", ""), overlays, align_id or find_id or ""))
            continue
        find_row = reports.get(find_id or "", {})
        tol_row = reports.get(tol_id or "", {})
        if find_row.get("status") == "ng" or find_row.get("branch") == "not_found":
            readings.append(_reading(task_id, "not_found", True, False, None, task.get("unit", ""), find_row.get("message", ""), overlays, find_id or ""))
            continue
        value = _task_value(task, find_row, tol_row)
        verdict = "pass" if tol_row.get("status") == "ok" else "fail"
        readings.append(_reading(task_id, verdict, True, True, value, task.get("unit", ""), tol_row.get("message", ""), overlays, tol_id or find_id or ""))
    return readings


def teach_pose(graph: dict[str, Any], task_id: str, report: Any) -> dict[str, Any]:
    """把定位試跑結果寫回 ref_x/ref_y/ref_angle。"""
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
    used = {m["task_id"] for n in graph.get("nodes", []) if (m := inspect_marker(n))}
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


def _image_source_node(graph: dict[str, Any], *, exclude: set[str]) -> str | None:
    for node in graph.get("nodes", []):
        if str(node.get("id")) in exclude:
            continue
        if node.get("type") in ("image_source", "fixed_image", "stereo_grab", "multi_light_grab"):
            return str(node.get("id"))
    return None


def _connect_image_inputs(graph: dict[str, Any], definition: task_base.TaskDefinition, task_id: str, source: str) -> None:
    for ref in definition.public_inputs:
        if ref.port != "image":
            continue
        target = f"{task_id}_{ref.role}"
        _replace_single_edge(graph, target, "image", task_base.edge(source, "image", target, "image"))


def _connect_locator(graph: dict[str, Any], task_id: str, locator_id: str) -> None:
    target_ids = {str(n["id"]) for n in _task_nodes(graph, task_id)}
    previous = _locator_for(task_id, graph.get("edges", []))
    managed = {(f"{previous}_align", "transform", tools.TRANSFORM_IN), (f"{previous}_find", "found", FLOW_IN)} if previous else set()
    graph["edges"] = [
        e for e in graph.get("edges", [])
        if not (str(e.get("target")) in target_ids and (str(e.get("source")), str(e.get("source_handle") or ""), str(e.get("target_handle") or "")) in managed)
    ]
    if not locator_id:
        return
    loc_nodes = {inspect_marker(n).get("role"): str(n["id"]) for n in _task_nodes(graph, locator_id) if inspect_marker(n)}
    find = loc_nodes.get("find")
    align = loc_nodes.get("align")
    if not find or not align:
        raise ValidationError(f"Locator task '{locator_id}' was not found", code="locator_not_found")
    for target in sorted(target_ids):
        node = next((n for n in graph.get("nodes", []) if str(n.get("id")) == target), None)
        if node is None or node.get("type") not in ("find_circle", "template_match"):
            continue
        graph.setdefault("edges", []).append(task_base.edge(align, "transform", target, tools.TRANSFORM_IN))
        graph.setdefault("edges", []).append(task_base.edge(find, "found", target, FLOW_IN))


def _replace_single_edge(graph: dict[str, Any], target: str, target_port: str, new_edge: dict[str, str]) -> None:
    graph["edges"] = [e for e in graph.get("edges", []) if not (str(e.get("target")) == target and str(e.get("target_handle") or "") == target_port)]
    graph.setdefault("edges", []).append(new_edge)


def _place_nodes(graph: dict[str, Any], nodes: list[dict[str, Any]]) -> None:
    xs = [float((n.get("position") or {}).get("x", 0)) for n in graph.get("nodes", []) if isinstance(n.get("position"), dict)]
    base_x = (max(xs) + 220) if xs else 120
    base_y = 80
    for i, node in enumerate(nodes):
        node.setdefault("position", {"x": base_x + i * 220, "y": base_y})


def _maintain_summary(graph: dict[str, Any]) -> None:
    graph["nodes"] = [n for n in graph.get("nodes", []) if str(n.get("id")) != SUMMARY_ID]
    graph["edges"] = [e for e in graph.get("edges", []) if str(e.get("source")) != SUMMARY_ID and str(e.get("target")) != SUMMARY_ID]
    tasks = read({k: v for k, v in graph.items() if k in ("nodes", "edges")})["tasks"]
    required: list[tuple[str, task_base.PortRef]] = []
    for task in tasks:
        if not task.get("required") or task.get("custom"):
            continue
        try:
            definition = get_definition(task["kind"], task.get("version"))
        except ValidationError:
            continue
        if definition.pass_port is not None:
            required.append((task["task_id"], definition.pass_port))
    if not required:
        return
    graph.setdefault("nodes", []).append({
        "id": SUMMARY_ID,
        "type": "inspection_summary",
        "params": {"expected_count": len(required)},
        "meta": {"inspect": {"task_id": SUMMARY_TASK_ID, "role": "summary", "kind": "summary", "schema_version": 1, "required": False}},
        "position": {"x": 120 + len(graph.get("nodes", [])) * 220, "y": 360},
    })
    for task_id, ref in required:
        graph.setdefault("edges", []).append(task_base.edge(f"{task_id}_{ref.role}", ref.port, SUMMARY_ID, "results"))


def _read_task(task_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    first = inspect_marker(nodes[0]) or {}
    kind = str(first.get("kind") or "")
    version = int(first.get("schema_version") or 1)
    roles = {inspect_marker(n)["role"]: str(n["id"]) for n in nodes if inspect_marker(n)}
    item: dict[str, Any] = {
        "task_id": task_id,
        "kind": kind,
        "version": version,
        "required": bool(first.get("required")),
        "nodes": roles,
        "fields": {},
        "custom": False,
        "reasons": [],
    }
    try:
        definition = get_definition(kind, version)
    except ValidationError:
        item["custom"] = True
        item["reasons"].append({"code": "unknown_kind", "role": "", "detail": kind})
        return item
    _read_fields(item, definition, nodes, edges)
    item["reasons"] = _custom_reasons(task_id, definition, nodes, edges)
    item["custom"] = bool(item["reasons"])
    return item


def _read_fields(item: dict[str, Any], definition: task_base.TaskDefinition, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    by_role = {inspect_marker(n)["role"]: n for n in nodes if inspect_marker(n)}
    fields = item["fields"]
    for key, spec in definition.fields.items():
        if key == "required":
            fields[key] = item["required"]
            continue
        if key == "locator":
            fields[key] = _locator_for(item["task_id"], edges)
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


def _locator_for(task_id: str, edges: list[dict[str, Any]]) -> str:
    for e in edges:
        if str(e.get("target")).startswith(f"{task_id}_") and str(e.get("target_handle") or "") == tools.TRANSFORM_IN:
            source = str(e.get("source"))
            if source.endswith("_align"):
                return source[:-6]
    return ""


def _published_name(node: dict[str, Any] | None, port: str) -> str:
    publish = ((node or {}).get("params") or {}).get("_publish")
    return str(publish.get(port) or "") if isinstance(publish, dict) else ""


def _custom_reasons(task_id: str, definition: task_base.TaskDefinition, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    fields = _fields_for_reason(definition, nodes, edges, task_id)
    expected_roles = dict(definition.roles)
    if definition.kind == "measure_diameter" and fields.get("mode") == "roundness" and fields.get("unit") == "mm":
        expected_roles["scale"] = "calibration"
    role_types = {inspect_marker(n)["role"]: str(n.get("type")) for n in nodes if inspect_marker(n)}
    for role, tool_key in expected_roles.items():
        if role not in role_types:
            reasons.append({"code": "missing_role", "role": role, "detail": f"Missing {role}"})
        elif role_types[role] != tool_key and not (definition.kind == "measure_diameter" and role == "tol" and role_types[role] in ("tolerance_judge", "gdt_measure")):
            reasons.append({"code": "role_type_changed", "role": role, "detail": f"Expected {tool_key}, got {role_types[role]}"})
    for role in sorted(set(role_types) - set(expected_roles)):
        reasons.append({"code": "unexpected_role", "role": role, "detail": f"Unexpected role {role}"})
    expected = {(f"{task_id}_{e.source_role}", e.source_port, f"{task_id}_{e.target_role}", e.target_port) for e in definition.edges_for(fields)}
    actual = {
        (str(e.get("source")), str(e.get("source_handle") or ""), str(e.get("target")), str(e.get("target_handle") or ""))
        for e in edges
        if str(e.get("source")).startswith(f"{task_id}_") and str(e.get("target")).startswith(f"{task_id}_")
    }
    for entry in sorted(expected - actual):
        reasons.append({"code": "managed_edge_changed", "role": entry[2].removeprefix(f"{task_id}_"), "detail": f"Missing {entry[0]}.{entry[1]} -> {entry[2]}.{entry[3]}"})
    for entry in sorted(actual - expected):
        reasons.append({"code": "managed_edge_changed", "role": entry[2].removeprefix(f"{task_id}_"), "detail": f"Unexpected {entry[0]}.{entry[1]} -> {entry[2]}.{entry[3]}"})
    allowed_inputs = {(f"{task_id}_{p.role}", p.port) for p in definition.public_inputs}
    for e in edges:
        target = (str(e.get("target")), str(e.get("target_handle") or ""))
        source = str(e.get("source"))
        if target[0].startswith(f"{task_id}_") and not source.startswith(f"{task_id}_") and target not in allowed_inputs:
            reasons.append({"code": "unexpected_input", "role": target[0].removeprefix(f"{task_id}_"), "detail": f"Unexpected input into {target[0]}.{target[1]}"})
    return reasons


def _fields_for_reason(definition: task_base.TaskDefinition, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    item = {"task_id": task_id, "required": True, "fields": {}}
    _read_fields(item, definition, nodes, edges)
    return item["fields"]


def _external_users(graph: dict[str, Any], node_ids: set[str]) -> list[dict[str, str]]:
    deps = []
    seen_tasks: set[str] = set()
    node_by_id = {str(n.get("id")): n for n in graph.get("nodes", [])}
    for e in graph.get("edges", []):
        source = str(e.get("source"))
        target = str(e.get("target"))
        if source in node_ids and target not in node_ids:
            marker = inspect_marker(node_by_id.get(target, {}))
            if marker and marker.get("kind") == "summary":
                continue
            if marker and marker.get("task_id"):
                tid = str(marker["task_id"])
                if tid in seen_tasks:
                    continue
                seen_tasks.add(tid)
                deps.append({"task_id": tid, "target": target, "target_handle": str(e.get("target_handle") or "")})
                continue
            deps.append({"source": source, "source_handle": str(e.get("source_handle") or ""), "target": target, "target_handle": str(e.get("target_handle") or "")})
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
    for e in graph.get("edges", []):
        if str(e.get("target")).startswith(f"{task_id}_") and str(e.get("target_handle") or "") == FLOW_IN:
            src = str(e.get("source"))
            row = nodes.get(src, {})
            if row.get("branch") == "not_found" or row.get("status") == "ng":
                return True
    return False


def _task_value(task: dict[str, Any], find_row: dict[str, Any], tol_row: dict[str, Any]) -> Any:
    fields = task.get("fields") or {}
    if fields.get("mode") == "roundness":
        return (tol_row.get("outputs") or {}).get("deviation")
    port = "diameter_world" if fields.get("calibration") else "diameter"
    return (find_row.get("outputs") or {}).get(port)


def _reading(task_id: str, verdict: str, valid: bool, detected: bool | None, value: Any, unit: str, reason: str, overlays: list[dict[str, Any]], node_id: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "verdict": verdict,
        "valid": valid,
        "detected": detected,
        "value": value,
        "unit": unit,
        "reason": reason or "",
        "overlays": overlays,
        "node_id": node_id,
    }
