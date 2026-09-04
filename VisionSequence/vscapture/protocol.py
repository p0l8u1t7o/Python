"""擷取端 ⇄ 伺服端的線上協定 v1（零依賴：struct／enum／dataclasses／json）。

伺服端（apps/vision/capture）與擷取端（vscapture）共用這一份定義；握手時比對 PROTOCOL_VERSION。

每則訊息 = ENVELOPE(16 B) | header(hlen) | payload(plen)，全部小端序：
    ENVELOPE = <H magic><B ver><B type><I req_id><I hlen><I plen>
控制訊息（HELLO／WELCOME／CHANNELS／SHM_*／STREAM／ERROR／TEST_RESULT）的 header 是 JSON；
熱路徑訊息（GRAB／FRAME／SLOT_FREE／TEST）的 header 是定長 struct，不做每影格 JSON。
req_id > 0 用來把回應對到請求（GRAB → FRAME／ERROR、STREAM → 回音、TEST → TEST_RESULT）；0 = 非請求。

同機共享記憶體：擷取端建立 SharedMemory（SEG_HDR 64 B ＋ K 個槽），FRAME 的 slot ≥ 0 代表像素在該槽（plen = 0），
伺服端 copy 完送 SLOT_FREE 把槽還給擷取端；擷取端絕不覆寫仍屬伺服端的槽。
"""

from __future__ import annotations

import json
import re
import socket
import struct
from dataclasses import dataclass
from enum import IntEnum, IntFlag
from typing import Any

PROTOCOL_VERSION = 1
MAGIC = 0x5643
HEARTBEAT_S = 5.0
HELLO_TIMEOUT_S = 5.0
MAX_CONTROL_BYTES = 1 << 20
MAX_CHANNELS = 32
SEG_MAGIC = b"VSCAP\0\0\0"
SEG_HEADER_BYTES = 64
SLOT_ALIGN = 4096

ENVELOPE = struct.Struct("<HBBIII")  # magic, ver, type, req_id, hlen, plen（16 B）
GRAB_HDR = struct.Struct("<HIQBB")  # chan, timeout_ms, min_seq, encoding, flags（16 B）
FRAME_HDR = struct.Struct("<HBBBBQQIIIIIIIIi6x")  # 64 B，欄位見 FrameHeader
SLOT_HDR = struct.Struct("<HiQ2x")  # chan, slot, seq（16 B）
SEG_HDR = struct.Struct("<8sQIIQ")  # magic, canary, slots, slot_bytes, reserved（32 B，補到 64）


class MsgType(IntEnum):
    HELLO = 0x01
    WELCOME = 0x02
    PING = 0x03
    PONG = 0x04
    CHANNELS = 0x05
    SHM_OFFER = 0x06
    SHM_ACCEPT = 0x07
    STREAM = 0x08
    ERROR = 0x09
    BYE = 0x0A
    TEST = 0x0B
    TEST_RESULT = 0x0C
    GRAB = 0x10
    FRAME = 0x11
    SLOT_FREE = 0x12


class Encoding(IntEnum):
    RAW = 0
    LZ4 = 1
    JPEG = 2
    AUTO = 255


class GrabFlags(IntFlag):
    NONE = 0
    AFTER_REQUEST = 1  # 影格必須在 GRAB 抵達之後才擷取（軟體觸發或等下一張）


class FrameFlags(IntFlag):
    NONE = 0
    FRESH = 1  # 這張是請求之後才擷取的
    CROPPED = 2  # ROI 不等於全幅


DTYPE_CODES = {"u8": 0, "u16": 1, "f32": 2}
DTYPE_NAMES = {v: k for k, v in DTYPE_CODES.items()}
NUMPY_DTYPES = {0: "uint8", 1: "uint16", 2: "float32"}
ITEMSIZE = {0: 1, 1: 2, 2: 4}
ENCODING_NAMES = {0: "raw", 1: "lz4", 2: "jpeg", 255: "auto"}
ENCODING_CODES = {v: k for k, v in ENCODING_NAMES.items()}
NAME_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,64}$")
CHANNEL_ID_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,32}$")
MODES = ("on_demand", "stream")


class ProtocolError(Exception):
    """封包格式或協定狀態錯誤；code 對應 ERROR 訊息的 code。"""

    def __init__(self, message: str, *, code: str = "malformed") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# 封包
# ---------------------------------------------------------------------------
def pack_envelope(mtype: int, req_id: int, hlen: int, plen: int) -> bytes:
    return ENVELOPE.pack(MAGIC, PROTOCOL_VERSION, int(mtype), int(req_id), int(hlen), int(plen))


