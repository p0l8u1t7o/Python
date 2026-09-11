"""把流程存成複合工具＋一條「取像 → 工具實例」的新流程。

助手頁結果卡的「封裝成複合工具」（`POST /agent/save-tool`）與代理動作 `save_as_tool` 走同一條路，
規則只有一份：取像與註解以外的步驟封裝進工具，教導參數與區域成為工具的對外參數。
"""

from __future__ import annotations

from typing import Any


def encapsulable_steps(graph: dict[str, Any]) -> list[str]:
    """會被封裝進工具的步驟（取像與註解以外）。"""
    from apps.vision.agent import actions

    return [str(n.get("id")) for n in (graph or {}).get("nodes", []) if not actions.is_acquisition(n) and n.get("type") != "note"]


def save_as_tool(user, graph: dict[str, Any], key: str, label: str, *, description: str = "", category: str = "detect",
                 flow_name: str = "") -> dict[str, Any]:
    """建工具與流程（同一個交易）；回 `{"row", "flow", "instance"}`。稽核與對話綁定由呼叫端做。"""
    from django.db import IntegrityError, transaction

    from apps.core.errors import Conflict, ValidationError
    from apps.vision import composites, versions
    from apps.vision.graph import validate_graph
    from apps.vision.models import Flow

    graph = validate_graph(graph)
    inner = encapsulable_steps(graph)
    if not inner:
        raise ValidationError("The flow has no inspection steps to encapsulate", code="empty_selection")
    label = (label or "").strip() or key
    enc = composites.encapsulate(graph, inner, key, label, expose_params=True, version=1)
    name = (flow_name or "").strip() or label
    with transaction.atomic():
        row = composites.create(user, {"key": key, "label": label, "description": description,
                                       "category": category or "detect", "icon": "Sparkles", "graph": enc["tool_graph"], "interface": enc["interface"]})
        try:
            with transaction.atomic():
                flow = Flow.objects.create(name=name, description=description, owner=user, graph=validate_graph(enc["graph"]))
        except IntegrityError:
            raise Conflict("A flow with that name already exists", code="flow_name_taken") from None
    versions.snapshot(flow, user=user, note="created")
    return {"row": row, "flow": flow, "instance": enc["instance"]["id"]}
