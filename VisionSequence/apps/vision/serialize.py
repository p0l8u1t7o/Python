"""流程的穩定序列化（匯出／匯入），給 CLI `manage.py flow` 與 API 共用。

匯出格式（schema_version 1）：
- key 固定順序：schema_version, exported_at, name, description, continuous_interval_ms, graph
- graph.nodes 依 id 排序、graph.edges 依 (source, target, source_handle, target_handle) 排序
- 節點 key 固定順序（id, type, label, description, enabled, continue_on_error, color, params, position, width, height，
  其餘依字母序）；params 依 key 排序；position 四捨五入為整數
- image_source.source_id 換成 {SOURCE} 佔位符（複用範本庫的 templatize）
- 2 空格縮排、ensure_ascii=False、UTF-8 無 BOM、LF、檔尾一個換行

設定環境變數 SOURCE_DATE_EPOCH（reproducible-builds 慣例）可固定 exported_at，讓兩次匯出 byte-identical。
DB 仍是執行期權威來源；匯入依 name upsert。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from django.db import IntegrityError, transaction

from apps.core.errors import Conflict, ValidationError
from apps.vision.api_more import instantiate, templatize
from apps.vision.graph import validate_graph
from apps.vision.models import Flow

SCHEMA_VERSION = 1
DOC_KEYS = ("schema_version", "exported_at", "name", "description", "continuous_interval_ms", "graph")
NODE_KEYS = ("id", "type", "label", "description", "enabled", "continue_on_error", "color", "params", "position", "width", "height")
EDGE_KEYS = ("id", "source", "source_handle", "target", "target_handle")


def _ordered(obj: dict[str, Any], first: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in first:
        if k in obj:
            out[k] = obj[k]
    for k in sorted(k for k in obj if k not in first):
        out[k] = obj[k]
    return out


def _sorted_json(value: Any) -> Any:
    """巢狀 dict 依 key 排序（params 內容可能有 ROI 物件等）。"""
    if isinstance(value, dict):
        return {k: _sorted_json(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_sorted_json(v) for v in value]
    return value


def _round_position(pos: Any) -> Any:
    if not isinstance(pos, dict):
        return pos
    out = {}
    for k in ("x", "y"):
        v = pos.get(k, 0)
        try:
            out[k] = int(round(float(v)))
        except (TypeError, ValueError):
            out[k] = 0
    return out


def normalize_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """排序、固定 key 順序、位置取整；不換佔位符。回傳新物件。"""
    graph = validate_graph(json.loads(json.dumps(graph or {"nodes": [], "edges": []})))
    nodes = []
    for n in sorted(graph.get("nodes", []), key=lambda n: str(n.get("id"))):
        n = dict(n)
        if "params" in n:
            n["params"] = _sorted_json(n.get("params") or {})
        if "position" in n:
            n["position"] = _round_position(n["position"])
        for k in ("width", "height"):
            if k in n and isinstance(n[k], (int, float)):
                n[k] = int(round(n[k]))
        nodes.append(_ordered(n, NODE_KEYS))
    edges = []
    for e in sorted(graph.get("edges", []), key=lambda e: (str(e.get("source")), str(e.get("target")), str(e.get("source_handle") or ""), str(e.get("target_handle") or ""))):
        edges.append(_ordered(dict(e), EDGE_KEYS))
    return {"nodes": nodes, "edges": edges}


def _exported_at() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    else:
        dt = datetime.now(tz=timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def export_flow(flow: Flow) -> dict[str, Any]:
    doc = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": _exported_at(),
        "name": flow.name,
        "description": flow.description or "",
        "continuous_interval_ms": int(flow.continuous_interval_ms or 0),
        "graph": normalize_graph(templatize(flow.graph or {"nodes": [], "edges": []})),
    }
    return {k: doc[k] for k in DOC_KEYS}


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def to_bytes(doc: dict[str, Any]) -> bytes:
    return dumps(doc).replace("\r\n", "\n").encode("utf-8")


def write_file(doc: dict[str, Any], path: str) -> None:
    with open(path, "wb") as f:
        f.write(to_bytes(doc))


def parse(text: str | bytes) -> dict[str, Any]:
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Not valid JSON: {exc}", code="bad_json") from None
    if not isinstance(doc, dict):
        raise ValidationError("A flow file must be an object", code="bad_flow_file")
    version = doc.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValidationError(f"Unsupported schema_version {version!r} (this build uses {SCHEMA_VERSION})", code="bad_schema_version")
    name = str(doc.get("name") or "").strip()
    if not name:
        raise ValidationError("The flow file has no name", code="bad_flow_file")
    if not isinstance(doc.get("graph"), dict):
        raise ValidationError("The flow file has no graph", code="bad_flow_file")
    return doc


def materialize_graph(doc: dict[str, Any], *, source_id: int | None) -> dict[str, Any]:
    """把 {SOURCE} 換成來源 id（未給則留空字串）並驗證。"""
    return validate_graph(instantiate(doc["graph"], source_id=source_id))


def _carry_over_sources(graph: dict[str, Any], existing: dict[str, Any]) -> None:
    """更新既有流程且沒指定 source_id：取像步驟沿用原流程的來源（同 id 優先，否則任一取像步驟的來源），
    不要把現場已設好的來源清成空白。"""
    old_by_id = {n.get("id"): n for n in existing.get("nodes", []) if n.get("type") == "image_source"}
    fallback = next((n.get("params", {}).get("source_id") for n in old_by_id.values() if n.get("params", {}).get("source_id") not in ("", None)), None)
    for node in graph.get("nodes", []):
        if node.get("type") != "image_source":
            continue
        params = node.setdefault("params", {})
        if params.get("source_id") not in ("", None):
            continue
        old = old_by_id.get(node.get("id"))
        old_sid = old.get("params", {}).get("source_id") if old else None
        params["source_id"] = old_sid if old_sid not in ("", None) else (fallback if fallback is not None else "")


def import_flow(doc: dict[str, Any], *, source_id: int | None = None, owner=None) -> tuple[Flow, bool]:
    """依 name upsert：存在則更新 graph／description／間隔並 version+1；不存在則建立。
    更新既有流程且未指定 source_id 時，取像步驟沿用原流程的來源。"""
    graph = materialize_graph(doc, source_id=source_id)
    name = str(doc["name"]).strip()
    description = str(doc.get("description") or "")
    interval = max(0, int(doc.get("continuous_interval_ms") or 0))
    try:
        with transaction.atomic():
            flow = Flow.objects.filter(name=name).first()
            if flow is None:
                flow = Flow.objects.create(name=name, description=description, graph=graph, owner=owner, continuous_interval_ms=interval)
                return flow, True
            if source_id is None:
                _carry_over_sources(graph, flow.graph or {})
            flow.graph = graph
            flow.description = description
            flow.continuous_interval_ms = interval
            flow.version += 1
            flow.save()
            return flow, False
    except IntegrityError:
        raise Conflict("A flow with that name already exists", code="flow_name_taken") from None


def find_flow(ref: str) -> Flow | None:
    """`<id|name>`：純數字先當 id。"""
    ref = str(ref).strip()
    if ref.isdigit():
        flow = Flow.objects.filter(pk=int(ref)).first()
        if flow is not None:
            return flow
    return Flow.objects.filter(name=ref).first()


__all__ = ["SCHEMA_VERSION", "export_flow", "normalize_graph", "dumps", "to_bytes", "write_file", "parse", "materialize_graph", "import_flow", "find_flow"]
