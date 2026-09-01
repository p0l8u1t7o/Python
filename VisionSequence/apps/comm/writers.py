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
import threading
import time
from typing import Any

from django.conf import settings

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
        raise CommError(f"位址格式錯誤：'{address}'（應為 area:offset[:dtype]）")
    area = _AREA_ALIASES.get(parts[0])
    if area is None:
        raise CommError(f"未知的位址區 '{parts[0]}'（coil / holding / discrete / input）")
    try:
        offset = int(parts[1], 0)
    except ValueError:
        raise CommError(f"位址偏移不是整數：'{parts[1]}'") from None
    if offset < 0 or offset > 0xFFFF:
        raise CommError(f"位址偏移超出範圍：{offset}")
    if area in ("coil", "discrete"):
        return area, offset, "bool"
    dtype = parts[2] if len(parts) > 2 and parts[2] else "uint16"
    if dtype not in _DTYPE_WORDS:
        raise CommError(f"未知的資料型別 '{dtype}'（{', '.join(_DTYPE_WORDS)}）")
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
        raise CommError(f"{self.kind} 不支援讀回")

    def _close(self) -> None:
        pass

    # -- 公開介面 -----------------------------------------------------------
    def write(self, values: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        """寫一批；第一次失敗會關閉、重開連線再試一次，第二次失敗才拋 CommError。"""
        if not values:
            return {"written": 0}
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
                        raise CommError(f"{self.name or self.kind}：{self.last_error}") from exc2
                self.writes += 1
                self.last_write_at = time.time()
                return out
            finally:
                self.timeout = old

    def read(self, addresses: list[str]) -> dict[str, Any]:
        with self._lock:
            try:
                return self._read(addresses)
            except CommError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = _msg(exc)
                try:
                    self._close()
                    self._open()
                    return self._read(addresses)
                except Exception as exc2:  # noqa: BLE001
                    raise CommError(f"{self.name or self.kind}：{_msg(exc2)}") from exc2

    def close(self) -> None:
        with self._lock:
            self._close()

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

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self.host = str(config.get("host") or "")
        if not self.host:
            raise ValidationError("modbus_tcp 需要 host", code="comm_config")
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
            raise CommError(f"連不上 {self.host}:{self.port}")

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
            raise CommError(f"{what} 失敗：{rr}")

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
                raise CommError(f"位址 '{address}' 是唯讀區，不能寫")
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
            raise ValidationError("tcp_client 需要 host 與 port", code="comm_config")
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
            raise CommError(f"連不上 {self.host}:{self.port}：{exc}") from exc
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
                    raise CommError("對方在回覆前關閉連線")
                buf += chunk
            out["reply"] = buf.decode(self.encoding, errors="replace").strip()
        return out

    def _read(self, addresses: list[str]) -> dict[str, Any]:
        raise CommError("tcp_client 不支援讀回")

    def info(self) -> dict[str, Any]:
        return {**super().info(), "host": self.host, "port": self.port, "connected": self.sock is not None, "template": self.template, "last_payload": self.last_payload}


# ---------------------------------------------------------------------------
# 模擬 DIO
# ---------------------------------------------------------------------------
class DioSimWriter(Writer):
    """只記錄狀態，供沒有設備的機器測流程。config.channels 有列時，寫到未宣告的通道算失敗。"""

    kind = "dio_sim"

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        channels = config.get("channels") or []
        if isinstance(channels, int):
            channels = [f"DO{i}" for i in range(channels)]
        self.channels = [str(c) for c in channels]
        self.state: dict[str, Any] = {c: 0 for c in self.channels}
        self.history: list[dict[str, Any]] = []

    def _write(self, values: dict[str, Any]) -> dict[str, Any]:
        if self.channels:
            unknown = [a for a in values if a not in self.channels]
            if unknown:
                raise CommError(f"未宣告的通道：{', '.join(unknown)}")
        for address, value in values.items():
            self.state[address] = value
        self.history.append({"at": time.time(), "values": dict(values)})
        if len(self.history) > 100:
            self.history = self.history[-100:]
        return {"written": len(values), "values": dict(values)}

    def _read(self, addresses: list[str]) -> dict[str, Any]:
        return {a: self.state.get(a) for a in addresses}

    def info(self) -> dict[str, Any]:
        return {**super().info(), "channels": self.channels, "state": dict(self.state)}


# ---------------------------------------------------------------------------
# registry / 快取
# ---------------------------------------------------------------------------
_BUILTIN: dict[str, type[Writer]] = {
    "modbus_tcp": ModbusTcpWriter,
    "tcp_client": TcpClientWriter,
    "dio_sim": DioSimWriter,
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
        raise ValidationError(f"未知的連線類型 '{kind}'", code="unknown_connection_kind")
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
        return writer


def _drop_locked(connection_id: int) -> None:
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
    if not cached:
        return {"open": False}
    try:
        return {"open": True, **cached[1].info()}
    except Exception as exc:  # noqa: BLE001
        return {"open": True, "error": str(exc)}


def prefetch_connections(compiled) -> None:
    """Runner prefetch hook：找出圖裡 write_modbus 用到的連線名稱，在呼叫者執行緒先開好。"""
    names: set[str] = set()
    for cn in compiled.nodes.values():
        if getattr(cn.tool, "key", "") != "write_modbus":
            continue
        value = (cn.node.get("params") or {}).get("connection")
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
        raise NotFound("連線不存在", code="connection_not_found")
    return conn


def kinds() -> list[dict[str, Any]]:
    plugins = getattr(settings, "VISION", {}).get("COMM_PLUGINS", {})
    out = [
        {"kind": "modbus_tcp", "label": "Modbus/TCP（線圈與暫存器）", "fields": ["host", "port", "unit_id", "timeout_s", "word_order"]},
        {"kind": "tcp_client", "label": "TCP 文字／JSON（上位機）", "fields": ["host", "port", "timeout_s", "template", "newline", "wait_reply"]},
        {"kind": "dio_sim", "label": "模擬 DIO（只記錄狀態）", "fields": ["channels"]},
    ]
    for kind, cls in _PLUGIN_KINDS.items():
        out.append({
            "kind": kind,
            "label": getattr(cls, "label", "") or f"外掛：{kind}",
            "fields": list(getattr(cls, "fields", []) or []),
            "description": getattr(cls, "description", ""),
        })
    for kind in plugins:
        if kind not in _PLUGIN_KINDS:
            out.append({"kind": kind, "label": f"外掛：{kind}", "fields": []})
    out.append({"kind": "plugin", "label": "外掛（自訂類別路徑）", "fields": ["class"]})
    return out


__all__ = [
    "CommError", "Writer", "ModbusTcpWriter", "TcpClientWriter", "DioSimWriter",
    "parse_address", "coerce", "open_connection", "close_connection", "close_all", "get_writer", "register_writer", "register_kind",
    "connection_info", "prefetch_connections", "get_connection", "kinds",
]
