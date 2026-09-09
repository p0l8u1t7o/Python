"""多光源取像、融合與批次取像的端到端替身測試。"""

from __future__ import annotations

import math
import time
from typing import Any

import cv2
import numpy as np
from django.test import TransactionTestCase

from apps.comm import writers
from apps.vision import sources
from apps.vision.capture.hub import hub
from apps.vision.models import ImageSource
from apps.vision.tools import base, register_builtins
from apps.vision.tools.base import ToolContext, ToolError
from tests._helpers import run_tool
from tests.fakes import MemoryWriter
from tests.test_capture import FakeCaptureClient, _wait
from tests.test_comm import free_port

register_builtins()


class LightMemoryWriter(MemoryWriter):
    """以 MemoryWriter.history 的時間戳記錄光源 set_light 語意。"""

    def __init__(self, config: dict[str, Any], **kw: Any) -> None:
        super().__init__(config, **kw)
        self.value_max = int(config.get("value_max", 255) or 255)
        self.strobe = str(config.get("strobe") or "steady")
        self.lead_time_ms = int(config.get("lead_time_ms", 0) or 0)
        self.channel_values = {int(k): int(v) for k, v in dict(config.get("initial") or {}).items()}

    def set_light(self, channel: int, value: int | None = None, mode: str = "brightness", *, timeout: float | None = None,
                  quiet: bool = False) -> dict[str, Any]:
        del timeout, quiet
        ch = int(channel)
        if mode == "off":
            level = 0
        elif mode == "on":
            level = int(value if value is not None else self.channel_values.get(ch, self.value_max))
        else:
            level = int(value if value is not None else 0)
            mode = "brightness"
        self.channel_values[ch] = level
        item = {"at": time.time(), "values": {str(ch): {"mode": mode, "value": level}}}
        self.history.append(item)
        self.writes += 1
        self.last_write_at = item["at"]
        return {"written": 1, "command": f"{mode}:{ch}:{level}", "channel": ch, "value": level, "mode": mode}


