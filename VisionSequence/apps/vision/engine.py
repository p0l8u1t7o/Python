"""資料流引擎：一次 run 在呼叫者的執行緒內，以拓樸順序把整張圖跑完。

規則：
- 節點依 compile_graph 的拓樸順序執行；輸入從上游的輸出表取。
- 帶 flow 輸入的節點：至少一條連入分支被選中才執行，否則 skipped。
- 必填輸入的上游被 skipped／error → 本節點 skipped（error 會讓整個 run failed，
  除非該節點設定 continue_on_error）。
- enabled=false 的節點：skipped，但若它是「單輸入單輸出同型別」會把輸入直通
  （關掉一個濾鏡不該讓下游全部斷線）。
- 工具拋 ToolError → 該節點 error（可預期的失敗）；其他例外 → error 並附 repr。
- 影像輸出只有「有人連線用到」或「編輯器試跑」時才登記進快取。
- run 狀態：所有節點 ok → ok；任一 judge/工具回 ng → ng；任一 error → failed。
"""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from apps.vision.graph import DECORATION_TYPES, CompiledGraph, CompiledNode
from apps.vision.images import store
from apps.vision.tools import base as tools_base
from apps.vision.tools.base import Result, ToolContext, ToolError

log = logging.getLogger(__name__)


@dataclass
class NodeReport:
    status: str = "ok"  # ok | ng | error | skipped
    duration_ms: float = 0.0
    message: str = ""
    branch: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    overlays: list[dict[str, Any]] = field(default_factory=list)
    overlay_on: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    logs: list[dict[str, Any]] = field(default_factory=list)


#: 節點報告對外的完整形狀。落地的 FlowRun 只留 status／duration_ms／message，SSE 對不要輸出的訂閱者也會瘦身；
#: 讀回或瘦身時都要用這份補齊，否則前端拿到少一半鍵的 NodeReport（`outputs[...]`／`Object.entries(outputs)` 會炸）。
NODE_REPORT_DEFAULTS: dict[str, Any] = {
    "status": "ok", "duration_ms": 0.0, "message": "", "branch": None,
    "outputs": {}, "overlays": [], "overlay_on": None, "detail": {}, "logs": [],
}


@dataclass
class RunReport:
    id: str
    flow_id: int
    flow_version: int
    trigger: str
    status: str = "ok"
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_ms: float = 0.0
    error: str = ""
    nodes: dict[str, NodeReport] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    station_id: str = ""
    recipe: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, *, include_node_outputs: bool = True) -> dict[str, Any]:
        return {
            "id": self.id,
            "station_id": self.station_id,
            "recipe": self.recipe,
            "warnings": list(self.warnings),
            "flow_id": self.flow_id,
            "flow_version": self.flow_version,
            "trigger": self.trigger,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 3),
            "error": self.error,
            "outputs": self.outputs,
            "nodes": {
                nid: {
                    "status": r.status,
                    "duration_ms": round(r.duration_ms, 3),
                    "message": r.message,
                    "branch": r.branch,
                    "outputs": r.outputs if include_node_outputs else {},
                    "overlays": r.overlays if include_node_outputs else [],
                    "overlay_on": r.overlay_on,
                    "detail": r.detail if include_node_outputs else {},
                    "logs": r.logs,
                }
                for nid, r in self.nodes.items()
            },
        }


_PLAIN_TYPES = (float, int, str, bool, type(None))


def _jsonable(value: Any) -> Any:
    """輸出埠的值轉成可回傳前端的 JSON；影像已在上游換成 ref dict。"""
    if type(value) in _PLAIN_TYPES:
        return value
    if isinstance(value, np.ndarray):
        if value.ndim == 3 and value.shape[1] == 1 and value.shape[2] == 2:
            # 輪廓 (N,1,2)
            return value.reshape(-1, 2).tolist()
        if value.size > 10000:
            return {"array": True, "shape": list(value.shape), "dtype": str(value.dtype)}
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > 2000:
            return [_jsonable(v) for v in value[:2000]] + [f"... ({len(value)} items)"]
        # 純量清單（直方圖、剖面、點座標）直接回傳，不逐項遞迴。
        if all(type(v) in _PLAIN_TYPES for v in value):
            return value if isinstance(value, list) else list(value)
        return [_jsonable(v) for v in value]
    return value


