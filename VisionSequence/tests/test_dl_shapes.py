"""shapes 標記與分割 trainer：YOLO txt 互轉、輕量語意分割端到端、YOLO trainer 缺依賴、實例分割後處理、API。"""

from __future__ import annotations

import os
import shutil
import uuid

import cv2
import numpy as np
from django.test import Client, SimpleTestCase, TransactionTestCase

from apps.vision.dl import base as dl_base
from apps.vision.dl.base import SampleRef, TrainError
from apps.vision.dl.builtin import PatchSegmentTrainer
from apps.vision.dl.shapes import export_dataset, iter_dataset, rasterize, read_yaml_classes, shapes_to_yolo, validate_shapes, yolo_to_shapes
from apps.vision.tools.builtin.dl import parse_yolo_seg
from tests._helpers import run_tool, temp_dir

dl_base.register_builtins()

CLASSES = ["spot"]


def _seg_image(cx: float, cy: float, seed: int, size: int = 96) -> tuple[np.ndarray, list]:
    """深灰底＋一塊亮紅色方形區域；回傳 (影像, shapes 標記)。"""
    rng = np.random.default_rng(seed)
    img = np.full((size, size, 3), 60, dtype=np.int16)
    img += rng.integers(-10, 10, img.shape, dtype=np.int16)
    half = 0.15
    x0, y0, x1, y1 = (cx - half) * size, (cy - half) * size, (cx + half) * size, (cy + half) * size
    cv2.rectangle(img, (int(x0), int(y0)), (int(x1), int(y1)), (40, 40, 220), -1)
    shapes = [{"label": "spot", "kind": "polygon", "points": [[cx - half, cy - half], [cx + half, cy - half], [cx + half, cy + half], [cx - half, cy + half]]}]
    return np.clip(img, 0, 255).astype(np.uint8), shapes


def _write_seg_samples(folder: str, n: int = 6) -> list[SampleRef]:
    refs = []
    rng = np.random.default_rng(1)
    for i in range(n):
        cx, cy = float(rng.uniform(0.3, 0.7)), float(rng.uniform(0.3, 0.7))
        img, shapes = _seg_image(cx, cy, i)
        path = os.path.join(folder, f"s{i}.png")
        ok, buf = cv2.imencode(".png", img)
        assert ok
        buf.tofile(path)
        refs.append(SampleRef(id=str(i), label="", path=path, shapes=shapes))
    return refs


