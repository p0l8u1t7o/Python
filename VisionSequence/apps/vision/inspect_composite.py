"""檢測任務 ↔ 內建複合工具實例（PRODUCT-DIRECTION v2 P4）。

檢測任務頁與 AI 助手的任務清單從這一批起把新任務放成**內建檢測複合工具的實例**（`composite:<key>` 節點，
一種方式一個工具，見 composites_builtin.py），不再產生帶 `meta.inspect` 的一組節點；舊流程裡的任務照樣由 inspect.py 讀寫，
兩種任務對頁面與助手是同一個形狀（`task_id`＝實例節點 id、`nodes={"instance": id}`、`source="composite"`）。

做法是**把實例還原成一組「合成的角色節點」再沿用任務層的讀寫**：讀回時，內部圖的每個步驟疊上實例參數
（`<role>:<param>`）就是 `_read_fields`／`read_hook` 看得懂的節點；寫入時，`TaskDefinition.build()` 建出的步驟參數依
複合工具的參數對照表（`param_map`）取回實例參數，所以方式切換、write hook、旋轉與標定的規則都只在任務定義裡寫一次。
方式（method）由工具 key 決定、結果名稱是實例具名輸出的名稱、必要與否記在 `meta.required`、定位接線與舊任務相同
（`align:transform → _transform`、`find:found → _flow`）。引擎摺疊後內部節點的報告仍在（`<實例>.<角色>`），讀值也沿用舊邏輯。
"""

from __future__ import annotations

import copy
from typing import Any

from django.conf import settings

from apps.core.errors import ValidationError
from apps.vision import composites_builtin as builtin
from apps.vision.tasks import base as task_base
from apps.vision.tasks import get as get_definition
from apps.vision.tools import base as tools

SPEC_BY_TYPE = {f"composite:{spec.key}": spec for spec in builtin.SPECS}
SOURCE = "composite"
_PROBE_TASK_ID = "t"


def default_enabled() -> bool:
    """新任務預設放實例（`VISION_INSPECT_COMPOSITE=0` 退回舊的 meta.inspect 節點組）。"""
    value = settings.VISION.get("INSPECT_COMPOSITE", "1")
    return str(value).strip().lower() not in ("0", "false", "no", "off")


def spec_of(node: dict[str, Any] | None) -> builtin.BuiltinSpec | None:
    if not isinstance(node, dict):
        return None
    return SPEC_BY_TYPE.get(str(node.get("type") or ""))


def is_locator(node: dict[str, Any] | None) -> bool:
    spec = spec_of(node)
    return spec is not None and spec.kind == "locate_part"


def spec_for(kind: str, fields: dict[str, Any]) -> builtin.BuiltinSpec:
    """任務種類＋方式欄位 → 內建工具。"""
    definition = get_definition(kind)
    candidates = [spec for spec in builtin.SPECS if spec.kind == kind]
    if not candidates:
        raise ValidationError(f"No built-in tool implements '{kind}'", code="kind_not_composable")
    if len(candidates) == 1:
        return candidates[0]
    method_field = candidates[0].method_field or ""
    wanted = fields.get(method_field)
    if wanted in (None, ""):
        wanted = definition.fields[method_field].default if method_field in definition.fields else None
    for spec in candidates:
        if spec.method_value == wanted:
            return spec
    raise ValidationError(f"Unsupported {method_field} '{wanted}' for '{kind}'", code="invalid_task_field")


def tool_type(spec: builtin.BuiltinSpec):
    return tools.get(f"composite:{spec.key}")


def available(kind: str, fields: dict[str, Any]) -> bool:
    """這種任務（與方式）有沒有已登錄的內建工具；沒有（圓周表面檢測、內建工具還沒建）就退回舊的節點組。"""
    try:
        spec = spec_for(kind, fields)
    except ValidationError:
        return False
    return tools.has(f"composite:{spec.key}")


def alias_ref(definition: task_base.TaskDefinition, fields: dict[str, Any]) -> task_base.PortRef | None:
    """結果名稱掛在哪個埠（與任務定義的 build 一致：量直徑不論模式都掛在 find 的直徑埠）。"""
    if definition.layout_hook:
        return definition.layout_hook(fields).value_port
    if definition.kind == "measure_diameter":
        return task_base.PortRef("find", "diameter_world" if fields.get("calibration") else "diameter")
    return None


