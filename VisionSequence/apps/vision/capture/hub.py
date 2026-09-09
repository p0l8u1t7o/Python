"""擷取端 hub：接受擷取端（vscapture 桌面程式）連入，登記名稱與相機通道，依需求向它要影像或接收串流。

執行緒：`vision-capture`（accept）＋每連線一條 `vision-capture-<name>`（讀取）；全部 daemon、不碰 ORM。
Runner 的工作執行緒經 `CaptureGrabber` 呼叫 `request_frame()`／`wait_for_seq()` 並在 Event／Condition 上等待（不持鎖）。
交給引擎的 ndarray 一律獨占：raw 的接收緩衝就是 ndarray、LZ4 解壓輸出、或從共享記憶體槽 copy 一次。
"""

from __future__ import annotations

import hmac
import itertools
import logging
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass
from multiprocessing import shared_memory
from typing import Any

import numpy as np
from django.conf import settings

from vscapture import __version__ as CLIENT_PROTO_PKG_VERSION
from apps.vision import trace
from apps.vision.capture import build
from vscapture import protocol as P
from vscapture.protocol import Encoding, FrameFlags, FrameHeader, GrabFlags, MsgType, ProtocolError

try:
    import lz4.block as lz4_block
except ImportError:  # 可選依賴：缺少時只接受 raw／jpeg
    lz4_block = None

log = logging.getLogger(__name__)

RCVBUF = 4 << 20


def _publish(kind: str, **fields: Any) -> None:
    """相機上下線進行程內事件匯流排（連線層的事件回報要用）。hub 不碰 ORM，這裡也只是記憶體。
    發不出去不能影響擷取端連線，所以整段包起來。"""
    try:
        from apps.vision.runner import bus

        bus.publish({"type": kind, **fields})
    except Exception:  # noqa: BLE001 - 事件發不出去不能拖垮取像
        log.debug("擷取端事件 %s 發布失敗", kind, exc_info=True)


def _cfg(key: str, default: Any) -> Any:
    return getattr(settings, "VISION", {}).get(key, default)


class CaptureError(Exception):
    """向擷取端要影像失敗；code：client_offline／no_channel／channel_disabled／timeout／disconnected／camera_error／unsupported_encoding／busy。"""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class FrameMeta:
    seq: int
    ts_ns: int
    width: int
    height: int
    channels: int
    dtype: str
    encoding: str
    roi_x: int
    roi_y: int
    full_w: int
    full_h: int
    fresh: bool
    shm: bool
    wire_bytes: int
    received_at: float
    received_perf: float
    captured_at: float | None = None
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq, "ts_ns": self.ts_ns, "width": self.width, "height": self.height, "channels": self.channels, "dtype": self.dtype,
            "encoding": self.encoding, "roi": {"x": self.roi_x, "y": self.roi_y, "w": self.width, "h": self.height}, "full": {"w": self.full_w, "h": self.full_h},
            "fresh": self.fresh, "shm": self.shm, "wire_bytes": self.wire_bytes, "latency_ms": round(self.latency_ms, 2),
            "captured_at": self.captured_at, "received_at": self.received_at,
        }


@dataclass(slots=True)
class Frame:
    image: np.ndarray
    meta: FrameMeta


class _Rate:
    """EWMA 的 fps 與 bytes/s；超過 2 秒沒影格則回 0。"""

    def __init__(self) -> None:
        self.frames = 0
        self.bytes = 0
        self.fps = 0.0
        self.bps = 0.0
        self.recv_ms = 0.0
        self._last: float | None = None

    def took(self, ms: float) -> None:
        self.recv_ms = ms if self.recv_ms == 0 else 0.8 * self.recv_ms + 0.2 * ms

    def tick(self, nbytes: int) -> None:
        now = time.perf_counter()
        if self._last is not None:
            dt = now - self._last
            if dt > 0:
                inst_fps = 1.0 / dt
                inst_bps = nbytes / dt
                self.fps = inst_fps if self.fps == 0 else 0.8 * self.fps + 0.2 * inst_fps
                self.bps = inst_bps if self.bps == 0 else 0.8 * self.bps + 0.2 * inst_bps
        self._last = now
        self.frames += 1
        self.bytes += int(nbytes)

    def snapshot(self) -> dict[str, Any]:
        stale = self._last is None or time.perf_counter() - self._last > 2.0
        return {"fps": 0.0 if stale else round(self.fps, 2), "bytes_per_s": 0 if stale else int(self.bps), "frames": self.frames, "recv_ms": round(self.recv_ms, 2)}


class _BufferPool:
    """接收緩衝池：2000 萬畫素彩色一張約 60 MB，每次 `np.empty` 都要重新 page fault
    （實測配置＋寫滿 17 ms、重用只要 2.4 ms —— 60 fps 的預算是 16.7 ms）。
    只重用「池是唯一持有者」的緩衝：交給引擎、還留在 latest 或 images.store 的永遠不會被覆寫。
    """

    def __init__(self, max_buffers: int = 3, max_bytes: int = 512 << 20) -> None:
        self.max_buffers = max(1, int(max_buffers))
        self.max_bytes = int(max_bytes)
        self._bufs: list[np.ndarray] = []
        self.hits = 0
        self.misses = 0

    def take(self, shape: tuple[int, ...], dtype: Any) -> np.ndarray:
        shape = tuple(int(v) for v in shape)
        dtype = np.dtype(dtype)
        for buf in self._bufs:
            # 參照數：池的 list、迴圈變數 buf、getrefcount 的引數 → 只有池持有時剛好 3
            if buf.shape == shape and buf.dtype == dtype and sys.getrefcount(buf) <= 3:
                self.hits += 1
                return buf
        self.misses += 1
        buf = np.empty(shape, dtype)
        keep = [b for b in self._bufs if b.shape == shape and b.dtype == dtype][: self.max_buffers - 1]
        if buf.nbytes * (len(keep) + 1) <= self.max_bytes:
            keep.append(buf)
        self._bufs = keep
        return buf

    def stats(self) -> dict[str, Any]:
        return {"buffers": len(self._bufs), "hits": self.hits, "misses": self.misses, "bytes": sum(int(b.nbytes) for b in self._bufs)}

    def clear(self) -> None:
        self._bufs = []


