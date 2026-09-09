"""傳輸客戶端：連線／指數退避重連／HELLO／心跳／共享記憶體協商／訊息分派（GRAB 回覆、串流開關、SLOT_FREE）。

執行緒：vsc-net（連線與讀取）、vsc-send（送出）、vsc-grab（GRAB 回覆，每通道一條）、vsc-stream-<cid>（串流）。
"""

from __future__ import annotations

import logging
import random
import socket
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
import hashlib

from vscapture import protocol as P
from vscapture.cameras.base import CameraParamError
from vscapture.config import ConnectionConfig
from vscapture.frames import encode, frame_item, prepare
from vscapture.protocol import Encoding, FrameFlags, FrameHeader, GrabFlags, MsgType, ProtocolError
from vscapture.shm import ShmRing, plan_slots
from vscapture.update import UpdateInfo
from vscapture.transport.sender import SendQueue, SenderThread
from vscapture.transport.stream import StreamPusher

if TYPE_CHECKING:
    from vscapture.engine import CaptureEngine

log = logging.getLogger(__name__)
SNDBUF = 4 << 20


class ConnState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    AUTH_FAILED = "auth_failed"


def machine_id() -> str:
    """穩定的機器識別（重連時伺服端據此取代舊連線）。"""
    from vscapture.config import app_dir

    path = app_dir() / "machine-id"
    try:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        path.parent.mkdir(parents=True, exist_ok=True)
        value = uuid.uuid4().hex
        path.write_text(value, encoding="utf-8")
        return value
    except OSError:
        return f"{socket.gethostname()}-{uuid.getnode():x}"


