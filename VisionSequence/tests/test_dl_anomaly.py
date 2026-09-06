"""WP-06 無監督異常檢測：記憶庫／coreset／kNN 純函式、trainer 端到端（假 backbone，不需 torch）、dl_anomaly 工具、suggest、取消、
離線（不下載）、API 訓練流程。真 backbone（resnet18_l2l3.onnx）存在時另跑一次端到端（tests.test_dl_live 也有）。"""

from __future__ import annotations

import os
import shutil
import tempfile
import time

import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from apps.vision.demo_images import _scratch_plate
from apps.vision.dl import anomaly, base as dl_base
from apps.vision.dl.anomaly_trainer import AnomalyTrainer
from apps.vision.dl.base import SampleRef, TrainCancelled, TrainError
from apps.vision.tools.base import ToolError
from tests._helpers import fake_backbone, run_tool, save_png, temp_dir


def _vision(tmp: str) -> dict:
    cfg = dict(settings.VISION)
    cfg["ASSET_DIR"] = tmp
    cfg["PERSIST_RUNS"] = False
    return cfg


def good_samples(folder: str, n: int = 12, seed: int = 1000) -> list[SampleRef]:
    return [SampleRef(id=f"g{i}", label="", path=save_png(_scratch_plate(seed + i, 0)[0], folder, f"g{i}.png")) for i in range(n)]


def bad_samples(folder: str, n: int = 4, seed: int = 2000, label: str = "defect") -> list[SampleRef]:
    return [SampleRef(id=f"b{i}", label=label, path=save_png(_scratch_plate(seed + i, 1)[0], folder, f"b{i}.png")) for i in range(n)]