def port_key(ref: task_base.PortRef) -> str:
    return f"{ref.role}:{ref.port}"


def report_roles(node: dict[str, Any]) -> dict[str, str]:
    """實例的每個內部步驟在引擎報告裡的 id（展平後 `<實例>.<角色>`）。"""
    spec = spec_of(node)
    assert spec is not None
    return {str(inner["id"]): f"{node['id']}.{inner['id']}" for inner in tool_type(spec).graph.get("nodes", [])}


# ---------------------------------------------------------------------------
# 讀回：實例 → 合成的角色節點 → 任務層的讀取
# ---------------------------------------------------------------------------
def role_nodes(node: dict[str, Any], spec: builtin.BuiltinSpec, required: bool) -> list[dict[str, Any]]:
    """內部圖的步驟疊上實例參數，變成 inspect.py 看得懂的一組節點（id `<task_id>_<role>`）。"""
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    task_id = str(node["id"])
    out = []
    for inner in tool_type(spec).graph.get("nodes", []):
        role = str(inner["id"])
        merged = copy.deepcopy(inner.get("params") if isinstance(inner.get("params"), dict) else {})
        for key, value in params.items():
            owner, sep, param = str(key).partition(":")
            if sep and owner == role:
                merged[param] = copy.deepcopy(value)
        synthetic = {"id": f"{task_id}_{role}", "type": inner["type"], "params": merged,
                     "meta": {"inspect": {"task_id": task_id, "role": role, "kind": spec.kind, "schema_version": 1, "required": required}}}
        if node.get("enabled") is False:
            synthetic["enabled"] = False
        out.append(synthetic)
    return out


