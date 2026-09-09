"""擷取端程式（vscapture）：設定、影格槽、模擬相機、通道執行緒、共享記憶體環、對真 hub 的 loopback 傳輸、headless CLI。

不需要相機也不需要 Qt；`vscapture` 的核心模組不在模組層 import PySide6 或相機 SDK。
"""

from __future__ import annotations

import json
import os
import sys
import hashlib
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
from django.test import SimpleTestCase

from apps.vision.capture.hub import CaptureError, hub
from tests.test_comm import free_port
from vscapture import app as appmod
from vscapture import config as configmod
from vscapture import protocol as P
from vscapture.cameras.base import CameraError, CameraParamError, ParamSpec
from vscapture.cameras.fake import FAKE_MODELS, FakeCamera
from vscapture.channel import Channel, ChannelState
from vscapture.engine import CaptureEngine
from vscapture.config import AppConfig, ChannelConfig, ConfigError, ConnectionConfig, DeliveryConfig, Roi
from vscapture.frames import BufferPool, Frame, FrameSlot, crop_roi, encode, frame_item, prepare
from vscapture.protocol import Encoding
from vscapture.transport.sender import item_bytes
from vscapture import i18n, params, update
from vscapture.shm import ShmRing, plan_slots
from vscapture.transport.client import ConnState


