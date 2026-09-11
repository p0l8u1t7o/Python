"""主動輸出（Modbus TCP／上位機）：把 run 的結果依對映表寫到通訊連線（apps.comm），或把影像推給上位機。

熱路徑不碰資料庫：連線由 apps.comm 的 prefetch hook 在呼叫者執行緒開好，
這裡只用 get_writer(name) 從記憶體拿；寫入失敗預設降級（run 仍 ok、記 warning）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from apps.comm.writers import CommError, coerce, get_writer
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext
from apps.vision.tools.messages import Msg

_MISSING = object()


def _clip(text: str, limit: int) -> str:
    """過長的訊息照舊截斷英文，但保留代碼與參數。"""
    if len(text) <= limit:
        return text
    if isinstance(text, Msg):
        return Msg(str(text)[:limit], text.code, text.args)
    return text[:limit]


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
            return self._failed(ctx, on_error, Msg.of("write_modbus.not_open", "Connection '{name}' is not open (missing, disabled, or not pre-loaded)", name=name), detail)
        if not payload:
            ctx.log("Nothing in the mapping table can be written", level="warning", missing=missing)
            return Result(outputs={"written": 0, "ok": True}, message=Msg.of("write_modbus.nothing", "Nothing to write"), detail=detail)
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
        return Result(outputs={"written": written, "ok": True}, message=Msg.of("write_modbus.wrote", "Wrote {written} values to {name}", written=written, name=name), detail=detail)

    @staticmethod
    def _failed(ctx: ToolContext, on_error: str, reason: str, detail: dict[str, Any]) -> Result:
        detail = {**detail, "error": reason}
        if on_error == "fail":
            return Result(outputs={"written": 0, "ok": False}, status="error", message=_clip(Msg.of("write_modbus.failed", "Write failed: {reason}", reason=reason), 500), detail=detail)
        ctx.log(f"Write failed (degraded): {reason}", level="warning")
        return Result(outputs={"written": 0, "ok": False}, status="ok", message=_clip(Msg.of("write_modbus.degraded", "Write failed (degraded): {reason}", reason=reason), 500), detail=detail)


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
            return Result(outputs={"values": [], "value": 0.0, "ok": True}, message=Msg.of("read_modbus.no_addresses", "The read mapping has no addresses"), detail=detail)

        writer = get_writer(name)
        if writer is None:
            return self._read_failed(ctx, on_error, Msg.of("read_modbus.not_open", "Connection '{name}' is not open (missing, disabled, or not pre-loaded)", name=name), detail)
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
            return Result(outputs={"values": [], "value": 0.0, "ok": False}, status="error", message=_clip(Msg.of("read_modbus.failed", "Read failed: {reason}", reason=reason), 500), detail=detail)
        ctx.log(f"Read failed (degraded): {reason}", level="warning")
        return Result(outputs={"values": [], "value": 0.0, "ok": False}, status="ok", message=_clip(Msg.of("read_modbus.degraded", "Read failed (degraded): {reason}", reason=reason), 500), detail=detail)



class SendImageTool(Tool):
    key = "send_image"
    accepts = ("u8", "u16", "f32")
    label = "Send image"
    description = "Pushes this step's image to a host program through a TCP image connection (kind tcp_image), with the run id, verdict and named outputs in the frame header. By default a failed send only logs a warning and does not fail the run."
    category = "output"
    icon = "Send"
    connection_params = ("connection",)
    params = [
        Param("connection", "Connection", kind="text", required=True, help_text="The name of a TCP image connection (create one under External integration ▸ TCP; an id also works)."),
        Param("encoding", "Encoding", kind="select", default="", options=[
            {"value": "", "label": "As the connection is set"},
            {"value": "jpeg", "label": "JPEG"},
            {"value": "png", "label": "PNG (lossless)"},
            {"value": "raw", "label": "Raw pixels"},
        ]),
        Param("quality", "JPEG quality", kind="number", default=85, minimum=1, maximum=100, step=1, group="Advanced"),
        Param("name", "Frame name", kind="text", default="", help_text="Goes into the header as name; blank uses the connection name.", group="Advanced"),
        Param("include_values", "Include verdict and outputs", kind="boolean", default=True, help_text="Puts judge and the named outputs so far into the header as values.", group="Advanced"),
        Param("only_ng", "Rejects only", kind="boolean", default=False),
        Param("on_error", "On send failure", kind="select", default="warn", options=[
            {"value": "warn", "label": "Degrade: log a warning and carry on"},
            {"value": "fail", "label": "Fail the run"},
        ]),
        Param("timeout_s", "Timeout (s)", kind="number", default=0, minimum=0, maximum=60, step=0.1, help_text="0 uses the connection's own timeout.", group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image")]
    outputs = [Port("sent", "Sent", "bool"), Port("bytes", "Bytes", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        judge = ctx.context.get("_judge")
        if ctx.flag("only_ng") and str(judge or "ok").lower() != "ng":
            return Result(outputs={"sent": False, "bytes": 0}, message=Msg.of("send_image.skipped", "OK, not sent"))
        name = str(ctx.param("connection") or "")
        writer = get_writer(name)
        on_error = str(ctx.param("on_error") or "warn")

        def degrade(reason: str) -> Result:
            if on_error == "fail":
                return Result(status="error", outputs={"sent": False, "bytes": 0}, message=reason, detail={"error": reason})
            return Result(outputs={"sent": False, "bytes": 0}, message=Msg.of("send_image.degraded", "Send skipped (degraded): {reason}", reason=reason), detail={"error": reason})

        if writer is None:
            return degrade(Msg.of("send_image.not_open", "Connection '{name}' is not open or does not exist", name=name))
        send = getattr(writer, "send_image", None)
        if send is None:
            return degrade(Msg.of("send_image.no_images", "Connection '{name}' ({kind}) cannot carry images; use a TCP image connection", name=name, kind=writer.kind))
        header: dict[str, Any] = {"run_id": ctx.run_id, "flow_id": ctx.flow_id, "node": ctx.node.get("id", "")}
        if ctx.param("name"):
            header["name"] = str(ctx.param("name"))
        if ctx.flag("include_values", True):
            values = {k: _scalar(v) for k, v in (ctx.context.get("_outputs") or {}).items() if not isinstance(v, np.ndarray)}
            if judge is not None:
                values["judge"] = judge
            header["values"] = values
        timeout = float(ctx.param("timeout_s") or 0) or None
        try:
            out = send(image, header, encoding=str(ctx.param("encoding") or "") or None, quality=int(ctx.param("quality") or 85), timeout=timeout)
        except CommError as exc:
            return degrade(str(exc))
        return Result(outputs={"sent": True, "bytes": out["bytes"]}, message=Msg.of("send_image.sent", "Sent {kb:.1f} KB ({encoding} {width}x{height})",
                                    kb=out["bytes"] / 1024, encoding=out["encoding"], width=out["width"], height=out["height"]), detail=out)

TOOLS = [WriteModbusTool(), ReadModbusTool(), SendImageTool()]
