"""跨 run 的影像緩衝工具。"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from apps.vision.images import store as image_store
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, flow_out
from apps.vision.tools.messages import Msg


def _node_slug(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "node")).strip("_")
    return (text or "node")[:48]


def _state_names(ctx: ToolContext) -> tuple[str, str]:
    base = f"frame_accumulate_{_node_slug(ctx.node.get('id') or ctx.node.get('type'))}"
    return f"{base}_meta", f"{base}_image"


def _overlay_key(ctx: ToolContext, name: str) -> str:
    return f"{ctx.flow_id}:{name}"


def _empty_image() -> None:
    """清空累積狀態時存 None，不要留一個退化的 ndarray。

    早期版本存 `np.empty((0,))`（1 維），`variables.snapshot()` 把 ndarray 一律當成影像
    去讀 `shape[1]`，於是流程只要 reset 過一次，`GET /flows/{id}/board`、`/variables`
    與 `/dashboards/{id}/data` 就全部 500——現場看板會整片掛掉。
    """
    return None


def _to_input_depth(values: np.ndarray, like: np.ndarray) -> np.ndarray:
    if like.dtype == np.uint8:
        return np.clip(np.rint(values), 0, 255).astype(np.uint8)
    if like.dtype == np.uint16:
        return np.clip(np.rint(values), 0, 65535).astype(np.uint16)
    return values.astype(like.dtype, copy=False) if np.issubdtype(like.dtype, np.floating) else values.astype(like.dtype)


class FrameAccumulateTool(Tool):
    key = "frame_accumulate"
    label = "Frame accumulate"
    description = "Accumulates several runs of the same image and emits their mean, maximum or minimum."
    category = "preprocess"
    icon = "Layers3"
    accepts = ("u8", "u16", "f32")
    params = [
        Param("mode", "Mode", kind="select", default="mean", options=[
            {"value": "mean", "label": "Mean"},
            {"value": "max", "label": "Maximum"},
            {"value": "min", "label": "Minimum"},
        ]),
        Param("count", "Frame count", kind="number", default=3, minimum=1, maximum=1000),
        Param("emit", "Output", kind="select", default="ready", options=[
            {"value": "ready", "label": "Only when full"},
            {"value": "always", "label": "Every run"},
        ]),
        Param("reset", "Reset", kind="boolean", default=False),
    ]
    inputs = [Port("image", "Image", "image"), Port("reset", "Reset", "bool", required=False)]
    outputs = [Port("image", "Image", "image"), Port("frames", "Frames", "number"), flow_out("ready", "Ready", "ok"), flow_out("waiting", "Waiting")]

    def execute(self, ctx: ToolContext) -> Result:
        meta_name, image_name = _state_names(ctx)
        if ctx.flag("reset") or bool(ctx.inputs.get("reset")):
            ctx.set_variable(meta_name, {"frames": 0}, scope="flow")
            ctx.set_variable(image_name, _empty_image(), scope="flow")
            return Result(outputs={"frames": 0}, branch="waiting", message=Msg.of("frame_accumulate.reset", "Reset"))

        image = ctx.require_image()
        mode = str(ctx.param("mode", "mean"))
        if mode not in ("mean", "max", "min"):
            mode = "mean"
        target = max(1, ctx.integer("count", 3))
        emit_always = ctx.param("emit", "ready") == "always"
        overlay = ctx.context.get("_variables_overlay")
        isolated_sandbox = ctx.sandboxed() and not (isinstance(overlay, dict) and _overlay_key(ctx, meta_name) in overlay)
        meta = {} if isolated_sandbox else ctx.variable(meta_name, {}, scope="flow")
        acc = None if isolated_sandbox else ctx.variable(image_name, None, scope="flow")
        valid = (
            isinstance(meta, dict)
            and isinstance(acc, np.ndarray)
            and tuple(meta.get("shape") or ()) == tuple(image.shape)
            and str(meta.get("dtype") or "") == str(image.dtype)
            and str(meta.get("mode") or "") == mode
            and int(meta.get("target") or target) == target
            and int(meta.get("frames") or 0) > 0
        )
        if not valid:
            frames = 0
            acc = None
        else:
            frames = int(meta.get("frames") or 0)

        work = image.astype(np.float32) if mode == "mean" else image.copy()
        if frames <= 0 or acc is None:
            acc = work
        elif mode == "mean":
            acc = acc.astype(np.float32, copy=False) + work
        elif mode == "max":
            acc = np.maximum(acc, work)
        else:
            acc = np.minimum(acc, work)
        frames += 1

        ctx.set_variable(meta_name, {"frames": frames, "shape": list(image.shape), "dtype": str(image.dtype), "mode": mode, "target": target}, scope="flow")
        ctx.set_variable(image_name, acc, scope="flow")

        ready = frames >= target
        if not ready and not emit_always:
            return Result(outputs={"frames": frames}, branch="waiting", message=Msg.of("frame_accumulate.progress", "{frames}/{target}", frames=frames, target=target))

        out = _to_input_depth(acc / float(frames), image) if mode == "mean" else np.asarray(acc).astype(image.dtype, copy=False)
        branch = "ready" if ready else "waiting"
        message = Msg.of("frame_accumulate.done", "{mode} {frames}/{target}", mode=mode, frames=frames, target=target)
        if ready:
            ctx.set_variable(meta_name, {"frames": 0}, scope="flow")
            ctx.set_variable(image_name, _empty_image(), scope="flow")
        return Result(outputs={"image": out, "frames": frames}, branch=branch, message=message)


class PreviousImageTool(Tool):
    key = "previous_image"
    label = "Previous image"
    description = "Reads an image output from a recent run of the same flow."
    category = "preprocess"
    icon = "History"
    params = [
        Param("node", "Node id", kind="text", required=True),
        Param("port", "Port", kind="text", default="image"),
        Param("k", "Runs back", kind="number", default=1, minimum=1, maximum=100),
    ]
    inputs: list[Port] = []
    outputs = [Port("image", "Image", "image"), flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "warn")]

    def execute(self, ctx: ToolContext) -> Result:
        node = str(ctx.param("node", "") or "").strip()
        port = str(ctx.param("port", "image") or "image").strip()
        k = max(1, ctx.integer("k", 1))
        if not node or not port:
            return Result(branch="not_found", status="ng", message=Msg.of("previous_image.missing_params", "Node and port are required"))
        with image_store._lock:  # noqa: SLF001 - ImageStore has no public run index reader.
            runs = [run for run in image_store._runs_by_flow.get(ctx.flow_id, []) if run != ctx.run_id]  # noqa: SLF001
        if len(runs) < k:
            return Result(branch="not_found", status="ng", message=Msg.of("previous_image.not_enough_runs", "No image {k} run(s) back", k=k))
        run_id = runs[-k]
        ref = f"{run_id}:{node}:{port}"
        image = image_store.get(ref)
        if image is None:
            return Result(branch="not_found", status="ng", message=Msg.of("previous_image.not_found", "{ref} not found", ref=ref))
        return Result(outputs={"image": image.copy()}, branch="found", message=ref)


TOOLS = [FrameAccumulateTool(), PreviousImageTool()]