class ShapeFormatTests(SimpleTestCase):
    def test_validate_and_yolo_roundtrip(self):
        shapes = validate_shapes([
            {"label": "spot", "kind": "polygon", "points": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]]},
            {"label": "spot", "kind": "bbox", "points": [[0.6, 0.7], [0.2, 0.3]]},  # 反向座標 → 正規化
        ], CLASSES)
        self.assertEqual(shapes[1]["points"], [[0.2, 0.3], [0.6, 0.7]])
        text = shapes_to_yolo(shapes, CLASSES)
        self.assertIn("\t", text)
        self.assertTrue(text.endswith("\n"))
        back = yolo_to_shapes(text, CLASSES)
        self.assertEqual(len(back), 2)
        self.assertEqual(back[0]["kind"], "polygon")
        self.assertEqual(back[1]["kind"], "bbox")
        for a, b in zip(shapes[0]["points"], back[0]["points"]):
            self.assertAlmostEqual(a[0], b[0], places=5)
        # 空白分隔（其他工具寫的）也讀得懂
        self.assertEqual(yolo_to_shapes("0 0.1 0.1 0.5 0.1 0.5 0.5", CLASSES)[0]["kind"], "polygon")

    def test_validate_rejects_bad(self):
        from apps.core.errors import ValidationError

        with self.assertRaises(ValidationError):
            validate_shapes([{"label": "nope", "kind": "polygon", "points": [[0, 0], [1, 0], [1, 1]]}], CLASSES)
        with self.assertRaises(ValidationError):
            validate_shapes([{"label": "spot", "kind": "polygon", "points": [[0, 0], [1, 0]]}], CLASSES)

    def test_rasterize(self):
        mask = rasterize([{"label": "spot", "kind": "polygon", "points": [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]}], CLASSES, 40, 40)
        self.assertEqual(int(mask[20, 20]), 1)
        self.assertEqual(int(mask[2, 2]), 0)

    def test_dataset_export_import(self):
        folder = temp_dir()
        out = os.path.join(folder, "ds")
        try:
            refs = _write_seg_samples(folder, 4)
            stats = export_dataset(((r.id, r.path, r.shapes) for r in refs), CLASSES, out, val_ratio=0.25)
            self.assertEqual(stats["train"] + stats["val"], 4)
            self.assertTrue(os.path.isfile(os.path.join(out, "data.yaml")))
            self.assertEqual(read_yaml_classes(out), CLASSES)
            rows = iter_dataset(out)
            self.assertEqual(len(rows), 4)
            for _, text in rows:
                self.assertTrue(yolo_to_shapes(text, CLASSES))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class PatchSegmentTests(SimpleTestCase):
    def setUp(self):
        self.folder = temp_dir()
        self.refs = _write_seg_samples(self.folder)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_train_export_and_infer_with_dl_segment(self):
        trainer = PatchSegmentTrainer()
        params = {"input_size": 128, "epochs": 200, "samples_per_image": 2000}
        result = trainer.train(self.refs, CLASSES, params, "cpu", lambda *a: None)
        self.assertGreaterEqual(result.metrics["train_accuracy"], 0.95)
        self.assertEqual(result.tool_key, "dl_segment")
        model_path = os.path.join(self.folder, "seg.onnx")
        with open(model_path, "wb") as f:
            f.write(result.onnx_bytes)
        img, shapes = _seg_image(0.5, 0.5, 99)
        tool_params = {**result.tool_params, "model": "m1", "min_area": 50}
        r = run_tool("dl_segment", image=img, params=tool_params, assets={"m1": model_path})
        self.assertEqual(r.status, "ok", r.message)
        self.assertGreater(r.outputs["area"], 100)
        # 目標區域中心應被標為類別 1
        cls_map = r.outputs["class_map"]
        self.assertEqual(int(cls_map[cls_map.shape[0] // 2, cls_map.shape[1] // 2]), 1)
        self.assertEqual(int(cls_map[3, 3]), 0)

    def test_suggest_shapes(self):
        trainer = PatchSegmentTrainer()
        labeled, unlabeled = self.refs[:4], [SampleRef(id=r.id, label="", path=r.path) for r in self.refs[4:]]
        out = trainer.suggest(labeled, unlabeled, CLASSES, {"input_size": 128})
        self.assertTrue(out)
        for sg in out:
            self.assertTrue(sg.shapes)
            self.assertEqual(sg.shapes[0]["label"], "spot")
            self.assertGreaterEqual(len(sg.shapes[0]["points"]), 3)

    def test_train_without_shapes_fails(self):
        refs = [SampleRef(id="x", label="", path=self.refs[0].path)]
        with self.assertRaises(TrainError):
            PatchSegmentTrainer().train(refs, CLASSES, {}, "cpu", lambda *a: None)


class YoloTrainerTests(SimpleTestCase):
    def test_catalogue_and_missing_deps(self):
        items = {t["kind"]: t for t in dl_base.catalogue()}
        self.assertIn("yolo_seg", items)
        self.assertEqual(items["yolo_seg"]["label_mode"], "shapes")
        self.assertEqual(items["yolo_seg"]["tool_key"], "dl_instance")
        try:
            import ultralytics  # noqa: F401

            has_ultra = True
        except ImportError:
            has_ultra = False
        if not has_ultra:
            folder = temp_dir()
            try:
                refs = _write_seg_samples(folder, 3)
                with self.assertRaises(TrainError) as ctx:
                    dl_base.get_trainer("yolo_seg").train(refs, CLASSES, {}, "cpu", lambda *a: None)
                self.assertIn("ultralytics", str(ctx.exception))
            finally:
                shutil.rmtree(folder, ignore_errors=True)


class ParseYoloSegTests(SimpleTestCase):
    def test_synthetic_instance(self):
        """手工組一組 YOLO-seg 風格輸出：一個高信心框＋讓 mask 在框內為正的 protos。"""
        size, nm, nc, n = 64, 4, 2, 100  # 候選框數遠大於通道數（真實 YOLO 為 8400）
        det = np.zeros((1, 4 + nc + nm, n), dtype=np.float32)
        # 候選 0：中心 (32,32)、寬高 24，類別 1 分數 0.9，係數推高 proto 0
        det[0, :4, 0] = [32, 32, 24, 24]
        det[0, 4 + 1, 0] = 0.9
        det[0, 4 + nc, 0] = 5.0
        protos = np.full((1, nm, 16, 16), -5.0, dtype=np.float32)
        protos[0, 0, 4:12, 4:12] = 5.0  # proto 0 在中心區域為正
        out = parse_yolo_seg(det, protos, conf=0.25, iou=0.45, max_count=10, size=(size, size))
        self.assertEqual(len(out), 1)
        inst = out[0]
        self.assertEqual(inst["class_id"], 1)
        self.assertAlmostEqual(inst["score"], 0.9, places=5)
        self.assertTrue(inst["mask"][32, 32])
        self.assertFalse(inst["mask"][2, 2])


class ShapesApiTests(TransactionTestCase):
    def setUp(self):
        self.client = Client()

    def post(self, url, body=None):
        return self.client.post(url, data=body, content_type="application/json")

    def _project(self):
        r = self.post("/api/vision/dl/projects", {"name": f"seg-{uuid.uuid4().hex[:6]}", "trainer_kind": "patch_segment", "classes": ["spot"]})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def _upload(self, pid, seed, cx=0.5, cy=0.5):
        from django.core.files.uploadedfile import SimpleUploadedFile

        img, shapes = _seg_image(cx, cy, seed)
        ok, buf = cv2.imencode(".png", img)
        assert ok
        r = self.client.post(f"/api/vision/dl/projects/{pid}/samples", {"files": SimpleUploadedFile(f"s{seed}.png", buf.tobytes(), content_type="image/png")})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["items"][0], shapes

    def test_shapes_label_flow(self):
        project = self._project()
        pid = project["id"]
        sample, shapes = self._upload(pid, 1)
        r = self.client.patch(f"/api/vision/dl/samples/{sample['id']}", data=__import__("json").dumps({"shapes": shapes}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()["shapes"]), 1)
        counts = self.client.get(f"/api/vision/dl/projects/{pid}").json()["counts"]
        self.assertEqual(counts["unlabeled"], 0)
        self.assertEqual(counts["per_class"]["spot"], 1)
        # 清空 shapes → 回未標記
        r = self.client.patch(f"/api/vision/dl/samples/{sample['id']}", data='{"shapes": []}', content_type="application/json")
        self.assertEqual(self.client.get(f"/api/vision/dl/projects/{pid}").json()["counts"]["unlabeled"], 1)

    def test_auto_label_shapes_and_accept(self):
        project = self._project()
        pid = project["id"]
        ids = []
        for i in range(4):
            sample, shapes = self._upload(pid, 10 + i, cx=0.4 + 0.05 * i)
            ids.append(sample["id"])
            self.client.patch(f"/api/vision/dl/samples/{sample['id']}", data=__import__("json").dumps({"shapes": shapes}), content_type="application/json")
        blank, _ = self._upload(pid, 50, cx=0.6)
        r = self.post(f"/api/vision/dl/projects/{pid}/auto-label", {"params": {"input_size": 128, "epochs": 60}})
        self.assertEqual(r.status_code, 200, r.content)
        items = r.json()["items"]
        self.assertTrue(items)
        self.assertIn("shapes", items[0])
        r = self.post(f"/api/vision/dl/projects/{pid}/labels", {"items": [{**it, "by": "auto"} for it in items]})
        self.assertEqual(r.status_code, 200, r.content)
        row = self.client.get(f"/api/vision/dl/projects/{pid}/samples").json()["items"]
        auto = [x for x in row if x["labeled_by"] == "auto"]
        self.assertTrue(auto)
        self.assertTrue(auto[0]["shapes"])

    def test_dataset_export_import_endpoints(self):
        import json as _json

        project = self._project()
        pid = project["id"]
        for i in range(3):
            sample, shapes = self._upload(pid, 20 + i)
            self.client.patch(f"/api/vision/dl/samples/{sample['id']}", data=_json.dumps({"shapes": shapes}), content_type="application/json")
        out_dir = os.path.join(temp_dir(), "ds")
        try:
            r = self.post(f"/api/vision/dl/projects/{pid}/dataset-export", {"dir": out_dir, "val_ratio": 0.34})
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.json()["train"] + r.json()["val"], 3)
            # 匯回另一個專案
            other = self._project()
            r = self.post(f"/api/vision/dl/projects/{other['id']}/dataset-import", {"dir": out_dir})
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.json()["imported"], 3)
            self.assertEqual(r.json()["counts"]["unlabeled"], 0)
        finally:
            shutil.rmtree(os.path.dirname(out_dir), ignore_errors=True)
