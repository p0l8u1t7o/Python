"""主動輸出（Modbus TCP／上位機）：把 run 的結果依對映表寫到通訊連線（apps.comm）。

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


class WriteModbusTool(Tool):
    key = "write_modbus"
    label = "Write Modbus"
    description = "Writes the verdict, named outputs or input values to a Modbus TCP device or host connection through a mapping table. By default a failed write only logs a warning and does not fail the run."
    category = "output"
    icon = "Cable"
    connection_params = ("connection",)
    params = [
        Param("connection", "Connection", kind="text", required=True, help_text="The name of a communication connection (create one on the Connections page; an id also works)."),
        Param(
            "mapping", "Mapping", kind="json", required=True, default=[{"src": "judge", "address": "coil:0", "dtype": "bool"}],
            help_text='An array of {"src": source, "address": address, "dtype"?: bool|int|float, "scale"?: factor, "offset"?: offset, "value"?: constant}. '
                      "The source may be judge (OK becomes 1, NG becomes 0), a named output, or this step's inputs v0, v1 and so on. "
                      "Modbus addresses look like coil:10, holding:100, holding:100:float32 or holding:100:int32; tcp_client uses template field names.",
        ),
        Param("on_error", "On write failure", kind="select", default="warn", options=[
            {"value": "warn", "label": "Degrade: log a warning and carry on"},
            {"value": "fail", "label": "Fail the run"},
        ]),
        Param("timeout_s", "Timeout (s)", kind="number", default=0, minimum=0, maximum=60, step=0.1, help_text="0 uses the connection's own timeout.", group="Advanced"),
    ]
    inputs = [Port("values", "Value", "any", required=False, multiple=True)]
    outputs = [Port("written", "Values written", "number"), Port("ok", "Succeeded", "bool")]

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
                missing.append(f"#{i}: not an object")
                continue
            src = str(item.get("src") or "")
            address = str(item.get("address") or src)
            if not address:
                missing.append(f"#{i}: no address")
                continue
            if "value" in item:
                value = item["value"]
            else:
                if not src:
                    missing.append(f"{address}: no src")
                    continue
                value = self._lookup(ctx, src, values)
                if value is _MISSING:
                    missing.append(f"{address}: source not found '{src}'")
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
                    missing.append(f"{address}: the value {value!r} cannot be converted to {dtype}")
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
            return self._failed(ctx, on_error, f"Connection '{name}' is not open (missing, disabled, or not pre-loaded)", detail)
        if not payload:
            ctx.log("Nothing in the mapping table can be written", level="warning", missing=missing)
            return Result(outputs={"written": 0, "ok": True}, message="Nothing to write", detail=detail)
        try:
            result = writer.write(payload, timeout=timeout)
        except CommError as exc:
            return self._failed(ctx, on_error, str(exc), detail)
        except Exception as exc:  # noqa: BLE001 — 外掛 writer 的未預期例外也要走降級
            return self._failed(ctx, on_error, f"{type(exc).__name__}: {exc}", detail)
        written = int(result.get("written", len(payload)))
        detail["result"] = {k: v for k, v in result.items() if k != "values"}
        if missing:
            ctx.log(f"{len(missing)} sources were not found and were skipped", level="warning", missing=missing)
        return Result(outputs={"written": written, "ok": True}, message=f"Wrote {written} values to {name}", detail=detail)

    @staticmethod
    def _failed(ctx: ToolContext, on_error: str, reason: str, detail: dict[str, Any]) -> Result:
        detail = {**detail, "error": reason}
        if on_error == "fail":
            return Result(outputs={"written": 0, "ok": False}, status="error", message=f"Write failed: {reason}"[:500], detail=detail)
        ctx.log(f"Write failed (degraded): {reason}", level="warning")
        return Result(outputs={"written": 0, "ok": False}, status="ok", message=f"Write failed (degraded): {reason}"[:500], detail=detail)


class ReadModbusTool(Tool):
    key = "read_modbus"
    label = "Read Modbus"
    description = (
        "Reads coils and registers from a communication connection for the flow to act on or return. "
        "A client connection (modbus_tcp) reads the PLC or device; a server connection (modbus_server) reads what the "
        "master wrote into this platform's registers, such as a part number or a trigger flag."
    )
    category = "logic"
    icon = "Cable"
    connection_params = ("connection",)
    params = [
        Param("connection", "Connection", kind="text", required=True, help_text="The name of a communication connection (create one under External integration ▸ Connections)."),
        Param(
            "mapping", "Read mapping", kind="json", required=True, default=[{"name": "recipe", "address": "holding:0"}],
            help_text='An array of {"name": name, "address": address, "scale"?: factor, "offset"?: offset}. '
                      "Addresses look like coil:10, discrete:3, holding:100, holding:100:float32 or input:7; a blank name falls back to the address.",
        ),
        Param("publish", "Also publish as named outputs", kind="boolean", default=False, help_text="With this on, the values read appear in the run outputs, where the HTTP and TCP replies show them."),
        Param("on_error", "On read failure", kind="select", default="warn", options=[
            {"value": "warn", "label": "Degrade: log a warning and carry on"},
            {"value": "fail", "label": "Fail the run"},
        ]),
        Param("timeout_s", "Timeout (s)", kind="number", default=0, minimum=0, maximum=60, step=0.1, help_text="0 uses the connection's own timeout.", group="Advanced"),
    ]
    inputs: list[Port] = []
    outputs = [Port("values", "Value", "list"), Port("value", "First value", "number"), Port("ok", "Succeeded", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        name = str(ctx.param("connection", "")).strip()
        mapping = ctx.param("mapping", [])
        if isinstance(mapping, dict):
            mapping = [mapping]
        if not isinstance(mapping, list):
            mapping = []
        on_error = str(ctx.param("on_error", "warn"))
        items = [item for item in mapping if isinstance(item, dict) and str(item.get("address") or "").strip()]
        addresses = [str(item["address"]).strip() for item in items]
        detail: dict[str, Any] = {"connection": name, "addresses": addresses}
        if not addresses:
            return Result(outputs={"values": [], "value": 0.0, "ok": True}, message="The read mapping has no addresses", detail=detail)

        writer = get_writer(name)
        if writer is None:
            return self._read_failed(ctx, on_error, f"Connection '{name}' is not open (missing, disabled, or not pre-loaded)", detail)
        try:
            raw = writer.read(addresses)
        except CommError as exc:
            return self._read_failed(ctx, on_error, str(exc), detail)
        except Exception as exc:  # noqa: BLE001 — 外掛 writer 的未預期例外也要走降級
            return self._read_failed(ctx, on_error, f"{type(exc).__name__}: {exc}", detail)

        values: list[Any] = []
        named: dict[str, Any] = {}
        for item in items:
            address = str(item["address"]).strip()
            value = _scalar(raw.get(address))
            scale, offset = item.get("scale"), item.get("offset")
            if (scale is not None or offset is not None) and isinstance(value, (bool, int, float)):
                value = float(value) * float(scale if scale is not None else 1.0) + float(offset or 0.0)
            values.append(value)
            named[str(item.get("name") or address)] = value
        detail["values"] = named
        result_context = None
        if ctx.flag("publish", False):
            outputs = dict(ctx.context.get("_outputs") or {})
            outputs.update(named)
            result_context = {"_outputs": outputs}
        first = next((v for v in values if isinstance(v, (int, float, bool))), 0)
        return Result(
            outputs={"values": values, "value": float(first), "ok": True},
            message=", ".join(f"{k}={v}" for k, v in named.items())[:200],
            detail=detail, context=result_context,
        )

    @staticmethod
    def _read_failed(ctx: ToolContext, on_error: str, reason: str, detail: dict[str, Any]) -> Result:
        detail = {**detail, "error": reason}
        if on_error == "fail":
            return Result(outputs={"values": [], "value": 0.0, "ok": False}, status="error", message=f"Read failed: {reason}"[:500], detail=detail)
        ctx.log(f"Read failed (degraded): {reason}", level="warning")
        return Result(outputs={"values": [], "value": 0.0, "ok": False}, status="ok", message=f"Read failed (degraded): {reason}"[:500], detail=detail)


TOOLS = [WriteModbusTool(), ReadModbusTool()]