class MultiLightTests(TransactionTestCase):
    """fake capture hub 與 MemoryWriter 共同驗證取像順序。"""

    def setUp(self) -> None:
        self.port = free_port()
        hub.start("127.0.0.1", self.port)
        self.clients: list[FakeCaptureClient] = []

    def tearDown(self) -> None:
        for client in self.clients:
            client.close()
        writers.close_all()
        sources.close_all()
        hub.stop()

    def connect(self, **kw: Any) -> FakeCaptureClient:
        client = FakeCaptureClient(self.port, **kw)
        self.clients.append(client)
        client.start()
        client.wait_ready()
        self.assertTrue(_wait(lambda: hub.get(client.client_name) is not None), client.welcome)
        return client

    def ctx(self, key: str, params: dict[str, Any], *, inputs: dict[str, Any] | None = None,
            context: dict[str, Any] | None = None) -> ToolContext:
        tool = base.get(key)
        return ToolContext(
            run_id="test", flow_id=1, node={"id": key, "type": key, "params": params}, inputs=inputs or {},
            context=context or {}, moment=0.0, log=lambda *a, **k: None, asset_path=lambda aid: None,
            grab=sources.grab_by_id, preview=True, depth=getattr(tool, "accepts", ("u8",)),
        )

    def capture_source(self, client: str = "ml-cam") -> ImageSource:
        self.connect(name=client, channels=[{"id": "cam0", "width": 16, "height": 12, "channels": 1, "dtype": "u8"}])
        return ImageSource.objects.create(
            name=f"{client}-source", kind="capture",
            config={"client": client, "channel": "cam0", "timeout_ms": 1000, "fresh": True},
        )

    def register_light(self, name: str = "light", **config: Any) -> LightMemoryWriter:
        light = LightMemoryWriter(config, name=name)
        writers.register_writer(name, light)
        return light

    def test_multi_light_grab_orders_light_settle_then_fresh_frame(self) -> None:
        frame_times: dict[int, float] = {}

        def factory(c: dict[str, Any], seq: int) -> np.ndarray:
            frame_times[seq] = time.time()
            return np.full((int(c["height"]), int(c["width"])), seq, np.uint8)

        self.connect(name="timed", channels=[{"id": "cam0", "width": 16, "height": 12, "channels": 1, "dtype": "u8"}],
                     frame_factory=factory)
        src = ImageSource.objects.create(name="timed-source", kind="capture", config={"client": "timed", "channel": "cam0", "timeout_ms": 1000})
        light = self.register_light("timed-light")
        params = {
            "source": src.id, "connection": "timed-light", "steps": "1,10,2000,0,35\n2,20,2000,90,35\n3,30,2000,180,35",
            "settle_ms": 60, "timeout_ms": 1000,
        }

        result = base.get("multi_light_grab").execute(self.ctx("multi_light_grab", params))

        self.assertEqual(result.outputs["count"], 3)
        self.assertEqual([int(im[0, 0]) for im in result.outputs["images"]], [1, 2, 3])
        self.assertEqual([h["values"] for h in light.history], [
            {"1": {"mode": "brightness", "value": 10}},
            {"2": {"mode": "brightness", "value": 20}},
            {"3": {"mode": "brightness", "value": 30}},
            {"1": {"mode": "off", "value": 0}},
            {"2": {"mode": "off", "value": 0}},
            {"3": {"mode": "off", "value": 0}},
        ])
        for index, seq in enumerate((1, 2, 3)):
            delta = frame_times[seq] - light.history[index]["at"]
            self.assertGreaterEqual(delta, 0.045, f"step {index + 1} settled only {delta * 1000:.1f} ms")
        self.assertTrue(result.detail["lit"])

    def test_strobe_wraps_each_frame_with_on_and_off(self) -> None:
        src = self.capture_source("strobe-cam")
        light = self.register_light("strobe-light", strobe="strobe", lead_time_ms=1)

        result = base.get("multi_light_grab").execute(self.ctx("multi_light_grab", {
            "source": src.id, "connection": "strobe-light", "steps": "1,11\n2,22", "settle_ms": 1, "timeout_ms": 1000,
        }))

        self.assertEqual(result.outputs["count"], 2)
        modes = [(next(iter(h["values"].items()))[0], next(iter(h["values"].items()))[1]["mode"]) for h in light.history]
        self.assertEqual(modes, [("1", "brightness"), ("1", "on"), ("1", "off"), ("2", "brightness"), ("2", "on"), ("2", "off"), ("1", "off"), ("2", "off")])

    def test_after_modes_off_keep_restore(self) -> None:
        for mode, expected in (("off", {1: 0, 2: 0}), ("keep", {1: 7, 2: 9}), ("restore", {1: 31, 2: 41})):
            with self.subTest(mode=mode):
                src = self.capture_source(f"after-{mode}")
                light = self.register_light(f"after-{mode}-light", initial={1: 31, 2: 41})
                result = base.get("multi_light_grab").execute(self.ctx("multi_light_grab", {
                    "source": src.id, "connection": f"after-{mode}-light", "steps": "1,7\n2,9",
                    "settle_ms": 1, "timeout_ms": 1000, "after": mode,
                }))
                self.assertEqual(result.outputs["count"], 2)
                self.assertEqual({k: light.channel_values.get(k) for k in (1, 2)}, expected)

    def test_missing_light_degrades_unless_required(self) -> None:
        src = self.capture_source("degraded-cam")

        result = base.get("multi_light_grab").execute(self.ctx("multi_light_grab", {
            "source": src.id, "connection": "missing-light", "steps": "1,5\n2,6", "settle_ms": 0, "timeout_ms": 1000,
        }))

        self.assertEqual(result.status, "ok")
        self.assertFalse(result.detail["lit"])
        self.assertEqual(result.outputs["count"], 2)
        with self.assertRaisesMessage(ToolError, "Connection 'missing-light' is not open"):
            base.get("multi_light_grab").execute(self.ctx("multi_light_grab", {
                "source": src.id, "connection": "missing-light", "steps": "1,5", "required": True,
            }))

    def test_non_capture_source_repeats_same_image(self) -> None:
        src = ImageSource.objects.create(name="synthetic", kind="synthetic", config={"width": 20, "height": 12, "pattern": "gradient"})

        result = base.get("multi_light_grab").execute(self.ctx("multi_light_grab", {
            "source": src.id, "connection": "missing-light", "steps": "1,5\n2,6\n3,7", "settle_ms": 0,
        }))

        self.assertEqual(result.outputs["count"], 3)
        self.assertTrue(any("Non-capture source" in warning for warning in result.detail["warnings"]))
        for image in result.outputs["images"][1:]:
            np.testing.assert_array_equal(image, result.outputs["images"][0])

    def test_image_source_frames_outputs_batch(self) -> None:
        src = self.capture_source("frames-cam")

        result = base.get("image_source").execute(self.ctx("image_source", {
            "source_id": src.id, "frames": 3, "frames_timeout_ms": 1000,
        }))

        self.assertEqual(len(result.outputs["images"]), 3)
        self.assertEqual([int(im[0, 0]) for im in result.outputs["images"]], [1, 2, 3])
        self.assertEqual(int(result.outputs["image"][0, 0]), 1)

    def test_multi_light_fuse_pixel_definitions(self) -> None:
        a = np.full((4, 5), 10, np.uint8)
        b = np.full((4, 5), 20, np.uint8)
        c = np.full((4, 5), 30, np.uint8)
        b[1, 2] = 250

        reflection = run_tool("multi_light_fuse", params={"mode": "reflection"}, inputs={"images": [a, b, c]})
        expected_reflection = np.median(np.stack([a, b, c], axis=0).astype(np.float32), axis=0).astype(np.uint8)
        np.testing.assert_array_equal(reflection.outputs["image"], expected_reflection)
        self.assertEqual(int(reflection.outputs["image"][1, 2]), 30)

        shadow = run_tool("multi_light_fuse", params={"mode": "shadow"}, inputs={"images": [a, a.copy(), a.copy()]})
        np.testing.assert_array_equal(shadow.outputs["image"], np.zeros_like(a))

        mean = run_tool("multi_light_fuse", params={"mode": "mean"}, inputs={"images": [a, b, c]})
        np.testing.assert_array_equal(mean.outputs["image"], np.clip(np.rint(np.mean(np.stack([a, b, c]).astype(np.float32), axis=0)), 0, 255).astype(np.uint8))

        ramp_x = np.tile(np.arange(5, dtype=np.uint8) * 20, (4, 1))
        ramp_y = np.tile((np.arange(4, dtype=np.uint8) * 30)[:, None], (1, 5))
        direction = run_tool("multi_light_fuse", params={"mode": "direction", "angle": 0, "normalize": False},
                             inputs={"images": [ramp_x, ramp_y], "azimuths": [0, 90]})
        gx = cv2.Sobel(ramp_x.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3, scale=1.0 / 8.0)
        gy = cv2.Sobel(ramp_y.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3, scale=1.0 / 8.0)
        expected_gradient = gx * math.cos(0) + gy * math.sin(math.radians(90)) * math.sin(0)
        np.testing.assert_allclose(direction.outputs["gradient"], expected_gradient.astype(np.float32))

    def test_photometric_images_port_matches_legacy_ports(self) -> None:
        from apps.vision.tools.builtin import photometric

        h, w = 40, 44
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        nx = (xx - w / 2) / 150.0
        ny = (yy - h / 2) / 150.0
        nz = np.ones_like(nx)
        normals = np.dstack([nx, ny, nz])
        normals /= np.linalg.norm(normals, axis=2, keepdims=True)
        lights = photometric.light_directions([0, 90, 180, 270], 30)
        images = [np.clip(180.0 * np.clip(normals @ lights[i], 0, None) + 10, 0, 255).astype(np.uint8) for i in range(4)]

        legacy = run_tool("photometric_stereo", images[0], {"output": "curvature"}, {
            "image_1": images[1], "image_2": images[2], "image_3": images[3],
        })
        multi = run_tool("photometric_stereo", params={"output": "curvature"}, inputs={"images": images})

        self.assertEqual(multi.outputs["lights"], legacy.outputs["lights"])
        for key, value in legacy.outputs.items():
            if isinstance(value, np.ndarray):
                np.testing.assert_array_equal(multi.outputs[key], value)
            else:
                self.assertEqual(multi.outputs[key], value)
