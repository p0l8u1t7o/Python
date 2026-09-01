"""平台內深度學習教導：ONNX 匯出、MLP trainer、自動標記、API 與訓練工作。"""

from __future__ import annotations

import os
import shutil
import time
import uuid

import cv2
import numpy as np
from django.test import Client, SimpleTestCase, TransactionTestCase

from apps.vision.dl import base as dl_base, jobs
from apps.vision.dl.base import SampleRef
from apps.vision.dl.builtin import MlpClassifierTrainer
from apps.vision.models import Asset, DlProject
from tests._helpers import run_tool, temp_dir

dl_base.register_builtins()


def _sample_image(bright: bool, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base_value = 200 if bright else 40
    img = np.full((80, 80, 3), base_value, dtype=np.int16)
    img += rng.integers(-20, 20, img.shape, dtype=np.int16)
    return np.clip(img, 0, 255).astype(np.uint8)


def _write_samples(folder: str, n_per_class: int = 6) -> list[SampleRef]:
    refs = []
    for i in range(n_per_class * 2):
        bright = i % 2 == 0
        path = os.path.join(folder, f"s{i}.png")
        ok, buf = cv2.imencode(".png", _sample_image(bright, i))
        assert ok
        buf.tofile(path)
        refs.append(SampleRef(id=str(i), label="bright" if bright else "dark", path=path))
    return refs


class TrainerTests(SimpleTestCase):
    def setUp(self):
        self.folder = temp_dir()
        self.refs = _write_samples(self.folder)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_train_export_and_infer_with_dl_classify(self):
        trainer = MlpClassifierTrainer()
        stages = []
        result = trainer.train(self.refs, ["dark", "bright"], {"input_size": 32, "epochs": 120}, "cpu",
                               lambda f, s, m: stages.append(s))
        self.assertGreaterEqual(result.metrics["train_accuracy"], 0.99)
        self.assertTrue(stages)
        self.assertEqual(result.tool_key, "dl_classify")
        # 匯出的模型直接給 dl_classify 工具用（trainer 建議的參數）
        model_path = os.path.join(self.folder, "m.onnx")
        with open(model_path, "wb") as f:
            f.write(result.onnx_bytes)
        params = {**result.tool_params, "model": "m1", "threshold": 0.5}
        r = run_tool("dl_classify", image=_sample_image(True, 999), params=params, assets={"m1": model_path})
        self.assertEqual(r.outputs["label"], "bright", r.message)
        r = run_tool("dl_classify", image=_sample_image(False, 998), params=params, assets={"m1": model_path})
        self.assertEqual(r.outputs["label"], "dark", r.message)

    def test_train_insufficient_samples(self):
        with self.assertRaises(dl_base.TrainError):
            MlpClassifierTrainer().train(self.refs[:1], ["dark", "bright"], {}, "cpu", lambda *a: None)

    def test_suggest_auto_label(self):
        trainer = MlpClassifierTrainer()
        labeled, unlabeled = self.refs[:6], [SampleRef(id=r.id, label="", path=r.path) for r in self.refs[6:]]
        out = trainer.suggest(labeled, unlabeled, ["dark", "bright"], {"input_size": 32})
        self.assertEqual(len(out), len(unlabeled))
        expect = {r.id: r.label for r in self.refs[6:]}
        correct = sum(1 for s in out if s.label == expect[s.sample_id])
        self.assertGreaterEqual(correct / len(out), 0.9)
        for s in out:
            self.assertGreaterEqual(s.score, 0.0)

    def test_catalogue(self):
        items = {t["kind"]: t for t in dl_base.catalogue()}
        self.assertIn("mlp_classify", items)
        self.assertEqual(items["mlp_classify"]["label_mode"], "classes")
        self.assertTrue(items["mlp_classify"]["params"])

    def test_train_respects_split_and_augment(self):
        """指定 split：val 樣本進驗證集、test 樣本不進訓練；augment 副本只加在訓練集。"""
        for i, ref in enumerate(self.refs):
            ref.split = "val" if i < 2 else "test" if i == 2 else "train"
        result = MlpClassifierTrainer().train(
            self.refs, ["dark", "bright"], {"input_size": 32, "epochs": 60, "augment": True}, "cpu", lambda *a: None)
        self.assertEqual(result.metrics["val_samples"], 2)
        self.assertEqual(result.metrics["test_holdout"], 1)
        self.assertEqual(result.metrics["samples"], len(self.refs) - 1)  # test 不在訓練池
        self.assertEqual(result.metrics["augmented"], (len(self.refs) - 3) * 3)  # 翻轉＋亮度×2


class DlApiTests(TransactionTestCase):
    """API 與背景訓練工作（訓練執行緒寫 DB → TransactionTestCase）。"""

    def setUp(self):
        self.client = Client()

    def post(self, url, body=None, **kw):
        return self.client.post(url, data=body, content_type="application/json", **kw)

    def _create_project(self):
        r = self.post("/api/vision/dl/projects", {"name": f"p-{uuid.uuid4().hex[:6]}", "trainer_kind": "mlp_classify", "classes": ["dark", "bright"]})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def _upload(self, project_id, bright: bool, seed: int, label=""):
        ok, buf = cv2.imencode(".png", _sample_image(bright, seed))
        assert ok
        from django.core.files.uploadedfile import SimpleUploadedFile

        file = SimpleUploadedFile(f"s{seed}.png", buf.tobytes(), content_type="image/png")
        r = self.client.post(f"/api/vision/dl/projects/{project_id}/samples", {"files": file, "label": label})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["items"][0]

    def test_devices_and_trainers(self):
        r = self.client.get("/api/vision/dl/devices")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("CPUExecutionProvider", data["providers"])
        self.assertIn("cpu", data["train_devices"])
        r = self.client.get("/api/vision/dl/trainers")
        self.assertIn("mlp_classify", [t["kind"] for t in r.json()["items"]])

    def test_settings_patch(self):
        r = self.client.patch("/api/vision/dl/settings", data='{"providers": ["CPUExecutionProvider"]}', content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["preferred_providers"], ["CPUExecutionProvider"])
        r = self.client.patch("/api/vision/dl/settings", data='{"providers": ["NopeProvider"]}', content_type="application/json")
        self.assertEqual(r.status_code, 422)

    def test_label_flow_and_auto_label(self):
        project = self._create_project()
        pid = project["id"]
        ids = []
        for i in range(4):
            ids.append(self._upload(pid, i % 2 == 0, i, label="bright" if i % 2 == 0 else "dark")["id"])
        for i in range(4, 8):
            ids.append(self._upload(pid, i % 2 == 0, i)["id"])
        r = self.client.get(f"/api/vision/dl/projects/{pid}")
        counts = r.json()["counts"]
        self.assertEqual(counts["total"], 8)
        self.assertEqual(counts["unlabeled"], 4)
        # 自動標記建議 → 批次接受
        r = self.post(f"/api/vision/dl/projects/{pid}/auto-label", {"params": {"input_size": 32}})
        self.assertEqual(r.status_code, 200, r.content)
        suggestions = r.json()["items"]
        self.assertEqual(len(suggestions), 4)
        r = self.post(f"/api/vision/dl/projects/{pid}/labels", {"items": [{**s, "by": "auto"} for s in suggestions]})
        self.assertEqual(r.json()["counts"]["unlabeled"], 0)
        # 單張改標
        r = self.client.patch(f"/api/vision/dl/samples/{ids[0]}", data='{"label": "dark"}', content_type="application/json")
        self.assertEqual(r.json()["label"], "dark")
        # 樣本影像檔
        r = self.client.get(f"/api/vision/dl/samples/{ids[0]}/file")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")

    def test_train_job_end_to_end(self):
        project = self._create_project()
        pid = project["id"]
        for i in range(8):
            self._upload(pid, i % 2 == 0, 100 + i, label="bright" if i % 2 == 0 else "dark")
        r = self.post(f"/api/vision/dl/projects/{pid}/train", {"params": {"input_size": 32, "epochs": 60}, "asset_name": "test-model"})
        self.assertEqual(r.status_code, 202, r.content)
        deadline = time.time() + 30
        job = None
        while time.time() < deadline:
            job = self.client.get("/api/vision/dl/train/status").json()["job"]
            if job and job["status"] in ("done", "failed", "cancelled"):
                break
            time.sleep(0.2)
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "done", job)
        self.assertTrue(job["asset_id"])
        asset = Asset.objects.filter(pk=job["asset_id"]).first()
        self.assertIsNotNone(asset)
        self.assertEqual(asset.kind, "model")
        self.assertTrue(os.path.isfile(asset.path))
        self.assertEqual(asset.meta["tool_key"], "dl_classify")
        project_row = DlProject.objects.get(pk=pid)
        self.assertEqual(project_row.last_asset_id, job["asset_id"])
        # 訓練槽已釋放：可以再開下一個
        self.assertIsNone(jobs.status() if jobs.status() and jobs.status()["status"] == "running" else None)

    def test_train_requires_samples(self):
        project = self._create_project()
        r = self.post(f"/api/vision/dl/projects/{project['id']}/train", {"params": {"epochs": 10}})
        self.assertEqual(r.status_code, 202)
        deadline = time.time() + 10
        while time.time() < deadline:
            job = self.client.get("/api/vision/dl/train/status").json()["job"]
            if job["status"] in ("done", "failed"):
                break
            time.sleep(0.1)
        self.assertEqual(job["status"], "failed")
        self.assertIn("樣本", job["error"])


