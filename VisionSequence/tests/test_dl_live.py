"""深度學習實機測試（VISION_TEST_DL=1；需要 ultralytics＋GPU／網路）：六個 trainer 經 API 走完（建專案→樣本→訓練→資產→流程實跑）、
訓練中取消、ai_* 工具的輸入邊界（灰階／極小／大圖／CPU／FP16／並行／ONNX 資產）、dl_detect 用 CUDA provider、SAM 正負點與多框、
各 trainer 的自動標記、範例畫廊的 DL 範本實跑。"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import threading
import time
import unittest
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.vision.dl import devices, sam
from apps.vision.graph import validate_graph
from apps.vision.models import Asset, Flow
from tests._helpers import run_tool, temp_dir
from tests.test_dl_yolo import BOATS_URL, BUS_URL, _cuda, _sample, _weights_dir

LIVE = os.environ.get("VISION_TEST_DL") == "1" and importlib.util.find_spec("ultralytics") is not None
live = unittest.skipUnless(LIVE, "設 VISION_TEST_DL=1 且安裝 ultralytics 才跑")
TMP = temp_dir()


def _shape_samples(n: int = 8, size: int = 160, kind: str = "bbox"):
    """亮方塊（label sq）在暗背景上；回 [(image, shapes)]，kind=bbox／polygon（旋轉矩形）。"""
    rng = np.random.default_rng(11)
    out = []
    for i in range(n):
        img = np.full((size, size, 3), 30, np.uint8)
        x, y = int(rng.integers(20, size - 70)), int(rng.integers(20, size - 70))
        if kind == "polygon":
            box = cv2.boxPoints(((x + 25.0, y + 20.0), (50.0, 36.0), float(rng.uniform(0, 90)))).astype(np.int32)
            cv2.fillPoly(img, [box], (220, 220, 220))
            shapes = [{"label": "sq", "kind": "polygon", "points": [[float(np.clip(px / size, 0, 1)), float(np.clip(py / size, 0, 1))] for px, py in box]}]
        else:
            cv2.rectangle(img, (x, y), (x + 50, y + 40), (220, 220, 220), -1)
            shapes = [{"label": "sq", "kind": "bbox", "points": [[x / size, y / size], [(x + 50) / size, (y + 40) / size]]}]
        img[0, i % size] = (31 + i, 30, 30)  # 每張獨一無二（樣本以像素 SHA 去重）
        out.append((img, shapes))
    return out


def _class_samples(n_per_class: int = 6, size: int = 96):
    rng = np.random.default_rng(5)
    out = []
    for i in range(n_per_class):
        for lab in ("bright", "dark"):
            img = np.full((size, size, 3), 30 if lab == "bright" else 200, np.uint8)
            cv2.circle(img, (size // 2 + int(rng.integers(-6, 6)), size // 2), size // 3, (220, 220, 220) if lab == "bright" else (40, 40, 40), -1)
            img[0, i % size] = (100 + i, 100, 100)  # 每張獨一無二（樣本以像素 SHA 去重）
            out.append((img, lab))
    return out


@live
@override_settings(VISION={**settings.VISION, "ASSET_DIR": Path(TMP), "PERSIST_RUNS": False})
class TrainersApiLiveTests(TransactionTestCase):
    """每個 trainer：API 建專案→上傳／標記→訓練→資產→用 runner 在樣本上實跑對應工具。"""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def _json(self, method, path, body=None):
        return getattr(self.client, method)(path, data=json.dumps(body or {}), content_type="application/json")

    def _upload(self, pid, image, name, label=""):
        ok, buf = cv2.imencode(".png", image)
        r = self.client.post(f"/api/vision/dl/projects/{pid}/samples", {"files": SimpleUploadedFile(name, buf.tobytes(), content_type="image/png"), "label": label})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["items"][0]["id"]

    def _wait(self, timeout=600):
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.client.get("/api/vision/dl/train/status").json().get("job")
            if st and st["status"] != "running":
                return st
            time.sleep(0.3)
        raise AssertionError("訓練逾時")

    def _run_flow(self, tool_key: str, params: dict, image: np.ndarray):
        from apps.vision.runner import runner

        graph = {"nodes": [{"id": "src", "type": "image_source", "params": {"source_id": 0}}, {"id": "t", "type": tool_key, "params": params}],
                 "edges": [{"source": "src", "target": "t"}]}
        flow = Flow.objects.create(name=f"live-{tool_key}-{time.time_ns()}", graph=validate_graph(graph))
        try:
            report = runner.run_sync(flow, trigger="preview", preview=True, input_image=image, timeout=120)
        finally:
            flow.delete()
        node = report.nodes["t"]
        self.assertNotEqual(node.status, "error", node.message)
        return report, node

    def _train_project(self, kind: str, classes: list[str], samples, params: dict, label_mode: str):
        r = self._json("post", "/api/vision/dl/projects", {"name": f"live-{kind}-{time.time_ns()}", "trainer_kind": kind, "classes": classes})
        self.assertEqual(r.status_code, 201, r.content)
        pid = r.json()["id"]
        for i, (image, ann) in enumerate(samples):
            if label_mode == "classes":
                self._upload(pid, image, f"s{i}.png", label=ann)
            else:
                sid = self._upload(pid, image, f"s{i}.png")
                self.assertEqual(self._json("patch", f"/api/vision/dl/samples/{sid}", {"shapes": ann}).status_code, 200)
        r = self._json("post", f"/api/vision/dl/projects/{pid}/train", {"params": params, "asset_name": f"live-{kind}"})
        self.assertEqual(r.status_code, 202, r.content)
        st = self._wait()
        self.assertEqual(st["status"], "done", st.get("error"))
        self.assertTrue(st["pending"])  # 訓練完不自動進資產庫
        st = self._json("post", "/api/vision/dl/train/save", {"name": f"live-{kind}"}).json()
        self.assertTrue(st["saved"])
        return pid, st

    def test_every_trainer_end_to_end(self):
        device = "cuda" if _cuda() else "cpu"
        # 1 mlp_classify → dl_classify
        pid, st = self._train_project("mlp_classify", ["bright", "dark"], _class_samples(), {"input_size": 32, "epochs": 100}, "classes")
        asset = Asset.objects.get(pk=st["asset_id"])
        _, node = self._run_flow("dl_classify", {**st["tool_params"], "model": str(asset.id), "threshold": 0.5}, _class_samples(1)[0][0])
        self.assertEqual(node.outputs["label"], "bright")
        # 2 patch_segment → dl_segment
        from apps.vision import demo_images

        pid, st = self._train_project("patch_segment", ["scratch"], demo_images.dl_scratch_labeled(6), {"input_size": 128, "epochs": 120, "samples_per_image": 1500}, "shapes")
        asset = Asset.objects.get(pk=st["asset_id"])
        _, node = self._run_flow("dl_segment", {**st["tool_params"], "model": str(asset.id), "target_class": 1}, demo_images._scratch_plate(9, 2)[0])
        self.assertGreater(node.outputs["area"], 0)
        # 3 ai_detect → ai_detect（.pt）＋ dl_detect（ONNX）
        pid, st = self._train_project("ai_detect", ["sq"], _shape_samples(), {"epochs": 1, "imgsz": 160, "batch": 4, "mosaic": 0.0}, "shapes")
        pt = Asset.objects.get(pk=st["asset_id"])
        self.assertTrue(pt.path.endswith(".pt"))
        onnx = Asset.objects.get(pk=st["metrics"]["onnx_asset_id"])
        img = _shape_samples(1)[0][0]
        _, node = self._run_flow("ai_detect", {**st["tool_params"], "model": str(pt.id), "conf": 0.01, "device": device, "min_count": 0}, img)
        self.assertIn("count", node.outputs)
        _, node2 = self._run_flow("dl_detect", {**onnx.meta["tool_params"], "model": str(onnx.id), "conf": 0.01, "min_count": 0}, img)
        self.assertIn("count", node2.outputs)
        r = self.client.get(f"/api/vision/dl/projects/{pid}")
        self.assertEqual(r.json()["last_asset_id"], pt.id.hex)
        # 4 ai_seg → ai_segment
        pid, st = self._train_project("ai_seg", ["sq"], _shape_samples(kind="polygon"), {"epochs": 1, "imgsz": 160, "batch": 4, "mosaic": 0.0, "model": "yolo11n-seg.pt"}, "shapes")
        _, node = self._run_flow("ai_segment", {**st["tool_params"], "model": str(Asset.objects.get(pk=st["asset_id"]).id), "conf": 0.01, "min_count": 0}, img)
        mask = node.outputs["mask"]
        self.assertTrue(isinstance(mask, dict) or getattr(mask, "shape", None) == (160, 160))  # 引擎報告裡影像輸出是快取 ref
        # 5 ai_obb → ai_obb
        pid, st = self._train_project("ai_obb", ["sq"], _shape_samples(kind="polygon"), {"epochs": 1, "imgsz": 160, "batch": 4, "mosaic": 0.0}, "shapes")
        _, node = self._run_flow("ai_obb", {**st["tool_params"], "model": str(Asset.objects.get(pk=st["asset_id"]).id), "conf": 0.01, "min_count": 0}, img)
        self.assertIn("matches", node.outputs)
        # 6 ai_cls → ai_classify
        pid, st = self._train_project("ai_cls", ["bright", "dark"], _class_samples(), {"epochs": 1, "imgsz": 224, "batch": 4}, "classes")
        self.assertEqual(sorted(st["metrics"]["classes"]), ["bright", "dark"])
        _, node = self._run_flow("ai_classify", {**st["tool_params"], "model": str(Asset.objects.get(pk=st["asset_id"]).id), "threshold": 0.0}, _class_samples(1)[0][0])
        self.assertIn(node.outputs["label"], ("bright", "dark"))
        self.assertEqual(Asset.objects.filter(kind="model").count(), 2 + 2 * 4)  # 內建 2 個各 1 資產、YOLO 4 個各 2 資產

    def test_cancel_yolo_training_keeps_partial_artifacts(self):
        r = self._json("post", "/api/vision/dl/projects", {"name": f"live-cancel-{time.time_ns()}", "trainer_kind": "ai_detect", "classes": ["sq"]})
        pid = r.json()["id"]
        for i, (image, shapes) in enumerate(_shape_samples()):
            sid = self._upload(pid, image, f"c{i}.png")
            self._json("patch", f"/api/vision/dl/samples/{sid}", {"shapes": shapes})
        r = self._json("post", f"/api/vision/dl/projects/{pid}/train", {"params": {"epochs": 40, "imgsz": 160, "batch": 4, "mosaic": 0.0}, "asset_name": "cancel-me"})
        self.assertEqual(r.status_code, 202, r.content)
        deadline = time.time() + 120
        while time.time() < deadline:
            st = self.client.get("/api/vision/dl/train/status").json().get("job") or {}
            if st.get("status") not in (None, "running") or (st.get("metrics") or {}).get("epoch", 0) >= 2:
                break
            time.sleep(0.3)
        self.assertEqual(self.client.post("/api/vision/dl/train/cancel").status_code, 200)
        st = self._wait()
        # ultralytics 收到 stop 後照常驗證／存檔／匯出：狀態 done 且 stopped_early
        self.assertEqual(st["status"], "done", st.get("error"))
        self.assertTrue(st["metrics"]["stopped_early"])
        self.assertLess(st["metrics"].get("epoch", 40), 40)
        # 訓練產物先進 pending，使用者命名存檔才建資產（取消提早停也一樣有部分產物可存）
        self.assertTrue(st.get("pending"), st)
        self.assertEqual(self._json("post", "/api/vision/dl/train/save", {"name": "cancel-me"}).status_code, 200)
        self.assertTrue(Asset.objects.filter(name="cancel-me").exists())


@live
class InferenceLiveEdgeTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bus = _sample(BUS_URL)

    def test_input_variants_devices_and_concurrency(self):
        gray = cv2.cvtColor(self.bus, cv2.COLOR_BGR2GRAY)
        r = run_tool("ai_detect", gray, {"model_name": "yolo11n.pt", "conf": 0.25})
        self.assertGreaterEqual(r.outputs["count"], 4)  # 灰階輸入照樣偵測
        tiny = run_tool("ai_detect", np.zeros((24, 24, 3), np.uint8), {"model_name": "yolo11n.pt", "min_count": 0})
        self.assertEqual(tiny.outputs["count"], 0)
        big = cv2.resize(self.bus, (1620, 2160))
        rb = run_tool("ai_detect", big, {"model_name": "yolo11n.pt", "conf": 0.25, "imgsz": 960})
        self.assertGreaterEqual(rb.outputs["count"], 4)
        self.assertGreater(max(d["cx"] for d in rb.outputs["matches"]), 810)  # 座標在大圖座標系（原圖寬 810）
        cpu = run_tool("ai_detect", self.bus, {"model_name": "yolo11n.pt", "conf": 0.25, "device": "cpu"})
        self.assertIn("cpu", cpu.message)
        if _cuda():
            half = run_tool("ai_detect", self.bus, {"model_name": "yolo11n.pt", "conf": 0.25, "device": "cuda", "half": True})
            self.assertIn("cuda", half.message)
            self.assertLessEqual(abs(half.outputs["count"] - cpu.outputs["count"]), 1)
        # 同一模型 4 執行緒並行：結果一致、不炸
        results, errors = [], []

        def work():
            try:
                results.append(run_tool("ai_detect", self.bus, {"model_name": "yolo11n.pt", "conf": 0.25}).outputs["count"])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=work) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(results)), 1)

    def test_onnx_asset_on_gpu_and_dl_detect_cuda_provider(self):
        w = _weights_dir()
        onnx = os.path.join(w, "yolo11n.onnx")
        if not os.path.isfile(onnx):
            from ultralytics import YOLO

            YOLO(os.path.join(w, "yolo11n.pt")).export(format="onnx", imgsz=640, dynamic=False, verbose=False)
        r = run_tool("ai_detect", self.bus, {"model": "o", "conf": 0.25, "device": "cuda" if _cuda() else "cpu"}, assets={"o": onnx})
        self.assertGreaterEqual(r.outputs["count"], 4)
        # dl_detect（自家 ONNX 後處理）在 CUDA provider 上：結果與 torch 路徑一致（±1）
        from apps.vision.tools.builtin import dl as dl_mod

        if "CUDAExecutionProvider" in devices.available_providers():
            with dl_mod._LOCK:
                dl_mod._SESSIONS.clear()
            devices._preferred = ["CUDAExecutionProvider"]
            try:
                labels = "\n".join(str(v) for v in range(80))
                rd = run_tool("dl_detect", self.bus, {"model": "o", "labels": labels, "conf": 0.25, "iou": 0.45, "input_size": 640}, assets={"o": onnx})
                sess = dl_mod.get_session(onnx)
                self.assertIn("CUDAExecutionProvider", sess.get_providers())
                torch_count = run_tool("ai_detect", self.bus, {"model_name": "yolo11n.pt", "conf": 0.25}).outputs["count"]
                self.assertLessEqual(abs(rd.outputs["count"] - torch_count), 2)
            finally:
                devices._preferred = []
                with dl_mod._LOCK:
                    dl_mod._SESSIONS.clear()


@live
class SamLiveEdgeTests(SimpleTestCase):
    def test_negative_point_multi_box_and_model_switch(self):
        bus = _sample(BUS_URL)
        dev = "cuda" if _cuda() else "cpu"
        pos = sam.suggest_shapes(bus, [[0.5, 0.5]], device=dev)
        both = sam.suggest_shapes(bus, [[0.5, 0.5], [0.5, 0.35]], [1, 0], device=dev)
        area = lambda s: cv2.contourArea(np.asarray([[x * 810, y * 1080] for x, y in s["points"]], np.float32))  # noqa: E731
        self.assertEqual((len(pos), len(both)), (1, 1))
        self.assertNotEqual(round(area(pos[0])), round(area(both[0])))  # 負點改變遮罩
        boxes = sam.suggest_shapes(bus, boxes_norm=[[0.05, 0.35, 0.3, 0.85], [0.6, 0.3, 0.95, 0.85], [0.0, 0.0, 0.2, 0.2]], device=dev)
        self.assertGreaterEqual(len(boxes), 2)
        small = sam.suggest_shapes(bus, [[0.5, 0.5]], model_name="mobile_sam.pt", device=dev)
        self.assertTrue(sam.loaded_model().endswith("mobile_sam.pt"))
        self.assertEqual(len(small), 1)
        sam.suggest_shapes(bus, [[0.5, 0.5]], device=dev)
        self.assertTrue(sam.loaded_model().endswith(sam.default_model()))


@live
@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class AutoLabelLiveTests(TransactionTestCase):
    def _json(self, method, path, body=None):
        return getattr(self.client, method)(path, data=json.dumps(body or {}), content_type="application/json")

    def test_base_model_suggestions_per_trainer(self):
        bus, boats = _sample(BUS_URL), _sample(BOATS_URL)
        for kind, image, expect_kind in (("ai_seg", bus, "polygon"), ("ai_detect", bus, "bbox"), ("ai_obb", boats, "polygon")):
            r = self._json("post", "/api/vision/dl/projects", {"name": f"al-{kind}-{time.time_ns()}", "trainer_kind": kind, "classes": ["thing"]})
            pid = r.json()["id"]
            ok, buf = cv2.imencode(".jpg", image)
            self.client.post(f"/api/vision/dl/projects/{pid}/samples", {"files": SimpleUploadedFile("a.jpg", buf.tobytes(), content_type="image/jpeg")})
            r = self._json("post", f"/api/vision/dl/projects/{pid}/auto-label", {"params": {"suggest_conf": 0.3}})
            self.assertEqual(r.status_code, 200, (kind, r.content))
            items = r.json()["items"]
            self.assertEqual(len(items), 1, kind)
            self.assertTrue(items[0]["shapes"], kind)
            self.assertTrue(all(sh["kind"] == expect_kind and sh["label"] == "thing" for sh in items[0]["shapes"]), kind)
            self.assertLessEqual(len(items[0]["shapes"]), 20)  # 底模提案上限


@live
@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class GalleryDlTemplatesLiveTests(TransactionTestCase):
    def test_yolo_templates_run_on_sample_sources(self):
        from apps.vision.api_more import SOURCE_PLACEHOLDER, instantiate
        from apps.vision import demo
        from apps.vision.demo import BUILTIN_TEMPLATES, TEMPLATES_NEED_DL, TEMPLATES_WIRING_ONLY, seed_demo
        from apps.vision.runner import runner

        seed_demo()
        for key, name, _d, _c, builder in BUILTIN_TEMPLATES:
            if key not in TEMPLATES_NEED_DL:
                continue
            flow = Flow.objects.create(name=f"tpl-{key}", graph=validate_graph(instantiate(builder(SOURCE_PLACEHOLDER), source_id=None, samples=demo.template_samples(key))))
            try:
                statuses = []
                for _ in range(5):  # 樣本圖 5 張輪播：前 3 張 OK、後 2 張 NG
                    report = runner.run_sync(flow, timeout=120)
                    errors = {nid: nr.message for nid, nr in report.nodes.items() if nr.status == "error"}
                    self.assertFalse(errors, f"{name} 有 error 節點: {errors}")
                    statuses.append(report.status)
                if key in TEMPLATES_WIRING_ONLY:
                    continue  # 底模接線示範：合成樣本辨識不到真實類別，只要求跑得完沒有 error 節點
                self.assertEqual(statuses[:3], ["ok", "ok", "ok"], (name, statuses))
                self.assertEqual(statuses[3:], ["ng", "ng"], (name, statuses))
            finally:
                flow.delete()
