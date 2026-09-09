"""站台 Dashboard 版面合約與驗證。"""

from __future__ import annotations

import copy
import re
from typing import Any

WIDGET_TYPES = (
    "image",
    "images",
    "run_control",
    "run_status",
    "verdict",
    "text",
    "button",
    "switch",
    "param",
    "variable",
    "traffic_light",
    "conditional_light",
    "group",
    "tabs",
    "table",
    "line_chart",
    "stats",
    "pie",
    "image_static",
    "clock",
    "log",
    "device_status",
    "child",
)
SOURCE_KINDS = ("output", "variable", "image", "status", "counts", "spc", "device")
ACTION_CHOICES = ("run_once", "continuous_start", "continuous_stop", "activate_recipe", "set_variable", "navigate", "lock", "unlock")
OP_CHOICES = ("eq", "ne", "gt", "gte", "lt", "lte", "between")
SCOPE_CHOICES = ("flow", "station")
_REQUIRED = object()
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

WIDGET_PROPS: dict[str, dict[str, tuple[str, Any, Any]]] = {
    "image": {
        "node": ("text", None, None),
        "port": ("text", None, None),
        "overlays": ("bool", True, None),
        "crosshair": ("bool", False, None),
        "history": ("int", 1, (1, 50)),
    },
    "images": {
        "items": ("image_items", [], None),
        "columns": ("int", 2, (1, 8)),
        "overlays": ("bool", True, None),
        "history": ("int", 1, (1, 50)),
    },
    "run_control": {"flow_id": ("flow_id", None, None)},
    "run_status": {},
    "verdict": {},
    "text": {"template": ("text", _REQUIRED, None)},
    "button": {
        "action": ("choice", _REQUIRED, ACTION_CHOICES),
        "flow_id": ("flow_id", None, None),
        "recipe": ("text", None, None),
        "variable": ("text", None, None),
        "value": ("any", None, None),
        "url": ("text", None, None),
    },
    "switch": {"variable": ("text", _REQUIRED, None), "scope": ("choice", "flow", SCOPE_CHOICES)},
    "param": {"node": ("text", _REQUIRED, None), "param": ("text", _REQUIRED, None)},
    "variable": {"variable": ("text", _REQUIRED, None), "scope": ("choice", "flow", SCOPE_CHOICES), "editable": ("bool", False, None)},
    "traffic_light": {},
    "conditional_light": {
        "key": ("text", _REQUIRED, None),
        "op": ("choice", _REQUIRED, OP_CHOICES),
        "value": ("any", _REQUIRED, None),
        "value2": ("any", None, None),
        "color_true": ("color", "#22c55e", None),
        "color_false": ("color", "#ef4444", None),
    },
    "group": {"title": ("text", "", None), "children": ("children", [], None)},
    "tabs": {"tabs": ("tabs", [], None)},
    "table": {"columns": ("columns", _REQUIRED, None), "rows": ("int", 10, (1, 200)), "rules": ("rules", [], None)},
    "line_chart": {"key": ("text", _REQUIRED, None), "points": ("int", 100, (2, 5000)), "lower": ("number", None, None), "upper": ("number", None, None)},
    "stats": {},
    "pie": {},
    "image_static": {"fixed_image_id": ("text", _REQUIRED, None)},
    "clock": {"timezone": ("text", "", None), "format": ("text", "HH:mm:ss", None)},
    "log": {"rows": ("int", 20, (1, 200))},
    "device_status": {},
    "child": {"dashboard_id": ("dashboard_id", _REQUIRED, None), "title": ("text", "", None)},
}

FLOW_WIDGET_TYPES = {
    "image",
    "images",
    "run_control",
    "run_status",
    "verdict",
    "text",
    "button",
    "switch",
    "param",
    "variable",
    "traffic_light",
    "conditional_light",
    "table",
    "line_chart",
    "stats",
    "pie",
}

DEFAULT_LAYOUT: dict[str, Any] = {
    "rows": 2,
    "cols": 4,
    "cells": [
        {"id": "image", "row": 1, "col": 1, "row_span": 2, "col_span": 2},
        {"id": "verdict", "row": 1, "col": 3, "row_span": 1, "col_span": 1},
        {"id": "stats", "row": 1, "col": 4, "row_span": 1, "col_span": 1},
        {"id": "control", "row": 2, "col": 3, "row_span": 1, "col_span": 2},
    ],
    "bars": {"top": True, "bottom": False, "left": False, "right": False},
    "default_flow_id": None,
    "widgets": [
        {"id": "latest_image", "type": "image", "cell": "image", "props": {"overlays": True, "crosshair": False, "history": 1}, "source": {"kind": "image"}},
        {"id": "verdict", "type": "verdict", "cell": "verdict", "props": {}, "source": {"kind": "status"}},
        {"id": "today", "type": "stats", "cell": "stats", "props": {}, "source": {"kind": "counts"}},
        {"id": "run", "type": "run_control", "cell": "control", "props": {}},
    ],
    "theme": {},
}


