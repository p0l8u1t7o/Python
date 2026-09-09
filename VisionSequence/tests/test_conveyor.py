from __future__ import annotations

import socket
import threading
import time
from typing import Any
from unittest import mock

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.comm import writers
from apps.comm.writers import TcpClientWriter
from apps.vision import engine, variables
from apps.vision.agent import service
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.tools import base
from apps.vision.tools.base import Result, ToolContext, ToolError
from apps.vision.dl import yolo_runtime
from tests.fakes import MemoryWriter
from tests._helpers import run_tool


class T:
    def __init__(self, value: Any):
        self.value = np.asarray(value)

    def cpu(self):
        return self

    def numpy(self):
        return self.value

    def __len__(self):
        return len(self.value)


class Boxes:
    def __init__(self, xyxy, conf, cls, track_id=None):
        self.xyxy, self.conf, self.cls = T(xyxy), T(conf), T(cls)
        self.id = None if track_id is None else T(track_id)

    def __len__(self):
        return len(self.xyxy)


class Masks:
    def __init__(self, data):
        self.data = T(data)


class Res:
    def __init__(self, boxes=None, masks=None):
        self.boxes = boxes
        self.masks = masks


class FakeModel:
    task = "segment"
    names = {0: "part"}


def _ctx(key: str, params: dict[str, Any], inputs: dict[str, Any], *, flow_id: int = 810, context: dict[str, Any] | None = None) -> ToolContext:
    tool = base.get(key)
    return ToolContext(
        run_id=f"{key}-test", flow_id=flow_id, node={"id": key, "type": key, "params": params},
        inputs=inputs, context=context if context is not None else {}, moment=0.0, log=lambda *a, **k: None,
        asset_path=lambda aid: None, grab=lambda sid: None, preview=False, depth=getattr(tool, "accepts", ("u8",)),
    )


def _match(cy: float, *, track_id: int = 7) -> dict[str, Any]:
    poly = [[90.0, cy - 30.0], [150.0, cy - 30.0], [150.0, cy + 30.0], [90.0, cy + 30.0]]
    return {"label": "part", "index": 0, "score": 0.9, "x": 90.0, "y": cy - 30.0, "w": 60.0, "h": 60.0,
            "cx": 120.0, "cy": cy, "centroid": [120.0, cy], "polygon": poly, "track_id": track_id}


