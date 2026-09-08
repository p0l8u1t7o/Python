from __future__ import annotations

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision import variables
from apps.vision.images import store as image_store
from apps.vision.tools import base, register_builtins
from apps.vision.tools.base import ToolContext

register_builtins()


def ctx_for(
    key: str,
    image: np.ndarray | None = None,
    params: dict | None = None,
    inputs: dict | None = None,
    *,
    flow_id: int = 1,
    run_id: str = "test",
    preview: bool = True,
    context: dict | None = None,
    node_id: str | None = None,
) -> ToolContext:
    tool = base.get(key)
    ins = dict(inputs or {})
    if image is not None:
        ins.setdefault("image", image)
    return ToolContext(
        run_id=run_id,
        flow_id=flow_id,
        node={"id": node_id or key, "type": key, "params": params or {}},
        inputs=ins,
        context=context if context is not None else {},
        moment=0.0,
        log=lambda *a, **k: None,
        asset_path=lambda aid: None,
        grab=lambda sid: None,
        preview=preview,
        depth=getattr(tool, "accepts", ("u8",)),
    )


def run(key: str, image: np.ndarray | None = None, params: dict | None = None, inputs: dict | None = None, **kwargs):
    return base.get(key).execute(ctx_for(key, image, params, inputs, **kwargs))


