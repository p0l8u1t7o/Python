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
import socket
import struct
import threading
import time
from typing import Any

import cv2
import numpy as np
from django.conf import settings

from apps.comm import triggers
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
    #: 這種連線由哪個整合頁管理（`/integration/<section>`）；外掛沒宣告就歸到外掛頁。
    section = "plugins"

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

    def _close(self) -> None:
        pass

    # -- 公開介面 -----------------------------------------------------------
    def write(self, values: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        """寫一批；第一次失敗會關閉、重開連線再試一次，第二次失敗才拋 CommError。"""
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
                self._trace("write", values, out, started)
                return out
            except CommError as exc:
                self._trace("write", values, {"error": str(exc)}, started, ok=False)
                raise
            finally:
                self.timeout = old

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
            raise CommError(f"Cannot reach {self.host}:{self.port}: {exc}") from exc
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

    def _read(self, addresses: list[str]) -> dict[str, Any]:
        raise CommError("tcp_client cannot read back")

    def info(self) -> dict[str, Any]:
        return {**super().info(), "host": self.host, "port": self.port, "connected": self.sock is not None, "template": self.template, "last_payload": self.last_payload}


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
            raise CommError(f"Cannot reach {self.host}:{self.port}: {exc}") from exc
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
    triggers.sync(conn.id, writer, conn.config or {})  # 有設觸發位址就開始輪詢（鎖外，迴圈會用到 writer）
    return writer


def _drop_locked(connection_id: int) -> None:
    triggers.stop(connection_id)
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
    if not cached:
        # 從站開不起來（埠被別的程式佔走是最常見的）時，狀態要說得出原因——
        # 不然管理員只看到「未開啟」，PLC 連不上卻找不到頭緒。
        out = {"open": False}
        if _start_errors.get(conn.id):
            out["error"] = _start_errors[conn.id]
        if trigger:
            out["trigger"] = trigger
        return out
    try:
        info = {"open": True, **cached[1].info()}
    except Exception as exc:  # noqa: BLE001
        info = {"open": True, "error": str(exc)}
    if trigger:
        info["trigger"] = trigger
    return info


#: 自動啟動失敗的原因（連線 id → 訊息）；連線狀態會帶出來。
_start_errors: dict[int, str] = {}


def should_autostart(conn) -> bool:
    """從站要一直在聽、設了觸發位址的要開始輪詢——這種連線不能等第一次寫入才開。"""
    try:
        cls = _resolve_class(conn.kind, conn.config or {})
    except Exception:  # noqa: BLE001
        return False
    return bool(conn.is_enabled and (getattr(cls, "listens", False) or triggers.config_of(conn.config or {})))


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


#: 兩種 Modbus 連線共用的觸發設定（見 apps/comm/triggers.py）。
TRIGGER_FIELDS = ["trigger_address", "trigger_flow", "trigger_interval_ms", "trigger_mode", "trigger_clear", "trigger_done_address", "trigger_recipe"]
_MODBUS_MASTER_FIELDS = ["host", "port", "unit_id", "timeout_s", "word_order"]
_MODBUS_SLAVE_FIELDS = ["host", "port", "unit_id", "size", "word_order"]


#: 沒宣告 section 的外掛歸外掛頁——連線一定要有頁面管得到，不然只能改資料庫才刪得掉。
FALLBACK_SECTION = "plugins"


def kinds() -> list[dict[str, Any]]:
    plugins = getattr(settings, "VISION", {}).get("COMM_PLUGINS", {})
    out = [
        {"kind": "modbus_tcp", "section": "modbus-client", "label": "Modbus TCP client (connects to a device)", "fields": [*_MODBUS_MASTER_FIELDS, *TRIGGER_FIELDS],
         "description": "The platform is the client and connects to any Modbus TCP device — a controller, a drive, an I/O module, a host program — reading and writing its coils and registers. It can also poll one address as a trigger source."},
        {"kind": "modbus_server", "section": "modbus-server", "label": "Modbus TCP server (this machine listens)", "fields": [*_MODBUS_SLAVE_FIELDS, *TRIGGER_FIELDS],
         "description": "The platform is the server and listens on a port for any Modbus TCP master to read and write our registers; the flow writes its results there for the master to collect. With a trigger address configured, a flag written by the master runs the flow once. The port opens automatically when the server starts."},
        {"kind": "tcp_client", "section": "tcp", "label": "TCP text or JSON (a host system)", "fields": ["host", "port", "timeout_s", "template", "newline", "wait_reply"]},
        {"kind": "tcp_image", "section": "tcp", "label": TcpImageWriter.label, "fields": list(TcpImageWriter.fields), "description": TcpImageWriter.description},
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
    "parse_address", "coerce", "open_connection", "close_connection", "close_all", "get_writer", "register_writer", "register_kind",
    "connection_info", "prefetch_connections", "get_connection", "kinds",
]
