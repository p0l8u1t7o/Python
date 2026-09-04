"""擷取端伺服端：協定、hub（握手／取像／串流／共享記憶體／失效）、CaptureGrabber、API、整條 run。

假擷取端 `FakeCaptureClient` 用 vscapture.protocol 走 loopback，不需要相機；hub 執行緒不碰 DB，
只有跑 runner 的 CaptureRunTests 需要 TransactionTestCase。
"""

from __future__ import annotations

import json
import socket
import threading
import time
from multiprocessing import shared_memory
from unittest import mock

import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from apps.core.errors import ValidationError
from apps.vision import sources
from apps.vision.capture import hub as hubmod
from apps.vision.capture.grabber import CaptureGrabber
from apps.vision.capture.hub import CaptureError, hub
from apps.vision.models import Flow, ImageSource
from tests.test_comm import free_port
from vscapture import protocol as P
from vscapture.protocol import Encoding, FrameFlags, FrameHeader, GrabFlags, MsgType, ProtocolError

try:
    import lz4.block  # noqa: F401

    HAS_LZ4 = True
except ImportError:
    HAS_LZ4 = False


def _default_channels():
    return [{"id": "cam0", "label": "Fake cam", "driver": "fake", "width": 64, "height": 48, "channels": 1, "dtype": "u8"}]