def unpack_envelope(buf: bytes | bytearray | memoryview) -> tuple[int, int, int, int]:
    """回 (type, req_id, hlen, plen)；magic／版本不對拋 ProtocolError。"""
    if len(buf) < ENVELOPE.size:
        raise ProtocolError("封包表頭不足")
    magic, ver, mtype, req_id, hlen, plen = ENVELOPE.unpack_from(buf, 0)
    if magic != MAGIC:
        raise ProtocolError("封包 magic 錯誤")
    if ver != PROTOCOL_VERSION:
        raise ProtocolError(f"協定版本不支援：{ver}", code="protocol_unsupported")
    return int(mtype), int(req_id), int(hlen), int(plen)


def pack_message(mtype: int, req_id: int = 0, header: bytes = b"", payload: bytes | bytearray | memoryview = b"") -> bytes:
    return pack_envelope(mtype, req_id, len(header), len(payload)) + bytes(header) + bytes(payload)


def dumps_json(body: dict[str, Any]) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def loads_json(buf: bytes | bytearray | memoryview) -> dict[str, Any]:
    try:
        body = json.loads(bytes(buf).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"控制訊息不是 JSON：{exc}") from None
    if not isinstance(body, dict):
        raise ProtocolError("控制訊息必須是 JSON 物件")
    return body


def pack_json(mtype: int, body: dict[str, Any], req_id: int = 0) -> bytes:
    return pack_message(mtype, req_id, dumps_json(body))


def pack_grab(chan: int, min_seq: int, timeout_ms: int, encoding: int = Encoding.AUTO, flags: int = 0) -> bytes:
    return GRAB_HDR.pack(int(chan), int(timeout_ms), int(min_seq), int(encoding), int(flags))


def unpack_grab(buf: bytes | bytearray | memoryview) -> tuple[int, int, int, int, int]:
    if len(buf) < GRAB_HDR.size:
        raise ProtocolError("GRAB 表頭不足")
    chan, timeout_ms, min_seq, encoding, flags = GRAB_HDR.unpack_from(buf, 0)
    return int(chan), int(min_seq), int(timeout_ms), int(encoding), int(flags)


def pack_slot_free(chan: int, slot: int, seq: int) -> bytes:
    return SLOT_HDR.pack(int(chan), int(slot), int(seq))


def unpack_slot_free(buf: bytes | bytearray | memoryview) -> tuple[int, int, int]:
    if len(buf) < SLOT_HDR.size:
        raise ProtocolError("SLOT_FREE 表頭不足")
    chan, slot, seq = SLOT_HDR.unpack_from(buf, 0)
    return int(chan), int(slot), int(seq)


