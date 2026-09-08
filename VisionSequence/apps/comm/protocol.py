"""把設備送來的一段文字或位元組拆成具名欄位，以及反過來組回去。

設備不會照平台的格式說話：條碼掃出來是 `LOT12345|2026-09-08|A7`、PLC 送來的是四個位元組的
大端整數、上位機丟的是 `ST01,RUN,12.34\\r\\n`。這個模組把「怎麼拆」寫成一份規格（純資料），
拆解與組裝都是純函式——所以流程裡的工具、連線上的規則、TCP 收到的一行都用同一套，
規格也能存進 `Connection.config` 之後由畫面編輯。

三種拆法（`mode`）：
  `delimiter`  依分隔字元切段，第 n 段給第 n 個欄位（最常見：逗號、Tab、直線）
  `fixed`      依位元組位置取（`start`／`end` 含兩端），配 `type` 與 `order` 轉型
  `regex`      正規表示式；有命名群組就用群組名，否則第 n 個群組給第 n 個欄位

欄位型別：string／int／float／bool／hex／bytes。整數與浮點可設 `scale`（PLC 常把 12.34 送成 1234，
`scale=0.01` 還原）與 `order`（ABCD 大端、DCBA 小端、BADC／CDAB 是字組交換的兩種，與 Modbus 同名）。

**拆不出來不丟例外**：欄位缺值就是 None，由呼叫的人決定要不要當失敗——產線上把一次讀壞
變成整條流程炸掉，比拿不到那個值糟糕得多。格式本身寫錯（欄位沒名字、位元組範圍顛倒）才丟
`ProtocolError`，那是設定階段就該修的。
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Any

MODES = ("delimiter", "fixed", "regex")
FIELD_TYPES = ("string", "int", "float", "bool", "hex", "bytes")
#: 位元組順序：與 Modbus 的說法一致。ABCD＝大端，DCBA＝小端，BADC／CDAB＝字組內外交換。
BYTE_ORDERS = ("ABCD", "BADC", "CDAB", "DCBA")
_TRUE = {"1", "true", "yes", "on", "ok", "t", "y"}
_FALSE = {"0", "false", "no", "off", "ng", "f", "n"}


class ProtocolError(ValueError):
    """規格本身有問題（設定階段就該修）；拆不出值不算，那會回 None。"""


@dataclass
class Field:
    """一個欄位怎麼取、怎麼轉型。

    `delimiter`／`regex` 用 `index`（第幾段／第幾個群組，0 起；regex 有命名群組時可省略）；
    `fixed` 用 `start`／`end`（位元組位置，含兩端）。
    """

    name: str
    type: str = "string"
    index: int | None = None
    start: int | None = None
    end: int | None = None
    order: str = "ABCD"
    #: 數值欄位讀出後乘上它（PLC 送 1234 表示 12.34 就設 0.01）
    scale: float = 1.0
    #: 取不到值時用這個（None＝留 None）
    default: Any = None

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip()
        if not self.name:
            raise ProtocolError("Every field needs a name")
        if self.type not in FIELD_TYPES:
            raise ProtocolError(f"Unknown field type '{self.type}' ({', '.join(FIELD_TYPES)})")
        if self.order not in BYTE_ORDERS:
            raise ProtocolError(f"Unknown byte order '{self.order}' ({', '.join(BYTE_ORDERS)})")
        if self.start is not None:
            self.start = int(self.start)
            self.end = int(self.end) if self.end is not None else self.start
            if self.start < 0 or self.end < self.start:
                raise ProtocolError(f"Field '{self.name}': the byte range {self.start}–{self.end} runs backwards")


@dataclass
class Spec:
    """一份拆解規格。`mode` 決定用哪一種拆法，其餘欄位只有該模式用得到。"""

    mode: str = "delimiter"
    fields: list[Field] = field(default_factory=list)
    #: delimiter：分隔字元（支援 \\t、\\r、\\n 這種寫法）
    separator: str = ","
    #: regex：樣式
    pattern: str = ""
    #: delimiter／regex：轉成文字時的編碼（收到 bytes 才用得到）
    encoding: str = "utf-8"
    #: delimiter：切段前後去空白
    strip: bool = True

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ProtocolError(f"Unknown mode '{self.mode}' ({', '.join(MODES)})")
        self.fields = [f if isinstance(f, Field) else Field(**f) for f in self.fields]
        if not self.fields:
            raise ProtocolError("A specification needs at least one field")
        names = [f.name for f in self.fields]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ProtocolError(f"Duplicate field names: {', '.join(dupes)}")
        if self.mode == "regex" and not str(self.pattern).strip():
            raise ProtocolError("The regex mode needs a pattern")
        if self.mode == "fixed" and any(f.start is None for f in self.fields):
            raise ProtocolError("Every field of a byte specification needs a start byte")


def spec_from(raw: Any) -> Spec:
    """dict（存在 Connection.config 或工具參數裡的樣子）→ Spec。"""
    if isinstance(raw, Spec):
        return raw
    if not isinstance(raw, dict):
        raise ProtocolError("The specification must be an object")
    known = {"mode", "fields", "separator", "pattern", "encoding", "strip"}
    return Spec(**{k: v for k, v in raw.items() if k in known})


def unescape(text: str) -> str:
    r"""把使用者在欄位裡打的 \r \n \t \0 轉成真的控制字元（樣板欄位也是這個規則）。"""
    out = str(text or "")
    for a, b in (("\\r", "\r"), ("\\n", "\n"), ("\\t", "\t"), ("\\0", "\0")):
        out = out.replace(a, b)
    return out


def as_bytes(payload: Any, encoding: str = "utf-8") -> bytes:
    """把手上的東西變成位元組：bytes 原樣、str 依編碼、其他先 str()。"""
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return bytes(payload)
    return str(payload if payload is not None else "").encode(encoding, errors="replace")


def as_text(payload: Any, encoding: str = "utf-8") -> str:
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return bytes(payload).decode(encoding, errors="replace")
    return str(payload if payload is not None else "")


def _reorder(raw: bytes, order: str) -> bytes:
    """把位元組換成大端順序再解。BADC／CDAB 需要成對的位元組。"""
    if order == "ABCD" or len(raw) < 2:
        return raw
    if order == "DCBA":
        return raw[::-1]
    if len(raw) % 2:
        return raw
    words = [raw[i : i + 2] for i in range(0, len(raw), 2)]
    if order == "BADC":  # 字組內交換
        return b"".join(w[::-1] for w in words)
    return b"".join(reversed(words))  # CDAB：字組順序交換


def decode_value(raw: bytes, kind: str, order: str = "ABCD", scale: float = 1.0, encoding: str = "utf-8") -> Any:
    """一段位元組 → Python 值。長度不合（例如 3 個位元組要當 int32）時回 None，不丟例外。"""
    if not raw:
        return None
    if kind == "bytes":
        return bytes(raw)
    if kind == "hex":
        return bytes(raw).hex().upper()
    if kind == "string":
        return raw.decode(encoding, errors="replace").strip("\x00").strip()
    ordered = _reorder(bytes(raw), order)
    if kind == "bool":
        return any(ordered)
    if kind == "float":
        fmt = {4: ">f", 8: ">d"}.get(len(ordered))
        if fmt is None:
            return None
        return struct.unpack(fmt, ordered)[0] * float(scale)
    if kind == "int":
        value = int.from_bytes(ordered, "big", signed=True)
        return value * scale if scale != 1.0 else value
    return None


def coerce_text(text: str, kind: str, scale: float = 1.0) -> Any:
    """一段文字 → Python 值。轉不動就回 None（設備偶爾送半行，不該讓流程炸掉）。"""
    text = text.strip()
    if kind in ("string", "hex", "bytes"):
        return text
    if not text:
        return None
    if kind == "bool":
        low = text.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        return None
    try:
        if kind == "int":
            value = int(text, 0)
            return value * scale if scale != 1.0 else value
        return float(text) * float(scale)
    except ValueError:
        return None


def parse(spec: Any, payload: Any) -> dict[str, Any]:
    """依規格把一段文字或位元組拆成 {欄位名: 值}。取不到的欄位是 None（或該欄位的 default）。"""
    s = spec_from(spec)
    if s.mode == "fixed":
        return _parse_fixed(s, as_bytes(payload, s.encoding))
    text = as_text(payload, s.encoding)
    return _parse_regex(s, text) if s.mode == "regex" else _parse_delimiter(s, text)


def _finish(s: Spec, values: dict[str, Any]) -> dict[str, Any]:
    return {f.name: (values.get(f.name) if values.get(f.name) is not None else f.default) for f in s.fields}


def _parse_delimiter(s: Spec, text: str) -> dict[str, Any]:
    sep = unescape(s.separator)
    parts = text.split(sep) if sep else [text]
    if s.strip:
        parts = [p.strip() for p in parts]
    out: dict[str, Any] = {}
    for i, f in enumerate(s.fields):
        idx = f.index if f.index is not None else i
        if 0 <= idx < len(parts):
            out[f.name] = coerce_text(parts[idx], f.type, f.scale)
    return _finish(s, out)


def _parse_regex(s: Spec, text: str) -> dict[str, Any]:
    try:
        rx = re.compile(s.pattern, re.S)
    except re.error as exc:
        raise ProtocolError(f"The pattern is not valid: {exc}") from None
    m = rx.search(text)
    if m is None:
        return _finish(s, {})
    named = m.groupdict()
    out: dict[str, Any] = {}
    for i, f in enumerate(s.fields):
        if f.name in named:
            piece = named[f.name]
        else:
            idx = (f.index if f.index is not None else i) + 1
            piece = m.group(idx) if idx <= m.re.groups else None
        if piece is not None:
            out[f.name] = coerce_text(piece, f.type, f.scale)
    return _finish(s, out)


def _parse_fixed(s: Spec, raw: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in s.fields:
        start, end = int(f.start or 0), int(f.end if f.end is not None else f.start or 0)
        if start >= len(raw):
            continue
        out[f.name] = decode_value(raw[start : end + 1], f.type, f.order, f.scale, s.encoding)
    return _finish(s, out)


def encode_value(value: Any, kind: str, size: int, order: str = "ABCD", scale: float = 1.0, encoding: str = "utf-8") -> bytes:
    """Python 值 → 固定長度的位元組（組回去用）。字串補 \\0、數值依 order 排位元組。"""
    if kind in ("bytes", "hex"):
        raw = bytes.fromhex(str(value)) if kind == "hex" and not isinstance(value, (bytes, bytearray)) else as_bytes(value, encoding)
        return raw[:size].ljust(size, b"\x00")
    if kind == "string":
        return as_bytes(value, encoding)[:size].ljust(size, b"\x00")
    if kind == "bool":
        return (b"\x01" if value else b"\x00").ljust(size, b"\x00")
    if kind == "float":
        fmt = {4: ">f", 8: ">d"}.get(size)
        if fmt is None:
            raise ProtocolError(f"A float needs 4 or 8 bytes, not {size}")
        return _reorder(struct.pack(fmt, float(value) / (float(scale) or 1.0)), order)
    number = int(round(float(value) / (float(scale) or 1.0)))
    try:
        return _reorder(number.to_bytes(size, "big", signed=number < 0), order)
    except OverflowError:
        raise ProtocolError(f"{number} does not fit in {size} bytes") from None


def pack(spec: Any, values: dict[str, Any]) -> bytes | str:
    """依規格把 {欄位名: 值} 組回去：`fixed` 回位元組，其餘回一行文字。"""
    s = spec_from(spec)
    if s.mode == "fixed":
        size = max((int(f.end or f.start or 0) + 1) for f in s.fields)
        buf = bytearray(size)
        for f in s.fields:
            start, end = int(f.start or 0), int(f.end if f.end is not None else f.start or 0)
            buf[start : end + 1] = encode_value(values.get(f.name, f.default), f.type, end - start + 1, f.order, f.scale, s.encoding)
        return bytes(buf)
    sep = unescape(s.separator)
    return sep.join("" if values.get(f.name, f.default) is None else str(values.get(f.name, f.default)) for f in s.fields)