class FakeCaptureClient(threading.Thread):
    """會說協定 v1 的假擷取端：HELLO → 回答 GRAB／STREAM／PING、可推串流、可走共享記憶體。"""

    def __init__(self, port, name="fake", channels=None, *, auth="", transport="tcp", encoding="raw", protocol=1, machine_id="m1",
                 hostname=None, answer_grabs=True, answer_pings=True, slots=2, bad_canary=False, frame_factory=None):
        super().__init__(daemon=True)
        self.port, self.client_name, self.auth, self.transport = port, name, auth, transport
        self.encoding, self.protocol, self.machine_id = encoding, protocol, machine_id
        self.hostname = socket.gethostname() if hostname is None else hostname
        self.answer_grabs, self.answer_pings, self.slots, self.bad_canary = answer_grabs, answer_pings, slots, bad_canary
        self.frame_factory = frame_factory
        self.channels = [dict(c) for c in (channels or _default_channels())]
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.welcome: dict | None = None
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.received: list[tuple[int, int, bytes]] = []
        self.grabs: list[tuple] = []
        self.slot_free: list[tuple[int, int]] = []
        self.shm: shared_memory.SharedMemory | None = None
        self.shm_accepted: bool | None = None
        self.free_slots: list[int] = []
        self.seq = {c["id"]: 0 for c in self.channels}
        self._send_lock = threading.Lock()
        self._canary = 0

    # ---- 影格 ----
    def spec(self, chan):
        return self.channels[chan]

    def make_image(self, chan, seq):
        c = self.spec(chan)
        if self.frame_factory:
            return self.frame_factory(c, seq)
        dtype = P.NUMPY_DTYPES[P.DTYPE_CODES[c.get("dtype", "u8")]]
        shape = (c["height"], c["width"]) if c.get("channels", 1) == 1 else (c["height"], c["width"], c["channels"])
        return np.full(shape, seq % 250, dtype=dtype)

    def send(self, mtype, req_id=0, header=b"", payload=b""):
        with self._send_lock:
            self.sock.sendall(P.pack_envelope(mtype, req_id, len(header), len(payload)) + bytes(header) + bytes(payload))

    def send_raw(self, data):
        with self._send_lock:
            self.sock.sendall(data)

    def _header_for(self, chan, seq, img, encoding, flags=0, slot=-1):
        c = self.spec(chan)
        ch = 1 if img.ndim == 2 else img.shape[2]
        roi = c.get("roi") or {}
        return FrameHeader.for_image(chan, seq, time.time_ns(), img.shape[1], img.shape[0], ch, P.DTYPE_CODES[str(img.dtype).replace("uint8", "u8").replace("uint16", "u16").replace("float32", "f32")],
                                     roi_x=roi.get("x", 0), roi_y=roi.get("y", 0), full_w=(c.get("full") or {}).get("w"), full_h=(c.get("full") or {}).get("h"),
                                     encoding=encoding, flags=flags, slot=slot)

    def send_frame(self, chan, seq, img, *, req_id=0, encoding=None, flags=0, mtype=MsgType.FRAME):
        enc = self.encoding if encoding is None else encoding
        img = np.ascontiguousarray(img)
        if self.transport == "shm" and self.shm_accepted and self.free_slots:
            slot = self.free_slots.pop(0)
            off = P.slot_offset(slot, self._slot_bytes)
            view = np.ndarray(img.shape, img.dtype, buffer=self.shm.buf, offset=off)
            view[...] = img
            del view
            self.send(mtype, req_id, self._header_for(chan, seq, img, Encoding.RAW, flags, slot).pack())
            return
        if enc == "lz4":
            payload = P.compress_lz4(img.data.cast("B"))
            code = Encoding.LZ4
        elif enc == "jpeg":
            import cv2

            payload = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()
            code = Encoding.JPEG
        else:
            payload = img.tobytes()
            code = Encoding.RAW
        self.send(mtype, req_id, self._header_for(chan, seq, img, code, flags).pack(), payload)

    def push(self, cid="cam0", img=None):
        chan = [c["id"] for c in self.channels].index(cid)
        self.seq[cid] += 1
        self.send_frame(chan, self.seq[cid], self.make_image(chan, self.seq[cid]) if img is None else img)
        return self.seq[cid]

    # ---- 執行緒 ----
    def run(self):
        try:
            self.send(MsgType.HELLO, 1, P.dumps_json({
                "protocol": self.protocol, "name": self.client_name, "version": "0.1.0", "auth": self.auth, "hostname": self.hostname, "pid": 1,
                "machine_id": self.machine_id, "features": {"lz4": HAS_LZ4, "shm": True, "jpeg": True}, "channels": self.channels,
            }))
            mtype, req_id, header, _ = P.read_message(self.sock)
            self.welcome = P.loads_json(header) if mtype == MsgType.WELCOME else {"ok": False, "code": f"type{mtype}"}
            self.ready.set()
            if not self.welcome.get("ok"):
                return
            if self.transport == "shm":
                self._offer_shm()
            while True:
                mtype, req_id, header, payload = P.read_message(self.sock)
                self.received.append((mtype, req_id, bytes(header)))
                if mtype == MsgType.GRAB:
                    self._on_grab(req_id, header)
                elif mtype == MsgType.PING:
                    if self.answer_pings:
                        self.send(MsgType.PONG, req_id)
                elif mtype == MsgType.STREAM:
                    body = P.loads_json(header)
                    self.send(MsgType.STREAM, req_id, P.dumps_json({**body, "ok": True}))
                elif mtype == MsgType.SLOT_FREE:
                    _, slot, seq = P.unpack_slot_free(header)
                    self.slot_free.append((slot, seq))
                    self.free_slots.append(slot)
                elif mtype == MsgType.SHM_ACCEPT:
                    self.shm_accepted = bool(P.loads_json(header).get("ok"))
        except (ConnectionError, OSError, ProtocolError):
            pass
        finally:
            self.closed.set()
            try:
                self.sock.close()
            except OSError:
                pass

    def _offer_shm(self):
        spec = self.channels[0]
        self._slot_bytes = P.align_slot_bytes(max(P.frame_nbytes(c["width"], c["height"], c.get("channels", 1), P.DTYPE_CODES[c.get("dtype", "u8")]) for c in self.channels))
        self._canary = int(time.time_ns()) & 0xFFFFFFFF
        self.shm = shared_memory.SharedMemory(create=True, size=P.segment_size(self.slots, self._slot_bytes))
        self.shm.buf[: P.SEG_HEADER_BYTES] = P.pack_seg_header(self._canary + (1 if self.bad_canary else 0), self.slots, self._slot_bytes)
        self.free_slots = list(range(self.slots))
        self.send(MsgType.SHM_OFFER, 2, P.dumps_json({"name": self.shm.name, "slots": self.slots, "slot_bytes": self._slot_bytes, "canary": self._canary}))
        del spec

    def _on_grab(self, req_id, header):
        chan, min_seq, timeout_ms, encoding, flags = P.unpack_grab(header)
        self.grabs.append((chan, min_seq, timeout_ms, encoding, flags))
        if self.answer_grabs is False:
            return
        if self.answer_grabs == "error":
            self.send(MsgType.ERROR, req_id, P.dumps_json({"code": "camera_error", "message": "假相機故障"}))
            return
        if self.answer_grabs == "close":
            self.sock.close()
            return
        cid = self.channels[chan]["id"]
        seq = max(self.seq[cid] + 1, min_seq + 1)
        self.seq[cid] = seq
        enc = None
        if encoding != Encoding.AUTO:
            enc = P.ENCODING_NAMES[encoding]
        self.send_frame(chan, seq, self.make_image(chan, seq), req_id=req_id, encoding=enc, flags=FrameFlags.FRESH if flags & GrabFlags.AFTER_REQUEST else 0)

    def wait_ready(self, timeout=5.0):
        self.ready.wait(timeout)
        return self.welcome

    def close(self):
        try:
            self.send(MsgType.BYE)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self.join(timeout=3)
        if self.shm is not None:
            try:
                self.shm.close()
                self.shm.unlink()
            except (OSError, BufferError):
                pass


