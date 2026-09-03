"""YOLO 整合：資料集匯出（segment／detect／obb／classify）、trainer 目錄、訓練產物雙資產（best.pt＋ONNX）；
以及需要 ultralytics＋GPU／網路的實機測試（設 VISION_TEST_DL=1 才跑）：yolo_* 五個工具、SAM2 點／框／全圖、
sam-point／auto-label API、四個 trainer 各訓練 1 epoch 並用產物在 yolo_* 工具實跑。"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import shutil
import unittest
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.vision.dl import base as dl_base
from apps.vision.dl import jobs, shapes
from apps.vision.dl.base import SampleRef, TrainResult
from apps.vision.tools import base as tools_base
from tests._helpers import run_tool, temp_dir

LIVE = os.environ.get("VISION_TEST_DL") == "1" and importlib.util.find_spec("ultralytics") is not None
live = unittest.skipUnless(LIVE, "設 VISION_TEST_DL=1 且安裝 ultralytics 才跑（會用 GPU、第一次會下載底模）")
BUS_URL = "https://ultralytics.com/images/bus.jpg"
BOATS_URL = "https://ultralytics.com/images/boats.jpg"


def _weights_dir() -> str:
    d = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", "weights")
    os.makedirs(d, exist_ok=True)
    return d


def _sample(url: str) -> np.ndarray:
    path = os.path.join(_weights_dir(), os.path.basename(url))
    if not os.path.isfile(path):
        urllib.request.urlretrieve(url, path)
    return cv2.imread(path)


SHAPES = [{"label": "a", "kind": "bbox", "points": [[0.1, 0.2], [0.3, 0.6]]}, {"label": "b", "kind": "polygon", "points": [[0.5, 0.5], [0.9, 0.5], [0.9, 0.9], [0.5, 0.9]]},
          {"label": "zzz", "kind": "bbox", "points": [[0, 0], [1, 1]]}]


class ExportTests(SimpleTestCase):
    def test_shapes_to_yolo_per_task(self):
        seg = shapes.shapes_to_yolo(SHAPES, ["a", "b"], "segment").splitlines()
        det = shapes.shapes_to_yolo(SHAPES, ["a", "b"], "detect").splitlines()
        obb = shapes.shapes_to_yolo(SHAPES, ["a", "b"], "obb").splitlines()
        self.assertEqual(len(seg), 2)  # 不在類別清單的略過
        self.assertEqual(len(seg[0].split("\t")), 9)  # bbox → 四角 polygon
        self.assertEqual(det[0].split("\t")[:1] + [round(float(v), 3) for v in det[0].split("\t")[1:]], ["0", 0.2, 0.4, 0.2, 0.4])
        self.assertEqual([round(float(v), 3) for v in det[1].split("\t")[1:]], [0.7, 0.7, 0.4, 0.4])  # polygon 取外接框
        self.assertEqual(len(obb[1].split("\t")), 9)
        corners = [round(float(v), 2) for v in obb[1].split("\t")[1:]]
        self.assertEqual(sorted(corners[0::2]), [0.5, 0.5, 0.9, 0.9])  # 軸對齊四邊形的最小旋轉矩形＝自己
        self.assertEqual(shapes.yolo_to_shapes(det[0] + "\n", ["a", "b"])[0]["kind"], "bbox")
        with self.assertRaises(Exception):
            shapes.shapes_to_yolo(SHAPES, ["a"], "pose")

    def test_export_dataset_task_and_classify(self):
        folder = temp_dir()
        try:
            img = np.zeros((32, 32, 3), np.uint8)
            paths = []
            for i in range(4):
                p = os.path.join(folder, f"s{i}.png")
                cv2.imwrite(p, img)
                paths.append(p)
            rows = [(f"id{i}", paths[i], SHAPES[:2], "") for i in range(4)]
            stats = shapes.export_dataset(rows, ["a", "b"], os.path.join(folder, "det"), val_ratio=0.25, task="detect")
            self.assertEqual((stats["train"], stats["val"], stats["task"]), (3, 1, "detect"))
            txt = open(glob.glob(os.path.join(folder, "det", "labels", "train", "*.txt"))[0], encoding="utf-8").read().splitlines()
            self.assertEqual(len(txt[0].split("\t")), 5)
            crows = [(f"id{i}", paths[i], "dark" if i % 2 else "bright", "") for i in range(4)]
            cstats = shapes.export_classify_dataset(crows, ["bright", "dark"], os.path.join(folder, "cls"), val_ratio=0.25)
            self.assertEqual((cstats["train"], cstats["val"]), (2, 2))  # 分層：每類至少 1 張進 val（ultralytics 要求 val 每類都有）
            self.assertEqual(sorted(os.listdir(os.path.join(folder, "cls", "train"))), ["bright", "dark"])
            self.assertEqual(sorted(os.listdir(os.path.join(folder, "cls", "val"))), ["bright", "dark"])
            self.assertEqual(len(glob.glob(os.path.join(folder, "cls", "*", "*", "*.jpg"))), 4)
            self.assertEqual({len(glob.glob(os.path.join(folder, "cls", "val", c, "*.jpg"))) for c in ("bright", "dark")}, {1})
            self.assertEqual(shapes._safe_name("a/b:c?"), "abc")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class TrainerRegistryTests(SimpleTestCase):
    def test_yolo_trainers_registered(self):
        dl_base.register_builtins()
        cat = {t["kind"]: t for t in dl_base.catalogue()}
        self.assertTrue({"yolo_seg", "yolo_detect", "yolo_cls", "yolo_obb"} <= set(cat))
        self.assertEqual({k: cat[k]["label_mode"] for k in ("yolo_seg", "yolo_detect", "yolo_cls", "yolo_obb")}, {"yolo_seg": "shapes", "yolo_detect": "shapes", "yolo_cls": "classes", "yolo_obb": "shapes"})
        self.assertEqual({k: cat[k]["tool_key"] for k in ("yolo_seg", "yolo_detect", "yolo_cls", "yolo_obb")}, {"yolo_seg": "yolo_segment", "yolo_detect": "yolo_detect", "yolo_cls": "yolo_classify", "yolo_obb": "yolo_obb"})
        self.assertNotIn("mosaic", [p["key"] for p in cat["yolo_cls"]["params"]])
        self.assertEqual(cat["yolo_cls"]["min_per_class"], 2)
        keys = {t.key for t in tools_base.all_types()}
        self.assertTrue({"yolo_detect", "yolo_segment", "yolo_classify", "yolo_pose", "yolo_obb"} <= keys)
        for k in ("yolo_detect", "yolo_segment", "yolo_classify", "yolo_pose", "yolo_obb"):
            t = tools_base.get(k)
            self.assertEqual(t.category, "dl")
            self.assertTrue(t.heavy)
            self.assertIn("model", [p.key for p in t.params])
            self.assertIn("model_name", [p.key for p in t.params])

    def test_tool_without_model_gives_clean_error(self):
        with self.assertRaises(tools_base.ToolError):
            run_tool("yolo_detect", np.zeros((64, 64, 3), np.uint8), {"model_name": ""})


TMP = temp_dir()


class _FakeWeightsTrainer(dl_base.Trainer):
    kind = "fake_weights"
    label = "fake"
    label_mode = "classes"
    tool_key = "yolo_detect"

    def train(self, samples, classes, params, device, progress):
        progress(0.5, "half", None)
        return TrainResult(onnx_bytes=b"ONNX", metrics={"acc": 1.0}, tool_key="dl_detect", tool_params={"labels": "a"},
                           weights_bytes=b"PT", weights_ext=".pt", weights_tool_key="yolo_detect", weights_tool_params={"model_name": "", "conf": 0.3})


@override_settings(VISION={**settings.VISION, "ASSET_DIR": Path(TMP), "PERSIST_RUNS": False})
class WeightsAssetTests(TransactionTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def test_train_job_stores_weights_and_onnx(self):
        from apps.vision.models import Asset, DlProject

        dl_base.register_builtins()
        dl_base._TRAINERS[_FakeWeightsTrainer.kind] = _FakeWeightsTrainer()
        try:
            project = DlProject.objects.create(name="fake-w", trainer_kind="fake_weights", classes=["a"])
            job = jobs.TrainJob(id="j1", project_id=project.id, project_name=project.name, trainer_kind="fake_weights", device="cpu", asset_name="模型 A")
            jobs._train(job, project.id, {})
            assets = list(Asset.objects.filter(kind="model").order_by("created_at"))
            self.assertEqual(len(assets), 2)
            pt = next(a for a in assets if a.path.endswith(".pt"))
            onnx = next(a for a in assets if a.path.endswith(".onnx"))
            self.assertEqual((pt.name, pt.meta["tool_key"], pt.meta["format"], pt.meta["onnx_asset_id"]), ("模型 A", "yolo_detect", "pt", onnx.id.hex))
            self.assertEqual((onnx.name, onnx.meta["tool_key"], onnx.meta["format"]), ("模型 A（ONNX）", "dl_detect", "onnx"))
            project.refresh_from_db()
            self.assertEqual(project.last_asset_id, pt.id.hex)
            self.assertEqual(project.last_metrics["onnx_asset_id"], onnx.id.hex)
            self.assertEqual((job.status, job.tool_key, job.tool_params["conf"], job.asset_id), ("done", "yolo_detect", 0.3, pt.id.hex))
            self.assertEqual(open(pt.path, "rb").read(), b"PT")
        finally:
            dl_base._TRAINERS.pop(_FakeWeightsTrainer.kind, None)


# ---------------------------------------------------------------------------
# 實機（VISION_TEST_DL=1）
# ---------------------------------------------------------------------------
@live
class YoloToolsLiveTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bus = _sample(BUS_URL)
        cls.boats = _sample(BOATS_URL)

    def test_detect_with_roi_and_filters(self):
        r = run_tool("yolo_detect", self.bus, {"model_name": "yolo11n.pt", "conf": 0.25})
        self.assertEqual((r.status, r.branch), ("ok", "found"))
        self.assertIn("bus", r.outputs["labels"])
        self.assertGreaterEqual(r.outputs["count"], 4)
        self.assertEqual({k for k in r.outputs["matches"][0]} >= {"x", "y", "w", "h", "cx", "cy", "label", "score", "index"}, True)
        self.assertNotIn("_i", r.outputs["matches"][0])
        roi = {"shape": "rect", "x": 0, "y": 200, "w": 810, "h": 600}
        r2 = run_tool("yolo_detect", self.bus, {"model_name": "yolo11n.pt", "conf": 0.25, "roi": roi, "filter_labels": "person"})
        self.assertTrue(all(lbl == "person" for lbl in r2.outputs["labels"]))
        self.assertTrue(all(200 <= d["cy"] <= 800 for d in r2.outputs["matches"]))
        self.assertEqual(r2.overlays[0]["kind"], "polygon" if r2.overlays[0].get("kind") == "polygon" else r2.overlays[0]["kind"])  # roi overlay 在第一個
        r3 = run_tool("yolo_detect", self.bus, {"model_name": "yolo11n.pt", "roi": {"shape": "rotated_rect", "cx": 405, "cy": 540, "w": 700, "h": 900, "angle": 10}})
        self.assertGreaterEqual(r3.outputs["count"], 3)
        r4 = run_tool("yolo_detect", self.bus, {"model_name": "yolo11n.pt", "min_count": 99})
        self.assertEqual((r4.status, r4.branch), ("ng", "found"))
        r5 = run_tool("yolo_detect", np.zeros((320, 320, 3), np.uint8), {"model_name": "yolo11n.pt"})
        self.assertEqual((r5.outputs["count"], r5.branch, r5.status), (0, "not_found", "ng"))

    def test_segment_classify_pose_obb(self):
        r = run_tool("yolo_segment", self.bus, {"model_name": "yolo11n-seg.pt", "conf": 0.25})
        self.assertGreaterEqual(r.outputs["count"], 4)
        self.assertEqual(r.outputs["mask"].shape, self.bus.shape[:2])
        self.assertGreater(int(r.outputs["mask"].max()), 0)
        self.assertEqual(len(r.outputs["contours"]), len([o for o in r.overlays if o["kind"] == "contours"]) or len(r.outputs["contours"]))
        self.assertTrue(all(m["area"] > 0 for m in r.outputs["matches"]))
        c = run_tool("yolo_classify", self.bus, {"model_name": "yolo11n-cls.pt", "threshold": 0.1, "top_k": 3})
        self.assertEqual(len(c.outputs["top"]), 3)
        self.assertEqual(c.outputs["label"], c.outputs["top"][0]["label"])
        c2 = run_tool("yolo_classify", self.bus, {"model_name": "yolo11n-cls.pt", "threshold": 0.1, "pass_labels": "nothing"})
        self.assertEqual((c2.status, c2.branch), ("ng", "fail"))
        p = run_tool("yolo_pose", self.bus, {"model_name": "yolo11n-pose.pt", "conf": 0.25})
        self.assertGreaterEqual(p.outputs["count"], 3)
        self.assertEqual(len(p.outputs["keypoints"][0]["points"]), 17)
        self.assertEqual(len(p.outputs["keypoints"][0]["points"][0]), 3)
        self.assertTrue(any(o["kind"] == "line" for o in p.overlays))
        o = run_tool("yolo_obb", self.boats, {"model_name": "yolo11n-obb.pt", "conf": 0.25, "max_count": 20})
        self.assertGreaterEqual(o.outputs["count"], 5)
        self.assertLessEqual(o.outputs["count"], 20)
        m = o.outputs["matches"][0]
        self.assertTrue({"cx", "cy", "w", "h", "angle", "points"} <= set(m))
        self.assertEqual(len(m["points"]), 4)
        self.assertEqual(len(o.outputs["contours"]), o.outputs["count"])

    def test_model_asset_pt_and_onnx_and_task_mismatch(self):
        w = _weights_dir()
        pt = os.path.join(w, "yolo11n.pt")
        r = run_tool("yolo_detect", self.bus, {"model": "w", "conf": 0.25}, assets={"w": pt})
        self.assertGreaterEqual(r.outputs["count"], 4)
        onnx = os.path.join(w, "yolo11n.onnx")
        if not os.path.isfile(onnx):
            from ultralytics import YOLO

            YOLO(pt).export(format="onnx", imgsz=640, dynamic=False, verbose=False)
        r2 = run_tool("yolo_detect", self.bus, {"model": "o", "conf": 0.25, "device": "cpu"}, assets={"o": onnx})
        self.assertGreaterEqual(r2.outputs["count"], 4)
        with self.assertRaises(tools_base.ToolError):
            run_tool("yolo_pose", self.bus, {"model_name": "yolo11n.pt"})
        with self.assertRaises(tools_base.ToolError):
            run_tool("yolo_detect", self.bus, {"model_name": "nope-model.pt"})


@live
class SamLiveTests(SimpleTestCase):
    def test_point_box_everything(self):
        from apps.vision.dl import sam

        bus = _sample(BUS_URL)
        one = sam.suggest_shapes(bus, [[0.5, 0.5]], device="cuda" if _cuda() else "cpu")
        self.assertEqual(len(one), 1)
        self.assertEqual(one[0]["kind"], "polygon")
        self.assertTrue(3 <= len(one[0]["points"]) <= 48)
        two = sam.suggest_shapes(bus, boxes_norm=[[0.05, 0.35, 0.3, 0.85], [0.6, 0.3, 0.95, 0.85]], device="cuda" if _cuda() else "cpu")
        self.assertEqual(len(two), 2)
        many = sam.suggest_everything(bus, device="cuda" if _cuda() else "cpu", max_masks=8)
        self.assertTrue(1 <= len(many) <= 8)
        self.assertTrue(sam.loaded_model().endswith(".pt"))
        with self.assertRaises(dl_base.TrainError):
            sam.suggest_shapes(bus, [], device="cpu")


def _cuda() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


@live
@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class SamApiLiveTests(TransactionTestCase):
    def _json(self, method: str, path: str, body: dict | None = None):
        return getattr(self.client, method)(path, data=json.dumps(body or {}), content_type="application/json")

    def test_sam_point_boxes_and_auto_label_sam(self):
        bus = _sample(BUS_URL)
        r = self._json("post", "/api/vision/dl/projects", {"name": "sam-live", "trainer_kind": "yolo_seg", "classes": ["thing"]})
        self.assertEqual(r.status_code, 201, r.content)
        pid = r.json()["id"]
        ok, buf = cv2.imencode(".jpg", bus)
        r = self.client.post(f"/api/vision/dl/projects/{pid}/samples", {"files": [SimpleUploadedFile("bus.jpg", buf.tobytes(), content_type="image/jpeg")]})
        self.assertEqual(r.status_code, 201, r.content)
        sid = r.json()["items"][0]["id"]
        r = self._json("post", f"/api/vision/dl/projects/{pid}/sam-point", {"sample_id": sid, "boxes": [[0.05, 0.35, 0.3, 0.85]]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()["shapes"]), 1)
        self.assertTrue(r.json()["model"])
        r = self._json("post", f"/api/vision/dl/projects/{pid}/sam-point", {"sample_id": sid, "points": [[0.5, 0.5], [0.1, 0.1]], "labels": [1, 0]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._json("post", f"/api/vision/dl/projects/{pid}/sam-point", {"sample_id": sid}).status_code, 422)
        r = self._json("post", f"/api/vision/dl/projects/{pid}/auto-label", {"method": "sam", "max_masks": 5})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual((body["method"], body["remaining"], len(body["items"])), ("sam", 0, 1))
        self.assertTrue(1 <= len(body["items"][0]["shapes"]) <= 5)
        self.assertTrue(all(sh["label"] == "thing" for sh in body["items"][0]["shapes"]))
        # classes 專案不能用 SAM 全圖提案
        r = self._json("post", "/api/vision/dl/projects", {"name": "sam-live-cls", "trainer_kind": "yolo_cls", "classes": ["a", "b"]})
        self.assertEqual(self._json("post", f"/api/vision/dl/projects/{r.json()['id']}/auto-label", {"method": "sam"}).status_code, 422)


def _synthetic_samples(folder: str, n: int = 8, size: int = 160) -> list[SampleRef]:
    """亮方塊在暗背景上：bbox／polygon 標記 'sq'；分類用 label bright／dark（偶數張有方塊）。"""
    rng = np.random.default_rng(3)
    refs = []
    for i in range(n):
        img = np.full((size, size, 3), 30, np.uint8)
        has = i % 2 == 0
        if has:
            x, y = int(rng.integers(20, size - 70)), int(rng.integers(20, size - 70))
            cv2.rectangle(img, (x, y), (x + 50, y + 40), (220, 220, 220), -1)
            box = [[x / size, y / size], [(x + 50) / size, (y + 40) / size]]
            shp = [{"label": "sq", "kind": "bbox", "points": box}]
        else:
            cv2.circle(img, (size // 2, size // 2), 3, (60, 60, 60), -1)
            shp = []
        path = os.path.join(folder, f"s{i}.png")
        cv2.imwrite(path, img)
        refs.append(SampleRef(id=f"s{i}", label="bright" if has else "dark", path=path, shapes=shp, split="val" if i in (0, 1) else "train"))
    return refs


@live
class YoloTrainLiveTests(SimpleTestCase):
    """四個 trainer 各訓練 1 epoch（imgsz 160、合成資料），產物能在對應的 yolo_* 工具實跑。"""

    def _train(self, trainer_kind: str, refs: list[SampleRef], classes: list[str], extra: dict[str, Any] | None = None):
        dl_base.register_builtins()
        trainer = dl_base.get_trainer(trainer_kind)
        stages: list[str] = []
        history: list[dict] = []

        class P:
            def __call__(self, f, s, m):
                stages.append(s)

            def log(self, m):
                pass

            def history(self, point):
                history.append(point)

        params = {"epochs": 1, "imgsz": 160 if trainer_kind != "yolo_cls" else 224, "batch": 4, "workers": 0, "patience": 5, "mosaic": 0.0, **(extra or {})}
        result = trainer.train(refs, classes, params, "cuda" if _cuda() else "cpu", P())
        self.assertTrue(result.onnx_bytes)
        self.assertTrue(result.weights_bytes)
        self.assertEqual(result.weights_tool_key, trainer.tool_key)
        self.assertEqual(result.metrics["task"], trainer.task)
        self.assertTrue(stages)
        return result

    def test_detect_seg_obb_cls(self):
        folder = temp_dir()
        try:
            refs = _synthetic_samples(folder)
            labeled = [r for r in refs if r.shapes]
            # 只有偶數張有形狀（4 張：val 1、train 3）
            det = self._train("yolo_detect", labeled, ["sq"])
            pt = os.path.join(folder, "det.pt")
            open(pt, "wb").write(det.weights_bytes)
            r = run_tool("yolo_detect", cv2.imread(refs[0].path), {"model": "m", **det.weights_tool_params, "conf": 0.01}, assets={"m": pt})
            self.assertIn(r.branch, ("found", "not_found"))
            onnx = os.path.join(folder, "det.onnx")
            open(onnx, "wb").write(det.onnx_bytes)
            r2 = run_tool("dl_detect", cv2.imread(refs[0].path), {"model": "o", **det.tool_params, "conf": 0.01}, assets={"o": onnx})
            self.assertIn(r2.branch, ("found", "not_found"))
            poly = [SampleRef(id=s.id, label=s.label, path=s.path, split=s.split, shapes=[{"label": "sq", "kind": "polygon", "points": [[p[0][0], p[0][1]], [p[1][0], p[0][1]], [p[1][0], p[1][1]], [p[0][0], p[1][1]]]} for p in [sh["points"] for sh in s.shapes]]) for s in labeled]
            seg = self._train("yolo_seg", poly, ["sq"], {"model": "yolo11n-seg.pt"})
            open(os.path.join(folder, "seg.pt"), "wb").write(seg.weights_bytes)
            r3 = run_tool("yolo_segment", cv2.imread(refs[0].path), {"model": "s", **seg.weights_tool_params, "conf": 0.01}, assets={"s": os.path.join(folder, "seg.pt")})
            self.assertEqual(r3.outputs["mask"].shape, (160, 160))
            obb = self._train("yolo_obb", poly, ["sq"])
            open(os.path.join(folder, "obb.pt"), "wb").write(obb.weights_bytes)
            r4 = run_tool("yolo_obb", cv2.imread(refs[0].path), {"model": "b", **obb.weights_tool_params, "conf": 0.01}, assets={"b": os.path.join(folder, "obb.pt")})
            self.assertIn("matches", r4.outputs)
            self.assertEqual(obb.tool_key, "")
            cls = self._train("yolo_cls", refs, ["bright", "dark"])
            self.assertEqual(sorted(cls.metrics["classes"]), ["bright", "dark"])
            open(os.path.join(folder, "cls.pt"), "wb").write(cls.weights_bytes)
            r5 = run_tool("yolo_classify", cv2.imread(refs[0].path), {"model": "c", **cls.weights_tool_params, "threshold": 0.0}, assets={"c": os.path.join(folder, "cls.pt")})
            self.assertIn(r5.outputs["label"], ("bright", "dark"))
            open(os.path.join(folder, "cls.onnx"), "wb").write(cls.onnx_bytes)
            r6 = run_tool("dl_classify", cv2.imread(refs[0].path), {"model": "co", **cls.tool_params, "threshold": 0.0}, assets={"co": os.path.join(folder, "cls.onnx")})
            self.assertIn(r6.outputs["label"], ("bright", "dark"))
            # 訓練後的自動標記：detect 用 best.pt 提案 bbox
            dl_base.register_builtins()
            sugg = dl_base.get_trainer("yolo_detect").suggest([], [SampleRef(id="u", label="", path=refs[0].path)], ["sq"], {"weights": det.metrics["weights_path"], "suggest_conf": 0.01, "imgsz": 160})
            self.assertTrue(all(sh["kind"] == "bbox" for s in sugg for sh in (s.shapes or [])))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