class DashboardError(ValueError):
    """Dashboard 版面設定錯誤。"""


def validate(layout: Any) -> dict[str, Any]:
    if not isinstance(layout, dict):
        raise DashboardError("layout must be an object")
    out = _base_layout(layout, strict=True)
    cells = _validate_cells(layout.get("cells"), out["rows"], out["cols"], strict=True)
    out["cells"] = cells
    out["widgets"] = _validate_widgets(layout.get("widgets"), {c["id"] for c in cells}, strict=True)
    return out


def effective(layout: Any) -> dict[str, Any]:
    if not isinstance(layout, dict):
        return copy.deepcopy(DEFAULT_LAYOUT)
    try:
        out = _base_layout(layout, strict=False)
        cells = _validate_cells(layout.get("cells"), out["rows"], out["cols"], strict=False)
        if not cells:
            return copy.deepcopy(DEFAULT_LAYOUT)
        out["cells"] = cells
        out["widgets"] = _validate_widgets(layout.get("widgets"), {c["id"] for c in cells}, strict=False)
        return out
    except Exception:  # noqa: BLE001 - 檢視端只需要可顯示的安全版面
        return copy.deepcopy(DEFAULT_LAYOUT)


def flows_of(layout: Any) -> set[int]:
    cfg = effective(layout)
    return _flows_of_effective(cfg, include_children=True)


def _flows_of_effective(cfg: dict[str, Any], *, include_children: bool) -> set[int]:
    default_flow = cfg.get("default_flow_id")
    found: set[int] = set()
    for widget in cfg.get("widgets") or []:
        wid_type = widget.get("type")
        props = widget.get("props") or {}
        source = widget.get("source") or {}
        for value in (source.get("flow_id"), props.get("flow_id")):
            if isinstance(value, int) and value > 0:
                found.add(value)
        if isinstance(default_flow, int) and default_flow > 0 and wid_type in FLOW_WIDGET_TYPES and not source.get("flow_id") and not props.get("flow_id"):
            found.add(default_flow)
        if wid_type == "images":
            for item in props.get("items") or []:
                fid = item.get("flow_id") if isinstance(item, dict) else None
                if isinstance(fid, int) and fid > 0:
                    found.add(fid)
    if include_children:
        child_ids = sorted({
            widget.get("props", {}).get("dashboard_id")
            for widget in cfg.get("widgets") or []
            if widget.get("type") == "child" and isinstance(widget.get("props", {}).get("dashboard_id"), int)
        })
        if child_ids:
            from apps.vision.models import Dashboard

            for child_layout in Dashboard.objects.filter(pk__in=child_ids).values_list("layout", flat=True):
                found |= _flows_of_effective(effective(child_layout), include_children=False)
    return found


def _base_layout(layout: dict[str, Any], *, strict: bool) -> dict[str, Any]:
    rows = _int_field(layout.get("rows", DEFAULT_LAYOUT["rows"]), "rows", (1, 10), strict=strict)
    cols = _int_field(layout.get("cols", DEFAULT_LAYOUT["cols"]), "cols", (1, 10), strict=strict)
    bars_raw = layout.get("bars", {})
    if strict and bars_raw is not None and not isinstance(bars_raw, dict):
        raise DashboardError("bars must be an object")
    bars = {}
    for key in ("top", "bottom", "left", "right"):
        value = (bars_raw or {}).get(key, False) if isinstance(bars_raw, dict) else False
        if strict and not isinstance(value, bool):
            raise DashboardError(f"bars.{key} must be a boolean")
        bars[key] = bool(value)
    default_flow = layout.get("default_flow_id")
    if default_flow is not None:
        if not isinstance(default_flow, int) or isinstance(default_flow, bool) or default_flow <= 0:
            if strict:
                raise DashboardError("default_flow_id must be a positive integer or null")
            default_flow = None
    theme = layout.get("theme") if isinstance(layout.get("theme"), dict) else {}
    if strict and "theme" in layout and not isinstance(layout.get("theme"), dict):
        raise DashboardError("theme must be an object")
    return {"rows": rows, "cols": cols, "cells": [], "bars": bars, "default_flow_id": default_flow, "widgets": [], "theme": theme}


