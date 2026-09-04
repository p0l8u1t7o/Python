"""擷取端程式（vscapture）：設定、影格槽、模擬相機、通道執行緒、共享記憶體環、對真 hub 的 loopback 傳輸、headless CLI。

不需要相機也不需要 Qt；`vscapture` 的核心模組不在模組層 import PySide6 或相機 SDK。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
from django.test import SimpleTestCase

from apps.vision.capture.hub import CaptureError, hub
from tests.test_comm import free_port
from vscapture import app as appmod
from vscapture import config as configmod
from vscapture import protocol as P
from vscapture.cameras.base import CameraParamError
from vscapture.cameras.fake import FakeCamera
from vscapture.channel import Channel, ChannelState
from vscapture.config import AppConfig, ChannelConfig, ConfigError, ConnectionConfig, DeliveryConfig, Roi
from vscapture.engine import CaptureEngine
from vscapture.frames import Frame, FrameSlot, crop_roi, encode, prepare
from vscapture.protocol import Encoding
from vscapture.shm import ShmRing
from vscapture.transport.client import ConnState


def _wait(pred, timeout=3.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


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


class FakeCameraTests(SimpleTestCase):
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

