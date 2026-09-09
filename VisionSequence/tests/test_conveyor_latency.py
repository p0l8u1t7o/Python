from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import connections
from django.test import TransactionTestCase, override_settings

from apps.vision import engine, sources
from apps.vision.capture.hub import hub
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.models import Flow, ImageSource
from apps.vision.runner import runner
from tests.test_capture import FakeCaptureClient
from tests.test_capture_client import _wait
from tests.test_comm import free_port
from vscapture.config import AppConfig, ChannelConfig, ConnectionConfig, DeliveryConfig
from vscapture.engine import CaptureEngine
from vscapture.transport.client import ConnState


@override_settings(VISION={**getattr(settings, "VISION", {}), "PERSIST_RUNS": False})
class ConveyorLatencyTests(TransactionTestCase):
    def setUp(self) -> None:
        self.port = free_port()
        hub.start("127.0.0.1", self.port)
        os.environ["VSCAPTURE_CONFIG"] = str(Path(tempfile.mkdtemp(prefix="vsc-lat-")) / "config.json")
        self.capture: CaptureEngine | None = None
        self.clients: list[FakeCaptureClient] = []

    def tearDown(self) -> None:
        for flow_id in list(runner._runtimes.keys()):  # noqa: SLF001
            runner.stop_continuous(flow_id)
            runner.forget(flow_id)
        sources.close_all()
        for client in self.clients:
            client.close()
        if self.capture is not None:
            self.capture.stop()
        hub.stop()
        os.environ.pop("VSCAPTURE_CONFIG", None)
        _wait(lambda: not hub.clients(), 2.0)
        connections.close_all()

    def _start_capture(self, *, client: str = "lat-pc", stream: bool = False) -> None:
        mode = "stream" if stream else "on_demand"
        cfg = AppConfig(
            connection=ConnectionConfig(host="127.0.0.1", port=self.port, client_name=client, auto_connect=False, heartbeat_s=1.0, reconnect_max_s=2.0),
            channels=[
                ChannelConfig(id="left", name="Left", backend="fake", device_id="fake:0", delivery=DeliveryConfig(encoding="raw", mode=mode)),
                ChannelConfig(id="right", name="Right", backend="fake", device_id="fake:1", delivery=DeliveryConfig(encoding="raw", mode=mode)),
            ],
        )
        self.capture = CaptureEngine(cfg)
        self.capture.start(connect=False)
        self.capture.connect()
        self.assertTrue(_wait(lambda: self.capture is not None and self.capture.transport.state == ConnState.CONNECTED, 5.0))
        self.assertTrue(_wait(lambda: hub.get(client) is not None, 3.0))

    def _capture_source(self, name: str, channel: str, *, client: str = "lat-pc", mode: str = "on_demand") -> ImageSource:
        return ImageSource.objects.create(name=name, kind="capture", config={"client": client, "channel": channel, "timeout_ms": 1000, "mode": mode})

    def test_frame_meta_has_capture_and_receive_timestamps(self) -> None:
        self._start_capture()
        frame = hub.request_frame("lat-pc", "left", timeout=2.0)
        self.assertIsNotNone(frame.meta.captured_at)
        self.assertGreater(frame.meta.received_at, 0)
        self.assertLess(abs(frame.meta.received_at - (frame.meta.captured_at or 0)) * 1000.0, 100.0)
        self.assertLess(abs(time.time() - frame.meta.received_at) * 1000.0, 1000.0)

    def test_run_report_timing_keys_and_totals(self) -> None:
        self._start_capture()
        src = self._capture_source("left-src", "left")
        flow = Flow.objects.create(name="latency-flow", graph={
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": src.id}},
                {"id": "gray", "type": "grayscale", "params": {}},
            ],
            "edges": [{"source": "src", "target": "gray", "source_handle": "image", "target_handle": "image"}],
        })
        runner.forget(flow.id)
        compiled = compile_graph(validate_graph(flow.graph))
        report = engine.execute(compiled, flow_id=flow.id, flow_version=flow.version, trigger="preview", grab=sources.grab_by_id, asset_path=lambda _aid: None)
        runner._record(runner.runtime(flow.id), report)  # noqa: SLF001
        self.assertEqual(report.status, "ok", report.error)
        timing = report.timing
        for key in ("grab_ms", "frame_age_ms", "since_capture_ms", "nodes_ms", "record_ms", "total_ms"):
            self.assertIn(key, timing)
        self.assertGreaterEqual(timing["grab_ms"], 0.0)
        self.assertGreaterEqual(timing["frame_age_ms"], 0.0)
        self.assertGreaterEqual(timing["since_capture_ms"], timing["frame_age_ms"])
        self.assertIn("src", timing["nodes_ms"])
        self.assertGreaterEqual(timing["total_ms"], report.duration_ms)
        self.assertLess(abs(timing["total_ms"] - (report.duration_ms + timing["record_ms"])), 5.0)

    def test_request_pair_returns_two_frames_and_dt(self) -> None:
        self._start_capture()
        left, right, dt_ms = hub.request_pair("lat-pc", "left", "right", timeout=2.0)
        self.assertEqual(left.image.shape, (480, 640, 3))
        self.assertEqual(right.image.shape, (480, 640, 3))
        self.assertIsNotNone(dt_ms)
        self.assertGreaterEqual(dt_ms or 0, 0.0)

    def test_stereo_grab_validate_graph_flow_can_run(self) -> None:
        self._start_capture()
        left = self._capture_source("left-src", "left")
        right = self._capture_source("right-src", "right")
        graph: dict[str, Any] = {
            "nodes": [
                {"id": "stereo", "type": "stereo_grab", "params": {"left": left.id, "right": right.id, "timeout_ms": 1000, "max_dt_ms": 1000}},
                {"id": "gray", "type": "grayscale", "params": {}},
            ],
            "edges": [{"source": "stereo", "target": "gray", "source_handle": "image", "target_handle": "image"}],
        }
        compiled = compile_graph(validate_graph(graph))
        report = engine.execute(compiled, flow_id=991, flow_version=1, trigger="stereo-test", grab=sources.grab_by_id, asset_path=lambda _aid: None)
        self.assertEqual(report.status, "ok", report.error)
        self.assertIn("dt_ms", report.nodes["stereo"].outputs)
        self.assertIsNotNone(report.nodes["stereo"].outputs["dt_ms"])

    def test_old_capture_client_zero_timestamp_is_accepted(self) -> None:
        old = FakeCaptureClient(
            self.port,
            name="old-pc",
            channels=[{"id": "cam0", "width": 32, "height": 24, "channels": 1, "dtype": "u8"}],
            captured_timestamp=False,
        )
        self.clients.append(old)
        old.start()
        old.wait_ready()
        self.assertTrue(_wait(lambda: hub.get("old-pc") is not None, 2.0))
        frame = hub.request_frame("old-pc", "cam0", timeout=1.0)
        self.assertEqual(frame.image.shape, (24, 32))
        self.assertIsNone(frame.meta.captured_at)
        self.assertGreater(frame.meta.received_at, 0.0)

    def test_stream_source_frame_age_under_fake_camera(self) -> None:
        self._start_capture(stream=True)
        src = self._capture_source("stream-left", "left", mode="stream")
        graph = {
            "nodes": [{"id": "src", "type": "image_source", "params": {"source_id": src.id}}],
            "edges": [],
        }
        compiled = compile_graph(validate_graph(graph))
        reports = [
            engine.execute(compiled, flow_id=992, flow_version=1, trigger="stream-test", grab=sources.grab_by_id, asset_path=lambda _aid: None)
            for _ in range(8)
        ]
        samples = [float(r.timing["frame_age_ms"]) for r in reports if r.timing.get("frame_age_ms") is not None]
        self.assertGreaterEqual(len(samples), 3)
        samples.sort()
        p95 = samples[min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))]
        self.assertLess(p95, 50.0)
