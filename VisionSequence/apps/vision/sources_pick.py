"""來源選擇器的純函式；依型別、語意與可達性判斷，不依節點排列。"""

from apps.vision.graph import _compatible
from apps.vision.tools import base as tools


def candidates(graph: dict, target: str, handle: str) -> list[dict]:
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    node = nodes.get(target)
    if not node or not tools.has(node["type"]):
        return []
    definition = tools.get(node["type"])
    port = next((p for p in definition.inputs if p.key == handle), None) or tools.param_port(definition, handle)
    if port is None:
        return []
    edges = graph.get("edges", [])
    downstream, pending = set(), [target]
    while pending:
        current = pending.pop()
        if current in downstream:
            continue
        downstream.add(current)
        pending.extend(e["target"] for e in edges if e["source"] == current)
    connected = {(e["source"], e.get("source_handle", "")) for e in edges if e["target"] == target and e.get("target_handle", "") == handle}
    result = []
    for source in nodes.values():
        if source["id"] in downstream or source["type"] == "note" or not tools.has(source["type"]):
            continue
        if port.multiple and (source["id"], "") in connected:
            continue
        for output in tools.get(source["type"]).outputs:
            if output.key in ("_image", "_overlays") or output.type == "flow":
                continue
            if port.multiple and (source["id"], output.key) in connected:
                continue
            if output.semantic and port.accepts_semantics and output.semantic not in port.accepts_semantics:
                continue
            if _compatible(output.type, port.type):
                result.append({"source": source["id"], "source_handle": output.key, "target": target, "target_handle": handle})
    target_task = node.get("meta", {}).get("inspect", {}).get("task_id")
    order = {key: i for i, key in enumerate(nodes)}

    def rank(edge):
        # 同任務優先，其次是定位任務；同階維持畫布節點順序。
        info = nodes[edge["source"]].get("meta", {}).get("inspect", {})
        priority = 0 if target_task and info.get("task_id") == target_task else 1 if info.get("kind") == "locate_part" else 2
        return priority, order[edge["source"]], edge["source_handle"]

    return sorted(result, key=rank)
