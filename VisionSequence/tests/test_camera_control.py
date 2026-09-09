"""相機控制：CHANNEL_SET 協定、API、工具層與 capture grabber 快取。"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from django.test import TransactionTestCase

from apps.vision import sources
from apps.vision.capture.hub import hub
from apps.vision.models import ImageSource
from apps.vision.tools import base, register_builtins
from apps.vision.tools.base import ToolContext
from tests.test_capture import FakeCaptureClient, _wait
from tests.test_comm import free_port

register_builtins()


def _channels() -> list[dict[str, Any]]:
    return [{
        "id": "cam0",
        "label": "Fake cam",
        "driver": "fake",
        "width": 64,
        "height": 48,
        "channels": 1,
        "dtype": "u8",
        "params": [
            {"name": "exposure_us", "label": "Exposure", "type": "float", "value": 10000, "minimum": 10, "maximum": 1000000},
            {"name": "gain_db", "label": "Gain", "type": "float", "value": 0, "minimum": 0, "maximum": 24},
        ],
        "outputs": ["Line1", "Line2"],
    }]


class CameraControlApiTests(TransactionTestCase):
    def setUp(self) -> None:
        self.port = free_port()
        hub.start("127.0.0.1", self.port)
        self.clients: list[FakeCaptureClient] = []
        self.client_app = self.client

    def tearDown(self) -> None:
        sources.close_all()
        for client in self.clients:
            client.close()
        hub.stop()
        _wait(lambda: not hub.clients(), 2.0)

    def connect(self, name: str = "api-cam") -> FakeCaptureClient:
        client = FakeCaptureClient(self.port, name=name, channels=_channels())
        self.clients.append(client)
        client.start()
        client.wait_ready()
        self.assertTrue(client.welcome["ok"], client.welcome)
        return client

    def test_params_api_get_and_patch(self):
        fake = self.connect()
        response = self.client_app.get("/api/vision/capture/clients/api-cam/channels/cam0/params")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["outputs"], ["Line1", "Line2"])
        self.assertEqual({p["name"] for p in body["params"]}, {"exposure_us", "gain_db"})
        self.assertTrue(body["features"]["channel_set"])

        response = self.client_app.patch(
            "/api/vision/capture/clients/api-cam/channels/cam0/params",
            data='{"params":{"exposure_us":7000}}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["applied"], {"exposure_us": 7000})
        self.assertEqual(fake.channel_sets[-1]["params"], {"exposure_us": 7000})


class CameraControlToolTests(TransactionTestCase):
    def setUp(self) -> None:
        self.port = free_port()
        hub.start("127.0.0.1", self.port)
        self.clients: list[FakeCaptureClient] = []
        self.source = ImageSource.objects.create(
            name="cap",
            kind="capture",
            config={"client": "tool-cam", "channel": "cam0", "timeout_ms": 1000, "fresh": True},
        )

    def tearDown(self) -> None:
        sources.close_all()
        for client in self.clients:
            client.close()
        hub.stop()
        _wait(lambda: not hub.clients(), 2.0)

    def connect(self, name: str = "tool-cam") -> FakeCaptureClient:
        client = FakeCaptureClient(self.port, name=name, channels=_channels())
        self.clients.append(client)
        client.start()
        client.wait_ready()
        self.assertTrue(client.welcome["ok"], client.welcome)
        return client

    def ctx(self, key: str, params: dict[str, Any], *, inputs: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> ToolContext:
        tool = base.get(key)
        return ToolContext(
            run_id="test",
            flow_id=1,
            node={"id": key, "type": key, "params": params},
            inputs=inputs or {},
            context=context or {},
            moment=time.time(),
            log=lambda *args, **kwargs: None,
            asset_path=lambda aid: None,
            grab=lambda sid: sources.grab_by_id(sid),
            preview=True,
            depth=getattr(tool, "accepts", ("u8",)),
        )

    def test_image_source_applies_exposure_before_grab_and_skips_same_values(self):
        fake = self.connect()
        tool = base.get("image_source")
        params = {"source_id": self.source.id, "exposure_us": 7000, "gain_db": 3.5}
        result = tool.execute(self.ctx("image_source", params))
        self.assertEqual(result.status, "ok", result.message)
        self.assertIsInstance(result.outputs["image"], np.ndarray)
        self.assertEqual(result.outputs["applied"], {"exposure_us": 7000.0, "gain_db": 3.5})
        self.assertEqual(len(fake.channel_sets), 1)
        self.assertEqual(fake.channel_sets[0]["params"], {"exposure_us": 7000.0, "gain_db": 3.5})

        second = tool.execute(self.ctx("image_source", params))
        self.assertEqual(second.status, "ok", second.message)
        self.assertEqual(len(fake.channel_sets), 1)

    def test_same_values_are_resent_after_capture_reconnect(self):
        first = self.connect()
        grabber = sources.open_source(self.source)
        self.assertTrue(grabber.set_params_once({"exposure_us": 5000})["ok"])
        self.assertEqual(len(first.channel_sets), 1)
        first.close()
        second = self.connect()
        self.assertTrue(_wait(lambda: hub.get("tool-cam") is not None, 2.0))
        self.assertTrue(grabber.set_params_once({"exposure_us": 5000})["ok"])
        self.assertEqual(len(second.channel_sets), 1)

    def test_camera_io_and_camera_set_tools_send_channel_commands(self):
        fake = self.connect()
        io_result = base.get("camera_io").execute(self.ctx("camera_io", {"source": self.source.id, "line": "Line2", "on_when": "ng", "pulse_ms": 25}, context={"_judge": "ng"}))
        self.assertEqual(io_result.outputs, {"ok": True, "active": True})
        self.assertEqual(fake.channel_sets[-1]["command"], "line_out")
        self.assertEqual(fake.channel_sets[-1]["args"], {"line": "Line2", "level": True, "pulse_ms": 25})

        set_result = base.get("camera_set").execute(self.ctx(
            "camera_set",
            {"source": self.source.id, "values": "trigger_source=Line1\ntrigger_delay_us=15", "user_set": "save", "user_set_name": "job1"},
        ))
        self.assertTrue(set_result.outputs["ok"], set_result.message)
        self.assertEqual(fake.channel_sets[-2]["params"], {"trigger_source": "Line1", "trigger_delay_us": 15})
        self.assertEqual(fake.channel_sets[-1]["command"], "save_user_set")
