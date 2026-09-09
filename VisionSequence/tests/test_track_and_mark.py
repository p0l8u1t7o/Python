from __future__ import annotations

import math
from unittest import mock

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision import shapemodel, variables
from apps.vision.tools import base
from apps.vision.tools.base import ToolContext
from apps.vision.tools.builtin import shape as shape_tool
from tests._helpers import run_tool, temp_dir


def _mark_scene(kind: str, cx: float = 110.0, cy: float = 90.0, angle: float = 0.0) -> np.ndarray:
    tpl = shape_tool.builtin_template(kind, 48, 6)
    if angle:
        center = ((tpl.shape[1] - 1) / 2, (tpl.shape[0] - 1) / 2)
        matrix = cv2.getRotationMatrix2D(center, -angle, 1.0)
        tpl = cv2.warpAffine(tpl, matrix, (tpl.shape[1], tpl.shape[0]), flags=cv2.INTER_LINEAR, borderValue=30)
    img = np.full((180, 220), 30, np.uint8)
    x0 = int(round(cx - tpl.shape[1] / 2))
    y0 = int(round(cy - tpl.shape[0] / 2))
    img[y0 : y0 + tpl.shape[0], x0 : x0 + tpl.shape[1]] = tpl
    return img


def _angle_error(got: float, want: float) -> float:
    return abs(((got - want) + 180.0) % 360.0 - 180.0)


def _track_ctx(params: dict, matches: list[dict] | None, *, flow_id: int = 77, preview: bool = False,
               context: dict | None = None, inputs: dict | None = None) -> ToolContext:
    tool = base.get("track_objects")
    ins = dict(inputs or {})
    if matches is not None:
        ins["matches"] = matches
    return ToolContext(
        run_id="track-test", flow_id=flow_id, node={"id": "track", "type": "track_objects", "params": params},
        inputs=ins, context=context if context is not None else {}, moment=0.0, log=lambda *a, **k: None,
        asset_path=lambda aid: None, grab=lambda sid: None, preview=preview, depth=getattr(tool, "accepts", ("u8",)),
    )


def _run_track(params: dict, matches: list[dict] | None, *, flow_id: int = 77, preview: bool = False,
               context: dict | None = None, inputs: dict | None = None):
    return base.get("track_objects").execute(_track_ctx(params, matches, flow_id=flow_id, preview=preview, context=context, inputs=inputs))


def _box(cx: float, cy: float = 50.0) -> dict:
    return {"cx": cx, "cy": cy, "w": 8.0, "h": 8.0, "score": 0.9}


class BuiltinMarkShapeTests(SimpleTestCase):
    def setUp(self):
        shape_tool.clear_builtin_model_cache()

    def test_builtin_marks_match_known_position_and_rotation(self):
        self.metrics: dict[str, tuple[float, float]] = {}
        for kind in ("cross", "square_outline", "disc"):
            plain = run_tool(
                "shape_match", _mark_scene(kind),
                {"model_source": "builtin", "builtin_shape": kind, "builtin_size": 48, "builtin_line_width": 6,
                 "min_score": 0.45, "angle_start": -45, "angle_extent": 90},
            )
            self.assertEqual(plain.branch, "found", (kind, plain.message))
            pos_err = math.hypot(plain.outputs["best_x"] - 110.0, plain.outputs["best_y"] - 90.0)
            self.assertLess(pos_err, 1.5, (kind, plain.outputs))

            rotated = run_tool(
                "shape_match", _mark_scene(kind, angle=30.0),
                {"model_source": "builtin", "builtin_shape": kind, "builtin_size": 48, "builtin_line_width": 6,
                 "min_score": 0.45, "angle_start": -45, "angle_extent": 90},
            )
            self.assertEqual(rotated.branch, "found", (kind, rotated.message))
            rot_pos_err = math.hypot(rotated.outputs["best_x"] - 110.0, rotated.outputs["best_y"] - 90.0)
            rot_ang_err = _angle_error(rotated.outputs["best_angle"], 30.0)
            self.assertLess(rot_pos_err, 1.5, (kind, rotated.outputs))
            self.assertLess(rot_ang_err, 2.0, (kind, rotated.outputs))
            self.metrics[kind] = (round(max(pos_err, rot_pos_err), 3), round(rot_ang_err, 3))

    def test_asset_model_source_keeps_existing_path(self):
        folder = temp_dir()
        tpl = shape_tool.builtin_template("cross", 48, 6)
        path = f"{folder}/shape.npz"
        shapemodel.save(path, shapemodel.teach(tpl, min_contrast=4.0))
        result = run_tool("shape_match", _mark_scene("cross"), {"model": "m", "min_score": 0.45}, assets={"m": path})
        self.assertEqual(result.branch, "found", result.message)
        self.assertLess(math.hypot(result.outputs["best_x"] - 110.0, result.outputs["best_y"] - 90.0), 1.5)

    def test_builtin_model_cache_reuses_same_parameters(self):
        original = shape_tool.shapemodel.teach
        calls = 0

        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        with mock.patch.object(shape_tool.shapemodel, "teach", side_effect=counted):
            first = shape_tool.builtin_model("cross", 48, 6)
            second = shape_tool.builtin_model("cross", 48, 6)
        self.assertIs(first, second)
        self.assertEqual(calls, 1)