def _wait(pred, timeout=3.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def _wait_true(fn, timeout=3.0):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if fn():
            return True
        time.sleep(0.02)
    return False


class ConfigTests(SimpleTestCase):
    def test_roundtrip_defaults_and_unknown_keys(self):
        tmp = Path(tempfile.mkdtemp(prefix="vsc-cfg-")) / "config.json"
        cfg = AppConfig(connection=ConnectionConfig(host="10.0.0.5", port=9101, client_name="LINE1"), channels=[
            ChannelConfig(id="cam1", name="上相機", backend="fake", device_id="fake:0", roi=Roi(10, 20, 100, 80), delivery=DeliveryConfig(encoding="jpeg", mode="stream")),
        ])
        configmod.save(cfg, tmp)
        self.assertFalse(tmp.with_suffix(".json.tmp").exists())
        loaded = configmod.load(tmp)
        self.assertEqual(loaded, cfg)
        raw = tmp.read_text(encoding="utf-8").replace('"version": 1', '"version": 1, "unknown": {"x": 1}')
        tmp.write_text(raw, encoding="utf-8")
        self.assertEqual(configmod.load(tmp).channels[0].roi, Roi(10, 20, 100, 80))
        self.assertEqual(configmod.load(tmp / "missing.json"), AppConfig())

    def test_ui_and_update_fields(self):
        cfg = configmod.AppConfig.from_dict({"connection": {"auto_update": "auto", "shm_max_mb": 256, "idle_stop_s": 30}, "ui": {"language": "en", "theme": "light"}})
        self.assertEqual((cfg.connection.auto_update, cfg.connection.shm_max_mb, cfg.connection.idle_stop_s), ("auto", 256, 30.0))
        self.assertEqual(configmod.AppConfig().connection.idle_stop_s, 60.0)
        self.assertEqual((cfg.ui.language, cfg.ui.theme), ("en", "light"))
        blank = configmod.AppConfig()
        self.assertEqual((blank.connection.auto_update, blank.ui.language, blank.ui.theme), ("notify", "zh-Hant", "dark"))
        for bad in ({"connection": {"auto_update": "always"}}, {"ui": {"language": "fr"}}, {"ui": {"theme": "neon"}}):
            with self.assertRaises(ConfigError):
                configmod.AppConfig.from_dict(bad)

    def test_invalid_values(self):
        with self.assertRaises(ConfigError) as cm:
            AppConfig.from_dict({"channels": [{"id": "a", "backend": "nope"}]})
        self.assertIn("channels[0].backend", str(cm.exception))
        with self.assertRaises(ConfigError):
            AppConfig.from_dict({"channels": [{"id": "a"}, {"id": "a"}]})
        with self.assertRaises(ConfigError):
            AppConfig.from_dict({"connection": {"local_mode": "maybe"}})
        with self.assertRaises(ConfigError):
            AppConfig.from_dict({"channels": [{"id": "a", "delivery": {"encoding": "png"}}]})
        self.assertEqual(Roi(-5, 10, 5000, 10).clamp(640, 480), Roi(0, 10, 640, 10))
        self.assertTrue(Roi(0, 0, 640, 480).clamp(640, 480).is_full())
        self.assertEqual(configmod.new_channel_id(["cam1", "cam2"]), "cam3")


class FramesTests(SimpleTestCase):
    def test_slot_wait_and_crop(self):
        slot = FrameSlot()
        self.assertIsNone(slot.wait_for(1, 0.05))
        threading.Timer(0.05, slot.publish, args=(np.zeros((8, 8), np.uint8),)).start()
        frame = slot.wait_for(1, 1.0)
        self.assertEqual(frame.seq, 1)
        self.assertIs(slot.latest(), frame)
        img = np.arange(64 * 48, dtype=np.uint8).reshape(48, 64)
        view, rx, ry = crop_roi(img, Roi(10, 5, 20, 10))
        self.assertEqual((view.shape, rx, ry), ((10, 20), 10, 5))
        self.assertEqual(int(view[0, 0]), int(img[5, 10]))
        view, rx, ry = crop_roi(img, Roi(60, 40, 100, 100))
        self.assertEqual((view.shape, rx, ry), ((8, 4), 60, 40))
        view, rx, ry = crop_roi(img, Roi(30, 20, 10, 10), origin=(20, 10))  # 硬體 ROI 位移
        self.assertEqual((view.shape, rx, ry), ((10, 10), 30, 20))

    def test_prepare_and_encode(self):
        img = np.random.default_rng(0).integers(0, 255, (48, 64, 3), dtype=np.uint8)
        frame = Frame(3, 123, img)
        fields, arr = prepare(frame, Roi(8, 8, 32, 16), DeliveryConfig(encoding="raw", mono=True, downscale=2))
        self.assertEqual((fields["width"], fields["height"], fields["channels"], fields["roi_x"], fields["roi_y"], fields["full_w"], fields["full_h"]), (16, 8, 1, 8, 8, 64, 48))
        self.assertTrue(arr.flags["C_CONTIGUOUS"])
        self.assertTrue(fields["flags"] & P.FrameFlags.CROPPED)
        fields, arr = prepare(frame, Roi(), DeliveryConfig(encoding="jpeg"))
        self.assertEqual(fields["encoding"], Encoding.JPEG)
        import cv2

        decoded = cv2.imdecode(np.frombuffer(encode(arr, Encoding.JPEG, 95), np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, (48, 64, 3))
        raw = encode(arr, Encoding.RAW)
        np.testing.assert_array_equal(np.frombuffer(raw, np.uint8).reshape(48, 64, 3), arr)
        if P.lz4_available():
            np.testing.assert_array_equal(np.frombuffer(P.decompress_lz4(encode(arr, Encoding.LZ4), arr.nbytes), np.uint8).reshape(arr.shape), arr)


class BufferPoolTests(SimpleTestCase):
    """大影格重用緩衝是 60 fps 的關鍵（20MP 一張 60 MB，重新配置要 17 ms、重用 2.4 ms）。"""

    def test_reuses_only_when_nobody_holds_it(self):
        pool = BufferPool(max_buffers=3)
        a = pool.take((4, 4), np.uint8)
        b = pool.take((4, 4), np.uint8)  # a 仍被本地變數持有 → 不會拿到同一張
        self.assertIsNot(a, b)
        del a
        c = pool.take((4, 4), np.uint8)  # a 已釋放 → 重用
        self.assertIsNot(c, b)
        self.assertEqual(pool.stats()["buffers"], 2)
        self.assertEqual((pool.hits, pool.misses), (1, 2))
        del b, c
        for _ in range(20):  # 沒人持有 → 之後全部命中，不再配置
            pool.take((4, 4), np.uint8)
        self.assertEqual(pool.misses, 2)
        # 尺寸／型別不同要換新的，舊的不留
        big = pool.take((8, 8), np.uint16)
        self.assertEqual((big.shape, big.dtype), ((8, 8), np.dtype(np.uint16)))
        self.assertEqual(pool.stats()["buffers"], 1)
        pool.clear()
        self.assertEqual(pool.stats()["buffers"], 0)

    def test_bytes_cap_and_shm_slot_plan(self):
        pool = BufferPool(max_buffers=4, max_bytes=100)
        held = [pool.take((60,), np.uint8) for _ in range(3)]
        self.assertEqual(len(held), 3)
        self.assertLessEqual(pool.stats()["bytes"], 100)
        # 一條連線的共享記憶體總量有上限：20MP 彩色一槽 60 MB
        self.assertEqual(plan_slots(6, 1 << 20), 6)
        self.assertEqual(plan_slots(6, 60 << 20, max_bytes=512 << 20), 6)
        self.assertEqual(plan_slots(16, 60 << 20, max_bytes=512 << 20), 8)
        self.assertEqual(plan_slots(16, 300 << 20, max_bytes=512 << 20), 2)  # 至少 2 槽


class FrameItemTests(SimpleTestCase):
    def test_raw_is_zero_copy_and_encoded_is_packed(self):
        arr = np.arange(24, dtype=np.uint8).reshape(2, 4, 3)
        hdr = P.FrameHeader.for_image(0, 7, 1, 4, 2, 3, 0)
        item, n = frame_item(P.MsgType.FRAME, 5, hdr, arr, P.Encoding.RAW)
        self.assertIsInstance(item, tuple)
        head, payload = item
        self.assertEqual(n, arr.nbytes)
        self.assertEqual(payload.nbytes, arr.nbytes)
        self.assertEqual(bytes(payload), arr.tobytes())
        mtype, req_id, hlen, plen = P.unpack_envelope(head)
        self.assertEqual((mtype, req_id, hlen, plen), (P.MsgType.FRAME, 5, P.FRAME_HDR.size, arr.nbytes))
        self.assertEqual(len(head), P.ENVELOPE.size + P.FRAME_HDR.size)
        self.assertEqual(item_bytes(item), len(head) + arr.nbytes)
        item2, n2 = frame_item(P.MsgType.FRAME, 0, hdr, arr, P.Encoding.JPEG, 80)
        self.assertIsInstance(item2, bytes)
        self.assertEqual(item_bytes(item2), len(item2))
        self.assertGreater(n2, 0)


class FakeCameraTests(SimpleTestCase):
    def test_models_cover_large_sensors(self):
        devices = FakeCamera.enumerate()
        self.assertEqual([d.device_id for d in devices], [f"fake:{i}" for i in range(len(FAKE_MODELS))])
        self.assertIn("2000 萬畫素", devices[3].label)
        cam = FakeCamera()
        desc = cam.open("fake:3")
        self.assertEqual((desc.sensor_w, desc.sensor_h), (5472, 3648))
        cam.start()
        img, _ = cam.grab_one(1.0)
        self.assertEqual((img.shape, img.dtype), ((3648, 5472, 3), np.dtype(np.uint8)))
        second, _ = cam.grab_one(1.0)
        self.assertFalse(np.array_equal(img, second))  # 每張的方塊位置不同
        cam.close()
        for bad in ("fake:9", "fake:x", "usb:0"):
            with self.assertRaises(CameraError):
                FakeCamera().open(bad)

    def test_lifecycle_params_and_roi(self):
        self.assertTrue(FakeCamera.available()[0])
        devices = FakeCamera.enumerate()
        self.assertEqual(devices[0].device_id, "fake:0")
        cam = FakeCamera()
        desc = cam.open("fake:1")
        self.assertEqual((desc.sensor_w, desc.sensor_h, desc.supports_hw_roi), (640, 480, True))
        cam.start()
        img, origin = cam.grab_one(1.0)
        self.assertEqual((img.shape, origin), ((480, 640, 3), (0, 0)))
        applied = cam.set_params({"pixel_format": "Mono8", "exposure_us": 20000, "fps": 60})
        self.assertEqual(applied["pixel_format"], "Mono8")
        img2, _ = cam.grab_one(1.0)
        self.assertEqual(img2.ndim, 2)
        with self.assertRaises(CameraParamError) as cm:
            cam.set_params({"bogus": 1, "pixel_format": "RGB16"})
        self.assertEqual(set(cm.exception.errors), {"bogus", "pixel_format"})
        is_hw, roi = cam.apply_roi(Roi(13, 21, 100, 50), True)
        self.assertTrue(is_hw)
        self.assertEqual(roi, Roi(8, 16, 96, 48))  # 對齊到 8 的倍數（向下）
        img3, origin = cam.grab_one(1.0)
        self.assertEqual((img3.shape, origin), ((48, 96), (8, 16)))
        cam.set_params({"trigger_mode": "software"})
        self.assertIsNone(cam.grab_one(0.05))
        img4, _ = cam.snap(1.0)
        self.assertEqual(img4.shape, (48, 96))
        self.assertIn("exposure_us", cam.get_params())
        cam.close()
        self.assertFalse(cam.is_open)


class ChannelTests(SimpleTestCase):
    def test_commands_run_on_owner_thread_and_acquire(self):
        events = []
        ch = Channel(ChannelConfig(id="c1", backend="fake", device_id="fake:0", delivery=DeliveryConfig(encoding="raw")), on_event=lambda k, d: events.append((k, d)))
        ch.start_thread()
        try:
            ch.open()
            self.assertEqual(ch.state, ChannelState.OPEN)
            self.assertEqual(ch.call(lambda: threading.current_thread().name), "vsc-cam-c1")
            ch.start()
            self.assertTrue(_wait(lambda: ch.slot.seq >= 3, 3.0))
            frame = ch.acquire(ch.slot.seq, 1.0)
            self.assertIsNotNone(frame)
            self.assertGreater(frame.seq, 0)
            latest = ch.acquire(0, 0.5, after_request=False)
            self.assertIsNotNone(latest)
            hello = ch.hello_dict()
            self.assertEqual((hello["width"], hello["height"], hello["channels"], hello["driver"]), (640, 480, 3, "fake"))
            ch.set_params({"pixel_format": "Mono8"})
            self.assertEqual(ch.cfg.params.pixel_format, "Mono8")
            self.assertEqual(ch.hello_dict()["channels"], 1)
            ch.apply_roi(Roi(0, 0, 320, 240), False)
            self.assertEqual(ch.hello_dict()["max_bytes"], 320 * 240)
            self.assertGreater(ch.stats()["seq"], 0)
            ch.stop()
            self.assertEqual(ch.state, ChannelState.OPEN)
            ch.close()
            self.assertEqual(ch.state, ChannelState.CLOSED)
            self.assertTrue(any(k == "channel" and d["state"] == "running" for k, d in events))
        finally:
            ch.stop_thread()


class ShmRingTests(SimpleTestCase):
    def test_slot_rules_and_attach(self):
        from multiprocessing import shared_memory

        img = np.full((4, 8), 7, np.uint8)
        ring = ShmRing.create("t", "c", 2, img.nbytes)
        try:
            self.assertEqual(ring.try_write(1, img), 0)
            self.assertEqual(ring.try_write(2, img), 1)
            self.assertIsNone(ring.try_write(3, img))  # 兩槽都被伺服端持有
            self.assertFalse(ring.release(0, 99))  # seq 不符忽略
            self.assertTrue(ring.release(0, 1))
            self.assertEqual(ring.try_write(3, np.full((4, 8), 9, np.uint8)), 0)
            other = shared_memory.SharedMemory(name=ring.name)
            try:
                self.assertEqual(P.unpack_seg_header(other.buf[: P.SEG_HDR.size]), (ring.canary, 2, ring.slot_bytes))
                off = P.slot_offset(0, ring.slot_bytes)
                self.assertEqual(bytes(other.buf[off : off + img.nbytes]), b"\x09" * 32)
            finally:
                other.close()
            self.assertEqual(ring.stats()["in_use"], 2)
            threading.Timer(0.05, ring.release, args=(1, 2)).start()
            self.assertEqual(ring.wait_write(4, img, 1.0), 1)
        finally:
            ring.close()
            ring.close()
        big = ShmRing.create("t", "d", 3, img.nbytes)
        try:
            big.try_write(1, img)
            big.try_write(2, img)
            big.try_write(3, img)
            self.assertIsNone(big.try_write(4, img))
            self.assertIsNone(big.try_write(9, img))  # seq 夠遠但持有不到 1 秒：不覆寫
            big._owner_time = {k: 0.0 for k in big._owner_time}  # noqa: SLF001 — 模擬持有超過 1 秒
            self.assertEqual(big.try_write(9, img), 0)  # 最舊的槽視為孤兒
            self.assertEqual(big.stats()["overwritten"], 1)
        finally:
            big.close()


class TransportLoopbackTests(SimpleTestCase):
    """擷取端引擎（兩個模擬通道）連到真的 hub：同機 → 共享記憶體、GRAB／串流／TEST／重連。"""

    def setUp(self):
        self.port = free_port()
        hub.start("127.0.0.1", self.port)
        os.environ["VSCAPTURE_CONFIG"] = str(Path(tempfile.mkdtemp(prefix="vsc-live-")) / "config.json")
        cfg = AppConfig(connection=ConnectionConfig(host="127.0.0.1", port=self.port, client_name="loop-pc", auto_connect=False, heartbeat_s=1.0, reconnect_max_s=2.0), channels=[
            ChannelConfig(id="a", name="A", backend="fake", device_id="fake:0", delivery=DeliveryConfig(encoding="raw")),
            ChannelConfig(id="b", name="B", backend="fake", device_id="fake:1", roi=Roi(16, 8, 64, 32), delivery=DeliveryConfig(encoding="jpeg", mono=True)),
        ])
        self.engine = CaptureEngine(cfg)
        self.engine.start(connect=False)

    def tearDown(self):
        self.engine.stop()
        hub.stop()
        os.environ.pop("VSCAPTURE_CONFIG", None)
        _wait(lambda: not hub.clients(), 2.0)

    def test_grab_stream_test_and_reconnect(self):
        self.engine.connect()
        self.assertTrue(_wait(lambda: self.engine.transport.state == ConnState.CONNECTED, 5.0), self.engine.transport.state_detail)
        self.assertTrue(_wait(lambda: hub.get("loop-pc") is not None))
        self.assertTrue(self.engine.transport.local_mode)
        self.assertTrue(_wait(lambda: "a" in self.engine.transport.rings and "b" in self.engine.transport.rings, 3.0))
        f = hub.request_frame("loop-pc", "a", timeout=2.0)
        self.assertEqual(f.image.shape, (480, 640, 3))
        self.assertTrue(f.meta.shm)
        f2 = hub.request_frame("loop-pc", "a", timeout=2.0, min_seq=f.meta.seq)
        self.assertGreater(f2.meta.seq, f.meta.seq)
        self.assertTrue(f2.meta.fresh)
        fb = hub.request_frame("loop-pc", "b", timeout=2.0)
        self.assertEqual(fb.image.shape, (32, 64))  # ROI＋單色
        self.assertEqual((fb.meta.roi_x, fb.meta.roi_y, fb.meta.full_w, fb.meta.full_h), (16, 8, 640, 480))
        fj = hub.request_frame("loop-pc", "b", timeout=2.0, encoding=Encoding.JPEG)
        self.assertTrue(fj.meta.shm)  # 本機模式：共享記憶體優先於編碼
        # 串流
        hub.set_stream("loop-pc", "a", True, max_fps=20)
        session = hub.get("loop-pc")
        self.assertTrue(_wait(lambda: session.by_id["a"].streaming, 2.0))
        first = hub.latest("loop-pc", "a")
        self.assertTrue(_wait(lambda: (hub.latest("loop-pc", "a") or first) is not None and hub.latest("loop-pc", "a").meta.seq > (first.meta.seq if first else 0) + 3, 3.0))
        hub.set_stream("loop-pc", "a", False)
        self.assertTrue(_wait(lambda: not session.by_id["a"].streaming, 2.0))
        # TEST 往返
        result = self.engine.transport.test_send("a").result(timeout=5.0)
        self.assertGreater(result["rtt_ms"], 0)
        self.assertEqual(result["bytes"], 640 * 480 * 3)
        # 伺服端重啟 → 自動重連（同一個埠）
        hub.stop()
        self.assertTrue(_wait(lambda: self.engine.transport.state in (ConnState.RECONNECTING, ConnState.CONNECTING), 5.0))
        hub.start("127.0.0.1", self.port)
        self.assertTrue(_wait(lambda: self.engine.transport.state == ConnState.CONNECTED and hub.get("loop-pc") is not None, 10.0))
        self.assertIsNotNone(hub.request_frame("loop-pc", "a", timeout=2.0).image)
        self.engine.disconnect()
        self.assertTrue(_wait(lambda: hub.get("loop-pc") is None, 3.0))
        self.assertEqual(self.engine.transport.state, ConnState.DISCONNECTED)

    def test_remote_mode_uses_tcp_payload(self):
        self.engine.cfg.connection.local_mode = "off"
        self.engine.connect()
        self.assertTrue(_wait(lambda: self.engine.transport.state == ConnState.CONNECTED, 5.0))
        _wait(lambda: hub.get("loop-pc") is not None)
        f = hub.request_frame("loop-pc", "a", timeout=2.0)
        self.assertFalse(f.meta.shm)
        self.assertEqual(f.meta.encoding, "raw")
        fj = hub.request_frame("loop-pc", "b", timeout=2.0)
        self.assertEqual(fj.meta.encoding, "jpeg")
        self.assertEqual(fj.image.shape, (32, 64))
        with self.assertRaises(CaptureError) as cm:
            hub.request_frame("loop-pc", "nope", timeout=0.5)
        self.assertEqual(cm.exception.code, "no_channel")

    def test_channel_set_params_outputs_and_user_sets(self):
        self.engine.connect()
        self.assertTrue(_wait(lambda: self.engine.transport.state == ConnState.CONNECTED, 5.0))
        session = hub.get("loop-pc")
        self.assertIsNotNone(session)
        self.assertTrue(session.features.get("channel_set"))
        channel_info = session.channel("a").to_dict()
        self.assertIn("Line1", channel_info["outputs"])
        self.assertIn("exposure_us", {p["name"] for p in channel_info["params"]})

        result = hub.set_channel_params("loop-pc", "a", {"exposure_us": 12345, "gain_db": 6.5, "trigger_source": "Line1", "trigger_delay_us": 20}, timeout=2.0)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["applied"]["exposure_us"], 12345)
        self.assertEqual(result["applied"]["gain_db"], 6.5)
        self.assertEqual(result["applied"]["trigger_source"], "Line1")
        self.assertEqual(result["applied"]["trigger_delay_us"], 20)

        result = hub.channel_command("loop-pc", "a", "save_user_set", {"name": "job1"}, timeout=2.0)
        self.assertTrue(result["ok"], result)
        self.assertTrue(hub.set_channel_params("loop-pc", "a", {"exposure_us": 22222}, timeout=2.0)["ok"])
        result = hub.channel_command("loop-pc", "a", "load_user_set", {"name": "job1"}, timeout=2.0)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["applied"]["exposure_us"], 12345)

        result = hub.channel_command("loop-pc", "a", "line_out", {"line": "Line1", "level": True, "pulse_ms": 50}, timeout=2.0)
        self.assertTrue(result["ok"], result)
        channel = self.engine.channels["a"]
        self.assertTrue(channel.call(lambda: channel.camera.output_levels["Line1"]))
        self.assertTrue(_wait(lambda: channel.call(lambda: channel.camera.output_levels["Line1"]) is False, 1.0))


