"""複合工具（PRODUCT-DIRECTION v2 §3）：用底層工具接好線、宣告對外介面，就是一個新的工具。

- 站台級資源 `CompositeTool`：key（工具箱的型別是 `composite:<key>`）、名稱、分類、圖示、對外介面；內部圖存在
  `Flow.kind="tool"` 的流程列（沿用編輯器、草稿、版本與衝突保護；流程清單不列它）。
- 登錄表 `registry()` 由資料庫建成 `CompositeToolType`（形狀與內建工具相同：params／inputs／outputs），`tools.get()`
  查不到內建就來這裡，所以工具目錄、圖驗證、參數卡、配方、自動調參都不必知道它是複合的。
- **載入時展平**（§3-6）：`flatten()` 在 compile 前把實例換成內部節點——id 前綴 `<instance>.<inner>`、對外埠的邊重接到
  內部節點、對外參數值綁回內部參數、實例上的具名輸出名稱搬到內部節點；引擎與 run report 都是平的，
  結束時 `fold_report()` 依實例把內部報告摺成一筆（最差狀態、耗時加總、對外輸出）。
- 對外介面的 key：埠 `<inner>:<port>`、參數 `<inner>:<param>`；只有 `exposed: true` 的埠、有列出的參數才成為介面。
- 巢狀只有兩層（流程 → 工具）：複合工具的內部圖不能再放複合工具（`check_references` 存檔時擋，`MAX_DEPTH`＝1）。直接引用、不鎖版本（改工具本體，所有流程立刻跟著變；版本鎖定是 P5）。
"""

from __future__ import annotations

import copy
import logging
import re
import threading
from typing import Any

from django.db import transaction

from apps.core.errors import Conflict, NotFound, ValidationError
from apps.vision.tools import base as tools

log = logging.getLogger(__name__)

PREFIX = "composite:"
#: 巢狀只有兩層：流程裡放複合工具，複合工具裡不能再放複合工具（2026-09-11 拍板）
MAX_DEPTH = 1
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
#: 展平後的節點 id：<instance>.<inner>
INSTANCE_SEP = "."
#: 對外埠／參數 key：<inner>:<port>
PORT_SEP = ":"
#: 工具編輯畫布試執行時餵影像的取像節點
INPUT_NODE_ID = "_tool_input"
CATEGORIES = tuple(tools.CATEGORY_LABELS)
FLOW_NAME_PREFIX = "tool:"


def is_composite(node_type: Any) -> bool:
    return isinstance(node_type, str) and node_type.startswith(PREFIX)


def type_key(tool_key: str) -> str:
    return f"{PREFIX}{tool_key}"


def split_key(key: str) -> tuple[str, str]:
    """`<inner>:<port>` → (inner, port)；沒有分隔就整個當 inner。"""
    inner, sep, port = str(key).partition(PORT_SEP)
    return inner, port if sep else ""


