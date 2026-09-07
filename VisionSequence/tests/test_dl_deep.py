"""深度學習深度測試（不需 torch／網路）：dl_* ONNX 工具的邊界、內建 trainer 的增強／分割／取消／建議、訓練工作生命週期、
ai_* 工具的座標回映與判定（假 Results）、yolo_runtime 快取與裝置、resolve_model 下載退回、SAM 幾何與全圖提案、YOLO trainer 的提案轉換。"""

from __future__ import annotations

import io
import json
import os
import shutil
import threading
import time
import urllib.error
from pathlib import Path
from typing import Any
from unittest import mock

import cv2
import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.vision.dl import base as dl_base
from apps.vision.dl import builtin, jobs, sam, yolo, yolo_runtime
from apps.vision.dl.base import SampleRef, TrainCancelled, TrainError, TrainResult
from apps.vision.tools import base as tools_base
from apps.vision.tools.builtin import dl as dl_mod
from apps.vision.tools.roi import crop
from tests._helpers import gap_classifier_onnx, identity_onnx, run_tool, save_png, temp_dir, yolo_seg_onnx


# ---------------------------------------------------------------------------
# 假的 ultralytics 物件（numpy 版 tensor）
# ---------------------------------------------------------------------------
class T:
    def __init__(self, a):
        self.a = np.asarray(a)

    def cpu(self):
        return self

    def numpy(self):
        return self.a

    def __len__(self):
        return len(self.a)

    def __getitem__(self, i):
        return T(self.a[i])

    def item(self):
        return self.a.item()

    def tolist(self):
        return self.a.tolist()


class Boxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy, self.conf, self.cls = T(xyxy), T(conf), T(cls)

    def __len__(self):
        return len(self.xyxy)


class Masks:
    def __init__(self, data, xy=None):
        self.data = T(data)
        self.xy = xy or []


class Kpts:
    def __init__(self, xy, conf=None):
        self.xy = T(xy)
        self.conf = None if conf is None else T(conf)


class Obb:
    def __init__(self, corners, xywhr, conf, cls):
        self.xyxyxyxy, self.xywhr, self.conf, self.cls = T(corners), T(xywhr), T(conf), T(cls)

    def __len__(self):
        return len(self.xyxyxyxy)


class Probs:
    def __init__(self, top5, top5conf):
        self.top5, self.top5conf = top5, top5conf
        self.top1, self.top1conf = top5[0], top5conf[0]


class Res:
    def __init__(self, boxes=None, masks=None, keypoints=None, obb=None, probs=None):
        self.boxes, self.masks, self.keypoints, self.obb, self.probs = boxes, masks, keypoints, obb, probs


class FakeModel:
    def __init__(self, task: str, names: dict[int, str], result: Any = None):
        self.task, self.names, self._result = task, names, result
        self.calls: list[dict[str, Any]] = []

    def predict(self, image, **kw):
        self.calls.append(kw)
        return [self._result] if self._result is not None else []


def _fake_runtime(task: str, names: dict[int, str], result: Any):
    model = FakeModel(task, names, result)
    return mock.patch.multiple(yolo_runtime, load=mock.DEFAULT, predict=mock.DEFAULT, names_of=mock.DEFAULT, task_of=mock.DEFAULT,
                               **{}), model


class _Runtime:
    """with _Runtime(task, names, result) as model: 讓 ai_* 工具不用 torch。"""

    def __init__(self, task, names, result, device="cpu"):
        self.model = FakeModel(task, names, result)
        self.device = device
        self._patches = []

    def __enter__(self):
        m = self.model
        for name, value in (("load", lambda *a, **k: m), ("predict", lambda model, image, **kw: (m.calls.append(kw), m._result)[1]),
                            ("names_of", lambda model: model.names), ("task_of", lambda model: model.task), ("pick_device", lambda pref: (self.device, ""))):
            p = mock.patch.object(yolo_runtime, name, value)
            p.start()
            self._patches.append(p)
        return m

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