class HeadlessCliTests(SimpleTestCase):
    def test_parse_and_build(self):
        args = appmod.parse_args(["--headless", "--server", "10.0.0.9:9100", "--name", "PC-9", "--fake", "2", "--config", str(Path(tempfile.mkdtemp()) / "c.json")])
        cfg, path, error = appmod.build_config(args)
        self.assertEqual((cfg.connection.host, cfg.connection.port, cfg.connection.client_name, error), ("10.0.0.9", 9100, "PC-9", ""))
        self.assertEqual([c.backend for c in cfg.channels], ["fake", "fake"])
        engine = appmod.build_engine(args)
        self.assertEqual(len(engine.cfg.channels), 2)
        self.assertNotIn("PySide6", sys.modules)
        bad = Path(tempfile.mkdtemp()) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        _, _, error = appmod.build_config(appmod.parse_args(["--config", str(bad)]))
        self.assertIn("設定檔", error)

    def test_list_cameras_mentions_fake(self):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            appmod.list_cameras()
        out = buf.getvalue()
        self.assertIn("模擬相機", out)
        self.assertNotIn("OpenCV", out)


class ParamTreeTests(SimpleTestCase):
    """相機參數的樹狀分組與搜尋（介面用的純邏輯，不需要 Qt）。"""

    def test_group_path_sort_and_search(self):
        exposure = ParamSpec("exposure_us", "float", 5000.0, standard=True, label="曝光時間")
        pattern = ParamSpec("Pattern", "enum", "a", label="Pattern")
        delay = ParamSpec("TriggerDelay", "float", 0.0, group="Acquisition/Trigger", label="Trigger Delay")
        deep = ParamSpec("X", "int", 0, group=" Root / Sub / Leaf ")
        self.assertEqual(params.group_path(exposure), ("基本",))  # 標準參數沒給 group → 基本
        self.assertEqual(params.group_path(pattern), ("進階",))
        self.assertEqual(params.group_path(delay), ("Acquisition", "Trigger"))  # 以「/」分層
        self.assertEqual(params.group_path(deep), ("Root", "Sub", "Leaf"))
        self.assertEqual([s.name for s in sorted([pattern, delay, exposure], key=params.sort_key)], ["exposure_us", "TriggerDelay", "Pattern"])
        self.assertEqual(params.param_label(exposure), "曝光時間")  # 標準參數走 i18n
        self.assertEqual(params.param_label(delay), "Trigger Delay")  # 廠牌參數保持 SDK 名稱
        self.assertTrue(params.matches(delay, "trig") and params.matches(delay, "TRIGGER"))
        self.assertTrue(params.matches(exposure, "曝光") and params.matches(exposure, "exposure"))
        self.assertFalse(params.matches(pattern, "trig"))
        self.assertTrue(params.matches(pattern, "  "))  # 空搜尋＝全部顯示
        self.assertIn("pixel_format", params.NEEDS_STOP)
        try:
            i18n.set_language("en")
            self.assertEqual(params.group_path(exposure), ("Basic",))
            self.assertEqual(params.param_label(exposure), "Exposure")
        finally:
            i18n.set_language("zh-Hant")