class TrackObjectsTests(SimpleTestCase):
    def setUp(self):
        variables.store.clear()
        self.addCleanup(variables.store.clear)

    def test_constant_velocity_keeps_id_through_occlusion(self):
        params = {"state_name": "trk", "max_distance": 15, "max_missing": 1}
        ids = []
        missings = []
        for x in (10, 20, 30):
            r = _run_track(params, [_box(x)])
            ids.append(r.outputs["tracks"][0]["id"])
            missings.append(r.outputs["tracks"][0]["missing"])
        hidden = _run_track(params, [])
        ids.append(hidden.outputs["tracks"][0]["id"])
        missings.append(hidden.outputs["tracks"][0]["missing"])
        shown = _run_track(params, [_box(50)])
        ids.append(shown.outputs["tracks"][0]["id"])
        missings.append(shown.outputs["tracks"][0]["missing"])
        self.assertEqual(ids, [1, 1, 1, 1, 1])
        self.assertEqual(missings, [0, 0, 0, 1, 0])
        self.assertAlmostEqual(shown.outputs["tracks"][0]["vx"], 10.0, delta=0.001)

        lost = _run_track(params, [])
        self.assertEqual(lost.outputs["tracks"][0]["id"], 1)
        gone = _run_track(params, [])
        self.assertEqual((gone.branch, gone.outputs["lost_count"]), ("not_found", 1))
        new = _run_track(params, [_box(80)])
        self.assertEqual(new.outputs["tracks"][0]["id"], 2)

    def test_crossing_targets_use_predicted_positions(self):
        params = {"state_name": "crossing", "max_distance": 25, "max_missing": 0}
        r1 = _run_track(params, [_box(30), _box(90)])
        self.assertEqual([t["id"] for t in r1.outputs["tracks"]], [1, 2])
        _run_track(params, [_box(50), _box(70)])
        r3 = _run_track(params, [_box(50), _box(70)])
        by_id = {t["id"]: t for t in r3.outputs["tracks"]}
        self.assertEqual(round(by_id[1]["cx"]), 70)
        self.assertEqual(round(by_id[2]["cx"]), 50)

    def test_count_line_uses_signed_crossing_direction(self):
        params = {
            "state_name": "counting", "max_distance": 40, "max_missing": 0,
            "line_mode": "points", "count_line": [[50, 100], [50, 0]],
        }
        _run_track(params, [_box(40)])
        right = _run_track(params, [_box(60)])
        self.assertEqual((right.outputs["count_in"], right.outputs["count_out"]), (1, 0))
        _run_track(params | {"reset": True}, [_box(60)])
        left = _run_track(params | {"reset": False}, [_box(40)])
        self.assertEqual((left.outputs["count_in"], left.outputs["count_out"]), (0, 1))

    def test_preview_overlay_does_not_pollute_production_state(self):
        params = {"state_name": "preview_state", "max_distance": 20, "max_missing": 2}
        prod = _run_track(params, [_box(10)], flow_id=91, preview=False)
        self.assertEqual(prod.outputs["tracks"][0]["id"], 1)
        before = variables.store.get(91, "preview_state")
        ctx: dict = {}
        preview_ids = []
        for x in (20, 30, 40):
            r = _run_track(params, [_box(x)], flow_id=91, preview=True, context=ctx)
            preview_ids.append(r.outputs["tracks"][0]["id"])
        self.assertEqual(preview_ids, [1, 1, 1])
        self.assertEqual(variables.store.get(91, "preview_state"), before)
        overlay_key = "91:preview_state"
        self.assertIn(overlay_key, ctx["_variables_overlay"])
        self.assertEqual(ctx["_variables_overlay"][overlay_key]["tracks"][0]["cx"], 40.0)

        overlay_ctx = {"_variables_overlay": {overlay_key: {"next_id": 4, "count_in": 0, "count_out": 0, "tracks": []}}}
        r = _run_track(params, [_box(100)], flow_id=91, preview=True, context=overlay_ctx)
        self.assertEqual(r.outputs["tracks"][0]["id"], 4)
        self.assertEqual(variables.store.get(91, "preview_state"), before)

    def test_snapshot_accepts_tracker_state(self):
        params = {"state_name": "snapshot_state", "max_distance": 20, "max_missing": 2}
        _run_track(params, [_box(10)], flow_id=92, preview=False)
        snap = variables.store.snapshot(92)
        self.assertIn("snapshot_state", snap)
        self.assertIsInstance(snap["snapshot_state"]["tracks"], list)

    def test_reset_clears_tracks_but_does_not_reuse_ids(self):
        params = {"state_name": "reset_state", "max_distance": 20, "max_missing": 2}
        first = _run_track(params, [_box(10)], flow_id=93, preview=False)
        reset = _run_track({**params, "reset": True}, [_box(40)], flow_id=93, preview=False)
        self.assertEqual(first.outputs["tracks"][0]["id"], 1)
        self.assertEqual(reset.outputs["tracks"][0]["id"], 2)