@dataclass(slots=True)
class FrameHeader:
    """FRAME／TEST 的定長表頭。slot == -1：像素在 payload；slot ≥ 0：像素在共享記憶體槽（plen 必須為 0、encoding raw）。"""

    chan: int
    encoding: int
    dtype: int
    channels: int
    flags: int
    seq: int
    ts_ns: int
    width: int
    height: int
    stride: int
    roi_x: int
    roi_y: int
    full_w: int
    full_h: int
    raw_len: int
    slot: int

    def pack(self) -> bytes:
        return FRAME_HDR.pack(self.chan, self.encoding, self.dtype, self.channels, self.flags, self.seq, self.ts_ns,
                              self.width, self.height, self.stride, self.roi_x, self.roi_y, self.full_w, self.full_h, self.raw_len, self.slot)

    @classmethod
    def unpack(cls, buf: bytes | bytearray | memoryview) -> FrameHeader:
        if len(buf) < FRAME_HDR.size:
            raise ProtocolError("FRAME 表頭不足")
        return cls(*[int(v) for v in FRAME_HDR.unpack_from(buf, 0)])

    @classmethod
    def for_image(cls, chan: int, seq: int, ts_ns: int, width: int, height: int, channels: int, dtype: int, *,
                  roi_x: int = 0, roi_y: int = 0, full_w: int | None = None, full_h: int | None = None,
                  encoding: int = Encoding.RAW, flags: int = 0, slot: int = -1) -> FrameHeader:
        itemsize = ITEMSIZE[int(dtype)]
        stride = int(width) * int(channels) * itemsize
        fw, fh = (int(full_w) if full_w else int(width)), (int(full_h) if full_h else int(height))
        if roi_x or roi_y or fw != width or fh != height:
            flags |= FrameFlags.CROPPED
        return cls(int(chan), int(encoding), int(dtype), int(channels), int(flags), int(seq), int(ts_ns), int(width), int(height),
                   stride, int(roi_x), int(roi_y), fw, fh, stride * int(height), int(slot))

    @property
    def itemsize(self) -> int:
        return ITEMSIZE.get(self.dtype, 0)

    def shape(self) -> tuple[int, ...]:
        return (self.height, self.width) if self.channels == 1 else (self.height, self.width, self.channels)

    @property
    def numpy_dtype(self) -> str:
        return NUMPY_DTYPES[self.dtype]

    def validate(self, n_channels: int, max_bytes: int, plen: int, *, shm_slots: int = 0, slot_bytes: int = 0) -> None:
        if not 0 <= self.chan < n_channels:
            raise ProtocolError(f"通道索引 {self.chan} 超出範圍", code="no_channel")
        if self.dtype not in ITEMSIZE:
            raise ProtocolError(f"未知的像素型別 {self.dtype}")
        if self.channels not in (1, 3, 4):
            raise ProtocolError(f"不支援的通道數 {self.channels}")
        if self.width <= 0 or self.height <= 0:
            raise ProtocolError("影像尺寸無效")
        if self.stride != self.width * self.channels * self.itemsize:
            raise ProtocolError("stride 與尺寸不符（v1 只接受連續影像）")
        if self.raw_len != self.stride * self.height:
            raise ProtocolError("raw_len 與尺寸不符")
        if self.raw_len > max_bytes:
            raise ProtocolError(f"影像 {self.raw_len} 位元組超過上限 {max_bytes}", code="too_large")
        if self.encoding not in (Encoding.RAW, Encoding.LZ4, Encoding.JPEG):
            raise ProtocolError(f"未知的編碼 {self.encoding}", code="unsupported_encoding")
        if self.slot >= 0:
            if plen != 0 or self.encoding != Encoding.RAW:
                raise ProtocolError("共享記憶體影格不得帶 payload 或壓縮")
            if shm_slots <= 0 or self.slot >= shm_slots:
                raise ProtocolError(f"共享記憶體槽 {self.slot} 無效")
            if self.raw_len > slot_bytes:
                raise ProtocolError("影像超過共享記憶體槽大小", code="too_large")
        else:
            if self.encoding == Encoding.RAW and plen != self.raw_len:
                raise ProtocolError("raw payload 長度與 raw_len 不符")
            if self.encoding != Encoding.RAW and plen <= 0:
                raise ProtocolError("壓縮影格缺少 payload")
            if plen > max_bytes:
                raise ProtocolError("payload 超過上限", code="too_large")