class IdleStopTests(SimpleTestCase):
    """省電：沒人要影像就停止取像，下次要影像自動恢復。"""

    def _engine(self, **conn):
        cfg = configmod.AppConfig(connection=configmod.ConnectionConfig(auto_connect=False, **conn))
        cfg.channels.append(configmod.ChannelConfig(id="cam1", name="t", backend="fake", device_id="fake:0", preview=False))
        engine = CaptureEngine(cfg)
        self.addCleanup(engine.stop)
        engine.start(connect=False)
        return engine, engine.channels["cam1"]

    def test_pause_after_idle_and_resume_on_request(self):
        _engine, ch = self._engine(idle_stop_s=0.5)
        self.assertTrue(_wait_true(lambda: ch.state.value == "running"))
        # 旗標先立起來、相機才停下來，兩個都要等到
        self.assertTrue(_wait_true(lambda: ch.idle_paused and ch.state.value == "open", 4.0), "閒置後應該暫停取像")
        self.assertTrue(ch.idle_paused)  # 相機仍開著，只是不取像
        self.assertIsNotNone(ch.camera)
        frame = ch.acquire(0, 2.0)  # 伺服端要影像 → 自動恢復
        self.assertIsNotNone(frame)
        self.assertFalse(ch.idle_paused)
        self.assertEqual(ch.state.value, "running")
        st = ch.stats()
        self.assertEqual(st["idle_paused"], False)
        self.assertLess(st["idle_s"], 1.0)

    def test_preview_and_ui_visibility(self):
        engine, ch = self._engine(idle_stop_s=0.5)
        ch.cfg.preview = True  # 介面在看預覽 → 不停
        self.assertTrue(_wait_true(lambda: ch.state.value == "running"))
        time.sleep(1.2)
        self.assertFalse(ch.idle_paused)
        engine.set_ui_visible(False)  # 縮到系統匣 → 沒人看預覽了
        self.assertTrue(_wait_true(lambda: ch.idle_paused, 4.0))
        engine.set_ui_visible(True)  # 回到前景 → 預覽要有畫面
        self.assertTrue(_wait_true(lambda: not ch.idle_paused and ch.state.value == "running", 4.0))

    def test_disabled_by_zero_and_manual_stop(self):
        _engine, ch = self._engine(idle_stop_s=0)  # 0＝一直取像
        self.assertTrue(_wait_true(lambda: ch.state.value == "running"))
        time.sleep(1.5)
        self.assertFalse(ch.idle_paused)
        ch.stop()  # 使用者自己按停止：不是省電暫停，也不該被自動恢復
        self.assertFalse(ch.idle_paused)
        self.assertIsNone(ch.acquire(0, 0.3))
        self.assertEqual(ch.state.value, "open")

    def test_streaming_channel_is_never_paused(self):
        engine, ch = self._engine(idle_stop_s=0.5)
        self.assertTrue(_wait_true(lambda: ch.state.value == "running"))
        engine.transport.is_streaming = lambda cid: True  # 伺服端開了串流
        time.sleep(1.5)
        self.assertFalse(ch.idle_paused, "串流中不能暫停")


