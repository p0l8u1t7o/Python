"""stereo 標定與輸送帶雙視野高度量測測試。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any

import cv2
import numpy as np
from django.test import SimpleTestCase, TransactionTestCase

from apps.vision import calib, engine
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.tools.builtin.output import FormatTextTool
from apps.vision.tools.base import ToolContext
from tests._helpers import run_tool


def _stereo_payload(w: int, h: int, *, z_ref: dict[str, float] | None = None) -> dict[str, Any]:
    f, baseline = 1200.0, 60.0
    stereo = {
        "left_source": "L",
        "right_source": "R",
        "M1": [[f, 0.0, w / 2], [0.0, f, h / 2], [0.0, 0.0, 1.0]],
        "D1": [0.0, 0.0, 0.0, 0.0, 0.0],
        "M2": [[f, 0.0, w / 2], [0.0, f, h / 2], [0.0, 0.0, 1.0]],
        "D2": [0.0, 0.0, 0.0, 0.0, 0.0],
        "R": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "T": [-baseline, 0.0, 0.0],
        "image_size": [w, h],
        "rms": 0.1,
        "baseline_mm": baseline,
        "board": {"pattern": "chessboard", "rows": 5, "cols": 7, "spacing": 20.0},
        "points": [{"index": 0, "error": 0.02}],
    }
    if z_ref is not None:
        stereo["z_ref"] = z_ref
    return {"unit": "mm", "image_size": [w, h], "stereo": stereo}


def _save_calibration(folder: str, payload: dict[str, Any]) -> str:
    path = os.path.join(folder, "stereo.json")
    calib.save(path, payload)
    return path


def _pair(
    w: int = 640,
    h: int = 360,
    *,
    obj_depth: float = 600.0,
    plane_depth: float = 800.0,
    motion_px: int = 0,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any], dict[str, Any]]:
    f, baseline = 1200.0, 60.0
    disp_obj = int(round(f * baseline / obj_depth))
    disp_plane = int(round(f * baseline / plane_depth))
    rng = np.random.default_rng(123)
    left = rng.integers(20, 80, (h, w), np.uint8)
    right = np.full_like(left, 45)
    right[:, : w - disp_plane] = left[:, disp_plane:]
    x, y, bw, bh = 260, 130, 120, 90
    texture = rng.integers(160, 255, (bh, bw), np.uint8)
    left[y : y + bh, x : x + bw] = texture
    right[y : y + bh, x - disp_obj : x - disp_obj + bw] = texture
    if motion_px:
        # motion_px > 0＝右相機晚拍、物體往 +x 走：右影像裡的物體再往 +x 多移 motion_px（對應 dt > 0）
        matrix = np.array([[1.0, 0.0, float(motion_px)], [0.0, 1.0, 0.0]], dtype=np.float32)
        right = cv2.warpAffine(right, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    match = {
        "index": 0,
        "label": "part",
        "polygon": [[x, y], [x + bw, y], [x + bw, y + bh], [x, y + bh]],
        "centroid": [x + bw / 2, y + bh / 2],
        "vx": 1.0 if motion_px else 0.0,
        "vy": 0.0,
    }
    plane = {"index": 1, "label": "belt", "bbox": [260, 30, 160, 80], "centroid": [340, 70]}
    return cv2.cvtColor(left, cv2.COLOR_GRAY2BGR), cv2.cvtColor(right, cv2.COLOR_GRAY2BGR), match, plane


def _run_stereo(path: str, left: np.ndarray, right: np.ndarray, matches: list[dict[str, Any]], **params: Any):
    dt_ms = params.pop("dt_ms", None)
    cfg = {"calibration": "st", "num_disparities": 160, "block_size": 5, "scale": 1.0, "min_valid_ratio": 0.5}
    cfg.update(params)
    inputs = {"image_right": right, "matches": matches}
    if dt_ms is not None:
        inputs["dt_ms"] = dt_ms
    return run_tool("stereo_depth", left, cfg, inputs, {"st": path})


class StereoDepthToolTests(SimpleTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vs-stereo-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_measures_depth_inside_object_mask(self):
        left, right, part, belt = _pair()
        path = _save_calibration(self.tmp, _stereo_payload(640, 360))
        res = _run_stereo(path, left, right, [part, belt])
        self.assertEqual(res.status, "ok", res.message)
        self.assertAlmostEqual(res.outputs["matches"][0]["distance_mm"], 600.0, delta=6.0)
        self.assertAlmostEqual(res.outputs["matches"][1]["distance_mm"], 800.0, delta=8.0)
        self.assertGreater(res.outputs["matches"][1]["valid_ratio"], 0.9)
        self.assertIsNone(res.outputs["matches"][0]["z"])

    def test_z_reference_formula(self):
        left, right, part, _belt = _pair()
        payload = _stereo_payload(640, 360, z_ref={"d0_mm": 800.0, "Z0_mm": 100.0, "scale": 1.2})
        path = _save_calibration(self.tmp, payload)
        res = _run_stereo(path, left, right, [part])
        distance = res.outputs["matches"][0]["distance_mm"]
        self.assertAlmostEqual(res.outputs["matches"][0]["z"], 100.0 + (800.0 - distance) * 1.2, delta=0.01)

    def test_motion_compensation_restores_shifted_pair(self):
        """dt 有號（右 − 左）：右晚拍（dt > 0）與左晚拍（dt < 0）兩個方向都要補得回來，方向反了會把誤差放大。"""
        path = _save_calibration(self.tmp, _stereo_payload(640, 360))
        for motion_px, dt_ms in ((10, 10), (-10, -10)):
            with self.subTest(dt_ms=dt_ms):
                left, right, part, _belt = _pair(motion_px=motion_px)
                comp = _run_stereo(path, left, right, [part], dt_ms=dt_ms, motion_compensation=True)
                raw = _run_stereo(path, left, right, [part], dt_ms=dt_ms, motion_compensation=False)
                comp_err = abs(comp.outputs["matches"][0]["distance_mm"] - 600.0)
                raw_err = abs(raw.outputs["matches"][0]["distance_mm"] - 600.0)
                self.assertLess(comp_err / 600.0, 0.01)
                self.assertGreater(raw_err, comp_err + 30.0)
                self.assertTrue(comp.outputs["matches"][0]["compensated"])
                self.assertFalse(raw.outputs["matches"][0]["compensated"])
        # 方向反了（dt 的號給錯）不能矇混過去：誤差要比不補償還大
        left, right, part, _belt = _pair(motion_px=10)
        wrong = _run_stereo(path, left, right, [part], dt_ms=-10, motion_compensation=True)
        self.assertGreater(abs(wrong.outputs["matches"][0]["distance_mm"] - 600.0), 30.0)

    def test_validate_rejects_bad_stereo_payloads(self):
        payload = _stereo_payload(640, 360)
        bad_matrix = json.loads(json.dumps(payload))
        bad_matrix["stereo"]["M1"] = [[1, 2], [3, 4]]
        with self.assertRaises(calib.CalibError):
            calib.validate(bad_matrix)
        missing_t = json.loads(json.dumps(payload))
        del missing_t["stereo"]["T"]
        with self.assertRaises(calib.CalibError):
            calib.validate(missing_t)
        bad_baseline = json.loads(json.dumps(payload))
        bad_baseline["stereo"]["baseline_mm"] = 0
        with self.assertRaises(calib.CalibError):
            calib.validate(bad_baseline)

    def test_format_text_treats_none_z_as_missing(self):
        """stereo_depth 量不到時 z=None：format_text 要當成缺欄補 0.00，不能讓整行炸掉。"""
        ctx = ToolContext(
            run_id="test",
            flow_id=1,
            node={"id": "fmt", "type": "format_text", "params": {"each_template": "{z:.2f}"}},
            inputs={"items": [{"z": None}]},
            context={},
            moment=0.0,
            log=lambda *a, **k: None,
            asset_path=lambda aid: None,
            grab=lambda sid: None,
            preview=True,
        )
        result = FormatTextTool().execute(ctx)
        self.assertEqual(result.outputs["lines"], ["0.00"])


class StereoCalibrationApiTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vs-stereo-api-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_import_endpoint_reads_baseline(self):
        config = {
            "M1": _stereo_payload(640, 360)["stereo"]["M1"],
            "D1": [0, 0, 0, 0, 0],
            "M2": _stereo_payload(640, 360)["stereo"]["M2"],
            "D2": [0, 0, 0, 0, 0],
            "R": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "T": [-60, 0, 0],
            "width": 640,
            "height": 360,
            "R1": [],
            "R2": [],
            "P1": [],
            "P2": [],
            "Q": [],
        }
        res = self.client.post("/api/vision/calibration/stereo/import", data=json.dumps({"config": config}), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertAlmostEqual(res.json()["payload"]["stereo"]["baseline_mm"], 60.0, delta=1e-6)

    def test_solve_mode_stereo_recovers_baseline(self):
        w, h = 1280, 960
        f, baseline = 1200.0, 60.0
        camera = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], np.float64)
        dist = np.zeros(5)
        obj = calib.board_object_points(7, 5, 20.0, "chessboard")
        views_left: list[list[list[float]]] = []
        views_right: list[list[list[float]]] = []
        poses = [(-8, -5, 0, -60, -40, 760), (6, 4, 5, 40, -30, 820), (0, 8, -6, -35, 30, 780),
                 (10, -6, 4, 55, 35, 860), (-5, 7, 8, 10, -60, 800), (4, -9, -4, -70, 50, 900)]
        for ax, ay, az, tx, ty, tz in poses:
            rvec = np.deg2rad([ax, ay, az]).astype(np.float64)
            tvec = np.array([tx, ty, tz], np.float64)
            left, _ = cv2.projectPoints(obj, rvec, tvec, camera, dist)
            board_rot, _ = cv2.Rodrigues(rvec)
            right_rvec, _ = cv2.Rodrigues(board_rot)
            right_tvec = tvec + np.array([-baseline, 0.0, 0.0])
            right, _ = cv2.projectPoints(obj, right_rvec, right_tvec, camera, dist)
            views_left.append(left.reshape(-1, 2).tolist())
            views_right.append(right.reshape(-1, 2).tolist())
        body = {"mode": "stereo", "image_size": [w, h], "cols": 7, "rows": 5, "spacing": 20.0,
                "views_left": views_left, "views_right": views_right, "left_source": "L", "right_source": "R"}
        res = self.client.post("/api/vision/calibration/solve", data=json.dumps(body), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        stereo = res.json()["payload"]["stereo"]
        self.assertAlmostEqual(stereo["baseline_mm"], baseline, delta=baseline * 0.01)
        self.assertEqual(len(stereo["points"]), 6)
        self.assertTrue(all(p["error"] >= 0 for p in stereo["points"]))


class StereoGraphTests(SimpleTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vs-stereo-graph-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_full_graph_outputs_robot_line(self):
        left, right, _part, _belt = _pair()
        path = _save_calibration(self.tmp, _stereo_payload(640, 360, z_ref={"d0_mm": 800.0, "Z0_mm": 50.0, "scale": 1.0}))
        graph = {
            "nodes": [
                {"id": "src", "type": "stereo_grab", "params": {"left": "L", "right": "R"}},
                {"id": "thr", "type": "threshold", "params": {"method": "fixed", "threshold": 120}},
                {"id": "blob", "type": "blob", "params": {"threshold_method": "none", "min_area": 1000}},
                {"id": "z", "type": "stereo_depth", "params": {"calibration": "st", "num_disparities": 160, "block_size": 5, "scale": 1.0}},
                {"id": "fmt", "type": "format_text", "params": {"name": "robot_line", "template": "{judge}", "each_template": "part,{cx:.2f},{cy:.2f},{z:.2f}"}},
            ],
            "edges": [
                {"source": "src", "target": "thr", "source_handle": "image", "target_handle": "image"},
                {"source": "thr", "target": "blob", "source_handle": "image", "target_handle": "image"},
                {"source": "src", "target": "z", "source_handle": "image", "target_handle": "image"},
                {"source": "src", "target": "z", "source_handle": "image_right", "target_handle": "image_right"},
                {"source": "blob", "target": "z", "source_handle": "blobs", "target_handle": "matches"},
                {"source": "z", "target": "fmt", "source_handle": "matches", "target_handle": "items"},
            ],
        }
        compiled = compile_graph(validate_graph(graph))

        def grab(source_id: str):
            return left if source_id == "L" else right if source_id == "R" else None

        report = engine.execute(compiled, flow_id=0, flow_version=1, trigger="test", grab=grab, asset_path=lambda aid: path if aid == "st" else None)
        self.assertEqual(report.status, "ok", report.error)
        line = report.outputs["robot_line"]
        cls, sx, sy, sz = line.split(",")
        self.assertEqual(cls, "part")
        self.assertGreater(float(sx), 250.0)
        self.assertGreater(float(sy), 120.0)
        self.assertAlmostEqual(float(sz), 250.0, delta=3.0)