# ---------------------------------------------------------------------------
# dl_* ONNX 工具邊界
# ---------------------------------------------------------------------------
class OnnxToolEdgeTests(SimpleTestCase):
    def setUp(self):
        if dl_mod.ort is None:
            self.skipTest("未安裝 onnxruntime")
        self.folder = temp_dir()
        self.gap = gap_classifier_onnx(self.folder)
        self.idn = identity_onnx(self.folder)
        self.seg = yolo_seg_onnx(self.folder)

    def tearDown(self):
        dl_mod.clear_sessions()
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_classify_gray_input_index_labels_and_session_cache(self):
        img = np.zeros((40, 40, 3), np.uint8)
        img[..., 2] = 200  # BGR：紅色通道最亮
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        base = {"model": "m", "mean": "0", "std": "1", "color_order": "bgr", "threshold": 0.1, "apply_softmax": False}
        r = run_tool("dl_classify", gray, base, assets={"m": self.gap})  # 2D 灰階輸入也能跑
        self.assertIn(r.outputs["label"], ("0", "1", "2"))  # 沒給 labels → 用索引
        r2 = run_tool("dl_classify", img, {**base, "labels": "b\ng\nr"}, assets={"m": self.gap})
        self.assertEqual(r2.outputs["label"], "r")
        self.assertEqual(len(r2.outputs["top"]), 3)
        r3 = run_tool("dl_classify", img, {**base, "labels": "b\ng\nr", "top_k": 1}, assets={"m": self.gap})
        self.assertEqual(len(r3.outputs["top"]), 1)
        s1 = dl_mod.get_session(self.gap)
        self.assertIs(dl_mod.get_session(self.gap), s1)
        dl_mod.clear_sessions()
        self.assertIsNot(dl_mod.get_session(self.gap), s1)
        with self.assertRaises(tools_base.ToolError):
            run_tool("dl_classify", img, {**base, "roi": {"shape": "rect", "x": 500, "y": 500, "w": 10, "h": 10}}, assets={"m": self.gap})
        with self.assertRaises(tools_base.ToolError):
            dl_mod.get_session(os.path.join(self.folder, "nope.onnx"))

    def test_segment_area_judge_and_rotated_roi(self):
        img = np.zeros((48, 64, 3), np.uint8)
        img[..., 1] = 255  # G 通道最大 → argmax=1
        base = {"model": "m", "mean": "0", "std": "1", "color_order": "bgr", "labels": "b\ng\nr", "target_class": 1}
        r = run_tool("dl_segment", img, base, assets={"m": self.idn})
        self.assertGreater(r.outputs["area"], 0)
        self.assertEqual(r.outputs["mask"].shape, (48, 64))
        r2 = run_tool("dl_segment", img, {**base, "max_area": 10}, assets={"m": self.idn})
        self.assertEqual((r2.status, r2.branch), ("ng", "ng"))
        r3 = run_tool("dl_segment", img, {**base, "roi": {"shape": "rotated_rect", "cx": 32, "cy": 24, "w": 30, "h": 20, "angle": 25}}, assets={"m": self.idn})
        self.assertGreater(r3.outputs["area"], 0)
        self.assertLess(r3.outputs["area"], r.outputs["area"])

    def test_instance_filters_and_limits(self):
        img = np.full((64, 64, 3), 90, np.uint8)
        base = {"model": "m", "labels": "obj", "conf": 0.5}
        r = run_tool("dl_instance", img, base, assets={"m": self.seg})
        self.assertEqual(r.outputs["count"], 1)
        self.assertEqual(r.outputs["mask"].shape, (64, 64))
        r2 = run_tool("dl_instance", img, {**base, "filter_labels": "nope"}, assets={"m": self.seg})
        self.assertEqual((r2.outputs["count"], r2.branch), (0, "not_found"))
        r3 = run_tool("dl_instance", img, {**base, "max_count_ok": 0, "min_count": 2}, assets={"m": self.seg})
        self.assertEqual(r3.status, "ng")
        r4 = run_tool("dl_instance", img, {**base, "roi": {"shape": "rect", "x": 8, "y": 8, "w": 48, "h": 48}}, assets={"m": self.seg})
        self.assertEqual(r4.outputs["count"], 1)
        self.assertTrue(all(o["kind"] in ("contours", "polygon", "rect") for o in r4.overlays))


# ---------------------------------------------------------------------------
# 內建 trainer（numpy）：增強、分割、取消、建議
# ---------------------------------------------------------------------------
def _disc(seed: int, bright: bool) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.full((48, 48, 3), 30 if bright else 200, np.uint8)
    cv2.circle(img, (24 + int(rng.integers(-3, 3)), 24), 14, (220, 220, 220) if bright else (40, 40, 40), -1)
    return img


def _refs(folder: str, n: int = 6, split: str = "") -> list[SampleRef]:
    out = []
    for i in range(n):
        for lab in ("bright", "dark"):
            path = save_png(_disc(i * 7 + (1 if lab == "bright" else 0), lab == "bright"), folder, f"{lab}{i}.png")
            out.append(SampleRef(id=f"{lab}{i}", label=lab, path=path, split=split))
    return out