class I18nTests(SimpleTestCase):
    """介面文案：三語系 key 與占位符要對齊，且遵守網頁同一套用詞規範。"""

    def test_all_languages_and_placeholders_align(self):
        import re

        self.assertEqual(i18n.LANGUAGE_CODES, ("zh-Hant", "zh-Hans", "en"))  # 與網頁相同的三種語言
        missing = [(key, code) for key, entry in i18n.TEXTS.items() for code in i18n.LANGUAGE_CODES if code not in entry]
        self.assertEqual(missing, [])
        bad = []
        for key, entry in i18n.TEXTS.items():
            base = set(re.findall(r"\{(\w+)\}", entry["zh-Hant"]))
            for code in i18n.LANGUAGE_CODES:
                if set(re.findall(r"\{(\w+)\}", entry[code])) != base:
                    bad.append(f"{key}/{code}")
        self.assertEqual(bad, [], f"占位符不一致：{bad}")

    def test_banned_words_and_lookup(self):
        banned = ["點一下", "試跑", "還沒有", "這個", "看看", "試試", "太敏感", "漏抓", "幫我", "搞", "丟掉", "一堆"]
        hits = [f"{k} ⟶ {w}" for k, entry in i18n.TEXTS.items() for w in banned if w in entry["zh-Hant"]]
        self.assertEqual(hits, [], f"用詞不符規範：{hits}")
        try:
            self.assertEqual(i18n.set_language("en"), "en")
            self.assertEqual(i18n.tr("connection.title"), "Connection")
            self.assertIn("0.2.0", i18n.tr("update.found", version="0.2.0", size="97 MB"))
            self.assertEqual(i18n.set_language("fr"), "zh-Hant")  # 不認得的語言退回繁中
            self.assertEqual(i18n.tr("connection.title"), "連線")
            self.assertEqual(i18n.tr("no.such.key"), "no.such.key")
            self.assertEqual(i18n.tr("connection.title", bogus=1), "連線")  # 多餘的參數不會炸
        finally:
            i18n.set_language("zh-Hant")

    def test_ui_strings_come_from_the_table(self):
        """介面模組不應該再有寫死的中文（改語言時會漏掉）。"""
        import re
        from pathlib import Path

        allow = {"live_view.py"}  # 畫布上的 HUD 只有數字與符號
        offenders = []
        for path in sorted((Path(__file__).resolve().parent.parent / "vscapture" / "ui").glob("*.py")):
            if path.name in allow:
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#")[0]
                if '"""' in line or line.strip().startswith("#") or "log." in code:  # 記錄訊息維持繁中（與後端一致）
                    continue
                for lit in re.findall(r'"([^"]*)"', code):
                    if re.search(r"[一-鿿]", lit):
                        offenders.append(f"{path.name}:{i} {lit}")
        self.assertEqual(offenders, [], f"介面有寫死的中文：{offenders[:5]}")