class DlDatasetApiTests(TransactionTestCase):
    """資料集管理 API：像素去重、zip 批次匯入、train/val/test 自動分割、版本凍結。"""

    def setUp(self):
        self.client = Client()

    def post(self, url, body=None, **kw):
        return self.client.post(url, data=body, content_type="application/json", **kw)

    def _create_project(self):
        r = self.post("/api/vision/dl/projects", {"name": f"p-{uuid.uuid4().hex[:6]}", "trainer_kind": "mlp_classify", "classes": ["dark", "bright"]})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def _png(self, bright: bool, seed: int) -> bytes:
        ok, buf = cv2.imencode(".png", _sample_image(bright, seed))
        assert ok
        return buf.tobytes()

    def _upload_file(self, pid, name, data, label=""):
        from django.core.files.uploadedfile import SimpleUploadedFile

        file = SimpleUploadedFile(name, data, content_type="application/octet-stream")
        r = self.client.post(f"/api/vision/dl/projects/{pid}/samples", {"files": file, "label": label})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def test_upload_dedupe_and_zip(self):
        import io
        import zipfile

        pid = self._create_project()["id"]
        png = self._png(True, 1)
        out = self._upload_file(pid, "a.png", png)
        self.assertEqual((len(out["items"]), out["duplicates"]), (1, 0))
        # 同一張再傳一次 → 去重
        out = self._upload_file(pid, "a2.png", png)
        self.assertEqual((len(out["items"]), out["duplicates"]), (0, 1))
        # zip：一張重複、一張新的、一個非影像（略過不算失敗）
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as z:
            z.writestr("dup.png", png)
            z.writestr("sub/new.png", self._png(False, 2))
            z.writestr("note.txt", b"skip me")
        out = self._upload_file(pid, "batch.zip", blob.getvalue())
        self.assertEqual((len(out["items"]), out["duplicates"], out["skipped"]), (1, 1, 0))
        r = self.client.get(f"/api/vision/dl/projects/{pid}/samples")
        self.assertEqual(len(r.json()["items"]), 2)

    def test_auto_split_filter_and_patch(self):
        pid = self._create_project()["id"]
        for i in range(10):
            bright = i % 2 == 0
            self._upload_file(pid, f"s{i}.png", self._png(bright, 10 + i), label="bright" if bright else "dark")
        r = self.post(f"/api/vision/dl/projects/{pid}/split", {"val": 0.2, "test": 0.2, "seed": 1})
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertEqual(data["train"] + data["val"] + data["test"], 10)
        self.assertEqual((data["val"], data["test"]), (2, 2))  # 每類 5 張 → 各 1 val、1 test（分層）
        r = self.client.get(f"/api/vision/dl/projects/{pid}/samples", {"split": "val"})
        items = r.json()["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual({s["label"] for s in items}, {"bright", "dark"})
        # 單張改分割與非法值
        r = self.client.patch(f"/api/vision/dl/samples/{items[0]['id']}", data='{"split": "test"}', content_type="application/json")
        self.assertEqual(r.json()["split"], "test")
        r = self.client.patch(f"/api/vision/dl/samples/{items[0]['id']}", data='{"split": "nope"}', content_type="application/json")
        self.assertEqual(r.status_code, 422)

    def test_version_freeze_and_delete(self):
        import zipfile

        pid = self._create_project()["id"]
        self._upload_file(pid, "a.png", self._png(True, 30), label="bright")
        self._upload_file(pid, "b.png", self._png(False, 31), label="dark")
        self._upload_file(pid, "c.png", self._png(True, 32))
        r = self.post(f"/api/vision/dl/projects/{pid}/versions", {"note": "第一版"})
        self.assertEqual(r.status_code, 201, r.content)
        ver = r.json()
        self.assertEqual(ver["name"], "v1")
        self.assertEqual(ver["stats"]["total"], 3)
        asset = Asset.objects.get(pk=ver["asset_id"])
        self.assertEqual(asset.kind, "dataset")
        self.assertTrue(os.path.isfile(asset.path))
        with zipfile.ZipFile(asset.path) as z:
            names = z.namelist()
        self.assertIn("manifest.json", names)
        self.assertTrue(any(n.startswith("bright/") for n in names))
        self.assertTrue(any(n.startswith("_unlabeled/") for n in names))
        r = self.client.get(f"/api/vision/dl/projects/{pid}/versions")
        self.assertEqual(len(r.json()["items"]), 1)
        path = asset.path
        r = self.client.delete(f"/api/vision/dl/versions/{ver['id']}")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(os.path.isfile(path))
        self.assertFalse(Asset.objects.filter(pk=ver["asset_id"]).exists())

    def test_sam_point_missing_deps(self):
        import importlib.util

        if importlib.util.find_spec("ultralytics"):
            self.skipTest("ultralytics 已安裝，缺件訊息不適用")
        pid = self._create_project()["id"]
        sid = self._upload_file(pid, "a.png", self._png(True, 40))["items"][0]["id"]
        r = self.post(f"/api/vision/dl/projects/{pid}/sam-point", {"sample_id": sid, "points": [[0.5, 0.5]]})
        self.assertEqual(r.status_code, 422, r.content)
        self.assertIn("ultralytics", r.json()["error"]["message"])
        # 缺 points → 參數錯誤
        r = self.post(f"/api/vision/dl/projects/{pid}/sam-point", {"sample_id": sid})
        self.assertEqual(r.status_code, 422)
