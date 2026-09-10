"""跨流程資料交接工具；試執行共用本次 run 的佇列副本。"""

from __future__ import annotations

import uuid

from apps.vision import images, queues
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.output import fill_template, format_values


def _key(ctx):
    seen = []
    try:
        key = fill_template(str(ctx.param("key", "")), ctx, missing="fail", seen=seen)
    except (ValueError, TypeError, IndexError, KeyError, AttributeError) as exc:
        raise ToolError(f"Queue key could not be filled: {exc}") from None
    if seen:
        raise ToolError(f"Queue key has missing values: {', '.join(seen)}")
    return key


_INPUTS = [Port(k, k, "any", required=False) for k in "abcd"]
_QUEUE = Param("queue", "Queue", default="parts", required=True)
_KEY = Param("key", "Part key", default="", help_text="A text layout such as {serial}; uses the same values as Format a reply.")


class QueuePushTool(Tool):
    key = "queue_push"
    label = "Push to queue"
    description = "Keep a part's values and optional image reference for another flow. Queues are cleared on process restart. Preview uses a private copy."
    category = "logic"
    icon = "ListPlus"
    accepts = ("u8", "u16", "f32")
    allows_unconnected = True
    params = [
        _QUEUE, _KEY,
        Param("values", "Values", kind="multiline", default="", help_text="One name=source per line, for example height=a. A connected data dictionary takes precedence. Missing sources fail the step."),
        Param("max_items", "Capacity", kind="number", default=64, minimum=1, maximum=1024, teach=True),
        Param("on_full", "When full", kind="select", default="drop_oldest", options=[
            {"value": "drop_oldest", "label": "Drop oldest"}, {"value": "reject", "label": "Reject push"}]),
        Param("ttl_s", "Lifetime", kind="number", default=0, minimum=0, unit="s", teach=True, help_text="Zero keeps the item until removed. Lifetime is set separately for each pushed item."),
    ]
    inputs = [Port("data", "Values", "any", required=False), Port("image", "Image", "image", required=False), *_INPUTS]
    outputs = [Port("seq", "Sequence", "number"), Port("size", "Size", "number"), Port("dropped", "Dropped", "number"),
               flow_out("pushed", "Pushed", "ok"), flow_out("full", "Full", "warn")]

    def execute(self, ctx: ToolContext) -> Result:
        values = ctx.inputs.get("data")
        if values is None:
            sources = format_values(ctx)
            # 保留原始值供正規化拒絕 ndarray，不讓格式工具先轉成清單。
            sources.update({k: v for k, v in ctx.inputs.items() if k in "abcd" and v is not None})
            values = {}
            for line in str(ctx.param("values", "")).splitlines():
                if not line.strip():
                    continue
                name, sep, source = line.partition("=")
                name, source = name.strip(), source.strip()
                if not sep or not name or not source:
                    raise ToolError("Write queue values as name=source, one per line")
                if source not in sources:
                    raise ToolError(f"Queue value source '{source}' is missing")
                if name in values:
                    raise ToolError(f"Queue value name '{name}' is duplicated")
                values[name] = sources[source]
        key = _key(ctx)
        try:
            values = queues.normalize(values)
            name = queues.check_name(ctx.param("queue", "parts"))
            capacity = ctx.number("max_items", 64)
            if not capacity.is_integer():
                raise queues.QueueError("Queue capacity must be an integer")
            image = ctx.image()
            ref = None
            if image is not None:
                ref = f"{ctx.run_id}:{ctx.node['id']}:queue-{uuid.uuid4().hex}"
                if ctx.sandboxed():
                    ctx.context.setdefault("_queues_images", {})[ref] = image
                else:
                    images.store.put(ref, image, flow_id=ctx.flow_id, run_id=ctx.run_id)
            result = queues.for_context(ctx).push(name, values, key=key, max_items=int(capacity),
                on_full=ctx.param("on_full", "drop_oldest"), ttl_s=ctx.number("ttl_s", 0),
                image_ref=ref, flow_id=ctx.flow_id, run_id=ctx.run_id)
        except (queues.QueueError, ValueError, OverflowError) as exc:
            raise ToolError(str(exc)) from None
        accepted = result.pop("accepted")
        return Result(outputs=result, status="ok" if accepted else "ng", branch="pushed" if accepted else "full",
                      message="Item queued" if accepted else "Queue is full")


class QueuePopTool(Tool):
    key = "queue_pop"
    label = "Read from queue"
    description = "Match a queued part by order or key. Preview reads a private copy. Images may expire before the values."
    category = "logic"
    icon = "ListMinus"
    allows_unconnected = True
    params = [
        _QUEUE, _KEY,
        Param("match", "Match", kind="select", default="fifo", options=[
            {"value": "fifo", "label": "Oldest first"}, {"value": "lifo", "label": "Newest first"}, {"value": "key", "label": "Part key"}]),
        Param("remove", "Remove after reading", kind="boolean", default=True),
        Param("wait_ms", "Wait", kind="number", default=0, minimum=0, maximum=2000, unit="ms", teach=True),
        Param("publish", "Publish values", kind="boolean", default=False, help_text="Add the matched dictionary fields to named outputs, replacing existing names."),
    ]
    inputs = [*_INPUTS]
    outputs = [Port("values", "Values", "any"), Port("key", "Part key", "string"), Port("age_ms", "Age", "number"),
               Port("image", "Image", "image"), Port("found", "Found", "bool"), Port("seq", "Sequence", "number"),
               Port("size", "Size", "number"), Port("oldest_age_ms", "Oldest age", "number"),
               flow_out("matched", "Matched", "ok"), flow_out("not_found", "Not found", "warn")]

    def execute(self, ctx: ToolContext) -> Result:
        match = ctx.param("match", "fifo")
        key = _key(ctx) if match == "key" else ""
        try:
            item, status = queues.for_context(ctx).pop(ctx.param("queue", "parts"), match=match, key=key,
                remove=ctx.flag("remove", True), wait_ms=ctx.number("wait_ms", 0))
        except queues.QueueError as exc:
            raise ToolError(str(exc)) from None
        output = {"values": {}, "key": "", "age_ms": 0.0, "image": None, "found": item is not None, "seq": 0,
                  "size": status["size"], "oldest_age_ms": status["oldest_age_ms"]}
        context = None
        warnings = []
        if item:
            output.update({k: item[k] for k in ("values", "key", "age_ms", "seq")})
            if item["image_ref"]:
                ref = item["image_ref"]
                image = ctx.context.get("_queues_images", {}).get(ref)
                if image is None:
                    image = images.store.get(ref)
                output["image"] = image
                if image is None:
                    warnings.append("The queued image is no longer available")
                    ctx.log(warnings[-1], level="warning")
            if ctx.flag("publish"):
                context = {"_outputs": {**(ctx.context.get("_outputs") or {}), **item["values"]}}
        return Result(outputs=output, context=context, branch="matched" if item else "not_found",
                      message=(warnings[0] if warnings else "Item matched") if item else "No matching item",
                      detail={"warnings": warnings, **({"flow_id": item["flow_id"], "run_id": item["run_id"], "at": item["at"]} if item else {})})


TOOLS = [QueuePushTool(), QueuePopTool()]