class UpdateTests(SimpleTestCase):
    """自動更新：版本比較、逐塊下載＋sha256 驗證、解壓、覆寫。"""

    @staticmethod
    def _zip(path, version="0.2.0", extra=b"x"):
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(f"VisionSequenceCapture-{version}/VisionSequenceCapture.exe", b"MZ" + extra)
            zf.writestr(f"VisionSequenceCapture-{version}/VisionSequenceCapture-console.exe", b"MZ" + extra)
            zf.writestr(f"VisionSequenceCapture-{version}/_internal/data.bin", extra * 10)
        return path.read_bytes()

    def test_version_compare(self):
        self.assertTrue(P.is_newer("0.2.0", "0.1.9"))
        self.assertTrue(P.is_newer("1.0", "0.9.9"))
        self.assertTrue(P.is_newer("0.1.10", "0.1.9"))
        self.assertFalse(P.is_newer("0.1.0", "0.1.0"))
        self.assertFalse(P.is_newer("0.1.0", "0.2.0"))
        self.assertFalse(P.is_newer("", "0.1.0"))
        self.assertEqual(P.version_tuple("0.2.0"), (0, 2, 0, 0))
        self.assertEqual(P.version_tuple("1.2.3rc4"), (1, 2, 34, 0))

    def test_download_verify_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blob = self._zip(root / "src.zip")
            digest = hashlib.sha256(blob).hexdigest()
            info = update.UpdateInfo(available=True, version="0.2.0", filename="VisionSequenceCapture-0.2.0-win64.zip", size=len(blob), sha256=digest, chunk=64)
            calls = []

            def pull(offset, length):
                calls.append((offset, length))
                chunk = blob[offset : offset + length]
                return chunk, offset + len(chunk) >= len(blob)

            seen = []
            zip_path = update.download(pull, info, dest=root / "dl", on_progress=lambda got, total: seen.append(got))
            self.assertEqual(zip_path.read_bytes(), blob)
            self.assertGreater(len(calls), 1)
            self.assertEqual(seen[-1], len(blob))
            self.assertEqual(list((root / "dl").glob("*.part")), [])
            staged = update.stage(zip_path, "0.2.0", dest=root / "st")
            self.assertTrue((staged / "VisionSequenceCapture.exe").is_file())
            self.assertTrue((staged / "_internal" / "data.bin").is_file())
            # sha256 不符要丟掉，不留半成品
            bad = update.UpdateInfo(available=True, version="0.2.0", filename="bad.zip", size=len(blob), sha256="00" * 32, chunk=64)
            with self.assertRaises(update.UpdateError):
                update.download(pull, bad, dest=root / "dl2")
            self.assertEqual(list((root / "dl2").glob("*")), [])
            # 長度不符也要擋
            short = update.UpdateInfo(available=True, version="0.2.0", filename="s.zip", size=len(blob) + 10, sha256="", chunk=64)
            with self.assertRaises(update.UpdateError):
                update.download(pull, short, dest=root / "dl3")

    def test_stage_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evil = root / "evil.zip"
            with zipfile.ZipFile(evil, "w") as zf:
                zf.writestr("../outside.exe", b"MZ")
            with self.assertRaises(update.UpdateError):
                update.stage(evil, "0.2.0", dest=root / "st")

    def test_updater_copies_over_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, dst = root / "new", root / "app"
            (src / "_internal").mkdir(parents=True)
            (src / "VisionSequenceCapture.exe").write_bytes(b"NEW")
            (src / "_internal" / "lib.dll").write_bytes(b"L2")
            dst.mkdir()
            (dst / "VisionSequenceCapture.exe").write_bytes(b"OLD")
            (dst / "keep.json").write_text("{}", encoding="utf-8")
            update._copy_tree(src, dst)  # noqa: SLF001
            self.assertEqual((dst / "VisionSequenceCapture.exe").read_bytes(), b"NEW")
            self.assertEqual((dst / "_internal" / "lib.dll").read_bytes(), b"L2")
            self.assertTrue((dst / "keep.json").is_file())  # 不動使用者的檔案

    def test_cleanup_keeps_current_staging(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(update, "updates_dir", return_value=Path(tmp)):
            (Path(tmp) / "staging-0.1.0").mkdir()
            (Path(tmp) / "staging-0.2.0").mkdir()
            (Path(tmp) / "old.zip").write_bytes(b"x")
            update.cleanup(keep_version="0.2.0")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["staging-0.2.0"])


