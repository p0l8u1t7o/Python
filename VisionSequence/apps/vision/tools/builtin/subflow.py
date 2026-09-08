"""子流程、逐項迴圈與切片工具。"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

from apps.vision import engine
from apps.vision.models import Flow
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.measure import offset_matches, offset_points
from apps.vision.tools.builtin.trigger import TriggerFlowTool, _plain
from apps.vision.tools.roi import crop

MAX_SUBFLOW_DEPTH = 5


def _target_id(ctx: ToolContext) -> int:
    return TriggerFlowTool._target_id(ctx)  # noqa: SLF001 - 與 trigger_flow 共用驗證文字與行為。


def _chain(ctx: ToolContext, target_id: int) -> list[int]:
    return TriggerFlowTool._trigger_chain(ctx, target_id)  # noqa: SLF001 - call_flow/trigger_flow 必須共用同一條鏈。


def _deadline(ctx: ToolContext) -> float | None:
    raw = ctx.context.get("_deadline")
    try:
        parent = float(raw)
    except (TypeError, ValueError):
        parent = 0.0
    if not math.isfinite(parent) or parent <= 0:
        parent = 0.0
    timeout_ms = ctx.number("timeout_ms", 0)
    local = time.perf_counter() + timeout_ms / 1000.0 if timeout_ms > 0 else 0.0
    candidates = [v for v in (parent, local) if v > 0]
    return min(candidates) if candidates else None


def _subflow_depth(ctx: ToolContext) -> int:
    try:
        return int(ctx.context.get("_call_depth") or 0)
    except (TypeError, ValueError):
        return 0


def _dry_run(ctx: ToolContext) -> bool:
    """最外層試執行不真的呼叫；子流程內的 sandbox 仍可繼續巢狀呼叫以檢查深度與環路。"""
    return bool(ctx.preview or ctx.flow_id <= 0 or (ctx.context.get("_sandbox") and _subflow_depth(ctx) <= 0))


def _child_context(ctx: ToolContext, chain: list[int], *, pass_outputs: bool, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    child: dict[str, Any] = {"_trigger_chain": chain, "_call_depth": _subflow_depth(ctx) + 1}
    if ctx.context.get("_sandbox"):
        child["_sandbox"] = True
    if pass_outputs:
        for key, value in (ctx.context.get("_outputs") or {}).items():
            child[str(key)] = _plain(value)
    if extra:
        child.update(extra)
    return child


def _load_target(target_id: int) -> Flow:
    target = Flow.objects.filter(pk=target_id).first()
    if target is None:
        raise ToolError(f"Target flow {target_id} does not exist")
    if not target.is_enabled:
        raise ToolError(f"Target flow '{target.name}' is disabled")
    return target


def _run_child(
    ctx: ToolContext,
    target: Flow,
    *,
    pass_outputs: bool,
    pass_image: bool,
    input_image: np.ndarray | None,
    extra_context: dict[str, Any] | None = None,
) -> engine.RunReport:
    if _subflow_depth(ctx) >= MAX_SUBFLOW_DEPTH:
        raise ToolError(f"Nested flow depth is limited to {MAX_SUBFLOW_DEPTH}")
    chain = _chain(ctx, target.id)
    from apps.vision.runner import runner

    compiled = runner.compiled_for(target)
    child_context = _child_context(ctx, chain, pass_outputs=pass_outputs, extra=extra_context)
    image = input_image if pass_image else None
    return engine.execute(
        compiled,
        flow_id=target.id,
        flow_version=target.version,
        trigger="call_flow",
        grab=runner._grab,  # noqa: SLF001 - 直跑路徑與 batch/warmup 同一個快取接縫。
        asset_path=runner._asset_path,  # noqa: SLF001
        preview=False,
        initial_context=child_context,
        input_image=image,
        run_id=ctx.run_id,
        deadline=_deadline(ctx),
        flow_timeout_s=0,
        stop_on_ng=bool(getattr(target, "stop_on_ng", False)),
    )


def _branch_for(status: str) -> str:
    return status if status in ("ok", "ng") else "failed"


def _prefixed(outputs: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {f"{prefix}{key}": value for key, value in outputs.items()}


def _restore_outputs(outputs: dict[str, Any], dx: float, dy: float) -> dict[str, Any]:
    restored = dict(outputs)
    if "points" in restored and restored["points"] is not None:
        restored["points"] = offset_points(restored["points"], dx, dy)
    if "matches" in restored and restored["matches"] is not None:
        restored["matches"] = offset_matches(restored["matches"], dx, dy)
    for x_key, y_key in _coordinate_pairs(restored):
        shifted = offset_points([[restored[x_key], restored[y_key]]], dx, dy)[0]
        restored[x_key], restored[y_key] = shifted[0], shifted[1]
    return restored


def _coordinate_pairs(values: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    candidates = [("x", "y"), ("cx", "cy")]
    for key in values:
        if key.endswith("_x"):
            candidates.append((key, f"{key[:-2]}_y"))
    for x_key, y_key in candidates:
        if x_key in values and y_key in values:
            try:
                float(values[x_key])
                float(values[y_key])
            except (TypeError, ValueError):
                continue
            pairs.append((x_key, y_key))
    return pairs


class CallFlowTool(Tool):
    key = "call_flow"
    label = "Call flow"
    description = "Runs another flow inline inside the current run. It does not queue, create a run record or update flow statistics."
    category = "logic"
    icon = "Workflow"
    params = [
        Param("target_flow_id", "Target flow", kind="number", required=True, minimum=1, step=1,
              help_text="Pick the flow to run inline. The value stored in the graph is the flow id."),
        Param("prefix", "Output prefix", kind="text", default="sub_",
              help_text="Added in front of child named outputs when they are merged into this run."),
        Param("pass_outputs", "Pass named outputs", kind="boolean", default=True),
        Param("pass_image", "Pass image", kind="boolean", default=True),
        Param("timeout_ms", "Timeout", kind="number", default=0, minimum=0, unit="ms",
              help_text="0 uses the time left on the parent run."),
    ]
    inputs = [Port("image", "Image", "image", required=False)]
    outputs = [
        flow_out("ok", "OK", "ok"), flow_out("ng", "NG", "warn"), flow_out("failed", "Failed", "critical"),
        Port("judge", "Judge", "string"), Port("ok", "OK", "bool"), Port("duration_ms", "Duration", "number"),
        Port("outputs", "Child outputs", "any"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        target_id = _target_id(ctx)
        if _dry_run(ctx):
            return Result(outputs={"judge": "", "ok": True, "duration_ms": 0.0, "outputs": {}}, branch="ok",
                          message=f"Would call flow {target_id}")
        target = _load_target(target_id)
        image = ctx.image("image") if ctx.flag("pass_image", True) else None
        report = _run_child(ctx, target, pass_outputs=ctx.flag("pass_outputs", True),
                            pass_image=ctx.flag("pass_image", True), input_image=image)
        branch = _branch_for(report.status)
        ok = report.status == "ok"
        judge = str(report.outputs.get("judge") or report.status.upper())
        child_outputs = dict(report.outputs or {})
        merged = _prefixed(child_outputs, str(ctx.param("prefix", "sub_") or ""))
        parent_outputs = dict(ctx.context.get("_outputs") or {})
        parent_outputs.update(merged)
        return Result(
            outputs={"judge": judge, "ok": ok, "duration_ms": report.duration_ms, "outputs": child_outputs},
            status="ok" if report.status == "ok" else ("ng" if report.status == "ng" else "error"),
            branch=branch,
            context={"_outputs": parent_outputs},
            message=f"Called flow '{target.name}' finished {report.status}" + (f": {report.error}" if report.error else ""),
        )


class ForEachTool(Tool):
    key = "for_each"
    label = "For each"
    description = "Runs an inline child flow once for every match, region or image and returns a per-item summary."
    category = "logic"
    icon = "Repeat"
    params = [
        Param("target_flow_id", "Target flow", kind="number", required=True, minimum=1, step=1),
        Param("source", "Items", kind="select", default="auto", options=[
            {"value": "auto", "label": "Auto"},
            {"value": "regions", "label": "Regions"},
            {"value": "matches", "label": "Matches"},
            {"value": "images", "label": "Images"},
        ]),
        Param("max_items", "Max items", kind="number", default=100, minimum=1, maximum=10000),
        Param("on_error", "On error", kind="select", default="continue", options=[
            {"value": "continue", "label": "Continue"},
            {"value": "stop", "label": "Stop"},
        ]),
        Param("pass_outputs", "Pass named outputs", kind="boolean", default=True),
        Param("timeout_ms", "Timeout", kind="number", default=0, minimum=0, unit="ms",
              help_text="0 uses the time left on the parent run."),
    ]
    inputs = [
        Port("image", "Image", "image", required=False),
        Port("regions", "Regions", "list", required=False),
        Port("matches", "Matches", "matches", required=False),
        Port("images", "Images", "image", required=False, multiple=True),
    ]
    outputs = [
        Port("count", "Count", "number"), Port("ok_count", "OK count", "number"), Port("ng_count", "NG count", "number"),
        Port("items", "Items", "list"), Port("all_ok", "All OK", "bool"),
        flow_out("ok", "All OK", "ok"), flow_out("ng", "Any NG", "critical"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        target_id = _target_id(ctx)
        kind, items = self._items(ctx)
        max_items = max(1, ctx.integer("max_items", 100))
        if len(items) > max_items:
            raise ToolError(f"for_each got {len(items)} items; max_items is {max_items}")
        if _dry_run(ctx):
            return Result(outputs={"count": len(items), "ok_count": len(items), "ng_count": 0, "items": [], "all_ok": True},
                          branch="ok", message=f"Would call flow {target_id} for {len(items)} items")
        target = _load_target(target_id)
        rows: list[dict[str, Any]] = []
        ok_count = 0
        ng_count = 0
        parent_image = ctx.image("image")
        for index, item in enumerate(items):
            try:
                image, offset, extra = self._item_input(kind, item, parent_image, index)
                report = _run_child(ctx, target, pass_outputs=ctx.flag("pass_outputs", True),
                                    pass_image=image is not None, input_image=image, extra_context=extra)
                outputs = dict(report.outputs or {})
                if offset != (0.0, 0.0):
                    outputs = _restore_outputs(outputs, offset[0], offset[1])
                status = report.status if report.status in ("ok", "ng") else "failed"
                if status == "ok":
                    ok_count += 1
                else:
                    ng_count += 1
                rows.append({"index": index, "status": status, "judge": outputs.get("judge", status.upper()),
                             "duration_ms": round(report.duration_ms, 3), "outputs": outputs, "offset": list(offset)})
                if status == "failed" and ctx.param("on_error", "continue") == "stop":
                    break
            except Exception as exc:  # noqa: BLE001 - 單項失敗是否中止由 on_error 控制。
                ng_count += 1
                rows.append({"index": index, "status": "failed", "judge": "FAILED", "duration_ms": 0.0,
                             "outputs": {}, "error": str(exc)[:300], "offset": [0.0, 0.0]})
                if ctx.param("on_error", "continue") == "stop":
                    break
        all_ok = bool(rows) and ok_count == len(rows) and ng_count == 0
        return Result(
            status="ok" if all_ok else "ng",
            branch="ok" if all_ok else "ng",
            outputs={"count": len(rows), "ok_count": ok_count, "ng_count": ng_count, "items": rows, "all_ok": all_ok},
            message=f"{ok_count}/{len(rows)} items OK",
        )

    @staticmethod
    def _items(ctx: ToolContext) -> tuple[str, list[Any]]:
        source = str(ctx.param("source", "auto") or "auto")
        order = ("regions", "matches", "images") if source == "auto" else (source,)
        for key in order:
            value = ctx.inputs.get(key)
            if value is None:
                continue
            items = value if isinstance(value, list) else [value]
            return key, list(items)
        raise ToolError("Wire matches, regions or images into for_each")

    @staticmethod
    def _item_input(kind: str, item: Any, image: np.ndarray | None, index: int) -> tuple[np.ndarray | None, tuple[float, float], dict[str, Any]]:
        extra = {"item_index": index, "item": _plain(item)}
        if kind == "regions":
            if not isinstance(item, dict) or not item.get("shape"):
                raise ToolError(f"regions[{index}] is not a region")
            if image is None:
                raise ToolError("Region iteration needs an image input")
            c = crop(image, item)
            extra.update({"region": item, "offset_x": c.x0, "offset_y": c.y0})
            return c.image, (float(c.x0), float(c.y0)), extra
        if kind == "matches":
            if not isinstance(item, dict):
                raise ToolError(f"matches[{index}] is not an object")
            extra["match"] = _plain(item)
            return None, (0.0, 0.0), extra
        if kind == "images":
            if not isinstance(item, np.ndarray):
                raise ToolError(f"images[{index}] is not an image")
            return item, (0.0, 0.0), extra
        raise ToolError("Items must be matches, regions or images")


class TileTool(Tool):
    key = "tile"
    label = "Tile image"
    description = "Splits the image area into rows and columns of rectangular regions, optionally with overlap."
    category = "logic"
    icon = "Grid3X3"
    params = [
        Param("rows", "Rows", kind="number", default=2, minimum=1, step=1),
        Param("cols", "Columns", kind="number", default=2, minimum=1, step=1),
        Param("overlap", "Overlap", kind="number", default=0, minimum=0,
              help_text="Either a ratio of each base tile or a pixel amount."),
        Param("overlap_mode", "Overlap mode", kind="select", default="ratio", options=[
            {"value": "ratio", "label": "Ratio"},
            {"value": "pixels", "label": "Pixels"},
        ]),
        Param("include_remainder", "Include remainder", kind="boolean", default=True),
        Param("width", "Width", kind="number", default=0, minimum=0, group="Advanced"),
        Param("height", "Height", kind="number", default=0, minimum=0, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image", required=False)]
    outputs = [Port("regions", "Regions", "list"), Port("count", "Count", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.image("image")
        if image is not None:
            height, width = image.shape[:2]
        else:
            width = ctx.integer("width", 0)
            height = ctx.integer("height", 0)
        if width <= 0 or height <= 0:
            raise ToolError("Tile needs an image input or width and height parameters")
        regions = tile_regions(
            width, height,
            rows=max(1, ctx.integer("rows", 1)),
            cols=max(1, ctx.integer("cols", 1)),
            overlap=max(0.0, ctx.number("overlap", 0)),
            overlap_mode=str(ctx.param("overlap_mode", "ratio") or "ratio"),
            include_remainder=ctx.flag("include_remainder", True),
        )
        return Result(outputs={"regions": regions, "count": len(regions)}, message=f"{len(regions)} tiles")


def tile_regions(width: int, height: int, *, rows: int, cols: int, overlap: float = 0.0,
                 overlap_mode: str = "ratio", include_remainder: bool = True) -> list[dict[str, float | str]]:
    """依影像大小產生矩形切片。overlap 是相鄰 tile 的重疊量，由左右／上下各半擴張。"""
    rows, cols = max(1, int(rows)), max(1, int(cols))
    if include_remainder:
        xs = [width * i / cols for i in range(cols + 1)]
        ys = [height * i / rows for i in range(rows + 1)]
    else:
        cell_w = math.floor(width / cols)
        cell_h = math.floor(height / rows)
        xs = [cell_w * i for i in range(cols + 1)]
        ys = [cell_h * i for i in range(rows + 1)]
    base_w = width / cols
    base_h = height / rows
    if overlap_mode == "pixels":
        ox = oy = float(overlap)
    else:
        ox, oy = base_w * float(overlap), base_h * float(overlap)
    regions: list[dict[str, float | str]] = []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0.0, xs[c] - ox / 2.0)
            x1 = min(float(width), xs[c + 1] + ox / 2.0)
            y0 = max(0.0, ys[r] - oy / 2.0)
            y1 = min(float(height), ys[r + 1] + oy / 2.0)
            regions.append({"shape": "rect", "x": round(x0, 4), "y": round(y0, 4),
                            "w": round(max(0.0, x1 - x0), 4), "h": round(max(0.0, y1 - y0), 4)})
    return regions


TOOLS = [CallFlowTool(), ForEachTool(), TileTool()]