def _bool_arg(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _int_arg(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class TransportClient:
    def __init__(self, engine: CaptureEngine, cfg: ConnectionConfig, *, version: str) -> None:
        self.engine = engine
        self.cfg = cfg
        self.version = version
        self.state = ConnState.DISCONNECTED
        self.state_detail = ""
        self.welcome: dict[str, Any] = {}
        self.local_mode = False
        self.update: UpdateInfo = UpdateInfo()
        self._pulls: dict[int, Future] = {}
        self.rings: dict[str, ShmRing] = {}  # cid → 共用的 ring（同一個物件）
        self._ring: ShmRing | None = None
        self._pending_ring: ShmRing | None = None
        self.queue = SendQueue()
        self.rtt_ms: float | None = None
        self.connected_since: float | None = None
        self.attempts = 0
        self.frames_sent = 0
        self.bytes_sent = 0
        self._sock: socket.socket | None = None
        self._sender: SenderThread | None = None
        self._thread: threading.Thread | None = None
        self._alive = False
        self._wake = threading.Event()
        self._req_counter = 1
        self._req_lock = threading.Lock()
        self._pings: dict[int, float] = {}
        self._offers: dict[int, str] = {}
        self._tests: dict[int, tuple[Future, float, int]] = {}
        self._pushers: dict[str, StreamPusher] = {}
        self._pulse_lock = threading.Lock()
        self._pulse_timers: set[threading.Timer] = set()
        self._pool: ThreadPoolExecutor | None = None
        self._last_rx = 0.0
        self._machine_id = machine_id()

    # ---- 對外 ----
    def start(self) -> None:
        if self._thread is not None:
            return
        self._alive = True
        self._thread = threading.Thread(target=self._run, name="vsc-net", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._alive = False
        self._wake.set()
        self._send_bye()
        self._teardown("stopped")
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._set_state(ConnState.DISCONNECTED)

    def reconnect_now(self) -> None:
        self.attempts = 0
        self._wake.set()
        self._teardown("reconnect")

    def update_config(self, cfg: ConnectionConfig) -> None:
        self.cfg = cfg

    def stats(self) -> dict[str, Any]:
        sender = self._sender
        return {
            "state": self.state.value, "detail": self.state_detail, "server": {k: self.welcome.get(k) for k in ("server", "server_version", "name")},
            "local": self.local_mode, "rtt_ms": None if self.rtt_ms is None else round(self.rtt_ms, 2), "attempts": self.attempts,
            "connected_since": self.connected_since, "frames_sent": self.frames_sent, "bytes_sent": self.bytes_sent + (sender.bytes_sent if sender else 0),
            "rings": {cid: r.stats() for cid, r in self.rings.items()}, "streams": {cid: {"sent": p.sent, "dropped": p.dropped} for cid, p in self._pushers.items()},
        }

    def is_streaming(self, cid: str) -> bool:
        """伺服端是否要這個通道連續推影格（串流中就不能省電暫停）。"""
        pusher = self._pushers.get(cid)
        return pusher is not None and pusher.is_alive()

    def send_channels(self) -> None:
        """通道設定變了：送 CHANNELS，並在本機模式重建受影響的共享記憶體環。"""
        if self.state != ConnState.CONNECTED:
            return
        self.queue.put_control(P.pack_json(MsgType.CHANNELS, {"channels": self.engine.hello_channels()}))
        if self.local_mode:
            self._negotiate_shm()

    def test_send(self, cid: str) -> Future:
        fut: Future = Future()
        if self.state != ConnState.CONNECTED:
            fut.set_exception(RuntimeError("尚未連線"))
            return fut
        ch = self.engine.channels.get(cid)
        frame = ch.slot.latest() if ch else None
        if ch is None or frame is None:
            fut.set_exception(RuntimeError("此通道尚無影格"))
            return fut
        fields, arr = prepare(frame, ch.cfg.roi, ch.cfg.delivery)
        t0 = time.perf_counter()
        payload = encode(arr, fields["encoding"], ch.cfg.delivery.jpeg_quality)
        encode_ms = (time.perf_counter() - t0) * 1000
        req_id = self._next_req()
        hdr = FrameHeader.for_image(self.engine.channel_index(cid), frame.seq, frame.ts_ns, fields["width"], fields["height"], fields["channels"], fields["dtype"],
                                    roi_x=fields["roi_x"], roi_y=fields["roi_y"], full_w=fields["full_w"], full_h=fields["full_h"],
                                    encoding=fields["encoding"], flags=fields["flags"], captured_at_ms=frame.ts_ns // 1_000_000)
        self._tests[req_id] = (fut, time.perf_counter(), len(payload))
        fut.encode_ms = encode_ms  # type: ignore[attr-defined]
        self.queue.put_reply(P.pack_message(MsgType.TEST, req_id, hdr.pack(), payload))
        return fut

    # ---- 連線迴圈 ----
    def _set_state(self, state: ConnState, detail: str = "") -> None:
        if state == self.state and detail == self.state_detail:
            return
        self.state, self.state_detail = state, detail
        self.engine.events.emit("connection", {"state": state.value, "detail": detail})

    def _run(self) -> None:
        while self._alive:
            self._wake.clear()
            self._set_state(ConnState.CONNECTING if self.attempts == 0 else ConnState.RECONNECTING, f"attempt:{self.attempts + 1}" if self.attempts else "")
            try:
                self._connect_once()
                if not self._alive:
                    break
                delay = 1.0  # 正常斷線後很快重連
            except _AuthFailed as exc:
                self._set_state(ConnState.AUTH_FAILED, str(exc))
                delay = 30.0
            except _Rejected as exc:
                self._set_state(ConnState.RECONNECTING, str(exc))
                delay = min(self.cfg.reconnect_max_s, 5.0 * (2 ** min(self.attempts, 4)))
            except (OSError, ProtocolError, ConnectionError) as exc:
                self._set_state(ConnState.RECONNECTING, str(exc))
                delay = min(self.cfg.reconnect_max_s, 2.0 ** min(self.attempts, 6)) + random.uniform(0, 0.5)
            except Exception as exc:  # noqa: BLE001
                log.exception("連線迴圈失敗")
                self._set_state(ConnState.RECONNECTING, str(exc))
                delay = 5.0
            finally:
                self._teardown("closed")
            self.attempts += 1
            if self._alive:
                self._wake.wait(delay)
        self._set_state(ConnState.DISCONNECTED)

    def _connect_once(self) -> None:
        sock = socket.create_connection((self.cfg.host, int(self.cfg.port)), timeout=5.0)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SNDBUF)
        except OSError:
            pass
        self._sock = sock
        self.queue = SendQueue()
        hello = {
            "protocol": P.PROTOCOL_VERSION, "name": self.cfg.client_name, "version": self.version, "auth": self.cfg.api_key,
            "hostname": socket.gethostname(), "pid": __import__("os").getpid(), "machine_id": self._machine_id,
            "features": {"lz4": P.lz4_available(), "shm": True, "jpeg": True, "channel_set": True, "upload": True}, "channels": self.engine.hello_channels(),
        }
        sock.sendall(P.pack_json(MsgType.HELLO, hello, 1))
        sock.settimeout(P.HELLO_TIMEOUT_S)
        mtype, _, header, _ = P.read_message(sock)
        if mtype != MsgType.WELCOME:
            raise ProtocolError("伺服端沒有回 WELCOME")
        welcome = P.loads_json(header)
        if not welcome.get("ok"):
            code = str(welcome.get("code") or "rejected")
            message = str(welcome.get("message") or code)
            if code == "auth_failed":
                raise _AuthFailed(message)
            raise _Rejected(message)
        self.welcome = welcome
        self.attempts = 0
        self.connected_since = time.time()
        self._last_rx = time.perf_counter()
        sock.settimeout(max(5.0, self.cfg.heartbeat_s * 3))
        self._sender = SenderThread(sock, self.queue, heartbeat_s=self.cfg.heartbeat_s, on_idle=self._ping, on_error=lambda exc: self._teardown(f"send:{exc}"))
        self._sender.start()
        self._pool = ThreadPoolExecutor(max_workers=max(2, len(self.engine.channels)), thread_name_prefix="vsc-grab")
        self.local_mode = self._decide_local(sock, welcome)
        self._on_update(welcome.get("update") or {})
        self._set_state(ConnState.CONNECTED, "local" if self.local_mode else "")
        log.info("已連上伺服端 %s:%s（%s）", self.cfg.host, self.cfg.port, "同機" if self.local_mode else "跨機")
        if self.local_mode:
            self._negotiate_shm()
        self._reader_loop(sock)

    def _decide_local(self, sock: socket.socket, welcome: dict[str, Any]) -> bool:
        if self.cfg.local_mode == "off":
            return False
        if self.cfg.local_mode == "force":
            return bool(welcome.get("local"))
        return bool(welcome.get("local")) and bool((welcome.get("prefer") or {}).get("shm", True))

    def _negotiate_shm(self) -> None:
        """一條連線一個共享記憶體區段（槽大小＝最大的通道影格），所有啟用的通道共用；容量不夠才重建。"""
        enabled = [ch for ch in self.engine.channels.values() if ch.cfg.enabled]
        if not enabled:
            return
        need = max(int(ch.hello_dict()["max_bytes"]) for ch in enabled)
        slots = plan_slots(min(16, 4 + 2 * len(enabled)), need)
        ring = self._ring
        if ring is not None and ring.slot_bytes >= P.align_slot_bytes(need) and ring.slots >= slots:
            self.rings = {ch.id: ring for ch in enabled}
            return
        if self._pending_ring is not None:
            return  # 上一個協商還在路上
        try:
            new_ring = ShmRing.create(self.cfg.client_name, "ring", slots, need)
        except (OSError, ValueError) as exc:
            log.warning("建立共享記憶體失敗：%s", exc)
            return
        # 協商期間先改走 TCP，並丟掉還沒送出的影格（舊槽索引不能再送）
        self.rings = {}
        self.queue.clear_frames()
        self._pending_ring = new_ring
        req_id = self._next_req()
        self._offers[req_id] = "*"
        self.queue.put_control(P.pack_json(MsgType.SHM_OFFER, new_ring.offer(), req_id))

    def _reader_loop(self, sock: socket.socket) -> None:
        while self._alive and self._sock is sock:
            try:
                mtype, req_id, header, payload = P.read_message(sock)
            except socket.timeout:
                if time.perf_counter() - self._last_rx > max(5.0, self.cfg.heartbeat_s * 3):
                    raise ConnectionError("伺服端沒有回應（心跳逾時）") from None
                continue
            self._last_rx = time.perf_counter()
            if mtype == MsgType.GRAB:
                self._on_grab(req_id, header)
            elif mtype == MsgType.PING:
                self.queue.put_control(P.pack_message(MsgType.PONG, req_id))
            elif mtype == MsgType.PONG:
                sent = self._pings.pop(req_id, None)
                if sent is not None:
                    self.rtt_ms = (time.perf_counter() - sent) * 1000
            elif mtype == MsgType.STREAM:
                self._on_stream(req_id, P.loads_json(header))
            elif mtype == MsgType.CHANNEL_SET:
                # 相機命令要在相機執行緒排隊等結果（NEEDS_STOP 的參數還會停止重啟相機，數百 ms），
                # 不能讓網路讀取執行緒同步等它——否則同一台擷取端上其他通道的 GRAB 全被排在後面。
                # 實測通道 a 的命令卡 800 ms 時，通道 b 的取像延遲 743 ms；改成背景執行緒後 < 50 ms。
                body = P.loads_json(header)
                threading.Thread(target=self._on_channel_set, args=(req_id, body), name="vsc-channel-set", daemon=True).start()
            elif mtype == MsgType.SLOT_FREE:
                chan, slot, seq = P.unpack_slot_free(header)
                cid = self.engine.channel_id(chan)
                ring = self.rings.get(cid) if cid else None
                if ring is not None:
                    ring.release(slot, seq)
            elif mtype == MsgType.SHM_ACCEPT:
                self._on_shm_accept(req_id, P.loads_json(header))
            elif mtype == MsgType.TEST_RESULT:
                self._on_test_result(req_id, P.loads_json(header))
            elif mtype == MsgType.UPDATE:
                self._on_update(P.loads_json(header))
            elif mtype == MsgType.UPDATE_DATA:
                self._on_update_data(req_id, P.loads_json(header), payload)
            elif mtype == MsgType.ERROR:
                body = P.loads_json(header)
                log.warning("伺服端回報錯誤 %s：%s", body.get("code"), body.get("message"))
            elif mtype == MsgType.BYE:
                raise ConnectionError("伺服端關閉連線")

    # ---- 訊息處理 ----
    def _next_req(self) -> int:
        with self._req_lock:
            self._req_counter += 1
            return self._req_counter

    def _ping(self) -> bytes | None:
        req_id = self._next_req()
        self._pings[req_id] = time.perf_counter()
        for old in [k for k, t in self._pings.items() if time.perf_counter() - t > 30]:
            self._pings.pop(old, None)
        return P.pack_message(MsgType.PING, req_id)

    def _on_grab(self, req_id: int, header: bytes) -> None:
        chan, min_seq, timeout_ms, encoding, flags = P.unpack_grab(header)
        pool = self._pool
        if pool is None:
            return
        pool.submit(self._answer_grab, req_id, chan, min_seq, timeout_ms / 1000.0, encoding, flags)

    def _answer_grab(self, req_id: int, chan: int, min_seq: int, timeout: float, encoding: int, flags: int) -> None:
        cid = self.engine.channel_id(chan)
        ch = self.engine.channels.get(cid) if cid else None
        if ch is None:
            self._error(req_id, "no_channel", "沒有此通道")
            return
        if not ch.cfg.enabled:
            self._error(req_id, "channel_disabled", "通道已停用")
            return
        started = time.perf_counter()
        after = bool(flags & GrabFlags.AFTER_REQUEST)
        try:
            frame = ch.acquire(min_seq, timeout, after_request=after)
        except Exception as exc:  # noqa: BLE001
            self._error(req_id, "camera_error", str(exc))
            return
        if frame is None:
            self._error(req_id, "timeout" if ch.state.value == "running" else "camera_error", ch.last_error or "取像逾時")
            return
        try:
            ring = self.rings.get(cid)
            fields, arr = prepare(frame, ch.cfg.roi, ch.cfg.delivery, force_raw=ring is not None)
            fresh = FrameFlags.FRESH if after else 0
            if ring is not None:
                remaining = max(0.0, timeout - (time.perf_counter() - started))
                slot = ring.wait_write(frame.seq, arr, min(0.2, remaining))
                if slot is not None:
                    hdr = FrameHeader.for_image(chan, frame.seq, frame.ts_ns, fields["width"], fields["height"], fields["channels"], fields["dtype"],
                                                roi_x=fields["roi_x"], roi_y=fields["roi_y"], full_w=fields["full_w"], full_h=fields["full_h"],
                                                flags=fields["flags"] | fresh, slot=slot, captured_at_ms=frame.ts_ns // 1_000_000)
                    self.queue.put_reply(P.pack_message(MsgType.FRAME, req_id, hdr.pack()))
                    self.frames_sent += 1
                    return
                fields["encoding"] = int(Encoding.RAW)
            if encoding != Encoding.AUTO:
                fields["encoding"] = int(encoding)
                if encoding == Encoding.LZ4 and not P.lz4_available():
                    fields["encoding"] = int(Encoding.RAW)
                if encoding == Encoding.JPEG and arr.dtype.name != "uint8":
                    fields["encoding"] = int(Encoding.RAW)
            hdr = FrameHeader.for_image(chan, frame.seq, frame.ts_ns, fields["width"], fields["height"], fields["channels"], fields["dtype"],
                                        roi_x=fields["roi_x"], roi_y=fields["roi_y"], full_w=fields["full_w"], full_h=fields["full_h"],
                                        encoding=fields["encoding"], flags=fields["flags"] | fresh, captured_at_ms=frame.ts_ns // 1_000_000)
            item, nbytes = frame_item(MsgType.FRAME, req_id, hdr, arr, fields["encoding"], ch.cfg.delivery.jpeg_quality)
            self.queue.put_reply(item)
            self.frames_sent += 1
            self.bytes_sent += nbytes
        except Exception as exc:  # noqa: BLE001
            log.exception("回覆 GRAB 失敗")
            self._error(req_id, "camera_error", str(exc))

    def _error(self, req_id: int, code: str, message: str) -> None:
        self.queue.put_control(P.pack_json(MsgType.ERROR, {"code": code, "message": message}, req_id))

    def _channel_result(self, req_id: int, body: dict[str, Any]) -> None:
        body.setdefault("ok", False)
        body.setdefault("applied", {})
        body.setdefault("errors", {})
        body.setdefault("message", "")
        self.queue.put_control(P.pack_json(MsgType.CHANNEL_RESULT, body, req_id))

    def _on_stream(self, req_id: int, body: dict[str, Any]) -> None:
        cid = str(body.get("channel") or "")
        enabled = bool(body.get("enabled"))
        ch = self.engine.channels.get(cid)
        ok = ch is not None
        if ok:
            pusher = self._pushers.pop(cid, None)
            if pusher is not None:
                pusher.stop()
            if enabled:
                pusher = StreamPusher(ch, self, self.engine.channel_index(cid), float(body.get("max_fps") or 0))
                self._pushers[cid] = pusher
                pusher.start()
        self.queue.put_control(P.pack_json(MsgType.STREAM, {"channel": cid, "enabled": enabled, "ok": ok}, req_id))
        self.engine.events.emit("stream", {"id": cid, "enabled": enabled and ok})

    def _on_channel_set(self, req_id: int, body: dict[str, Any]) -> None:
        cid = str(body.get("channel") or "")
        ch = self.engine.channels.get(cid)
        if ch is None:
            self._channel_result(req_id, {"ok": False, "errors": {"channel": "no such channel"}, "message": "No such channel"})
            return
        if not ch.cfg.enabled:
            self._channel_result(req_id, {"ok": False, "errors": {"channel": "channel disabled"}, "message": "Channel disabled"})
            return
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        command = str(body.get("command") or "")
        args = body.get("args") if isinstance(body.get("args"), dict) else {}
        applied: dict[str, Any] = {}
        errors: dict[str, str] = {}
        messages: list[str] = []

        if command == "load_user_set":
            name = str(args.get("name") or "")
            try:
                ch.load_user_set(name)
                applied.update(ch.param_values())
            except Exception as exc:  # noqa: BLE001
                errors["user_set"] = str(exc)
        elif command and command not in ("line_out", "save_user_set"):
            errors["command"] = f"unknown command: {command}"

        if params:
            try:
                applied.update(ch.set_params(dict(params)))
            except CameraParamError as exc:
                errors.update({str(k): str(v) for k, v in exc.errors.items()})
                applied.update(ch.param_values(set(params)))
            except Exception as exc:  # noqa: BLE001
                errors["params"] = str(exc)
                applied.update(ch.param_values(set(params)))

        if command == "line_out":
            line = str(args.get("line") or "")
            level = _bool_arg(args.get("level"))
            pulse_ms = max(0, _int_arg(args.get("pulse_ms"), 0))
            try:
                ch.set_output(line, level)
                applied[f"output:{line}"] = level
                if pulse_ms > 0:
                    self._schedule_output_reset(ch, line, not level, pulse_ms / 1000.0)
                    messages.append("pulse scheduled")
            except Exception as exc:  # noqa: BLE001
                errors["line_out"] = str(exc)
        elif command == "save_user_set":
            name = str(args.get("name") or "")
            try:
                ch.save_user_set(name)
            except Exception as exc:  # noqa: BLE001
                errors["user_set"] = str(exc)

        ok = not errors
        self._channel_result(req_id, {"ok": ok, "applied": applied, "errors": errors, "message": "; ".join(messages)})

    def _schedule_output_reset(self, ch, line: str, level: bool, delay_s: float) -> None:
        timer: threading.Timer | None = None

        def run() -> None:
            try:
                ch.set_output(line, level)
            except Exception:  # noqa: BLE001
                log.debug("camera output pulse reset failed", exc_info=True)
            finally:
                if timer is not None:
                    with self._pulse_lock:
                        self._pulse_timers.discard(timer)

        timer = threading.Timer(delay_s, run)
        timer.daemon = True
        with self._pulse_lock:
            self._pulse_timers.add(timer)
        timer.start()

    def _on_shm_accept(self, req_id: int, body: dict[str, Any]) -> None:
        self._offers.pop(req_id, None)
        ring, self._pending_ring = self._pending_ring, None
        if ring is None:
            return
        if body.get("ok"):
            old, self._ring = self._ring, ring
            if old is not None:
                old.close()
            self.rings = {ch.id: ring for ch in self.engine.channels.values() if ch.cfg.enabled}
            log.info("改走共享記憶體（%d 槽，每槽 %d 位元組）", ring.slots, ring.slot_bytes)
        else:
            log.info("共享記憶體未被接受：%s", body.get("error"))
            ring.close()

    # ---- 自動更新 ----
    def _on_update(self, body: dict[str, Any]) -> None:
        info = UpdateInfo.from_dict(body)
        self.update = info
        if info.available:
            log.info("伺服端有新版擷取端 %s（%.1f MB）", info.version, info.size / 1e6)
        self.engine.events.emit("update", {"info": info})

    def _on_update_data(self, req_id: int, body: dict[str, Any], payload: bytes | bytearray) -> None:
        fut = self._pulls.pop(req_id, None)
        if fut is None or fut.cancelled():
            return
        error = str(body.get("error") or "")
        if error:
            fut.set_exception(RuntimeError(error))
            return
        fut.set_result((bytes(payload), bool(body.get("eof"))))

    def pull_update(self, offset: int, length: int, timeout: float = 30.0) -> tuple[bytes, bool]:
        """向伺服端要安裝檔的一段（走同一條已驗證的連線）；回 (資料, 是否到檔尾)。"""
        if self.state != ConnState.CONNECTED:
            raise RuntimeError("尚未連線")
        req_id = self._next_req()
        fut: Future = Future()
        self._pulls[req_id] = fut
        try:
            self.queue.put_control(P.pack_json(MsgType.UPDATE_PULL, {"offset": int(offset), "length": int(length)}, req_id))
            return fut.result(timeout)
        finally:
            self._pulls.pop(req_id, None)

    def upload_file(self, path: str | Path, *, cancel: threading.Event | None = None, on_progress=None) -> dict[str, Any]:
        """把錄影檔逐塊上傳到伺服端；走已驗證連線的控制佇列，不進影格路徑。"""
        if self.state != ConnState.CONNECTED:
            raise RuntimeError("Not connected")
        features = self.welcome.get("features") if isinstance(self.welcome.get("features"), dict) else {}
        if not bool(features.get("upload")):
            raise RuntimeError("The server does not support video upload; update the server")
        src = Path(path)
        size = src.stat().st_size
        digest = hashlib.sha256()
        with src.open("rb") as fh:
            for chunk in iter(lambda: fh.read(P.UPLOAD_CHUNK_BYTES), b""):
                digest.update(chunk)
        sha = digest.hexdigest()
        upload_id = uuid.uuid4().hex
        header = {"id": upload_id, "filename": src.name, "size": size, "sha256": sha, "chunk": P.UPLOAD_CHUNK_BYTES}
        self.queue.put_control(P.pack_json(MsgType.UPLOAD_BEGIN, header, self._next_req()))
        sent = 0
        try:
            with src.open("rb") as fh:
                while True:
                    if cancel is not None and cancel.is_set():
                        self.queue.put_control(P.pack_json(MsgType.UPLOAD_END, {"id": upload_id, "filename": src.name, "cancel": True}, self._next_req()))
                        return {"ok": False, "cancelled": True, "sent": sent, "size": size}
                    chunk = fh.read(P.UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    self.queue.put_control(P.pack_message(MsgType.UPLOAD_DATA, self._next_req(), P.dumps_json({"id": upload_id, "offset": sent}), chunk))
                    sent += len(chunk)
                    if callable(on_progress):
                        on_progress(sent, size)
            self.queue.put_control(P.pack_json(MsgType.UPLOAD_END, {"id": upload_id, "filename": src.name, "size": size, "sha256": sha}, self._next_req()))
            return {"ok": True, "cancelled": False, "sent": sent, "size": size, "sha256": sha}
        except Exception:
            self.queue.put_control(P.pack_json(MsgType.UPLOAD_END, {"id": upload_id, "filename": src.name, "cancel": True}, self._next_req()))
            raise

    def _on_test_result(self, req_id: int, body: dict[str, Any]) -> None:
        entry = self._tests.pop(req_id, None)
        if entry is None:
            return
        fut, t0, nbytes = entry
        fut.set_result({"rtt_ms": round((time.perf_counter() - t0) * 1000, 2), "bytes": nbytes, "encode_ms": round(getattr(fut, "encode_ms", 0.0), 2), "decode_ms": body.get("decode_ms")})

    # ---- 拆除 ----
    def _send_bye(self) -> None:
        sock = self._sock
        if sock is not None and self.state == ConnState.CONNECTED:
            try:
                sock.sendall(P.pack_message(MsgType.BYE))
            except OSError:
                pass

    def _teardown(self, reason: str) -> None:
        sock, self._sock = self._sock, None
        with self._pulse_lock:
            timers = list(self._pulse_timers)
            self._pulse_timers.clear()
        for timer in timers:
            timer.cancel()
        for p in list(self._pushers.values()):
            p.stop()
        self._pushers.clear()
        self.queue.close()
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self.rings = {}
        for ring in (self._ring, self._pending_ring):
            if ring is not None:
                ring.close()
        self._ring = self._pending_ring = None
        for fut, _, _ in self._tests.values():
            if not fut.done():
                fut.set_exception(RuntimeError("連線已中斷"))
        self._tests.clear()
        for pull in self._pulls.values():
            if not pull.done():
                pull.set_exception(RuntimeError("連線已中斷"))
        self._pulls.clear()
        self.local_mode = False
        if self.state == ConnState.CONNECTED:
            self.connected_since = None
            self._set_state(ConnState.RECONNECTING if self._alive else ConnState.DISCONNECTED, reason)


class _AuthFailed(Exception):
    pass


class _Rejected(Exception):
    pass
