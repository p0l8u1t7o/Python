"""主動輸出（Modbus TCP／上位機）：每種 kind 一個 Writer，`open_connection()` 依 Connection 設定建立並快取。

Writer 介面：
    write(values: dict[address, value], *, timeout=None) -> dict   寫一批（內部 lock、逾時、斷線自動重連一次）
    read(addresses: list[str]) -> dict                             讀回（測試／整合頁用）
    close()
    info() -> dict                                                 狀態（前端顯示）
可預期的失敗一律拋 CommError；工具層據此降級（預設不讓 run failed）。

位址格式（modbus_tcp）：
    coil:10                 線圈（bool）
    holding:100             保持暫存器，uint16（值四捨五入）
    holding:100:int16 / uint16 / int32 / uint32 / float32 / float64
    discrete:3 / input:7    只讀（read 用）
    數字可用 0x 十六進位。
tcp_client 的「位址」是範本裡的欄位名；dio_sim 是通道名。

外掛：settings.VISION["COMM_PLUGINS"] = {"opcua": "plugins.opcua:OpcUaWriter"}，
或 kind="plugin" 以 config["class"] 指定。

熱路徑規則：執行緒池內的工具只呼叫 get_writer(name)（純記憶體）；連線開啟在 Runner 的
prefetch hook（呼叫者執行緒）完成。
"""

from __future__ import annotations

import importlib
import json
import logging
import queue
import socket
import struct
import threading
import time
from typing import Any

import cv2
import numpy as np
from django.conf import settings

from apps.comm import events as eventmod, triggers
from apps.core.errors import NotFound, ValidationError

log = logging.getLogger(__name__)


class CommError(Exception):
    """可預期的通訊失敗（連不上、逾時、位址不合法、裝置回錯誤）。"""


# ---------------------------------------------------------------------------
# 位址解析
# ---------------------------------------------------------------------------
_AREA_ALIASES = {
    "coil": "coil", "co": "coil", "c": "coil",
    "holding": "holding", "hr": "holding", "register": "holding", "reg": "holding", "h": "holding",
    "discrete": "discrete", "di": "discrete",
    "input": "input", "ir": "input",
}
_DTYPES = ("bool", "int16", "uint16", "int32", "uint32", "int64", "uint64", "float32", "float64")
_DTYPE_WORDS = {"int16": 1, "uint16": 1, "int32": 2, "uint32": 2, "int64": 4, "uint64": 4, "float32": 2, "float64": 4}


def parse_address(address: str) -> tuple[str, int, str]:
    """'holding:100:float32' → ('holding', 100, 'float32')。coil 的 dtype 固定 bool。"""
    parts = [p.strip().lower() for p in str(address or "").split(":")]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise CommError(f"Malformed address '{address}' (expected area:offset[:dtype])")
    area = _AREA_ALIASES.get(parts[0])
    if area is None:
        raise CommError(f"Unknown address area '{parts[0]}' (coil, holding, discrete or input)")
    try:
        offset = int(parts[1], 0)
    except ValueError:
        raise CommError(f"The address offset is not an integer: '{parts[1]}'") from None
    if offset < 0 or offset > 0xFFFF:
        raise CommError(f"Address offset out of range: {offset}")
    if area in ("coil", "discrete"):
        return area, offset, "bool"
    dtype = parts[2] if len(parts) > 2 and parts[2] else "uint16"
    if dtype not in _DTYPE_WORDS:
        raise CommError(f"Unknown data type '{dtype}' ({', '.join(_DTYPE_WORDS)})")
    return area, offset, dtype


def coerce(value: Any, dtype: str) -> Any:
    """把工具算出來的值轉成該型別可寫的 Python 值。"""
    if dtype == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "ok")
        return bool(value)
    if dtype in ("float32", "float64", "float"):
        return float(value)
    if dtype in ("int", "int16", "uint16", "int32", "uint32", "int64", "uint64"):
        return int(round(float(value)))
    return value