class BuiltinTrainerDeepTests(SimpleTestCase):
    def setUp(self):
        self.folder = temp_dir()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_mlp_augment_split_cancel_suggest(self):
        trainer = builtin.MlpClassifierTrainer()
        refs = _refs(self.folder)
        for r in refs[:4]:
            r.split = "val"
        result = trainer.train(refs, ["bright", "dark"], {"input_size": 32, "epochs": 120, "augment": True, "augment_brightness": 0.2}, "cpu", lambda f, s, m: None)
        self.assertGreater(result.metrics.get("augmented", 0), 0)
        self.assertEqual(result.metrics["val_samples"], 4)  # 人工指定 val 以指定為準
        self.assertGreaterEqual(result.metrics["val_accuracy"], 0.99)
        self.assertEqual(result.tool_key, "dl_classify")
        self.assertEqual(result.weights_bytes, b"")

        def cancelling(f, s, m):
            raise TrainCancelled()

        with self.assertRaises(TrainCancelled):
            trainer.train(refs, ["bright", "dark"], {"input_size": 32, "epochs": 50}, "cpu", cancelling)
        with self.assertRaises(TrainError):
            trainer.train(refs[:1], ["bright", "dark"], {"input_size": 32}, "cpu", lambda f, s, m: None)
        unl = [SampleRef(id="u1", label="", path=save_png(_disc(99, True), self.folder, "u1.png")), SampleRef(id="u2", label="", path=save_png(_disc(98, False), self.folder, "u2.png"))]
        sugg = {s.sample_id: s for s in trainer.suggest(refs, unl, ["bright", "dark"], {"input_size": 32})}
        self.assertEqual((sugg["u1"].label, sugg["u2"].label), ("bright", "dark"))
        self.assertTrue(all(0 < s.score <= 1 for s in sugg.values()))
        with self.assertRaises(TrainError):
            trainer.suggest([], unl, ["bright", "dark"], {})

    def test_patch_segment_trains_and_segments_scratches(self):
        from apps.vision import demo_images

        trainer = builtin.PatchSegmentTrainer()
        refs = []
        for i, (image, shapes) in enumerate(demo_images.dl_scratch_labeled(6)):
            refs.append(SampleRef(id=f"s{i}", label="", path=save_png(image, self.folder, f"s{i}.png"), shapes=shapes))
        result = trainer.train(refs, ["scratch"], {"input_size": 128, "epochs": 150, "samples_per_image": 1500, "augment": True}, "cpu", lambda f, s, m: None)
        self.assertEqual(result.tool_key, "dl_segment")
        model = os.path.join(self.folder, "seg.onnx")
        open(model, "wb").write(result.onnx_bytes)
        params = {**result.tool_params, "model": "m", "target_class": 1}
        scratched, _ = demo_images._scratch_plate(777, 2)
        clean, _ = demo_images._scratch_plate(778, 0)
        r_bad = run_tool("dl_segment", scratched, params, assets={"m": model})
        r_ok = run_tool("dl_segment", clean, params, assets={"m": model})
        self.assertGreater(r_bad.outputs["area"], r_ok.outputs["area"] * 3 + 50)
        # 自動標記：用已標記的快速訓練後對未標記提案 polygon
        unl = [SampleRef(id="u", label="", path=save_png(scratched, self.folder, "u.png"))]
        sugg = trainer.suggest(refs, unl, ["scratch"], {"input_size": 128, "epochs": 100})
        self.assertEqual(len(sugg), 1)
        self.assertTrue(all(sh["kind"] == "polygon" and sh["label"] == "scratch" for sh in sugg[0].shapes))
        with self.assertRaises(TrainError):
            trainer.suggest([], unl, ["scratch"], {})


# ---------------------------------------------------------------------------
# 訓練工作生命週期
# ---------------------------------------------------------------------------
TMP = temp_dir()


class _SlowTrainer(dl_base.Trainer):
    kind = "slow_fake"
    label = "slow"
    label_mode = "classes"
    tool_key = "dl_classify"

    def train(self, samples, classes, params, device, progress):
        for i in range(int(params.get("steps") or 40)):
            progress(i / 40, f"step {i}", {"epoch": i + 1, "loss": round(1.0 / (i + 1), 3)})  # jobs.TrainProgress 在取消時擲 TrainCancelled；帶 epoch＋數值才進 history
            time.sleep(0.05)
        if params.get("fail"):
            raise TrainError("刻意失敗")
        return TrainResult(onnx_bytes=b"ONNX", metrics={"ok": 1}, tool_key="dl_classify", tool_params={})