def _validate_cells(raw: Any, rows: int, cols: int, *, strict: bool) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        if strict:
            raise DashboardError("cells must be a list")
        raw = []
    out: list[dict[str, Any]] = []
    ids: set[str] = set()
    occupied: dict[tuple[int, int], str] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            if strict:
                raise DashboardError(f"cell[{index}] must be an object")
            continue
        cell_id = _text(item.get("id"), f"cell[{index}].id", required=True, strict=strict)
        if not cell_id:
            continue
        if cell_id in ids:
            if strict:
                raise DashboardError(f"Duplicate cell id '{cell_id}'")
            continue
        try:
            row = _int_field(item.get("row"), f"cell '{cell_id}'.row", (1, rows), strict=strict)
            col = _int_field(item.get("col"), f"cell '{cell_id}'.col", (1, cols), strict=strict)
            row_span = _int_field(item.get("row_span", 1), f"cell '{cell_id}'.row_span", (1, rows), strict=strict)
            col_span = _int_field(item.get("col_span", 1), f"cell '{cell_id}'.col_span", (1, cols), strict=strict)
            if row + row_span - 1 > rows or col + col_span - 1 > cols:
                raise DashboardError(f"Cell '{cell_id}' exceeds the grid")
            for r in range(row, row + row_span):
                for c in range(col, col + col_span):
                    if (r, c) in occupied:
                        raise DashboardError(f"Cell '{cell_id}' overlaps cell '{occupied[(r, c)]}'")
        except DashboardError:
            if strict:
                raise
            continue
        for r in range(row, row + row_span):
            for c in range(col, col + col_span):
                occupied[(r, c)] = cell_id
        ids.add(cell_id)
        out.append({"id": cell_id, "row": row, "col": col, "row_span": row_span, "col_span": col_span})
    return out


def _validate_widgets(raw: Any, cell_ids: set[str], *, strict: bool) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        if strict:
            raise DashboardError("widgets must be a list")
        raw = []
    out: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            if strict:
                raise DashboardError(f"widget[{index}] must be an object")
            continue
        wid = _text(item.get("id"), f"widget[{index}].id", required=True, strict=strict)
        if not wid:
            continue
        if wid in ids:
            if strict:
                raise DashboardError(f"Duplicate widget id '{wid}'")
            continue
        typ = item.get("type")
        if typ not in WIDGET_TYPES:
            if strict:
                raise DashboardError(f"Widget '{wid}' has unknown type '{typ}'")
            continue
        cell = item.get("cell")
        if not isinstance(cell, str) or cell not in cell_ids:
            if strict:
                raise DashboardError(f"Widget '{wid}' references unknown cell '{cell}'")
            continue
        try:
            props = _props(wid, typ, item.get("props") or {}, strict=strict)
            source = _source(wid, item.get("source"), strict=strict)
        except DashboardError:
            if strict:
                raise
            continue
        out.append({"id": wid, "type": typ, "cell": cell, "props": props, **({"source": source} if source else {})})
        ids.add(wid)
    return out


def _props(wid: str, typ: str, raw: Any, *, strict: bool) -> dict[str, Any]:
    if not isinstance(raw, dict):
        if strict:
            raise DashboardError(f"Widget '{wid}' props must be an object")
        raw = {}
    spec = WIDGET_PROPS[typ]
    if strict:
        extra = set(raw) - set(spec)
        if extra:
            raise DashboardError(f"Widget '{wid}' has unknown props.{sorted(extra)[0]}")
    out: dict[str, Any] = {}
    for name, (kind, default, constraint) in spec.items():
        # 沒給、或給 null 的選填 props 都算「用預設」：effective() 會把選填欄位補成 None，
        # 檢視端 GET 回來的版面必須能原樣 PATCH 回去（JSON 編輯器就是這條路）。
        if name not in raw or (raw[name] is None and default is not _REQUIRED):
            if default is _REQUIRED:
                raise DashboardError(f"Widget '{wid}' missing props.{name}")
            out[name] = copy.deepcopy(default)
            continue
        # 必填與否看 spec 的預設值：預設是空字串的欄位（時鐘時區、群組標題）送空字串是合法的，
        # 否則 validate 會把它補成 ""，effective 再把整個 widget 判成壞的丟掉（存了就消失）。
        out[name] = _check_value(raw[name], f"Widget '{wid}' props.{name}", kind, constraint,
                                 strict=strict, required=default is _REQUIRED)
    return out


