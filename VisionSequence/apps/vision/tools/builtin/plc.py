"""主動輸出到 PLC / 上位機：把 run 的結果依對映表寫到通訊連線（apps.comm）。

熱路徑不碰資料庫：連線由 apps.comm 的 prefetch hook 在呼叫者執行緒開好，
這裡只用 get_writer(name) 從記憶體拿；寫入失敗預設降級（run 仍 ok、記 warning）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from apps.comm.writers import CommError, coerce, get_writer
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext

_MISSING = object()


def _scalar(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.item() if value.size == 1 else value.tolist()
    return value


class WritePlcTool(Tool):
    key = "write_plc"
    label = "寫入 PLC"
    description = "依對映表把判定、具名輸出或輸入埠的值寫到 PLC／上位機連線。寫入失敗預設只記警告不讓 run 失敗。"
    category = "output"
    icon = "Cable"
    params = [
        Param("connection", "連線", kind="text", required=True, help_text="填通訊連線的名稱（設定頁「連線」建立；也可填 id）。"),
        Param(
            "mapping", "對映表", kind="json", required=True, default=[{"src": "judge", "address": "coil:0", "dtype": "bool"}],
            help_text='陣列，每項 {"src": 來源, "address": 位址, "dtype"?: bool|int|float, "scale"?: 倍率, "offset"?: 加值, "value"?: 常數}。'
                      "src：judge（OK→1 / NG→0）、具名輸出名稱、或本節點輸入埠的 v0、v1…。"
                      "位址：modbus 用 coil:10 / holding:100 / holding:100:float32 / holding:100:int32；tcp_client 用範本欄位名；dio_sim 用通道名。",
        ),
        Param("on_error", "寫入失敗時", kind="select", default="warn", options=[
            {"value": "warn", "label": "降級：記警告，run 照常"},
            {"value": "fail", "label": "讓 run 失敗"},
        ]),
        Param("timeout_s", "逾時（秒）", kind="number", default=0, minimum=0, maximum=60, step=0.1, help_text="0 = 用連線設定的逾時。", group="進階"),
    ]
    inputs = [Port("values", "值", "any", required=False, multiple=True)]
    outputs = [Port("written", "寫入筆數", "number"), Port("ok", "成功", "bool")]

    # -- 值來源 -------------------------------------------------------------
    def _lookup(self, ctx: ToolContext, src: str, values: list[Any]) -> Any:
        if src == "judge":
            judge = ctx.context.get("_judge")
            if judge is None:
                judge = (ctx.context.get("_outputs") or {}).get("judge")
            if judge is None:
                return _MISSING
            return 1 if str(judge).lower() == "ok" else 0
        if len(src) >= 2 and src[0] == "v" and src[1:].isdigit():
            idx = int(src[1:])
            return values[idx] if idx < len(values) else _MISSING
        outputs = ctx.context.get("_outputs") or {}
        if src in outputs:
            return outputs[src]
        if src in ctx.context:
            return ctx.context[src]
        return _MISSING

    def _build(self, ctx: ToolContext, mapping: list[dict[str, Any]], values: list[Any]) -> tuple[dict[str, Any], list[str]]:
        payload: dict[str, Any] = {}
        missing: list[str] = []
        for i, item in enumerate(mapping):
            if not isinstance(item, dict):
                missing.append(f"#{i}: 不是物件")
                continue
            src = str(item.get("src") or "")
            address = str(item.get("address") or src)
            if not address:
                missing.append(f"#{i}: 沒有 address")
                continue
            if "value" in item:
                value = item["value"]
            else:
                if not src:
                    missing.append(f"{address}: 沒有 src")
                    continue
                value = self._lookup(ctx, src, values)
                if value is _MISSING:
                    missing.append(f"{address}: 找不到來源 '{src}'")
                    continue
            value = _scalar(value)
            dtype = str(item.get("dtype") or "")
            scale = item.get("scale")
            offset = item.get("offset")
            if (scale is not None or offset is not None) and isinstance(value, (bool, int, float)):
                value = float(value) * float(scale if scale is not None else 1.0) + float(offset or 0.0)
                if not dtype:
                    dtype = "float"
            if dtype:
                try:
                    value = coerce(value, dtype)
                except (TypeError, ValueError):
                    missing.append(f"{address}: 值 {value!r} 無法轉成 {dtype}")
                    continue
            payload[address] = value
        return payload, missing

    # -- 執行 -------------------------------------------------------------
    def execute(self, ctx: ToolContext) -> Result:
        name = str(ctx.param("connection", "")).strip()
        mapping = ctx.param("mapping", [])
        if isinstance(mapping, dict):
            mapping = [mapping]
        if not isinstance(mapping, list):
            mapping = []
        on_error = str(ctx.param("on_error", "warn"))
        timeout = ctx.number("timeout_s", 0) or None
        values = ctx.inputs.get("values") or []
        if not isinstance(values, list):
            values = [values]

        payload, missing = self._build(ctx, mapping, values)
        detail: dict[str, Any] = {"connection": name, "values": payload, "missing": missing}

        writer = get_writer(name)
        if writer is None:
            return self._failed(ctx, on_error, f"連線 '{name}' 未開啟（不存在、已停用或尚未預先載入）", detail)
        if not payload:
            ctx.log("對映表沒有任何可寫的值", level="warning", missing=missing)
            return Result(outputs={"written": 0, "ok": True}, message="沒有可寫的值", detail=detail)
        try:
            result = writer.write(payload, timeout=timeout)
        except CommError as exc:
            return self._failed(ctx, on_error, str(exc), detail)
        except Exception as exc:  # noqa: BLE001 — 外掛 writer 的未預期例外也要走降級
            return self._failed(ctx, on_error, f"{type(exc).__name__}: {exc}", detail)
        written = int(result.get("written", len(payload)))
        detail["result"] = {k: v for k, v in result.items() if k != "values"}
        if missing:
            ctx.log(f"{len(missing)} 個來源找不到，已略過", level="warning", missing=missing)
        return Result(outputs={"written": written, "ok": True}, message=f"已寫入 {written} 筆到 {name}", detail=detail)

    @staticmethod
    def _failed(ctx: ToolContext, on_error: str, reason: str, detail: dict[str, Any]) -> Result:
        detail = {**detail, "error": reason}
        if on_error == "fail":
            return Result(outputs={"written": 0, "ok": False}, status="error", message=f"寫入失敗：{reason}"[:500], detail=detail)
        ctx.log(f"寫入 PLC 失敗（已降級）：{reason}", level="warning")
        return Result(outputs={"written": 0, "ok": False}, status="ok", message=f"寫入失敗（已降級）：{reason}"[:500], detail=detail)


TOOLS = [WritePlcTool()]