# ---------------------------------------------------------------------------
# 基底
# ---------------------------------------------------------------------------
class Writer:
    kind = ""
    #: 資料夾外掛的顯示資訊（設定頁 kind 下拉）；label 空字串時顯示「外掛：<kind>」。
    label = ""
    description = ""
    #: config 欄位名稱提示（設定頁顯示用）。
    fields: list[str] = []
    #: False = 這個類別不掛載（apps.core.plugins 掃描時略過）。
    enabled = True
    #: True = 這個連線自己開埠等對方連進來（從站／伺服器）；啟動時要自動開，不能等第一次寫入。
    listens = False
    #: True = 送得出一段自己排版好的文字（事件回報、心跳、接收規則的回覆）；Modbus 這種只有位址的連線是 False。
    texts = False
    #: 這種連線由哪個整合頁管理（`/integration/<section>`）；外掛沒宣告就歸到外掛頁。
    section = "plugins"

    @classmethod
    def receives_config(cls, config: dict[str, Any]) -> bool:
        """這份設定會不會「收」資料？會收的連線要自動開起來，不能等第一次寫入。"""
        return False

    def __init__(self, config: dict[str, Any], *, connection_id: int = 0, name: str = "") -> None:
        self.config = config
        self.connection_id = connection_id
        self.name = name
        self.timeout = float(config.get("timeout_s", 2.0) or 2.0)
        self.writes = 0
        self.errors = 0
        self.reconnects = 0
        self.last_error = ""
        self.last_write_at = 0.0
        self._lock = threading.Lock()

    # -- 子類實作 -----------------------------------------------------------
    def _open(self) -> None:
        pass

    def _write(self, values: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _read(self, addresses: list[str]) -> dict[str, Any]:
        raise CommError(f"{self.kind} cannot read back")

    def _send_text(self, text: str) -> dict[str, Any]:
        raise CommError(f"{self.kind} cannot send a line of text")

    def _close(self) -> None:
        pass

    # -- 公開介面 -----------------------------------------------------------
    def write(self, values: dict[str, Any], *, timeout: float | None = None, quiet: bool = False) -> dict[str, Any]:
        """寫一批；第一次失敗會關閉、重開連線再試一次，第二次失敗才拋 CommError。
        `quiet=True`：成功不進整合追蹤（與 `read` 同一個規則）——心跳與週期回送每秒一則，
        記下去只會把真正的命令沖出環形緩衝；失敗照樣記。"""
        if not values:
            return {"written": 0}
        started = time.perf_counter()
        with self._lock:
            old = self.timeout
            if timeout:
                self.timeout = float(timeout)
            try:
                try:
                    out = self._write(values)
                except Exception as exc:  # noqa: BLE001
                    self.errors += 1
                    self.last_error = _msg(exc)
                    self.reconnects += 1
                    try:
                        self._close()
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        self._open()
                        out = self._write(values)
                    except Exception as exc2:  # noqa: BLE001
                        self.last_error = _msg(exc2)
                        raise CommError(f"{self.name or self.kind}: {self.last_error}") from exc2
                self.writes += 1
                self.last_write_at = time.time()
                if not quiet:
                    self._trace("write", values, out, started)
                return out
            except CommError as exc:
                self._trace("write", values, {"error": str(exc)}, started, ok=False)
                raise
            finally:
                self.timeout = old

    def send_text(self, text: str, *, quiet: bool = False) -> dict[str, Any]:
        """送一段自己排好版的文字（事件回報、心跳、接收規則的回覆）。

        與 `write` 的差別：`write` 是「把這些值送出去」，由連線的樣板決定長相；
        `send_text` 是「原樣送這一行」，樣板已經在呼叫端套好了。失敗一樣重連再試一次。
        """
        started = time.perf_counter()
        with self._lock:
            try:
                try:
                    out = self._send_text(text)
                except CommError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.errors += 1
                    self.last_error = _msg(exc)
                    self.reconnects += 1
                    try:
                        self._close()
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        self._open()
                        out = self._send_text(text)
                    except Exception as exc2:  # noqa: BLE001
                        self.last_error = _msg(exc2)
                        raise CommError(f"{self.name or self.kind}: {self.last_error}") from exc2
                self.writes += 1
                self.last_write_at = time.time()
                if not quiet:
                    self._trace("send", text, out, started)
                return out
            except CommError as exc:
                self._trace("send", text, {"error": str(exc)}, started, ok=False)
                raise

    def read(self, addresses: list[str], *, quiet: bool = False) -> dict[str, Any]:
        """讀一批。`quiet=True`：成功不進整合追蹤——觸發輪詢每秒幾十次，
        記下去只會把真正的命令沖出環形緩衝；失敗照樣記。"""
        started = time.perf_counter()
        with self._lock:
            try:
                out = self._read(addresses)
                if not quiet:
                    self._trace("read", addresses, out, started)
                return out
            except CommError as exc:
                self._trace("read", addresses, {"error": str(exc)}, started, ok=False)
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = _msg(exc)
                try:
                    self._close()
                    self._open()
                    out = self._read(addresses)
                    if not quiet:
                        self._trace("read", addresses, out, started)
                    return out
                except Exception as exc2:  # noqa: BLE001
                    self._trace("read", addresses, {"error": _msg(exc2)}, started, ok=False)
                    raise CommError(f"{self.name or self.kind}: {_msg(exc2)}") from exc2

    def close(self) -> None:
        with self._lock:
            self._close()

    def _trace(self, action: str, request: Any, result: Any, started: float, *, ok: bool = True) -> None:
        """把命令與結果記進整合追蹤（整合頁的「命令與結果」）；失敗永遠記，成功只在有人看時記。"""
        try:
            from apps.vision import trace

            items = request if isinstance(request, (list, dict)) else [request]
            summary = f"{action} {len(items)} entries: " + "、".join(f"{k}={v}" for k, v in list(items.items())[:4]) if isinstance(items, dict) else f"{action}：" + "、".join(str(x) for x in list(items)[:4])
            trace.record("modbus", summary, direction="out", name=self.name or self.kind, detail={"request": request, "result": result},
                         ok=ok, ms=(time.perf_counter() - started) * 1000)
        except Exception:  # noqa: BLE001 — 追蹤不能影響通訊
            pass

    def info(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "writes": self.writes, "errors": self.errors, "reconnects": self.reconnects,
            "last_error": self.last_error, "last_write_at": self.last_write_at,
        }


def _msg(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    return text[:300]


# ---------------------------------------------------------------------------
# Modbus/TCP
# ---------------------------------------------------------------------------
class ModbusTcpWriter(Writer):
    """config: host, port=502, unit_id=1, timeout_s=2, word_order=big|little"""

    kind = "modbus_tcp"
    label = "Modbus TCP client (connects to a device)"

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self.host = str(config.get("host") or "")
        if not self.host:
            raise ValidationError("modbus_tcp needs a host", code="comm_config")
        self.port = int(config.get("port", 502) or 502)
        self.unit_id = int(config.get("unit_id", 1) if config.get("unit_id") is not None else 1)
        self.word_order = "little" if str(config.get("word_order", "big")).lower() == "little" else "big"
        self.client = None
        self._open()

    def _open(self) -> None:
        from pymodbus.client import ModbusTcpClient

        self.client = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout, retries=0)
        if not self.client.connect():
            self.client.close()
            self.client = None
            raise CommError(f"Cannot reach {self.host}:{self.port}")

    def _close(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            finally:
                self.client = None

    def _client(self):
        if self.client is None:
            self._open()
        self.client.comm_params.timeout_connect = self.timeout
        return self.client

    @staticmethod
    def _check(rr, what: str) -> None:
        if rr is None or rr.isError():
            raise CommError(f"{what} failed: {rr}")

    def _write(self, values: dict[str, Any]) -> dict[str, Any]:
        from pymodbus.client import ModbusTcpClient

        client = self._client()
        written: dict[str, Any] = {}
        for address, raw in values.items():
            area, offset, dtype = parse_address(address)
            if area == "coil":
                value = coerce(raw, "bool")
                self._check(client.write_coil(offset, value, device_id=self.unit_id), f"write_coil {address}")
            elif area == "holding":
                value = coerce(raw, dtype)
                if dtype == "uint16":
                    regs = [max(0, min(0xFFFF, int(value)))]
                else:
                    regs = ModbusTcpClient.convert_to_registers(value, getattr(ModbusTcpClient.DATATYPE, dtype.upper()), word_order=self.word_order)
                if len(regs) == 1:
                    self._check(client.write_register(offset, regs[0], device_id=self.unit_id), f"write_register {address}")
                else:
                    self._check(client.write_registers(offset, regs, device_id=self.unit_id), f"write_registers {address}")
            else:
                raise CommError(f"Address '{address}' is in a read-only area")
            written[address] = value
        return {"written": len(written), "values": written}

    def _read(self, addresses: list[str]) -> dict[str, Any]:
        from pymodbus.client import ModbusTcpClient

        client = self._client()
        out: dict[str, Any] = {}
        for address in addresses:
            area, offset, dtype = parse_address(address)
            if area in ("coil", "discrete"):
                fn = client.read_coils if area == "coil" else client.read_discrete_inputs
                rr = fn(offset, count=1, device_id=self.unit_id)
                self._check(rr, f"read {address}")
                out[address] = bool(rr.bits[0])
            else:
                fn = client.read_holding_registers if area == "holding" else client.read_input_registers
                count = _DTYPE_WORDS[dtype]
                rr = fn(offset, count=count, device_id=self.unit_id)
                self._check(rr, f"read {address}")
                if dtype == "uint16":
                    out[address] = int(rr.registers[0])
                else:
                    out[address] = ModbusTcpClient.convert_from_registers(rr.registers, getattr(ModbusTcpClient.DATATYPE, dtype.upper()), word_order=self.word_order)
        return out

    def info(self) -> dict[str, Any]:
        return {**super().info(), "host": self.host, "port": self.port, "unit_id": self.unit_id, "connected": bool(self.client is not None and self.client.connected)}


#: Modbus 功能碼 → 位址區（pymodbus 的 datastore 以功能碼決定要動哪一區）
_READ_FC = {"coil": 1, "discrete": 2, "holding": 3, "input": 4}
_WRITE_FC = {"coil": 5, "discrete": 2, "holding": 16, "input": 4}


class ModbusServerWriter(Writer):
    """本平台當 **Modbus TCP 從站（server）**：對方（任何 Modbus TCP 主站）來讀寫我們的暫存器。

    config: host=0.0.0.0, port=5020, unit_id=1, size=512（每區的點數）, word_order=big|little
    - `write()` 把值寫進 datastore（主站下次讀就拿得到）；`read()` 讀 datastore（看主站寫了什麼）。
    - 伺服器跑在自己的執行緒與事件迴圈，跨執行緒存取一律走 `run_coroutine_threadsafe`。
    - 不佔用引擎的執行緒池；一條連線一個埠。
    """

    kind = "modbus_server"
    label = "Modbus/TCP server (this machine listens)"
    listens = True
    fields = ["host", "port", "unit_id", "size", "word_order", "trigger_address", "trigger_flow", "trigger_interval_ms", "trigger_mode", "trigger_clear", "trigger_done_address"]

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self.host = str(config.get("host") or "0.0.0.0")
        self.port = int(config.get("port", 5020) or 5020)
        self.unit_id = int(config.get("unit_id", 1) if config.get("unit_id") is not None else 1)
        self.size = max(8, min(65536, int(config.get("size", 512) or 512)))
        self.word_order = "little" if str(config.get("word_order", "big")).lower() == "little" else "big"
        self.server = None
        self.loop = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error = ""
        self.requests = 0
        self.connections = 0
        self._open()

    # -- 伺服器生命週期 -----------------------------------------------------
    def _open(self) -> None:
        if self.server is not None:
            return
        self._ready.clear()
        self._error = ""
        self._thread = threading.Thread(target=self._serve, name=f"modbus-server-{self.port}", daemon=True)
        self._thread.start()
        if not self._ready.wait(5.0) or self.server is None:
            reason = self._error or "timeout"
            raise CommError(f"The Modbus server could not start on {self.host}:{self.port} ({reason}); check that no other program holds that port")

    def _serve(self) -> None:
        import asyncio

        async def main() -> None:
            from pymodbus.server import ModbusTcpServer
            from pymodbus.simulator import DataType, SimData, SimDevice

            bits = [SimData(0, count=self.size, values=False, datatype=DataType.BITS)]
            regs = [SimData(0, count=self.size, values=0, datatype=DataType.UINT16)]
            device = SimDevice(self.unit_id, simdata=(bits, list(bits), regs, list(regs)))
            self.loop = asyncio.get_running_loop()
            self.server = ModbusTcpServer(device, address=(self.host, self.port), trace_pdu=self._trace_pdu, trace_connect=self._trace_connect)
            await self.server.serve_forever(background=True)
            self._ready.set()
            await self.server.serving

        try:
            asyncio.run(main())
        except Exception as exc:  # noqa: BLE001
            self._error = _msg(exc)
            self.server = None
            log.warning("Modbus 從站 %s:%s 結束：%s", self.host, self.port, self._error)
        finally:
            self._ready.set()

    def _trace_pdu(self, sending: bool, pdu):  # noqa: ANN001 — pymodbus 的回呼
        """主站的每一則請求／我們的回應都記進整合追蹤（整合頁「命令與結果」看得到）。"""
        try:
            if not sending:
                self.requests += 1
            from apps.vision import trace

            name = type(pdu).__name__.replace("Request", "").replace("Response", "")
            detail = {"function_code": getattr(pdu, "function_code", None), "address": getattr(pdu, "address", None)}
            for attr in ("count", "bits", "registers"):
                value = getattr(pdu, attr, None)
                if value not in (None, [], 0):
                    detail[attr] = value if not isinstance(value, list) else value[:16]
            trace.record("modbus", f"{"reply" if sending else "master request"} {name}", direction="out" if sending else "in", name=self.name or self.kind, detail=detail)
        except Exception:  # noqa: BLE001 — 追蹤失敗不能影響通訊
            pass
        return pdu

    def _trace_connect(self, connected: bool) -> None:  # noqa: FBT001
        try:
            self.connections += 1 if connected else 0
            from apps.vision import trace

            trace.record("modbus", "master connected" if connected else "master disconnected", name=self.name or self.kind, detail={"port": self.port})
        except Exception:  # noqa: BLE001
            pass

    def _close(self) -> None:
        import asyncio

        server, loop = self.server, self.loop
        self.server = None
        if server is not None and loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(server.shutdown(), loop).result(5)
            except Exception:  # noqa: BLE001
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.loop = None

    # -- datastore 存取（跨執行緒）------------------------------------------
    def _require(self):
        """伺服器已停（關閉或啟動失敗）時給明確錯誤，而不是 AttributeError。"""
        if self.server is None or self.loop is None:
            raise CommError(f"{self.name or self.kind}: the Modbus server is not running")
        return self.server

    def _call(self, coro):
        import asyncio

        if self.loop is None:
            raise CommError("The Modbus server is not running")
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(self.timeout or 2.0)

    def _write(self, values: dict[str, Any]) -> dict[str, Any]:
        from pymodbus.client import ModbusTcpClient

        server = self._require()
        written: dict[str, Any] = {}
        for address, raw in values.items():
            area, offset, dtype = parse_address(address)
            if area in ("coil", "discrete"):
                value = coerce(raw, "bool")
                self._call(server.async_setValues(self.unit_id, _WRITE_FC[area], offset, [bool(value)]))
            else:
                value = coerce(raw, dtype)
                if dtype == "uint16":
                    regs = [max(0, min(0xFFFF, int(value)))]
                else:
                    regs = ModbusTcpClient.convert_to_registers(value, getattr(ModbusTcpClient.DATATYPE, dtype.upper()), word_order=self.word_order)
                self._call(server.async_setValues(self.unit_id, _WRITE_FC[area], offset, [int(r) & 0xFFFF for r in regs]))
            written[address] = value
        return {"written": len(written), "values": written}

    def _read(self, addresses: list[str]) -> dict[str, Any]:
        from pymodbus.client import ModbusTcpClient

        server = self._require()
        out: dict[str, Any] = {}
        for address in addresses:
            area, offset, dtype = parse_address(address)
            if area in ("coil", "discrete"):
                got = self._call(server.async_getValues(self.unit_id, _READ_FC[area], offset, 1))
                out[address] = bool(got[0])
            else:
                count = _DTYPE_WORDS[dtype]
                got = self._call(server.async_getValues(self.unit_id, _READ_FC[area], offset, count))
                regs = [int(v) & 0xFFFF for v in got]
                out[address] = int(regs[0]) if dtype == "uint16" else ModbusTcpClient.convert_from_registers(regs, getattr(ModbusTcpClient.DATATYPE, dtype.upper()), word_order=self.word_order)
        return out

    def info(self) -> dict[str, Any]:
        return {
            **super().info(), "host": self.host, "port": self.port, "unit_id": self.unit_id, "size": self.size,
            "listening": bool(self.server is not None), "requests": self.requests, "role": "server",
        }


# ---------------------------------------------------------------------------
# TCP 文字／JSON
# ---------------------------------------------------------------------------
class _Missing(dict):
    def __missing__(self, key: str) -> str:
        return ""


class TcpClientWriter(Writer):
    """把結果以一行文字送到上位機（長連線）。

    config: host, port, timeout_s=2, template="RESULT {judge} {width_px}\\n"（有 template 就套格式，
    否則整包 JSON 一行）、newline="\\n"（template 沒以換行結尾時補上）、encoding="utf-8"、
    wait_reply=false（true 則等對方回一行，放進結果 reply）。
    """

    kind = "tcp_client"
    texts = True

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self.host = str(config.get("host") or "")
        self.port = int(config.get("port", 0) or 0)
        if not self.host or not self.port:
            raise ValidationError("tcp_client needs a host and a port", code="comm_config")
        self.template = str(config.get("template") or "")
        self.newline = str(config.get("newline", "\n") if config.get("newline") is not None else "\n")
        self.encoding = str(config.get("encoding") or "utf-8")
        self.wait_reply = bool(config.get("wait_reply", False))
        self.sock: socket.socket | None = None
        self.last_payload = ""
        self._open()

    def _open(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            # 這是主動連出去的連線：對方（上位機的接收程式）要先開著在聽，平台才連得上。
            raise CommError(f"Nothing is listening at {self.host}:{self.port} ({exc}). The platform connects out to the host program, so start the receiver first") from exc
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock = sock

    def _close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def render(self, values: dict[str, Any]) -> str:
        if self.template:
            text = self.template.format_map(_Missing(values))
        else:
            text = json.dumps(values, ensure_ascii=False, default=str)
        if self.newline and not text.endswith(self.newline):
            text += self.newline
        return text

    def _write(self, values: dict[str, Any]) -> dict[str, Any]:
        if self.sock is None:
            self._open()
        payload = self.render(values)
        self.sock.settimeout(self.timeout)
        self.sock.sendall(payload.encode(self.encoding))
        self.last_payload = payload
        out: dict[str, Any] = {"written": len(values), "payload": payload}
        if self.wait_reply:
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise CommError("The other side closed the connection before replying")
                buf += chunk
            out["reply"] = buf.decode(self.encoding, errors="replace").strip()
        return out

    def _send_text(self, text: str) -> dict[str, Any]:
        """原樣送出（事件、心跳與規則回覆）；沒有結尾字元時補上，設備才切得出一行。"""
        if self.sock is None:
            self._open()
        payload = text if not self.newline or text.endswith(self.newline) else text + self.newline
        self.sock.settimeout(self.timeout)
        self.sock.sendall(payload.encode(self.encoding, errors="replace"))
        self.last_payload = payload
        return {"sent": len(payload), "payload": payload}

    def _read(self, addresses: list[str]) -> dict[str, Any]:
        raise CommError("tcp_client cannot read back")

    def info(self) -> dict[str, Any]:
        return {**super().info(), "host": self.host, "port": self.port, "connected": self.sock is not None, "template": self.template, "last_payload": self.last_payload}


# ---------------------------------------------------------------------------
# 位元組串流（串口／UDP／TCP server）
# ---------------------------------------------------------------------------
STREAM_ENCODINGS = ("utf-8", "ascii", "latin-1", "hex")
STREAM_ENDINGS = {"\\n": "\n", "\n": "\n", "\\r": "\r", "\r": "\r", "\\r\\n": "\r\n", "\r\n": "\r\n"}
STREAM_FIELDS = ["timeout_s", "end_char", "end_custom", "encoding"]
STREAM_BUFFER_LIMIT = 64 * 1024


def _hex_bytes(text: str) -> bytes:
    raw = "".join(str(text or "").split())
    if len(raw) % 2:
        raise CommError("Hex payloads need an even number of digits")
    try:
        return bytes.fromhex(raw)
    except ValueError as exc:
        raise CommError("Hex payloads can only contain 0-9 and A-F") from exc


CR = bytes([13])  # 行尾的 CR；設備常送 CRLF 而設定只寫 LF


class StreamWriter(Writer):
    """共用的位元組串流連線；子類只負責開關連線與收送 bytes。"""

    texts = True
    section = "devices"

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self.template = str(config.get("template") or "")
        raw_end = str(config.get("end_char") or "\\n")
        if raw_end == "custom":
            raw_end = str(config.get("end_custom") or "")
        self.end = self._decode_end(raw_end)
        self.end_bytes = self.end.encode("latin-1", errors="replace")
        self.encoding = str(config.get("encoding") or "utf-8").lower()
        if self.encoding not in STREAM_ENCODINGS:
            raise ValidationError(f"encoding must be one of {', '.join(STREAM_ENCODINGS)}", code="comm_config")
        self._closed = threading.Event()
        self._connected = False
        self._rx_thread: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self.bytes_sent = 0
        self.bytes_received = 0
        self.lines_received = 0
        self.last_payload = ""
        self.last_line = ""
        self._buffer_warnings = 0
        #: 緩衝爆掉之後，丟到下一個結尾字元為止再重新收行（不然殘餘會污染下一行）。
        self._resyncing = False

    @staticmethod
    def _decode_end(text: str) -> str:
        from apps.comm.protocol import unescape

        out = unescape(text)
        return out if out else "\n"

    def _start_stream(self) -> None:
        self._open()
        self._connected = True
        if self._receives():
            self._rx_thread = threading.Thread(target=self._receive_loop, name=f"stream-writer-{self.name or self.kind}", daemon=True)
            self._rx_thread.start()

    def _receives(self) -> bool:
        return True

    @classmethod
    def receives_config(cls, config: dict[str, Any]) -> bool:
        return True

    def _send_bytes(self, data: bytes) -> Any:
        raise NotImplementedError

    def _recv_bytes(self) -> bytes:
        raise NotImplementedError

    def _require(self) -> None:
        if self._closed.is_set():
            raise CommError(f"{self.name or self.kind}: the connection is closed")
        if not self._connected:
            raise CommError(f"{self.name or self.kind}: the connection is not open")

    def _payload_bytes(self, text: str) -> bytes:
        if self.encoding != "hex":
            return text.encode(self.encoding, errors="replace")
        body = text
        ended = bool(self.end and body.endswith(self.end))
        if ended:
            body = body[: -len(self.end)]
        return _hex_bytes(body) + (self.end_bytes if ended else b"")

    def _line_text(self, data: bytes) -> str:
        if self.encoding == "hex":
            return data.hex().upper()
        return data.decode(self.encoding, errors="replace")

    def _with_end(self, text: str) -> str:
        return text if not self.end or text.endswith(self.end) else text + self.end

    def render(self, values: dict[str, Any]) -> str:
        if self.template:
            text = self.template.format_map(_Missing(values))
        else:
            text = json.dumps(values, ensure_ascii=False, default=str)
        return self._with_end(text)

    def _send_payload(self, text: str) -> dict[str, Any]:
        payload = self._with_end(text)
        data = self._payload_bytes(payload)
        with self._send_lock:
            self._require()
            try:
                self._send_bytes(data)
            except Exception as exc:  # noqa: BLE001
                self._mark_disconnected(exc)
                raise CommError(f"{self.name or self.kind}: {_msg(exc)}") from exc
        self.bytes_sent += len(data)
        self.last_payload = payload
        return {"sent": len(payload), "bytes": len(data), "payload": payload}

    def write(self, values: dict[str, Any], *, timeout: float | None = None, quiet: bool = False) -> dict[str, Any]:
        if not values:
            return {"written": 0}
        started = time.perf_counter()
        old = self.timeout
        if timeout:
            self.timeout = float(timeout)
        try:
            out = {"written": len(values), **self._send_payload(self.render(values))}
            self.writes += 1
            self.last_write_at = time.time()
            if not quiet:
                self._trace("write", values, out, started)
            return out
        except CommError as exc:
            self.errors += 1
            self.last_error = _msg(exc)
            self._trace("write", values, {"error": str(exc)}, started, ok=False)
            raise
        finally:
            self.timeout = old

    def send_text(self, text: str, *, quiet: bool = False) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            out = self._send_payload(text)
            self.writes += 1
            self.last_write_at = time.time()
            if not quiet:
                self._trace("send", text, out, started)
            return out
        except CommError as exc:
            self.errors += 1
            self.last_error = _msg(exc)
            self._trace("send", text, {"error": str(exc)}, started, ok=False)
            raise

    def _write(self, values: dict[str, Any]) -> dict[str, Any]:
        return {"written": len(values), **self._send_payload(self.render(values))}

    def _send_text(self, text: str) -> dict[str, Any]:
        return self._send_payload(text)

    def _read(self, addresses: list[str]) -> dict[str, Any]:
        raise CommError(f"{self.kind} cannot read back")

    def _mark_disconnected(self, exc: BaseException | str) -> None:
        self.last_error = _msg(exc) if isinstance(exc, BaseException) else str(exc)[:300]
        self._connected = False
        try:
            self._close()
        except Exception:  # noqa: BLE001
            pass

    def _receive_loop(self) -> None:
        buf = bytearray()
        backoff = 0.5
        while not self._closed.is_set():
            if not self._connected:
                if self._closed.wait(backoff):
                    return
                try:
                    self._open()
                    self._connected = True
                    self.reconnects += 1
                    self.last_error = ""
                    backoff = 0.5
                except Exception as exc:  # noqa: BLE001
                    self.last_error = _msg(exc)
                    backoff = min(30.0, backoff * 2)
                continue
            try:
                chunk = self._recv_bytes()
            except Exception as exc:  # noqa: BLE001
                if not self._closed.is_set():
                    self.errors += 1
                    self._mark_disconnected(exc)
                continue
            if not chunk:
                continue
            self.bytes_received += len(chunk)
            buf.extend(chunk)
            if self._resyncing:
                # 還在丟棄爆掉那一行的殘餘：找到結尾字元才重新開始收。
                cut = bytes(buf).find(self.end_bytes) if self.end_bytes else -1
                if cut < 0:
                    if len(buf) > STREAM_BUFFER_LIMIT:
                        buf.clear()
                    continue
                buf = bytearray(buf[cut + len(self.end_bytes):])
                self._resyncing = False
            if len(buf) > STREAM_BUFFER_LIMIT:
                self._buffer_warnings += 1
                buf.clear()
                self._resyncing = bool(self.end_bytes)
                self._trace_in("input buffer exceeded 64 KB; dropped pending bytes", ok=False, detail={"bytes": STREAM_BUFFER_LIMIT})
                continue
            while self.end_bytes and self.end_bytes in buf:
                line, _, rest = bytes(buf).partition(self.end_bytes)
                buf = bytearray(rest)
                # 設定成 LF 但設備照樣送 CRLF 是現場常態：行尾多出來的 CR 是框線不是內容，去掉。
                if line.endswith(CR) and CR not in self.end_bytes:
                    line = line[:-1]
                self._on_line(self._line_text(line))

    def _trace_in(self, summary: str, *, ok: bool = True, detail: Any = None) -> None:
        try:
            from apps.vision import trace

            trace.record("modbus", summary, direction="in", name=self.name or self.kind, detail=detail, ok=ok, force=not ok)
        except Exception:  # noqa: BLE001
            pass

    def _on_line(self, line: str) -> None:
        self.lines_received += 1
        self.last_line = line[:200]
        self._trace_in(line, detail={"line": line})
        try:
            from apps.vision.tcp_server import match_rules

            matched = match_rules(line)
        except Exception as exc:  # noqa: BLE001
            self._trace_in(f"rule failed: {_msg(exc)}", ok=False, detail={"line": line})
            return
        if matched is None:
            return
        reply = matched.get("_raw") if isinstance(matched, dict) else None
        if reply is None:
            reply = json.dumps(matched, ensure_ascii=False, default=str)
        try:
            self.send_text(str(reply), quiet=True)
        except CommError:
            pass

    def close(self) -> None:
        self._closed.set()
        try:
            self._close()
        finally:
            self._connected = False
        if self._rx_thread is not None:
            self._rx_thread.join(timeout=2.0)
            self._rx_thread = None

    def info(self) -> dict[str, Any]:
        return {
            **super().info(), "connected": self._connected, "bytes_sent": self.bytes_sent, "bytes_received": self.bytes_received,
            "lines_received": self.lines_received, "last_line": self.last_line, "last_payload": self.last_payload,
            "encoding": self.encoding, "end_char": self.end,
        }


class SerialStreamWriter(StreamWriter):
    kind = "serial"
    label = "Serial text device"
    description = "Sends and receives line-based text or hex bytes over a serial port."
    fields = ["port", "baudrate", "bytesize", "parity", "stopbits", *STREAM_FIELDS]

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self.port = str(config.get("port") or "").strip()
        if not self.port:
            raise ValidationError("serial needs a port", code="comm_config")
        self.baudrate = int(config.get("baudrate", 9600) or 9600)
        self.bytesize = int(config.get("bytesize", 8) or 8)
        self.parity = str(config.get("parity") or "N").upper()[:1]
        self.stopbits = float(config.get("stopbits", 1) or 1)
        self.serial = None
        self._start_stream()

    def _open(self) -> None:
        try:
            import serial
        except ImportError as exc:
            raise CommError("Serial support is not installed; run pip install pyserial") from exc
        self.serial = serial.serial_for_url(
            self.port, baudrate=self.baudrate, bytesize=self.bytesize, parity=self.parity, stopbits=self.stopbits,
            timeout=0.1, write_timeout=self.timeout,
        )

    def _close(self) -> None:
        if self.serial is not None:
            try:
                self.serial.close()
            finally:
                self.serial = None

    def _send_bytes(self, data: bytes) -> Any:
        if self.serial is None:
            raise CommError("The serial port is not open")
        self.serial.write(data)
        self.serial.flush()

    def _recv_bytes(self) -> bytes:
        if self.serial is None:
            raise CommError("The serial port is not open")
        return bytes(self.serial.read(4096))

    def info(self) -> dict[str, Any]:
        return {**super().info(), "port": self.port, "baudrate": self.baudrate, "bytesize": self.bytesize, "parity": self.parity, "stopbits": self.stopbits}


class UdpStreamWriter(StreamWriter):
    kind = "udp"
    label = "UDP text device"
    description = "Sends line-based text or hex bytes to a UDP endpoint, and can listen on a local port for received lines."
    fields = ["host", "port", "bind_port", *STREAM_FIELDS]

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self.host = str(config.get("host") or "").strip()
        self.port = int(config.get("port", 0) or 0)
        self.bind_port = int(config.get("bind_port", 0) or 0)
        if not self.host or not self.port:
            raise ValidationError("udp needs a host and a port", code="comm_config")
        self.sock: socket.socket | None = None
        self._start_stream()

    def _receives(self) -> bool:
        return self.bind_port > 0

    @classmethod
    def receives_config(cls, config: dict[str, Any]) -> bool:
        try:
            return int(config.get("bind_port", 0) or 0) > 0
        except (TypeError, ValueError):
            return False

    def _open(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.2)
        if self.bind_port > 0:
            sock.bind(("", self.bind_port))
        self.sock = sock

    def _close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _send_bytes(self, data: bytes) -> Any:
        if self.sock is None:
            raise CommError("The UDP socket is not open")
        self.sock.sendto(data, (self.host, self.port))

    def _recv_bytes(self) -> bytes:
        if self.sock is None:
            raise CommError("The UDP socket is not open")
        try:
            data, _peer = self.sock.recvfrom(65535)
            return data
        except socket.timeout:
            return b""

    def info(self) -> dict[str, Any]:
        return {**super().info(), "host": self.host, "port": self.port, "bind_port": self.bind_port, "listening": self.bind_port > 0}


class TcpServerTextWriter(StreamWriter):
    kind = "tcp_server_text"
    label = "TCP text device server"
    description = "Listens for devices that connect to this machine, then sends and receives line-based text or hex bytes."
    listens = True
    fields = ["host", "port", "max_clients", *STREAM_FIELDS]

    def __init__(self, config, **kw) -> None:
        self._clients: set[socket.socket] = set()
        self._clients_lock = threading.Lock()
        self._accept_thread: threading.Thread | None = None
        self._rx_queue: queue.Queue[bytes] = queue.Queue()
        super().__init__(config, **kw)
        self.host = str(config.get("host") or "0.0.0.0")
        self.port = int(config.get("port", 0) or 0)
        if not self.port:
            raise ValidationError("tcp_server_text needs a port", code="comm_config")
        self.max_clients = max(1, int(config.get("max_clients", 4) or 4))
        self.server: socket.socket | None = None
        self._start_stream()

    def _open(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(self.max_clients)
        srv.settimeout(0.5)
        self.server = srv
        self.port = int(srv.getsockname()[1])
        self._accept_thread = threading.Thread(target=self._accept_loop, name=f"tcp-device-{self.port}", daemon=True)
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        while not self._closed.is_set():
            srv = self.server
            if srv is None:
                return
            try:
                client, _peer = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._clients_lock:
                if len(self._clients) >= self.max_clients:
                    client.close()
                    continue
                self._clients.add(client)
            client.settimeout(0.5)
            threading.Thread(target=self._client_loop, args=(client,), name=f"tcp-device-client-{self.port}", daemon=True).start()

    def _client_loop(self, client: socket.socket) -> None:
        try:
            while not self._closed.is_set():
                try:
                    data = client.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    return
                self._rx_queue.put(data)
        except OSError:
            pass
        finally:
            with self._clients_lock:
                self._clients.discard(client)
            try:
                client.close()
            except OSError:
                pass

    def _close(self) -> None:
        srv, self.server = self.server, None
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=1.0)
            self._accept_thread = None

    def _send_bytes(self, data: bytes) -> Any:
        with self._clients_lock:
            clients = list(self._clients)
        if not clients:
            raise CommError("No device is connected")
        dead: list[socket.socket] = []
        for client in clients:
            try:
                client.sendall(data)
            except OSError:
                dead.append(client)
        if dead:
            with self._clients_lock:
                for client in dead:
                    self._clients.discard(client)
            for client in dead:
                try:
                    client.close()
                except OSError:
                    pass
        if len(dead) == len(clients):
            raise CommError("All connected devices failed")

    def _recv_bytes(self) -> bytes:
        try:
            return self._rx_queue.get(timeout=0.2)
        except queue.Empty:
            return b""

    def info(self) -> dict[str, Any]:
        with self._clients_lock:
            clients = len(self._clients)
        return {**super().info(), "host": self.host, "port": self.port, "listening": self.server is not None, "clients": clients, "max_clients": self.max_clients}


LIGHT_PRESETS: dict[str, dict[str, Any]] = {
    "custom": {
        "brightness_template": "{channel},{value}",
        "on_template": "{channel},ON",
        "off_template": "{channel},OFF",
        "channels": 4,
        "value_max": 255,
    },
    "hikrobot_digital": {
        "brightness_template": "SL{channel_letter}{value:04d}#",
        "on_template": "SW{channel_letter}0001#",
        "off_template": "SW{channel_letter}0000#",
        "channels": 4,
        "value_max": 255,
        "end_char": "none",
        "baudrate": 115200,
    },
    "ccs_pd3": {
        "brightness_template": "@{channel0:02d}F{value:03d}{checksum}",
        "on_template": "@{channel0:02d}L1{checksum}",
        "off_template": "@{channel0:02d}L0{checksum}",
        "channels": 3,
        "value_max": 255,
        "end_char": "\\r\\n",
        "baudrate": 38400,
    },
    "ccs_pds": {
        "brightness_template": "@99F{value:03d}{checksum}",
        "on_template": "@99F{value_max:03d}{checksum}",
        "off_template": "@99F000{checksum}",
        "channels": 1,
        "value_max": 255,
        "end_char": "\\r\\n",
        "baudrate": 9600,
    },
    "cst_dps": {
        "brightness_template": "S{channel_letter}{value:04d}TC#",
        "on_template": "S{channel_letter}{value:04d}TC#",
        "off_template": "S{channel_letter}0000FC#",
        "channels": 4,
        "value_max": 999,
        "end_char": "none",
        "baudrate": 9600,
    },
}


class LightControllerWriter(StreamWriter):
    """光源控制器：用串口或 TCP 送一行可設定的 ASCII 命令。"""

    kind = "light"
    label = "Light controller"
    description = "Controls a machine-vision light controller over serial or TCP with configurable line templates for brightness, on and off commands."
    fields = [
        "transport", "preset", "host", "port", "baudrate", "bytesize", "parity", "stopbits",
        *STREAM_FIELDS, "channels", "value_max", "brightness_template", "on_template", "off_template", "strobe", "lead_time_ms",
    ]

    def __init__(self, config, **kw) -> None:
        cfg = self._apply_preset(dict(config or {}))
        super().__init__(cfg, **kw)
        raw_end = str(cfg.get("end_char", "\\n") if cfg.get("end_char") is not None else "\\n").strip().lower()
        if raw_end in ("", "none", "no", "false"):
            self.end = ""
            self.end_bytes = b""
        self.transport = str(cfg.get("transport") or "serial").lower()
        if self.transport not in ("serial", "tcp"):
            raise ValidationError("light transport must be serial or tcp", code="comm_config")
        self.preset = str(cfg.get("preset") or "custom")
        self.channels = max(1, min(64, int(cfg.get("channels", 4) or 4)))
        self.value_max = max(1, min(65535, int(cfg.get("value_max", 255) or 255)))
        self.brightness_template = str(cfg.get("brightness_template") or "{channel},{value}")
        self.on_template = str(cfg.get("on_template") or "")
        self.off_template = str(cfg.get("off_template") or "")
        self.strobe = str(cfg.get("strobe") or "steady")
        self.lead_time_ms = max(0, int(float(cfg.get("lead_time_ms", 0) or 0)))
        self.channel_values: dict[int, int] = {}
        self.last_command = ""
        self.serial = None
        self.sock: socket.socket | None = None
        self.host = str(cfg.get("host") or "").strip()
        self.port = str(cfg.get("port") or "").strip()
        self.tcp_port = 0
        self.baudrate = int(cfg.get("baudrate", 9600) or 9600)
        self.bytesize = int(cfg.get("bytesize", 8) or 8)
        self.parity = str(cfg.get("parity") or "N").upper()[:1]
        self.stopbits = float(cfg.get("stopbits", 1) or 1)
        if self.transport == "serial":
            if not self.port:
                raise ValidationError("light serial transport needs a port", code="comm_config")
        else:
            if not self.host or not self.port:
                raise ValidationError("light tcp transport needs a host and a port", code="comm_config")
            self.tcp_port = int(self.port)
        self._start_stream()

    @staticmethod
    def _apply_preset(config: dict[str, Any]) -> dict[str, Any]:
        preset = str(config.get("preset") or "custom")
        return {**LIGHT_PRESETS.get(preset, LIGHT_PRESETS["custom"]), **config}

    def _open(self) -> None:
        if self.transport == "serial":
            try:
                import serial
            except ImportError as exc:
                raise CommError("Serial support is not installed; run pip install pyserial") from exc
            self.serial = serial.serial_for_url(
                self.port, baudrate=self.baudrate, bytesize=self.bytesize, parity=self.parity, stopbits=self.stopbits,
                timeout=0.1, write_timeout=self.timeout,
            )
            return
        try:
            sock = socket.create_connection((self.host, self.tcp_port), timeout=self.timeout)
        except OSError as exc:
            raise CommError(f"Cannot reach {self.host}:{self.tcp_port} ({exc})") from exc
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(0.1)
        self.sock = sock

    def _close(self) -> None:
        if self.serial is not None:
            try:
                self.serial.close()
            finally:
                self.serial = None
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _send_bytes(self, data: bytes) -> Any:
        if self.transport == "serial":
            if self.serial is None:
                raise CommError("The serial port is not open")
            self.serial.write(data)
            self.serial.flush()
            return
        if self.sock is None:
            raise CommError("The TCP socket is not open")
        self.sock.sendall(data)

    def _recv_bytes(self) -> bytes:
        if self.transport == "serial":
            if self.serial is None:
                raise CommError("The serial port is not open")
            return bytes(self.serial.read(4096))
        if self.sock is None:
            raise CommError("The TCP socket is not open")
        try:
            data = self.sock.recv(4096)
        except socket.timeout:
            return b""
        if not data:
            raise CommError("The light controller closed the TCP connection")
        return data

    @staticmethod
    def _channel_letter(channel: int) -> str:
        return chr(ord("A") + channel - 1) if 1 <= channel <= 26 else str(channel)

    def _values(self, channel: int, value: int) -> dict[str, Any]:
        return {
            "channel": channel, "channel0": channel - 1, "channel_letter": self._channel_letter(channel),
            "value": value, "value_max": self.value_max, "strobe": self.strobe, "lead_time_ms": self.lead_time_ms,
        }

    def _render_template(self, template: str, channel: int, value: int) -> str:
        from apps.comm.protocol import unescape

        marker = "\u0000CHECKSUM\u0000"
        values = self._values(channel, value)
        values["checksum"] = marker
        try:
            rendered = unescape(template).format_map(_Missing(values))
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            raise CommError(f"The light command template could not be filled in: {exc}") from None
        if marker in rendered:
            before = rendered.split(marker, 1)[0]
            enc = self.encoding if self.encoding != "hex" else "ascii"
            rendered = rendered.replace(marker, f"{sum(before.encode(enc, errors='replace')) & 0xFF:02X}")
        return rendered

    def render_light(self, channel: int | str, value: Any = None, mode: str = "brightness") -> str:
        try:
            ch = int(channel)
        except (TypeError, ValueError):
            raise CommError(f"Light channel must be an integer: {channel!r}") from None
        if ch < 1 or ch > self.channels:
            raise CommError(f"Light channel {ch} is outside 1..{self.channels}")
        try:
            level = int(round(float(self.value_max if value is None else value)))
        except (TypeError, ValueError):
            raise CommError(f"Light value must be a number: {value!r}") from None
        if level < 0 or level > self.value_max:
            raise CommError(f"Light value {level} is outside 0..{self.value_max}")
        mode = str(mode or "brightness").lower()
        if mode == "off":
            template = self.off_template or self.brightness_template
            level = 0
        elif mode == "on":
            template = self.on_template or self.brightness_template
            level = self.channel_values.get(ch, level or self.value_max)
        elif mode == "brightness":
            template = self.brightness_template
        else:
            raise CommError("Light mode must be brightness, on or off")
        if not template:
            raise CommError(f"No light command template is configured for mode {mode}")
        return self._render_template(template, ch, level)

    def set_light(self, channel: int | str, value: Any = None, mode: str = "brightness", *, timeout: float | None = None,
                  quiet: bool = False) -> dict[str, Any]:
        started = time.perf_counter()
        old = self.timeout
        if timeout:
            self.timeout = float(timeout)
        request = {"channel": channel, "value": value, "mode": mode}
        try:
            command = self.render_light(channel, value, mode)
            out = self._send_payload(command)
            ch = int(channel)
            mode_key = str(mode or "brightness").lower()
            if mode_key == "off":
                self.channel_values[ch] = 0
            elif mode_key == "on":
                self.channel_values[ch] = int(round(float(value))) if value is not None else self.channel_values.get(ch, self.value_max)
            elif value is not None:
                self.channel_values[ch] = int(round(float(value)))
            self.last_command = command
            self.writes += 1
            self.last_write_at = time.time()
            result = {**out, "command": command, "channel": ch, "value": self.channel_values.get(ch, 0)}
            if not quiet:
                self._trace("light", request, result, started)
            return result
        except CommError as exc:
            self.errors += 1
            self.last_error = _msg(exc)
            self._trace("light", request, {"error": str(exc)}, started, ok=False)
            raise
        finally:
            self.timeout = old

    def write(self, values: dict[str, Any], *, timeout: float | None = None, quiet: bool = False) -> dict[str, Any]:
        if not values:
            return {"written": 0}
        written: dict[str, Any] = {}
        commands: list[str] = []
        for channel, raw in values.items():
            mode = "brightness"
            value = raw
            if isinstance(raw, str) and raw.strip().lower() in ("on", "off"):
                mode = raw.strip().lower()
                value = self.channel_values.get(int(channel), self.value_max)
            elif isinstance(raw, bool):
                mode = "on" if raw else "off"
                value = self.channel_values.get(int(channel), self.value_max)
            out = self.set_light(channel, value, mode, timeout=timeout, quiet=True)
            written[str(channel)] = out["value"]
            commands.append(str(out.get("command") or ""))
        result = {"written": len(written), "values": written, "commands": commands, "last_command": commands[-1] if commands else ""}
        if not quiet:
            self._trace("write", values, result, time.perf_counter())
        return result

    def info(self) -> dict[str, Any]:
        base = {
            **super().info(), "transport": self.transport, "preset": self.preset, "channels": self.channels,
            "value_max": self.value_max, "channel_values": dict(sorted(self.channel_values.items())),
            "last_command": self.last_command, "strobe": self.strobe, "lead_time_ms": self.lead_time_ms,
        }
        if self.transport == "serial":
            return {**base, "port": self.port, "baudrate": self.baudrate, "bytesize": self.bytesize, "parity": self.parity, "stopbits": self.stopbits}
        return {**base, "host": self.host, "port": self.tcp_port}


# ---------------------------------------------------------------------------
# TCP 傳圖：把影像推給上位機
# ---------------------------------------------------------------------------
#: 影格：MAGIC(4) + 版本(1) + 表頭長度(4, big-endian) + 影像長度(4, big-endian) + 表頭 JSON + 影像 bytes。
#: 表頭 JSON 帶 name／run_id／flow_id／node／width／height／channels／dtype／encoding／values；
#: 影像用 jpeg／png（標準檔案 bytes）或 raw（row-major、表頭有 shape 與 dtype）。
IMAGE_MAGIC = b"VSIM"
IMAGE_VERSION = 1
IMAGE_HEAD = struct.Struct(">4sBII")
IMAGE_ENCODINGS = ("jpeg", "png", "raw")


class TcpImageWriter(Writer):
    """把影像連同一小段 JSON 表頭推給上位機（長連線）。

    config: host, port, timeout_s=2, encoding=jpeg|png|raw, quality=85（jpeg）。
    `send_image()` 送影像；`write(values)` 送一個只有表頭、沒有影像的影格（值放在表頭的 values），
    所以同一條連線也能用 write_modbus 的對映表送純量。對方只要照 IMAGE_HEAD 讀四個欄位就能拆包。
    """

    kind = "tcp_image"
    section = "tcp"
    label = "TCP image push (a host system)"
    description = "Pushes the image of a flow step to a host program over one long-lived TCP connection: a fixed 13-byte prefix, a JSON header (size, encoding, run id, verdict and named outputs) and the image bytes as JPEG, PNG or raw pixels."
    fields = ["host", "port", "timeout_s", "encoding", "quality"]

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self.host = str(config.get("host") or "")
        self.port = int(config.get("port", 0) or 0)
        if not self.host or not self.port:
            raise ValidationError("tcp_image needs a host and a port", code="comm_config")
        self.encoding = str(config.get("encoding") or "jpeg").lower()
        if self.encoding not in IMAGE_ENCODINGS:
            raise ValidationError(f"encoding must be one of {', '.join(IMAGE_ENCODINGS)}", code="comm_config")
        self.quality = int(config.get("quality", 85) or 85)
        self.sock: socket.socket | None = None
        self.frames = 0
        self.bytes_sent = 0
        self.last_frame_bytes = 0
        self._open()

    def _open(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            # 這是主動連出去的連線：對方（上位機的接收程式）要先開著在聽，平台才連得上。
            raise CommError(f"Nothing is listening at {self.host}:{self.port} ({exc}). The platform connects out to the host program, so start the receiver first") from exc
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock = sock

    def _close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    # -- 影格 -------------------------------------------------------------
    def encode(self, image: np.ndarray, encoding: str | None = None, quality: int | None = None) -> tuple[bytes, dict[str, Any]]:
        """影像 → (bytes, 表頭欄位)。raw 送原始像素（不正規化）；jpeg／png 先把非 8 位元正規化。"""
        enc = (encoding or self.encoding).lower()
        if enc not in IMAGE_ENCODINGS:
            raise CommError(f"Unknown image encoding '{enc}'")
        meta: dict[str, Any] = {"width": int(image.shape[1]), "height": int(image.shape[0]),
                                "channels": int(image.shape[2]) if image.ndim == 3 else 1, "dtype": str(image.dtype), "encoding": enc}
        if enc == "raw":
            return np.ascontiguousarray(image).tobytes(), meta
        img = image
        if img.dtype != np.uint8:
            lo, hi = float(np.nanmin(img)), float(np.nanmax(img))
            scale = 255.0 / (hi - lo) if hi > lo else 1.0
            img = np.clip((img.astype(np.float32) - lo) * scale, 0, 255).astype(np.uint8)
        params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality or self.quality)] if enc == "jpeg" else []
        ok, buf = cv2.imencode(".jpg" if enc == "jpeg" else ".png", img, params)
        if not ok:
            raise CommError("Could not encode the image")
        return buf.tobytes(), meta

    @staticmethod
    def frame(header: dict[str, Any], payload: bytes = b"") -> bytes:
        head = json.dumps(header, ensure_ascii=False, default=str).encode("utf-8")
        return IMAGE_HEAD.pack(IMAGE_MAGIC, IMAGE_VERSION, len(head), len(payload)) + head + payload

    def _send(self, data: bytes) -> None:
        """送一個影格；第一次失敗關閉重開再試一次（上位機重啟後第一張不該就掉）。"""
        for attempt in (1, 2):
            try:
                if self.sock is None:
                    self._open()
                self.sock.settimeout(self.timeout)
                self.sock.sendall(data)
                return
            except (OSError, CommError) as exc:
                self._close()
                if attempt == 2:
                    raise CommError(f"Send failed: {exc}") from exc
                self.reconnects += 1

    def send_image(self, image: np.ndarray, header: dict[str, Any] | None = None, *, encoding: str | None = None,
                   quality: int | None = None, timeout: float | None = None) -> dict[str, Any]:
        """把一張影像推出去；回 {bytes, encoding, width, height}。失敗拋 CommError（工具層決定要不要降級）。"""
        started = time.perf_counter()
        with self._lock:
            old = self.timeout
            if timeout:
                self.timeout = float(timeout)
            try:
                payload, meta = self.encode(image, encoding, quality)
                head = {**(header or {}), **meta, "name": (header or {}).get("name") or self.name}
                data = self.frame(head, payload)
                try:
                    self._send(data)
                except CommError as exc:
                    self.errors += 1
                    self.last_error = str(exc)
                    self._trace("send_image", {k: v for k, v in head.items() if k != "values"}, {"error": str(exc)}, started, ok=False)
                    raise
                self.writes += 1
                self.frames += 1
                self.bytes_sent += len(data)
                self.last_frame_bytes = len(payload)
                self.last_write_at = time.time()
                out = {"bytes": len(payload), "encoding": meta["encoding"], "width": meta["width"], "height": meta["height"]}
                self._trace("send_image", {k: v for k, v in head.items() if k != "values"}, out, started)
                return out
            finally:
                self.timeout = old

    def _write(self, values: dict[str, Any]) -> dict[str, Any]:
        self._send(self.frame({"name": self.name, "values": values}))
        return {"written": len(values)}

    def _read(self, addresses: list[str]) -> dict[str, Any]:
        raise CommError("tcp_image cannot read back")

    def info(self) -> dict[str, Any]:
        return {**super().info(), "host": self.host, "port": self.port, "connected": self.sock is not None,
                "encoding": self.encoding, "frames": self.frames, "bytes_sent": self.bytes_sent, "last_frame_bytes": self.last_frame_bytes}


# ---------------------------------------------------------------------------
# registry / 快取
# ---------------------------------------------------------------------------
_BUILTIN: dict[str, type[Writer]] = {
    "modbus_tcp": ModbusTcpWriter,
    "modbus_server": ModbusServerWriter,
    "tcp_client": TcpClientWriter,
    "tcp_image": TcpImageWriter,
    "serial": SerialStreamWriter,
    "udp": UdpStreamWriter,
    "tcp_server_text": TcpServerTextWriter,
    "light": LightControllerWriter,
}

#: 資料夾外掛註冊的 kind（apps.core.plugins 掛載）。
_PLUGIN_KINDS: dict[str, type[Writer]] = {}

_lock = threading.Lock()
#: connection_id → (updated_at iso, writer)
_open: dict[int, tuple[str, Writer]] = {}
#: 連線名稱 → writer（工具在熱路徑用；由 open_connection 維護）
_by_name: dict[str, Writer] = {}


def register_kind(cls: type[Writer]) -> bool:
    """註冊資料夾外掛的連線類別；kind 已存在（內建或先註冊者優先）回 False。"""
    kind = str(getattr(cls, "kind", "") or "")
    if not kind or kind in _BUILTIN:
        log.warning("連線外掛 %s 的 kind '%s' 無效或與內建重複，略過", cls.__name__, kind)
        return False
    if kind in _PLUGIN_KINDS:
        if _PLUGIN_KINDS[kind] is not cls:
            log.warning("連線 kind '%s' 已被 %s 註冊，略過 %s", kind, _PLUGIN_KINDS[kind].__name__, cls.__name__)
        return False
    _PLUGIN_KINDS[kind] = cls
    return True


def _resolve_class(kind: str, config: dict[str, Any]) -> type[Writer]:
    if kind in _BUILTIN:
        return _BUILTIN[kind]
    if kind in _PLUGIN_KINDS:
        return _PLUGIN_KINDS[kind]
    plugins = getattr(settings, "VISION", {}).get("COMM_PLUGINS", {})
    path = config.get("class") if kind == "plugin" else plugins.get(kind)
    if not path or ":" not in path:
        raise ValidationError(f"Unknown connection kind '{kind}'", code="unknown_connection_kind")
    module, cls = path.split(":", 1)
    return getattr(importlib.import_module(module), cls)


def open_connection(conn, *, force: bool = False) -> Writer:
    """依模型列建立（或取回快取的）writer。設定變更（updated_at 變）會重開。"""
    stamp = conn.updated_at.isoformat() if conn.updated_at else ""
    with _lock:
        cached = _open.get(conn.id)
        if cached and cached[0] == stamp and not force:
            _by_name[conn.name] = cached[1]
            return cached[1]
        if cached:
            _drop_locked(conn.id)
        cls = _resolve_class(conn.kind, conn.config or {})
        writer = cls(dict(conn.config or {}), connection_id=conn.id, name=conn.name)
        _open[conn.id] = (stamp, writer)
        _by_name[conn.name] = writer
    triggers.sync(conn.id, writer, conn.config or {})  # 有規則就開始輪詢（鎖外，迴圈會用到 writer）
    eventmod.sync(conn.id, writer, conn.config or {})  # 有選事件或開心跳就開始回報
    return writer


def _drop_locked(connection_id: int) -> None:
    triggers.stop(connection_id)
    eventmod.stop(connection_id)
    cached = _open.pop(connection_id, None)
    if not cached:
        return
    for name, w in list(_by_name.items()):
        if w is cached[1]:
            _by_name.pop(name, None)
    try:
        cached[1].close()
    except Exception:  # noqa: BLE001
        log.exception("關閉連線 %s 失敗", connection_id)


def close_connection(connection_id: int) -> None:
    with _lock:
        _drop_locked(connection_id)


def close_all() -> None:
    triggers.stop_all()
    eventmod.stop_all()
    with _lock:
        for cid in list(_open):
            _drop_locked(cid)
        _by_name.clear()


def get_writer(name: str) -> Writer | None:
    """熱路徑：純記憶體查詢，不碰資料庫。名稱或數字 id 皆可。"""
    key = str(name or "").strip()
    if not key:
        return None
    with _lock:
        w = _by_name.get(key)
        if w is None and key.isdigit():
            cached = _open.get(int(key))
            w = cached[1] if cached else None
        return w


def register_writer(name: str, writer: Writer) -> None:
    """把不是來自資料庫的 writer 放進名稱快取（測試、外掛程式化建立）。"""
    with _lock:
        _by_name[str(name)] = writer


def connection_info(conn) -> dict[str, Any]:
    with _lock:
        cached = _open.get(conn.id)
    trigger = triggers.status(conn.id)
    reporting = eventmod.status(conn.id)
    if not cached:
        # 從站開不起來（埠被別的程式佔走是最常見的）時，狀態要說得出原因——
        # 不然管理員只看到「未開啟」，PLC 連不上卻找不到頭緒。
        out = {"open": False}
        if _start_errors.get(conn.id):
            out["error"] = _start_errors[conn.id]
        if trigger:
            out["trigger"] = trigger
        if reporting:
            out["events"] = reporting
        return out
    try:
        info = {"open": True, **cached[1].info()}
    except Exception as exc:  # noqa: BLE001
        info = {"open": True, "error": str(exc)}
    if trigger:
        info["trigger"] = trigger
    if reporting:
        info["events"] = reporting
    return info


#: 自動啟動失敗的原因（連線 id → 訊息）；連線狀態會帶出來。
_start_errors: dict[int, str] = {}


def should_autostart(conn) -> bool:
    """從站要一直在聽、有觸發規則或事件回報的要開始跑——這種連線不能等第一次寫入才開。"""
    try:
        cls = _resolve_class(conn.kind, conn.config or {})
    except Exception:  # noqa: BLE001
        return False
    config = conn.config or {}
    receives = False
    try:
        receives = bool(cls.receives_config(config))
    except Exception:  # noqa: BLE001 - 設定壞掉不該擋住其他連線啟動
        receives = False
    return bool(conn.is_enabled and (getattr(cls, "listens", False) or receives or triggers.settings_of(config) or eventmod.settings_of(config)))


def ensure_started(conn) -> None:
    """建立／修改連線後呼叫：需要的話立刻開起來，失敗不擋 API（原因會出現在連線狀態）。"""
    if not should_autostart(conn):
        _start_errors.pop(conn.id, None)
        return
    try:
        open_connection(conn)
        _start_errors.pop(conn.id, None)
    except Exception as exc:  # noqa: BLE001 — 開不起來（埠被佔用最常見）不擋 API，但要說得出原因
        _start_errors[conn.id] = _msg(exc)
        log.warning("連線 %s 啟動失敗：%s", conn.name, exc)


def autostart() -> list[str]:
    """啟動時要自己活起來的連線：從站得一直在聽（PLC 隨時會連），有觸發設定的要開始輪詢。

    `manage.py serve` 在 TCP／擷取端之後呼叫。以前從站要等到有人在網頁按「測試」或流程跑過
    一次才開埠——伺服器重開後 PLC 就連不上，是從站模式最容易踩的坑。
    """
    from apps.comm.models import Connection

    started: list[str] = []
    for conn in Connection.objects.filter(is_enabled=True):
        if not should_autostart(conn):
            continue
        try:
            open_connection(conn)
            _start_errors.pop(conn.id, None)
            started.append(conn.name)
        except Exception as exc:  # noqa: BLE001 — 開不起來只記錄，其他連線照常
            _start_errors[conn.id] = _msg(exc)
            log.warning("連線 %s 自動啟動失敗：%s", conn.name, exc)
    if started:
        log.info("已自動啟動 %s 個連線：%s", len(started), "、".join(started))
    return started


def prefetch_connections(compiled) -> None:
    """Runner prefetch hook：找出圖裡用到的連線名稱，在呼叫者執行緒先開好。

    工具以 `Tool.connection_params` 宣告哪些參數是連線名稱（不再寫死工具 key——寫死的時候
    只有 write_modbus 被掃到，只讀不寫的流程會拿不到連線而靜默降級）。
    """
    names: set[str] = set()
    for cn in compiled.nodes.values():
        params = cn.node.get("params") or {}
        for key in getattr(cn.tool, "connection_params", ()):
            value = params.get(key)
            if value not in (None, ""):
                names.add(str(value).strip())
    if not names:
        return
    from django.db.models import Q

    from apps.comm.models import Connection

    ids = [int(n) for n in names if n.isdigit()]
    rows = Connection.objects.filter(Q(name__in=names) | Q(id__in=ids), is_enabled=True)
    for conn in rows:
        try:
            open_connection(conn)
        except Exception:  # noqa: BLE001 — 開不起來的連線在執行時由工具降級回報，不在這裡擋
            log.warning("連線 %s 預先開啟失敗", conn.name, exc_info=True)


def get_connection(connection_id: int):
    from apps.comm.models import Connection

    conn = Connection.objects.filter(pk=connection_id).first()
    if conn is None:
        raise NotFound("Connection not found", code="connection_not_found")
    return conn


#: 觸發規則表（`triggers` 是規則陣列，見 apps/comm/rules.py）；`trigger_interval_ms` 是整條連線的輪詢間隔。
#: 舊的扁平 `trigger_address`／`trigger_flow`… 仍讀得到（`rules.from_legacy`），但表單只給規則表。
TRIGGER_FIELDS = ["triggers", "trigger_interval_ms"]
#: 站台事件回報與心跳（見 apps/comm/events.py）。文字連線兩者都能用；
#: Modbus 只有心跳（把遞增的計數寫進一個位址，PLC 的看門狗就是這樣做的）。
EVENT_FIELDS = ["events", "event_template", "heartbeat_ms", "heartbeat_payload"]
MODBUS_EVENT_FIELDS = ["heartbeat_ms", "heartbeat_address"]
_MODBUS_MASTER_FIELDS = ["host", "port", "unit_id", "timeout_s", "word_order"]
_MODBUS_SLAVE_FIELDS = ["host", "port", "unit_id", "size", "word_order"]


#: 沒宣告 section 的外掛歸外掛頁——連線一定要有頁面管得到，不然只能改資料庫才刪得掉。
FALLBACK_SECTION = "plugins"


def kinds() -> list[dict[str, Any]]:
    plugins = getattr(settings, "VISION", {}).get("COMM_PLUGINS", {})
    out = [
        {"kind": "modbus_tcp", "section": "modbus-client", "label": "Modbus TCP client (connects to a device)", "fields": [*_MODBUS_MASTER_FIELDS, *TRIGGER_FIELDS, *MODBUS_EVENT_FIELDS],
         "description": "The platform is the client and connects to any Modbus TCP device — a controller, a drive, an I/O module, a host program — reading and writing its coils and registers. It can also poll one address as a trigger source."},
        {"kind": "modbus_server", "section": "modbus-server", "label": "Modbus TCP server (this machine listens)", "fields": [*_MODBUS_SLAVE_FIELDS, *TRIGGER_FIELDS, *MODBUS_EVENT_FIELDS],
         "description": "The platform is the server and listens on a port for any Modbus TCP master to read and write our registers; the flow writes its results there for the master to collect. With a trigger address configured, a flag written by the master runs the flow once. The port opens automatically when the server starts."},
        {"kind": "tcp_client", "section": "tcp", "label": "TCP text or JSON (a host system)", "fields": ["host", "port", "timeout_s", "template", "newline", "wait_reply", *EVENT_FIELDS]},
        {"kind": "tcp_image", "section": "tcp", "label": TcpImageWriter.label, "fields": list(TcpImageWriter.fields), "description": TcpImageWriter.description},
        {"kind": "serial", "section": "devices", "label": SerialStreamWriter.label, "fields": [*SerialStreamWriter.fields, *TRIGGER_FIELDS, *EVENT_FIELDS], "description": SerialStreamWriter.description},
        {"kind": "udp", "section": "devices", "label": UdpStreamWriter.label, "fields": [*UdpStreamWriter.fields, *TRIGGER_FIELDS, *EVENT_FIELDS], "description": UdpStreamWriter.description},
        {"kind": "tcp_server_text", "section": "devices", "label": TcpServerTextWriter.label, "fields": [*TcpServerTextWriter.fields, *TRIGGER_FIELDS, *EVENT_FIELDS], "description": TcpServerTextWriter.description},
        {"kind": "light", "section": "devices", "label": LightControllerWriter.label, "fields": list(LightControllerWriter.fields), "description": LightControllerWriter.description,
         "presets": {key: {k: v for k, v in value.items() if k != "baudrate"} for key, value in LIGHT_PRESETS.items()}},
    ]
    for kind, cls in _PLUGIN_KINDS.items():
        out.append({
            "kind": kind,
            "section": str(getattr(cls, "section", "") or FALLBACK_SECTION),
            "label": getattr(cls, "label", "") or f"Plugin: {kind}",
            "fields": list(getattr(cls, "fields", []) or []),
            "description": getattr(cls, "description", ""),
        })
    for kind in plugins:
        if kind not in _PLUGIN_KINDS:
            out.append({"kind": kind, "section": FALLBACK_SECTION, "label": f"Plugin: {kind}", "fields": []})
    out.append({"kind": "plugin", "section": FALLBACK_SECTION, "label": "Plugin (a class path of your own)", "fields": ["class"]})
    return out


__all__ = [
    "CommError", "Writer", "ModbusTcpWriter", "ModbusServerWriter", "TcpClientWriter", "TcpImageWriter", "IMAGE_HEAD", "IMAGE_MAGIC",
    "StreamWriter", "SerialStreamWriter", "UdpStreamWriter", "TcpServerTextWriter", "LightControllerWriter", "LIGHT_PRESETS",
    "parse_address", "coerce", "open_connection", "close_connection", "close_all", "get_writer", "register_writer", "register_kind",
    "connection_info", "prefetch_connections", "get_connection", "kinds",
]