class PackagingTests(SimpleTestCase):
    """scripts/package_capture_client.py：zip＋manifest 與 /capture/download/info 的接縫。"""

    @staticmethod
    def _packager():
        import importlib.util

        path = Path(__file__).resolve().parent.parent / "scripts" / "package_capture_client.py"
        spec = importlib.util.spec_from_file_location("package_capture_client", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_zip_manifest_and_download_info(self):
        import hashlib
        import zipfile

        from django.test import override_settings

        from apps.vision.capture.api import download_info

        pk = self._packager()
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "dist" / "VisionSequenceCapture"
            (dist / "_internal" / "PySide6").mkdir(parents=True)
            (dist / "VisionSequenceCapture.exe").write_bytes(b"MZ" + bytes(1000))
            (dist / "VisionSequenceCapture-console.exe").write_bytes(b"MZ" + bytes(500))
            (dist / "_internal" / "PySide6" / "Qt6Core.dll").write_bytes(bytes(2000))
            out = Path(tmp) / "downloads"
            m = pk.package(dist, out, "0.1.0", sdks=["pypylon"])
            self.assertEqual(m["filename"], "VisionSequenceCapture-0.1.0-win64.zip")
            self.assertEqual(m["files"], 3)
            self.assertEqual(m["sdks"], ["pypylon"])
            self.assertTrue(m["built_at"].endswith("Z"))
            zpath = out / m["filename"]
            self.assertEqual(m["size"], zpath.stat().st_size)
            self.assertEqual(m["sha256"], hashlib.sha256(zpath.read_bytes()).hexdigest())
            with zipfile.ZipFile(zpath) as zf:
                names = set(zf.namelist())
                self.assertIn("VisionSequenceCapture-0.1.0/README.txt", names)
                self.assertIn("VisionSequenceCapture-0.1.0/VisionSequenceCapture-console.exe", names)
                self.assertIn("VisionSequenceCapture-0.1.0/_internal/PySide6/Qt6Core.dll", names)
                readme = zf.read("VisionSequenceCapture-0.1.0/README.txt").decode("utf-8")
            self.assertIn("Basler（pylon）", readme)
            self.assertNotIn("OpenCV", readme)
            self.assertIn("\r\n", readme)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["sha256"], m["sha256"])
            # 伺服端 API 讀同一份 manifest
            with override_settings(DATA_DIR=Path(tmp)):
                info = download_info()
            self.assertTrue(info["available"])
            self.assertEqual((info["version"], info["filename"], info["sha256"], info["size"]), ("0.1.0", m["filename"], m["sha256"], m["size"]))
            # 再打一版：預設只留最新的 zip
            m2 = pk.package(dist, out, "0.2.0")
            self.assertEqual(sorted(p.name for p in out.glob("*.zip")), [m2["filename"]])
            self.assertIn("無（只有網路攝影機", pk.readme_text("0.2.0", []))
            with self.assertRaises(FileNotFoundError):
                pk.package(Path(tmp) / "nope", out, "0.3.0")

    def test_cli(self):
        pk = self._packager()
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "d"
            dist.mkdir()
            (dist / "a.exe").write_bytes(b"x")
            self.assertEqual(pk.main(["--dist", str(dist), "--out", str(Path(tmp) / "o"), "--version", "9.9.9", "--sdks", "ids_peak, pyueye"]), 0)
            manifest = json.loads((Path(tmp) / "o" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual((manifest["version"], manifest["sdks"]), ("9.9.9", ["ids_peak", "pyueye"]))