class ChannelState:
    def __init__(self, index: int, spec: dict[str, Any], lock: threading.Lock) -> None:
        self.index = index
        self.spec = spec
        self.latest: Frame | None = None
        self.last_seq = 0
        self.streaming = False
        self.last_error = ""
        self.rate = _Rate()
        self.pool = _BufferPool()
        self.cond = threading.Condition(lock)

    @property
    def id(self) -> str:
        return self.spec["id"]

    @property
    def enabled(self) -> bool:
        return bool(self.spec.get("enabled", True))

    def to_dict(self, in_use_by: list[str] | None = None) -> dict[str, Any]:
        latest = self.latest
        age = None if latest is None else round((time.perf_counter() - latest.meta.received_perf) * 1000, 1)
        out = {
            "id": self.id, "label": self.spec["label"], "driver": self.spec["driver"], "index": self.index,
            "width": self.spec["width"], "height": self.spec["height"], "channels": self.spec["channels"], "dtype": self.spec["dtype"],
            "pixel_format": self.spec["pixel_format"], "roi": self.spec["roi"], "full": self.spec["full"],
            "mode": "stream" if self.streaming else self.spec["mode"], "enabled": self.enabled, "streaming": self.streaming,
            "seq": self.last_seq, "last_frame_age_ms": age, "encoding": latest.meta.encoding if latest else "", "shm": bool(latest and latest.meta.shm),
            "last_error": self.last_error, "in_use_by": list(in_use_by or []), **self.rate.snapshot(),
        }
        if isinstance(self.spec.get("params"), list):
            out["params"] = self.spec["params"]
        if isinstance(self.spec.get("outputs"), list):
            out["outputs"] = self.spec["outputs"]
        return out


class _Pending:
    __slots__ = ("event", "frame", "error", "result", "sent_at")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.frame: Frame | None = None
        self.error: CaptureError | None = None
        self.result: dict[str, Any] | None = None
        self.sent_at = time.perf_counter()


#: 連線序號產生器（見 ClientSession.session_id）。
_SESSION_SEQ = itertools.count(1)