# ---------------------------------------------------------------------------
# 共享記憶體版面
# ---------------------------------------------------------------------------
def align_slot_bytes(n: int) -> int:
    return max(SLOT_ALIGN, ((int(n) + SLOT_ALIGN - 1) // SLOT_ALIGN) * SLOT_ALIGN)


def slot_offset(index: int, slot_bytes: int) -> int:
    return SEG_HEADER_BYTES + int(index) * int(slot_bytes)


def segment_size(slots: int, slot_bytes: int) -> int:
    return SEG_HEADER_BYTES + int(slots) * int(slot_bytes)


def pack_seg_header(canary: int, slots: int, slot_bytes: int) -> bytes:
    raw = SEG_HDR.pack(SEG_MAGIC, int(canary), int(slots), int(slot_bytes), 0)
    return raw + b"\0" * (SEG_HEADER_BYTES - len(raw))


def unpack_seg_header(buf: bytes | bytearray | memoryview) -> tuple[int, int, int]:
    if len(buf) < SEG_HDR.size:
        raise ProtocolError("共享記憶體表頭不足")
    magic, canary, slots, slot_bytes, _ = SEG_HDR.unpack_from(buf, 0)
    if bytes(magic) != SEG_MAGIC:
        raise ProtocolError("共享記憶體 magic 錯誤")
    return int(canary), int(slots), int(slot_bytes)


# ---------------------------------------------------------------------------
# 名稱／通道描述
# ---------------------------------------------------------------------------
def validate_name(name: Any) -> str:
    s = str(name or "").strip()
    if not NAME_RE.match(s):
        raise ProtocolError("擷取端名稱只能用英數、底線、連字號與點（1～64 字）", code="bad_hello")
    return s


def frame_nbytes(width: int, height: int, channels: int, dtype: int) -> int:
    return int(width) * int(height) * int(channels) * ITEMSIZE[int(dtype)]


def validate_channel_dict(d: Any) -> dict[str, Any]:
    """把擷取端送來的通道描述正規化：id、label、driver、width、height、channels、dtype、roi、full、mode、enabled、max_bytes。"""
    if not isinstance(d, dict):
        raise ProtocolError("通道描述必須是物件", code="bad_hello")
    cid = str(d.get("id") or "").strip()
    if not CHANNEL_ID_RE.match(cid):
        raise ProtocolError(f"通道 id '{cid}' 無效", code="bad_hello")
    try:
        width, height = int(d.get("width", 0)), int(d.get("height", 0))
        channels = int(d.get("channels", 1))
    except (TypeError, ValueError):
        raise ProtocolError(f"通道 {cid} 的尺寸無效", code="bad_hello") from None
    dtype = str(d.get("dtype", "u8"))
    if dtype not in DTYPE_CODES or channels not in (1, 3, 4) or width < 0 or height < 0:
        raise ProtocolError(f"通道 {cid} 的像素格式無效", code="bad_hello")
    full = d.get("full") if isinstance(d.get("full"), dict) else {}
    full_w, full_h = int(full.get("w", width) or width), int(full.get("h", height) or height)
    roi = d.get("roi") if isinstance(d.get("roi"), dict) else {}
    roi_out = {"x": int(roi.get("x", 0) or 0), "y": int(roi.get("y", 0) or 0), "w": int(roi.get("w", width) or width), "h": int(roi.get("h", height) or height)}
    mode = str(d.get("mode", "on_demand"))
    if mode not in MODES:
        mode = "on_demand"
    max_bytes = int(d.get("max_bytes") or frame_nbytes(max(width, 1), max(height, 1), channels, DTYPE_CODES[dtype]))
    return {
        "id": cid, "label": str(d.get("label") or cid)[:120], "driver": str(d.get("driver") or "other")[:32],
        "width": width, "height": height, "channels": channels, "dtype": dtype,
        "pixel_format": str(d.get("pixel_format") or ("Mono8" if channels == 1 else "BGR8"))[:32],
        "roi": roi_out, "full": {"w": full_w, "h": full_h}, "mode": mode,
        "enabled": bool(d.get("enabled", True)), "max_bytes": max_bytes,
    }


def is_loopback(ip: str) -> bool:
    ip = str(ip or "")
    return ip.startswith("127.") or ip in ("::1", "localhost") or ip.startswith("::ffff:127.")


# ---------------------------------------------------------------------------
# socket 小工具（簡單客戶端／測試用；hub 的熱路徑另有 recv_into 版本）
# ---------------------------------------------------------------------------
def recv_into_exactly(sock: socket.socket, view: memoryview) -> None:
    got = 0
    total = len(view)
    while got < total:
        n = sock.recv_into(view[got:], total - got)
        if n <= 0:
            raise ConnectionError("連線已關閉")
        got += n


def recv_exactly(sock: socket.socket, n: int) -> bytearray:
    buf = bytearray(n)
    if n:
        recv_into_exactly(sock, memoryview(buf))
    return buf


def read_message(sock: socket.socket, *, max_control: int = MAX_CONTROL_BYTES, max_payload: int = 256 << 20) -> tuple[int, int, bytearray, bytearray]:
    """讀一則完整訊息，回 (type, req_id, header, payload)。"""
    env = recv_exactly(sock, ENVELOPE.size)
    mtype, req_id, hlen, plen = unpack_envelope(env)
    if hlen > max_control:
        raise ProtocolError("控制訊息過大", code="too_large")
    if plen > max_payload:
        raise ProtocolError("payload 過大", code="too_large")
    header = recv_exactly(sock, hlen)
    payload = recv_exactly(sock, plen)
    return mtype, req_id, header, payload


# ---------------------------------------------------------------------------
# LZ4（可選）
# ---------------------------------------------------------------------------
def lz4_available() -> bool:
    try:
        import lz4.block  # noqa: F401
    except ImportError:
        return False
    return True


def compress_lz4(view: bytes | bytearray | memoryview) -> bytes:
    import lz4.block

    return lz4.block.compress(view, store_size=False)


def decompress_lz4(buf: bytes | bytearray | memoryview, raw_len: int) -> bytearray:
    import lz4.block

    return lz4.block.decompress(buf, uncompressed_size=int(raw_len), return_bytearray=True)