class FrameAndPasteTests(SimpleTestCase):
    def setUp(self):
        variables.store.clear()
        for run_id in ("prev-a", "prev-b", "prev-c"):
            image_store.drop_run(run_id)

    def tearDown(self):
        variables.store.clear()
        for run_id in ("prev-a", "prev-b", "prev-c"):
            image_store.drop_run(run_id)

    def test_frame_accumulate_mean_max_min(self):
        frames = [np.full((4, 5), value, np.uint8) for value in (60, 120, 180)]
        for mode, expected in (("mean", 120), ("max", 180), ("min", 60)):
            variables.store.clear()
            result = None
            for frame in frames:
                result = run("frame_accumulate", frame, {"mode": mode, "count": 3}, flow_id=101, preview=False, node_id=f"acc_{mode}")
            self.assertIsNotNone(result)
            self.assertEqual(result.branch, "ready")
            self.assertTrue(np.array_equal(result.outputs["image"], np.full((4, 5), expected, np.uint8)))

    def test_frame_accumulate_preview_overlay_does_not_pollute_production(self):
        flow_id = 102
        params = {"mode": "mean", "count": 3}
        first = run("frame_accumulate", np.full((2, 2), 60, np.uint8), params, flow_id=flow_id, preview=False, node_id="acc")
        self.assertEqual(first.branch, "waiting")
        self.assertEqual(first.outputs["frames"], 1)

        preview_context: dict = {}
        preview_result = None
        for value in (60, 120, 180):
            preview_result = run(
                "frame_accumulate",
                np.full((2, 2), value, np.uint8),
                params,
                flow_id=flow_id,
                preview=True,
                context=preview_context,
                node_id="acc",
            )
        self.assertEqual(preview_result.branch, "ready")
        self.assertTrue(np.array_equal(preview_result.outputs["image"], np.full((2, 2), 120, np.uint8)))
        self.assertEqual(variables.store.get(flow_id, "frame_accumulate_acc_meta")["frames"], 1)

        second = run("frame_accumulate", np.full((2, 2), 120, np.uint8), params, flow_id=flow_id, preview=False, node_id="acc")
        self.assertEqual(second.branch, "waiting")
        self.assertEqual(second.outputs["frames"], 2)
        third = run("frame_accumulate", np.full((2, 2), 180, np.uint8), params, flow_id=flow_id, preview=False, node_id="acc")
        self.assertEqual(third.branch, "ready")
        self.assertTrue(np.array_equal(third.outputs["image"], np.full((2, 2), 120, np.uint8)))

    def test_frame_accumulate_sandbox_overlay_does_not_pollute_production(self):
        flow_id = 103
        params = {"mode": "max", "count": 3}
        run("frame_accumulate", np.full((2, 2), 10, np.uint8), params, flow_id=flow_id, preview=False, node_id="acc")
        sandbox_context: dict = {"_sandbox": True}
        for value in (20, 30, 40):
            result = run(
                "frame_accumulate",
                np.full((2, 2), value, np.uint8),
                params,
                flow_id=flow_id,
                preview=False,
                context=sandbox_context,
                node_id="acc",
            )
        self.assertEqual(result.branch, "ready")
        self.assertTrue(np.array_equal(result.outputs["image"], np.full((2, 2), 40, np.uint8)))
        self.assertEqual(variables.store.get(flow_id, "frame_accumulate_acc_meta")["frames"], 1)

    def test_previous_image_reads_recent_run_and_not_found_branch(self):
        flow_id = 104
        a = np.full((3, 3), 11, np.uint8)
        b = np.full((3, 3), 22, np.uint8)
        image_store.put("prev-a:node1:image", a, flow_id=flow_id, run_id="prev-a")
        image_store.put("prev-b:node1:image", b, flow_id=flow_id, run_id="prev-b")
        result = run("previous_image", params={"node": "node1", "port": "image", "k": 1}, flow_id=flow_id, run_id="prev-c", preview=False)
        self.assertEqual(result.branch, "found")
        self.assertTrue(np.array_equal(result.outputs["image"], b))
        missing = run("previous_image", params={"node": "node1", "port": "image", "k": 3}, flow_id=flow_id, run_id="prev-c", preview=False)
        self.assertEqual(missing.branch, "not_found")
        self.assertEqual(missing.status, "ng")

    def test_arithmetic_new_modes(self):
        a = np.array([[10, 100], [200, 250]], dtype=np.uint8)
        b = np.array([[30, 80], [220, 10]], dtype=np.uint8)
        cases = {
            "min": cv2.min(a, b),
            "max": cv2.max(a, b),
            "mean": cv2.addWeighted(a, 0.5, b, 0.5, 0),
            "weighted": cv2.addWeighted(a, 0.25, b, 0.75, 0),
        }
        for op, expected in cases.items():
            params = {"op": op, "weight": 0.25} if op == "weighted" else {"op": op}
            result = run("arithmetic", params=params, inputs={"a": a, "b": b})
            self.assertTrue(np.array_equal(result.outputs["image"], expected), op)

    def test_apply_mask_fill_inside_outside_and_default(self):
        image = np.full((3, 3), 10, np.uint8)
        mask = np.zeros((3, 3), np.uint8)
        mask[1, 1] = 255
        default = run("apply_mask", image, inputs={"mask": mask})
        expected_default = np.zeros((3, 3), np.uint8)
        expected_default[1, 1] = 10
        self.assertTrue(np.array_equal(default.outputs["image"], expected_default))

        outside = run("apply_mask", image, {"side": "outside", "fill_value": 7}, {"mask": mask})
        expected_outside = np.full((3, 3), 7, np.uint8)
        expected_outside[1, 1] = 10
        self.assertTrue(np.array_equal(outside.outputs["image"], expected_outside))

        inside = run("apply_mask", image, {"side": "inside", "fill_value": 99}, {"mask": mask})
        expected_inside = np.full((3, 3), 10, np.uint8)
        expected_inside[1, 1] = 99
        self.assertTrue(np.array_equal(inside.outputs["image"], expected_inside))

    def test_paste_back_matches_direct_roi_write_and_clips(self):
        base_img = np.arange(6 * 7, dtype=np.uint8).reshape(6, 7)
        patch = base_img[1:3, 2:5].copy()
        patch = (patch + 100).astype(np.uint8)
        result = run("paste_back", base_img, {"x": 2, "y": 1}, {"patch": patch})
        expected = base_img.copy()
        expected[1:3, 2:5] = patch
        self.assertTrue(np.array_equal(result.outputs["image"], expected))

        over = np.full((3, 4), 9, np.uint8)
        clipped = run("paste_back", base_img, {"x": -1, "y": 2}, {"patch": over})
        expected_clip = base_img.copy()
        expected_clip[2:5, 0:3] = over[:, 1:4]
        self.assertTrue(np.array_equal(clipped.outputs["image"], expected_clip))

    def test_undistort_manual_identity_and_negative_k1_direction(self):
        yy, xx = np.mgrid[:65, :65]
        image = np.dstack([xx, yy, np.zeros_like(xx)]).astype(np.uint8)
        identity = run("undistort", image, {"mode": "manual", "k1": 0, "k2": 0, "alpha": 0})
        self.assertTrue(np.array_equal(identity.outputs["image"], image))

        pulled = run("undistort", image, {"mode": "manual", "k1": -0.5, "k2": 0, "scale": 1, "alpha": 0})
        out = pulled.outputs["image"]
        self.assertEqual(out[0, 0, :2].tolist(), [8, 8])
        self.assertEqual(out[32, 32, :2].tolist(), [32, 32])
        self.assertEqual(out[64, 64, :2].tolist(), [56, 56])

    def helper_accumulator_state_survives_the_variables_snapshot(self):
        """frame_accumulate 存的狀態不得讓 variables.snapshot() 拋例外。

        踩過的坑：清空時存 `np.empty((0,))`（1 維），而 snapshot 把每個 ndarray 都當影像去讀
        `shape[1]` → IndexError。流程只要 reset 過一次，`GET /flows/{id}/board`、
        `/flows/{id}/variables` 與 `/dashboards/{id}/data` 就全部 500——board 是文件化的
        整合契約，現場看板會整片掛掉。這條同時鎖住工具層與 snapshot 的加固。
        """
        flow_id = 4321          # SimpleTestCase 不能碰 DB：store 的 set/snapshot 純記憶體，不必 ensure_loaded
        image = np.full((6, 8), 60, np.uint8)

        # 1) 清空之後 snapshot 要正常
        run("frame_accumulate", image, {"count": 3, "reset": True}, {}, flow_id=flow_id, preview=False, node_id="acc")
        snap = variables.store.snapshot(flow_id)
        self.assertIsInstance(snap, dict)

        # 2) 累積中（真的存了 2 維影像）也要正常，而且回報得出寬高
        run("frame_accumulate", image, {"count": 3}, {}, flow_id=flow_id, preview=False, node_id="acc")
        snap = variables.store.snapshot(flow_id)
        images = [v for v in snap.values() if isinstance(v, dict) and v.get("image")]
        self.assertTrue(images, snap)
        self.assertEqual((images[0]["width"], images[0]["height"]), (8, 6))

        # 3) 任何形狀的 ndarray 都不該讓這條顯示路徑炸掉
        variables.store.set(flow_id, "odd_scalar", np.float32(1.5))
        variables.store.set(flow_id, "odd_1d", np.zeros((3,), np.uint8))
        self.assertIsInstance(variables.store.snapshot(flow_id), dict)

    def helper_accumulator_state_survives_the_variables_snapshot_duplicate(self):
        """frame_accumulate 存的狀態不得讓 variables.snapshot() 拋例外。

        踩過的坑：清空時存 `np.empty((0,))`（1 維），而 snapshot 把每個 ndarray 都當影像去讀
        `shape[1]` → IndexError。流程只要 reset 過一次，`GET /flows/{id}/board`、
        `/flows/{id}/variables` 與 `/dashboards/{id}/data` 就全部 500——board 是文件化的
        整合契約，現場看板會整片掛掉。這條同時鎖住工具層與 snapshot 的加固。
        """
        flow_id = 4321          # SimpleTestCase 不能碰 DB：store 的 set/snapshot 純記憶體
        image = np.full((6, 8), 60, np.uint8)

        # 1) 清空之後 snapshot 要正常
        run("frame_accumulate", image, {"count": 3, "reset": True}, {}, flow_id=flow_id, preview=False, node_id="acc")
        snap = variables.store.snapshot(flow_id)
        self.assertIsInstance(snap, dict)

        # 2) 累積中（真的存了 2 維影像）也要正常，而且回報得出寬高
        run("frame_accumulate", image, {"count": 3}, {}, flow_id=flow_id, preview=False, node_id="acc")
        snap = variables.store.snapshot(flow_id)
        images = [v for v in snap.values() if isinstance(v, dict) and v.get("image")]
        self.assertTrue(images, snap)
        self.assertEqual((images[0]["width"], images[0]["height"]), (8, 6))

        # 3) 任何形狀的 ndarray 都不該讓這條顯示路徑炸掉
        variables.store.set(flow_id, "odd_scalar", np.float32(1.5))
        variables.store.set(flow_id, "odd_1d", np.zeros((3,), np.uint8))
        self.assertIsInstance(variables.store.snapshot(flow_id), dict)

    def test_accumulator_state_survives_the_variables_snapshot(self):
        """frame_accumulate 存的狀態不得讓 variables.snapshot() 拋例外。

        踩過的坑：清空時存 `np.empty((0,))`（1 維），而 snapshot 把每個 ndarray 都當影像去讀
        `shape[1]` → IndexError。流程只要 reset 過一次，`GET /flows/{id}/board`、
        `/flows/{id}/variables` 與 `/dashboards/{id}/data` 就全部 500——board 是文件化的
        整合契約，現場看板會整片掛掉。這條同時鎖住工具層與 snapshot 的加固。
        """
        flow_id = 4321          # SimpleTestCase 不能碰 DB：store 的 set/snapshot 純記憶體
        image = np.full((6, 8), 60, np.uint8)

        # 1) 清空之後 snapshot 要正常
        run("frame_accumulate", image, {"count": 3, "reset": True}, {}, flow_id=flow_id, preview=False, node_id="acc")
        snap = variables.store.snapshot(flow_id)
        self.assertIsInstance(snap, dict)

        # 2) 累積中（真的存了 2 維影像）也要正常，而且回報得出寬高
        run("frame_accumulate", image, {"count": 3}, {}, flow_id=flow_id, preview=False, node_id="acc")
        snap = variables.store.snapshot(flow_id)
        images = [v for v in snap.values() if isinstance(v, dict) and v.get("image")]
        self.assertTrue(images, snap)
        self.assertEqual((images[0]["width"], images[0]["height"]), (8, 6))

        # 3) 任何形狀的 ndarray 都不該讓這條顯示路徑炸掉
        variables.store.set(flow_id, "odd_scalar", np.float32(1.5))
        variables.store.set(flow_id, "odd_1d", np.zeros((3,), np.uint8))
        self.assertIsInstance(variables.store.snapshot(flow_id), dict)

    def test_changed_tools_do_not_mutate_input_images(self):
        image = np.arange(25, dtype=np.uint8).reshape(5, 5)
        other = np.flipud(image).copy()
        mask = np.zeros((5, 5), np.uint8)
        mask[1:4, 1:4] = 255
        patch = np.full((3, 3), 99, np.uint8)
        cases = [
            ("frame_accumulate", image, {"count": 2}, {}),
            ("arithmetic", None, {"op": "weighted", "weight": 0.25}, {"a": image, "b": other}),
            ("apply_mask", image, {"side": "inside", "fill_value": 7}, {"mask": mask}),
            ("paste_back", image, {"x": 1, "y": 1, "mode": "masked"}, {"patch": patch, "mask": mask[:3, :3]}),
            ("undistort", image, {"mode": "manual", "k1": 0}, {}),
        ]
        for key, main, params, inputs in cases:
            snapshots = [(arr, arr.copy()) for arr in ([main] if isinstance(main, np.ndarray) else [])]
            snapshots.extend((arr, arr.copy()) for arr in inputs.values() if isinstance(arr, np.ndarray))
            run(key, main, params, inputs, flow_id=200, preview=True, context={}, node_id=f"pure_{key}")
            for arr, snap in snapshots:
                self.assertTrue(np.array_equal(arr, snap), key)