class ClientSession(threading.Thread):
    """一條擷取端連線：握手、讀取迴圈、影格接收；對外提供 request_frame／latest／wait_for_seq／set_stream。"""

    def __init__(self, hub: CaptureHub, sock: socket.socket, peer: tuple[str, int]) -> None:
        super().__init__(name="vision-capture-session", daemon=True)
        #: 單調遞增的連線序號：擷取端斷線重連後要判斷「這是不是同一條連線」，
        #: 不能用 id()——CPython 會重用記憶體位址，新的 session 很可能拿到剛釋放的舊位址。
        self.session_id = next(_SESSION_SEQ)
        self.hub = hub
        self.sock = sock
        self.peer = peer
        self.name_ = ""
        self.version = ""
        self._announced = ""  # 已通知過的安裝檔版本（避免每次心跳重推）
        self.hostname = ""
        self.machine_id = ""
        self.pid = 0
        self.features: dict[str, Any] = {}
        self.local = False
        self.connected_at = time.time()
        self.alive = True
        self.registered = False
        self.close_reason = ""
        self.channels: list[ChannelState] = []
        self.by_id: dict[str, ChannelState] = {}
        self.prefer_encoding = int(Encoding.RAW)
        self.shm: shared_memory.SharedMemory | None = None
        self.shm_slots = 0
        self.shm_slot_bytes = 0
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._req_counter = itertools.count(1)
        self._env_buf = bytearray(P.ENVELOPE.size)
        self._hdr_buf = bytearray(P.FRAME_HDR.size)
        self._payload_buf = bytearray(0)
        self._missed_pings = 0
        self._closed = threading.Event()

    # ---- 執行緒主體 ----
    def run(self) -> None:
        reason = "eof"
        try:
            if not self._handshake():
                return
            self.name = f"vision-capture-{self.name_}"
            while self.alive:
                try:
                    self._recv_exactly(memoryview(self._env_buf))
                except socket.timeout:
                    if self._missed_pings >= 2:
                        reason = "heartbeat"
                        break
                    self._missed_pings += 1
                    self._announce_update()
                    self.send(MsgType.PING)
                    continue
                self._missed_pings = 0
                mtype, req_id, hlen, plen = P.unpack_envelope(self._env_buf)
                if not self._dispatch(mtype, req_id, hlen, plen):
                    reason = "bye"
                    break
        except ProtocolError as exc:
            reason = f"protocol:{exc.code}"
            log.warning("擷取端 %s（%s）協定錯誤：%s", self.name_ or "?", self.peer, exc)
            self._try_send_error(0, exc.code, str(exc))
        except (ConnectionError, OSError, socket.timeout) as exc:
            reason = self.close_reason or f"socket:{exc.__class__.__name__}"
        except Exception:  # noqa: BLE001
            reason = "internal"
            log.exception("擷取端 %s 讀取迴圈失敗", self.name_ or self.peer)
        finally:
            self.close(reason)
            if self.registered:
                self.hub.unregister(self)

    # ---- 握手 ----
    def _handshake(self) -> bool:
        self.sock.settimeout(P.HELLO_TIMEOUT_S)
        self._recv_exactly(memoryview(self._env_buf))
        mtype, req_id, hlen, plen = P.unpack_envelope(self._env_buf)
        if mtype != MsgType.HELLO or hlen > P.MAX_CONTROL_BYTES or plen != 0:
            raise ProtocolError("The first message must be HELLO", code="bad_hello")
        body = P.loads_json(self._recv_bytes(hlen))
        if int(body.get("protocol", 0)) != P.PROTOCOL_VERSION:
            self._reject(req_id, "protocol_unsupported", f"Unsupported protocol version {body.get('protocol')} (this server speaks {P.PROTOCOL_VERSION})")
            return False
        secret = self.hub.auth_secret()
        if secret and not hmac.compare_digest(str(body.get("auth") or ""), secret):
            time.sleep(0.5)  # 節流暴力嘗試
            self._reject(req_id, "auth_failed", "The capture client key was rejected")
            return False
        try:
            self.name_ = P.validate_name(body.get("name"))
            channels = [P.validate_channel_dict(c) for c in (body.get("channels") or [])]
        except ProtocolError as exc:
            self._reject(req_id, exc.code, str(exc))
            return False
        if len(channels) > P.MAX_CHANNELS:
            self._reject(req_id, "too_many_channels", f"Too many channels, the limit is {P.MAX_CHANNELS}")
            return False
        self.version = str(body.get("version") or "")[:32]
        self.hostname = str(body.get("hostname") or "")[:128]
        self.machine_id = str(body.get("machine_id") or "")[:64]
        self.pid = int(body.get("pid") or 0)
        self.features = body.get("features") if isinstance(body.get("features"), dict) else {}
        self._install_channels(channels)
        self.local = self._detect_local()
        lz4_both = bool(self.features.get("lz4")) and lz4_block is not None
        self.prefer_encoding = int(Encoding.RAW) if self.local or not lz4_both else int(Encoding.LZ4)
        rejection = self.hub.register(self)
        if rejection is not None:
            self._reject(req_id, rejection, "That capture client name is already in use" if rejection == "name_taken" else rejection)
            return False
        wanted = {c.id: self.hub.stream_wanted(self.name_, c.id) for c in self.channels}
        self.send(MsgType.WELCOME, req_id, P.dumps_json({
            "ok": True, "protocol": P.PROTOCOL_VERSION, "server": "VisionSequence", "server_version": CLIENT_PROTO_PKG_VERSION, "name": self.name_,
            "local": self.local, "prefer": {"encoding": P.ENCODING_NAMES[self.prefer_encoding], "shm": self.local},
            "max_frame_bytes": self.hub.max_frame_bytes(), "heartbeat_s": P.HEARTBEAT_S, "stream": wanted,
            "update": self._update_payload(),
        }))
        self.sock.settimeout(P.HEARTBEAT_S)
        for cid, on in wanted.items():
            if on:
                self.set_stream(cid, True)
        log.info("擷取端 %s 已連線（%s:%s，%s，通道 %d）", self.name_, self.peer[0], self.peer[1], "同機" if self.local else "跨機", len(self.channels))
        _publish("source_connected", client=self.name_, local=self.local, channels=[c.id for c in self.channels])
        trace.record("capture", f"Capture client {self.name_} connected ({"same machine" if self.local else "across machines"}, channels {len(self.channels)}）", name=self.name_,
                     detail={"address": f"{self.peer[0]}:{self.peer[1]}", "version": self.version, "channels": [c.id for c in self.channels]}, force=True)
        return True

    def _reject(self, req_id: int, code: str, message: str) -> None:
        self.close_reason = code
        try:
            self.send(MsgType.WELCOME, req_id, P.dumps_json({"ok": False, "code": code, "message": message, "protocol": P.PROTOCOL_VERSION}))
        except OSError:
            pass

    def _detect_local(self) -> bool:
        if not P.is_loopback(self.peer[0]):
            try:
                local_ips = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None)}
            except OSError:
                local_ips = set()
            if self.peer[0] not in local_ips:
                return False
        return bool(self.hostname) and self.hostname.lower() == socket.gethostname().lower()

    def _install_channels(self, specs: list[dict[str, Any]]) -> None:
        with self._lock:
            new: list[ChannelState] = []
            for i, spec in enumerate(specs):
                old = self.channels[i] if i < len(self.channels) and self.channels[i].id == spec["id"] else None
                if old is not None:
                    old.spec = spec
                    new.append(old)
                else:
                    new.append(ChannelState(i, spec, self._lock))
            self.channels = new
            self.by_id = {c.id: c for c in new}

    # ---- 讀取 ----
    def _recv_exactly(self, view: memoryview) -> None:
        got, total = 0, len(view)
        while got < total:
            n = self.sock.recv_into(view[got:], total - got)
            if n <= 0:
                raise ConnectionError("The capture client closed the connection")
            got += n

    def _recv_bytes(self, n: int) -> bytearray:
        buf = bytearray(n)
        if n:
            self._recv_exactly(memoryview(buf))
        return buf

    def _payload(self, n: int) -> memoryview:
        if len(self._payload_buf) < n:
            self._payload_buf = bytearray(n)
        view = memoryview(self._payload_buf)[:n]
        self._recv_exactly(view)
        return view

    def _drain(self, n: int) -> None:
        while n > 0:
            chunk = min(n, 1 << 20)
            self._payload(chunk)
            n -= chunk

    def _dispatch(self, mtype: int, req_id: int, hlen: int, plen: int) -> bool:
        """處理一則訊息；回 False 表示對方要求關閉（BYE）。"""
        if mtype in (MsgType.FRAME, MsgType.TEST):
            if hlen != P.FRAME_HDR.size:
                raise ProtocolError("The FRAME header length is wrong")
            if plen > self.hub.max_frame_bytes():
                raise ProtocolError(f"The frame is {plen} bytes, over the limit", code="too_large")
            self._recv_exactly(memoryview(self._hdr_buf))
            self._on_frame(mtype, req_id, FrameHeader.unpack(self._hdr_buf), plen)
            return True
        if hlen > P.MAX_CONTROL_BYTES or plen > self.hub.max_frame_bytes():
            raise ProtocolError("The message is too large", code="too_large")
        header = self._recv_bytes(hlen) if hlen else bytearray()
        if plen:
            self._drain(plen)
        if mtype == MsgType.PING:
            self.send(MsgType.PONG, req_id)
        elif mtype == MsgType.PONG:
            pass
        elif mtype == MsgType.BYE:
            self.close_reason = "bye"
            return False
        elif mtype == MsgType.CHANNELS:
            body = P.loads_json(header)
            specs = [P.validate_channel_dict(c) for c in (body.get("channels") or [])]
            if len(specs) > P.MAX_CHANNELS:
                raise ProtocolError(f"Too many channels, the limit is {P.MAX_CHANNELS}", code="too_many_channels")
            self._install_channels(specs)
        elif mtype == MsgType.SHM_OFFER:
            self._on_shm_offer(req_id, P.loads_json(header))
        elif mtype == MsgType.STREAM:
            body = P.loads_json(header)
            ch = self.by_id.get(str(body.get("channel") or ""))
            if ch is not None:
                with self._lock:
                    ch.streaming = bool(body.get("enabled")) and bool(body.get("ok", True))
        elif mtype == MsgType.CHANNEL_RESULT:
            self._resolve(req_id, result=P.loads_json(header))
        elif mtype == MsgType.UPDATE_PULL:
            self._on_update_pull(req_id, P.loads_json(header))
        elif mtype == MsgType.ERROR:
            body = P.loads_json(header)
            code = str(body.get("code") or "error")
            message = str(body.get("message") or code)
            self._resolve(req_id, error=CaptureError(f"The capture client reported: {message}", code=code))
            if req_id == 0:
                log.warning("擷取端 %s 回報錯誤 %s：%s", self.name_, code, message)
        elif mtype in (MsgType.HELLO, MsgType.WELCOME, MsgType.SHM_ACCEPT, MsgType.GRAB, MsgType.CHANNEL_SET, MsgType.SLOT_FREE, MsgType.TEST_RESULT, MsgType.UPDATE, MsgType.UPDATE_DATA):
            raise ProtocolError(f"A capture client must not send {MsgType(mtype).name}")
        else:
            raise ProtocolError(f"Unknown message type {mtype}")
        return True

    # ---- 自動更新（安裝檔走同一條已驗證的連線送，不必另開埠或再驗一次金鑰）----
    def _update_payload(self) -> dict[str, Any]:
        data = build.info()
        if not data.get("available"):
            return {"available": False}
        self._announced = str(data["version"])
        return {
            "available": P.is_newer(str(data["version"]), self.version), "version": data["version"], "filename": data["filename"],
            "size": data["size"], "sha256": data["sha256"], "built_at": data["built_at"], "chunk": P.UPDATE_CHUNK_BYTES,
        }

    def _announce_update(self) -> None:
        """伺服端重新建置了（manifest 版本變了）就主動通知已連線的擷取端。"""
        data = build.info()
        version = str(data.get("version") or "")
        if not data.get("available") or version == self._announced:
            return
        self._announced = version
        if not P.is_newer(version, self.version):
            return
        try:
            self.send(MsgType.UPDATE, 0, P.dumps_json(self._update_payload()))
            log.info("已通知擷取端 %s 有新版 %s（目前 %s）", self.name_, version, self.version or "?")
        except CaptureError:
            pass

    def _on_update_pull(self, req_id: int, body: dict[str, Any]) -> None:
        offset = int(body.get("offset") or 0)
        length = min(int(body.get("length") or P.UPDATE_CHUNK_BYTES), P.UPDATE_CHUNK_BYTES)
        try:
            chunk, eof = build.read_chunk(offset, length)
        except (OSError, ValueError) as exc:
            self.send(MsgType.UPDATE_DATA, req_id, P.dumps_json({"offset": offset, "eof": True, "error": str(exc)}))
            return
        self.send(MsgType.UPDATE_DATA, req_id, P.dumps_json({"offset": offset, "eof": eof}), chunk)

    def _on_frame(self, mtype: int, req_id: int, hdr: FrameHeader, plen: int) -> None:
        started = time.perf_counter()
        received_perf = 0.0
        received_at = 0.0
        n_channels = len(self.channels)
        try:
            hdr.validate(n_channels, self.hub.max_frame_bytes(), plen, shm_slots=self.shm_slots, slot_bytes=self.shm_slot_bytes)
        except ProtocolError as exc:
            if exc.code == "too_large":
                raise
            if plen:
                self._drain(plen)
            if exc.code == "no_channel":
                self._resolve(req_id, error=CaptureError(str(exc), code="no_channel"))
                return
            raise
        if hdr.encoding == Encoding.LZ4 and lz4_block is None:
            self._drain(plen)
            self._resolve(req_id, error=CaptureError("The server has no LZ4; use raw instead", code="unsupported_encoding"))
            self._try_send_error(req_id, "unsupported_encoding", "LZ4 is not installed on the server")
            return
        with self._lock:
            pool = self.channels[hdr.chan].pool
        image = self._read_pixels(hdr, plen, pool)
        wire = plen if hdr.slot < 0 else 0
        if hdr.slot >= 0:
            self.send(MsgType.SLOT_FREE, 0, P.pack_slot_free(hdr.chan, hdr.slot, hdr.seq))
        if mtype == MsgType.TEST:
            self.send(MsgType.TEST_RESULT, req_id, P.dumps_json({"bytes": wire, "decode_ms": round((time.perf_counter() - started) * 1000, 2), "shape": list(image.shape)}))
            return
        received_perf = time.perf_counter()
        received_at = time.time()
        meta = FrameMeta(
            seq=hdr.seq, ts_ns=hdr.ts_ns, width=hdr.width, height=hdr.height, channels=hdr.channels, dtype=P.DTYPE_NAMES[hdr.dtype],
            encoding=P.ENCODING_NAMES[hdr.encoding] if hdr.slot < 0 else "shm", roi_x=hdr.roi_x, roi_y=hdr.roi_y, full_w=hdr.full_w, full_h=hdr.full_h,
            fresh=bool(hdr.flags & FrameFlags.FRESH), shm=hdr.slot >= 0, wire_bytes=wire,
            received_at=received_at, received_perf=received_perf, captured_at=hdr.captured_at,
        )
        frame = Frame(image, meta)
        with self._lock:
            ch = self.channels[hdr.chan]
            ch.latest = frame
            ch.last_seq = max(ch.last_seq, hdr.seq)
            ch.last_error = ""
            ch.rate.tick(wire or hdr.raw_len)
            ch.rate.took((time.perf_counter() - started) * 1000)
            pending = self._pending.pop(req_id, None) if req_id else None
            if pending is not None:
                meta.latency_ms = (time.perf_counter() - pending.sent_at) * 1000
                pending.frame = frame
                pending.event.set()
            ch.cond.notify_all()
        self.hub._notify_frame(self.name_, ch.id)

    def _read_pixels(self, hdr: FrameHeader, plen: int, pool: _BufferPool) -> np.ndarray:
        shape, dtype = hdr.shape(), hdr.numpy_dtype
        if hdr.slot >= 0:
            shm = self.shm
            if shm is None:
                raise ProtocolError("A slot frame arrived before shared memory was accepted")
            out = pool.take(shape, dtype)
            off = P.slot_offset(hdr.slot, self.shm_slot_bytes)
            # 暫時的 ndarray view：np.copyto 會放開 GIL（memoryview 指派不會），複製完立刻丟掉
            # ——shm.buf 上絕不能留著 view，否則 close() 會 BufferError。
            src = np.ndarray(shape, dtype, buffer=shm.buf, offset=off)
            try:
                np.copyto(out, src)
            finally:
                del src
            return out
        if hdr.encoding == Encoding.RAW:
            out = pool.take(shape, dtype)
            self._recv_exactly(out.data.cast("B"))
            return out
        buf = self._payload(plen)
        if hdr.encoding == Encoding.LZ4:
            raw = lz4_block.decompress(buf, uncompressed_size=hdr.raw_len, return_bytearray=True)
            return np.frombuffer(raw, dtype=dtype).reshape(shape)
        import cv2

        flag = cv2.IMREAD_GRAYSCALE if hdr.channels == 1 else cv2.IMREAD_UNCHANGED if hdr.channels == 4 else cv2.IMREAD_COLOR
        image = cv2.imdecode(np.frombuffer(buf, np.uint8), flag)
        if image is None or image.shape[:2] != (hdr.height, hdr.width):
            raise ProtocolError("The JPEG frame failed to decode, or its size does not match")
        return np.ascontiguousarray(image)

    # ---- 共享記憶體 ----
    def _on_shm_offer(self, req_id: int, body: dict[str, Any]) -> None:
        name = str(body.get("name") or "")
        try:
            slots, slot_bytes, canary = int(body.get("slots") or 0), int(body.get("slot_bytes") or 0), int(body.get("canary") or 0)
        except (TypeError, ValueError):
            slots = slot_bytes = canary = 0
        error = ""
        if not self.local:
            error = "Not the same machine, staying on TCP"
        elif slots < 2 or slot_bytes <= 0 or slot_bytes > self.hub.max_frame_bytes() or not name:
            error = "Invalid shared-memory parameters"
        else:
            try:
                shm = shared_memory.SharedMemory(name=name, create=False)
                if os.name != "nt":
                    try:
                        from multiprocessing import resource_tracker

                        resource_tracker.unregister(shm._name, "shared_memory")  # noqa: SLF001
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    got_canary, got_slots, got_bytes = P.unpack_seg_header(shm.buf[: P.SEG_HDR.size])
                    if got_canary != canary or got_slots != slots or got_bytes != slot_bytes or shm.size < P.segment_size(slots, slot_bytes):
                        error = "The shared-memory header does not match"
                except ProtocolError as exc:
                    error = str(exc)
                if error:
                    shm.close()
                else:
                    old = self.shm
                    self.shm, self.shm_slots, self.shm_slot_bytes = shm, slots, slot_bytes
                    if old is not None:
                        old.close()
            except (FileNotFoundError, OSError, ValueError) as exc:
                error = f"Could not attach the shared memory segment: {exc}"
        self.send(MsgType.SHM_ACCEPT, req_id, P.dumps_json({"ok": not error, "error": error} if error else {"ok": True}))
        if error:
            log.info("擷取端 %s 的共享記憶體未採用：%s", self.name_, error)

    # ---- 送出 ----
    def send(self, mtype: int, req_id: int = 0, header: bytes = b"", payload: bytes = b"") -> None:
        data = P.pack_envelope(mtype, req_id, len(header), len(payload)) + header + payload
        try:
            with self._send_lock:
                self.sock.sendall(data)
        except OSError as exc:
            self.close_reason = self.close_reason or "send_failed"
            self.close("send_failed")
            raise CaptureError("The capture client disconnected", code="disconnected") from exc

    def _try_send_error(self, req_id: int, code: str, message: str) -> None:
        try:
            self.send(MsgType.ERROR, req_id, P.dumps_json({"code": code, "message": message}))
        except (CaptureError, OSError):
            pass

    def next_req_id(self) -> int:
        return next(self._req_counter)

    def _resolve(self, req_id: int, *, error: CaptureError | None = None, frame: Frame | None = None, result: dict[str, Any] | None = None) -> None:
        if not req_id:
            return
        with self._lock:
            pending = self._pending.pop(req_id, None)
            if pending is None:
                return
            pending.error, pending.frame, pending.result = error, frame, result
            pending.event.set()

    # ---- 給 hub／grabber 用 ----
    def channel(self, channel: str) -> ChannelState:
        ch = self.by_id.get(channel)
        if ch is None:
            raise CaptureError(f'Capture client "{self.name_}" has no channel "{channel}"', code="no_channel")
        if not ch.enabled:
            raise CaptureError(f'Channel "{channel}" is disabled', code="channel_disabled")
        return ch

    def request_frame(self, channel: str, *, timeout: float, min_seq: int = 0, after_request: bool = True, encoding: int = Encoding.AUTO) -> Frame:
        ch = self.channel(channel)
        if not self.alive:
            raise CaptureError("The capture client disconnected", code="disconnected")
        req_id = self.next_req_id()
        pending = _Pending()
        with self._lock:
            self._pending[req_id] = pending
        flags = GrabFlags.AFTER_REQUEST if after_request else GrabFlags.NONE
        try:
            self.send(MsgType.GRAB, req_id, P.pack_grab(ch.index, min_seq, int(timeout * 1000), encoding, flags))
        except CaptureError:
            with self._lock:
                self._pending.pop(req_id, None)
            raise
        if not pending.event.wait(timeout + 0.25):
            with self._lock:
                self._pending.pop(req_id, None)
            with self._lock:
                ch.last_error = "The capture client timed out"
            raise CaptureError(f'Capture client "{self.name_}" timed out without returning an image', code="timeout")
        if pending.error is not None:
            with self._lock:
                ch.last_error = str(pending.error)
            raise pending.error
        assert pending.frame is not None
        return pending.frame

    def request_pair(self, channel_a: str, channel_b: str, *, timeout: float) -> tuple[Frame, Frame, float | None]:
        """同時對兩個通道送 GRAB，等兩張新影格回來後計算擷取時間差。"""
        ch_a = self.channel(channel_a)
        ch_b = self.channel(channel_b)
        if not self.alive:
            raise CaptureError("The capture client disconnected", code="disconnected")
        req_a, req_b = self.next_req_id(), self.next_req_id()
        pending_a, pending_b = _Pending(), _Pending()
        with self._lock:
            self._pending[req_a] = pending_a
            self._pending[req_b] = pending_b
            min_a, min_b = ch_a.last_seq, ch_b.last_seq
        try:
            header_a = P.pack_grab(ch_a.index, min_a, int(timeout * 1000), Encoding.AUTO, GrabFlags.AFTER_REQUEST)
            header_b = P.pack_grab(ch_b.index, min_b, int(timeout * 1000), Encoding.AUTO, GrabFlags.AFTER_REQUEST)
            self.send(MsgType.GRAB, req_a, header_a)
            self.send(MsgType.GRAB, req_b, header_b)
        except CaptureError:
            with self._lock:
                self._pending.pop(req_a, None)
                self._pending.pop(req_b, None)
            raise
        frames: list[Frame] = []
        for ch, pending in ((ch_a, pending_a), (ch_b, pending_b)):
            if not pending.event.wait(timeout + 0.25):
                with self._lock:
                    self._pending.pop(req_a, None)
                    self._pending.pop(req_b, None)
                    ch.last_error = "The capture client timed out"
                raise CaptureError(f'Capture client "{self.name_}" timed out without returning a stereo pair', code="timeout")
            if pending.error is not None:
                with self._lock:
                    ch.last_error = str(pending.error)
                raise pending.error
            assert pending.frame is not None
            frames.append(pending.frame)
        left, right = frames
        if left.meta.captured_at is not None and right.meta.captured_at is not None:
            dt_ms = abs(left.meta.captured_at - right.meta.captured_at) * 1000.0
        else:
            dt_ms = abs(left.meta.received_at - right.meta.received_at) * 1000.0
        return left, right, dt_ms

    def latest(self, channel: str) -> Frame | None:
        ch = self.channel(channel)
        with self._lock:
            return ch.latest

    def wait_for_seq(self, channel: str, min_seq: int, timeout: float) -> Frame:
        ch = self.channel(channel)
        with self._lock:
            ok = ch.cond.wait_for(lambda: not self.alive or (ch.latest is not None and ch.latest.meta.seq > min_seq), timeout)
            if not self.alive:
                raise CaptureError("The capture client disconnected", code="disconnected")
            if not ok or ch.latest is None:
                raise CaptureError(f'The stream from capture client "{self.name_}" timed out with no new frame', code="timeout")
            return ch.latest

    def set_stream(self, channel: str, enabled: bool, max_fps: float = 0) -> None:
        ch = self.channel(channel)
        self.send(MsgType.STREAM, self.next_req_id(), P.dumps_json({"channel": ch.id, "enabled": bool(enabled), "max_fps": float(max_fps or 0)}))

    def _send_channel_set(self, channel: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        ch = self.channel(channel)
        if not self.alive:
            raise CaptureError("The capture client disconnected", code="disconnected")
        if not bool(self.features.get("channel_set")):
            raise CaptureError("capture client does not support channel_set; update the client", code="unsupported_feature")
        req_id = self.next_req_id()
        pending = _Pending()
        with self._lock:
            self._pending[req_id] = pending
        try:
            self.send(MsgType.CHANNEL_SET, req_id, P.dumps_json({"channel": ch.id, **body}))
        except CaptureError:
            with self._lock:
                self._pending.pop(req_id, None)
            raise
        if not pending.event.wait(float(timeout) + 0.25):
            with self._lock:
                self._pending.pop(req_id, None)
                ch.last_error = "The capture client timed out"
            raise CaptureError(f'Capture client "{self.name_}" timed out without applying camera settings', code="timeout")
        if pending.error is not None:
            with self._lock:
                ch.last_error = str(pending.error)
            raise pending.error
        result = pending.result if isinstance(pending.result, dict) else {}
        normalized = {
            "ok": bool(result.get("ok")),
            "applied": result.get("applied") if isinstance(result.get("applied"), dict) else {},
            "errors": result.get("errors") if isinstance(result.get("errors"), dict) else {},
            "message": str(result.get("message") or ""),
        }
        self._merge_channel_params(ch, normalized["applied"])
        return normalized

    def _merge_channel_params(self, ch: ChannelState, applied: dict[str, Any]) -> None:
        if not applied:
            return
        with self._lock:
            specs = ch.spec.get("params")
            if not isinstance(specs, list):
                return
            for spec in specs:
                if isinstance(spec, dict) and str(spec.get("name") or "") in applied:
                    spec["value"] = applied[str(spec.get("name") or "")]

    def set_channel_params(self, channel: str, params: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]:
        return self._send_channel_set(channel, {"params": dict(params or {})}, timeout)

    def channel_command(self, channel: str, command: str, args: dict[str, Any] | None = None, timeout: float = 2.0) -> dict[str, Any]:
        return self._send_channel_set(channel, {"command": str(command), "args": dict(args or {})}, timeout)

    def close(self, reason: str = "closed") -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self.alive = False
        self.close_reason = self.close_reason or reason
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        with self._lock:
            pendings = list(self._pending.values())
            self._pending.clear()
            for ch in self.channels:
                ch.streaming = False
                ch.cond.notify_all()
        for p in pendings:
            p.error = CaptureError("The capture client disconnected", code="disconnected")
            p.event.set()
        if self.shm is not None:
            try:
                self.shm.close()
            except (BufferError, OSError):
                pass
            self.shm = None
        if self.registered:
            log.info("擷取端 %s 斷線（%s）", self.name_, self.close_reason)
            _publish("source_lost", client=self.name_, reason=self.close_reason)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            channels = [c.to_dict(self.hub.users_of(self.name_, c.id)) for c in self.channels]
        return {
            "name": self.name_, "address": f"{self.peer[0]}:{self.peer[1]}", "version": self.version, "hostname": self.hostname,
            "connected_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.connected_at)), "local": self.local,
            "prefer_encoding": P.ENCODING_NAMES[self.prefer_encoding], "shm": self.shm is not None, "channels": channels,
        }


class CaptureHub:
    """擷取端登錄表與監聽埠（模組單例 `hub`）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, ClientSession] = {}
        self._lock = threading.Lock()
        self._stream_refs: dict[tuple[str, str], int] = {}
        self._stream_wanted: dict[tuple[str, str], bool] = {}
        self._users: dict[tuple[str, str], set[str]] = {}
        self._frame_events: dict[tuple[str, str], threading.Event] = {}
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.host = ""
        self.port = 0

    # ---- 生命週期 ----
    @property
    def listening(self) -> bool:
        return self._listener is not None

    def start(self, host: str, port: int) -> None:
        if self._listener is not None:
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, int(port)))
        listener.listen(16)
        listener.settimeout(0.5)
        self._listener = listener
        self.host, self.port = host, int(listener.getsockname()[1])
        self._thread = threading.Thread(target=self._accept_loop, name="vision-capture", daemon=True)
        self._thread.start()
        log.info("擷取端連入埠監聽 %s:%s", host, self.port)

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            s.close("shutdown")
        for s in sessions:
            s.join(timeout=2.0)

    def _accept_loop(self) -> None:
        while True:
            listener = self._listener
            if listener is None:
                return
            try:
                sock, peer = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RCVBUF)
            except OSError:
                pass
            ClientSession(self, sock, (peer[0], peer[1])).start()

    # ---- 登錄表 ----
    def register(self, session: ClientSession) -> str | None:
        with self._lock:
            old = self._sessions.get(session.name_)
            if old is not None and old.alive and not (session.machine_id and old.machine_id == session.machine_id):
                return "name_taken"
            self._sessions[session.name_] = session
            session.registered = True
        if old is not None and old is not session:
            old.registered = False
            old.close("replaced")
        return None

    def unregister(self, session: ClientSession) -> None:
        with self._lock:
            if self._sessions.get(session.name_) is session:
                del self._sessions[session.name_]

    def get(self, name: str) -> ClientSession | None:
        with self._lock:
            s = self._sessions.get(name)
        return s if s is not None and s.alive else None

    def clients(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [s.to_dict() for s in sessions if s.alive]

    def _require(self, client: str) -> ClientSession:
        session = self.get(client)
        if session is None:
            raise CaptureError(f'Capture client "{client}" is not connected', code="client_offline")
        return session

    # ---- 影格 ----
    def request_frame(self, client: str, channel: str, *, timeout: float, min_seq: int = 0, after_request: bool = True, encoding: int = Encoding.AUTO) -> Frame:
        return self._require(client).request_frame(channel, timeout=timeout, min_seq=min_seq, after_request=after_request, encoding=encoding)

    def request_pair(self, client: str, channel_a: str, channel_b: str, *, timeout: float) -> tuple[Frame, Frame, float | None]:
        return self._require(client).request_pair(channel_a, channel_b, timeout=timeout)

    def latest(self, client: str, channel: str) -> Frame | None:
        return self._require(client).latest(channel)

    def wait_for_seq(self, client: str, channel: str, min_seq: int, timeout: float) -> Frame:
        return self._require(client).wait_for_seq(channel, min_seq, timeout)

    def set_channel_params(self, client: str, channel: str, params: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]:
        return self._require(client).set_channel_params(channel, params, timeout)

    def channel_command(self, client: str, channel: str, command: str, args: dict[str, Any] | None = None, timeout: float = 2.0) -> dict[str, Any]:
        return self._require(client).channel_command(channel, command, args, timeout)

    # ---- 串流 ----
    def stream_wanted(self, client: str, channel: str) -> bool:
        key = (client, channel)
        with self._lock:
            return bool(self._stream_wanted.get(key)) or self._stream_refs.get(key, 0) > 0

    def acquire_stream(self, client: str, channel: str, source_name: str = "") -> None:
        key = (client, channel)
        with self._lock:
            self._stream_refs[key] = self._stream_refs.get(key, 0) + 1
            first = self._stream_refs[key] == 1
            if source_name:
                self._users.setdefault(key, set()).add(source_name)
        session = self.get(client)
        if session is not None and first:
            try:
                session.set_stream(channel, True)
            except CaptureError:
                pass

    def release_stream(self, client: str, channel: str, source_name: str = "") -> None:
        key = (client, channel)
        with self._lock:
            n = max(0, self._stream_refs.get(key, 0) - 1)
            self._stream_refs[key] = n
            if source_name:
                self._users.get(key, set()).discard(source_name)
            last = n == 0 and not self._stream_wanted.get(key)
        session = self.get(client)
        if session is not None and last:
            try:
                session.set_stream(channel, False)
            except CaptureError:
                pass

    def set_stream(self, client: str, channel: str, enabled: bool, max_fps: float = 0) -> None:
        with self._lock:
            self._stream_wanted[(client, channel)] = bool(enabled)
            refs = self._stream_refs.get((client, channel), 0)
        session = self._require(client)
        session.set_stream(channel, enabled or refs > 0, max_fps)

    def note_user(self, client: str, channel: str, source_name: str, present: bool) -> None:
        key = (client, channel)
        with self._lock:
            users = self._users.setdefault(key, set())
            (users.add if present else users.discard)(source_name)

    def users_of(self, client: str, channel: str) -> list[str]:
        with self._lock:
            return sorted(self._users.get((client, channel), set()))

    def frame_event(self, client: str, channel: str) -> threading.Event:
        key = (client, channel)
        with self._lock:
            event = self._frame_events.get(key)
            if event is None:
                event = self._frame_events[key] = threading.Event()
            return event

    def _notify_frame(self, client: str, channel: str) -> None:
        with self._lock:
            event = self._frame_events.get((client, channel))
        if event is not None:
            event.set()

    # ---- 設定 ----
    def auth_secret(self) -> str:
        return str(_cfg("CAPTURE_AUTH", "") or _cfg("API_KEY", "") or "")

    def max_frame_bytes(self) -> int:
        return int(_cfg("CAPTURE_MAX_FRAME_MB", 64)) << 20

    def stats(self) -> dict[str, Any]:
        with self._lock:
            n = len(self._sessions)
        return {"listening": self.listening, "host": self.host, "port": self.port, "clients": n}


hub = CaptureHub()


def start_in_background(host: str, port: int) -> CaptureHub:
    hub.start(host, port)
    return hub


def stop() -> None:
    hub.stop()