def _source(wid: str, raw: Any, *, strict: bool) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise DashboardError(f"Widget '{wid}' source must be an object")
        return {}
    out: dict[str, Any] = {}
    allowed = {"flow_id", "kind", "key"}
    if strict:
        extra = set(raw) - allowed
        if extra:
            raise DashboardError(f"Widget '{wid}' has unknown source.{sorted(extra)[0]}")
    if "flow_id" in raw and raw["flow_id"] is not None:
        out["flow_id"] = _check_value(raw["flow_id"], f"Widget '{wid}' source.flow_id", "flow_id", None, strict=strict)
    if "kind" in raw:
        out["kind"] = _check_value(raw["kind"], f"Widget '{wid}' source.kind", "choice", SOURCE_KINDS, strict=strict)
    if "key" in raw and raw["key"] is not None:
        out["key"] = _check_value(raw["key"], f"Widget '{wid}' source.key", "text", None, strict=strict)
    return out


def _check_value(value: Any, field: str, kind: str, constraint: Any, *, strict: bool, required: bool = True) -> Any:
    if kind == "any":
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise DashboardError(f"{field} must be a boolean")
        return value
    if kind == "int":
        return _int_field(value, field, constraint, strict=strict)
    if kind == "number":
        if value is None:
            return None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise DashboardError(f"{field} must be a number")
        return value
    if kind == "flow_id":
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise DashboardError(f"{field} must be a positive integer")
        return value
    if kind == "dashboard_id":
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise DashboardError(f"{field} must be a positive integer")
        return value
    if kind == "choice":
        if value not in constraint:
            raise DashboardError(f"{field} must be one of {', '.join(constraint)}")
        return value
    if kind == "color":
        if not isinstance(value, str) or not _COLOR_RE.match(value):
            raise DashboardError(f"{field} must be a #rrggbb color")
        return value
    if kind == "text":
        return _text(value, field, required=required, strict=strict)
    if kind == "children":
        return _string_list(value, field)
    if kind == "columns":
        values = _string_list(value, field)
        if not values:
            raise DashboardError(f"{field} must contain at least one key")
        return values
    if kind == "tabs":
        return _tabs(value, field)
    if kind == "rules":
        return _rules(value, field)
    if kind == "image_items":
        return _image_items(value, field)
    raise DashboardError(f"{field} has unsupported validator {kind}")


def _int_field(value: Any, field: str, bounds: tuple[int, int], *, strict: bool) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        if strict:
            raise DashboardError(f"{field} must be an integer")
        value = bounds[0]
    low, high = bounds
    if value < low or value > high:
        if strict:
            raise DashboardError(f"{field} must be between {low} and {high}")
        value = max(low, min(high, int(value)))
    return int(value)


def _text(value: Any, field: str, *, required: bool, strict: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        if strict:
            raise DashboardError(f"{field} must be a string")
        return None
    text = value.strip()
    if required and not text:
        raise DashboardError(f"{field} is required")
    return text[:500]


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise DashboardError(f"{field} must be a list")
    out = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise DashboardError(f"{field}[{index}] must be a non-empty string")
        out.append(item.strip()[:120])
    return out


def _tabs(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise DashboardError(f"{field} must be a list")
    out = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise DashboardError(f"{field}[{index}] must be an object")
        title = _text(item.get("title"), f"{field}[{index}].title", required=True, strict=True)
        children = _string_list(item.get("children", []), f"{field}[{index}].children")
        out.append({"title": title, "children": children})
    return out


def _rules(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise DashboardError(f"{field} must be a list")
    out = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise DashboardError(f"{field}[{index}] must be an object")
        key = _text(item.get("key"), f"{field}[{index}].key", required=True, strict=True)
        op = _check_value(item.get("op"), f"{field}[{index}].op", "choice", OP_CHOICES, strict=True)
        row = {"key": key, "op": op, "value": item.get("value")}
        if item.get("color") is not None:
            row["color"] = _check_value(item.get("color"), f"{field}[{index}].color", "color", None, strict=True)
        out.append(row)
    return out


def _image_items(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise DashboardError(f"{field} must be a list")
    out = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise DashboardError(f"{field}[{index}] must be an object")
        row: dict[str, Any] = {}
        if item.get("flow_id") is not None:
            row["flow_id"] = _check_value(item["flow_id"], f"{field}[{index}].flow_id", "flow_id", None, strict=True)
        for key in ("node", "port", "title"):
            if item.get(key) is not None:
                row[key] = _text(item.get(key), f"{field}[{index}].{key}", required=True, strict=True)
        out.append(row)
    return out