def _wait(pred, timeout=3.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


# ---------------------------------------------------------------------------
class ProtoTests(SimpleTestCase):
    def test_struct_sizes(self):
        self.assertEqual((P.ENVELOPE.size, P.GRAB_HDR.size, P.FRAME_HDR.size, P.SLOT_HDR.size), (16, 16, 64, 16))
        self.assertLessEqual(P.SEG_HDR.size, P.SEG_HEADER_BYTES)

    def test_envelope_roundtrip_and_errors(self):
        buf = P.pack_envelope(MsgType.GRAB, 7, 16, 0)
        self.assertEqual(P.unpack_envelope(buf), (MsgType.GRAB, 7, 16, 0))
        with self.assertRaises(ProtocolError):
            P.unpack_envelope(b"\0" * 16)
        bad = bytearray(buf)
        bad[2] = 9
        with self.assertRaises(ProtocolError) as cm:
            P.unpack_envelope(bad)
        self.assertEqual(cm.exception.code, "protocol_unsupported")

    def test_frame_header(self):
        h = FrameHeader.for_image(1, 42, 123, 64, 48, 3, 0, roi_x=10, roi_y=5, full_w=640, full_h=480)
        h2 = FrameHeader.unpack(h.pack())
        self.assertEqual(h, h2)
        self.assertTrue(h.flags & FrameFlags.CROPPED)
        self.assertEqual(h.shape(), (48, 64, 3))
        self.assertEqual(h.raw_len, 64 * 48 * 3)
        h.validate(2, 1 << 20, h.raw_len)
        with self.assertRaises(ProtocolError):
            h.validate(1, 1 << 20, h.raw_len)  # chan 超出
        with self.assertRaises(ProtocolError):
            h.validate(2, 1 << 20, h.raw_len - 1)  # plen 不符
        with self.assertRaises(ProtocolError) as cm:
            h.validate(2, 100, h.raw_len)
        self.assertEqual(cm.exception.code, "too_large")
        h.stride += 1
        with self.assertRaises(ProtocolError):
            h.validate(2, 1 << 20, h.raw_len)
        s = FrameHeader.for_image(0, 1, 0, 8, 8, 1, 0, slot=1)
        with self.assertRaises(ProtocolError):
            s.validate(1, 1 << 20, 0)  # 沒有 shm
        s.validate(1, 1 << 20, 0, shm_slots=2, slot_bytes=4096)

    def test_names_and_channels(self):
        self.assertEqual(P.validate_name(" line1-PC.a "), "line1-PC.a")
        with self.assertRaises(ProtocolError):
            P.validate_name("有中文")
        c = P.validate_channel_dict({"id": "cam0", "width": 640, "height": 480, "channels": 3, "dtype": "u8", "mode": "bogus"})
        self.assertEqual((c["mode"], c["full"], c["roi"]["w"], c["max_bytes"], c["pixel_format"]), ("on_demand", {"w": 640, "h": 480}, 640, 640 * 480 * 3, "BGR8"))
        with self.assertRaises(ProtocolError):
            P.validate_channel_dict({"id": "bad id", "width": 1, "height": 1})
        hdr = P.pack_seg_header(99, 4, 4096)
        self.assertEqual(len(hdr), P.SEG_HEADER_BYTES)
        self.assertEqual(P.unpack_seg_header(hdr), (99, 4, 4096))
        self.assertEqual(P.align_slot_bytes(1), 4096)
        self.assertEqual(P.slot_offset(2, 4096), P.SEG_HEADER_BYTES + 8192)


# ---------------------------------------------------------------------------
class _HubBase(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.port = free_port()
        hub.start("127.0.0.1", cls.port)

    @classmethod
    def tearDownClass(cls):
        hub.stop()
        super().tearDownClass()

    def setUp(self):
        self.clients: list[FakeCaptureClient] = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        _wait(lambda: not hub.clients(), 2.0)
        with hub._lock:  # noqa: SLF001
            hub._stream_refs.clear()
            hub._stream_wanted.clear()
            hub._users.clear()

    def connect(self, **kw) -> FakeCaptureClient:
        c = FakeCaptureClient(self.port, **kw)
        self.clients.append(c)
        c.start()
        c.wait_ready()
        return c


class HubTests(_HubBase):
    def test_hello_registers_local_client(self):
        c = self.connect(name="pc1")
        self.assertTrue(c.welcome["ok"], c.welcome)
        self.assertTrue(c.welcome["local"])
        self.assertTrue(_wait(lambda: any(x["name"] == "pc1" for x in hub.clients())))
        item = next(x for x in hub.clients() if x["name"] == "pc1")
        self.assertEqual(item["channels"][0]["id"], "cam0")
        self.assertEqual(item["channels"][0]["width"], 64)
        self.assertTrue(item["local"])

    def test_remote_hostname_is_not_local(self):
        c = self.connect(name="pc2", hostname="OTHER-PC")
        self.assertFalse(c.welcome["local"])
        self.assertEqual(c.welcome["prefer"]["encoding"], "lz4" if HAS_LZ4 else "raw")

    def test_auth_and_protocol_version(self):
        with override_settings(VISION={**settings.VISION, "CAPTURE_AUTH": "k"}):
            bad = self.connect(name="pc3", auth="wrong")
            self.assertEqual(bad.welcome["code"], "auth_failed")
            ok = self.connect(name="pc3", auth="k")
            self.assertTrue(ok.welcome["ok"])
        old = self.connect(name="pc4", protocol=2)
        self.assertEqual(old.welcome["code"], "protocol_unsupported")

    def test_duplicate_name(self):
        a = self.connect(name="dup", machine_id="m1")
        b = self.connect(name="dup", machine_id="m1")  # 同機重連：取代
        self.assertTrue(b.welcome["ok"])
        self.assertTrue(_wait(lambda: a.closed.is_set()))
        c = self.connect(name="dup", machine_id="m2")  # 異機：拒絕
        self.assertEqual(c.welcome["code"], "name_taken")

    def test_grab_fresh_and_buffered(self):
        self.connect(name="g1")
        f1 = hub.request_frame("g1", "cam0", timeout=1.0)
        f2 = hub.request_frame("g1", "cam0", timeout=1.0, min_seq=f1.meta.seq)
        self.assertGreater(f2.meta.seq, f1.meta.seq)
        self.assertTrue(f2.meta.fresh)
        self.assertEqual(f2.image.shape, (48, 64))
        self.assertEqual(int(f2.image[0, 0]), f2.meta.seq % 250)
        self.assertEqual(f2.meta.encoding, "raw")
        f3 = hub.request_frame("g1", "cam0", timeout=1.0, after_request=False)
        self.assertFalse(f3.meta.fresh)
        self.assertGreater(f3.meta.latency_ms, 0)
        item = next(x for x in hub.clients() if x["name"] == "g1")["channels"][0]
        self.assertEqual(item["seq"], f3.meta.seq)
        self.assertIsNotNone(item["last_frame_age_ms"])

    def test_shapes_dtypes_and_roi_meta(self):
        chans = [
            {"id": "bgr", "width": 32, "height": 16, "channels": 3, "dtype": "u8", "roi": {"x": 10, "y": 20, "w": 32, "h": 16}, "full": {"w": 640, "h": 480}},
            {"id": "u16", "width": 8, "height": 8, "channels": 1, "dtype": "u16"},
            {"id": "f32", "width": 8, "height": 4, "channels": 1, "dtype": "f32"},
        ]
        self.connect(name="s1", channels=chans)
        f = hub.request_frame("s1", "bgr", timeout=1.0)
        self.assertEqual((f.image.shape, f.image.dtype), ((16, 32, 3), np.dtype("uint8")))
        self.assertEqual((f.meta.roi_x, f.meta.roi_y, f.meta.full_w, f.meta.full_h), (10, 20, 640, 480))
        self.assertEqual(hub.request_frame("s1", "u16", timeout=1.0).image.dtype, np.dtype("uint16"))
        self.assertEqual(hub.request_frame("s1", "f32", timeout=1.0).image.dtype, np.dtype("float32"))
        self.assertTrue(hub.request_frame("s1", "bgr", timeout=1.0).image.flags["C_CONTIGUOUS"])

    def test_lz4_and_jpeg(self):
        if HAS_LZ4:
            c = self.connect(name="z1", encoding="lz4")
            f = hub.request_frame("z1", "cam0", timeout=1.0, encoding=Encoding.LZ4)
            self.assertEqual(f.meta.encoding, "lz4")
            np.testing.assert_array_equal(f.image, c.make_image(0, f.meta.seq))
            with mock.patch.object(hubmod, "lz4_block", None):
                with self.assertRaises(CaptureError) as cm:
                    hub.request_frame("z1", "cam0", timeout=1.0, encoding=Encoding.LZ4)
                self.assertEqual(cm.exception.code, "unsupported_encoding")
            f = hub.request_frame("z1", "cam0", timeout=1.0, encoding=Encoding.RAW)  # 連線仍在
            self.assertEqual(f.meta.encoding, "raw")
        j = self.connect(name="j1", encoding="jpeg", channels=[{"id": "cam0", "width": 64, "height": 48, "channels": 3, "dtype": "u8"}])
        f = hub.request_frame("j1", "cam0", timeout=1.0, encoding=Encoding.JPEG)
        self.assertEqual((f.image.shape, f.meta.encoding), ((48, 64, 3), "jpeg"))
        self.assertLess(abs(int(f.image[0, 0, 0]) - f.meta.seq % 250), 6)
        del j

    def test_timeout_error_and_disconnect(self):
        self.connect(name="t1", answer_grabs=False)
        t0 = time.monotonic()
        with self.assertRaises(CaptureError) as cm:
            hub.request_frame("t1", "cam0", timeout=0.3)
        self.assertEqual(cm.exception.code, "timeout")
        self.assertLess(time.monotonic() - t0, 1.5)
        self.connect(name="t2", answer_grabs="error")
        with self.assertRaises(CaptureError) as cm:
            hub.request_frame("t2", "cam0", timeout=1.0)
        self.assertEqual(cm.exception.code, "camera_error")
        self.connect(name="t3", answer_grabs="close")
        with self.assertRaises(CaptureError) as cm:
            hub.request_frame("t3", "cam0", timeout=2.0)
        self.assertEqual(cm.exception.code, "disconnected")
        self.assertTrue(_wait(lambda: hub.get("t3") is None))
        with self.assertRaises(CaptureError) as cm:
            hub.request_frame("t3", "cam0", timeout=0.2)
        self.assertEqual(cm.exception.code, "client_offline")
        with self.assertRaises(CaptureError) as cm:
            hub.request_frame("t1", "nope", timeout=0.2)
        self.assertEqual(cm.exception.code, "no_channel")

    def test_stream_latest_and_wait(self):
        c = self.connect(name="st1")
        session = hub.get("st1")
        hub.set_stream("st1", "cam0", True)
        self.assertTrue(_wait(lambda: session.by_id["cam0"].streaming))
        for _ in range(3):
            c.push("cam0")
        self.assertTrue(_wait(lambda: (hub.latest("st1", "cam0") or Frame0).meta.seq == 3))
        threading.Timer(0.1, c.push, args=("cam0",)).start()
        f = hub.wait_for_seq("st1", "cam0", 3, 1.0)
        self.assertEqual(f.meta.seq, 4)
        with self.assertRaises(CaptureError) as cm:
            hub.wait_for_seq("st1", "cam0", 4, 0.2)
        self.assertEqual(cm.exception.code, "timeout")
        hub.set_stream("st1", "cam0", False)
        self.assertTrue(_wait(lambda: not session.by_id["cam0"].streaming))
        item = next(x for x in hub.clients() if x["name"] == "st1")["channels"][0]
        self.assertEqual(item["mode"], "on_demand")

    def test_shared_memory_roundtrip(self):
        c = self.connect(name="shm1", transport="shm", slots=2)
        self.assertTrue(_wait(lambda: c.shm_accepted is not None))
        self.assertTrue(c.shm_accepted)
        session = hub.get("shm1")
        self.assertIsNotNone(session.shm)
        seqs = []
        for _ in range(8):
            f = hub.request_frame("shm1", "cam0", timeout=1.0)
            self.assertTrue(f.meta.shm)
            self.assertEqual(f.meta.encoding, "shm")
            np.testing.assert_array_equal(f.image, c.make_image(0, f.meta.seq))
            seqs.append(f.meta.seq)
        self.assertEqual(len(seqs), len(set(seqs)))
        self.assertTrue(_wait(lambda: len(c.slot_free) == 8))
        self.assertEqual(sorted(c.free_slots), [0, 1])
        item = next(x for x in hub.clients() if x["name"] == "shm1")
        self.assertTrue(item["shm"])
        self.assertTrue(item["channels"][0]["shm"])
        self.assertIn("recv_ms", item["channels"][0])
        # 接收緩衝要重用：8 張只配置少數幾個（20MP 時每次重配要多花 15 ms）
        pool = session.channels[0].pool
        self.assertGreaterEqual(pool.hits, 4)
        self.assertLessEqual(pool.stats()["buffers"], 3)

    def test_shared_memory_rejected_falls_back(self):
        c = self.connect(name="shm2", transport="shm", bad_canary=True)
        self.assertTrue(_wait(lambda: c.shm_accepted is not None))
        self.assertFalse(c.shm_accepted)
        self.assertIsNone(hub.get("shm2").shm)
        f = hub.request_frame("shm2", "cam0", timeout=1.0)
        self.assertFalse(f.meta.shm)
        r = self.connect(name="shm3", transport="shm", hostname="REMOTE")
        self.assertTrue(_wait(lambda: r.shm_accepted is not None))
        self.assertFalse(r.shm_accepted)

    def test_oversize_and_garbage_close_connection(self):
        big = self.connect(name="big")
        big.send_raw(P.pack_envelope(MsgType.FRAME, 1, P.FRAME_HDR.size, hub.max_frame_bytes() + 1))
        self.assertTrue(_wait(lambda: hub.get("big") is None))
        junk = self.connect(name="junk")
        junk.send_raw(b"\0" * 16)
        self.assertTrue(_wait(lambda: hub.get("junk") is None))

    def test_ping_pong_and_heartbeat(self):
        c = self.connect(name="hb1")
        c.send(MsgType.PING, 5)
        self.assertTrue(_wait(lambda: any(t == MsgType.PONG and r == 5 for t, r, _ in c.received)))
        with mock.patch.object(P, "HEARTBEAT_S", 0.2):
            dead = self.connect(name="hb2", answer_pings=False)
            self.assertTrue(_wait(lambda: hub.get("hb2") is None, 3.0))
            self.assertTrue(any(t == MsgType.PING for t, _, _ in dead.received))

    def test_channels_update_keeps_indices(self):
        c = self.connect(name="ch1")
        c.channels = [{**c.channels[0], "enabled": False}, {"id": "cam1", "width": 16, "height": 8, "channels": 1, "dtype": "u8"}]
        c.seq["cam1"] = 0
        c.send(MsgType.CHANNELS, 0, P.dumps_json({"channels": c.channels}))
        self.assertTrue(_wait(lambda: "cam1" in hub.get("ch1").by_id))
        with self.assertRaises(CaptureError) as cm:
            hub.request_frame("ch1", "cam0", timeout=0.5)
        self.assertEqual(cm.exception.code, "channel_disabled")
        f = hub.request_frame("ch1", "cam1", timeout=1.0)
        self.assertEqual(f.image.shape, (8, 16))
        self.assertEqual(c.grabs[-1][0], 1)


class Frame0:
    class meta:
        seq = 0


# ---------------------------------------------------------------------------
class CaptureGrabberTests(_HubBase):
    def tearDown(self):
        sources.close_all()
        super().tearDown()

    def test_on_demand_and_fresh(self):
        c = self.connect(name="gr1")
        g = CaptureGrabber({"client": "gr1", "channel": "cam0", "timeout_ms": 1000}, source_id=1, name="來源A")
        a = g.grab()
        b = g.grab()
        self.assertIsNotNone(a)
        self.assertEqual(g.frames, 2)
        self.assertEqual(int(b[0, 0]), g.last_seq % 250)
        self.assertEqual(c.grabs[-1][4] & GrabFlags.AFTER_REQUEST, GrabFlags.AFTER_REQUEST)
        info = g.info()
        self.assertTrue(info["connected"])
        self.assertEqual((info["client"], info["channel"], info["mode"], info["seq"]), ("gr1", "cam0", "on_demand", g.last_seq))
        self.assertIn("age_ms", info)
        self.assertIn("來源A", hub.users_of("gr1", "cam0"))
        g2 = CaptureGrabber({"client": "gr1", "channel": "cam0", "fresh": False}, source_id=2, name="來源B")
        g2.grab()
        self.assertEqual(c.grabs[-1][4], 0)
        g.close()
        self.assertNotIn("來源A", hub.users_of("gr1", "cam0"))

    def test_stream_mode(self):
        c = self.connect(name="gr2")
        g = CaptureGrabber({"client": "gr2", "channel": "cam0", "mode": "stream", "timeout_ms": 800}, source_id=3, name="串流來源")
        session = hub.get("gr2")
        self.assertTrue(_wait(lambda: session.by_id["cam0"].streaming))
        threading.Timer(0.1, c.push, args=("cam0",)).start()
        img = g.grab()
        self.assertIsNotNone(img)
        self.assertEqual(g.last_seq, 1)
        self.assertIsNone(g.grab())  # 沒有新影格 → 逾時
        self.assertIn("逾時", g.last_error)
        self.assertTrue(g.info()["streaming"])
        g.close()
        self.assertTrue(_wait(lambda: not session.by_id["cam0"].streaming))

    def test_offline_and_config_errors(self):
        g = CaptureGrabber({"client": "ghost", "channel": "cam0"})
        self.assertIsNone(g.grab())
        self.assertIn("ghost", g.last_error)
        self.assertFalse(g.info()["connected"])
        with self.assertRaises(ValidationError):
            CaptureGrabber({"client": "", "channel": ""})
        with self.assertRaises(ValidationError) as cm:
            sources.try_grab("capture", {"client": "ghost", "channel": "cam0"})
        self.assertEqual(cm.exception.code, "no_frame")
        self.connect(name="live")
        self.assertEqual(sources.try_grab("capture", {"client": "live", "channel": "cam0"}).shape, (48, 64))
        kinds = {k["kind"]: k for k in sources.kinds()}
        self.assertEqual(kinds["capture"]["label"], "擷取端相機")
        self.assertIn("client", kinds["capture"]["fields"])
        # 未開啟的來源也要能回連線狀態（清單／側欄顯示離線、fps、最近影格）
        from apps.vision.capture.grabber import channel_status
        from apps.vision.models import ImageSource

        ghost = ImageSource(id=9901, name="ghost", kind="capture", config={"client": "ghost", "channel": "cam0"})
        self.assertEqual((sources.source_info(ghost)["open"], sources.source_info(ghost)["connected"]), (False, False))
        live = ImageSource(id=9902, name="live", kind="capture", config={"client": "live", "channel": "cam0"})
        info = sources.source_info(live)
        self.assertTrue(info["connected"])
        self.assertEqual((info["open"], info["width"], info["height"]), (False, 64, 48))
        self.assertTrue(channel_status("live", "nope")["last_error"].startswith("擷取端"))


# ---------------------------------------------------------------------------
class CaptureApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.port = free_port()
        hub.start("127.0.0.1", cls.port)

    @classmethod
    def tearDownClass(cls):
        hub.stop()
        super().tearDownClass()

    def setUp(self):
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        sources.close_all()
        _wait(lambda: not hub.clients(), 2.0)

    def connect(self, **kw):
        c = FakeCaptureClient(self.port, **kw)
        self.clients.append(c)
        c.start()
        c.wait_ready()
        return c

    def test_clients_preview_and_stream(self):
        r = self.client.get("/api/vision/capture/clients")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["items"], [])
        self.assertTrue(r.json()["listening"])
        self.connect(name="api1")
        _wait(lambda: hub.get("api1") is not None)
        r = self.client.get("/api/vision/capture/clients")
        self.assertEqual(r.json()["items"][0]["name"], "api1")
        r = self.client.get("/api/vision/capture/clients/api1/channels/cam0/preview?max=32")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertEqual(self.client.get("/api/vision/capture/clients/api1/channels/nope/preview").status_code, 404)
        self.assertEqual(self.client.get("/api/vision/capture/clients/nobody/channels/cam0/preview").status_code, 404)
        r = self.client.post("/api/vision/capture/clients/api1/channels/cam0/stream", data=json.dumps({"enabled": True}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(_wait(lambda: hub.get("api1").by_id["cam0"].streaming))
        self.assertEqual(self.client.post("/api/vision/capture/clients/nobody/channels/cam0/stream", data=json.dumps({"enabled": True}), content_type="application/json").status_code, 404)
        self.connect(name="slow", answer_grabs=False)
        _wait(lambda: hub.get("slow") is not None)
        self.assertEqual(self.client.get("/api/vision/capture/clients/slow/channels/cam0/preview").status_code, 503)

    def test_download_info_and_file(self):
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="vs-dl-"))
        with override_settings(DATA_DIR=tmp):
            r = self.client.get("/api/vision/capture/download/info")
            self.assertEqual(r.status_code, 200)
            self.assertFalse(r.json()["available"])
            self.assertEqual(self.client.get("/api/vision/capture/download").status_code, 404)
            (tmp / "downloads").mkdir()
            (tmp / "downloads" / "VisionSequenceCapture-0.1.0-win64.zip").write_bytes(b"PK\x05\x06" + b"\0" * 18)
            (tmp / "downloads" / "manifest.json").write_text(json.dumps({"version": "0.1.0", "filename": "VisionSequenceCapture-0.1.0-win64.zip", "sha256": "ab", "built_at": "2026-09-04T00:00:00Z"}), encoding="utf-8")
            info = self.client.get("/api/vision/capture/download/info").json()
            self.assertTrue(info["available"])
            self.assertEqual((info["version"], info["size"]), ("0.1.0", 22))
            r = self.client.get("/api/vision/capture/download")
            self.assertEqual(r.status_code, 200)
            self.assertIn("VisionSequenceCapture-0.1.0-win64.zip", r["Content-Disposition"])
            self.assertEqual(b"".join(r.streaming_content)[:2], b"PK")

    def test_source_test_and_crud(self):
        self.connect(name="src1")
        _wait(lambda: hub.get("src1") is not None)
        body = {"kind": "capture", "config": {"client": "src1", "channel": "cam0", "mode": "on_demand", "timeout_ms": 1000, "fresh": True}}
        r = self.client.post("/api/vision/sources/test", data=json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["width"], r.json()["height"]), (64, 48))
        r = self.client.post("/api/vision/sources/test", data=json.dumps({"kind": "capture", "config": {"client": "ghost", "channel": "cam0"}}), content_type="application/json")
        self.assertEqual(r.status_code, 422)
        self.assertIn("ghost", r.json()["error"]["message"])
        r = self.client.post("/api/vision/sources", data=json.dumps({"name": "擷取端來源", "kind": "capture", "config": body["config"]}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        sid = r.json()["id"]
        r = self.client.get(f"/api/vision/sources/{sid}/preview?max=32")
        self.assertEqual(r.status_code, 200)
        r = self.client.get(f"/api/vision/sources/{sid}")
        self.assertTrue(r.json()["status"]["connected"])
        self.assertEqual(r.json()["status"]["client"], "src1")
        item = next(x for x in hub.clients() if x["name"] == "src1")["channels"][0]
        self.assertIn("擷取端來源", item["in_use_by"])
        info = self.client.get("/api/vision/integration/info").json()
        self.assertEqual(info["capture_port"], settings.VISION["CAPTURE_PORT"])
        self.assertIn("capture_listening", info)


# ---------------------------------------------------------------------------
@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class CaptureRunTests(TransactionTestCase):
    """整條 run：image_source(capture) → 引擎；擷取端斷線時 run 失敗。"""

    def setUp(self):
        self.port = free_port()
        hub.start("127.0.0.1", self.port)
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        sources.close_all()
        hub.stop()

    def connect(self, **kw):
        c = FakeCaptureClient(self.port, **kw)
        self.clients.append(c)
        c.start()
        c.wait_ready()
        return c

    def test_run_with_capture_source(self):
        from apps.vision.runner import runner

        c = self.connect(name="run1", channels=[{"id": "cam0", "width": 96, "height": 64, "channels": 3, "dtype": "u8"}])
        _wait(lambda: hub.get("run1") is not None)
        src = ImageSource.objects.create(name="run-cap", kind="capture", config={"client": "run1", "channel": "cam0", "timeout_ms": 1000})
        flow = Flow.objects.create(name="capture-flow", graph={
            "nodes": [{"id": "src", "type": "image_source", "params": {"source_id": src.id}}, {"id": "gray", "type": "grayscale", "params": {}}],
            "edges": [{"id": "e1", "source": "src", "target": "gray", "source_handle": "image", "target_handle": "image"}],
        })
        runner.forget(flow.id)
        report = runner.run_sync(flow, trigger="test")
        self.assertEqual(report.status, "ok", report.error)
        self.assertIn("96×64", report.nodes["src"].message)
        c.close()
        self.assertTrue(_wait(lambda: hub.get("run1") is None))
        report = runner.run_sync(flow, trigger="test")
        self.assertEqual(report.status, "failed")
        self.assertIn("run1", report.nodes["src"].message or report.error or "")