def _wait_job(timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = jobs.status()
        if st and st["status"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError("job timeout")


@override_settings(VISION={**settings.VISION, "ASSET_DIR": Path(TMP), "PERSIST_RUNS": False})
class TrainJobLifecycleTests(TransactionTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        dl_base.register_builtins()
        dl_base._TRAINERS[_SlowTrainer.kind] = _SlowTrainer()

    def tearDown(self):
        dl_base._TRAINERS.pop(_SlowTrainer.kind, None)

    def test_busy_cancel_fail_and_status_log(self):
        from apps.vision.models import Asset, DlProject

        project = DlProject.objects.create(name="slow", trainer_kind="slow_fake", classes=["a"])
        st = jobs.start(project, {"steps": 40}, "cpu", "慢模型")
        self.assertEqual(st["status"], "running")
        from apps.core.errors import Conflict

        with self.assertRaises(Conflict):
            jobs.start(project, {}, "cpu", "x")
        r = self.client.post(f"/api/vision/dl/projects/{project.id}/train", data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 409)
        time.sleep(0.3)
        self.assertTrue(jobs.cancel())
        st = _wait_job()
        self.assertEqual(st["status"], "cancelled")
        self.assertFalse(jobs.cancel())  # 已結束
        self.assertEqual(Asset.objects.filter(kind="model").count(), 0)
        # 失敗：錯誤訊息保留、資產不建
        jobs.start(project, {"steps": 2, "fail": True}, "cpu", "壞模型")
        st = _wait_job()
        self.assertEqual((st["status"], st["error"]), ("failed", "刻意失敗"))
        # 成功 + 增量 log／history：訓練完只是「等著存」，資產庫還沒有東西
        jobs.start(project, {"steps": 3}, "cpu", "好模型")
        st = _wait_job()
        self.assertEqual((st["status"], st["asset_name"], st["tool_key"]), ("done", "好模型", "dl_classify"))
        self.assertGreaterEqual(len(st["history"]), 3)
        self.assertTrue(st["pending"])
        self.assertFalse(st["saved"])
        self.assertEqual(Asset.objects.filter(kind="model").count(), 0)
        # 命名後儲存才建資產並回寫專案
        st = self.client.post("/api/vision/dl/train/save", data=json.dumps({"name": "改過的名字"}), content_type="application/json").json()
        self.assertEqual((st["saved"], st["pending"], st["asset_name"]), (True, False, "改過的名字"))
        self.assertEqual(Asset.objects.filter(kind="model", name="改過的名字").count(), 1)
        project.refresh_from_db()
        self.assertEqual(project.last_asset_id, st["asset_id"])
        self.assertEqual(self.client.post("/api/vision/dl/train/save", data="{}", content_type="application/json").status_code, 409)  # 沒有待存的
        # 放棄：檔案刪掉、資產庫不多東西
        jobs.start(project, {"steps": 2}, "cpu", "不要的")
        st = _wait_job()
        folder = jobs.status()["id"]
        self.assertTrue(os.path.isdir(os.path.join(jobs.pending_root(), folder)))
        self.assertTrue(self.client.post("/api/vision/dl/train/discard", data="{}", content_type="application/json").json()["discarded"])
        self.assertFalse(os.path.isdir(os.path.join(jobs.pending_root(), folder)))
        self.assertEqual(Asset.objects.filter(kind="model").count(), 1)
        r = self.client.get(f"/api/vision/dl/train/status?log_from={st['log_next']}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["job"]["logs"], [])  # 端點包在 {"job": …}
        # 裝置不在 trainer.devices 內會退回第一個
        self.assertEqual(jobs.start(project, {"steps": 1}, "cuda", "d")["device"], "cpu")
        _wait_job()


# ---------------------------------------------------------------------------
# ai_* 工具：座標回映與判定（假 Results，不需 torch）
# ---------------------------------------------------------------------------
IMG = np.zeros((150, 200, 3), np.uint8)
NAMES = {0: "person", 1: "bus"}


class YoloToolMappingTests(SimpleTestCase):
    def test_detect_rect_roi_filter_and_verdict(self):
        res = Res(boxes=Boxes([[10, 10, 50, 60], [70, 20, 90, 40]], [0.9, 0.6], [1, 0]))
        with _Runtime("detect", NAMES, res) as model:
            r = run_tool("ai_detect", IMG, {"model_name": "x.pt", "roi": {"shape": "rect", "x": 50, "y": 20, "w": 100, "h": 100}, "conf": 0.3, "iou": 0.5, "max_count": 7, "imgsz": 320})
        self.assertEqual(r.outputs["count"], 2)
        d = r.outputs["matches"][0]
        self.assertEqual((d["x"], d["y"], d["w"], d["h"], d["cx"], d["cy"], d["label"], d["score"]), (60.0, 30.0, 40.0, 50.0, 80.0, 55.0, "bus", 0.9))
        self.assertEqual(model.calls[0]["conf"], 0.3)
        self.assertEqual((model.calls[0]["iou"], model.calls[0]["max_det"], model.calls[0]["imgsz"], model.calls[0]["device"]), (0.5, 7, 320, "cpu"))
        self.assertNotIn("half", model.calls[0])
        self.assertEqual(r.overlays[0]["kind"], "rect")  # roi overlay
        self.assertEqual(len(r.overlays), 3)
        with _Runtime("detect", NAMES, res):
            r2 = run_tool("ai_detect", IMG, {"model_name": "x.pt", "filter_labels": "person", "min_count": 2})
        self.assertEqual((r2.outputs["count"], r2.outputs["labels"], r2.status, r2.branch), (1, ["person"], "ng", "found"))
        with _Runtime("detect", NAMES, res):
            r3 = run_tool("ai_detect", IMG, {"model_name": "x.pt", "max_count_ok": 1})
        self.assertEqual(r3.status, "ng")
        with _Runtime("detect", NAMES, None):
            r4 = run_tool("ai_detect", IMG, {"model_name": "x.pt", "min_count": 0})
        self.assertEqual((r4.outputs["count"], r4.branch, r4.status), (0, "not_found", "ok"))
        with _Runtime("pose", NAMES, res):
            with self.assertRaises(tools_base.ToolError):
                run_tool("ai_segment", IMG, {"model_name": "x.pt"})

    def test_detect_rotated_roi_maps_through_to_full(self):
        region = {"shape": "rotated_rect", "cx": 100, "cy": 75, "w": 120, "h": 80, "angle": 30}
        c = crop(IMG, region, upright=True)
        res = Res(boxes=Boxes([[10, 10, 30, 30]], [0.8], [0]))
        with _Runtime("detect", NAMES, res):
            r = run_tool("ai_detect", IMG, {"model_name": "x.pt", "roi": region})
        d = r.outputs["matches"][0]
        ex, ey = c.to_full(10, 10)
        self.assertAlmostEqual(d["x"], round(ex, 1), places=1)
        self.assertAlmostEqual(d["y"], round(ey, 1), places=1)
        self.assertEqual(r.overlays[-1]["angle"], 30.0)

    def test_half_only_when_cuda_and_requested(self):
        res = Res(boxes=Boxes([[0, 0, 5, 5]], [0.9], [0]))
        with _Runtime("detect", NAMES, res, device="cuda") as model:
            run_tool("ai_detect", IMG, {"model_name": "x.pt", "half": True})
            run_tool("ai_detect", IMG, {"model_name": "x.pt", "half": False})
        self.assertEqual([c.get("half") for c in model.calls], [True, None])

    def test_segment_masks_resize_offsets_min_area(self):
        region = {"shape": "rect", "x": 20, "y": 10, "w": 100, "h": 100}
        data = np.zeros((2, 32, 32), np.float32)
        data[0, 4:20, 4:20] = 1  # 16×16 於 32 格 → 子圖 100×100 上約 50×50
        data[1, 0:2, 0:2] = 1  # 很小 → 被 min_area 濾掉
        res = Res(boxes=Boxes([[12, 12, 62, 62], [0, 0, 6, 6]], [0.9, 0.5], [1, 0]), masks=Masks(data))
        with _Runtime("segment", NAMES, res):
            r = run_tool("ai_segment", IMG, {"model_name": "x.pt", "roi": region, "min_area": 100})
        self.assertEqual(r.outputs["count"], 1)
        m = r.outputs["matches"][0]
        self.assertEqual((m["label"], m["x"], m["y"], m["w"], m["h"]), ("bus", 32.0, 22.0, 50.0, 50.0))
        self.assertGreater(m["area"], 2000)
        mask = r.outputs["mask"]
        self.assertEqual(mask.shape, (150, 200))
        ys, xs = np.nonzero(mask)
        self.assertTrue(xs.min() >= 20 + 12 and ys.min() >= 10 + 12)  # 偏移到全圖
        self.assertEqual(len(r.outputs["contours"]), 1)
        self.assertEqual([o["kind"] for o in r.overlays], ["contours", "rect"])

    def test_pose_keypoints_and_skeleton(self):
        xy = np.zeros((1, 17, 2), np.float32)
        conf = np.full((1, 17), 0.9, np.float32)
        for i in range(17):
            xy[0, i] = [10 + i * 5, 20 + (i % 3) * 5]
        conf[0, 3] = 0.1  # 低信心點不畫
        res = Res(boxes=Boxes([[5, 5, 100, 100]], [0.9], [0]), keypoints=Kpts(xy, conf))
        with _Runtime("pose", {0: "person"}, res):
            r = run_tool("ai_pose", IMG, {"model_name": "x.pt", "roi": {"shape": "rect", "x": 30, "y": 10, "w": 150, "h": 130}, "kpt_conf": 0.3})
        k = r.outputs["keypoints"][0]
        self.assertEqual(len(k["points"]), 17)
        self.assertEqual(k["points"][0][:2], [40.0, 30.0])
        self.assertEqual(k["points"][3][2], 0.1)
        kinds = [o["kind"] for o in r.overlays]
        self.assertIn("points", kinds)
        self.assertIn("line", kinds)
        pts_overlay = next(o for o in r.overlays if o["kind"] == "points")
        self.assertEqual(len(pts_overlay["points"]), 16)  # 一點低於門檻
        self.assertNotIn("_i", r.outputs["matches"][0])

    def test_obb_corners_and_angle(self):
        corners = np.array([[[10, 10], [30, 10], [30, 20], [10, 20]]], np.float32)
        xywhr = np.array([[20, 15, 20, 10, np.deg2rad(15)]], np.float32)
        res = Res(obb=Obb(corners, xywhr, [0.7], [1]))
        with _Runtime("obb", NAMES, res):
            r = run_tool("ai_obb", IMG, {"model_name": "x.pt", "roi": {"shape": "rect", "x": 100, "y": 50, "w": 80, "h": 60}})
        m = r.outputs["matches"][0]
        self.assertEqual((m["cx"], m["cy"], m["w"], m["h"], m["angle"], m["label"]), (120.0, 65.0, 20.0, 10.0, 15.0, "bus"))
        self.assertEqual(m["points"][0], [110.0, 60.0])
        self.assertEqual(r.outputs["contours"][0].shape, (4, 1, 2))
        self.assertEqual([o["kind"] for o in r.overlays], ["rect", "polygon"])
        with _Runtime("obb", NAMES, res):
            r2 = run_tool("ai_obb", IMG, {"model_name": "x.pt", "filter_labels": "person"})
        self.assertEqual(r2.outputs["count"], 0)

    def test_classify_topk_threshold_pass_labels(self):
        res = Res(probs=Probs([1, 0, 2], [0.6, 0.3, 0.1]))
        names = {0: "cat", 1: "dog", 2: "bird"}
        with _Runtime("classify", names, res):
            r = run_tool("ai_classify", IMG, {"model_name": "x.pt", "top_k": 2, "threshold": 0.5})
            r2 = run_tool("ai_classify", IMG, {"model_name": "x.pt", "threshold": 0.7})
            r3 = run_tool("ai_classify", IMG, {"model_name": "x.pt", "threshold": 0.5, "pass_labels": "cat,bird"})
        self.assertEqual((r.outputs["label"], r.outputs["index"], r.outputs["score"], len(r.outputs["top"]), r.branch), ("dog", 1, 0.6, 2, "pass"))
        self.assertEqual(r.overlays[0]["kind"], "text")
        self.assertEqual(r2.branch, "fail")
        self.assertEqual(r3.status, "ng")
        with _Runtime("classify", names, Res()):
            with self.assertRaises(tools_base.ToolError):
                run_tool("ai_classify", IMG, {"model_name": "x.pt"})


# ---------------------------------------------------------------------------
# yolo_runtime：快取、裝置、載入錯誤；resolve_model 下載退回
# ---------------------------------------------------------------------------
class FakeYOLO:
    instances = 0

    def __init__(self, path, **kw):
        FakeYOLO.instances += 1
        self.path, self.kw = path, kw
        self.task = kw.get("task") or "detect"
        self.names = {0: "a"}

    def predict(self, image, **kw):
        return ["res"]


class YoloRuntimeTests(SimpleTestCase):
    def setUp(self):
        yolo_runtime.clear()
        self.folder = temp_dir()

    def tearDown(self):
        yolo_runtime.clear()
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_pick_device(self):
        with mock.patch.object(yolo_runtime, "cuda_available", return_value=True):
            self.assertEqual(yolo_runtime.pick_device("auto"), ("cuda", ""))
            self.assertEqual(yolo_runtime.pick_device("cpu"), ("cpu", ""))
        with mock.patch.object(yolo_runtime, "cuda_available", return_value=False):
            self.assertEqual(yolo_runtime.pick_device("auto"), ("cpu", ""))
            dev, note = yolo_runtime.pick_device("cuda")
            self.assertEqual(dev, "cpu")
            self.assertIn("CUDA", note)

    def test_cache_eviction_task_and_errors(self):
        paths = [os.path.join(self.folder, f"m{i}.pt") for i in range(3)]
        for p in paths:
            open(p, "wb").write(b"x")
        onnx = os.path.join(self.folder, "m.onnx")
        open(onnx, "wb").write(b"x")
        with mock.patch.object(yolo_runtime, "_import_yolo", return_value=FakeYOLO), mock.patch.object(yolo_runtime, "MAX_MODELS", 2):
            FakeYOLO.instances = 0
            a = yolo_runtime.load(paths[0])
            self.assertIs(yolo_runtime.load(paths[0]), a)
            yolo_runtime.load(paths[1])
            yolo_runtime.load(paths[2])
            self.assertEqual(FakeYOLO.instances, 3)
            self.assertEqual([os.path.basename(m["path"]) for m in yolo_runtime.loaded()], ["m1.pt", "m2.pt"])
            self.assertEqual(yolo_runtime.load(onnx, task="segment").kw, {"task": "segment"})
            self.assertEqual(yolo_runtime.load(paths[1], task="segment").kw, {})  # .pt 不傳 task
            self.assertEqual(yolo_runtime.predict(yolo_runtime.load(paths[1]), IMG), "res")
            with self.assertRaises(yolo_runtime.ModelUnavailable):
                yolo_runtime.load("")
            with self.assertRaises(yolo_runtime.ModelUnavailable):
                yolo_runtime.load(os.path.join(self.folder, "missing.pt"))
        with mock.patch.object(yolo_runtime, "_import_yolo", side_effect=yolo_runtime.ModelUnavailable("未安裝")):
            with self.assertRaises(yolo_runtime.ModelUnavailable):
                yolo_runtime.load(paths[0])
        with mock.patch.object(yolo_runtime, "_import_yolo", return_value=FakeYOLO):
            m = yolo_runtime.load(paths[0])
            with mock.patch.object(m, "predict", side_effect=RuntimeError("boom")):
                with self.assertRaises(yolo_runtime.ModelUnavailable):
                    yolo_runtime.predict(m, IMG)

    def test_predict_serializes_per_model(self):
        p = os.path.join(self.folder, "m.pt")
        open(p, "wb").write(b"x")
        active = {"n": 0, "max": 0}
        lock = threading.Lock()

        class Slow(FakeYOLO):
            def predict(self, image, **kw):
                with lock:
                    active["n"] += 1
                    active["max"] = max(active["max"], active["n"])
                time.sleep(0.02)
                with lock:
                    active["n"] -= 1
                return ["ok"]

        with mock.patch.object(yolo_runtime, "_import_yolo", return_value=Slow):
            m = yolo_runtime.load(p)
            threads = [threading.Thread(target=lambda: yolo_runtime.predict(m, IMG)) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(active["max"], 1)

    def test_resolve_model_names_and_release_fallback(self):
        with override_settings(VISION={**settings.VISION, "ASSET_DIR": Path(self.folder)}):
            self.assertEqual(yolo.resolve_model("custom_thing.pt"), "custom_thing.pt")  # 非官方名稱：原樣交給 ultralytics
            local = os.path.join(self.folder, "mine.pt")
            open(local, "wb").write(b"x")
            self.assertEqual(yolo.resolve_model(local), local)
            calls = []

            def fake_urlopen(url, timeout=0):
                calls.append(url)
                if "v8.4.0" in url:
                    raise urllib.error.HTTPError(url, 404, "nf", {}, None)
                return io.BytesIO(b"weights")

            with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                path = yolo.resolve_model("yolo11n-obb.pt")
            self.assertTrue(path.endswith("yolo11n-obb.pt"))
            self.assertEqual(open(path, "rb").read(), b"weights")
            self.assertEqual(len(calls), 2)
            self.assertEqual(yolo.resolve_model("yolo11n-obb.pt"), path)  # 快取命中不再下載
            with mock.patch("urllib.request.urlopen", side_effect=lambda url, timeout=0: (_ for _ in ()).throw(urllib.error.HTTPError(url, 404, "nf", {}, None))):
                with self.assertRaises(TrainError) as ctx:
                    yolo.resolve_model("yolo99z.pt")
            self.assertIn("not available for download", str(ctx.exception))
            for name in ("yolo26n-seg.pt", "yolo11x-pose.pt", "sam2.1_b.pt", "mobile_sam.pt", "yolov8n-cls.pt"):
                self.assertTrue(yolo._ASSET_NAME.match(name), name)
            self.assertFalse(yolo._ASSET_NAME.match("best.pt"))


# ---------------------------------------------------------------------------
# SAM：幾何與全圖提案（假模型）
# ---------------------------------------------------------------------------
class SamUnitTests(SimpleTestCase):
    def test_polygons_and_px(self):
        circle = [[100 + 40 * np.cos(a), 100 + 40 * np.sin(a)] for a in np.linspace(0, 2 * np.pi, 200, endpoint=False)]
        polys = sam._mask_to_polygons([circle, [[0, 0], [1, 0], [1, 1]]], 200, 200)
        self.assertEqual(len(polys), 1)
        self.assertTrue(3 <= len(polys[0]) <= 48)
        self.assertTrue(all(0 <= x <= 1 and 0 <= y <= 1 for x, y in polys[0]))
        self.assertEqual(sam._to_px([[-1, 2], [0.5, 0.5]], 100, 50), [[0, 49], [50, 24]])  # 夾到 [0, w-1]；0.5×49=24.5 銀行家捨入
        with self.assertRaises(TrainError):
            sam.suggest_shapes(np.zeros((10, 10, 3), np.uint8), [], device="cpu")
        with self.assertRaises(TrainError):
            sam.suggest_shapes(np.zeros((10, 10, 3), np.uint8), boxes_norm=[[0.5, 0.5, 0.5, 0.5]], device="cpu")  # 退化框
        self.assertIn(sam.default_model(), ("sam2.1_t.pt", str(settings.VISION.get("SAM_MODEL"))))

    def test_everything_sorting_limit_background(self):
        w = h = 200
        big = [[0, 0], [w, 0], [w, h], [0, h]]  # 蓋滿 → 略過
        sq = lambda x, y, s: [[x, y], [x + s, y], [x + s, y + s], [x, y + s]]  # noqa: E731
        fake = mock.Mock(return_value=[Res(masks=Masks(np.zeros((1, 1, 1)), xy=[big, sq(10, 10, 30), sq(100, 100, 60), sq(50, 50, 45), [[0, 0], [1, 1]]]))])
        with mock.patch.object(sam, "_session", return_value=fake):
            shapes = sam.suggest_everything(np.zeros((h, w, 3), np.uint8), device="cpu", max_masks=2)
            self.assertEqual(len(shapes), 2)
            areas = [cv2.contourArea(np.asarray([[x * w, y * h] for x, y in s["points"]], np.float32)) for s in shapes]
            self.assertGreater(areas[0], areas[1])
            self.assertAlmostEqual(areas[0], 3600, delta=50)
            self.assertEqual(fake.call_args.kwargs["device"], "cpu")
            # 點與框的呼叫形狀
            out = sam.suggest_shapes(np.zeros((h, w, 3), np.uint8), [[0.5, 0.5], [0.1, 0.1]], [1, 0], device="cpu")
            self.assertEqual(fake.call_args.kwargs["points"], [[[100, 100], [20, 20]]])
            self.assertEqual(fake.call_args.kwargs["labels"], [[1, 0]])
            self.assertEqual(len(out), 4)
            sam.suggest_shapes(np.zeros((h, w, 3), np.uint8), [[0.5, 0.5]], boxes_norm=[[0.1, 0.1, 0.9, 0.9]], device="cpu")
            self.assertEqual(fake.call_args.kwargs["bboxes"], [[20, 20, 179, 179]])
            self.assertEqual(fake.call_args.kwargs["points"], [[[100, 100]]])

    def test_session_falls_back_to_mobile_sam(self):
        calls = []

        def fake_resolve(name, log_fn=None):
            calls.append(name)
            if name != sam.FALLBACK_MODEL:
                raise TrainError("下載失敗")
            return "mobile.pt"

        with mock.patch.object(sam, "_import_sam", return_value=lambda path: f"model:{path}"), mock.patch.object(sam, "resolve_model", side_effect=fake_resolve):
            sam._sessions.clear()
            self.assertEqual(sam._session("sam2.1_t.pt"), "model:mobile.pt")
            self.assertEqual(calls, ["sam2.1_t.pt", "mobile_sam.pt"])
            self.assertEqual(sam.loaded_model(), "mobile.pt")
            sam._sessions.clear()


# ---------------------------------------------------------------------------
# YOLO trainer：提案轉換、指標、參數
# ---------------------------------------------------------------------------
class YoloTrainerUnitTests(SimpleTestCase):
    def test_clean_metrics_and_params(self):
        raw = {"metrics/mAP50(B)": 0.5, "metrics/mAP50(M)": 0.6, "metrics/precision(B)": 0.7, "fitness": 1.2, "x": "n/a"}
        self.assertEqual(yolo._clean_metrics(raw), {"mAP50": 0.6, "precision": 0.7, "fitness": 1.2})
        keys = {p.key for p in yolo._params("m.pt", "classify")}
        self.assertNotIn("mosaic", keys)
        self.assertIn("mosaic", {p.key for p in yolo._params("m.pt", "detect")})
        self.assertEqual(next(p for p in yolo._params("m.pt", "classify") if p.key == "imgsz").default, 224)

    def test_shapes_from_result_per_task(self):
        seg = yolo.YoloSegTrainer()
        r = Res(boxes=Boxes([[0, 0, 10, 10], [0, 0, 5, 5]], [0.9, 0.8], [3, 7]), masks=Masks(np.zeros((2, 1, 1)), xy=[np.array([[0, 0], [50, 0], [50, 50], [0, 50]], np.float32), np.array([[0, 0], [1, 0]], np.float32)]))
        names = {3: "car", 7: "sq"}
        shapes, scores = seg._shapes_from_result(r, names, ["sq"], using_base=True, w=100, h=100)
        self.assertEqual([s["label"] for s in shapes], ["sq"])  # 底模：名稱對不上掛第一類；退化 polygon 略過
        shapes, _ = seg._shapes_from_result(r, names, ["sq"], using_base=False, w=100, h=100)
        self.assertEqual(shapes, [])  # 訓練過：只留名稱對上的（car 不在、sq 那個是退化 polygon）
        det = yolo.YoloDetectTrainer()
        r2 = Res(boxes=Boxes([[10, 20, 30, 40]], [0.5], [3]))
        shapes, scores = det._shapes_from_result(r2, names, ["car"], using_base=False, w=100, h=200)
        self.assertEqual(shapes, [{"label": "car", "kind": "bbox", "points": [[0.1, 0.1], [0.3, 0.2]]}])
        obb = yolo.YoloObbTrainer()
        r3 = Res(obb=Obb(np.array([[[0, 0], [10, 0], [10, 10], [0, 10]]], np.float32), np.zeros((1, 5)), [0.4], [9]))
        shapes, _ = obb._shapes_from_result(r3, {9: "x"}, ["y"], using_base=True, w=100, h=100)
        self.assertEqual((shapes[0]["label"], shapes[0]["kind"], len(shapes[0]["points"])), ("y", "polygon", 4))

    def test_suggest_classify_and_missing_weights(self):
        folder = temp_dir()
        try:
            path = save_png(np.zeros((32, 32, 3), np.uint8), folder, "u.png")
            cls = yolo.YoloClassifyTrainer()
            with self.assertRaises(TrainError):
                cls.suggest([], [SampleRef(id="u", label="", path=path)], ["ok"], {"weights": os.path.join(folder, "gone.pt")})
            with self.assertRaises(TrainError):
                cls.suggest([], [SampleRef(id="u", label="", path=path)], [], {})
            self.assertEqual(cls.suggest([], [], ["ok"], {}), [])
            weights = os.path.join(folder, "best.pt")
            open(weights, "wb").write(b"x")

            class ClsYOLO(FakeYOLO):
                def __init__(self, p, **kw):
                    super().__init__(p, **kw)
                    self.names = {0: "ng", 1: "ok"}
                    self.ckpt = {"train_args": {"imgsz": 224}}

                def predict(self, image, **kw):
                    self.last = kw
                    return [Res(probs=Probs([1, 0], [0.8, 0.2]))]

            with mock.patch.object(yolo, "_import_ultralytics", return_value=ClsYOLO):
                sugg = cls.suggest([], [SampleRef(id="u", label="", path=path)], ["ok", "ng"], {"weights": weights, "suggest_conf": 0.5})
            self.assertEqual((sugg[0].sample_id, sugg[0].label, sugg[0].score), ("u", "ok", 0.8))
            # 底模的分類名稱對不上 → 沒有提案（不掛第一類）
            with mock.patch.object(yolo, "_import_ultralytics", return_value=ClsYOLO):
                self.assertEqual(cls.suggest([], [SampleRef(id="u", label="", path=path)], ["good", "bad"], {"weights": weights}), [])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_train_requires_classes_and_matching_base_task(self):
        with self.assertRaises(TrainError):
            yolo.YoloDetectTrainer().train([], [], {}, "cpu", lambda f, s, m: None)
        with self.assertRaises(TrainError):
            yolo.YoloClassifyTrainer().train([], ["only"], {}, "cpu", lambda f, s, m: None)