class ConveyorCoreTests(SimpleTestCase):
    def setUp(self):
        variables.store.clear()
        self.addCleanup(variables.store.clear)
        writers.close_all()
        self.addCleanup(writers.close_all)

    def test_edge_filter_then_tracking_confirms_once_and_reset_keeps_id_monotonic(self):
        image = np.zeros((240, 240, 3), np.uint8)
        edge = base.get("edge_filter")
        track = base.get("track_objects")
        params = {"state_name": "conv", "max_distance": 80, "max_missing": 1, "confirm_frames": 2, "motion": "linear"}
        new_ids = []
        for cy in (30.0, 90.0, 150.0, 180.0):
            er = edge.execute(_ctx("edge_filter", {"margin_top": 50, "margin_bottom": 50, "margin_left": 0, "margin_right": 0}, {"matches": [_match(cy)], "image": image}))
            tr = track.execute(_ctx("track_objects", params, {"matches": er.outputs["matches"]}))
            new_ids.extend(t["id"] for t in tr.outputs["new_confirmed"])
        self.assertEqual(new_ids, [1])

        reset = track.execute(_ctx("track_objects", {**params, "reset": True}, {"matches": [_match(100.0, track_id=99)]}))
        self.assertGreater(reset.outputs["tracks"][0]["id"], 1)
        after = track.execute(_ctx("track_objects", params, {"matches": [_match(150.0, track_id=99)]}))
        self.assertEqual(after.outputs["new_confirmed"][0]["id"], reset.outputs["tracks"][0]["id"])

    def test_edge_filter_needs_the_image_for_bottom_and_right_margins(self):
        """沒有影像就判不了下邊與右邊；第一版把影像埠設成選填時，碰下邊的物體會被靜默放行（探針抓到）。"""
        edge = base.get("edge_filter")
        image = np.zeros((240, 240, 3), np.uint8)
        bottom = _match(230.0)
        kept = edge.execute(_ctx("edge_filter", {"margin_top": 50, "margin_bottom": 50, "margin_left": 0, "margin_right": 0}, {"matches": [bottom], "image": image}))
        self.assertEqual(kept.outputs["matches"], [])
        with self.assertRaises(ToolError):
            edge.execute(_ctx("edge_filter", {"margin_top": 50, "margin_bottom": 50, "margin_left": 0, "margin_right": 0}, {"matches": [bottom]}))

    def test_format_text_items_one_line_per_match(self):
        items = [
            {"label": "part", "index": 3, "centroid": [12.345, 67.891]},
            {"label": "part", "index": 4, "centroid": [20.0, 80.5], "z": 1.25},
        ]
        r = run_tool("format_text", params={"each_template": "{index},{centroid[0]:.2f},{centroid[1]:.2f},{z:.2f}", "join": "\\n"}, inputs={"items": items})
        self.assertEqual(r.outputs["lines"], ["3,12.35,67.89,0.00", "4,20.00,80.50,1.25"])
        self.assertEqual(r.outputs["text"], "3,12.35,67.89,0.00\n4,20.00,80.50,1.25")

    def test_tcp_client_queue_returns_quickly_drops_oldest_and_recovers(self):
        port = _free_port()
        writer = TcpClientWriter({"host": "127.0.0.1", "port": port, "timeout_s": 0.05, "queue": True, "queue_size": 2, "newline": "\n"}, name="robot")
        self.addCleanup(writer.close)
        durations = []
        for i in range(6):
            t0 = time.perf_counter()
            writer.send_text(f"m{i}")
            durations.append(time.perf_counter() - t0)
        self.assertLess(max(durations), 0.005)
        self.assertGreaterEqual(writer.info()["dropped"], 1)

        received: list[str] = []
        stop = threading.Event()
        thread = threading.Thread(target=_line_server, args=(port, received, stop), daemon=True)
        thread.start()
        self.addCleanup(stop.set)
        deadline = time.time() + 3.0
        while time.time() < deadline and not any("m5" in line for line in received):
            time.sleep(0.02)
            writer.send_text("m5")
        self.assertTrue(any("m5" in line for line in received), received)
        self.assertFalse(any(line.strip() == "m0" for line in received), received)

    def test_validate_graph_and_engine_sequence_send_only_new_confirmed(self):
        robot = MemoryWriter({}, name="robot")
        writers.register_writer("robot", robot)
        graph = _conveyor_graph()
        compiled = compile_graph(validate_graph(graph))
        images = [np.zeros((240, 240, 3), np.uint8) for _ in range(6)]

        def fake_segment(_self, ctx):
            idx = int(str(ctx.run_id).removeprefix("seq")) if str(ctx.run_id).startswith("seq") else 0
            cy = (30.0, 90.0, 150.0, 180.0, 190.0, 220.0)[idx]
            matches = [_match(cy)]
            return Result(outputs={"count": 1, "matches": matches, "mask": np.zeros((240, 240), np.uint8), "contours": [], "labels": ["part"], "centroids": [[120.0, cy]]})

        with mock.patch.object(type(base.get("ai_segment")), "execute", fake_segment):
            service.trial_run(validate_graph(graph), images[0], keep_images=False)
            for i, image in enumerate(images):
                rep = engine.execute(compiled, flow_id=811, flow_version=1, trigger="test", grab=lambda sid: image, asset_path=lambda aid: None,
                                     preview=False, input_image=image, run_id=f"seq{i}")
                self.assertNotEqual(rep.status, "error", rep.error)
        sent = [row["values"]["line"] for row in robot.history if row["values"].get("line")]
        self.assertEqual(sent, ["0,120.00,150.00,0.00"])

    def test_ai_segment_polygon_and_centroid_use_largest_mask_piece(self):
        mask = np.zeros((1, 100, 100), np.float32)
        mask[0, 20:80, 20:35] = 1
        mask[0, 65:80, 20:80] = 1
        mask[0, 5:12, 5:12] = 1
        res = Res(boxes=Boxes([[0, 0, 90, 90]], [0.95], [0]), masks=Masks(mask))
        model = FakeModel()
        with mock.patch.object(yolo_runtime, "load", return_value=model), \
             mock.patch.object(yolo_runtime, "predict", return_value=res), \
             mock.patch.object(yolo_runtime, "names_of", return_value={0: "part"}), \
             mock.patch.object(yolo_runtime, "task_of", return_value="segment"), \
             mock.patch.object(yolo_runtime, "pick_device", return_value=("cpu", "")):
            r = run_tool("ai_segment", np.zeros((100, 100, 3), np.uint8), {"model_name": "x.pt", "max_polygon_points": 12})
        match = r.outputs["matches"][0]
        largest = np.zeros((100, 100), np.uint8)
        largest[20:80, 20:35] = 1
        largest[65:80, 20:80] = 1
        moments = cv2.moments(largest, binaryImage=True)
        want = [round(moments["m10"] / moments["m00"], 2), round(moments["m01"] / moments["m00"], 2)]
        self.assertEqual(match["centroid"], want)
        self.assertLessEqual(len(match["polygon"]), 12)
        self.assertEqual(r.outputs["centroids"], [want])


def _conveyor_graph() -> dict[str, Any]:
    nodes = [
        {"id": "src", "type": "image_source", "params": {"mode": "auto"}},
        {"id": "seg", "type": "ai_segment", "params": {"model_name": "x.pt", "min_count": 0}},
        {"id": "edge", "type": "edge_filter", "params": {"margin_top": 50, "margin_bottom": 50, "margin_left": 0, "margin_right": 0}},
        {"id": "trk", "type": "track_objects", "params": {"state_name": "conv_graph", "max_distance": 80, "max_missing": 1, "confirm_frames": 2}},
        {"id": "fmt", "type": "format_text", "params": {"name": "line", "template": "{judge}", "each_template": "{index},{centroid[0]:.2f},{centroid[1]:.2f},0.00", "join": "\\n"}},
        {"id": "send", "type": "write_modbus", "params": {"connection": "robot", "mapping": [{"src": "line", "address": "line"}]}},
    ]
    edges = [
        {"source": "src", "target": "seg"},
        {"source": "seg", "target": "edge", "source_handle": "matches", "target_handle": "matches"},
        {"source": "src", "target": "edge", "source_handle": "image", "target_handle": "image"},
        {"source": "edge", "target": "trk", "source_handle": "matches", "target_handle": "matches"},
        {"source": "trk", "target": "fmt", "source_handle": "new_confirmed", "target_handle": "items"},
        {"source": "fmt", "target": "send", "source_handle": "text", "target_handle": "values"},
    ]
    return {"nodes": nodes, "edges": edges}


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _line_server(port: int, received: list[str], stop: threading.Event) -> None:
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen()
    server.settimeout(0.1)
    try:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            with conn:
                conn.settimeout(0.1)
                data = b""
                while not stop.is_set():
                    try:
                        chunk = conn.recv(4096)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    data += chunk
                    while b"\n" in data:
                        line, data = data.split(b"\n", 1)
                        received.append(line.decode("utf-8", errors="replace"))
    finally:
        server.close()
