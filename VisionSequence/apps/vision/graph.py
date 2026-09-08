"""圖驗證與編譯：存檔時驗，啟動時再驗一次；編譯結果依 flow version 快取。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from apps.core.errors import ValidationError
from apps.vision.tools import base as tools

DECORATION_TYPES = ("note",)
#: 改名過的工具 key：舊圖與舊匯出檔在驗證／編譯時自動換成新 key（DB 另有資料轉移）。
#: 併掉／改名的工具：舊 graph 載入（validate/compile）時自動換 type；參數名刻意相容，值照舊可用。
LEGACY_TOOL_TYPES = {
    "write_plc": "write_modbus", "edges": "filter", "hist_eq": "lut",
    # 深度學習工具改名（產品表面不再出現技術名稱；migration 0024 也把既有流程的 type 改掉）
    "yolo_detect": "ai_detect", "yolo_segment": "ai_segment", "yolo_classify": "ai_classify", "yolo_pose": "ai_pose", "yolo_obb": "ai_obb",
}
#: 隱含埠的名字與規格都在 tools/base.py 的 IMPLICIT_INPUTS／IMPLICIT_OUTPUTS，這裡只是取個短名字用。
FLOW_IN = tools.FLOW_IN
OVERLAYS_OUT = tools.OVERLAYS_OUT
IMAGE_THRU = tools.IMAGE_THRU


class GraphError(ValidationError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, code="invalid_graph", details=details)


def _limits() -> tuple[int, int]:
    cfg = getattr(settings, "VISION", {})
    return int(cfg.get("MAX_NODES", 300)), int(cfg.get("MAX_EDGES", 600))


def _compatible(source_type: str, target_type: str) -> bool:
    if source_type == "flow" or target_type == "flow":
        return source_type == target_type
    if "any" in (source_type, target_type):
        return True
    if source_type == target_type:
        return True
    # number 可餵給 string / list 型的顯示工具；bool 可當 number。
    return (source_type, target_type) in {
        ("number", "string"),
        ("bool", "number"),
        ("bool", "string"),
        ("string", "any"),
        ("points", "list"),
        ("matches", "list"),
        ("contours", "list"),
    }


def validate_graph(graph: Any) -> dict:
    if not isinstance(graph, dict):
        raise GraphError("The graph must be an object with nodes and edges")
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges") or []
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise GraphError("Both nodes and edges must be lists")
    max_nodes, max_edges = _limits()
    if len(raw_nodes) > max_nodes:
        raise GraphError(f"The node limit is {max_nodes}", node_count=len(raw_nodes))
    if len(raw_edges) > max_edges:
        raise GraphError(f"The edge limit is {max_edges}", edge_count=len(raw_edges))

    seen: dict[str, dict] = {}
    for node in raw_nodes:
        if not isinstance(node, dict):
            raise GraphError("Every node must be an object")
        node_id = str(node.get("id") or "")
        if not node_id:
            raise GraphError("A node has no id")
        if node_id in seen:
            raise GraphError(f"Node id '{node_id}' is duplicated", node_id=node_id)
        node_type = str(node.get("type") or "")
        if node_type in LEGACY_TOOL_TYPES:
            node_type = node["type"] = LEGACY_TOOL_TYPES[node_type]
        if node_type not in DECORATION_TYPES:
            tools.get(node_type)  # 查無 → UnknownToolType（附可用 key）
        seen[node_id] = node

    def port_type(node_id: str, key: str, direction: str) -> str:
        node = seen[node_id]
        if node["type"] in DECORATION_TYPES:
            raise GraphError("A note cannot take part in the dataflow", node_id=node_id)
        tool = tools.get(str(node["type"]))
        implicit = tools.implicit_input(key) if direction == "in" else tools.implicit_output(key)
        if implicit is not None:
            return implicit.type
        if direction == "in":
            # 參數訂閱：`param:<key>` 讓這個參數改吃上游送來的值（型別依 Param.kind）
            bound = tools.param_port(tool, key)
            if bound is not None:
                return bound.type
            if key.startswith(tools.PARAM_PREFIX):
                raise GraphError(
                    f"Node '{node_id}' ({tool.label}) has no parameter '{key[len(tools.PARAM_PREFIX):]}' that can be driven by a value",
                    node_id=node_id, port=key,
                )
        ports = tool.inputs if direction == "in" else tool.outputs
        for port in ports:
            if port.key == key:
                return port.type
        raise GraphError(
            f"Node '{node_id}' ({tool.label}) has no {'input' if direction == 'in' else 'output'} port '{key}'",
            node_id=node_id,
            port=key,
        )

    connected_inputs: dict[tuple[str, str], int] = {}
    for edge in raw_edges:
        if not isinstance(edge, dict):
            raise GraphError("Every edge must be an object")
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in seen:
            raise GraphError(f"The edge's source node '{source}' does not exist", node_id=source)
        if target not in seen:
            raise GraphError(f"The edge's target node '{target}' does not exist", node_id=target)
        if source == target:
            raise GraphError("A node cannot connect to itself", node_id=source)
        if seen[target]["type"] in DECORATION_TYPES:
            raise GraphError("Nothing can connect into a note", node_id=target)
        if seen[source]["type"] in DECORATION_TYPES:
            # 註解指出去的虛線是註解，不是資料流；引擎不理它。
            continue
        s_handle = str(edge.get("source_handle") or "")
        t_handle = str(edge.get("target_handle") or "")
        s_tool = tools.get(str(seen[source]["type"]))
        t_tool = tools.get(str(seen[target]["type"]))
        if not s_handle:
            s_handle = s_tool.outputs[0].key if s_tool.outputs else ""
        if not t_handle:
            t_handle = t_tool.inputs[0].key if t_tool.inputs else FLOW_IN
        st = port_type(source, s_handle, "out")
        tt = port_type(target, t_handle, "in")
        if not _compatible(st, tt):
            raise GraphError(
                f"'{source}.{s_handle}'（{st}) cannot connect to '{target}.{t_handle}'（{tt}）",
                node_id=target,
                port=t_handle,
            )
        if tt != "flow":
            # 隱含輸入埠不在工具的宣告清單裡（next() 會 StopIteration），能不能接多條看那張表
            implicit_in = tools.implicit_input(t_handle)
            declared = next((p for p in t_tool.inputs if p.key == t_handle), None)
            # 隱含埠與參數埠都不在工具的宣告清單裡；參數埠一定只能接一條（一個參數一個值）
            multiple = implicit_in.multiple if implicit_in else bool(declared and declared.multiple)
            count = connected_inputs.get((target, t_handle), 0) + 1
            connected_inputs[(target, t_handle)] = count
            if count > 1 and not multiple:
                raise GraphError(
                    f"Node '{target}' input port '{t_handle}' accepts only one connection",
                    node_id=target,
                    port=t_handle,
                )
        edge["source_handle"] = s_handle
        edge["target_handle"] = t_handle

    # 必須是 DAG：拓樸排序一次做完（也順便給引擎用）。
    order = topological_order(raw_nodes, raw_edges)
    executable = [n for n in raw_nodes if n["type"] not in DECORATION_TYPES]
    if len(order) != len(executable):
        raise GraphError("The graph contains a cycle; an inspection flow must be acyclic")
    return {"nodes": raw_nodes, "edges": raw_edges}


def topological_order(nodes: list[dict], edges: list[dict]) -> list[str]:
    ids = [str(n["id"]) for n in nodes if n.get("type") not in DECORATION_TYPES]
    id_set = set(ids)
    indeg = {i: 0 for i in ids}
    out: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        s, t = str(e.get("source")), str(e.get("target"))
        if s in id_set and t in id_set:
            out[s].append(t)
            indeg[t] += 1
    # 以節點宣告順序當 tie-break，讓執行順序穩定可預期。
    ready = [i for i in ids if indeg[i] == 0]
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for nxt in out[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
    return order


@dataclass
class CompiledNode:
    id: str
    type: str
    node: dict
    tool: Any
    #: 輸入埠 key → [(source_id, source_port)]
    inputs: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    #: 控制輸入：[(source_id, branch_key)]
    flow_inputs: list[tuple[str, str]] = field(default_factory=list)
    #: 第一個 image 型輸入埠（overlays 預設座標系）。
    primary_image_port: str | None = None


@dataclass
class CompiledGraph:
    order: list[str]
    nodes: dict[str, CompiledNode]
    #: 有邊連出的 (node_id, port) 集合：沒人用的輸出影像不必進快取（省記憶體與時間）。
    consumed: set[tuple[str, str]]


def restrict_to(compiled: CompiledGraph, node_id: str) -> CompiledGraph:
    """只保留 node_id 與其祖先（資料邊與控制邊）：工具專屬頁調參數時不必跑整張圖。"""
    if node_id not in compiled.nodes:
        raise GraphError(f"Node '{node_id}' does not exist", node_id=node_id)
    keep: set[str] = set()
    stack = [node_id]
    while stack:
        nid = stack.pop()
        if nid in keep:
            continue
        keep.add(nid)
        cn = compiled.nodes[nid]
        for sources in cn.inputs.values():
            stack.extend(src for src, _ in sources)
        stack.extend(src for src, _ in cn.flow_inputs)
    return CompiledGraph(
        order=[n for n in compiled.order if n in keep],
        nodes={n: compiled.nodes[n] for n in keep},
        consumed=compiled.consumed,
    )


def compile_graph(graph: dict) -> CompiledGraph:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    compiled: dict[str, CompiledNode] = {}
    for n in nodes:
        if n.get("type") in DECORATION_TYPES:
            continue
        ntype = LEGACY_TOOL_TYPES.get(str(n["type"]), str(n["type"]))
        tool = tools.get(ntype)
        cn = CompiledNode(id=str(n["id"]), type=ntype, node=n, tool=tool)
        for p in tool.inputs:
            if p.type == "image":
                cn.primary_image_port = p.key
                break
        compiled[cn.id] = cn
    consumed: set[tuple[str, str]] = set()
    for e in edges:
        s, t = str(e.get("source")), str(e.get("target"))
        if s not in compiled or t not in compiled:
            continue
        sh = str(e.get("source_handle") or (compiled[s].tool.outputs[0].key if compiled[s].tool.outputs else ""))
        th = str(e.get("target_handle") or (compiled[t].tool.inputs[0].key if compiled[t].tool.inputs else FLOW_IN))
        s_port = next((p for p in compiled[s].tool.outputs if p.key == sh), None)
        if (s_port and s_port.type == "flow") or th == FLOW_IN:
            compiled[t].flow_inputs.append((s, sh))
        else:
            compiled[t].inputs.setdefault(th, []).append((s, sh))
            consumed.add((s, sh))
    return CompiledGraph(order=topological_order(nodes, edges), nodes=compiled, consumed=consumed)