# ---------------------------------------------------------------------------
# 登錄表：資料庫列 → ToolType
# ---------------------------------------------------------------------------
class CompositeToolType:
    """形狀與 `tools.Tool` 相同的工具型別；永遠不會被 execute（compile 前已展平）。"""

    heavy = False
    version = 1
    enabled = True
    connection_params: tuple[str, ...] = ()
    cases_param = ""
    accepts: tuple[str, ...] = ("u8",)
    wants_gray = False
    source = "composite"
    #: 隱含埠（直通影像、標記）不套在複合工具上；位置修正埠仍依有沒有 roi 參數決定
    implicit_ports = False

    def __init__(self, row, graph: dict[str, Any], resolve) -> None:
        self.tool_id = int(row.id)
        self.tool_key = str(row.key)
        self.key = type_key(self.tool_key)
        self.label = str(row.label)
        self.description = str(row.description or "")
        self.category = str(row.category or "logic")
        self.icon = str(row.icon or "Boxes")
        self.builtin = bool(row.builtin)
        self.flow_id = int(row.flow_id)
        self.updated_at = row.updated_at.isoformat() if row.updated_at else ""
        self.graph = graph
        self.interface = tools.node_interface({"interface": row.interface if isinstance(row.interface, dict) else {}})
        nodes = {str(n.get("id")): n for n in graph.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
        self.inputs: list[tools.Port] = []
        self.outputs: list[tools.Port] = []
        self.params: list[tools.Param] = []
        #: 對外埠 key → (inner id, inner port, type)；展平與摺疊都靠它
        self.input_map: dict[str, tuple[str, str]] = {}
        self.output_map: dict[str, tuple[str, str, str]] = {}
        self.param_map: dict[str, tuple[str, str]] = {}
        for spec in _ordered(self.interface["inputs"]):
            if spec.get("exposed") is not True:
                continue
            inner_id, port_key = split_key(spec["key"])
            node = nodes.get(inner_id)
            inner_tool = resolve(node) if node else None
            port = _input_port(inner_tool, port_key) if inner_tool else None
            if port is None:
                continue
            label = str(spec.get("alias") or "").strip() or _port_label(node, inner_tool, port.label)
            self.inputs.append(tools.Port(spec["key"], label, port.type, required=port.required, multiple=port.multiple,
                                          accepts_semantics=tuple(port.accepts_semantics), primary=bool(port.primary)))
            self.input_map[spec["key"]] = (inner_id, port_key)
        for spec in _ordered(self.interface["outputs"]):
            if spec.get("exposed") is not True:
                continue
            inner_id, port_key = split_key(spec["key"])
            node = nodes.get(inner_id)
            inner_tool = resolve(node) if node else None
            port = _output_port(inner_tool, node, port_key) if inner_tool else None
            if port is None:
                continue
            label = str(spec.get("alias") or "").strip() or _port_label(node, inner_tool, port.label)
            self.outputs.append(tools.Port(spec["key"], label, port.type, required=False, multiple=False, tone=port.tone,
                                           semantic=port.semantic, primary=bool(port.primary)))
            self.output_map[spec["key"]] = (inner_id, port_key, port.type)
        for spec in _ordered(self.interface["params"]):
            inner_id, param_key = split_key(spec["key"])
            node = nodes.get(inner_id)
            inner_tool = resolve(node) if node else None
            base = next((p for p in (inner_tool.params if inner_tool else []) if p.key == param_key), None)
            if base is None:
                continue
            node_params = node.get("params") if isinstance(node.get("params"), dict) else {}
            default = spec["default"] if "default" in spec else node_params.get(param_key, base.default)
            self.params.append(tools.Param(
                spec["key"], str(spec.get("alias") or "").strip() or _port_label(node, inner_tool, base.label), kind=base.kind,
                required=base.required, default=default, help_text=str(spec.get("help_text") or base.help_text),
                options=list(base.options), unit=base.unit, minimum=base.minimum, maximum=base.maximum, step=base.step,
                shapes=list(base.shapes), accept=base.accept, group=base.group,
                teach=bool(spec["teach"]) if isinstance(spec.get("teach"), bool) else base.teach,
            ))
            self.param_map[spec["key"]] = (inner_id, param_key)

    def execute(self, ctx):  # pragma: no cover - 展平後永遠不會執行到
        raise RuntimeError(f"Composite tool '{self.tool_key}' must be flattened before execution")


def _ordered(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(specs, key=lambda s: (s.get("order") if isinstance(s.get("order"), (int, float)) and not isinstance(s.get("order"), bool) else 1e9))


def _port_label(node: dict[str, Any] | None, inner_tool, port_label: str) -> str:
    owner = str((node or {}).get("label") or getattr(inner_tool, "label", "") or (node or {}).get("id") or "")
    return f"{owner}: {port_label}" if owner else port_label


def _input_port(inner_tool, port_key: str) -> tools.Port | None:
    for p in inner_tool.inputs:
        if p.key == port_key:
            return p
    bound = tools.param_port(inner_tool, port_key)
    if bound is not None:
        return bound
    implicit = tools.implicit_input(port_key)
    if implicit is not None and implicit.shows_on(inner_tool):
        return tools.Port(implicit.key, implicit.label, implicit.type, required=False, multiple=implicit.multiple, accepts_semantics=implicit.accepts_semantics)
    return None


def _output_port(inner_tool, node: dict[str, Any] | None, port_key: str) -> tools.Port | None:
    for p in inner_tool.outputs:
        if p.key == port_key:
            return p
    for p in tools.case_ports(inner_tool, node):
        if p.key == port_key:
            return p
    implicit = tools.implicit_output(port_key)
    if implicit is not None and implicit.shows_on(inner_tool):
        return tools.Port(implicit.key, implicit.label, implicit.type, required=False)
    return None


_lock = threading.Lock()
_cache: dict[str, CompositeToolType] | None = None


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def registry() -> dict[str, CompositeToolType]:
    """`composite:<key>` → ToolType。單一 API 行程，快取到下次 invalidate。"""
    global _cache
    cached = _cache
    if cached is not None:
        return cached
    with _lock:
        if _cache is not None:
            return _cache
        try:
            loaded = _load()
        except Exception:  # noqa: BLE001 - 資料庫不可用（例如 SimpleTestCase、migrate 前）時工具目錄仍要列得出內建工具
            log.debug("複合工具登錄表載入失敗，暫時視為沒有複合工具", exc_info=True)
            return {}
        _cache = loaded
        return _cache


def _load() -> dict[str, CompositeToolType]:
    from apps.vision.models import CompositeTool

    rows = {row.key: row for row in CompositeTool.objects.select_related("flow").order_by("key")}
    built: dict[str, CompositeToolType] = {}
    building: set[str] = set()

    def resolve(node: dict[str, Any] | None):
        ntype = str((node or {}).get("type") or "")
        if is_composite(ntype):
            return build(ntype[len(PREFIX):])
        try:
            return tools.get(ntype)
        except tools.UnknownToolType:
            return None

    def build(key: str) -> CompositeToolType | None:
        if key in built:
            return built[key]
        row = rows.get(key)
        if row is None or key in building:
            return None
        building.add(key)
        try:
            built[key] = CompositeToolType(row, row.flow.graph or {"nodes": [], "edges": []}, resolve)
        except Exception:  # noqa: BLE001 - 一個壞掉的工具不該讓整個目錄消失
            log.warning("複合工具 %s 建不起來", key, exc_info=True)
            return None
        finally:
            building.discard(key)
        return built[key]

    for key in rows:
        build(key)
    return {t.key: t for t in built.values()}


def get_type(key: str) -> CompositeToolType | None:
    return registry().get(key if key.startswith(PREFIX) else type_key(key))


def all_types() -> list[CompositeToolType]:
    return sorted(registry().values(), key=lambda t: (tools.CATEGORY_ORDER.get(t.category, 99), t.label))


# ---------------------------------------------------------------------------
# 展平與摺疊
# ---------------------------------------------------------------------------
class FlattenError(ValidationError):
    pass


def flatten(graph: dict[str, Any], *, depth: int = 0) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """實例 → 內部節點。回 (平的圖, {instance id: {"tool", "inner", "outputs"}})；沒有複合工具時原圖直接回。"""
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not any(is_composite(n.get("type")) for n in nodes if isinstance(n, dict)):
        return graph, {}
    if depth >= MAX_DEPTH:
        raise FlattenError(f"Composite tools nest deeper than {MAX_DEPTH} levels", code="composite_too_deep")
    reg = registry()
    out_nodes: list[dict[str, Any]] = []
    out_edges: list[dict[str, Any]] = []
    instances: dict[str, dict[str, Any]] = {}
    roots: dict[str, list[str]] = {}
    roi_owners: dict[str, list[str]] = {}
    for n in nodes:
        ntype = str(n.get("type") or "")
        if not is_composite(ntype):
            out_nodes.append(n)
            continue
        ct = reg.get(ntype)
        if ct is None:
            raise FlattenError(f"Unknown composite tool '{ntype[len(PREFIX):]}'", code="unknown_composite", details={"node_id": str(n.get("id"))})
        inner_graph, inner_instances = flatten(ct.graph, depth=depth + 1)
        inst = str(n["id"])
        prefix = f"{inst}{INSTANCE_SEP}"
        params = n.get("params") if isinstance(n.get("params"), dict) else {}
        bind: dict[str, dict[str, Any]] = {}
        for ext_key, (inner_id, param_key) in ct.param_map.items():
            value = params.get(ext_key)
            if value is None or value == "":
                continue
            # 巢狀：對外參數可能指到內部另一個複合工具的對外參數，沿著它往下解到真正的節點
            node_id, key = _resolve_param(inner_instances, inner_id, param_key)
            bind.setdefault(node_id, {})[key] = value
        by_id: dict[str, dict[str, Any]] = {}
        for inner in inner_graph.get("nodes") or []:
            m = copy.deepcopy(inner)
            inner_id = str(m["id"])
            m["id"] = prefix + inner_id
            if n.get("enabled") is False:
                m["enabled"] = False
            if n.get("continue_on_error"):
                m["continue_on_error"] = True
            _strip_aliases(m)
            if inner_id in bind:
                m["params"] = {**(m.get("params") if isinstance(m.get("params"), dict) else {}), **bind[inner_id]}
            by_id[inner_id] = m
            out_nodes.append(m)
        # 實例上的具名輸出名稱 → 內部節點（引擎的 _apply_publish 只看節點自己的 interface）
        for spec in tools.node_interface(n)["outputs"]:
            alias = str(spec.get("alias") or "").strip()
            mapped = ct.output_map.get(spec["key"])
            if not alias or not mapped:
                continue
            node_id, port = _resolve_source(inner_instances, mapped[0], mapped[1])
            if node_id in by_id:
                tools.set_output_alias(by_id[node_id], port, alias)
        inner_edges = inner_graph.get("edges") or []
        has_incoming = {str(e.get("target")) for e in inner_edges}
        for e in inner_edges:
            out_edges.append({**e, "id": f"{prefix}{e.get('id') or ''}".rstrip(INSTANCE_SEP) or None, "source": prefix + str(e.get("source")), "target": prefix + str(e.get("target"))})
        roots[inst] = [prefix + inner_id for inner_id in by_id if inner_id not in has_incoming]
        roi_owners[inst] = sorted({prefix + inner_id for inner_id, _ in ct.param_map.values() if any(p.kind == "roi" and p.key.startswith(f"{inner_id}{PORT_SEP}") for p in ct.params)})
        instances[inst] = {
            "tool": ct.tool_key,
            "enabled": n.get("enabled") is not False,
            "inner": [prefix + inner_id for inner_id in by_id],
            "inputs": {ext_key: (prefix + inner_id, port_key) for ext_key, (inner_id, port_key) in ct.input_map.items()},
            "params": {ext_key: (prefix + inner_id, param_key) for ext_key, (inner_id, param_key) in ct.param_map.items()},
            "outputs": {ext_key: (prefix + inner_id, port_key, port_type) for ext_key, (inner_id, port_key, port_type) in ct.output_map.items()},
        }
        for sub_inst, info in inner_instances.items():
            instances[prefix + sub_inst] = {**info, "inner": [prefix + x for x in info["inner"]],
                                            "inputs": {k: (prefix + v[0], v[1]) for k, v in info["inputs"].items()},
                                            "params": {k: (prefix + v[0], v[1]) for k, v in info["params"].items()},
                                            "outputs": {k: (prefix + v[0], v[1], v[2]) for k, v in info["outputs"].items()}}
    for e in edges:
        s, t = str(e.get("source")), str(e.get("target"))
        edge = dict(e)
        if s in instances:
            ct = reg[type_key(instances[s]["tool"])]
            sh = str(e.get("source_handle") or (ct.outputs[0].key if ct.outputs else ""))
            edge["source"], edge["source_handle"] = _resolve_source(instances, s, sh)
        if t in instances:
            th = str(e.get("target_handle") or "")
            if th in ("", tools.FLOW_IN):
                for i, root in enumerate(roots[t]):
                    out_edges.append({**edge, "id": f"{e.get('id') or ''}#{i}", "target": root, "target_handle": tools.FLOW_IN})
                continue
            if th == tools.TRANSFORM_IN:
                for i, owner in enumerate(roi_owners[t]):
                    out_edges.append({**edge, "id": f"{e.get('id') or ''}#{i}", "target": owner, "target_handle": tools.TRANSFORM_IN})
                continue
            edge["target"], edge["target_handle"] = _resolve_target(instances, t, th)
        out_edges.append(edge)
    return {**graph, "nodes": out_nodes, "edges": out_edges}, instances


def _resolve_target(instances: dict[str, dict[str, Any]], node: str, handle: str) -> tuple[str, str]:
    """對外輸入埠 → 真正的內部節點與埠；內部又是複合工具就繼續往下解（巢狀）。"""
    while node in instances:
        mapped = instances[node]["inputs"].get(handle)
        if mapped is None:
            inner_id, port = split_key(handle)
            return f"{node}{INSTANCE_SEP}{inner_id}", port
        node, handle = mapped
    return node, handle


def _resolve_param(instances: dict[str, dict[str, Any]], node: str, key: str) -> tuple[str, str]:
    while node in instances:
        mapped = instances[node]["params"].get(key)
        if mapped is None:
            inner_id, param = split_key(key)
            return f"{node}{INSTANCE_SEP}{inner_id}", param
        node, key = mapped
    return node, key


def _resolve_source(instances: dict[str, dict[str, Any]], node: str, handle: str) -> tuple[str, str]:
    while node in instances:
        mapped = instances[node]["outputs"].get(handle)
        if mapped is None:
            inner_id, port = split_key(handle)
            return f"{node}{INSTANCE_SEP}{inner_id}", port
        node, handle = mapped[0], mapped[1]
    return node, handle


def _strip_aliases(node: dict[str, Any]) -> None:
    """工具內部的具名輸出名稱不外洩：同一個工具放兩次會撞名，只有實例上取的名稱才發布。"""
    iface = node.get(tools.INTERFACE_KEY)
    if not isinstance(iface, dict) or not isinstance(iface.get("outputs"), list):
        return
    outputs = []
    for spec in iface["outputs"]:
        if isinstance(spec, dict) and "alias" in spec:
            spec = {k: v for k, v in spec.items() if k != "alias"}
            if set(spec) == {"key"}:
                continue
        outputs.append(spec)
    if outputs:
        iface["outputs"] = outputs
    else:
        iface.pop("outputs", None)
    if not iface:
        node.pop(tools.INTERFACE_KEY, None)


_STATUS_RANK = {"error": 3, "ng": 2, "ok": 1, "skipped": 0}


def fold_report(report, instances: dict[str, dict[str, Any]]) -> None:
    """內部節點的報告摺成實例一筆：最差狀態、耗時加總、對外輸出與分支、標記合併；內部報告仍留著（統計與影像 ref 用）。"""
    if not instances:
        return
    from apps.vision.engine import NodeReport

    # 巢狀：先摺內層（外層的對外輸出可能指到內層實例）
    for inst, info in sorted(instances.items(), key=lambda kv: -kv[0].count(INSTANCE_SEP)):
        if inst in report.nodes:
            continue
        inner = [report.nodes[nid] for nid in info["inner"] if nid in report.nodes]
        if not inner:
            continue
        status = max((r.status for r in inner), key=lambda s: _STATUS_RANK.get(s, 0))
        message = next((r.message for r in inner if r.status == status and r.message), "")
        if info.get("enabled") is False:
            # 停用的實例：內部單進單出的節點會直通（狀態 ok），但整個工具算被跳過
            status, message = "skipped", "disabled"
        outputs: dict[str, Any] = {}
        branch: str | None = None
        for ext_key, (inner_id, port_key, port_type) in info["outputs"].items():
            r = report.nodes.get(inner_id)
            if r is None:
                continue
            if port_type == "flow":
                if r.branch == port_key:
                    branch = ext_key
            elif port_key in r.outputs:
                outputs[ext_key] = r.outputs[port_key]
        overlays = [o for r in inner for o in r.overlays]
        overlay_on = next((r.overlay_on for r in inner if r.overlay_on), None)
        report.nodes[inst] = NodeReport(
            status=status, duration_ms=sum(r.duration_ms for r in inner), message=message, branch=branch, outputs=outputs,
            overlays=overlays, overlay_on=overlay_on, detail={"composite": info["tool"], "steps": list(info["inner"])},
        )


def preview_graph(graph: dict[str, Any], interface: dict[str, Any] | None) -> dict[str, Any]:
    """工具編輯畫布的試執行：對外影像輸入接到一個只吃暫存／推送影像的取像節點，其餘對外輸入留空（該步驟會被跳過）。"""
    iface = tools.node_interface({"interface": interface or {}})
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    by_id = {str(n.get("id")): n for n in nodes if isinstance(n, dict)}
    targets: list[tuple[str, str]] = []
    for spec in iface["inputs"]:
        if spec.get("exposed") is not True:
            continue
        inner_id, port_key = split_key(spec["key"])
        node = by_id.get(inner_id)
        if node is None:
            continue
        try:
            inner_tool = tools.get(str(node.get("type") or ""))
        except tools.UnknownToolType:
            continue
        port = _input_port(inner_tool, port_key)
        if port is not None and port.type == "image":
            targets.append((inner_id, port_key))
    if not targets or INPUT_NODE_ID in by_id:
        return graph
    top = min((float((n.get("position") or {}).get("y") or 0) for n in nodes), default=0.0)
    left = min((float((n.get("position") or {}).get("x") or 0) for n in nodes), default=0.0)
    nodes.append({"id": INPUT_NODE_ID, "type": "image_source", "label": "Tool input", "params": {"mode": "input"}, "position": {"x": left - 280, "y": top}})
    for inner_id, port_key in targets:
        edges.append({"id": f"{INPUT_NODE_ID}->{inner_id}:{port_key}", "source": INPUT_NODE_ID, "source_handle": "image", "target": inner_id, "target_handle": port_key})
    return {**graph, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# 引用檢查：循環、深度、使用者
# ---------------------------------------------------------------------------
def referenced_keys(graph: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for n in graph.get("nodes") or []:
        ntype = str((n or {}).get("type") or "") if isinstance(n, dict) else ""
        if is_composite(ntype) and ntype[len(PREFIX):] not in keys:
            keys.append(ntype[len(PREFIX):])
    return keys


def check_references(tool_key: str | None, graph: dict[str, Any], *, chain: tuple[str, ...] = ()) -> int:
    """回這張圖的巢狀深度（不含自己）。複合工具的內部圖裡不能再放複合工具（流程與工具是僅有的兩層）；
    流程裡的實例仍檢查循環與深度（訊息帶路徑）。"""
    reg = registry()
    depth = 0
    refs = referenced_keys(graph)
    if tool_key is not None and refs:
        raise ValidationError(f"A composite tool cannot contain another composite tool ({', '.join(refs)}); flows and tools are the only two levels", code="composite_nested", details={"keys": refs})
    for key in refs:
        path = " > ".join((*chain, tool_key or "(flow)", key))
        if key == tool_key or key in chain:
            raise ValidationError(f"Composite tool '{key}' would reference itself: {path}", code="composite_cycle", details={"path": path})
        sub = reg.get(type_key(key))
        if sub is None:
            raise ValidationError(f"Unknown composite tool '{key}'", code="unknown_composite", details={"key": key})
        depth = max(depth, 1 + check_references(key, sub.graph, chain=(*chain, tool_key or "(flow)")))
    if depth > MAX_DEPTH:
        raise ValidationError(f"Composite tools nest deeper than {MAX_DEPTH} levels", code="composite_too_deep")
    return depth


def usage(tool_key: str) -> dict[str, list[dict[str, Any]]]:
    """哪些流程、哪些其他複合工具用到它（改工具本體前的影響清單，§3-5）。"""
    from apps.vision.models import CompositeTool, Flow

    ntype = type_key(tool_key)
    flows: list[dict[str, Any]] = []
    tools_using: list[dict[str, Any]] = []
    tool_by_flow = {t.flow_id: t for t in CompositeTool.objects.only("id", "key", "label", "flow_id")}
    for flow in Flow.objects.only("id", "name", "kind", "graph").order_by("name"):
        count = sum(1 for n in (flow.graph or {}).get("nodes") or [] if isinstance(n, dict) and n.get("type") == ntype)
        if not count:
            continue
        if flow.kind == "tool":
            owner = tool_by_flow.get(flow.id)
            if owner is not None:
                tools_using.append({"id": owner.id, "key": owner.key, "label": owner.label, "count": count})
        else:
            flows.append({"id": flow.id, "name": flow.name, "count": count})
    return {"flows": flows, "tools": tools_using}


# ---------------------------------------------------------------------------
# CRUD（API 與匯入共用）
# ---------------------------------------------------------------------------
def _clean_key(value: Any) -> str:
    key = str(value or "").strip().lower()
    if not KEY_RE.match(key):
        raise ValidationError("The tool key must start with a letter and use only lowercase letters, digits and underscores (2-64 characters)", code="bad_tool_key", details={"field": "key"})
    if tools.has(key):
        raise ValidationError(f"'{key}' is already a built-in tool key", code="bad_tool_key", details={"field": "key"})
    return key


def _clean_meta(payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "label" in payload or not partial:
        label = str(payload.get("label") or "").strip()
        if not label:
            raise ValidationError("The tool needs a name", code="bad_tool_label", details={"field": "label"})
        out["label"] = label[:120]
    if "description" in payload:
        out["description"] = str(payload.get("description") or "")
    if "category" in payload or not partial:
        category = str(payload.get("category") or "logic")
        if category not in CATEGORIES:
            raise ValidationError(f"Unknown category '{category}'", code="bad_tool_category", details={"field": "category"})
        out["category"] = category
    if "icon" in payload or not partial:
        out["icon"] = (str(payload.get("icon") or "").strip() or "Boxes")[:64]
    return out


def _clean_interface(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError("The interface must be an object", code="bad_interface", details={"field": "interface"})
    out: dict[str, Any] = {}
    for section in ("inputs", "outputs", "params"):
        items = value.get(section)
        if items is None:
            continue
        if not isinstance(items, list):
            raise ValidationError(f"interface.{section} must be a list", code="bad_interface", details={"field": section})
        clean: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or not str(item.get("key") or ""):
                raise ValidationError(f"interface.{section} entries need a key", code="bad_interface", details={"field": section})
            if "exposed" in item and not isinstance(item["exposed"], bool):
                raise ValidationError(f"interface.{section} '{item['key']}' exposed must be true or false", code="bad_interface", details={"field": section})
            if "order" in item and (isinstance(item["order"], bool) or not isinstance(item["order"], (int, float))):
                raise ValidationError(f"interface.{section} '{item['key']}' order must be a number", code="bad_interface", details={"field": section})
            if "alias" in item and item["alias"] is not None and not isinstance(item["alias"], str):
                raise ValidationError(f"interface.{section} '{item['key']}' alias must be text", code="bad_interface", details={"field": section})
            if section == "params" and "teach" in item and not isinstance(item["teach"], bool):
                raise ValidationError(f"interface.params '{item['key']}' teach must be true or false", code="bad_interface", details={"field": section})
            clean.append(dict(item))
        if clean:
            out[section] = clean
    return out


def _clean_graph(tool_key: str | None, value: Any) -> dict[str, Any]:
    from apps.vision.graph import validate_graph

    graph = validate_graph(value if value is not None else {"nodes": [], "edges": []})
    for n in graph.get("nodes") or []:
        # 內部節點 id 不能叫 param：對外埠 key `param:<port>` 會被當成參數訂閱埠
        if str(n.get("id") or "") == tools.PARAM_PREFIX.rstrip(PORT_SEP):
            raise ValidationError(f"Node id '{n.get('id')}' is reserved inside a composite tool", code="bad_node_id")
    check_references(tool_key, graph)
    return graph


def get_tool(tool_id: int):
    from apps.vision.models import CompositeTool

    row = CompositeTool.objects.select_related("flow", "created_by").filter(pk=tool_id).first()
    if row is None:
        raise NotFound(f"Composite tool {tool_id} not found", code="composite_not_found")
    return row


def create(user, payload: dict[str, Any], *, builtin: bool = False):
    from apps.vision.models import CompositeTool, Flow

    key = _clean_key(payload.get("key"))
    meta = _clean_meta(payload, partial=False)
    graph = _clean_graph(key, payload.get("graph"))
    interface = _clean_interface(payload.get("interface"))
    with transaction.atomic():
        if CompositeTool.objects.filter(key=key).exists():
            raise Conflict(f"A composite tool with key '{key}' already exists", code="composite_exists", details={"key": key})
        flow = Flow.objects.create(name=f"{FLOW_NAME_PREFIX}{key}", description=meta.get("description", ""), graph=graph, kind="tool",
                                   owner=user if getattr(user, "pk", None) else None, is_enabled=False)
        row = CompositeTool.objects.create(flow=flow, key=key, builtin=builtin, interface=interface, created_by=flow.owner, **meta)
    invalidate()
    return row


def update(row, payload: dict[str, Any], *, user=None):
    from apps.vision import versions

    if row.builtin:
        raise Conflict("Built-in composite tools are read-only; save a copy first", code="composite_builtin")
    meta = _clean_meta(payload, partial=True)
    changed_graph = "graph" in payload
    graph = _clean_graph(row.key, payload.get("graph")) if changed_graph else None
    interface = _clean_interface(payload.get("interface")) if "interface" in payload else None
    with transaction.atomic():
        for field_name, value in meta.items():
            setattr(row, field_name, value)
        if interface is not None:
            row.interface = interface
        flow = row.flow
        if "description" in meta:
            flow.description = meta["description"]
        if graph is not None and graph != (flow.graph or {}):
            flow.graph = graph
            flow.version += 1
        flow.save()
        row.save()
        if graph is not None:
            versions.snapshot(flow, user=user)
    invalidate()
    return row


def delete(row) -> None:
    used = usage(row.key)
    if used["flows"] or used["tools"]:
        raise Conflict("This composite tool is still in use", code="composite_in_use", details=used)
    with transaction.atomic():
        flow = row.flow
        row.delete()
        flow.delete()
    invalidate()


def duplicate(row, user, payload: dict[str, Any]):
    """「另存為我的工具」：內建（唯讀）或別人的工具複製一份可改的。"""
    key = _clean_key(payload.get("key") or f"{row.key}_copy")
    label = str(payload.get("label") or f"{row.label} (copy)").strip()
    return create(user, {"key": key, "label": label, "description": row.description, "category": row.category, "icon": row.icon,
                         "graph": copy.deepcopy(row.flow.graph or {}), "interface": copy.deepcopy(row.interface or {})})


def out(row, *, graph: bool = False, with_usage: bool = False) -> dict[str, Any]:
    data = {
        "id": row.id, "key": row.key, "type": type_key(row.key), "label": row.label, "description": row.description,
        "category": row.category, "category_label": tools.CATEGORY_LABELS.get(row.category, row.category), "icon": row.icon,
        "builtin": row.builtin, "flow_id": row.flow_id, "interface": row.interface or {},
        "created_by": row.created_by.username if row.created_by_id else "",
        "created_at": row.created_at.isoformat() if row.created_at else "", "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        "version": int(row.flow.version) if row.flow_id else 1,
    }
    if graph:
        data["graph"] = row.flow.graph or {"nodes": [], "edges": []}
    if with_usage:
        used = usage(row.key)
        data["used_by_flows"] = len(used["flows"])
        data["used_by_tools"] = len(used["tools"])
        data["uses"] = referenced_keys(row.flow.graph or {})
    return data


# ---------------------------------------------------------------------------
# 匯出／匯入（.tool.json；.flow.json 內嵌依賴）
# ---------------------------------------------------------------------------
TOOL_SCHEMA_VERSION = 1
TOOL_DOC_KIND = "composite_tool"


def export_doc(row, *, _seen: set[str] | None = None) -> dict[str, Any]:
    from apps.vision import serialize

    seen = _seen if _seen is not None else set()
    seen.add(row.key)
    graph = row.flow.graph or {"nodes": [], "edges": []}
    doc: dict[str, Any] = {
        "schema_version": TOOL_SCHEMA_VERSION, "kind": TOOL_DOC_KIND, "exported_at": serialize._exported_at(),
        "key": row.key, "label": row.label, "description": row.description or "", "category": row.category, "icon": row.icon,
        "graph": serialize.normalize_graph(graph), "interface": row.interface or {},
    }
    pictures = serialize._fixed_images_payload(graph)
    if pictures:
        doc["fixed_images"] = pictures
    deps = dependency_docs(graph, _seen=seen)
    if deps:
        doc["dependencies"] = deps
    return doc


def dependency_docs(graph: dict[str, Any], *, _seen: set[str] | None = None) -> list[dict[str, Any]]:
    """圖裡用到的複合工具（含巢狀）各一份匯出文件，匯入端沒有就建起來。"""
    from apps.vision.models import CompositeTool

    seen = _seen if _seen is not None else set()
    docs: list[dict[str, Any]] = []
    for key in referenced_keys(graph):
        if key in seen:
            continue
        row = CompositeTool.objects.select_related("flow").filter(key=key).first()
        if row is None:
            continue
        docs.append(export_doc(row, _seen=seen))
    return docs


def parse_doc(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise ValidationError("A tool file must be an object", code="bad_tool_file")
    if doc.get("kind") != TOOL_DOC_KIND:
        raise ValidationError("Not a composite tool file (kind must be composite_tool)", code="bad_tool_file")
    if doc.get("schema_version") != TOOL_SCHEMA_VERSION:
        raise ValidationError(f"Unsupported schema_version {doc.get('schema_version')!r} (this build uses {TOOL_SCHEMA_VERSION})", code="bad_schema_version")
    if not isinstance(doc.get("graph"), dict):
        raise ValidationError("The tool file has no graph", code="bad_tool_file")
    return doc


def import_doc(user, doc: dict[str, Any], *, replace: bool = False) -> tuple[Any, str]:
    """匯入一份 .tool.json（先匯入依賴）。回 (row, "created"|"updated"|"kept")；同 key 已存在且不 replace 就保留現有的。"""
    from apps.vision import serialize
    from apps.vision.models import CompositeTool

    doc = parse_doc(doc)
    for dep in doc.get("dependencies") or []:
        import_doc(user, dep, replace=replace)
    serialize.restore_fixed_images(doc)
    payload = {"key": doc.get("key"), "label": doc.get("label"), "description": doc.get("description"), "category": doc.get("category"),
               "icon": doc.get("icon"), "graph": doc.get("graph"), "interface": doc.get("interface")}
    existing = CompositeTool.objects.select_related("flow").filter(key=str(doc.get("key") or "").strip().lower()).first()
    if existing is not None:
        if not replace:
            return existing, "kept"
        if existing.builtin:
            return existing, "kept"
        return update(existing, payload, user=user), "updated"
    return create(user, payload), "created"


def import_dependencies(user, doc: dict[str, Any], *, replace: bool = False) -> list[dict[str, Any]]:
    """`.flow.json` 內嵌的複合工具：缺的建起來、已有的保留（replace 才覆蓋）。回每個工具的結果。"""
    results: list[dict[str, Any]] = []
    for dep in doc.get("composite_tools") or []:
        try:
            row, action = import_doc(user, dep, replace=replace)
            results.append({"key": row.key, "action": action})
        except (ValidationError, Conflict) as exc:
            results.append({"key": str((dep or {}).get("key") or ""), "action": "failed", "error": str(exc)})
    return results


# ---------------------------------------------------------------------------
# 封裝：一組步驟 → 工具內部圖＋介面＋實例（與前端 lib/composite.ts 的 encapsulateSelection 同一套規則）
# ---------------------------------------------------------------------------
def encapsulate(graph: dict[str, Any], node_ids: list[str], key: str, label: str, *, expose_params: bool = False) -> dict[str, Any]:
    """把 `node_ids` 那組步驟封裝成工具。回 {tool_graph, interface, instance, graph}：

    - 對外輸入＝從外面接進來的資料埠＋沒接線也沒畫區域的必填輸入；控制線與隱含埠（`_` 開頭）照原樣接到實例上
    - 對外輸出＝接到外面的埠＋有具名輸出名稱的埠（名稱搬到實例上，工具內部不留）
    - `expose_params`：把內部步驟的教導參數與區域參數列成對外參數（助手產出的工具要能在工具頁調）
    - `graph`＝原圖把那組步驟換成一個實例、邊重接
    """
    key = _clean_key(key)
    chosen = {str(x) for x in node_ids}
    nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, dict)]
    edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
    inner = [n for n in nodes if str(n.get("id")) in chosen and n.get("type") != "note"]
    if not inner:
        raise ValidationError("Select at least one step to encapsulate", code="empty_selection")
    inner_ids = {str(n["id"]) for n in inner}
    by_id = {str(n.get("id")): n for n in nodes}

    def src(e: dict[str, Any]) -> str:
        return str(e.get("source"))

    def tgt(e: dict[str, Any]) -> str:
        return str(e.get("target"))

    def tool_of(node: dict[str, Any]):
        try:
            return tools.get(str(node.get("type") or ""))
        except tools.UnknownToolType:
            return None

    internal = [e for e in edges if src(e) in inner_ids and tgt(e) in inner_ids]
    incoming = [e for e in edges if tgt(e) in inner_ids and src(e) not in inner_ids]
    outgoing = [e for e in edges if src(e) in inner_ids and tgt(e) not in inner_ids]
    fed = {(tgt(e), str(e.get("target_handle") or "")) for e in internal}

    inputs: list[dict[str, Any]] = []
    seen_in: set[str] = set()

    def add_input(node_id: str, port: str) -> None:
        k = f"{node_id}{PORT_SEP}{port}"
        if k in seen_in:
            return
        seen_in.add(k)
        inputs.append({"key": k, "exposed": True, "order": len(inputs)})

    for e in incoming:
        handle = str(e.get("target_handle") or "")
        if handle == tools.FLOW_IN or handle.startswith("_"):
            continue
        add_input(tgt(e), handle)
    for n in inner:
        tool = tool_of(n)
        params = n.get("params") if isinstance(n.get("params"), dict) else {}
        for p in (tool.inputs if tool else ()):
            if not p.required or p.key.startswith("_") or (str(n["id"]), p.key) in fed:
                continue
            if p.type == "region" and isinstance(params.get(p.key), dict):
                continue
            add_input(str(n["id"]), p.key)

    outputs: list[dict[str, Any]] = []
    seen_out: set[str] = set()
    instance_aliases: list[dict[str, Any]] = []

    def add_output(node_id: str, port: str) -> None:
        k = f"{node_id}{PORT_SEP}{port}"
        if k in seen_out:
            return
        seen_out.add(k)
        outputs.append({"key": k, "exposed": True, "order": len(outputs)})

    def first_output(node_id: str) -> str:
        tool = tool_of(by_id.get(node_id) or {})
        return tool.outputs[0].key if tool and tool.outputs else ""

    for e in outgoing:
        handle = str(e.get("source_handle") or "") or first_output(src(e))
        if handle:
            add_output(src(e), handle)
    for n in inner:
        for port, alias in tools.output_aliases(n).items():
            add_output(str(n["id"]), port)
            instance_aliases.append({"key": f"{n['id']}{PORT_SEP}{port}", "alias": alias})

    params_spec: list[dict[str, Any]] = []
    if expose_params:
        used_alias: set[str] = set()
        for n in inner:
            tool = tool_of(n)
            node_params = n.get("params") if isinstance(n.get("params"), dict) else {}
            for p in (tool.params if tool else ()):
                if not (p.teach or p.kind == "roi"):
                    continue
                rule = p.visible_when if isinstance(p.visible_when, dict) else None
                if rule and isinstance(rule.get("param"), str) and isinstance(rule.get("in"), list) and node_params.get(rule["param"], next((d.default for d in tool.params if d.key == rule["param"]), None)) not in rule["in"]:
                    continue  # 目前設定下看不到的參數不對外（門檻方式是 fixed 就不會有自適應的區塊大小）
                alias = p.label
                if alias in used_alias:
                    alias = f"{n.get('label') or n['id']} {p.label}"
                used_alias.add(alias)
                entry: dict[str, Any] = {"key": f"{n['id']}{PORT_SEP}{p.key}", "alias": alias, "order": len(params_spec)}
                if p.teach:
                    entry["teach"] = True
                params_spec.append(entry)

    def pos(n: dict[str, Any]) -> tuple[float, float]:
        p = n.get("position") if isinstance(n.get("position"), dict) else {}
        return float(p.get("x") or 0), float(p.get("y") or 0)

    min_x = min(pos(n)[0] for n in inner)
    min_y = min(pos(n)[1] for n in inner)
    tool_nodes = []
    for n in inner:
        c = copy.deepcopy(n)
        c.pop("meta", None)
        c.pop("selected", None)
        x, y = pos(n)
        c["position"] = {"x": x - min_x + 40, "y": y - min_y + 40}
        _strip_aliases(c)
        tool_nodes.append(c)
    tool_graph = {"nodes": tool_nodes, "edges": [copy.deepcopy(e) for e in internal]}

    existing = {str(n.get("id")) for n in nodes}
    inst_id = key
    counter = 2
    while inst_id in existing:
        inst_id = f"{key}_{counter}"
        counter += 1
    instance: dict[str, Any] = {
        "id": inst_id, "type": type_key(key), "label": label, "params": {},
        "position": {"x": round(sum(pos(n)[0] for n in inner) / len(inner)), "y": round(sum(pos(n)[1] for n in inner) / len(inner))},
    }
    if instance_aliases:
        instance[tools.INTERFACE_KEY] = {"outputs": instance_aliases}

    rewired: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str, str]] = set()

    def push(e: dict[str, Any]) -> None:
        sig = (str(e.get("source")), str(e.get("source_handle") or ""), str(e.get("target")), str(e.get("target_handle") or ""))
        if sig in seen_edges:
            return
        seen_edges.add(sig)
        rewired.append(e)

    for e in edges:
        s_in, t_in = src(e) in inner_ids, tgt(e) in inner_ids
        if s_in and t_in:
            continue
        if not s_in and not t_in:
            push(copy.deepcopy(e))
            continue
        if t_in:
            handle = str(e.get("target_handle") or "")
            target_handle = handle if handle == tools.FLOW_IN or handle.startswith("_") else f"{tgt(e)}{PORT_SEP}{handle}"
            push({"id": f"{src(e)}-{inst_id}-{target_handle}", "source": src(e), "source_handle": e.get("source_handle"), "target": inst_id, "target_handle": target_handle})
            continue
        handle = str(e.get("source_handle") or "") or first_output(src(e))
        push({"id": f"{inst_id}-{handle}-{tgt(e)}-{e.get('target_handle') or ''}", "source": inst_id, "source_handle": f"{src(e)}{PORT_SEP}{handle}", "target": tgt(e), "target_handle": e.get("target_handle")})

    interface: dict[str, Any] = {"inputs": inputs, "outputs": outputs}
    if params_spec:
        interface["params"] = params_spec
    rest = [copy.deepcopy(n) for n in nodes if str(n.get("id")) not in inner_ids]
    return {"tool_graph": tool_graph, "interface": interface, "instance": instance, "graph": {**graph, "nodes": [*rest, instance], "edges": rewired}}