def _passthrough(cn: CompiledNode, inputs: dict[str, Any]) -> dict[str, Any] | None:
    """停用的節點若能直通就直通：第一個 image 輸入 → 同型別的第一個 image 輸出。"""
    in_ports = [p for p in cn.tool.inputs if p.type == "image"]
    out_ports = [p for p in cn.tool.outputs if p.type == "image"]
    out: dict[str, Any] = {}
    if in_ports and out_ports and isinstance(inputs.get(in_ports[0].key), np.ndarray):
        out[out_ports[0].key] = inputs[in_ports[0].key]
    thru = inputs.get("_image")
    if not isinstance(thru, np.ndarray) and in_ports:
        thru = inputs.get(in_ports[0].key)
    if isinstance(thru, np.ndarray):
        out["_image"] = thru  # 隱含直通輸出：停用時也照樣往下傳
    return out or None


def execute(
    compiled: CompiledGraph,
    *,
    flow_id: int,
    flow_version: int,
    trigger: str,
    grab: Callable[[str], np.ndarray | None],
    asset_path: Callable[[str], str | None],
    preview: bool = False,
    initial_context: dict[str, Any] | None = None,
    input_image: np.ndarray | None = None,
    run_id: str | None = None,
    deadline: float | None = None,
    on_node: Callable[[str, NodeReport], None] | None = None,
) -> RunReport:
    run_id = run_id or uuid.uuid4().hex
    report = RunReport(id=run_id, flow_id=flow_id, flow_version=flow_version, trigger=trigger)
    report.started_at = time.time()
    t0 = time.perf_counter()
    context: dict[str, Any] = dict(initial_context or {})
    if input_image is not None:
        context["_input_image"] = input_image

    outputs: dict[tuple[str, str], Any] = {}
    status_of: dict[str, str] = {}
    branch_of: dict[str, str | None] = {}
    any_ng = False
    any_error = False

    for node_id in compiled.order:
        cn = compiled.nodes[node_id]
        node_report = NodeReport()
        nt0 = time.perf_counter()

        if deadline is not None and time.perf_counter() > deadline:
            node_report.status = "error"
            node_report.message = "the run timed out"
            report.nodes[node_id] = node_report
            status_of[node_id] = "error"
            any_error = True
            report.error = "the run timed out"
            break

        # -- 控制分支 ---------------------------------------------------
        if cn.flow_inputs:
            taken = any(
                status_of.get(src) in ("ok", "ng") and branch_of.get(src) == branch
                for src, branch in cn.flow_inputs
            )
            if not taken:
                node_report.status = "skipped"
                node_report.message = "branch not selected"
                report.nodes[node_id] = node_report
                status_of[node_id] = "skipped"
                continue

        # -- 收集輸入 ---------------------------------------------------
        inputs: dict[str, Any] = {}
        blocked = None
        for port in cn.tool.inputs:
            sources = cn.inputs.get(port.key, [])
            values = []
            for src, sport in sources:
                st = status_of.get(src)
                if st in ("ok", "ng"):
                    values.append(outputs.get((src, sport)))
                elif port.required:
                    blocked = f"upstream '{src}' {st or "not executed"}"
            if port.multiple:
                inputs[port.key] = values
            else:
                inputs[port.key] = values[0] if values else None
            if port.required and not sources and port.type != "flow":
                # 未連線的必填輸入：來源工具可以自己抓（例如 image_source），其他標錯。
                if not getattr(cn.tool, "allows_unconnected", False):
                    blocked = blocked or f"input port '{port.key}' is not connected"
        # 隱含輸入埠（collect=True 的那些，目前只有影像直通 _image）：不進工具邏輯，引擎自己用
        for spec in tools_base.IMPLICIT_INPUTS:
            if not spec.collect:
                continue
            for src, sport in cn.inputs.get(spec.key, []):
                if status_of.get(src) not in ("ok", "ng"):
                    continue
                value = outputs.get((src, sport))
                if value is None or (spec.type == "image" and not isinstance(value, np.ndarray)):
                    continue
                inputs[spec.key] = value
                break
        if blocked:
            node_report.status = "skipped"
            node_report.message = blocked
            report.nodes[node_id] = node_report
            status_of[node_id] = "skipped"
            continue

        # -- 停用 -------------------------------------------------------
        if cn.node.get("enabled") is False:
            passthrough = _passthrough(cn, inputs)
            if passthrough:
                for k, v in passthrough.items():
                    outputs[(node_id, k)] = v
                node_report.status = "ok"
                node_report.message = "disabled (pass-through)"
                status_of[node_id] = "ok"
            else:
                node_report.status = "skipped"
                node_report.message = "disabled"
                status_of[node_id] = "skipped"
            report.nodes[node_id] = node_report
            continue

        # -- 執行 -------------------------------------------------------
        logs: list[dict[str, Any]] = []

        def _log(message: str, *, level: str = "info", **detail: Any) -> None:
            if len(logs) < 50:
                logs.append({"level": level, "message": str(message)[:500], **({"detail": detail} if detail else {})})

        ctx = ToolContext(
            run_id=run_id,
            flow_id=flow_id,
            node=cn.node,
            inputs=inputs,
            context=context,
            depth=getattr(cn.tool, "accepts", ("u8",)),
            moment=time.time(),
            log=_log,
            asset_path=asset_path,
            grab=grab,
            preview=preview,
        )
        try:
            result = cn.tool.execute(ctx)
            if not isinstance(result, Result):
                raise ToolError(f"Tool '{cn.type}' returned no Result")
        except ToolError as exc:
            result = Result(status="error", message=str(exc)[:500])
        except Exception as exc:  # noqa: BLE001
            log.exception("工具 %s (%s) 例外", cn.type, node_id)
            result = Result(status="error", message=f"{type(exc).__name__}: {exc}"[:500], detail={"trace": traceback.format_exc()[-2000:]} if preview else {})

        node_report.duration_ms = (time.perf_counter() - nt0) * 1000
        node_report.status = result.status if result.status in ("ok", "ng", "error") else "ok"
        node_report.message = result.message
        node_report.branch = result.branch
        node_report.logs = logs
        node_report.detail = _jsonable(result.detail)
        node_report.overlays = result.overlays
        node_report.overlay_on = result.overlay_on or cn.primary_image_port
        if result.context:
            context.update(result.context)

        # 輸出登記（含隱含的標記輸出埠）
        outputs[(node_id, tools_base.OVERLAYS_OUT)] = result.overlays
        for k, v in result.outputs.items():
            outputs[(node_id, k)] = v
            if isinstance(v, np.ndarray) and any(p.key == k and p.type == "image" for p in cn.tool.outputs):
                if preview or (node_id, k) in compiled.consumed or cn.tool.category in ("source", "output"):
                    node_report.outputs[k] = store.put(f"{run_id}:{node_id}:{k}", v, flow_id=flow_id, run_id=run_id)
                else:
                    h, w = v.shape[:2]
                    node_report.outputs[k] = {"ref": None, "width": int(w), "height": int(h)}
            elif k == "_input_image":
                continue
            else:
                node_report.outputs[k] = _jsonable(v)
        # 影像直通（_image，宣告輸出之後才登記——分析／檢視優先看真正的輸出埠）：
        # 原影像原樣往下傳；overlays 只是 metadata、工具不就地改影像，下游檢測不受標記影響。
        thru = inputs.get(tools_base.IMAGE_THRU)
        if not isinstance(thru, np.ndarray) and cn.primary_image_port:
            v = inputs.get(cn.primary_image_port)
            thru = v if isinstance(v, np.ndarray) else None
        if isinstance(thru, np.ndarray):
            outputs[(node_id, tools_base.IMAGE_THRU)] = thru
            # 只在被接走時放進 report：直通埠不是「執行後」結果，viewer／分析都不該看到它
            if (node_id, tools_base.IMAGE_THRU) in compiled.consumed:
                node_report.outputs[tools_base.IMAGE_THRU] = store.put(f"{run_id}:{node_id}:{tools_base.IMAGE_THRU}", thru, flow_id=flow_id, run_id=run_id)
        # 讓前端也能看到 primary 輸入影像（overlay 座標系）——只在試跑時，避免重複快取。
        if preview and cn.primary_image_port and isinstance(inputs.get(cn.primary_image_port), np.ndarray):
            src = next((s for s in cn.inputs.get(cn.primary_image_port, [])), None)
            if src:
                node_report.detail = {**node_report.detail, "_input_ref": f"{run_id}:{src[0]}:{src[1]}"}

        report.nodes[node_id] = node_report
        status_of[node_id] = node_report.status
        branch_of[node_id] = result.branch

        if node_report.status == "ng":
            any_ng = True
        elif node_report.status == "error":
            any_error = True
            if not cn.node.get("continue_on_error"):
                report.error = report.error or f"{cn.node.get('label') or cn.type}: {result.message}"
        if on_node:
            on_node(node_id, node_report)

    # 未執行到的節點（逾時中斷）標 skipped。
    for node_id in compiled.order:
        if node_id not in report.nodes:
            report.nodes[node_id] = NodeReport(status="skipped", message="Not run")

    report.context = {k: _jsonable(v) for k, v in context.items() if not k.startswith("_")}
    report.outputs = _jsonable(context.get("_outputs", {}))
    if any_error and report.error:
        report.status = "failed"
    elif any_ng or context.get("_judge") == "ng":
        report.status = "ng"
    elif context.get("_judge") == "failed":
        report.status = "failed"
    else:
        report.status = "ok"
    report.finished_at = time.time()
    report.duration_ms = (time.perf_counter() - t0) * 1000
    return report


__all__ = ["execute", "RunReport", "NodeReport", "DECORATION_TYPES"]