class PureTests(SimpleTestCase):
    def test_coreset_and_nn_distance(self):
        rng = np.random.default_rng(0)
        feats = np.concatenate([rng.normal(0, 1, (500, 16)), rng.normal(8, 1, (500, 16))]).astype(np.float32)
        idx = anomaly.coreset(feats, 0.1, seed=1)
        self.assertEqual(len(idx), 100)
        self.assertEqual(len(set(idx.tolist())), 100)
        # 兩個群都有代表
        self.assertGreater((idx < 500).sum(), 10)
        self.assertGreater((idx >= 500).sum(), 10)
        self.assertTrue(np.array_equal(anomaly.coreset(feats, 1.0), np.arange(1000)))
        bank = feats[idx]
        bank_sq = np.einsum("ij,ij->i", bank, bank)
        d = anomaly.nn_distance(feats[:10], bank, bank_sq)
        brute = np.sqrt(((feats[:10, None, :] - bank[None, :, :]) ** 2).sum(-1)).min(axis=1)
        self.assertTrue(np.allclose(d, brute, atol=1e-3))
        far = np.full((3, 16), 50.0, np.float32)
        self.assertTrue((anomaly.nn_distance(far, bank, bank_sq) > 100).all())
        # exclude：把最近的列排除後距離變大
        ex = np.zeros(len(bank), dtype=bool)
        ex[np.argmin(((bank - feats[0]) ** 2).sum(1))] = True
        self.assertGreaterEqual(anomaly.nn_distance(feats[:1], bank, bank_sq, exclude=ex)[0], d[0])
        proj = anomaly.projection(384, 128)
        self.assertEqual(proj.shape, (384, 128))
        self.assertIsNone(anomaly.projection(64, 128))
        self.assertIsNone(anomaly.projection(384, 0))

    def test_score_map_and_pack_load(self):
        d = np.zeros(16, np.float32)
        d[5] = 4.0
        smap = anomaly.score_map(d, (4, 4), (64, 64), sigma=2.0)
        self.assertEqual(smap.shape, (64, 64))
        self.assertGreater(smap[20, 20], smap[60, 60])
        folder = temp_dir()
        try:
            bank = np.random.default_rng(0).standard_normal((50, 8)).astype(np.float32)
            path = os.path.join(folder, "m.npz")
            with open(path, "wb") as fh:
                fh.write(anomaly.pack(bank, b"not-really-onnx", {"input_size": 32, "threshold": 1.5}, np.eye(8, dtype=np.float32)))
            model = anomaly.load(path)
            self.assertIs(anomaly.load(path), model)
            self.assertEqual(model["backbone"], b"not-really-onnx")
            self.assertEqual(model["meta"]["threshold"], 1.5)
            self.assertEqual(model["proj"].shape, (8, 8))
            np.savez(os.path.join(folder, "bad.npz"), foo=np.zeros(3))
            with self.assertRaises(anomaly.AnomalyError):
                anomaly.load(os.path.join(folder, "bad.npz"))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class TrainerTests(TestCase):
    """假 backbone（pooling）版：不需 torch／真權重，離線可跑。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vs-anomaly-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.override = override_settings(VISION=_vision(self.tmp))
        self.override.enable()
        self.addCleanup(self.override.disable)
        fake_backbone(anomaly.backbone_path())
        anomaly.clear_sessions()
        dl_base.register_builtins()

    def _train(self, samples, classes=("good", "defect"), **params):
        trainer = AnomalyTrainer()
        events = []
        return trainer.train(samples, list(classes), {"input_size": 320, "coreset_ratio": 0.2, "projection_dims": 0, **params}, "cpu", lambda f, s, m: events.append((f, s))), events

    def test_end_to_end_good_only_then_scratch(self):
        good = good_samples(self.tmp, 12)
        res, events = self._train(good, classes=("good",))
        self.assertEqual(res.tool_key, "dl_anomaly")
        self.assertEqual(res.weights_ext, ".npz")
        self.assertEqual(res.weights_tool_key, "dl_anomaly")
        self.assertGreater(len(res.onnx_bytes), 10)
        self.assertEqual(res.metrics["samples"], 12)
        self.assertGreater(res.metrics["bank"], 100)
        self.assertGreater(res.metrics["threshold"], 0)
        self.assertGreaterEqual(events[-1][0], 0.9)
        self.assertNotIn("auroc", res.metrics)
        path = os.path.join(self.tmp, "model.npz")
        with open(path, "wb") as fh:
            fh.write(res.weights_bytes)
        model = anomaly.load(path)
        self.assertEqual(model["meta"]["kind"], "anomaly")
        # 新良品不誤判（門檻由 leave-one-out 分數定）、刮痕抓到
        flagged = 0
        for i in range(6):
            r = run_tool("dl_anomaly", _scratch_plate(3000 + i, 0)[0], {"model": "m", "device": "cpu"}, assets={"m": path})
            flagged += r.outputs["count"] > 0
            self.assertEqual(r.outputs["score_map"].shape, (320, 320))
        self.assertLessEqual(flagged, 1)
        caught = 0
        for i in range(6):
            r = run_tool("dl_anomaly", _scratch_plate(4000 + i, 1)[0], {"model": "m", "device": "cpu"}, assets={"m": path})
            caught += r.outputs["count"] > 0 and r.branch == "defect"
        self.assertGreaterEqual(caught, 5)
        self.assertEqual(r.outputs["mask"].dtype, np.uint8)
        self.assertGreater(r.outputs["score"], r.outputs["threshold_used"])
        self.assertTrue(any(o["kind"] == "rect" for o in r.overlays))
        # 手動門檻與 ROI
        r2 = run_tool("dl_anomaly", _scratch_plate(4000, 1)[0], {"model": "m", "threshold": 1e6, "device": "cpu"}, assets={"m": path})
        self.assertEqual((r2.outputs["count"], r2.branch), (0, "ok"))
        r3 = run_tool("dl_anomaly", _scratch_plate(4000, 1)[0], {"model": "m", "roi": {"shape": "rect", "x": 20, "y": 20, "w": 200, "h": 200}, "device": "cpu"}, assets={"m": path})
        self.assertEqual(r3.outputs["score_map"].shape, (320, 320))
        self.assertEqual(int(r3.outputs["score_map"][300, 300]), 0)  # ROI 外為 0

    def test_labelled_defects_report_auroc_and_suggest(self):
        good = good_samples(self.tmp, 10)
        bad = bad_samples(self.tmp, 4)
        res, _ = self._train(good + bad)
        self.assertEqual(res.metrics["samples"], 10)
        self.assertEqual(res.metrics["other_samples"], 4)
        self.assertGreaterEqual(res.metrics["auroc"], 0.9)
        self.assertGreaterEqual(res.metrics["other_flagged"], 3)
        trainer = AnomalyTrainer()
        sug = trainer.suggest(good, bad + good_samples(self.tmp, 2, seed=5000), ["good", "defect"], {"input_size": 320, "coreset_ratio": 0.2, "projection_dims": 0})
        by_id = {s.sample_id: s for s in sug}
        self.assertEqual(len(by_id), 6)
        self.assertGreaterEqual(sum(by_id[f"b{i}"].label == "defect" for i in range(4)), 3)
        self.assertTrue(all(s.score >= 0 for s in sug))

    def test_errors_cancel_and_augment(self):
        with self.assertRaises(TrainError):
            self._train(good_samples(self.tmp, 2))
        os.remove(anomaly.backbone_path())
        with self.assertRaises(TrainError) as cm:
            self._train(good_samples(self.tmp, 5))
        self.assertIn("backbone", str(cm.exception))
        fake_backbone(anomaly.backbone_path())
        anomaly.clear_sessions()

        def cancelling(f, s, m):
            if f > 0.3:
                raise TrainCancelled()

        with self.assertRaises(TrainCancelled):
            AnomalyTrainer().train(good_samples(self.tmp, 6), ["good"], {"input_size": 320, "coreset_ratio": 0.2}, "cpu", cancelling)
        res, _ = self._train(good_samples(self.tmp, 5), classes=("good",), augment=True, augment_brightness=0.1)
        self.assertEqual(res.metrics["augmented"], 15)
        with self.assertRaises(ToolError):
            run_tool("dl_anomaly", _scratch_plate(1, 0)[0], {})
        with self.assertRaises(ToolError):
            run_tool("dl_anomaly", _scratch_plate(1, 0)[0], {"model": "x"}, assets={"x": save_png(_scratch_plate(1, 0)[0], self.tmp, "p.png")})


class LiveBackboneTests(TestCase):
    """真 backbone 存在（開發機跑過 manage.py anomaly_backbone --export）時的端到端；沒有就略過。"""

    def test_real_backbone_separates_scratches(self):
        if not anomaly.backbone_available():
            self.skipTest("resnet18_l2l3.onnx not installed")
        tmp = tempfile.mkdtemp(prefix="vs-anomaly-live-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        good = good_samples(tmp, 20)
        res = AnomalyTrainer().train(good, ["good"], {"input_size": 320, "coreset_ratio": 0.1}, "cpu", lambda f, s, m: None)
        path = os.path.join(tmp, "live.npz")
        with open(path, "wb") as fh:
            fh.write(res.weights_bytes)
        good_scores = [run_tool("dl_anomaly", _scratch_plate(3000 + i, 0)[0], {"model": "m", "device": "cpu"}, assets={"m": path}).outputs["score"] for i in range(5)]
        bad_scores = [run_tool("dl_anomaly", _scratch_plate(4000 + i, 1)[0], {"model": "m", "device": "cpu"}, assets={"m": path}).outputs["score"] for i in range(5)]
        self.assertGreater(min(bad_scores), max(good_scores))
        self.assertGreater(min(bad_scores), res.metrics["threshold"])


class TrainJobTests(TransactionTestCase):
    """經 jobs／API 走完：主產物是記憶庫 npz（tool_key dl_anomaly）、另有 backbone ONNX 資產、專案 last_asset 指向 npz。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vs-anomaly-job-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.override = override_settings(VISION=_vision(self.tmp))
        self.override.enable()
        self.addCleanup(self.override.disable)
        fake_backbone(anomaly.backbone_path())
        anomaly.clear_sessions()
        dl_base.register_builtins()

    def test_train_job_creates_npz_primary_asset(self):
        from apps.vision.dl import jobs
        from apps.vision.models import Asset, DlProject, DlSample

        project = DlProject.objects.create(name="anomaly-job", trainer_kind="anomaly", classes=["good"])
        for i, s in enumerate(good_samples(self.tmp, 6)):
            DlSample.objects.create(project=project, label="", path=s.path, sha256=f"h{i}", width=320, height=320)
        st = jobs.start(project, {"input_size": 320, "coreset_ratio": 0.2, "projection_dims": 0}, "cpu", "anomaly model")
        self.assertEqual(st["status"], "running")
        deadline = time.time() + 60
        while time.time() < deadline:
            st = jobs.status()
            if st and st["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(st["status"], "done", st)
        self.assertEqual(st["tool_key"], "dl_anomaly")
        primary = Asset.objects.get(pk=st["asset_id"])
        self.assertTrue(primary.path.endswith(".npz"))
        self.assertEqual(primary.meta["tool_key"], "dl_anomaly")
        self.assertEqual(primary.meta["format"], "npz")
        self.assertIn("onnx_asset_id", primary.meta)
        onnx_asset = Asset.objects.get(pk=primary.meta["onnx_asset_id"])
        self.assertTrue(onnx_asset.path.endswith(".onnx"))
        project.refresh_from_db()
        self.assertEqual(project.last_asset_id, primary.id.hex)
        self.assertGreater(project.last_metrics["threshold"], 0)
        # 訓練出的資產直接給工具用
        r = run_tool("dl_anomaly", _scratch_plate(4000, 1)[0], {"model": str(primary.id), "device": "cpu"}, assets={str(primary.id): primary.path})
        self.assertEqual(r.branch, "defect")
