"""內建的檢測任務複合工具（PRODUCT-DIRECTION v2 §4）：八種檢測任務 → 「一種方式一個工具」。

任務定義（`apps/vision/tasks/`）仍是唯一事實來源：每個內建工具的內部圖由 `TaskDefinition.build()` 用預設欄位產生
（必填但沒有預設值的欄位——區域、參考圖、模型——先填佔位值，建好再清空，讓它們變成對外參數由使用者在流程上填），
對外埠來自任務的公開輸入／輸出，對外參數來自「有 role＋param 的欄位」（顯示名稱與說明沿用欄位）。
內建工具唯讀（`builtin=True`），使用者要改就「另存複本」。圓周表面檢測的內部幾何依 ROI 半徑算（卡尺數、掃描區），
內部圖固定後改 ROI 會對不上，所以刻意不做（2026-09-11 拍板）。

`ensure_builtin_tools()` 可重複執行：沒有就建、定義變了就更新內部圖與介面；`manage.py serve` 啟動與 `seed_demo` 都呼叫。
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Any

from apps.vision import composites
from apps.vision.tasks import base as tasks
from apps.vision.tasks.base import PortRef
from apps.vision.tools import base as tools

log = logging.getLogger(__name__)

CATEGORY = "inspection"


@dataclass(frozen=True)
class BuiltinSpec:
    key: str
    kind: str
    label: str
    icon: str
    #: 方式欄位與值（沒有方式的任務為 None）
    method_field: str | None = None
    method_value: str | None = None


SPECS: tuple[BuiltinSpec, ...] = (
    BuiltinSpec("measure_diameter", "measure_diameter", "Measure diameter", "CircleDot", "mode", "check"),
    BuiltinSpec("measure_roundness", "measure_diameter", "Measure roundness", "Circle", "mode", "roundness"),
    BuiltinSpec("locate_part_template", "locate_part", "Locate part (template)", "Crosshair", "method", "template"),
    BuiltinSpec("locate_part_shape", "locate_part", "Locate part (shape model)", "Crosshair", "method", "shape"),
    BuiltinSpec("locate_part_register", "locate_part", "Locate part (registered picture)", "Crosshair", "method", "register"),
    BuiltinSpec("measure_distance_edges", "measure_distance", "Measure distance (edge pair)", "Ruler", "mode", "edge_pair"),
    BuiltinSpec("measure_distance_holes", "measure_distance", "Measure distance (hole centres)", "Ruler", "mode", "hole_centres"),
    BuiltinSpec("count_objects", "count_objects", "Count objects", "Hash"),
    BuiltinSpec("check_presence_template", "check_presence", "Check presence (template)", "ScanSearch", "method", "template"),
    BuiltinSpec("check_presence_blob", "check_presence", "Check presence (blob)", "ScanSearch", "method", "blob"),
    BuiltinSpec("check_presence_print", "check_presence", "Check presence (print)", "ScanSearch", "method", "print"),
    BuiltinSpec("inspect_edge_defect", "inspect_edge_defect", "Inspect edge defect", "Waves", "method", "simple"),
    BuiltinSpec("inspect_edge_defect_freeform", "inspect_edge_defect", "Inspect edge defect (free-form outline)", "Waves", "method", "freeform"),
    BuiltinSpec("read_code", "read_and_verify", "Read code", "Barcode", "mode", "code"),
    BuiltinSpec("read_text_verify", "read_and_verify", "Read and verify text", "ScanText", "mode", "text"),
)

#: 結果名稱由實例的具名輸出名稱決定，不當對外參數；locator 由對外的位置修正埠取代
_SKIP_FIELDS = {"result_name", "locator", "required"}
_TASK_ID = "t"


def _placeholder(spec: tasks.FieldSpec) -> Any:
    """必填但沒有預設值的欄位：先給一個能通過建立的值，建好再清掉（變成對外參數）。"""
    if spec.kind == "roi":
        shape = (spec.shapes or ("rect",))[0]
        if shape == "annulus":
            return {"shape": "annulus", "cx": 50, "cy": 50, "r_inner": 10, "r_outer": 40}
        if shape == "circle":
            return {"shape": "circle", "cx": 50, "cy": 50, "r": 40}
        return {"shape": "rect", "x": 0, "y": 0, "w": 100, "h": 100}
    if spec.kind == "images":
        return []
    if spec.kind == "asset":
        return "placeholder"
    if spec.kind == "json":
        return {"placeholder": True}
    if spec.kind in ("text", "output_key"):
        return "x"
    if spec.kind == "number":
        return spec.default if spec.default is not None else 0
    return spec.default


def _visible(spec: tasks.FieldSpec, fields: dict[str, Any], definition: tasks.TaskDefinition) -> bool:
    if not spec.visible_when:
        return True
    for key, wanted in spec.visible_when.items():
        allowed = wanted if isinstance(wanted, list) else [wanted]
        if fields.get(key, definition.fields[key].default if key in definition.fields else None) not in allowed:
            return False
    return True


def build_tool(spec: BuiltinSpec) -> tuple[dict[str, Any], dict[str, Any], str]:
    """回 (內部圖, 對外介面, 說明)。"""
    definition = tasks.get(spec.kind)
    fields: dict[str, Any] = {key: field.default for key, field in definition.fields.items()}
    if spec.method_field:
        fields[spec.method_field] = spec.method_value
    placeholders: set[str] = set()
    for key, field in definition.fields.items():
        if field.required and _visible(field, fields, definition) and fields.get(key) in (None, "", []):
            fields[key] = _placeholder(field)
            placeholders.add(key)
    nodes, edges = definition.build({"task_id": _TASK_ID, "fields": fields, "required": True}, {})
    prefix = f"{_TASK_ID}_"
    rename = {str(n["id"]): str(n["id"])[len(prefix):] for n in nodes if str(n["id"]).startswith(prefix)}
    for node in nodes:
        node["id"] = rename.get(str(node["id"]), str(node["id"]))
        node.pop("meta", None)
        composites._strip_aliases(node)
    for edge in edges:
        edge["source"] = rename.get(str(edge["source"]), str(edge["source"]))
        edge["target"] = rename.get(str(edge["target"]), str(edge["target"]))
    by_role = {node["id"]: node for node in nodes}
    # 佔位值清掉：對外參數的預設值變成「未填」，使用者在流程上填
    for key in placeholders:
        field = definition.fields[key]
        if field.role and field.param and field.role in by_role:
            params = by_role[field.role].setdefault("params", {})
            params[field.param] = [] if field.kind == "images" else None
    # 版面：由左而右
    for index, node in enumerate(nodes):
        node["position"] = {"x": 40 + index * 260, "y": 40}
    graph = {"nodes": nodes, "edges": edges}

    layout = definition.layout_hook(fields) if definition.layout_hook else None
    in_refs = list(definition.inputs_for(fields))
    out_refs = list(layout.outputs if layout else definition.public_outputs)
    for extra in ((layout.pass_port, layout.value_port) if layout else (definition.pass_port,)):
        if extra is not None and extra not in out_refs:
            out_refs.append(extra)
    # 判定角色的分支埠也對外（流程要靠它走控制線）
    verdict_role = layout.verdict_role if layout else (definition.pass_port.role if definition.pass_port else "")
    if verdict_role and verdict_role in by_role:
        for port in tools.get(str(by_role[verdict_role]["type"])).outputs:
            ref = PortRef(verdict_role, port.key)
            if port.type == "flow" and ref not in out_refs:
                out_refs.append(ref)
    inputs = [{"key": f"{ref.role}:{ref.port}", "exposed": True, "order": i} for i, ref in enumerate(r for r in in_refs if r.port != tools.FLOW_IN and r.role in by_role)]
    outputs = [{"key": f"{ref.role}:{ref.port}", "exposed": True, "order": i} for i, ref in enumerate(r for r in out_refs if r.role in by_role)]
    params: list[dict[str, Any]] = []
    for key, field in definition.fields.items():
        if key in _SKIP_FIELDS or not field.role or not field.param or field.role not in by_role or not _visible(field, fields, definition):
            continue
        entry: dict[str, Any] = {"key": f"{field.role}:{field.param}", "alias": field.label, "order": len(params)}
        if field.help_text:
            entry["help_text"] = field.help_text
        if key in placeholders:
            entry["default"] = [] if field.kind == "images" else None
        params.append(entry)
    method_label = ""
    if spec.method_field:
        options = definition.fields[spec.method_field].options
        method_label = next((str(o.get("label")) for o in options if o.get("value") == spec.method_value), str(spec.method_value))
    description = definition.help_text + (f" Method: {method_label}." if method_label else "")
    return graph, {"inputs": inputs, "outputs": outputs, "params": params}, description


def ensure_builtin_tools() -> dict[str, int]:
    """沒有就建、定義變了就更新；一個壞掉不影響其他。回 {created, updated, unchanged, failed}。"""
    from django.db import transaction

    from apps.vision.models import CompositeTool

    counts = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    for spec in SPECS:
        try:
            graph, interface, description = build_tool(spec)
            payload = {"key": spec.key, "label": spec.label, "description": description, "category": CATEGORY, "icon": spec.icon, "graph": graph, "interface": interface}
            row = CompositeTool.objects.select_related("flow").filter(key=spec.key).first()
            if row is None:
                composites.create(None, payload, builtin=True)
                counts["created"] += 1
                continue
            with transaction.atomic():
                changed = False
                for field_name in ("label", "description", "category", "icon"):
                    if getattr(row, field_name) != payload[field_name]:
                        setattr(row, field_name, payload[field_name])
                        changed = True
                if row.interface != interface:
                    row.interface = interface
                    changed = True
                if not row.builtin:
                    row.builtin = True
                    changed = True
                clean = composites._clean_graph(spec.key, copy.deepcopy(graph))
                if (row.flow.graph or {}) != clean:
                    row.flow.graph = clean
                    row.flow.version += 1
                    row.flow.save()
                    changed = True
                if changed:
                    row.save()
            counts["updated" if changed else "unchanged"] += 1
        except Exception:  # noqa: BLE001 - 一個任務定義壞了不該讓其他內建工具消失
            log.warning("內建複合工具 %s 建不起來", spec.key, exc_info=True)
            counts["failed"] += 1
    composites.invalidate()
    return counts