def _role_edges(task_id: str, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """接進實例 `<role>:<port>` 埠的邊改寫成接進合成節點的邊（read hook 用來找參考幾何）。"""
    out = []
    for e in edges:
        if str(e.get("target")) != task_id:
            continue
        role, sep, port = str(e.get("target_handle") or "").partition(":")
        if sep:
            out.append({**e, "target": f"{task_id}_{role}", "target_handle": port})
    return out


def read_instance(node: dict[str, Any], edges: list[dict[str, Any]], all_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    from apps.vision import inspect as legacy

    spec = spec_of(node)
    assert spec is not None
    definition = get_definition(spec.kind)
    task_id = str(node["id"])
    meta = node.get("meta") if isinstance(node.get("meta"), dict) else {}
    required = bool(meta.get("required", True))
    item: dict[str, Any] = {
        "task_id": task_id, "kind": spec.kind, "version": definition.version, "required": required,
        "nodes": {"instance": task_id}, "fields": {}, "custom": False, "disabled": node.get("enabled") is False,
        "reasons": [], "source": SOURCE, "tool": spec.key,
    }
    legacy._read_fields(item, definition, role_nodes(node, spec, required), _role_edges(task_id, edges), all_nodes)
    fields = item["fields"]
    if spec.method_field:
        fields[spec.method_field] = spec.method_value
    if "locator" in definition.fields:
        fields["locator"] = legacy._locator_for(task_id, edges, all_nodes)
    if "result_name" in definition.fields:
        ref = alias_ref(definition, fields)
        fields["result_name"] = tools.output_aliases(node).get(port_key(ref), "") if ref else ""
    return item


# ---------------------------------------------------------------------------
# 寫入：欄位 → TaskDefinition.build() → 實例參數
# ---------------------------------------------------------------------------
def instance_params(spec: builtin.BuiltinSpec, fields: dict[str, Any], required: bool) -> tuple[dict[str, Any], dict[str, str], task_base.TaskLayout | None]:
    """回 (實例參數, 具名輸出 {對外埠: 名稱}, 版面)。任務定義是唯一事實來源：這裡只把它建出的步驟參數對回實例。"""
    definition = get_definition(spec.kind)
    nodes, _ = definition.build({"task_id": _PROBE_TASK_ID, "fields": fields, "required": required}, {})
    prefix = f"{_PROBE_TASK_ID}_"
    by_role = {str(n["id"])[len(prefix):]: n for n in nodes}
    ctype = tool_type(spec)
    params: dict[str, Any] = {}
    for ext_key, (inner_id, param_key) in ctype.param_map.items():
        node = by_role.get(inner_id)
        node_params = node.get("params") if node and isinstance(node.get("params"), dict) else None
        if node_params is not None and param_key in node_params:
            params[ext_key] = copy.deepcopy(node_params[param_key])
    aliases = {f"{role}:{port}": name for role, node in by_role.items() for port, name in tools.output_aliases(node).items()}
    layout = definition.layout_hook(fields) if definition.layout_hook else None
    return params, aliases, layout


def _apply_aliases(node: dict[str, Any], old: dict[str, str], new: dict[str, str]) -> None:
    for port in old:
        if port not in new:
            tools.set_output_alias(node, port, "")
    for port, name in new.items():
        tools.set_output_alias(node, port, name)


def _connect_images(graph: dict[str, Any], node: dict[str, Any], source: str) -> None:
    for port in tools.get(str(node["type"])).inputs:
        if port.type != "image":
            continue
        if not any(e.get("target") == node["id"] and e.get("target_handle") == port.key for e in graph.get("edges", [])):
            graph.setdefault("edges", []).append(task_base.edge(source, "image", str(node["id"]), port.key))


def _connect_external(graph: dict[str, Any], node: dict[str, Any], previous: task_base.TaskLayout | None, layout: task_base.TaskLayout | None) -> None:
    """版面的外部輸入（參考幾何）：拿掉舊的、接上新的；其他接進實例的線不動。"""
    task_id = str(node["id"])
    managed = {f"{e['role']}:{e['input']}" for lay in (previous, layout) if lay for e in lay.external}
    graph["edges"] = [e for e in graph.get("edges", []) if not (str(e.get("target")) == task_id and str(e.get("target_handle") or "") in managed)]
    for e in (layout.external if layout else ()):
        graph["edges"].append(task_base.edge(e["source"], e["port"], task_id, f"{e['role']}:{e['input']}"))


def _prepare_fields(definition: task_base.TaskDefinition, fields: dict[str, Any]) -> dict[str, Any]:
    fields = task_base.task_fields({"fields": fields}, definition)
    if "calibration" in definition.fields and fields.get("calibration") and "unit" in definition.fields:
        fields["unit"] = "mm"
    if fields.get("unit") == "mm" and not fields.get("calibration"):
        raise ValidationError("Millimetre mode needs a calibration", code="missing_calibration")
    return fields


def build_instance(graph: dict[str, Any], task: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    from apps.vision import inspect as legacy
    from apps.vision.graph import validate_graph

    out = legacy._clone_graph(graph)
    definition = get_definition(str(task.get("kind") or ""), task.get("version"))
    fields = _prepare_fields(definition, {**(task.get("fields") if isinstance(task.get("fields"), dict) else {}), **{k: task[k] for k in definition.fields if k in task}})
    required = bool(task.get("required", fields.get("required", True)))
    spec = spec_for(definition.kind, fields)
    task_id = legacy._unique_task_id(out, str(task.get("task_id") or task.get("id") or definition.kind))
    params, aliases, layout = instance_params(spec, fields, required)
    node: dict[str, Any] = {"id": task_id, "type": f"composite:{spec.key}", "params": params, "meta": {"required": required}}
    _apply_aliases(node, {}, aliases)
    legacy._place_nodes(out, [node])
    out.setdefault("nodes", []).append(node)
    source = ctx.get("image_node") or ctx.get("source_node") or legacy._image_source_node(out, exclude={task_id})
    if source is None:
        raise ValidationError("Add an image source before building inspection tasks", code="missing_image_source")
    _connect_images(out, node, str(source))
    _connect_external(out, node, None, layout)
    legacy._connect_locator(out, task_id, str(fields.get("locator") or ""))
    legacy._maintain_summary(out)
    return validate_graph(out)


def update_instance(graph: dict[str, Any], node_id: str, task: dict[str, Any]) -> dict[str, Any]:
    from apps.vision import inspect as legacy
    from apps.vision.graph import FLOW_IN, validate_graph

    out = legacy._clone_graph(graph)
    node = next(n for n in out["nodes"] if str(n.get("id")) == node_id)
    spec = spec_of(node)
    assert spec is not None
    definition = get_definition(spec.kind)
    current = read_instance(node, out.get("edges", []), out["nodes"])
    supplied = dict(task.get("fields") if isinstance(task.get("fields"), dict) else {})
    supplied.update({k: task[k] for k in definition.fields if k in task})
    fields = {**current["fields"], **supplied}
    if "calibration" in definition.fields and "calibration" in supplied and "unit" not in supplied:
        fields["unit"] = "mm" if fields.get("calibration") else "px"
    if "required" in task:
        fields["required"] = task["required"]
    fields = _prepare_fields(definition, fields)
    required = bool(fields.get("required", True))
    new_spec = spec_for(spec.kind, fields)
    old_params, old_aliases, old_layout = instance_params(spec, current["fields"], current["required"]) if _buildable(spec, current["fields"]) else ({}, tools.output_aliases(node), None)
    params, aliases, layout = instance_params(new_spec, fields, required)
    if new_spec.key != spec.key:
        # 換方式＝換成另一個內建工具：同一個節點 id 與位置，接到已不存在的埠的線拿掉
        node["type"] = f"composite:{new_spec.key}"
        node.pop(tools.INTERFACE_KEY, None)
        ctype = tool_type(new_spec)
        inputs = {p.key for p in ctype.inputs} | {tools.TRANSFORM_IN, FLOW_IN}
        outputs = {p.key for p in ctype.outputs}
        out["edges"] = [e for e in out.get("edges", []) if not ((str(e.get("target")) == node_id and str(e.get("target_handle") or "") not in inputs)
                                                               or (str(e.get("source")) == node_id and str(e.get("source_handle") or "") not in outputs))]
        old_aliases = {}
    node["params"] = params
    node.setdefault("meta", {})["required"] = required
    _apply_aliases(node, old_aliases, aliases)
    image = next((str(e["source"]) for e in out.get("edges", []) if str(e.get("target")) == node_id and str(e.get("target_handle") or "").endswith(":image")), None)
    if image:
        _connect_images(out, node, image)
    _connect_external(out, node, old_layout, layout)
    if "locator" in supplied or "locator" in task or new_spec.key != spec.key:
        legacy._connect_locator(out, node_id, str(fields.get("locator") or ""))
    legacy._maintain_summary(out)
    return validate_graph(out)


def _buildable(spec: builtin.BuiltinSpec, fields: dict[str, Any]) -> bool:
    try:
        instance_params(spec, fields, True)
    except ValidationError:
        return False
    return True


def remove_instance(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    from apps.vision import inspect as legacy
    from apps.vision.graph import validate_graph

    out = legacy._clone_graph(graph)
    deps = legacy._external_users(out, {node_id})
    if deps:
        return {"graph": out, "dependencies": deps, "removed": False}
    out["nodes"] = [n for n in out.get("nodes", []) if str(n.get("id")) != node_id]
    out["edges"] = [e for e in out.get("edges", []) if str(e.get("source")) != node_id and str(e.get("target")) != node_id]
    legacy._maintain_summary(out)
    return {"graph": validate_graph(out), "dependencies": [], "removed": True}


def teach_pose_instance(graph: dict[str, Any], node_id: str, report: Any) -> dict[str, Any]:
    from apps.vision import inspect as legacy
    from apps.vision.graph import validate_graph

    out = legacy._clone_graph(graph)
    node = next(n for n in out["nodes"] if str(n.get("id")) == node_id)
    if not is_locator(node):
        raise ValidationError("The task is not a locator", code="not_locator")
    row = legacy._report_nodes(report).get(f"{node_id}.find", {})
    outputs = row.get("outputs") or {}
    if row.get("status") != "ok":
        raise ValidationError("The locator did not find a part", code="locate_not_found")
    x, y, angle = outputs.get("best_x"), outputs.get("best_y"), outputs.get("best_angle", 0)
    if x is None or y is None:
        first = (outputs.get("matches") or [{}])[0] or {}
        x, y, angle = first.get("cx"), first.get("cy"), first.get("angle", 0)
    try:
        params = node.setdefault("params", {})
        params["align:ref_x"] = float(x)
        params["align:ref_y"] = float(y)
        params["align:ref_angle"] = float(angle or 0)
    except (TypeError, ValueError):
        raise ValidationError("The locator result did not include a usable pose", code="bad_locator_pose") from None
    return validate_graph(out)
