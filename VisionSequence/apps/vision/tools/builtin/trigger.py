"""流程觸發工具。"""

from __future__ import annotations

from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

import numpy as np

from apps.vision.images import store
from apps.vision.models import Flow
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.messages import Msg


class TriggerFlowTool(Tool):
    key = "trigger_flow"
    label = "Trigger flow"
    description = "Starts another flow from this run. Async returns after queueing; sync waits for the child result when there is executor capacity."
    category = "output"
    icon = "Workflow"
    params = [
        Param("target_flow_id", "Target flow", kind="number", required=True, minimum=1, step=1,
              help_text="Pick the flow to run next. The value stored in the graph is the flow id."),
        Param("mode", "Mode", kind="select", default="async", options=[
            {"value": "async", "label": "Async - queue and continue"},
            {"value": "sync", "label": "Sync - wait for result"},
        ]),
        Param("timeout_ms", "Sync timeout", kind="number", default=30000, minimum=1, unit="ms",
              visible_when={"param": "mode", "in": ["sync"]}),
        Param("pass_outputs", "Pass named outputs", kind="boolean", default=True),
        Param("pass_image", "Pass image", kind="boolean", default=True),
    ]
    inputs = [Port("image", "Image", "image", required=False)]
    outputs = [Port("run_id", "Run id", "string"), Port("judge", "Judge", "string"), Port("ok", "OK", "bool"),
               flow_out("ok", "OK", "ok"), flow_out("ng", "NG", "warn"), flow_out("failed", "Failed", "critical")]

    def execute(self, ctx: ToolContext) -> Result:
        target_id = self._target_id(ctx)
        mode = str(ctx.param("mode", "async") or "async").lower()
        if mode not in ("async", "sync"):
            raise ToolError(Msg.of("trigger_flow.bad_mode", "Mode must be async or sync"))
        if ctx.sandboxed():
            return Result(outputs={"run_id": "", "judge": "", "ok": True}, branch="ok", message=Msg.of("trigger_flow.would_trigger", "Would trigger flow {flow}", flow=target_id))

        target = Flow.objects.filter(pk=target_id).first()
        if target is None:
            raise ToolError(Msg.of("trigger_flow.not_found", "Target flow {flow} does not exist", flow=target_id))
        if not target.is_enabled:
            raise ToolError(Msg.of("trigger_flow.disabled", "Target flow '{name}' is disabled", name=target.name))
        chain = self._trigger_chain(ctx, target.id)
        child_context = self._child_context(ctx, chain)

        from apps.vision.runner import runner

        if mode == "sync":
            # 同步等待會佔住父流程的 worker；只有在 executor 目前明確還有空 worker、且沒有更早排隊的工作時才等。
            # 否則父流程等子流程、子流程等 worker，現場會看到整條線卡住，所以這裡寧可明確失敗。
            ok, cap = runner.sync_wait_available()
            if not ok:
                raise ToolError(Msg.of(
                    "trigger_flow.no_worker",
                    "Cannot wait for the triggered flow safely: no executor worker is clearly available "
                    "(workers {busy}/{max_workers}, queued {queued}). Use async mode or raise VISION_MAX_WORKERS.",
                    busy=cap.get("workers_busy"), max_workers=cap.get("max_workers"), queued=cap.get("executor_queued"),
                ))
        future = runner.submit(target, trigger="trigger_flow", context=child_context)
        run_id = str(getattr(future, "run_id", ""))
        if mode == "async":
            return Result(outputs={"run_id": run_id, "judge": "", "ok": True}, branch="ok",
                          message=Msg.of("trigger_flow.queued", "Queued flow '{name}' as {run}", name=target.name, run=run_id[:8]))
        try:
            report = future.result(timeout=max(0.001, ctx.number("timeout_ms", 30000) / 1000.0))
        except FutureTimeout:
            raise ToolError(Msg.of("trigger_flow.timeout", "Timed out waiting for triggered flow '{name}' ({run}); the child run continues",
                                  name=target.name, run=run_id[:8])) from None
        judge = str(report.outputs.get("judge") or report.status.upper())
        branch = report.status if report.status in ("ok", "ng") else "failed"
        ok = report.status == "ok"
        return Result(
            outputs={"run_id": run_id, "judge": judge, "ok": ok},
            status="ok" if report.status == "ok" else ("ng" if report.status == "ng" else "error"),
            branch=branch,
            message=(Msg.of("trigger_flow.finished_error", "Triggered flow '{name}' finished {status}: {error}",
                            name=target.name, status=report.status, error=report.error) if report.error
                     else Msg.of("trigger_flow.finished", "Triggered flow '{name}' finished {status}", name=target.name, status=report.status)),
        )

    @staticmethod
    def _target_id(ctx: ToolContext) -> int:
        try:
            target_id = int(ctx.param("target_flow_id"))
        except (TypeError, ValueError):
            raise ToolError(Msg.of("trigger_flow.no_target", "Pick a target flow")) from None
        if target_id <= 0:
            raise ToolError(Msg.of("trigger_flow.no_target", "Pick a target flow"))
        return target_id

    @staticmethod
    def _trigger_chain(ctx: ToolContext, target_id: int) -> list[int]:
        raw = ctx.context.get("_trigger_chain")
        chain: list[int] = []
        if isinstance(raw, (list, tuple)):
            for item in raw:
                try:
                    chain.append(int(item))
                except (TypeError, ValueError):
                    continue
        if ctx.flow_id > 0 and ctx.flow_id not in chain:
            chain.append(ctx.flow_id)
        if target_id in chain:
            if target_id == ctx.flow_id:
                raise ToolError(Msg.of("trigger_flow.self_trigger", "A flow cannot trigger itself"))
            raise ToolError(Msg.of("trigger_flow.loop", "Trigger chain would loop: {chain}",
                                  chain=" -> ".join([*(str(x) for x in chain), str(target_id)])))
        return [*chain, target_id]

    @staticmethod
    def _child_context(ctx: ToolContext, chain: list[int]) -> dict[str, Any]:
        child: dict[str, Any] = {"_trigger_chain": chain}
        if ctx.flag("pass_outputs", True):
            for key, value in (ctx.context.get("_outputs") or {}).items():
                child[str(key)] = _plain(value)
        if ctx.flag("pass_image", True):
            image = ctx.image("image")
            if isinstance(image, np.ndarray):
                node_id = str(ctx.node.get("id") or "trigger_flow")
                ref = f"{ctx.run_id}:{node_id}:trigger_input"
                store.put(ref, image, flow_id=ctx.flow_id, run_id=ctx.run_id)
                child["_input_image_ref"] = ref
                child["image_ref"] = ref
        return child


def _plain(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return {"array": True, "shape": list(value.shape)}
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


TOOLS = [TriggerFlowTool()]
